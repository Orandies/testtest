"""CLI для Git-агента — интерактивный режим работы с git через текстовые команды.

Использование:
    release-promotion-agent git [--repo PATH] [--dry-run]

Примеры команд:
    - "создай файл 123.yaml внутри которого написано слово 'Мяу' 10 раз в ветку 123p"
    - "переключись на ветку main"
    - "покажи статус репозитория"
"""

from __future__ import annotations

import typer
from rich.console import Console

from release_promotion_agent.agents.git_agent import GitAgent, GitOperationResult
from release_promotion_agent.config import Config
from release_promotion_agent.core.errors import ConfigError

__all__ = ["git_app"]

console = Console()

git_app = typer.Typer(
    name="git",
    help="Git-агент для выполнения операций через текстовые команды.",
)


@git_app.callback(invoke_without_command=True)
def git_callback(
    ctx: typer.Context,
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Путь к git-репозиторию (по умолчанию текущая директория)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Режим сухой проверки (команды не выполняются)",
    ),
) -> None:
    """Запустить интерактивный режим Git-агента."""
    if ctx.invoked_subcommand is not None:
        return

    run_git_agent(repo_path=repo, dry_run=dry_run)


@git_app.command("run")
def run_git_command(
    request: str = typer.Argument(..., help="Текстовая команда для выполнения"),
    repo: str | None = typer.Option(
        None,
        "--repo",
        "-r",
        help="Путь к git-репозиторию",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Режим сухой проверки",
    ),
) -> None:
    """Выполнить одну команду и выйти.

    Пример:
        release-promotion-agent git run "создай файл test.txt с hello"
    """
    result = execute_single_command(request, repo_path=repo, dry_run=dry_run)
    _print_result(result)


def run_git_agent(
    repo_path: str | None = None,
    dry_run: bool = False,
) -> None:
    """Запускает интерактивный режим Git-агента."""
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    if not config.has_llm:
        console.print(
            "[red]Не настроен GigaChat. "
            "Укажите GIGACHAT_CREDENTIALS "
            "или GIGACHAT_CERT_FILE+GIGACHAT_KEY_FILE.[/red]"
        )
        raise typer.Exit(code=1)

    agent = GitAgent(config=config, repo_path=repo_path)

    mode = "mTLS" if config.use_mtls else "token"
    repo_info = f"репозиторий: {agent._repo_path}"
    dry_run_info = " [yellow](dry-run)[/yellow]" if dry_run else ""

    console.print(f"[bold]Git Agent[/bold] (режим: {mode}, {repo_info}{dry_run_info})")
    console.print("[dim]Введите команду или 'exit' для выхода, 'status' для статуса репозитория[/dim]\n")

    while True:
        try:
            request = input("Команда > ")
        except EOFError:
            print("\nВыход.")
            break
        except KeyboardInterrupt:
            print("\nВыход.")
            break

        if not request.strip():
            continue

        if request.lower() in ("exit", "quit"):
            console.print("Выход.")
            break

        if request.lower() == "status":
            status = agent.get_repo_status()
            branch = agent.get_current_branch()
            console.print(f"\n[bold]Ветка:[/bold] {branch}")
            console.print(f"[bold]Статус:[/bold]\n{status}\n")
            continue

        if request.lower() == "branch":
            branch = agent.get_current_branch()
            console.print(f"\n[bold]Текущая ветка:[/bold] {branch}\n")
            continue

        try:
            result = agent.process(request, dry_run=dry_run)
            _print_result(result)
        except Exception as exc:
            console.print(f"[red]Ошибка: {exc}[/red]\n")


def execute_single_command(
    request: str,
    repo_path: str | None = None,
    dry_run: bool = False,
) -> GitOperationResult:
    """Выполняет одну команду без интерактивного режима."""
    try:
        config = Config.load()
    except ConfigError as exc:
        raise RuntimeError(f"Ошибка конфигурации: {exc}") from None

    if not config.has_llm:
        raise RuntimeError("Не настроен GigaChat")

    agent = GitAgent(config=config, repo_path=repo_path)
    return agent.process(request, dry_run=dry_run)


def _print_result(result: GitOperationResult) -> None:
    """Выводит результат выполнения команды."""
    if result.explanation:
        console.print(f"\n[bold]Пояснение:[/bold] {result.explanation}")

    if result.output:
        console.print(f"\n{result.output}")

    if result.success:
        if result.commands_executed:
            console.print("\n[green]✓ Все команды выполнены успешно[/green]")
        elif result.commands_planned:
            console.print("\n[blue]i Команды запланированы (dry-run)[/blue]")
    else:
        console.print(f"\n[red]✗ Ошибка: {result.error}[/red]")

    console.print()


def main() -> None:
    """Точка входа для CLI."""
    git_app()


if __name__ == "__main__":
    main()
