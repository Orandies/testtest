"""Командный интерфейс: проверка конфигурации и демонстрационный прогон."""

from __future__ import annotations

from typer.testing import CliRunner

from release_promotion_agent.cli.app import app

runner = CliRunner()

# Переменные релизного сценария. При старте они не обязательны — check-config
# показывает их как «чего не хватает», а не как ошибку.
RELEASE_VARS = (
    "SOURCECONTROL_BASE_URL",
    "SOURCECONTROL_TOKEN",
    "CONFLUENCE_BASE_URL",
    "CONFLUENCE_TOKEN",
    "AGENT_ALLOWED_USERS",
    "AKK_ALLOWED_USERS",
)

# Без одного из этих режимов не стартует ничто — это единственная жёсткая
# проверка при загрузке конфигурации.
GIGACHAT_VARS = (
    "GIGACHAT_CERT_FILE",
    "GIGACHAT_KEY_FILE",
    "GIGACHAT_CREDENTIALS",
)


def test_check_config_fails_without_gigachat_mode(monkeypatch) -> None:
    for var in RELEASE_VARS + GIGACHAT_VARS:
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 1
    assert "GigaChat" in result.output


def test_check_config_passes_on_full_environment(monkeypatch, valid_env: dict[str, str]) -> None:
    for key, value in valid_env.items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    assert "OK" in result.output
    assert "не хватает" not in result.output


def test_check_config_names_what_release_mode_lacks(monkeypatch, valid_env: dict[str, str]) -> None:
    """Чат-режим запускается, но инженер должен видеть, чего нет для релиза."""
    del valid_env["SOURCECONTROL_TOKEN"]
    for var in RELEASE_VARS + GIGACHAT_VARS:
        monkeypatch.delenv(var, raising=False)
    for key, value in valid_env.items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    assert "SOURCECONTROL_TOKEN" in result.output


def test_demo_runs_without_network() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "ALL_DONE" in result.output
    assert "pulls" in result.output


def test_demo_with_corrections_passes_both_loops() -> None:
    result = runner.invoke(app, ["demo", "--with-corrections"])
    assert result.exit_code == 0
    assert "ALL_DONE" in result.output
    assert "correction" in result.output
