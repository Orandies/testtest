"""Сверка факта и намерения.

Расхождения только выносятся человеку: агент не выбирает, какой источник
считать правильным.

Категории расхождений:

- FACT_ONLY      — изменение есть в diff веток, но его нет в инструкции;
- INTENT_ONLY    — инструкция требует изменения, которого нет в diff;
- VALUE_MISMATCH — ключ есть в обоих источниках, но значения разные;
- FACT_UNPARSED  — файл из diff не разобран, сверка по ключам невозможна.

Правила сопоставления:

- позиции сопоставляются по тройке репозиторий, файл, путь ключа;
- позиция инструкции без указания ключа относится к файлу целиком и
  покрывает все изменения этого файла;
- результат детерминирован: одинаковый вход даёт одинаковый отчёт,
  включая порядок записей и stable_hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from release_promotion_agent.analyzers.branch_diff import BranchDiff, KeyChange
from release_promotion_agent.analyzers.intent import IntentChange, ReleaseIntent


class DiscrepancyKind(StrEnum):
    """Вид расхождения между фактом и намерением.

    FACT_ONLY — изменение есть в diff, но инструкция о нём молчит.
    INTENT_ONLY — инструкция требует изменения, которого в diff нет.
    VALUE_MISMATCH — ключ есть в обоих источниках, значения разные.
    FACT_UNPARSED — файл не разобран, сверка по ключам невозможна.
    """

    FACT_ONLY = "FACT_ONLY"
    INTENT_ONLY = "INTENT_ONLY"
    VALUE_MISMATCH = "VALUE_MISMATCH"
    FACT_UNPARSED = "FACT_UNPARSED"


class MatchedItem(BaseModel):
    """Позиция, где факт и намерение совпали."""

    model_config = ConfigDict(frozen=True)

    repo_key: str
    file_path: str
    key_path: str | None
    fact: KeyChange | None
    intent: IntentChange


class Discrepancy(BaseModel):
    """Одно расхождение. Решение по нему принимает человек."""

    model_config = ConfigDict(frozen=True)

    kind: DiscrepancyKind
    repo_key: str
    file_path: str
    key_path: str | None = None
    fact: KeyChange | None = None
    intent: IntentChange | None = None
    note: str | None = None


class ReconciliationReport(BaseModel):
    """Результат сверки: что совпало и что разошлось.

    Отчёт ничего не решает. Совпавшие позиции идут в план как есть,
    расхождения выносятся человеку — выбирать, какой источник считать
    правильным, агент не имеет права: diff и инструкция расходятся не
    только когда кто-то ошибся, но и когда изменение сознательно не
    попало в инструкцию.

    Порядок записей и stable_hash детерминированы: одинаковый вход даёт
    побайтово одинаковый отчёт. Это делает отчёт пригодным для тестовой
    корзины и вторым звеном цепочки аудита.
    """

    model_config = ConfigDict(frozen=True)

    release_id: str
    matched: tuple[MatchedItem, ...]
    discrepancies: tuple[Discrepancy, ...]

    def stable_hash(self) -> str:
        """Хэш отчёта для цепочки аудита."""
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile(facts: Sequence[BranchDiff], intent: ReleaseIntent) -> ReconciliationReport:
    """Сверяет diff всех репозиториев с намерением релиза."""
    matched: list[MatchedItem] = []
    discrepancies: list[Discrepancy] = []

    # Индекс изменений по тройке репозиторий, файл, ключ.
    # Неразобранные файлы собираются отдельно.
    fact_index: dict[tuple[str, str, str], KeyChange] = {}
    unparsed: list[tuple[str, str, str]] = []
    for diff in facts:
        for file_diff in diff.files:
            if file_diff.parse_error is not None:
                unparsed.append((diff.repo_key, file_diff.path, file_diff.parse_error))
                continue
            for change in file_diff.changes:
                fact_index[(diff.repo_key, file_diff.path, change.key_path)] = change

    for repo_key, file_path, note in unparsed:
        discrepancies.append(
            Discrepancy(
                kind=DiscrepancyKind.FACT_UNPARSED,
                repo_key=repo_key,
                file_path=file_path,
                key_path=None,
                note=note,
            )
        )

    consumed: set[tuple[str, str, str]] = set()

    for item in intent.changes:
        if item.key_path is None:
            # Позиция про файл целиком покрывает все изменения этого файла.
            file_facts = [key for key in fact_index if key[:2] == (item.repo_key, item.file_path)]
            if file_facts:
                consumed.update(file_facts)
                matched.append(
                    MatchedItem(
                        repo_key=item.repo_key,
                        file_path=item.file_path,
                        key_path=None,
                        fact=None,
                        intent=item,
                    )
                )
            else:
                discrepancies.append(
                    Discrepancy(
                        kind=DiscrepancyKind.INTENT_ONLY,
                        repo_key=item.repo_key,
                        file_path=item.file_path,
                        key_path=None,
                        intent=item,
                    )
                )
            continue

        # Позиция с конкретным ключом ищет точное совпадение.
        key = (item.repo_key, item.file_path, item.key_path)
        fact = fact_index.get(key)
        if fact is None:
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.INTENT_ONLY,
                    repo_key=item.repo_key,
                    file_path=item.file_path,
                    key_path=item.key_path,
                    intent=item,
                )
            )
            continue
        consumed.add(key)
        # Ключ совпал, но значения разные — это расхождение для человека.
        if item.new_value is not None and item.new_value != fact.new_value:
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.VALUE_MISMATCH,
                    repo_key=item.repo_key,
                    file_path=item.file_path,
                    key_path=item.key_path,
                    fact=fact,
                    intent=item,
                    note="значение в инструкции не совпадает со значением в релизной ветке",
                )
            )
        else:
            matched.append(
                MatchedItem(
                    repo_key=item.repo_key,
                    file_path=item.file_path,
                    key_path=item.key_path,
                    fact=fact,
                    intent=item,
                )
            )

    # Изменения, не покрытые ни одной позицией инструкции.
    for key, fact in fact_index.items():
        if key not in consumed:
            repo_key, file_path, _ = key
            discrepancies.append(
                Discrepancy(
                    kind=DiscrepancyKind.FACT_ONLY,
                    repo_key=repo_key,
                    file_path=file_path,
                    key_path=fact.key_path,
                    fact=fact,
                )
            )

    # Сортировка даёт одинаковый отчёт при одинаковом входе.
    matched.sort(key=lambda m: (m.repo_key, m.file_path, m.key_path or ""))
    discrepancies.sort(key=lambda d: (d.repo_key, d.file_path, d.key_path or "", d.kind))
    return ReconciliationReport(
        release_id=intent.release_id,
        matched=tuple(matched),
        discrepancies=tuple(discrepancies),
    )
