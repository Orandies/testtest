"""Git/SourceControl Tool — обёртка над SourceControl API для агента.

Предоставляет методы чтения файлов, создания веток, коммитов и pull requests.
Используется как внешний инструмент агента (не доступен напрямую LLM).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from release_promotion_agent.core.errors import SourceControlError
from release_promotion_agent.tools.models import (
    BranchInfo,
    CompareFile,
    CompareResult,
    FileChangeStatus,
    PullRequestInfo,
    RepoInfo,
    RepoRef,
)

__all__ = ["SourceControlClient", "SourceControlError"]

MAX_ATTEMPTS = 3
_RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5


class SourceControlClient:
    """Работа с системой контроля версий по HTTP API.

    Читает diff веток и содержимое файлов, создаёт ветки, коммиты и pull
    request. Метода слияния здесь нет и не будет: агент готовит
    изменения, но не вливает их — это второй эшелон защиты к токену без
    прав на слияние. Отсутствие метода закреплено тестом.

    Сетевой протокол: три попытки с растущей паузой на сетевых сбоях и
    кодах 429 и 5xx; остальные ответы 4xx возвращают ошибку сразу, потому
    что повторять запрос с неверным токеном или к несуществующему
    репозиторию бессмысленно.

    Файлы правятся по одному: операции «один коммит на несколько файлов»
    в API нет, поэтому commit_files применяет изменения последовательно.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
        )

    # ── чтение ───────────────────────────────────────────────────────

    def list_projects(self, tenant: str) -> list[RepoInfo]:
        """Список проектов тенанта."""
        data = self._request_json("GET", f"/tenants/{tenant}/projects")
        items = data.get("values") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise SourceControlError(f"неожиданный формат ответа projects для тенанта {tenant}")
        return [
            RepoInfo(key=str(item.get("key") or item["name"]), name=str(item["name"]))
            for item in items
        ]

    def compare(self, ref: RepoRef, base_ref: str, head_ref: str) -> CompareResult:
        """Файлы, различающиеся между базовой и релизной ветками."""
        data = self._request_json(
            "GET", f"{ref.path}/compare", params={"base": base_ref, "head": head_ref}
        )
        files = data.get("files") if isinstance(data, dict) else None
        if files is None:
            raise SourceControlError(f"неожиданный формат ответа compare для {ref.key}")
        return CompareResult(
            repo_key=ref.key,
            base_ref=base_ref,
            head_ref=head_ref,
            files=tuple(
                CompareFile(path=item["path"], status=FileChangeStatus(item["status"].upper()))
                for item in files
            ),
        )

    def get_file(self, ref: RepoRef, path: str, branch: str) -> str:
        """Содержимое файла на указанной ветке, текстом в UTF-8."""
        response = self._request(
            "GET", f"{ref.path}/raw/{path.lstrip('/')}", params={"ref": branch}
        )
        assert response is not None
        return response.text

    # ── запись: ветка, файлы, pull request, комментарий ──────────────

    def get_branch(self, ref: RepoRef, name: str) -> BranchInfo | None:
        """Ветка, если она есть, иначе None."""
        data = self._request_json("GET", f"{ref.path}/branches/{name}", none_on_404=True)
        if data is None:
            return None
        return BranchInfo(name=data.get("name", name), head_commit=data.get("head_commit"))

    def create_branch(self, ref: RepoRef, name: str, from_ref: str) -> BranchInfo:
        """Создаёт ветку копией указанной."""
        data = self._request_json(
            "POST",
            f"{ref.path}/branches",
            json_body={"name": name, "from_ref": from_ref},
        )
        return BranchInfo(name=data.get("name", name), head_commit=data.get("head_commit"))

    def update_file(self, ref: RepoRef, path: str, branch: str, content: str, message: str) -> str:
        """Обновляет содержимое одного файла и возвращает id коммита."""
        data = self._request_json(
            "PUT",
            f"{ref.path}/contents/file/update",
            json_body={
                "path": path,
                "branch": branch,
                "content": content,
                "message": message,
            },
        )
        return str(data.get("commit_id") or data.get("id") or "")

    def create_file(self, ref: RepoRef, path: str, branch: str, content: str, message: str) -> str:
        """Создаёт новый файл и возвращает id коммита."""
        data = self._request_json(
            "POST",
            f"{ref.path}/contents/file/create",
            json_body={
                "path": path,
                "branch": branch,
                "content": content,
                "message": message,
            },
        )
        return str(data.get("commit_id") or data.get("id") or "")

    def commit_files(self, ref: RepoRef, branch: str, message: str, files: dict[str, str]) -> str:
        """Записывает все файлы в ветку и возвращает id последнего коммита."""
        last_commit = ""
        for path in sorted(files):
            last_commit = self.update_file(ref, path, branch, files[path], message)
        return last_commit

    def find_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str
    ) -> PullRequestInfo | None:
        """Открытый pull request из ветки в ветку, если он уже создан."""
        data = self._request_json(
            "GET",
            f"{ref.path}/pulls",
            params={"source": source_branch, "target": target_branch, "state": "open"},
        )
        values = data.get("values") if isinstance(data, dict) else data
        if not values:
            return None
        return self._pull_request_from(values[0], source_branch, target_branch)

    def create_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str, title: str, body: str
    ) -> PullRequestInfo:
        """Создаёт pull request из временной ветки в релизную."""
        data = self._request_json(
            "POST",
            f"{ref.path}/pulls",
            json_body={
                "source": source_branch,
                "target": target_branch,
                "title": title,
                "body": body,
            },
        )
        return self._pull_request_from(data, source_branch, target_branch)

    def add_pull_request_comment(self, ref: RepoRef, index: int, text: str) -> None:
        """Добавляет комментарий к pull request."""
        self._request_json("POST", f"{ref.path}/pulls/{index}/comments", json_body={"text": text})

    @staticmethod
    def _pull_request_from(
        data: dict[str, Any], source_branch: str, target_branch: str
    ) -> PullRequestInfo:
        """Собирает описание pull request из ответа API."""
        index = data.get("index", data.get("number"))
        if index is None:
            raise SourceControlError("в ответе pull request нет поля index")
        return PullRequestInfo(
            index=int(index),
            url=str(data.get("url") or data.get("html_url") or ""),
            source_branch=str(data.get("source") or source_branch),
            target_branch=str(data.get("target") or target_branch),
        )

    # ── выполнение запросов ──────────────────────────────────────────

    def _request_json(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
        none_on_404: bool = False,
    ) -> Any:
        response = self._request(
            method, path, params=params, json_body=json_body, none_on_404=none_on_404
        )
        if response is None:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise SourceControlError(f"ответ {path} не является JSON: {exc}") from exc

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
        none_on_404: bool = False,
    ) -> httpx.Response | None:
        """Выполняет запрос с ретраями."""
        last_problem = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._client.request(method, path, params=params, json=json_body)
            except httpx.TransportError as exc:
                last_problem = f"сетевая ошибка: {exc}"
            else:
                if response.status_code < 400:
                    return response
                if none_on_404 and response.status_code == 404:
                    return None
                if response.status_code not in _RETRIABLE_STATUSES:
                    raise SourceControlError(
                        f"SourceControl ответил {response.status_code} на {method} {path}",
                        status_code=response.status_code,
                    )
                last_problem = f"HTTP {response.status_code}"
            if attempt < MAX_ATTEMPTS:
                self._sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        raise SourceControlError(
            f"{method} {path}: {MAX_ATTEMPTS} попытки исчерпаны, "
            f"последняя проблема — {last_problem}"
        )

    # ── жизненный цикл ───────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SourceControlClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
