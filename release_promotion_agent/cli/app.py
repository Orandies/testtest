"""Командный интерфейс на Typer.

Команды:

    check-config  проверка переменных окружения и секретов
    demo          прогон сценария целиком на подставных данных
    chat          интерактивный режим с GigaChat (по умолчанию)
    bot           запустить SberChat-бота (webhook + gRPC)
    git           Git-агент для выполнения операций через текстовые команды
    console       консольный бот для анализа Confluence и работы с SourceControl через MCP

Команда demo не обращается к внешним системам: SourceControl, модель и
инженер заменены заглушками из release_promotion_agent.cli.demo. Она
показывает весь путь сессии и печатает восстановленную цепочку аудита.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from release_promotion_agent.agents.chat_agent import ChatAgent
from release_promotion_agent.cli.console_bot import main as console_bot_main
from release_promotion_agent.cli.demo import run_demo_session
from release_promotion_agent.cli.git_cli import git_app
from release_promotion_agent.config import Config
from release_promotion_agent.core import audit_chain
from release_promotion_agent.core.errors import ConfigError
from release_promotion_agent.sberchat_bot.bot import create_bot

__all__ = ["app"]

app = typer.Typer(
    name="release-promotion-agent",
    help="Агент подготовки релизных изменений конфигов.",
    no_args_is_help=True,
)
_console = Console()

# Добавляем Git-агент как подкоманду
app.add_typer(git_app, name="git")


@app.command("check-config")
def check_config() -> None:
    """Проверяет конфигурацию до любого обращения к внешним системам."""
    try:
        config = Config.load()
    except ConfigError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    lines = []
    lines.append("[green]Конфигурация OK[/green]")
    git_mode = "mTLS" if config.use_mtls else "token" if config.use_token else "не настроен"
    lines.append(f"  GigaChat: {git_mode}")
    sc_status = "настроен" if config.has_sourcecontrol else "не настроен (chat-режим)"
    lines.append(f"  SourceControl: {sc_status}")
    lines.append(f"  Confluence: {'настроен' if config.has_confluence else 'не настроен'}")
    # Выключенная проверка сертификата — первое, о чём спросит информационная
    # безопасность. Она должна быть видна в выводе команды, а не только в .env.
    if config.confluence_ca_bundle is not None:
        lines.append(f"    сертификат проверяется по {config.confluence_ca_bundle}")
    elif not config.confluence_verify_ssl:
        lines.append(
            "[yellow]    ВНИМАНИЕ: проверка сертификата Confluence выключена — "
            "подмена страницы плана установки не будет замечена[/yellow]"
        )
    if config.allowed_users:
        lines.append(f"  Разрешённые пользователи: {', '.join(config.allowed_users)}")
    # Чат-режиму хватает одного GigaChat, релизному сценарию — нет.
    # Показываем, чего не хватает, до того как инженер начнёт сессию.
    missing = config.missing_for_release()
    if missing:
        lines.append(f"  Релизный сценарий: не хватает {', '.join(missing)}")
    else:
        lines.append("  Релизный сценарий: переменные на месте")
    _console.print("\n".join(lines))


@app.command("demo")
def demo(
    with_corrections: bool = typer.Option(
        False,
        "--with-corrections",
        help="Пройти оба чекпоинта с одной корректировкой на каждом.",
    ),
) -> None:
    """Прогоняет сценарий на подставных данных, без обращения к сети."""
    result = run_demo_session(with_corrections=with_corrections)

    _console.print(f"\n[bold]Сессия[/bold] {result.session_id}")
    _console.print(f"Конечное состояние: [green]{result.final_state}[/green]\n")

    pr_table = Table(title="Открытые pull request")
    pr_table.add_column("репозиторий")
    pr_table.add_column("ссылка")
    for repo_key, url in sorted(result.pr_urls.items()):
        pr_table.add_row(repo_key, url)
    _console.print(pr_table)

    decisions = Table(title="Решения человека")
    decisions.add_column("чекпоинт")
    decisions.add_column("решение")
    decisions.add_column("комментарий")
    for approval in result.store.approvals:
        decisions.add_row(approval.checkpoint, approval.decision, approval.comment or "-")
    _console.print(decisions)

    events = Table(title="Журнал аудита")
    events.add_column("событие")
    events.add_column("данные")
    for event in result.store.audit_log:
        events.add_row(event.event_type, str(event.payload))
    _console.print(events)

    for repo_key in sorted(result.pr_urls):
        chain = audit_chain.reconstruct_repo_chain(result.store.audit_pairs(), repo_key)
        status = "полная" if chain.is_complete else "неполная"
        _console.print(
            f"\n[bold]Цепочка аудита[/bold] {repo_key}: [green]{status}[/green]\n"
            f"  diff:            {chain.diff_hash}\n"
            f"  намерение:       {chain.plan_hash}\n"
            f"  промпт / ответ:  {chain.prompt_hash} / {chain.response_hash}\n"
            f"  валидация:       {chain.validation_passed}\n"
            f"  план подтвердил: {chain.plan_approved_by}\n"
            f"  pull request:    {chain.pr_url}\n"
            f"  доп. коммиты:    {list(chain.extra_commits) or '—'}\n"
            f"  PR подтвердил:   {chain.pr_approved_by}"
        )


@app.command("chat")
def chat() -> None:
    """Интерактивный режим с GigaChat.

    Поддерживает автоматическое чтение Confluence-страниц из URL.
    Для orchestrator-режима (создание PR) запустите:
      release-promotion-agent demo
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if not config.has_llm:
        _console.print(
            "[red]Не настроен GigaChat. "
            "Укажите GIGACHAT_CREDENTIALS "
            "или GIGACHAT_CERT_FILE+GIGACHAT_KEY_FILE.[/red]"
        )
        raise typer.Exit(code=1)

    agent = ChatAgent(config)
    mode = "mTLS" if config.use_mtls else "token"
    _console.print(f"[bold]Release Promotion Agent[/bold] (chat, режим: {mode})")
    if config.has_confluence:
        msg = "Confluence: настроен | "
        msg += "Введите вопрос или 'exit' для выхода."
        _console.print(f"[dim]{msg}[/dim]\n")
    else:
        msg = "Confluence: не настроен | "
        msg += "Введите вопрос или 'exit' для выхода."
        _console.print(f"[dim]{msg}[/dim]\n")

    while True:
        request = ""
        while not request:
            try:
                request = input("Запрос > ")
            except UnicodeDecodeError:
                # Терминал оставил полукодированные байты при backspace
                # Просто перезапрашиваем ввод
                continue
            except EOFError:
                print("\nВыход.")
                return
            except KeyboardInterrupt:
                print("\nВыход.")
                return
        if request.lower() in ("exit", "quit"):
            print("Выход.")
            break

        try:
            response = agent.process(request)
        except Exception as exc:
            _console.print(f"[red]Ошибка: {exc}[/red]\n")
            continue

        _console.print(f"\n{response.text}\n")
        _console.print(
            f"[dim]Токены: вход={response.usage.input_tokens}, "
            f"выход={response.usage.output_tokens}, "
            f"всего={response.usage.total_tokens}, "
            f"cache={response.usage.cache_hits}[/dim]\n"
        )


@app.command("bot")
def bot() -> None:
    """Запустить SberChat-бота (официальная SDK).

    Бот принимает сообщения из SberChat через gRPC и отвечает
    через ChatAgent (диалог с GigaChat).
    Управление осуществляется командами: /start, /chat, /status, /help.

    Для работы необходимы:
      - SBERCHAT_BOT_TOKEN   — токен бота (получить через @SberChatBot)
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if not config.has_sberchat_bot:
        _console.print(
            "[red]Не настроен SberChat бот. "
            "Укажите SBERCHAT_BOT_TOKEN.[/red]"
        )
        raise typer.Exit(code=1)

    if not config.has_llm:
        _console.print(
            "[red]Не настроен GigaChat. "
            "Укажите GIGACHAT_CREDENTIALS или GIGACHAT_CERT_FILE+GIGACHAT_KEY_FILE.[/red]"
        )
        raise typer.Exit(code=1)

    _console.print("[bold]Release Promotion Agent[/bold] (SberChat бот)")
    if config.sberchat_root_certs:
        _console.print(f"  Root certs: {config.sberchat_root_certs}")
    if config.sberchat_sandbox:
        _console.print("  Sandbox: true")
    if config.allowed_users:
        _console.print(f"  Allowed users: {', '.join(config.allowed_users)}")
    _console.print("\n[green]Бот запускается...[/green]\n")

    async def main() -> None:
        bot_instance = create_bot(config)
        try:
            await bot_instance.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            _console.print("\n[yellow]Остановка бота...[/yellow]")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _console.print("\n[yellow]Остановка бота...[/yellow]")


@app.command("console")
def console() -> None:
    """Запустить консольного бота для анализа Confluence и работы с SourceControl.
    
    Процесс работы:
    1. Пользователь отправляет текст или ссылку на Confluence
    2. Бот анализирует содержимое и пишет краткую сводку действий
    3. Ждёт подтверждения от пользователя
    4. Если подтверждено -> спрашивает ветку для изменений
    5. Делает коммиты и пушит изменения в SourceControl через MCP
    
    Для работы необходимы:
      - GIGACHAT_CREDENTIALS или mTLS сертификаты
      - SOURCECONTROL_BASE_URL и SOURCECONTROL_TOKEN (для записи)
      - CONFLUENCE_BASE_URL и CONFLUENCE_TOKEN (для чтения страниц)
    """
    console_bot_main()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
