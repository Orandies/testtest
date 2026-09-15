"""Общие fixtures. Внешних сетевых вызовов в тестах НЕТ — только моки и файлы."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def valid_env(tmp_path: Path) -> dict[str, str]:
    """Минимально полное окружение для Config.load() — без единого реального секрета."""
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("fake-cert")
    key.write_text("fake-key")
    return {
        "SOURCECONTROL_BASE_URL": "https://sourcecontrol.invalid/api/v3/",
        "SOURCECONTROL_TOKEN": "sc-token-value",
        "CONFLUENCE_BASE_URL": "https://confluence.invalid",
        "CONFLUENCE_TOKEN": "confluence-token-value",
        "GIGACHAT_CERT_FILE": str(cert),
        "GIGACHAT_KEY_FILE": str(key),
        "AGENT_ALLOWED_USERS": "engineer1, engineer2",
    }
