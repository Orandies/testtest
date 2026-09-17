"""Local Git Tool — обёртка над системной утилитой git для агента.

Предоставляет методы для выполнения всех git-команд: clone, diff, merge,
checkout, commit, push, pull и других. Использует subprocess для вызова
системной утилиты git.

Поддерживает аутентификацию через HTTPS с использованием логина и пароля
(или токена вместо пароля) из переменных окружения BITBUCKET_USERNAME и
BITBUCKET_PASSWORD.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


@dataclass
class GitResult:
    """Результат выполнения git-команды."""
    success: bool
    stdout: str
    stderr: str
    return_code: int


class LocalGitClient:
    """Работа с Git через системные команды.
    
    Поддерживает все основные git-команды: clone, diff, merge, checkout,
    commit, push, pull, branch, status, log и другие.
    
    Для аутентификации в удалённых репозиториях (Bitbucket и др.) используются
    переменные окружения:
      - BITBUCKET_USERNAME: логин пользователя
      - BITBUCKET_PASSWORD: пароль или HTTP access token
    
    При клонировании HTTPS URL автоматически преобразуется в формат с учётными
    данными для аутентификации.
    """

    def __init__(self, repo_path: str | None = None):
        """Инициализация клиента.
        
        Args:
            repo_path: Путь к локальному репозиторию. Если None, команды
                      будут выполняться в текущей директории.
        """
        self.repo_path = Path(repo_path) if repo_path else None
        
        # Загружаем учётные данные для аутентификации
        self._username = os.getenv("BITBUCKET_USERNAME")
        self._password = os.getenv("BITBUCKET_PASSWORD")
        self._has_credentials = bool(self._username and self._password)
        
    def _add_credentials_to_url(self, url: str) -> str:
        """Добавляет учётные данные в HTTPS URL для аутентификации.
        
        Args:
            url: Исходный URL репозитория.
            
        Returns:
            URL с добавленными учётными данными в формате https://username:password@host/path,
            или исходный URL, если учётные данные не настроены или URL не HTTPS.
        """
        if not self._has_credentials:
            return url
            
        try:
            parsed = urlparse(url)
            # Добавляем credentials только для HTTPS URL
            if parsed.scheme in ("https", "http"):
                # Формируем netloc с учётными данными
                netloc = f"{self._username}:{self._password}@{parsed.netloc}"
                # Собираем URL обратно
                return urlunparse((
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
        except Exception:
            # В случае ошибки парсинга возвращаем исходный URL
            pass
            
        return url
        
    def _run_git(
        self,
        *args: str,
        cwd: str | None = None,
        check: bool = False,
    ) -> GitResult:
        """Выполняет git-команду.
        
        Args:
            *args: Аргументы команды git (без 'git' в начале).
            cwd: Рабочая директория. Если None, используется repo_path или текущая.
            check: Если True, бросает исключение при ошибке.
            
        Returns:
            GitResult с результатом выполнения.
        """
        cmd = ["git"] + list(args)
        work_dir = cwd or str(self.repo_path) if self.repo_path else None
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=300,  # 5 минут таймаут
            )
            return GitResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return GitResult(
                success=False,
                stdout="",
                stderr="Превышено время выполнения команды (5 минут)",
                return_code=-1,
            )
        except FileNotFoundError:
            return GitResult(
                success=False,
                stdout="",
                stderr="Команда 'git' не найдена. Убедитесь, что git установлен.",
                return_code=-1,
            )
        except Exception as e:
            return GitResult(
                success=False,
                stdout="",
                stderr=f"Ошибка выполнения: {str(e)}",
                return_code=-1,
            )

    # ── Основные команды ──────────────────────────────────────────────

    def clone(self, url: str, target_path: str | None = None) -> GitResult:
        """Клонирует репозиторий.
        
        Args:
            url: URL репозитория (HTTPS или SSH). Для HTTPS URL автоматически
                добавляются учётные данные из BITBUCKET_USERNAME и BITBUCKET_PASSWORD.
            target_path: Путь для клонирования. Если None, используется имя из URL.
            
        Returns:
            GitResult с результатом операции.
        """
        # Добавляем учётные данные в URL для аутентификации
        auth_url = self._add_credentials_to_url(url)
        args = ["clone", auth_url]
        if target_path:
            args.append(target_path)
        return self._run_git(*args, cwd=None)

    def checkout(self, branch: str, create: bool = False) -> GitResult:
        """Переключается на ветку.
        
        Args:
            branch: Имя ветки.
            create: Если True, создаёт новую ветку (-b).
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        return self._run_git(*args)

    def create_branch(self, branch_name: str, from_ref: str = "HEAD") -> GitResult:
        """Создаёт новую ветку.
        
        Args:
            branch_name: Имя новой ветки.
            from_ref: От какой точки создать ветку (по умолчанию HEAD).
            
        Returns:
            GitResult с результатом операции.
        """
        return self._run_git("branch", branch_name, from_ref)

    def add(self, *files: str) -> GitResult:
        """Добавляет файлы в staging area.
        
        Args:
            *files: Файлы для добавления. Можно использовать "." для всех.
            
        Returns:
            GitResult с результатом операции.
        """
        return self._run_git("add", *files)

    def commit(self, message: str, files: list[str] | None = None) -> GitResult:
        """Создаёт коммит.
        
        Args:
            message: Сообщение коммита.
            files: Файлы для коммита. Если None, коммитятся все изменённые.
            
        Returns:
            GitResult с результатом операции.
        """
        if files:
            self.add(*files)
        return self._run_git("commit", "-m", message)

    def push(self, remote: str = "origin", branch: str | None = None, force: bool = False) -> GitResult:
        """Пушит изменения в удалённый репозиторий.
        
        Args:
            remote: Имя удалённого репозитория (по умолчанию origin).
            branch: Имя ветки. Если None, пушится текущая.
            force: Если True, использует --force.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["push"]
        if force:
            args.append("--force")
        args.append(remote)
        if branch:
            args.append(branch)
        return self._run_git(*args)

    def pull(self, remote: str = "origin", branch: str | None = None) -> GitResult:
        """Пуллит изменения из удалённого репозитория.
        
        Args:
            remote: Имя удалённого репозитория (по умолчанию origin).
            branch: Имя ветки. Если None, пуллится текущая.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["pull"]
        args.append(remote)
        if branch:
            args.append(branch)
        return self._run_git(*args)

    def merge(self, branch: str, no_ff: bool = False) -> GitResult:
        """Мержит ветку в текущую.
        
        Args:
            branch: Имя ветки для мержа.
            no_ff: Если True, использует --no-ff (создаёт merge commit).
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["merge"]
        if no_ff:
            args.append("--no-ff")
        args.append(branch)
        return self._run_git(*args)

    def diff(self, ref1: str = "HEAD", ref2: str | None = None, path: str | None = None) -> GitResult:
        """Показывает различия между коммитами/ветками.
        
        Args:
            ref1: Первая ссылка (коммит, ветка, тег).
            ref2: Вторая ссылка. Если None, сравнивается с рабочим деревом.
            path: Путь к файлу для фильтрации.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["diff"]
        if ref2:
            args.extend([ref1, ref2])
        else:
            args.append(ref1)
        if path:
            args.extend(["--", path])
        return self._run_git(*args)

    def status(self, short: bool = False) -> GitResult:
        """Показывает статус репозитория.
        
        Args:
            short: Если True, использует краткий формат (-s).
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["status"]
        if short:
            args.append("-s")
        return self._run_git(*args)

    def log(self, count: int = 10, oneline: bool = True, branch: str | None = None) -> GitResult:
        """Показывает историю коммитов.
        
        Args:
            count: Количество коммитов.
            oneline: Если True, использует формат --oneline.
            branch: Ветка для просмотра. Если None, текущая.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["log"]
        if oneline:
            args.append("--oneline")
        args.extend(["-n", str(count)])
        if branch:
            args.append(branch)
        return self._run_git(*args)

    def fetch(self, remote: str = "origin", branch: str | None = None) -> GitResult:
        """Фетчит изменения из удалённого репозитория.
        
        Args:
            remote: Имя удалённого репозитория.
            branch: Имя ветки. Если None, фетчатся все ветки.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["fetch"]
        args.append(remote)
        if branch:
            args.append(branch)
        return self._run_git(*args)

    def delete_branch(self, branch: str, force: bool = False) -> GitResult:
        """Удаляет локальную ветку.
        
        Args:
            branch: Имя ветки для удаления.
            force: Если True, использует -D вместо -d.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["branch"]
        args.append("-D" if force else "-d")
        args.append(branch)
        return self._run_git(*args)

    def list_branches(self, remote: bool = False) -> GitResult:
        """Список веток.
        
        Args:
            remote: Если True, показывает удалённые ветки (-r).
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["branch"]
        if remote:
            args.append("-r")
        return self._run_git(*args)

    def current_branch(self) -> GitResult:
        """Показывает текущую ветку.
        
        Returns:
            GitResult с именем текущей ветки в stdout.
        """
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def init(self, path: str | None = None) -> GitResult:
        """Инициализирует новый git-репозиторий.
        
        Args:
            path: Путь для инициализации. Если None, используется текущая директория.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["init"]
        if path:
            args.append(path)
        return self._run_git(*args, cwd=path)

    def config(self, key: str, value: str | None = None, global_scope: bool = False) -> GitResult:
        """Читает или устанавливает конфигурацию git.
        
        Args:
            key: Ключ конфигурации (например, user.name).
            value: Значение. Если None, читает текущее значение.
            global_scope: Если True, использует --global.
            
        Returns:
            GitResult с результатом операции.
        """
        args = ["config"]
        if global_scope:
            args.append("--global")
        args.append(key)
        if value is not None:
            args.append(value)
        return self._run_git(*args)

    def execute_command(self, command_str: str) -> GitResult:
        """Выполняет произвольную git-команду.
        
        Args:
            command_str: Строка команды после 'git' (например, "diff HEAD~1").
            
        Returns:
            GitResult с результатом операции.
        """
        args = command_str.split()
        return self._run_git(*args)


# Функция для создания инструмента в формате, понятном агенту
def get_git_tool_definition() -> dict[str, Any]:
    """Возвращает определение инструмента для LLM-агента."""
    return {
        "type": "function",
        "function": {
            "name": "git_execute",
            "description": "Выполняет любую git-команду в локальном репозитории. "
                          "Поддерживает: clone, diff, merge, checkout, commit, push, pull, "
                          "branch, status, log, fetch, delete и другие команды.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Git команда без префикса 'git'. "
                                      "Примеры: 'clone https://github.com/user/repo.git', "
                                      "'diff HEAD~1', 'merge feature-branch', "
                                      "'checkout -b new-branch', 'commit -m \"message\"'",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Путь к репозиторию. Если не указан, используется путь по умолчанию.",
                    },
                },
                "required": ["command"],
            },
        },
    }
