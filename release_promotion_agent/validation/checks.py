"""Проверки кандидата: корректность YAML и границы допустимых правок.

Кандидат может менять только файлы и ключи из подтверждённого человеком
плана. Любое изменение за этими границами отклоняется.

Сравнение YAML реализовано здесь независимо от анализаторов: код, который
проверяет результат, не переиспользует код, этот результат порождающий.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from release_promotion_agent.validation.models import CandidateFile, ValidationResult


def validate_yaml_text(text: str) -> ValidationResult:
    """Проверяет, что текст разбирается как YAML."""
    try:
        document = _parse(text)
    except YAMLError as exc:
        return ValidationResult.fail(f"кандидат не является валидным YAML: {exc}")
    if not isinstance(document, Mapping):
        return ValidationResult.ok(warnings=("корень документа не является словарём",))
    return ValidationResult.ok()


def guard_diff_scope(
    candidate: CandidateFile,
    current_text: str,
    allowed_key_paths: Collection[str],
    whole_file_allowed: bool = False,
) -> ValidationResult:
    """Проверяет, что кандидат меняет только разрешённые планом ключи.

    Ключ разрешён, если его путь совпадает с разрешённым или вложен в него:
    при разрешённом a.b можно менять и a.b.c. Флаг whole_file_allowed
    означает, что план подтвердил файл целиком.
    """
    # Разбираем обе версии: нечитаемый YAML даёт ошибку в результате.
    try:
        candidate_doc = _to_plain(_parse(candidate.content))
        current_doc = _to_plain(_parse(current_text))
    except YAMLError as exc:
        return ValidationResult.fail(f"не удалось разобрать YAML: {exc}")

    # Считаем, какие ключи кандидат меняет.
    changed = sorted(_changed_key_paths(current_doc, candidate_doc))
    if whole_file_allowed or not changed:
        return ValidationResult.ok()

    # Каждый изменённый ключ должен попадать в границы плана.
    allowed = tuple(allowed_key_paths)
    out_of_scope = [path for path in changed if not _is_allowed(path, allowed)]
    if out_of_scope:
        return ValidationResult.fail(
            *(
                f"изменение вне подтверждённого плана: {candidate.file_path} → "
                f"{path or '<корень документа>'}"
                for path in out_of_scope
            )
        )
    return ValidationResult.ok()


def validate_candidate(
    candidate: CandidateFile,
    current_text: str,
    allowed_key_paths: Collection[str],
    whole_file_allowed: bool = False,
) -> ValidationResult:
    """Полная проверка кандидата: сначала YAML, затем границы правок."""
    yaml_result = validate_yaml_text(candidate.content)
    if not yaml_result.valid:
        return yaml_result
    return yaml_result.merged_with(
        guard_diff_scope(candidate, current_text, allowed_key_paths, whole_file_allowed)
    )


# ── собственная реализация сравнения ─────────────────────────────────


def _parse(text: str) -> Any:
    return YAML(typ="rt").load(StringIO(text))


def _to_plain(node: Any) -> Any:
    if isinstance(node, Mapping):
        return {str(key): _to_plain(value) for key, value in node.items()}
    if isinstance(node, list | tuple):
        return [_to_plain(item) for item in node]
    if node is None or isinstance(node, bool):
        return node
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    if isinstance(node, str):
        return str(node)
    return str(node)


def _changed_key_paths(old: Any, new: Any, prefix: str = "") -> set[str]:
    """Пути ключей, по которым кандидат отличается от текущего конфига."""
    if isinstance(old, dict) and isinstance(new, dict):
        changed: set[str] = set()
        for key in set(old) | set(new):
            child = f"{prefix}.{key}" if prefix else key
            if key not in old or key not in new:
                # Ключ добавлен или удалён — изменение по этому пути.
                changed.add(child)
            else:
                changed |= _changed_key_paths(old[key], new[key], child)
        return changed
    # Скаляры, списки и разные типы: либо равны, либо изменены целиком.
    return set() if old == new else {prefix}


def _is_allowed(path: str, allowed: tuple[str, ...]) -> bool:
    # Разрешён сам ключ и любой вложенный в него, но не соседний.
    return any(path == item or path.startswith(item + ".") for item in allowed)
