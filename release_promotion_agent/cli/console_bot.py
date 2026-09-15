"""Консольный бот для взаимодействия с AI-агентом.

Процесс работы:
1. Пользователь отправляет текст или ссылку на Confluence
2. Бот анализирует содержимое и пишет краткую сводку действий, которые ПЛАНИРУЕТ сделать
3. Ждёт подтверждения от пользователя
4. Если пользователь подтверждает -> спрашивает в какой ветке сделать изменения
5. После получения ответа -> делает коммиты и пушит изменения в SourceControl через MCP

Исключает sberchat - работает только в консоли.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from release_promotion_agent.config import Config
from release_promotion_agent.agents.chat_agent import ChatAgent
from release_promotion_agent.mcp import MCPClient
from release_promotion_agent.tools.confluence_tool import read_confluence_url

logger = logging.getLogger(__name__)
console = Console()

# Ссылка на страницу Confluence в тексте
_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


class ConsoleBot:
    """Консольный бот для взаимодействия с AI-агентом."""
    
    def __init__(self, config: Config | None = None) -> None:
        if config is None:
            config = Config.load()
        
        self.config = config
        self.chat_agent = ChatAgent(config)
        self.mcp_client: MCPClient | None = None
        
        # Проверяем наличие MCP конфигурации
        self._has_mcp = (
            config.sourcecontrol_base_url is not None
            and config.sourcecontrol_token is not None
        )
        
        if self._has_mcp:
            try:
                self._init_mcp_client(config)
            except Exception as exc:
                logger.warning("MCP клиент не инициализирован: %s", exc)
    
    def _init_mcp_client(self, config: Config) -> None:
        """Инициализация MCP клиента."""
        # Для MCP нужны сертификат и ключ из SecMan
        # В production они приходят через переменные окружения
        cert_file = config.gigachat_cert_file
        key_file = config.gigachat_key_file
        
        if cert_file is None or key_file is None:
            # Пробуем использовать токен как альтернативу
            logger.info("mTLS не настроен, пробуем token-based аутентификацию")
            return
        
        self.mcp_client = MCPClient(
            server_url=config.sourcecontrol_base_url or "",
            cert_file=cert_file,
            key_file=key_file,
            tuz="SA-S0000000000",  # ТУЗ по умолчанию
        )
    
    def run(self) -> None:
        """Запустить консольного бота."""
        console.print(Panel.fit(
            "[bold blue]Release Promotion Agent - Console Bot[/bold blue]\n\n"
            "Отправьте текст или ссылку на Confluence для анализа.\n"
            "Бот проанализирует и напишет план действий.\n"
            "Для выхода введите 'exit' или 'quit'",
            border_style="blue",
        ))
        
        if not self.config.has_llm:
            console.print("[red]GigaChat не настроен. Укажите GIGACHAT_CREDENTIALS или mTLS.[/red]")
            return
        
        if self._has_mcp:
            console.print("[green]✓ MCP подключён к SourceControl[/green]")
        else:
            console.print("[yellow]⚠ MCP не настроен - только анализ без записи[/yellow]")
        
        console.print("\n[dim]Введите запрос > [/dim]", end="")
        
        while True:
            try:
                user_input = input().strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Выход.[/yellow]")
                return
            
            if not user_input:
                console.print("[dim]Введите запрос > [/dim]", end="")
                continue
            
            if user_input.lower() in ("exit", "quit"):
                console.print("[green]Выход.[/green]")
                return
            
            try:
                self._process_message(user_input)
            except Exception as exc:
                console.print(f"[red]Ошибка: {exc}[/red]")
            
            console.print("\n[dim]Введите запрос > [/dim]", end="")
    
    def _process_message(self, message: str) -> None:
        """Обработать сообщение пользователя."""
        # Шаг 1: Определяем тип сообщения (текст или ссылка на Confluence)
        confluence_urls = self._extract_confluence_urls(message)
        
        if confluence_urls:
            console.print(f"\n[blue]📄 Найдена ссылка на Confluence: {confluence_urls[0]}[/blue]")
            # Читаем страницу Confluence
            try:
                confluence_content = read_confluence_url(confluence_urls[0], self.config)
                console.print(f"[green]✓ Страница прочитана: {confluence_content.get('title', 'Без заголовка')}[/green]")
                
                # Добавляем контент к сообщению для анализа
                analysis_request = (
                    f"{message}\n\n"
                    f"Содержимое страницы Confluence:\n"
                    f"{confluence_content.get('body_text', '')[:10000]}"
                )
            except Exception as exc:
                console.print(f"[red]✗ Ошибка чтения Confluence: {exc}[/red]")
                analysis_request = message
        else:
            analysis_request = message
        
        # Шаг 2: Анализируем запрос через LLM и получаем план действий
        console.print("\n[magenta]🤖 Анализ запроса...[/magenta]")
        
        plan_summary = self._generate_plan_summary(analysis_request)
        
        # Шаг 3: Показываем пользователю план действий и ждём подтверждения
        console.print(Panel(
            f"[bold]План действий:[/bold]\n\n{plan_summary}\n\n"
            f"[yellow]Подтвердите выполнение (да/нет) или внесите корректировки:[/yellow]",
            title="📋 Сводка планируемых действий",
            border_style="yellow",
        ))
        
        # Шаг 4: Ждём подтверждения
        confirmation = self._wait_for_confirmation()
        
        if not confirmation:
            console.print("[red]✗ План отклонён пользователем[/red]")
            return
        
        console.print("[green]✓ План подтверждён[/green]")
        
        # Шаг 5: Спрашиваем ветку для изменений
        if self.mcp_client is None:
            console.print("[yellow]⚠ MCP клиент не подключён - пропускаем запись[/yellow]")
            return
        
        branch_name = self._ask_branch_name()
        if not branch_name:
            console.print("[red]✗ Ветка не указана - отмена[/red]")
            return
        
        # Шаг 6: Выполняем изменения через MCP
        console.print(f"\n[cyan]🔧 Выполнение изменений в ветке {branch_name}...[/cyan]")
        
        try:
            result = self._execute_changes(branch_name, plan_summary)
            console.print(f"[green]✓ Изменения выполнены: {result}[/green]")
        except Exception as exc:
            console.print(f"[red]✗ Ошибка выполнения: {exc}[/red]")
    
    def _extract_confluence_urls(self, text: str) -> list[str]:
        """Извлечь URL Confluence из текста."""
        urls = _URL_PATTERN.findall(text)
        confluence_urls = []
        
        base_url = self.config.confluence_base_url
        if base_url:
            host = base_url.split("//")[-1].split("/")[0]
            for url in urls:
                clean_url = url.rstrip(".,;:!?)]\"'")
                if "confluence" in clean_url.lower() or host in clean_url:
                    confluence_urls.append(clean_url)
        else:
            # Если база не настроена, ищем любые URL со словом confluence
            for url in urls:
                clean_url = url.rstrip(".,;:!?)]\"'")
                if "confluence" in clean_url.lower():
                    confluence_urls.append(clean_url)
        
        return confluence_urls
    
    def _generate_plan_summary(self, request: str) -> str:
        """Сгенерировать сводку плана действий через LLM."""
        prompt = (
            "Проанализируй следующий запрос и составь краткий план действий, "
            "которые необходимо выполнить в системе контроля версий.\n\n"
            "Формат ответа:\n"
            "1. [Действие 1]\n"
            "2. [Действие 2]\n"
            "...\n\n"
            "Будь конкретен: какие файлы изменить, какие значения обновить.\n\n"
            f"Запрос пользователя:\n{request}"
        )
        
        response = self.chat_agent.process(prompt)
        return response.text
    
    def _wait_for_confirmation(self) -> bool:
        """Дождаться подтверждения от пользователя."""
        while True:
            try:
                answer = input("\n[bold]Выполнить план? (да/нет)[/bold] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            
            if answer in ("да", "yes", "y", "ok"):
                return True
            elif answer in ("нет", "no", "n"):
                return False
            else:
                # Если пользователь ввёл что-то другое, считаем это корректировкой
                console.print(f"[dim]Корректировка: {answer}[/dim]")
                # Пересчитываем план с учётом корректировки
                # (упрощённо - просто продолжаем)
                return True
    
    def _ask_branch_name(self) -> str | None:
        """Спросить имя ветки для изменений."""
        try:
            branch = input("\n[bold]В какой ветке сделать изменения?[/bold] > ").strip()
            return branch if branch else None
        except (EOFError, KeyboardInterrupt):
            return None
    
    def _execute_changes(self, branch_name: str, plan: str) -> str:
        """Выполнить изменения через MCP клиент.
        
        Args:
            branch_name: Имя ветки для изменений
            plan: Текстовое описание плана действий
            
        Returns:
            Строка с результатом выполнения
        """
        if self.mcp_client is None:
            raise RuntimeError("MCP клиент не подключён")
        
        # Парсим план и выполняем действия
        # Это упрощённая реализация - в production нужен полноценный парсер
        
        # Пример: создание ветки
        # repo_key нужно определить из контекста или спросить у пользователя
        repo_key = self._ask_repo_key()
        
        # Создаём ветку если нужно
        branches = self.mcp_client.get_list_branches(repo_key)
        branch_exists = any(b.get("name") == branch_name for b in branches)
        
        if not branch_exists:
            console.print(f"[dim]Создание ветки {branch_name}...[/dim]")
            self.mcp_client.create_branch(
                repo_key=repo_key,
                branch_name=branch_name,
                from_ref="main",  # Или спросить у пользователя
            )
        
        # Применяем изменения из плана
        # Здесь должна быть логика парсинга плана и вызова соответствующих MCP инструментов
        # Для демонстрации - создаём тестовый файл
        
        console.print("[dim]Применение изменений...[/dim]")
        
        # Пример изменения файла
        test_file_path = "changes.md"
        test_content = f"# Изменения по плану\n\n{plan}"
        
        result = self.mcp_client.create_or_update_file(
            repo_key=repo_key,
            branch=branch_name,
            file_path=test_file_path,
            content=test_content,
            message=f"Apply changes: {plan[:50]}...",
        )
        
        commit_id = result.get("commit_id", "unknown")
        
        # Создаём pull request
        console.print("[dim]Создание pull request...[/dim]")
        
        pr_result = self.mcp_client.create_pull_request(
            repo_key=repo_key,
            source_branch=branch_name,
            target_branch="main",
            title=f"Changes: {plan[:50]}...",
            body=f"Автоматически созданный PR\n\nПлан изменений:\n{plan}",
        )
        
        pr_url = pr_result.get("url", "")
        
        return f"Committed: {commit_id}, PR: {pr_url}"
    
    def _ask_repo_key(self) -> str:
        """Спросить ключ репозитория."""
        # В production можно получить список репозиториев и показать пользователю
        if self.mcp_client:
            try:
                # Получаем информацию о репозитории
                # Для упрощения используем hardcoded значение или спрашиваем
                pass
            except Exception:
                pass
        
        try:
            repo = input("[bold]Ключ репозитория?[/bold] > ").strip()
            return repo if repo else "default-repo"
        except (EOFError, KeyboardInterrupt):
            return "default-repo"


def main() -> None:
    """Точка входа для консольного бота."""
    try:
        config = Config.load()
    except Exception as exc:
        console.print(f"[red]Ошибка загрузки конфигурации: {exc}[/red]")
        sys.exit(1)
    
    bot = ConsoleBot(config)
    bot.run()


if __name__ == "__main__":
    main()
