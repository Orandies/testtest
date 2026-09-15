"""Validation: YAML-проверка никогда не падает; diff-scope guard режет всё вне плана."""

from __future__ import annotations

import pytest

from release_promotion_agent.validation.checks import (
    guard_diff_scope,
    validate_candidate,
    validate_yaml_text,
)
from release_promotion_agent.validation.models import CandidateFile, Env, ValidationResult

CURRENT = """\
server:
  port: 8080
  timeout-seconds: 30
logging:
  level: INFO
"""


def _candidate(content: str) -> CandidateFile:
    return CandidateFile(
        repo_key="controller-a", env=Env.PSI, file_path="config/psi/app.yaml", content=content
    )


def test_valid_yaml_ok() -> None:
    assert validate_yaml_text("a: 1\n") == ValidationResult.ok()


def test_broken_yaml_is_error_not_exception() -> None:
    result = validate_yaml_text("{{ not yaml ]]\n:::")
    assert not result.valid
    assert "YAML" in result.errors[0]


def test_non_mapping_root_is_warning() -> None:
    result = validate_yaml_text("- 1\n- 2\n")
    assert result.valid
    assert result.warnings


def test_change_inside_plan_passes() -> None:
    candidate = _candidate(CURRENT.replace("timeout-seconds: 30", "timeout-seconds: 60"))
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["server.timeout-seconds"])
    assert result.valid


def test_change_outside_plan_hard_fails() -> None:
    candidate = _candidate(CURRENT.replace("level: INFO", "level: DEBUG"))
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["server.timeout-seconds"])
    assert not result.valid
    assert "logging.level" in result.errors[0]


def test_mixed_changes_fail_and_name_only_violators() -> None:
    content = CURRENT.replace("timeout-seconds: 30", "timeout-seconds: 60").replace(
        "level: INFO", "level: DEBUG"
    )
    result = guard_diff_scope(
        _candidate(content), CURRENT, allowed_key_paths=["server.timeout-seconds"]
    )
    assert not result.valid
    assert len(result.errors) == 1
    assert "logging.level" in result.errors[0]


def test_added_key_outside_plan_fails() -> None:
    candidate = _candidate(CURRENT + "extra:\n  key: 1\n")
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["server.timeout-seconds"])
    assert not result.valid
    assert "extra" in result.errors[0]


def test_removed_key_outside_plan_fails() -> None:
    candidate = _candidate(CURRENT.replace("  timeout-seconds: 30\n", ""))
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["logging.level"])
    assert not result.valid


def test_child_of_allowed_key_passes() -> None:
    """План подтвердил `server` — менять `server.timeout-seconds` можно."""
    candidate = _candidate(CURRENT.replace("timeout-seconds: 30", "timeout-seconds: 60"))
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["server"])
    assert result.valid


def test_sibling_of_allowed_key_fails() -> None:
    """Разрешён `server.port` — `server.timeout-seconds` менять нельзя."""
    candidate = _candidate(CURRENT.replace("timeout-seconds: 30", "timeout-seconds: 60"))
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=["server.port"])
    assert not result.valid


def test_whole_file_allowed_passes_everything() -> None:
    candidate = _candidate("совсем: другой\nконфиг: true\n")
    result = guard_diff_scope(candidate, CURRENT, allowed_key_paths=[], whole_file_allowed=True)
    assert result.valid


def test_identical_candidate_passes_with_empty_plan() -> None:
    assert guard_diff_scope(_candidate(CURRENT), CURRENT, allowed_key_paths=[]).valid


def test_validate_candidate_combines_yaml_and_scope() -> None:
    broken = validate_candidate(_candidate("{{ ]]"), CURRENT, allowed_key_paths=[])
    assert not broken.valid and "YAML" in broken.errors[0]

    ok = validate_candidate(
        _candidate(CURRENT.replace("timeout-seconds: 30", "timeout-seconds: 60")),
        CURRENT,
        allowed_key_paths=["server.timeout-seconds"],
    )
    assert ok.valid


@pytest.mark.parametrize("guard_kwargs", [{}, {"whole_file_allowed": False}])
def test_guard_never_raises_on_broken_yaml(guard_kwargs: dict) -> None:
    result = guard_diff_scope(_candidate("{{ ]]"), CURRENT, allowed_key_paths=[], **guard_kwargs)
    assert not result.valid
