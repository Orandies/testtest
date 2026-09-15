"""Хранилище состояния сессии в памяти процесса.

Держит всё, что накапливается за один запуск агента: состояние FSM,
позиции плана, решения человека на чекпоинтах, вызовы модели и события
аудита. Живёт столько же, сколько процесс.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    """Единый формат времени во всех записях: UTC ISO-8601."""
    return datetime.now(UTC).isoformat()


class RepoTask(BaseModel):
    """Состояние одного репозитория в цикле по репозиториям.

    На репозиторий приходится ровно одна такая запись за сессию, и она
    обновляется на месте. Отсюда гарантия «не более одного pull request
    на репозиторий»: если запись уже содержит ссылку на PR, повторный
    заход её увидит и создавать второй не станет.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    repo_state: str
    branch_name: str | None = None
    pr_url: str | None = None
    updated_at: str


class PlanItem(BaseModel):
    """Позиция плана: совпадение или расхождение между фактом и намерением.

    source: FACT — только в diff веток, INTENT — только в инструкции,
    BOTH — есть в обоих источниках.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    file_path: str
    key_path: str | None
    change_kind: str
    source: str
    status: str


class Approval(BaseModel):
    """Решение инженера на чекпоинте: PLAN — цикл 1, PR — цикл 2."""

    model_config = ConfigDict(frozen=True)

    checkpoint: str
    decision: str
    repo_key: str | None = None
    comment: str | None = None
    created_at: str


class LlmCall(BaseModel):
    """Вызов модели: хэши промпта и ответа, номер попытки, итог валидации."""

    model_config = ConfigDict(frozen=True)

    purpose: str
    prompt_hash: str
    response_hash: str | None
    attempts: int
    validation_result: str | None
    created_at: str


class AuditEvent(BaseModel):
    """Событие аудита. payload приходит уже после редакции секретов."""

    model_config = ConfigDict(frozen=True)

    event_type: str
    payload: dict[str, Any]
    created_at: str


class SessionStore(BaseModel):
    """Всё состояние одной сессии в одном объекте.

    Держит положение автомата, задачи по репозиториям, позиции плана,
    решения человека на обоих чекпоинтах, вызовы модели и журнал аудита.
    Живёт столько же, сколько процесс: постоянного хранилища пока нет,
    перезапуск сессию не сохраняет.

    Передаётся оркестратору явным параметром, а не берётся откуда-то
    сверху. Все изменения проходят через методы этого класса, и каждое
    из них ставит отметку времени — поэтому журнал не расходится с
    состоянием и по нему восстанавливается ход сессии.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    user_id: str
    fsm_state: str
    release_id: str | None = None
    repo_tasks: dict[str, RepoTask] = Field(default_factory=dict)
    plan_items: list[PlanItem] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    llm_calls: list[LlmCall] = Field(default_factory=list)
    audit_log: list[AuditEvent] = Field(default_factory=list)

    def set_fsm_state(self, state: str) -> None:
        self.fsm_state = state

    def upsert_repo_task(
        self,
        repo_key: str,
        repo_state: str,
        branch_name: str | None = None,
        pr_url: str | None = None,
    ) -> RepoTask:
        """Обновляет запись репозитория. Переданный None не затирает уже
        сохранённые branch_name и pr_url — так на репо остаётся одна запись
        и, как следствие, не больше одного PR за сессию.
        """
        previous = self.repo_tasks.get(repo_key)
        task = RepoTask(
            repo_key=repo_key,
            repo_state=repo_state,
            branch_name=branch_name or (previous.branch_name if previous else None),
            pr_url=pr_url or (previous.pr_url if previous else None),
            updated_at=utc_now_iso(),
        )
        self.repo_tasks[repo_key] = task
        return task

    def add_plan_items(self, items: list[PlanItem]) -> None:
        self.plan_items.extend(items)

    def add_approval(
        self,
        checkpoint: str,
        decision: str,
        repo_key: str | None = None,
        comment: str | None = None,
    ) -> None:
        self.approvals.append(
            Approval(
                checkpoint=checkpoint,
                decision=decision,
                repo_key=repo_key,
                comment=comment,
                created_at=utc_now_iso(),
            )
        )

    def record_llm_call(
        self,
        purpose: str,
        prompt_hash: str,
        response_hash: str | None = None,
        attempts: int = 1,
        validation_result: str | None = None,
    ) -> None:
        self.llm_calls.append(
            LlmCall(
                purpose=purpose,
                prompt_hash=prompt_hash,
                response_hash=response_hash,
                attempts=attempts,
                validation_result=validation_result,
                created_at=utc_now_iso(),
            )
        )

    def append_audit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.audit_log.append(
            AuditEvent(
                event_type=event_type,
                payload=payload or {},
                created_at=utc_now_iso(),
            )
        )

    def audit_pairs(self) -> list[tuple[str, dict[str, Any]]]:
        """События в виде пар для восстановления цепочки аудита."""
        return [(event.event_type, event.payload) for event in self.audit_log]
