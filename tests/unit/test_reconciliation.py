"""Reconciliation: категории расхождений, поглощение «файлом целиком», детерминизм.

Отчёт стабилен, расхождения не решаются автоматически.
"""

from __future__ import annotations

from release_promotion_agent.analyzers.branch_diff import (
    BranchDiff,
    ChangeKind,
    FileDiff,
    FileStatus,
    KeyChange,
)
from release_promotion_agent.analyzers.intent import IntentChange, ReleaseIntent
from release_promotion_agent.analyzers.reconciliation import DiscrepancyKind, reconcile


def _fact(*changes: KeyChange, path: str = "config/psi/app.yaml") -> BranchDiff:
    return BranchDiff(
        repo_key="controller-a",
        base_ref="master",
        head_ref="release/1",
        files=(FileDiff(path=path, status=FileStatus.MODIFIED, changes=changes),),
    )


def _change(key_path: str, new_value: object = None) -> KeyChange:
    return KeyChange(
        key_path=key_path, change_kind=ChangeKind.CHANGED, old_value="old", new_value=new_value
    )


def _intent(*changes: IntentChange) -> ReleaseIntent:
    return ReleaseIntent(release_id="R-1", changes=changes)


def test_matched_when_key_and_value_agree() -> None:
    report = reconcile(
        [_fact(_change("a.b", new_value=60))],
        _intent(
            IntentChange(
                repo_key="controller-a",
                file_path="config/psi/app.yaml",
                key_path="a.b",
                new_value=60,
            )
        ),
    )
    assert len(report.matched) == 1
    assert report.discrepancies == ()


def test_intent_without_value_matches_any_fact_value() -> None:
    """Инструкция не назвала значение — сверять нечего, совпадение по ключу."""
    report = reconcile(
        [_fact(_change("a.b", new_value=999))],
        _intent(
            IntentChange(repo_key="controller-a", file_path="config/psi/app.yaml", key_path="a.b")
        ),
    )
    assert len(report.matched) == 1
    assert report.discrepancies == ()


def test_value_mismatch_is_surfaced_not_resolved() -> None:
    report = reconcile(
        [_fact(_change("a.b", new_value=60))],
        _intent(
            IntentChange(
                repo_key="controller-a",
                file_path="config/psi/app.yaml",
                key_path="a.b",
                new_value=90,
            )
        ),
    )
    assert report.matched == ()
    (d,) = report.discrepancies
    assert d.kind is DiscrepancyKind.VALUE_MISMATCH
    assert d.fact is not None and d.fact.new_value == 60
    assert d.intent is not None and d.intent.new_value == 90


def test_fact_only_and_intent_only() -> None:
    report = reconcile(
        [_fact(_change("only.in.diff"))],
        _intent(
            IntentChange(
                repo_key="controller-a",
                file_path="config/psi/app.yaml",
                key_path="only.in.plan",
            )
        ),
    )
    kinds = [(d.kind, d.key_path) for d in report.discrepancies]
    assert kinds == [
        (DiscrepancyKind.FACT_ONLY, "only.in.diff"),
        (DiscrepancyKind.INTENT_ONLY, "only.in.plan"),
    ]


def test_whole_file_intent_consumes_all_fact_changes() -> None:
    report = reconcile(
        [_fact(_change("x"), _change("y"))],
        _intent(
            IntentChange(repo_key="controller-a", file_path="config/psi/app.yaml", key_path=None)
        ),
    )
    assert len(report.matched) == 1
    assert report.matched[0].key_path is None
    assert report.discrepancies == ()


def test_whole_file_intent_without_facts_is_intent_only() -> None:
    report = reconcile(
        [],
        _intent(
            IntentChange(repo_key="controller-a", file_path="config/psi/app.yaml", key_path=None)
        ),
    )
    (d,) = report.discrepancies
    assert d.kind is DiscrepancyKind.INTENT_ONLY and d.key_path is None


def test_unparsed_file_goes_to_human() -> None:
    fact = BranchDiff(
        repo_key="controller-a",
        base_ref="master",
        head_ref="release/1",
        files=(
            FileDiff(
                path="config/psi/broken.yaml",
                status=FileStatus.MODIFIED,
                parse_error="ошибка парсинга",
            ),
        ),
    )
    report = reconcile([fact], _intent())
    (d,) = report.discrepancies
    assert d.kind is DiscrepancyKind.FACT_UNPARSED
    assert d.note == "ошибка парсинга"


def test_deterministic_regardless_of_input_order() -> None:
    facts = [
        _fact(_change("b.key", 1), _change("a.key", 2)),
    ]
    intent_items = (
        IntentChange(
            repo_key="controller-a", file_path="config/psi/app.yaml", key_path="a.key", new_value=2
        ),
        IntentChange(
            repo_key="controller-a", file_path="config/psi/app.yaml", key_path="zz.absent"
        ),
    )
    report1 = reconcile(facts, ReleaseIntent(release_id="R-1", changes=intent_items))
    report2 = reconcile(facts, ReleaseIntent(release_id="R-1", changes=intent_items[::-1]))
    assert report1 == report2
    assert report1.stable_hash() == report2.stable_hash()
