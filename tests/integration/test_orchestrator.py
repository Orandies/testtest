"""Сценарий целиком: от параметров до открытого pull request.

Проверяются оба чекпоинта, циклы корректировок, полнота цепочки аудита и
условия остановки при неисправимых ответах модели.
"""

from __future__ import annotations

import hashlib

import pytest

from release_promotion_agent.agents.release_agent import (
    Decision,
    Orchestrator,
    PlannedFileChange,
    ProposedPlan,
    RepoParams,
    SessionParams,
)
from release_promotion_agent.analyzers.intent import IntentChange, ReleaseIntent
from release_promotion_agent.cli.demo import InMemorySourceControl
from release_promotion_agent.core import audit_chain as audit_chain
from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import EngineUnavailableError, EscalationError
from release_promotion_agent.core.fsm import SessionState
from release_promotion_agent.tools.models import RepoRef
from release_promotion_agent.validation.models import Env

REF = RepoRef(tenant="demo-tenant", project="DEMO", repo="configs-core")
REPO_KEY = REF.key
CONFIG_PATH = "agents/PSI.yaml"

# Кандидат в границах плана: добавлен только server.retries.
GOOD_CANDIDATE = (
    "server:\n  port: 8080\n  timeout-seconds: 60\n  retries: 5\nlogging:\n  level: INFO\n"
)
# Кандидат за границами плана: тронут logging.level.
OUT_OF_SCOPE_CANDIDATE = "server:\n  port: 8080\n  timeout-seconds: 60\nlogging:\n  level: DEBUG\n"


def _plan(candidate: str = GOOD_CANDIDATE) -> ProposedPlan:
    return ProposedPlan(
        release_id="R-1",
        changes=(
            PlannedFileChange(
                repo_key=REPO_KEY,
                env=Env.PSI,
                file_path=CONFIG_PATH,
                candidate_content=candidate,
                allowed_key_paths=("server.retries",),
                summary="добавить server.retries",
            ),
        ),
        summary_text="план: добавить retries",
        prompt_hash=hashlib.sha256(b"prompt").hexdigest(),
        response_hash=hashlib.sha256(b"response").hexdigest(),
    )


class FakeEngine:
    """Отдаёт планы по списку; последний повторяется, если список исчерпан."""

    def __init__(self, plans: list[ProposedPlan], pr_candidates=None) -> None:
        self._plans = list(plans)
        self._pr_candidates = pr_candidates or []
        self.propose_calls = 0
        self.revise_calls = 0

    def _next_plan(self) -> ProposedPlan:
        return self._plans.pop(0) if len(self._plans) > 1 else self._plans[0]

    def propose(self, facts, intent, report, feedback) -> ProposedPlan:
        self.propose_calls += 1
        return self._next_plan()

    def revise(self, plan, correction, feedback) -> ProposedPlan:
        self.revise_calls += 1
        return self._next_plan()

    def pr_feedback(self, plan, repo_key, comment, feedback):
        return tuple(self._pr_candidates)


class UnavailableEngine(FakeEngine):
    """Модель, которая недоступна."""

    def __init__(self) -> None:
        super().__init__([_plan()])

    def propose(self, facts, intent, report, feedback) -> ProposedPlan:
        raise EngineUnavailableError("модель не ответила")


class ScriptedHuman:
    """Решения инженера заданы заранее."""

    def __init__(self, plan_decisions: list[Decision], pr_decisions: list[Decision]) -> None:
        self.plan_decisions = list(plan_decisions)
        self.pr_decisions = list(pr_decisions)
        self.notifications: list[str] = []

    def review_plan(self, plan, report) -> Decision:
        return self.plan_decisions.pop(0)

    def review_pr(self, repo_key, pr_url) -> Decision:
        return self.pr_decisions.pop(0)

    def notify(self, text: str) -> None:
        self.notifications.append(text)


def _params() -> SessionParams:
    return SessionParams(
        release_id="R-1",
        target_env=Env.PSI,
        repos=(RepoParams(ref=REF, release_ref="release/v1.0", base_ref="master"),),
    )


def _intent() -> ReleaseIntent:
    return ReleaseIntent(
        release_id="R-1",
        changes=(
            IntentChange(
                repo_key=REPO_KEY,
                file_path=CONFIG_PATH,
                key_path="server.timeout-seconds",
                new_value=60,
            ),
        ),
    )


def test_happy_path_from_params_to_pull_request() -> None:
    sc = InMemorySourceControl()
    human = ScriptedHuman([Decision(approved=True)], [Decision(approved=True)])
    orchestrator = Orchestrator(sc, FakeEngine([_plan()]), human)
    context = SessionContext.new(user_id="engineer", release_id="R-1")

    result = orchestrator.run(context, _params(), _intent)

    assert result.final_state is SessionState.ALL_DONE
    assert REPO_KEY in result.pr_urls

    # Изменения попали во временную ветку, а не в релизную.
    branch = f"rpa/{context.session_id[:8]}/{REF.repo}"
    assert sc.trees[(REPO_KEY, branch)][CONFIG_PATH] == GOOD_CANDIDATE

    # Оба чекпоинта пройдены и записаны.
    assert [(a.checkpoint, a.decision) for a in result.store.approvals] == [
        ("PLAN", "approved"),
        ("PR", "approved"),
    ]

    # Запись репозитория доведена до конечного состояния.
    task = result.store.repo_tasks[REPO_KEY]
    assert task.repo_state == "DONE"
    assert task.branch_name == branch and task.pr_url

    assert any("pulls" in note for note in human.notifications)


def test_audit_chain_is_fully_reconstructable() -> None:
    human = ScriptedHuman([Decision(approved=True)], [Decision(approved=True)])
    orchestrator = Orchestrator(InMemorySourceControl(), FakeEngine([_plan()]), human)
    result = orchestrator.run(SessionContext.new(user_id="engineer"), _params(), _intent)

    chain = audit_chain.reconstruct_repo_chain(result.store.audit_pairs(), REPO_KEY)
    assert chain.is_complete
    assert chain.plan_approved_by == "engineer"
    assert chain.pr_approved_by == "engineer"
    assert chain.extra_commits == ()


def test_correction_loops_in_both_checkpoints() -> None:
    plan = _plan()
    engine = FakeEngine([plan], pr_candidates=[plan.changes[0]])
    human = ScriptedHuman(
        [Decision(approved=False, comment="поменяй план"), Decision(approved=True)],
        [Decision(approved=False, comment="поправь файл"), Decision(approved=True)],
    )
    orchestrator = Orchestrator(InMemorySourceControl(), engine, human)

    result = orchestrator.run(SessionContext.new(user_id="engineer"), _params(), _intent)

    assert result.final_state is SessionState.ALL_DONE
    assert engine.revise_calls == 1
    assert [(a.checkpoint, a.decision) for a in result.store.approvals] == [
        ("PLAN", "correction"),
        ("PLAN", "approved"),
        ("PR", "correction"),
        ("PR", "approved"),
    ]

    chain = audit_chain.reconstruct_repo_chain(result.store.audit_pairs(), REPO_KEY)
    assert len(chain.extra_commits) == 1


def test_repeated_error_stops_after_two_attempts() -> None:
    """Одна и та же ошибка дважды подряд — третья попытка не делается."""
    engine = FakeEngine([_plan(OUT_OF_SCOPE_CANDIDATE)])
    orchestrator = Orchestrator(InMemorySourceControl(), engine, ScriptedHuman([], []))

    with pytest.raises(EscalationError, match="одна и та же ошибка"):
        orchestrator.run(SessionContext.new(user_id="engineer"), _params(), _intent)
    assert engine.propose_calls == 2


def test_three_distinct_failures_stop_the_loop() -> None:
    engine = FakeEngine(
        [
            _plan(OUT_OF_SCOPE_CANDIDATE),
            _plan("server:\n  timeout-seconds: 60\nextra: 1\n"),
            _plan("server:\n  timeout-seconds: 60\nanother: 2\n"),
        ]
    )
    orchestrator = Orchestrator(InMemorySourceControl(), engine, ScriptedHuman([], []))

    with pytest.raises(EscalationError, match="неудачные попытки"):
        orchestrator.run(SessionContext.new(user_id="engineer"), _params(), _intent)
    assert engine.propose_calls == 3


def test_unavailable_engine_hands_materials_to_human() -> None:
    human = ScriptedHuman([], [])
    orchestrator = Orchestrator(InMemorySourceControl(), UnavailableEngine(), human)

    with pytest.raises(EscalationError, match="модель недоступна"):
        orchestrator.run(SessionContext.new(user_id="engineer"), _params(), _intent)

    # Инженер получил исходные материалы, а не молчаливую остановку.
    assert any("Модель недоступна" in note for note in human.notifications)
    assert any("diff_hash" in note for note in human.notifications)
