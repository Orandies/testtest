"""Модели данных SourceControl API v3."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

__all__ = [
    "RepoRef",
    "RepoInfo",
    "FileChangeStatus",
    "CompareFile",
    "CompareResult",
    "BranchInfo",
    "PullRequestInfo",
]


class RepoRef(BaseModel):
    """Координаты репозитория: путь API строится как
    /repos/{tenant}/{project}/{repo}.
    """

    model_config = ConfigDict(frozen=True)

    tenant: str
    project: str
    repo: str

    @property
    def path(self) -> str:
        return f"/repos/{self.tenant}/{self.project}/{self.repo}"

    @property
    def key(self) -> str:
        return f"{self.tenant}/{self.project}/{self.repo}"


class RepoInfo(BaseModel):
    """Элемент списка проектов или репозиториев."""

    model_config = ConfigDict(frozen=True)

    key: str
    name: str


class FileChangeStatus(StrEnum):
    """Что случилось с файлом между двумя ветками, по данным API.

    Приходит из ответа системы контроля версий и переводится в свой
    FileStatus анализатора: внешние названия в остальной код не
    протекают.
    """

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    REMOVED = "REMOVED"


class CompareFile(BaseModel):
    """Один изменённый файл в сравнении двух веток."""

    model_config = ConfigDict(frozen=True)

    path: str
    status: FileChangeStatus


class CompareResult(BaseModel):
    """Результат сравнения: какие файлы различаются между base и head."""

    model_config = ConfigDict(frozen=True)

    repo_key: str
    base_ref: str
    head_ref: str
    files: tuple[CompareFile, ...]


class BranchInfo(BaseModel):
    """Ветка репозитория."""

    model_config = ConfigDict(frozen=True)

    name: str
    head_commit: str | None = None


class PullRequestInfo(BaseModel):
    """Pull request. Адресуется порядковым номером index в пределах репозитория."""

    model_config = ConfigDict(frozen=True)

    index: int
    url: str
    source_branch: str
    target_branch: str
