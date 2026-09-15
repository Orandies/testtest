"""JSON-логи: каждая запись — валидный JSON с session_id/user_id; секреты редактируются."""

from __future__ import annotations

import json
import logging

from release_promotion_agent.core.logging_setup import (
    JsonFormatter,
    set_log_context,
    setup_logging,
)
from release_promotion_agent.core.redaction import Redactor


def _format_one(record: logging.LogRecord, formatter: JsonFormatter) -> dict[str, object]:
    return json.loads(formatter.format(record))


def _make_record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="release_promotion_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_record_is_json_with_session_and_user() -> None:
    set_log_context("sess-42", "engineer1")
    entry = _format_one(_make_record("старт анализа"), JsonFormatter())
    assert entry["message"] == "старт анализа"
    assert entry["session_id"] == "sess-42"
    assert entry["user_id"] == "engineer1"
    assert entry["level"] == "INFO"


def test_extra_fields_pass_through() -> None:
    entry = _format_one(
        _make_record("diff готов", repo_key="controller-a", event_type="DIFF_DONE"),
        JsonFormatter(),
    )
    assert entry["repo_key"] == "controller-a"
    assert entry["event_type"] == "DIFF_DONE"


def test_secret_redacted_in_output() -> None:
    formatter = JsonFormatter(Redactor(known_secrets=("super-secret-token",)))
    raw = formatter.format(_make_record("получен токен super-secret-token"))
    assert "super-secret-token" not in raw


def test_setup_logging_writes_json_lines(tmp_path) -> None:
    log_file = tmp_path / "logs" / "agent.log"
    setup_logging(level="INFO", log_file=log_file)
    set_log_context("sess-1", "engineer1")
    logging.getLogger("release_promotion_agent.smoke").info("проверка")
    for handler in logging.getLogger().handlers:
        handler.flush()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    parsed = json.loads(lines[-1])
    assert parsed["session_id"] == "sess-1"
    # прибираем за собой глобальный root-логгер
    logging.getLogger().handlers.clear()
