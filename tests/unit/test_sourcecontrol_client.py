"""Клиент SourceControl v3 (read): реальные пути, парсинг fixtures, ретраи.

Обращений к сети нет: транспорт подменён заглушкой httpx.MockTransport.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from release_promotion_agent.core.errors import SourceControlError
from release_promotion_agent.tools.git_tool import MAX_ATTEMPTS, SourceControlClient
from release_promotion_agent.tools.models import FileChangeStatus, RepoRef

# Координаты репозитория для проверки построения путей.
REF = RepoRef(tenant="omega", project="PROJ01", repo="configs_core")
BASE = "/api/v3"


def _client_with(handler) -> SourceControlClient:
    sleeps: list[float] = []
    client = SourceControlClient(
        base_url=f"https://api.sc-cd.invalid{BASE}",
        token="fake-token",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    client.test_sleeps = sleeps  # type: ignore[attr-defined] — только для тестов
    return client


def test_repo_ref_builds_v3_path() -> None:
    assert REF.path == "/repos/omega/PROJ01/configs_core"
    assert REF.key == "omega/PROJ01/configs_core"


def test_list_projects_uses_tenants_path(fixtures_dir: Path) -> None:
    payload = (fixtures_dir / "sourcecontrol" / "repos.json").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{BASE}/tenants/omega/projects"
        assert request.headers["Authorization"] == "Bearer fake-token"
        return httpx.Response(200, text=payload)

    with _client_with(handler) as client:
        projects = client.list_projects("omega")
    assert [p.key for p in projects] == ["controller-a", "controller-b"]


def test_compare_parses_fixture(fixtures_dir: Path) -> None:
    payload = (fixtures_dir / "sourcecontrol" / "compare_controller_a.json").read_text(
        encoding="utf-8"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{BASE}{REF.path}/compare"
        assert request.url.params["base"] == "master"
        assert request.url.params["head"] == "release/v1.0"
        return httpx.Response(200, text=payload)

    with _client_with(handler) as client:
        result = client.compare(REF, "master", "release/v1.0")
    assert result.repo_key == REF.key
    assert [(f.path, f.status) for f in result.files] == [
        ("config/ift/application.yaml", FileChangeStatus.MODIFIED),
        ("config/ift/feature-flags.yaml", FileChangeStatus.ADDED),
        ("config/ift/legacy.yaml", FileChangeStatus.REMOVED),
    ]


def test_get_file_uses_raw_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{BASE}{REF.path}/raw/agents/PSI.yaml"
        assert request.url.params["ref"] == "release/v1.0"
        return httpx.Response(200, text="server:\n  port: 8080\n")

    with _client_with(handler) as client:
        content = client.get_file(REF, "agents/PSI.yaml", "release/v1.0")
    assert content == "server:\n  port: 8080\n"


def test_retries_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[])

    with _client_with(handler) as client:
        assert client.list_projects("omega") == []
        assert client.test_sleeps == [0.5, 1.0]  # экспоненциальный backoff
    assert len(calls) == 3


def test_gives_up_after_max_attempts() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with _client_with(handler) as client:
        with pytest.raises(SourceControlError, match="исчерпаны"):
            client.list_projects("omega")
    assert len(calls) == MAX_ATTEMPTS


def test_network_errors_are_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    with _client_with(handler) as client:
        with pytest.raises(SourceControlError, match="сетевая ошибка"):
            client.list_projects("omega")
    assert len(calls) == MAX_ATTEMPTS


def test_client_error_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    with _client_with(handler) as client:
        with pytest.raises(SourceControlError) as exc_info:
            client.list_projects("omega")
    assert len(calls) == 1  # 4xx — немедленно, без ретраев
    assert exc_info.value.status_code == 401


def test_merge_physically_absent() -> None:
    """В API такая операция есть, в клиенте агента её нет и быть не должно."""
    members = [name.lower() for name in dir(SourceControlClient)]
    assert not any("merge" in name for name in members)
