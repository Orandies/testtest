"""Branch Diff Analyzer: нормализация файл → ключ → old/new, детерминизм, hash.

Результат должен быть стабильным: одинаковый вход даёт одинаковый выход.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from release_promotion_agent.analyzers.branch_diff import (
    ChangedFileInput,
    ChangeKind,
    FileStatus,
    analyze_branch_diff,
)


@pytest.fixture
def controller_a_pair(fixtures_dir: Path) -> ChangedFileInput:
    configs = fixtures_dir / "configs"
    return ChangedFileInput(
        path="config/ift/application.yaml",
        base_text=(configs / "controller_a_master.yaml").read_text(encoding="utf-8"),
        head_text=(configs / "controller_a_release.yaml").read_text(encoding="utf-8"),
    )


def test_modified_file_normalized_key_changes(controller_a_pair: ChangedFileInput) -> None:
    diff = analyze_branch_diff("controller-a", "master", "release/2026-07", [controller_a_pair])
    (file_diff,) = diff.files
    assert file_diff.status is FileStatus.MODIFIED
    assert file_diff.parse_error is None
    normalized = [(c.key_path, c.change_kind, c.old_value, c.new_value) for c in file_diff.changes]
    assert normalized == [
        ("features.new-billing", ChangeKind.REMOVED, False, None),
        ("integration.circuit-breaker", ChangeKind.ADDED, None, {"enabled": True}),
        (
            "integration.endpoints",
            ChangeKind.CHANGED,
            ["https://service-a.invalid", "https://service-b.invalid"],
            [
                "https://service-a.invalid",
                "https://service-b.invalid",
                "https://service-c.invalid",
            ],
        ),
        ("server.timeout-seconds", ChangeKind.CHANGED, 30, 60),
    ]


def test_added_and_removed_files() -> None:
    added = ChangedFileInput(path="b.yaml", base_text=None, head_text="flags:\n  x: true\n")
    removed = ChangedFileInput(path="a.yaml", base_text="old: 1\n", head_text=None)
    diff = analyze_branch_diff("r", "master", "rel", [added, removed])
    # файлы отсортированы по пути
    assert [(f.path, f.status) for f in diff.files] == [
        ("a.yaml", FileStatus.REMOVED),
        ("b.yaml", FileStatus.ADDED),
    ]
    assert [(c.key_path, c.change_kind) for c in diff.files[0].changes] == [
        ("old", ChangeKind.REMOVED)
    ]
    assert [(c.key_path, c.change_kind) for c in diff.files[1].changes] == [
        ("flags", ChangeKind.ADDED)
    ]


def test_unparseable_yaml_is_flagged_not_swallowed() -> None:
    broken = ChangedFileInput(
        path="broken.yaml", base_text="ok: 1\n", head_text="{{ not yaml ]]\n:::"
    )
    diff = analyze_branch_diff("r", "master", "rel", [broken])
    (file_diff,) = diff.files
    assert file_diff.parse_error is not None
    assert file_diff.changes == ()


def test_both_versions_missing_is_an_error() -> None:
    with pytest.raises(ValueError, match="обе версии"):
        analyze_branch_diff(
            "r", "master", "rel", [ChangedFileInput(path="x.yaml", base_text=None, head_text=None)]
        )


def test_identical_content_yields_no_changes() -> None:
    text = "server:\n  port: 8080\n"
    diff = analyze_branch_diff(
        "r", "master", "rel", [ChangedFileInput(path="same.yaml", base_text=text, head_text=text)]
    )
    assert diff.files[0].changes == ()


def test_non_mapping_root_compared_as_whole() -> None:
    diff = analyze_branch_diff(
        "r",
        "master",
        "rel",
        [ChangedFileInput(path="scalar.yaml", base_text="42\n", head_text="43\n")],
    )
    (change,) = diff.files[0].changes
    assert (change.key_path, change.old_value, change.new_value) == ("", 42, 43)


def test_deterministic_including_input_order(controller_a_pair: ChangedFileInput) -> None:
    """DoD: одинаковый вход (в любом порядке) → одинаковый выход и hash."""
    other = ChangedFileInput(path="config/ift/z.yaml", base_text="a: 1\n", head_text="a: 2\n")
    diff1 = analyze_branch_diff("r", "master", "rel", [controller_a_pair, other])
    diff2 = analyze_branch_diff("r", "master", "rel", [other, controller_a_pair])
    assert diff1 == diff2
    assert diff1.stable_hash() == diff2.stable_hash()


def test_hash_reacts_to_content(controller_a_pair: ChangedFileInput) -> None:
    diff1 = analyze_branch_diff("r", "master", "rel", [controller_a_pair])
    diff2 = analyze_branch_diff(
        "r",
        "master",
        "rel",
        [ChangedFileInput(path=controller_a_pair.path, base_text="a: 1\n", head_text="a: 2\n")],
    )
    assert diff1.stable_hash() != diff2.stable_hash()
