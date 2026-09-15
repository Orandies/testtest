"""Нормализация diff между базовой и релизной ветками — «факт» релиза.

На вход подаётся содержимое конфигов на двух ветках, на выходе получается
структура файл → ключ → прежнее и новое значение.

Правила разбора:

- YAML читается в режиме round-trip, без потери структуры документа;
- вложенные ключи разворачиваются в путь через точку: a.b.c;
- списки сравниваются целиком как значение своего ключа, потому что
  порядок элементов в конфигах значим;
- файл, который не разбирается как YAML, помечается ошибкой разбора и
  уходит человеку, а не пропускается молча;
- результат детерминирован: одинаковый вход даёт одинаковый выход и
  одинаковый stable_hash, первое звено цепочки аудита.

Смысл изменений здесь не интерпретируется — это задача модели.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from io import StringIO
from typing import Any

from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class ChangeKind(StrEnum):
    """Что случилось с одним ключом конфига: появился, исчез, изменился."""

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


class FileStatus(StrEnum):
    """Что случилось с файлом целиком.

    Отличается от ChangeKind уровнем: файл может быть только добавлен,
    изменён или удалён, а внутри изменённого файла у каждого ключа своя
    судьба.
    """

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    REMOVED = "REMOVED"


class ChangedFileInput(BaseModel):
    """Один файл в двух версиях.

    base_text — содержимое на базовой ветке, None означает, что файла там нет;
    head_text — содержимое на релизной ветке, None означает, что файл удалён.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    base_text: str | None
    head_text: str | None


class KeyChange(BaseModel):
    """Изменение одного ключа конфига.

    key_path — путь до ключа через точку: вложенность разворачивается в
    плоскую строку, поэтому сопоставлять позиции плана с изменениями
    можно простым сравнением строк.

    Список считается одним значением целиком, а не набором элементов: в
    конфигах контроллеров порядок элементов значим, и «добавили один
    адрес в середину» — это изменение всего списка.
    """

    key_path: str
    change_kind: ChangeKind
    old_value: object = None
    new_value: object = None


class FileDiff(BaseModel):
    """Изменения в одном файле.

    Если файл не разобрался как YAML, changes останется пустым, а причина
    попадёт в parse_error. Такой файл не пропускается молча: он уходит
    человеку отдельным расхождением, потому что сверить его по ключам
    невозможно, а промолчать значит потерять изменение.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    status: FileStatus
    changes: tuple[KeyChange, ...] = ()
    parse_error: str | None = None


class BranchDiff(BaseModel):
    """Что изменилось в релизной ветке одного репозитория — ФАКТ релиза.

    Первый из двух источников, на которых строится работа агента: он
    говорит, что действительно поменялось, независимо от того, что
    написано в инструкции.

    Структура детерминирована: одинаковый вход даёт одинаковый выход и
    одинаковый stable_hash. Этот хэш — первое звено цепочки аудита, по
    нему потом видно, из какого именно состояния веток вырос план.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    base_ref: str
    head_ref: str
    files: tuple[FileDiff, ...]

    def stable_hash(self) -> str:
        """Хэш содержимого для цепочки аудита."""
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def analyze_branch_diff(
    repo_key: str,
    base_ref: str,
    head_ref: str,
    files: Sequence[ChangedFileInput],
) -> BranchDiff:
    """Строит нормализованный diff по всем переданным файлам. Детерминирован."""
    return BranchDiff(
        repo_key=repo_key,
        base_ref=base_ref,
        head_ref=head_ref,
        files=tuple(_diff_file(file) for file in sorted(files, key=lambda f: f.path)),
    )


def _diff_file(file: ChangedFileInput) -> FileDiff:
    # Судьба файла определяется наличием версий.
    if file.base_text is None and file.head_text is None:
        raise ValueError(f"файл {file.path}: обе версии отсутствуют — нечего сравнивать")
    if file.base_text is None:
        status = FileStatus.ADDED
    elif file.head_text is None:
        status = FileStatus.REMOVED
    else:
        status = FileStatus.MODIFIED

    # Отсутствующая версия считается пустым документом: добавленный файл
    # даёт добавление всех своих ключей, удалённый — их удаление.
    try:
        old_doc = _parse_yaml(file.base_text) if file.base_text is not None else {}
        new_doc = _parse_yaml(file.head_text) if file.head_text is not None else {}
    except YAMLError as exc:
        # Файл не разобран: помечаем ошибкой и отдаём человеку.
        return FileDiff(path=file.path, status=status, parse_error=str(exc))

    # Обход обоих документов с последующей сортировкой даёт стабильный порядок.
    changes: list[KeyChange] = []
    _diff_nodes(old_doc, new_doc, path=(), changes=changes)
    changes.sort(key=lambda c: c.key_path)
    return FileDiff(path=file.path, status=status, changes=tuple(changes))


def _parse_yaml(text: str) -> Any:
    yaml = YAML(typ="rt")  # round-trip сохраняет структуру документа
    return _to_plain(yaml.load(StringIO(text)))


def _to_plain(node: Any) -> Any:
    """Приводит типы парсера к обычным значениям Python."""
    if isinstance(node, Mapping):
        return {str(key): _to_plain(value) for key, value in node.items()}
    if isinstance(node, list | tuple):
        return [_to_plain(item) for item in node]
    if node is None or isinstance(node, bool | int | float | str):
        # Скалярные подклассы парсера приводятся к базовым типам.
        if isinstance(node, bool) or node is None:
            return node
        if isinstance(node, int):
            return int(node)
        if isinstance(node, float):
            return float(node)
        return str(node)
    # Даты, теги и прочее — строкой, чтобы результат был сравнимым.
    return str(node)


def _diff_nodes(old: Any, new: Any, path: tuple[str, ...], changes: list[KeyChange]) -> None:
    # Обе стороны — словари: спускаемся по объединению ключей.
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            child_path = (*path, key)
            if key not in new:
                changes.append(
                    KeyChange(
                        key_path=".".join(child_path),
                        change_kind=ChangeKind.REMOVED,
                        old_value=old[key],
                    )
                )
            elif key not in old:
                changes.append(
                    KeyChange(
                        key_path=".".join(child_path),
                        change_kind=ChangeKind.ADDED,
                        new_value=new[key],
                    )
                )
            else:
                # Ключ есть с обеих сторон — сравниваем значения глубже.
                _diff_nodes(old[key], new[key], child_path, changes)
        return
    # Скаляры, списки и разные типы сравниваются целиком.
    if old != new:
        changes.append(
            KeyChange(
                key_path=".".join(path),
                change_kind=ChangeKind.CHANGED,
                old_value=old,
                new_value=new,
            )
        )
