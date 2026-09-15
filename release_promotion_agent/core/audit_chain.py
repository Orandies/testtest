"""Цепочка аудита одной сессии.

Звенья идут в порядке: хэш diff веток, хэш намерения, хэши промпта и ответа
модели, результат валидации, кто подтвердил план, ссылка на pull request,
дополнительные коммиты, кто подтвердил PR.

Модуль знает имена событий и умеет восстанавливать цепочку по одному
репозиторию из последовательности событий сессии.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from release_promotion_agent.core.redaction import Redactor

# Имена событий: строки не дублируются по остальному коду.
EVENT_SESSION_STARTED = "SESSION_STARTED"
EVENT_DIFF_ANALYZED = "DIFF_ANALYZED"
EVENT_INTENT_READ = "INTENT_READ"
EVENT_RECONCILIATION_DONE = "RECONCILIATION_DONE"
EVENT_PLAN_PROPOSED = "PLAN_PROPOSED"
EVENT_VALIDATION_RESULT = "VALIDATION_RESULT"
EVENT_PLAN_DECISION = "PLAN_DECISION"
EVENT_PLAN_APPROVED = "PLAN_APPROVED"
EVENT_BRANCH_CREATED = "BRANCH_CREATED"
EVENT_COMMIT_CREATED = "COMMIT_CREATED"
EVENT_PR_OPENED = "PR_OPENED"
EVENT_PR_EXTRA_COMMIT = "PR_EXTRA_COMMIT"
EVENT_PR_APPROVED = "PR_APPROVED"
EVENT_SESSION_COMPLETED = "SESSION_COMPLETED"


def redact_payload(redactor: Redactor, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Вырезает секреты из строковых значений перед записью события."""

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return redactor.redact(value)
        if isinstance(value, Mapping):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [scrub(item) for item in value]
        return value

    return {key: scrub(value) for key, value in payload.items()}


class RepoAuditChain(BaseModel):
    """Цепочка аудита по одному репозиторию, собранная из событий сессии.

    Отвечает на вопрос «на каком основании изменился этот конфиг»: от хэша
    diff веток и хэша намерения через промпт и ответ модели к результату
    проверки, подтверждению человека и ссылке на pull request.

    Каждое поле — звено. Пустое звено означает, что события не было:
    цепочка не достраивается догадками, а показывает ровно то, что
    записано. Полнота проверяется свойством is_complete.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    diff_hash: str | None = None
    plan_hash: str | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    validation_passed: bool | None = None
    plan_approved_by: str | None = None
    pr_url: str | None = None
    extra_commits: tuple[str, ...] = ()
    pr_approved_by: str | None = None

    @property
    def is_complete(self) -> bool:
        """Все обязательные звенья на месте. Дополнительные коммиты
        необязательны: их может не быть, если правок по ревью не было."""
        return all(
            value is not None
            for value in (
                self.diff_hash,
                self.plan_hash,
                self.prompt_hash,
                self.response_hash,
                self.validation_passed,
                self.plan_approved_by,
                self.pr_url,
                self.pr_approved_by,
            )
        )


def reconstruct_repo_chain(
    events: Iterable[tuple[str, Mapping[str, Any]]], repo_key: str
) -> RepoAuditChain:
    """Собирает цепочку по репозиторию из событий сессии."""
    diff_hash = plan_hash = prompt_hash = response_hash = None
    validation_passed: bool | None = None
    plan_approved_by = pr_url = pr_approved_by = None
    extra_commits: list[str] = []

    # События уровня сессии общие для всех репозиториев, события с repo_key
    # относятся только к своему.
    for event_type, payload in events:
        event_repo = payload.get("repo_key")
        if event_type == EVENT_DIFF_ANALYZED and event_repo == repo_key:
            diff_hash = payload.get("diff_hash")
        elif event_type == EVENT_INTENT_READ:
            plan_hash = payload.get("plan_hash")
        elif event_type == EVENT_PLAN_PROPOSED:
            prompt_hash = payload.get("prompt_hash")
            response_hash = payload.get("response_hash")
        elif event_type == EVENT_VALIDATION_RESULT:
            validation_passed = bool(payload.get("valid"))
        elif event_type == EVENT_PLAN_APPROVED:
            plan_approved_by = payload.get("approved_by")
        elif event_type == EVENT_PR_OPENED and event_repo == repo_key:
            pr_url = payload.get("pr_url")
        elif event_type == EVENT_PR_EXTRA_COMMIT and event_repo == repo_key:
            commit_id = payload.get("commit_id")
            if commit_id is not None:
                extra_commits.append(str(commit_id))
        elif event_type == EVENT_PR_APPROVED and event_repo == repo_key:
            pr_approved_by = payload.get("approved_by")

    return RepoAuditChain(
        repo_key=repo_key,
        diff_hash=diff_hash,
        plan_hash=plan_hash,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        validation_passed=validation_passed,
        plan_approved_by=plan_approved_by,
        pr_url=pr_url,
        extra_commits=tuple(extra_commits),
        pr_approved_by=pr_approved_by,
    )
