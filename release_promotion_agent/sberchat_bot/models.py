"""Модели данных SberChat API.

Представляют входящие/исходящие сообщения, пользователей и сущности,
используемые webhook-обработчиком и gRPC-клиентом.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

__all__ = [
    "User",
    "Message",
    "IncomingMessage",
    "OutgoingMessage",
    "MessageType",
    "Update",
    "EventType",
    "BotState",
]


class MessageType(StrEnum):
    """Тип контента сообщения."""

    TEXT = "text"
    DOCUMENT = "document"
    IMAGE = "image"
    LOCATION = "location"
    COMMAND = "command"


class EventType(StrEnum):
    """Тип события, пришедшего через webhook."""

    MESSAGE_NEW = "message_new"
    MESSAGE_REPLY = "message_reply"
    MESSAGE_EDIT = "message_edit"


class User(BaseModel):
    """Участник чата в SberChat.

    Адресуется user_id — уникальным идентификатором в системе SberChat.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    @property
    def name(self) -> str:
        """Человекочитаемое имя для логов и вывода.

        Порядок: display_name > first_name last_name > user_id.
        """
        if self.display_name:
            return self.display_name
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or self.user_id


class Message(BaseModel):
    """Базовое сообщение (общая часть для Incoming и Outgoing).

    text — полезная нагрузка (текст или описание документа/изображения).
    """

    model_config = ConfigDict(frozen=True)

    text: str
    attachments: list[str] | None = None


class IncomingMessage(Message):
    """Входящее сообщение от пользователя.

    Приходит в webhook: содержит идентификатор автора, времени и тип.
    """

    model_config = ConfigDict(frozen=True)

    event_type: EventType
    message_id: str
    user: User
    timestamp: datetime
    parent_id: str | None = None

    @property
    def is_command(self) -> bool:
        """Сообщение является командой, если текст начинается с '/'."""
        return self.text.startswith("/")

    @property
    def command_name(self) -> str | None:
        """Извлечь имя команды из текста, если это команда.

        Пример: '/start' -> 'start', '/start @bot' -> 'start'.
        """
        if not self.is_command:
            return None
        return self.text.lstrip("/").split()[0] or None


class OutgoingMessage(Message):
    """Исходящее сообщение, отправляемое пользователю."""

    model_config = ConfigDict(frozen=True)

    parent_message_id: str


class Update(BaseModel):
    """Полное событие обновления из SberChat.

    Оборачивает IncomingMessage и дополняет метаданными.
    """

    model_config = ConfigDict(frozen=True)

    update: IncomingMessage
    update_id: str = ""


class BotState(StrEnum):
    """Состояния жизненного цикла бота."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    ERROR = "error"
