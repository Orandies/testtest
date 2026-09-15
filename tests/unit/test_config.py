"""Config: что обязательно при старте, что — только для релизного сценария.

Обязателен ровно один пункт: режим аутентификации GigaChat, без него не
работает ни один режим. SourceControl и Confluence опциональны — чат-режим
запускается без них, и требовать эти доступы у всех подряд означало бы не
пускать инженера в чат из-за того, что ему там не нужно. Проверка для
релизного сценария вынесена в отдельный метод и срабатывает перед первым
обращением к внешним системам.
"""

from __future__ import annotations

import pytest

from release_promotion_agent.config import Config
from release_promotion_agent.core.errors import ConfigError


def test_empty_env_fails_only_on_gigachat_mode() -> None:
    with pytest.raises(ConfigError) as exc_info:
        Config.load(env={})
    message = str(exc_info.value)
    assert "GIGACHAT_CERT_FILE" in message
    assert "GIGACHAT_CREDENTIALS" in message
    # Одна и та же проблема не должна попадать в список дважды.
    assert message.count("не задан режим аутентификации GigaChat") == 1


def test_release_mode_lists_exactly_what_is_missing(valid_env: dict[str, str]) -> None:
    del valid_env["CONFLUENCE_TOKEN"]
    config = Config.load(env=valid_env)
    assert config.missing_for_release() == ("CONFLUENCE_TOKEN",)
    with pytest.raises(ConfigError) as exc_info:
        config.require_release_mode()
    message = str(exc_info.value)
    assert "CONFLUENCE_TOKEN" in message
    assert "SOURCECONTROL_TOKEN" not in message


def test_release_mode_passes_on_full_environment(valid_env: dict[str, str]) -> None:
    config = Config.load(env=valid_env)
    assert config.missing_for_release() == ()
    config.require_release_mode()


def test_missing_cert_file_fails(valid_env: dict[str, str]) -> None:
    valid_env["GIGACHAT_CERT_FILE"] = valid_env["GIGACHAT_CERT_FILE"] + ".nope"
    with pytest.raises(ConfigError, match="GIGACHAT_CERT_FILE"):
        Config.load(env=valid_env)


def test_happy_path_and_allowlist(valid_env: dict[str, str]) -> None:
    config = Config.load(env=valid_env)
    assert config.allowed_users == ("engineer1", "engineer2")
    assert config.is_authorized("engineer1")
    assert not config.is_authorized("stranger")
    assert config.sourcecontrol_base_url == "https://sourcecontrol.invalid/api/v3"


def test_secrets_not_in_repr(valid_env: dict[str, str]) -> None:
    config = Config.load(env=valid_env)
    dump = repr(config) + str(config)
    assert "sc-token-value" not in dump
    assert "confluence-token-value" not in dump


def test_secret_values_collected_for_redaction(valid_env: dict[str, str]) -> None:
    config = Config.load(env=valid_env)
    assert set(config.secret_values()) == {"sc-token-value", "confluence-token-value"}


def test_secret_values_in_chat_mode(valid_env: dict[str, str]) -> None:
    """Чат-режим: токенов нет вовсе, но фильтр логов всё равно должен строиться."""
    for var in (
        "SOURCECONTROL_BASE_URL",
        "SOURCECONTROL_TOKEN",
        "CONFLUENCE_BASE_URL",
        "CONFLUENCE_TOKEN",
    ):
        del valid_env[var]
    config = Config.load(env=valid_env)
    assert config.secret_values() == ()


def test_confluence_certificate_checked_by_default(valid_env: dict[str, str]) -> None:
    """Умолчание — проверять сертификат: из Confluence приходит план установки,
    и подмена сервера означала бы подмену намерения."""
    config = Config.load(env=valid_env)
    assert config.confluence_verify_ssl is True
    assert config.confluence_tls_verify is True


def test_confluence_certificate_check_can_be_disabled(valid_env: dict[str, str]) -> None:
    valid_env["CONFLUENCE_VERIFY_SSL"] = "false"
    config = Config.load(env=valid_env)
    assert config.confluence_verify_ssl is False
    assert config.confluence_tls_verify is False


def test_confluence_ca_bundle_wins_over_flag(tmp_path, valid_env: dict[str, str]) -> None:
    """Корневой сертификат внутреннего центра — правильная замена выключению:
    проверка продолжает работать."""
    bundle = tmp_path / "internal-ca.pem"
    bundle.write_text("fake-ca")
    valid_env["CONFLUENCE_CA_BUNDLE"] = str(bundle)
    config = Config.load(env=valid_env)
    assert config.confluence_tls_verify == str(bundle)


def test_missing_ca_bundle_fails_fast(valid_env: dict[str, str]) -> None:
    valid_env["CONFLUENCE_CA_BUNDLE"] = "C:/nope/missing-root.pem"
    with pytest.raises(ConfigError, match="CONFLUENCE_CA_BUNDLE"):
        Config.load(env=valid_env)
