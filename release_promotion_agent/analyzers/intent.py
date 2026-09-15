"""Намерение релиза — что должно измениться по инструкции.

Структура своя, независимая от формата исходной страницы инструкции:
разбор страницы переводит её в эти модели, поэтому остальной код от
формата документа не зависит.

Намерение — второй источник правды наравне с diff веток. Источники не
смешиваются: расхождения между ними выносятся человеку.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from release_promotion_agent.analyzers.branch_diff import ChangeKind


class IntentChange(BaseModel):
    """Одна позиция инструкции: в таком-то файле такого-то репо поменять ключ.

    key_path=None означает «файл целиком» (инструкция говорит о файле,
    не о конкретном ключе). new_value=None — значение в инструкции не названо.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    file_path: str
    key_path: str | None = None
    change_kind: ChangeKind | None = None
    new_value: Any = None
    # Исходная формулировка и ссылка на раздел — для трассировки к инструкции.
    comment: str | None = None
    source_ref: str | None = None


class ReleaseIntent(BaseModel):
    """Всё намерение релиза, нормализованное из Deploy Plan."""

    model_config = ConfigDict(frozen=True)

    release_id: str
    changes: tuple[IntentChange, ...]

    def stable_hash(self) -> str:
        """plan_hash для аудит-цепочки: sha256 канонического JSON."""
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
