"""Управление идентификатором сессии GigaChat."""

from __future__ import annotations

import uuid

__all__ = ["SessionManager"]


class SessionManager:
    """Управляет идентификатором сессии GigaChat.

    session_id используется для кэширования токенов и
    привязки диалога к одной сессии в GigaChat.
    """

    def __init__(self) -> None:
        self._session_id = str(uuid.uuid4())

    @property
    def id(self) -> str:
        return self._session_id

    def reset(self) -> None:
        self._session_id = str(uuid.uuid4())
