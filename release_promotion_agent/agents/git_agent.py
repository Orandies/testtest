"""Git CLI Agent — агент для выполнения git-операций по текстовым командам.

Позволяет создавать ветки, файлы, делать коммиты в локальный git-репозиторий
на основе естественного языка (например: "создай файл 123.yaml с 'Мяу' в ветке 123p").
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from release_promotion_agent.config import Config
from release_promotion_agent.llm import ConversationManager, GigaChatClient, SessionManager
from release_promotion_agent.models.chat_response import ChatResponse

__all__ = ["GitAgent"]


GIT_SYSTEM_PROMPT = """Ты — ассистент для работы с Git-репозиторием через командную строку.
Твоя задача — понимать запросы пользователя на естественном языке и преобразовывать их в последовательность git-команд.

Доступные операции:
1. Создание ветки: "git checkout -b <branch_name>" или "git branch <branch_name>"
2. Переключение ветки: "git checkout <branch_name>"
3. Создание файла: записать содержимое в файл
4. Добавление файлов: "git add <file_path>"
5. Коммит: "git commit -m '<message>'"
6. Проверка статуса: "git status"
7. Проверка текущей ветки: "git branch --show-current"
8. Список файлов: "ls" или "find"

Формат ответа:
Всегда отвечай в формате JSON с полями:
{
    "commands": [
        {"type": "git", "command": "git checkout -b feature"},
        {"type": "file", "path": "file.txt", "content": "содержимое"},
        {"type": "git", "command": "git add file.txt"},
        {"type": "git", "command": "git commit -m 'сообщение'"}
    ],
    "explanation": "краткое пояснение что будет сделано"
}

Примеры:
Запрос: "создай файл test.yaml с содержимым hello в ветке test-branch"
Ответ: {
    "commands": [
        {"type": "git", "command": "git checkout -b test-branch"},
        {"type": "file", "path": "test.yaml", "content": "hello"},
        {"type": "git", "command": "git add test.yaml"},
        {"type": "git", "command": "git commit -m 'создан test.yaml'"}
    ],
    "explanation": "Создана ветка test-branch, файл test.yaml с содержимым 'hello' и закоммичен"
}

Запрос: "переключись на ветку main"
Ответ: {
    "commands": [
        {"type": "git", "command": "git checkout main"}
    ],
    "explanation": "Переключение на ветку main"
}

Важно:
- Если ветка не существует, создавай её с помощью "git checkout -b"
- Все файлы создаются относительно корня репозитория
- Для коммита всегда используй осмысленное сообщение
- Не выполняй опасные операции (force push, reset и т.д.)
"""


class GitAgent:
    """Агент для выполнения git-операций по текстовым командам.

    Принимает запросы на естественном языке, использует LLM для извлечения
    команд, и выполняет их в локальном git-репозитории.
    """

    def __init__(
        self,
        config: Config | None = None,
        repo_path: str | Path | None = None,
    ) -> None:
        if config is None:
            config = Config.load()
        self._config = config
        self._client = GigaChatClient(config)
        self._conversation = ConversationManager(system_prompt=GIT_SYSTEM_PROMPT)
        self._session = SessionManager()
        self._repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()

    def process(self, request: str, dry_run: bool = False) -> GitOperationResult:
        """Обработать запрос и выполнить git-операции.

        Args:
            request: Текст запроса пользователя на естественном языке.
            dry_run: Если True, только показать команды без выполнения.

        Returns:
            GitOperationResult с результатами выполнения.
        """
        # Добавляем запрос в историю
        self._conversation.add_user(request)

        # Формируем сообщения для LLM
        messages = list(self._conversation.get_messages())

        try:
            response = self._client.ask(messages, session_id=self._session.id)
        except Exception as exc:
            return GitOperationResult(
                success=False,
                error=f"Ошибка LLM: {exc}",
                commands_executed=[],
                output="",
            )

        # Обновляем историю
        self._conversation.add_ai(response.text)

        # Парсим ответ LLM
        parsed = self._parse_llm_response(response.text)
        if not parsed:
            return GitOperationResult(
                success=False,
                error="Не удалось распарсить ответ LLM",
                commands_executed=[],
                output=response.text,
            )

        commands = parsed.get("commands", [])
        explanation = parsed.get("explanation", "")

        if dry_run:
            return GitOperationResult(
                success=True,
                explanation=explanation,
                commands_planned=commands,
                output="Dry run: команды не выполнены",
            )

        # Выполняем команды
        executed_commands = []
        output_lines = []
        for cmd_info in commands:
            cmd_type = cmd_info.get("type")
            if cmd_type == "git":
                cmd = cmd_info.get("command", "")
                result = self._run_git_command(cmd)
                executed_commands.append({"command": cmd, **result})
                if result["success"]:
                    output_lines.append(f"✓ {cmd}")
                else:
                    output_lines.append(f"✗ {cmd}: {result.get('error', '')}")
                    return GitOperationResult(
                        success=False,
                        explanation=explanation,
                        commands_executed=executed_commands,
                        output="\n".join(output_lines),
                        error=f"Команда '{cmd}' не выполнилась: {result.get('error')}",
                    )
            elif cmd_type == "file":
                path = cmd_info.get("path")
                content = cmd_info.get("content", "")
                result = self._create_file(path, content)
                executed_commands.append({"command": f"create {path}", **result})
                if result["success"]:
                    output_lines.append(f"✓ создан файл {path}")
                else:
                    output_lines.append(f"✗ создание {path}: {result.get('error', '')}")
                    return GitOperationResult(
                        success=False,
                        explanation=explanation,
                        commands_executed=executed_commands,
                        output="\n".join(output_lines),
                        error=f"Не удалось создать файл {path}: {result.get('error')}",
                    )

        return GitOperationResult(
            success=True,
            explanation=explanation,
            commands_executed=executed_commands,
            output="\n".join(output_lines),
        )

    def _parse_llm_response(self, text: str) -> dict[str, Any] | None:
        """Парсит JSON-ответ от LLM."""
        import json
        import re

        # Ищем JSON в тексте (может быть обёрнут в markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Пробуем найти JSON без markdown
            json_match = re.search(r"({.*})", text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                return None

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    def _run_git_command(self, command: str) -> dict[str, Any]:
        """Выполняет git-команду в репозитории."""
        try:
            result = subprocess.run(
                command.split(),
                cwd=self._repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _create_file(self, path: str, content: str) -> dict[str, Any]:
        """Создаёт файл с содержимым в репозитории."""
        try:
            file_path = self._repo_path / path
            # Создаём родительские директории если нужно
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(file_path)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_repo_status(self) -> str:
        """Возвращает статус репозитория."""
        result = self._run_git_command("git status")
        if result["success"]:
            return result["stdout"]
        return f"Ошибка: {result.get('stderr', result.get('error', 'неизвестно'))}"

    def get_current_branch(self) -> str:
        """Возвращает текущую ветку."""
        result = self._run_git_command("git branch --show-current")
        if result["success"]:
            return result["stdout"] or "detached HEAD"
        return "unknown"


class GitOperationResult:
    """Результат выполнения git-операций."""

    def __init__(
        self,
        success: bool,
        explanation: str = "",
        commands_executed: list[dict[str, Any]] | None = None,
        commands_planned: list[dict[str, Any]] | None = None,
        output: str = "",
        error: str = "",
    ) -> None:
        self.success = success
        self.explanation = explanation
        self.commands_executed = commands_executed or []
        self.commands_planned = commands_planned or []
        self.output = output
        self.error = error

    def __str__(self) -> str:
        lines = []
        if self.explanation:
            lines.append(f"Пояснение: {self.explanation}")
        if self.output:
            lines.append(f"Результат:\n{self.output}")
        if self.error:
            lines.append(f"Ошибка: {self.error}")
        return "\n".join(lines)
