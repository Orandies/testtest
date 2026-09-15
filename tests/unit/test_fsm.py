"""Автомат сессии: разрешённые переходы, циклы корректировок, запреты."""

from __future__ import annotations

import pytest

from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import InvalidTransitionError
from release_promotion_agent.core.fsm import TRANSITIONS, SessionFSM, SessionState

HAPPY_PATH = (
    SessionState.PARAMS_COLLECTED,
    SessionState.DIFF_ANALYZED,
    SessionState.PLAN_ANALYZED,
    SessionState.PLAN_PROPOSED,
    SessionState.AWAITING_PLAN_APPROVAL,
    SessionState.PLAN_APPROVED,
    SessionState.REPO_BRANCHING,
    SessionState.REPO_COMMITTED,
    SessionState.PR_OPENED,
    SessionState.AWAITING_PR_APPROVAL,
    SessionState.REPO_DONE,
    SessionState.ALL_DONE,
)


def _start() -> SessionFSM:
    return SessionFSM.start(SessionContext.new(user_id="engineer", release_id="R-1"))


def test_happy_path_is_fully_allowed() -> None:
    fsm = _start()
    for state in HAPPY_PATH:
        fsm.transition_to(state)
    assert fsm.state is SessionState.ALL_DONE


def test_plan_correction_loop() -> None:
    fsm = _start()
    for state in HAPPY_PATH[:5]:
        fsm.transition_to(state)
    fsm.transition_to(SessionState.PLAN_CORRECTION)
    fsm.transition_to(SessionState.PLAN_PROPOSED)
    fsm.transition_to(SessionState.AWAITING_PLAN_APPROVAL)
    fsm.transition_to(SessionState.PLAN_APPROVED)
    assert fsm.state is SessionState.PLAN_APPROVED


def test_pr_correction_loop_and_next_repo() -> None:
    fsm = _start()
    for state in HAPPY_PATH[:10]:
        fsm.transition_to(state)
    fsm.transition_to(SessionState.PR_CORRECTION)
    fsm.transition_to(SessionState.AWAITING_PR_APPROVAL)
    fsm.transition_to(SessionState.REPO_DONE)
    fsm.transition_to(SessionState.REPO_BRANCHING)
    assert fsm.state is SessionState.REPO_BRANCHING


def test_forbidden_transition_raises_and_keeps_state() -> None:
    fsm = _start()
    with pytest.raises(InvalidTransitionError):
        fsm.transition_to(SessionState.PLAN_APPROVED)
    assert fsm.state is SessionState.SESSION_STARTED
    assert fsm.store.fsm_state == "SESSION_STARTED"


def test_all_done_is_terminal() -> None:
    assert TRANSITIONS[SessionState.ALL_DONE] == frozenset()


def test_every_state_is_reachable() -> None:
    reachable = {SessionState.SESSION_STARTED}
    for targets in TRANSITIONS.values():
        reachable |= targets
    assert reachable == set(SessionState)


def test_transitions_are_recorded_in_audit() -> None:
    fsm = _start()
    fsm.transition_to(SessionState.PARAMS_COLLECTED)
    events = fsm.store.audit_pairs()
    assert events[0][0] == "SESSION_STARTED"
    assert events[-1] == ("FSM_TRANSITION", {"from": "SESSION_STARTED", "to": "PARAMS_COLLECTED"})
