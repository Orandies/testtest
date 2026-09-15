"""Состояние сессии в памяти: записи репозиториев, решения, журнал."""

from __future__ import annotations

from release_promotion_agent.core.session import PlanItem, SessionStore


def _store() -> SessionStore:
    return SessionStore(
        session_id="session-1",
        user_id="engineer",
        fsm_state="SESSION_STARTED",
        release_id="R-1",
    )


def test_upsert_keeps_single_record_per_repo() -> None:
    store = _store()
    store.upsert_repo_task("repo-a", "BRANCHING", branch_name="rpa/x")
    store.upsert_repo_task("repo-a", "COMMITTED")
    assert len(store.repo_tasks) == 1
    assert store.repo_tasks["repo-a"].repo_state == "COMMITTED"


def test_upsert_does_not_erase_known_values() -> None:
    store = _store()
    store.upsert_repo_task("repo-a", "PR_OPENED", branch_name="rpa/x", pr_url="https://pr/1")
    task = store.upsert_repo_task("repo-a", "AWAITING_PR_APPROVAL")
    assert task.branch_name == "rpa/x"
    assert task.pr_url == "https://pr/1"


def test_plan_items_and_approvals_are_collected() -> None:
    store = _store()
    store.add_plan_items(
        [
            PlanItem(
                repo_key="repo-a",
                file_path="agents/PSI.yaml",
                key_path="server.retries",
                change_kind="ADDED",
                source="BOTH",
                status="MATCHED",
            )
        ]
    )
    store.add_approval("PLAN", "approved", comment="ок")
    store.add_approval("PR", "approved", repo_key="repo-a")
    assert len(store.plan_items) == 1
    assert [a.checkpoint for a in store.approvals] == ["PLAN", "PR"]


def test_llm_calls_and_audit_are_recorded() -> None:
    store = _store()
    store.record_llm_call("analyze", "prompt-hash", "response-hash", attempts=2)
    store.append_audit("PLAN_PROPOSED", {"proposal_hash": "abc"})
    assert store.llm_calls[0].attempts == 2
    assert store.audit_pairs() == [("PLAN_PROPOSED", {"proposal_hash": "abc"})]
