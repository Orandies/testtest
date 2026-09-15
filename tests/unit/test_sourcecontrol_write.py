"""Write-часть клиента SourceControl: ветки, файлы, PR, комментарии.

Обращений к сети нет: транспорт подменён заглушкой httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx

from release_promotion_agent.tools.git_tool import SourceControlClient
from release_promotion_agent.tools.models import RepoRef

REF = RepoRef(tenant="omega", project="PROJ01", repo="configs_core")
BASE = "/api/v3"


def _client_with(handler) -> SourceControlClient:
    return SourceControlClient(
        base_url=f"https://api.sc-cd.invalid{BASE}",
        token="fake-token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )


def test_get_branch_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{BASE}{REF.path}/branches/rpa/x"
        return httpx.Response(404)

    with _client_with(handler) as client:
        assert client.get_branch(REF, "rpa/x") is None


def test_create_branch_posts_to_branches() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "rpa/x", "head_commit": "abc123"})

    with _client_with(handler) as client:
        branch = client.create_branch(REF, "rpa/x", from_ref="release/v1.0")
    assert seen["method"] == "POST"
    assert seen["path"] == f"{BASE}{REF.path}/branches"
    assert seen["body"] == {"name": "rpa/x", "from_ref": "release/v1.0"}
    assert branch.head_commit == "abc123"


def test_update_file_uses_contents_file_update() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"commit_id": "c42"})

    with _client_with(handler) as client:
        commit = client.update_file(REF, "agents/PSI.yaml", "rpa/x", "a: 1\n", "сообщение")
    assert seen["method"] == "PUT"
    assert seen["path"] == f"{BASE}{REF.path}/contents/file/update"
    assert seen["body"]["path"] == "agents/PSI.yaml"
    assert seen["body"]["branch"] == "rpa/x"
    assert commit == "c42"


def test_create_file_uses_contents_file_create() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"commit_id": "c7"})

    with _client_with(handler) as client:
        assert client.create_file(REF, "new.yaml", "rpa/x", "a: 1\n", "msg") == "c7"
    assert seen["path"] == f"{BASE}{REF.path}/contents/file/create"


def test_commit_files_applies_each_file_in_sorted_order() -> None:
    """Файлы применяются по одному в порядке сортировки путей."""
    applied: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        applied.append(body["path"])
        return httpx.Response(200, json={"commit_id": f"c{len(applied)}"})

    with _client_with(handler) as client:
        last = client.commit_files(
            REF,
            "rpa/x",
            "msg",
            {"agents/PSI.yaml": "a: 1\n", "common/COMMON.yaml": "b: 2\n"},
        )
    assert applied == ["agents/PSI.yaml", "common/COMMON.yaml"]
    assert last == "c2"


def test_find_pull_request_none_when_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{BASE}{REF.path}/pulls"
        assert request.url.params["source"] == "rpa/x"
        return httpx.Response(200, json={"values": []})

    with _client_with(handler) as client:
        assert client.find_pull_request(REF, "rpa/x", "release/v1.0") is None


def test_create_and_find_pull_request_use_index() -> None:
    pr_json = {
        "index": 7,
        "url": "https://sc-cd.invalid/pr/7",
        "source": "rpa/x",
        "target": "release/v1.0",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=pr_json)
        return httpx.Response(200, json={"values": [pr_json]})

    with _client_with(handler) as client:
        created = client.create_pull_request(REF, "rpa/x", "release/v1.0", "t", "b")
        found = client.find_pull_request(REF, "rpa/x", "release/v1.0")
    assert created == found
    assert created.index == 7


def test_add_pr_comment_posts_to_index_comments() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    with _client_with(handler) as client:
        client.add_pull_request_comment(REF, 7, "доп. коммит по ревью")
    assert seen["path"] == f"{BASE}{REF.path}/pulls/7/comments"
    assert seen["body"] == {"text": "доп. коммит по ревью"}
