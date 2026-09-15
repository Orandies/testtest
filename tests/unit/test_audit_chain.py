"""Аудит-цепочка: редакция payload и детерминированное восстановление по репо."""

from __future__ import annotations

from release_promotion_agent.core import audit_chain
from release_promotion_agent.core.redaction import MASK, Redactor


def test_redact_payload_scrubs_nested_strings() -> None:
    redactor = Redactor(known_secrets=("topsecret",))
    payload = {
        "url": "https://sc.invalid/pr/1?token=topsecret",
        "nested": {"note": "с topsecret внутри"},
        "list": ["topsecret", 42],
        "number": 7,
    }
    clean = audit_chain.redact_payload(redactor, payload)
    assert "topsecret" not in str(clean)
    assert MASK in clean["url"]
    assert clean["number"] == 7


def _full_events(repo_key: str = "controller-a") -> list[tuple[str, dict]]:
    return [
        (audit_chain.EVENT_DIFF_ANALYZED, {"repo_key": repo_key, "diff_hash": "d1"}),
        (audit_chain.EVENT_INTENT_READ, {"plan_hash": "p1"}),
        (audit_chain.EVENT_PLAN_PROPOSED, {"prompt_hash": "pr1", "response_hash": "r1"}),
        (audit_chain.EVENT_VALIDATION_RESULT, {"purpose": "analyze", "valid": True}),
        (audit_chain.EVENT_PLAN_APPROVED, {"approved_by": "engineer1"}),
        (audit_chain.EVENT_PR_OPENED, {"repo_key": repo_key, "pr_url": "https://sc.invalid/pr/1"}),
        (audit_chain.EVENT_PR_EXTRA_COMMIT, {"repo_key": repo_key, "commit_id": "c9"}),
        (audit_chain.EVENT_PR_APPROVED, {"repo_key": repo_key, "approved_by": "engineer1"}),
    ]


def test_full_chain_reconstructed() -> None:
    result = audit_chain.reconstruct_repo_chain(_full_events(), "controller-a")
    assert result.is_complete
    assert result.diff_hash == "d1"
    assert result.plan_hash == "p1"
    assert result.prompt_hash == "pr1"
    assert result.response_hash == "r1"
    assert result.validation_passed is True
    assert result.plan_approved_by == "engineer1"
    assert result.pr_url == "https://sc.invalid/pr/1"
    assert result.extra_commits == ("c9",)
    assert result.pr_approved_by == "engineer1"


def test_incomplete_chain_detected() -> None:
    events = [e for e in _full_events() if e[0] != audit_chain.EVENT_PR_APPROVED]
    result = audit_chain.reconstruct_repo_chain(events, "controller-a")
    assert not result.is_complete


def test_events_of_other_repo_ignored() -> None:
    events = _full_events("controller-b")
    result = audit_chain.reconstruct_repo_chain(events, "controller-a")
    assert result.pr_url is None
    assert result.plan_hash == "p1"  # события уровня сессии — общие
