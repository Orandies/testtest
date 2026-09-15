"""Логирование в формате JSON.

В каждой записи присутствуют идентификаторы сессии и пользователя, поэтому
логи пригодны для загрузки в систему сбора логов как есть.

Контекст сессии задаётся через set_log_context: все последующие записи
помечаются автоматически, глобальное изменяемое состояние не используется.
Файловый обработчик ротирует логи по размеру.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from release_promotion_agent.core.redaction import Redactor

_session_id_var: ContextVar[str] = ContextVar("session_id", default="-")
_user_id_var: ContextVar[str] = ContextVar("user_id", default="-")

# Служебные атрибуты записи лога, которые не попадают в JSON.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def set_log_context(session_id: str, user_id: str) -> None:
    """Привязывает последующие записи лога к сессии и пользователю."""
    _session_id_var.set(session_id)
    _user_id_var.set(user_id)


class JsonFormatter(logging.Formatter):
    """Превращает запись лога в одну строку JSON, очищенную от секретов.

    Обязательные поля есть в каждой записи: время, уровень, источник,
    текст, идентификаторы сессии и пользователя. Идентификаторы берутся
    из самой записи, а если их там нет — из контекста текущей сессии,
    заданного через set_log_context. Поэтому проставлять их руками при
    каждом вызове не нужно, и они не теряются.

    Всё, что передали в вызов дополнительными полями, попадает в тот же
    объект JSON. Готовая строка перед возвратом проходит через фильтр
    секретов: это последняя точка, где их ещё можно вырезать.
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        # Идентификаторы берутся из самой записи, а если их там нет —
        # из контекста текущей сессии.
        entry: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": getattr(record, "session_id", None) or _session_id_var.get(),
            "user_id": getattr(record, "user_id", None) or _user_id_var.get(),
        }
        # Дополнительные поля вызова попадают в JSON как есть.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        # Очистка выполняется последней, по уже собранной строке.
        return self._redactor.redact(json.dumps(entry, ensure_ascii=False, default=str))


def setup_logging(
    level: str = "INFO",
    redactor: Redactor | None = None,
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
) -> None:
    """Настраивает корневой логгер: вывод в stderr и, если задан путь, в файл
    с ротацией по размеру."""
    formatter = JsonFormatter(redactor)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
        )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
