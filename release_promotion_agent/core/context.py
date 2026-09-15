"""Контекст сессии: кто запустил, какой релиз, с какими параметрами.

Передаётся явным параметром, глобальное состояние не используется.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionContext(BaseModel):
    """Кто запустил сессию, какой релиз и с какими параметрами.

    Объект неизменяемый и передаётся явным параметром сверху вниз — от
    команды до модуля, который делает запрос. Глобального состояния в
    агенте нет: это то, что позже позволит вести несколько сессий в одном
    процессе, ничего не переписывая.

    session_id и user_id попадают в каждую запись журнала, поэтому по
    логам видно, чья это была сессия, даже когда их идёт несколько.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    user_id: str
    release_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def new(
        cls,
        user_id: str,
        release_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> SessionContext:
        return cls(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            release_id=release_id,
            params=params or {},
        )
