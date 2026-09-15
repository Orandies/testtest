"""Чтение Confluence и разбор плана установки.

Страница релиза — источник НАМЕРЕНИЯ: того, что по инструкции должно
измениться в конфигах. Второй источник, diff веток, живёт в analyzers и с
этим не смешивается.

Модуль умеет три вещи:

- ConfluenceClient — чтение страниц по идентификатору, заголовку и поиском;
- read_confluence_url — чтение страницы по ссылке из текста;
- разбор содержимого в DeployPlan: позиции «репозиторий, файл, ключ».

Ссылку принимает в трёх видах: с идентификатором страницы, с пространством
и заголовком, коротким адресом. Аутентификация — токен либо пара логина и
токена, в зависимости от того, что настроено.

Только чтение: агент никогда ничего не пишет в Confluence.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from atlassian import Confluence
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from release_promotion_agent.config import Config
from release_promotion_agent.core.errors import ConfluenceError

logger = logging.getLogger(__name__)

__all__ = [
    "ConfluenceClient",
    "DeployPlan",
    "DeployPlanChange",
    "ConfluencePage",
    "ConfluenceReadError",
    "get_confluence_page_by_id",
    "extract_deploy_plan_from_page",
    "read_confluence_url",
]


# ── Доменные модели ────────────────────────────────────────────────────


class ConfluencePage:
    """Прочитанная страница: метаданные, исходный HTML и текст.

    Содержимое хранится в двух видах. HTML — как пришло от сервера,
    текст — приведённый к markdown: именно он уходит модели, потому что
    разметка страницы для разбора смысла только мешает.
    """

    def __init__(
        self,
        page_id: str,
        title: str,
        space_key: str,
        body_html: str,
        body_markdown: str | None = None,
        url: str | None = None,
    ) -> None:
        self.page_id = page_id
        self.title = title
        self.space_key = space_key
        self.body_html = body_html
        self.body_markdown = body_markdown or _html_to_markdown(body_html)
        self.url = url or f"https://{space_key.lower()}.confluence.internal/pages/{page_id}"

    def to_markdown(self) -> str:
        """Конвертирует HTML body в Markdown."""
        return self.body_markdown


class DeployPlanChange:
    """Одна позиция плана установки: что изменить и где.

    Позиция без указания ключа относится к файлу целиком. При сверке с
    diff это важно: такая позиция покрывает любые изменения внутри файла,
    и они не попадут в расхождения как незапланированные.
    """

    def __init__(
        self,
        repo_key: str,
        file_path: str,
        key_path: str | None = None,
        change_kind: str = "CHANGED",
        new_value: str | None = None,
        description: str | None = None,
        source_ref: str | None = None,
    ) -> None:
        self.repo_key = repo_key
        self.file_path = file_path
        self.key_path = key_path
        self.change_kind = change_kind
        self.new_value = new_value
        self.description = description
        self.source_ref = source_ref


class DeployPlan:
    """План установки, разобранный из страницы релиза, — НАМЕРЕНИЕ.

    Второй из двух источников агента: он говорит, что по инструкции
    должно измениться. Первый источник, diff веток, говорит, что
    изменилось на самом деле. Смешивать их нельзя — расхождения между
    ними и есть то, ради чего агент нужен.
    """

    def __init__(
        self,
        release_id: str,
        target_env: str,
        changes: list[DeployPlanChange],
        summary: str = "",
        source_page_id: str | None = None,
    ) -> None:
        self.release_id = release_id
        self.target_env = target_env
        self.changes = changes
        self.summary = summary
        self.source_page_id = source_page_id

    def changes_for(self, repo_key: str) -> list[DeployPlanChange]:
        """Фильтрует изменения по репозиторию."""
        return [c for c in self.changes if c.repo_key == repo_key]

    def __len__(self) -> int:
        return len(self.changes)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в словарь для JSON-ответа."""
        return {
            "release_id": self.release_id,
            "target_env": self.target_env,
            "summary": self.summary,
            "changes": [
                {
                    "repo": c.repo_key,
                    "file": c.file_path,
                    "key_path": c.key_path,
                    "kind": c.change_kind,
                    "description": c.description,
                }
                for c in self.changes
            ],
        }


# ── Вспомогательные функции ────────────────────────────────────────────


def _html_to_markdown(html: str) -> str:
    """Минимальный конвертер HTML → Markdown."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup
    text = body.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_page_identifier(url_or_id: str) -> dict[str, Any]:
    """Парсит URL или ID в унифицированный формат.

    Поддерживаемые форматы:
    - Простой ID: "123456"
    - URL с pageId: ".../pages/123456"
    - URL с query param: "...?pageId=123456"
    - /display/SPACE/Title: ".../display/DEV/Release+Plan"
    - Shortcode: ".../x/AB123"
    """
    if url_or_id.isdigit():
        return {"type": "id", "value": url_or_id}

    parsed = urlparse(url_or_id)
    query_params = parse_qs(parsed.query)

    # Поиск в query params
    for key in ("pageId", "pageid"):
        if key in query_params:
            return {"type": "id", "value": query_params[key][0]}

    # Поиск в пути: /pages/123456
    path_id_match = re.search(r"/pages/(\d+)", parsed.path)
    if path_id_match:
        return {"type": "id", "value": path_id_match.group(1)}

    # /display/SPACE/Title
    display_match = re.search(r"/display/([^/]+)/(.+)", parsed.path)
    if display_match:
        space_key = display_match.group(1)
        title = unquote(display_match.group(2)).replace("+", " ")
        return {"type": "title", "space": space_key, "title": title}

    # По умолчанию считаем что это ID
    return {"type": "id", "value": url_or_id}


def _get_confluence_client(config: Config | None = None) -> Confluence:
    """Создаёт экземпляр atlassian.Confluence из настроек проекта.

    Использует те же переменные окружения, что и текущий Config:
    - CONFLUENCE_BASE_URL
    - CONFLUENCE_TOKEN
    """
    if config is None:
        try:
            config = Config.load()
        except Exception as exc:
            raise ConfluenceError(f"Не удалось загрузить конфигурацию: {exc}") from exc

    if not config.has_confluence:
        raise ConfluenceError(
            "Confluence не настроен. Укажите CONFLUENCE_BASE_URL и CONFLUENCE_TOKEN."
        )

    base_url = config.confluence_base_url or ""
    token = config.confluence_token.get_secret_value() if config.confluence_token else ""

    if not base_url or not token:
        raise ConfluenceError("CONFLUENCE_BASE_URL или CONFLUENCE_TOKEN не заданы.")

    return Confluence(
        url=base_url,
        token=token,
        # Значение приходит из конфигурации, а не зашито в код: по умолчанию
        # сертификат проверяется, при заданном CONFLUENCE_CA_BUNDLE — по
        # внутреннему удостоверяющему центру.
        verify_ssl=config.confluence_tls_verify,
    )


def _parse_changes(text: str) -> list[DeployPlanChange]:
    """Извлекает изменения из текста страницы (deploy-plan)."""
    changes: list[DeployPlanChange] = []

    # Паттерн 1: табличный формат repo|file|key
    repo_file_pattern = re.compile(
        r"([\w-]+/[\w-]+/[\w-]+)\s*[|,]\s*"
        r"([\w/.-]+)\s*[|,]?\s*([\w.]+)?\s*[|,]?\s*(.*)",
        re.MULTILINE,
    )
    for match in repo_file_pattern.finditer(text):
        repo = match.group(1).strip()
        file_path = match.group(2).strip()
        key_path = match.group(3).strip() if match.group(3) else None
        description = match.group(4).strip() or None

        if not any(c.repo_key == repo and c.file_path == file_path for c in changes):
            changes.append(
                DeployPlanChange(
                    repo_key=repo,
                    file_path=file_path,
                    key_path=key_path if key_path else None,
                    description=description,
                )
            )

    # Паттерн 2: список с изменениями repo/file → key
    item_pattern = re.compile(
        r"[-•*]\s*([\w-]+/[\w-]+/[\w-]+)\s*:\s*"
        r"([\w/.-]+)\s*→?\s*(\w+)(?:\s*(.+?))?(?=\n[-•*]|\Z)",
        re.MULTILINE,
    )
    for match in item_pattern.finditer(text):
        repo = match.group(1).strip()
        file_path = match.group(2).strip()
        key_path = match.group(3).strip()
        description = match.group(4).strip() if match.group(4) else None

        if not any(c.repo_key == repo and c.file_path == file_path for c in changes):
            changes.append(
                DeployPlanChange(
                    repo_key=repo,
                    file_path=file_path,
                    key_path=key_path if key_path else None,
                    description=description,
                )
            )

    return changes


def _extract_field(text: str, patterns: list[str]) -> str | None:
    """Извлекает поле из текста по списку паттернов."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_page_id_from_search_result(result: dict) -> str | None:
    """Извлекает page_id из результата поиска CQL API.

    atlassian-python-api возвращает ID двумя способами:
    - result['id'] — при прямом GET к /content/{id}
    - result['content']['id'] — при поиске через /search
    """
    return result.get("id") or result.get("content", {}).get("id")


def _build_deploy_plan(page: ConfluencePage) -> DeployPlan:
    """Строит DeployPlan из содержимого страницы."""
    text = page.to_markdown()
    changes = _parse_changes(text)

    release_id = (
        _extract_field(
            text,
            [
                r"release[_\s]?id[:\s]+([\w.-]+)",
                r"release[_\s]?number[:\s]+([\w.-]+)",
                r"version[:\s]+([\w.-]+)",
            ],
        )
        or page.title
    )

    target_env = (
        _extract_field(
            text,
            [
                r"target[_\s]?env[:\s]+([\w-]+)",
                r"environment[:\s]+([\w-]+)",
                r"стенд[:\s]+([\w-]+)",
            ],
        )
        or "unknown"
    )

    summary = text[:500] if len(text) > 500 else text

    return DeployPlan(
        release_id=release_id,
        target_env=target_env,
        changes=changes,
        summary=summary,
        source_page_id=page.page_id,
    )


# ── LangChain Tools ────────────────────────────────────────────────────


@tool
def get_confluence_page_by_id(page_id_or_url: str) -> str:
    """
    Получает содержимое страницы Confluence.
    Принимает либо уникальный ID страницы (например, '123456'),
    либо полную ссылку на неё.

    Используй этот инструмент, когда нужно проанализировать содержимое
    Confluence-страницы и подготовить краткую сводку (summary).

    Args:
        page_id_or_url: ID страницы или URL (например, https://confluence/pages/123456)

    Returns:
        Строка с заголовком и содержимым страницы (до 20000 символов).
    """
    try:
        client = _get_confluence_client()
        identifier = _extract_page_identifier(page_id_or_url)

        if identifier["type"] == "id":
            page_data = client.get_page_by_id(
                page_id=identifier["value"], expand="body.view,body.storage,title"
            )
        else:
            page_data = client.get_page_by_title(
                space=identifier["space"],
                title=identifier["title"],
                expand="body.view,body.storage,title",
            )

        if not page_data:
            return f"Страница по запросу '{page_id_or_url}' не найдена."

        html = page_data.get("body", {}).get("storage", {}).get("value", "")
        markdown = _html_to_markdown(html) if html else ""
        title = page_data.get("title", "Без заголовка")
        space_key = page_data.get("space", {}).get("key", "UNKNOWN")
        page_id = page_data.get("id", "")

        result = f"📄 {title} [Space: {space_key}, ID: {page_id}]\n\n"
        if markdown:
            result += markdown[:20000]
        else:
            result += "Страница пуста или содержит только вложения."

        return result

    except ConfluenceError as e:
        return f"❌ Ошибка конфигурации Confluence: {e}"
    except Exception as e:
        return f"❌ Ошибка при обращении к Confluence: {e}"


@tool
def extract_deploy_plan_from_page(page_id_or_url: str) -> str:
    """
    Извлекает структурированный deploy-plan из инструкции к релизу.
    Парсит репозитории, файлы, пути ключей и описания изменений.

    Используй этот инструмент для получения плана изменений из страницы
    с инструкцией к релизу.

    Args:
        page_id_or_url: ID страницы или URL инструкции к релизу.

    Returns:
        JSON с планом изменений (release_id, target_env, список changes).
    """
    try:
        client = _get_confluence_client()
        identifier = _extract_page_identifier(page_id_or_url)

        if identifier["type"] == "id":
            page_data = client.get_page_by_id(
                page_id=identifier["value"], expand="body.storage,title"
            )
        else:
            page_data = client.get_page_by_title(
                space=identifier["space"], title=identifier["title"], expand="body.storage,title"
            )

        if not page_data:
            return "❌ Страница не найдена."

        html = page_data.get("body", {}).get("storage", {}).get("value", "")
        title = page_data.get("title", "Без заголовка")
        space_key = page_data.get("space", {}).get("key", "UNKNOWN")
        page_id = page_data.get("id", "")

        page = ConfluencePage(
            page_id=page_id,
            title=title,
            space_key=space_key,
            body_html=html,
        )

        plan = _build_deploy_plan(page)

        if not plan.changes:
            return (
                f"📦 Deploy Plan '{plan.release_id}' (env: {plan.target_env})\n"
                f"Изменения не найдены. Попробуй get_confluence_page_by_id для полного текста."
            )

        plan_info = f"📦 Deploy Plan '{plan.release_id}' (env: {plan.target_env})"
        return plan_info + "\n" + str(plan.to_dict())

    except ConfluenceError as e:
        return f"❌ Ошибка конфигурации Confluence: {e}"
    except Exception as e:
        return f"❌ Ошибка парсинга deploy-plan: {e}"


# ── ConfluenceClient (совместимый с текущим кодом) ────────────────────


class ConfluenceClient:
    """Чтение страниц Confluence: по идентификатору, по заголовку, поиском.

    Внутри работает библиотека atlassian-python-api, а не самописный
    HTTP-клиент: разбор ответов и совместимость с версиями сервера
    остаются на её стороне.

    Только чтение. Агент никогда ничего не пишет в Confluence: страница
    релиза — источник намерения, и менять источник, по которому сам же
    сверяешься, нельзя.

    Проверка сертификата сервера приходит параметром из конфигурации.
    Отключать её — крайняя мера: подменённая страница станет для агента
    законным основанием изменить конфиги.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        username: str | None = None,
        timeout: float = 30.0,
        verify_ssl: bool | str = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._verify_ssl = verify_ssl

        self._client = Confluence(
            url=base_url,
            token=token,
            verify_ssl=verify_ssl,
        )

    def get_page_by_id(self, page_id: str, *, expand: str = "body.storage") -> ConfluencePage:
        """Получает страницу по ID (совместимо с оригинальным интерфейсом)."""
        try:
            data = self._client.get_page_by_id(page_id, expand=expand)
            if not data:
                raise ConfluenceError(f"Страница не найдена: {page_id}")

            title = data.get("title", "Untitled")
            space = data.get("space", {})
            space_key = space.get("key", "UNKNOWN")
            html = data.get("body", {}).get("storage", {}).get("value", "")
            url = data.get("_links", {}).get("webui", "")
            if url:
                url = f"{self._base_url}{url}"

            return ConfluencePage(
                page_id=page_id,
                title=title,
                space_key=space_key,
                body_html=html,
                url=url,
            )
        except Exception as exc:
            raise ConfluenceError(f"не удалось прочитать страницу {page_id}: {exc}") from exc

    def get_page_by_title(
        self, title: str, space_key: str, *, expand: str = "body.storage"
    ) -> ConfluencePage:
        """Получает страницу по названию и ключу пространства."""
        try:
            data = self._client.get_page_by_title(space=space_key, title=title, expand=expand)
            if not data:
                raise ConfluenceError(
                    f"Страница '{title}' в пространстве '{space_key}' не найдена."
                )

            page_id = data.get("id", "")
            page_title = data.get("title", "Untitled")
            html = data.get("body", {}).get("storage", {}).get("value", "")
            url = data.get("_links", {}).get("webui", "")
            if url:
                url = f"{self._base_url}{url}"

            return ConfluencePage(
                page_id=page_id,
                title=page_title,
                space_key=space_key,
                body_html=html,
                url=url,
            )
        except Exception as exc:
            raise ConfluenceError(f"не удалось прочитать страницу «{title}»: {exc}") from exc

    def search(self, cql: str, limit: int = 10) -> list[dict]:
        """Ищет страницы через CQL (Confluence Query Language)."""
        try:
            # atlassian-python-api не имеет публичного метода search,
            # используем requests с авторизацией из клиента
            url = f"{self._base_url}/rest/api/search"
            params = {"cql": cql, "limit": limit}
            headers = {"Accept": "application/json"}
            # atlassian.Confluence использует token auth
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"

            import requests

            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self._timeout,
                verify=self._verify_ssl,
            )
            if response.status_code != 200:
                raise ConfluenceError(f"поиск по CQL не удался: HTTP {response.status_code}")
            return response.json().get("results", [])
        except Exception as exc:
            raise ConfluenceError(f"поиск по CQL не удался: {exc}") from exc


# ── ConfluenceReadError и read_confluence_url (совместимость) ─────────


class ConfluenceReadError(Exception):
    """Ошибка при чтении страницы Confluence."""

    pass


# Паттерн для извлечения page_id из Confluence URL
CONFLUENCE_PATTERNS = [
    # /pages/123456789
    (r"/pages/(\d+)", "page_id"),
    # /display/SPACE/123456789
    (r"/display/[^/]+/(\d+)", "page_id"),
    # /x/SHORTCODE (соглашения страниц)
    (r"/x/([A-Z0-9]+)", "shortcode"),
    # /spaces/~username/pages/share/page.action?pageId=123
    (r"pageId=(\d+)", "page_id"),
    # /spaces/{space}/pages/{id}/{title}
    (r"/spaces/[^/]+/pages/(\d+)/", "page_id"),
    # /display/SPACE/TITLE (wiki markup URL — ищем по space+title)
    (r"/display/([^/]+)/([^/?]+)", "space_title"),
]

CONFLUENCE_HOSTS = [
    "confluence",
    "wiki",
    "docs",
]


def _is_confluence_url(url: str) -> bool:
    """Проверяет, что URL ведёт на Confluence."""
    host = url.lower()
    return any(h in host for h in CONFLUENCE_HOSTS) and any(
        p in url for p in ["/pages/", "/display/", "/x/", "?pageId=", "/spaces/"]
    )


def _extract_page_id_from_url(url: str) -> dict[str, str]:
    """Извлекает page_id или shortcode из URL (старая сигнатура для совместимости)."""
    for pattern, key in CONFLUENCE_PATTERNS:
        match = re.search(pattern, url)
        if match:
            if key == "space_title":
                # Для space_title возвращаем space/title
                return {key: f"{match.group(1)}/{match.group(2)}"}
            return {key: match.group(1)}
    return {}


def _extract_base_url_from_url(url: str) -> str:
    """Извлекает базовый URL (без пути и параметров)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def read_confluence_url(
    url: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Прочитать содержимое Confluence-страницы по URL.

    Возвращает словарь, а не объект страницы: результат уходит прямо
    в диалог, где нужны только готовые поля, а не поведение объекта.

    Args:
        url: URL страницы Confluence.
        config: Конфигурация агента. Если None — пытается загрузить из окружения.

    Returns:
        Словарь с полями: title, body_html, body_text, page_id, url, error.

    Raises:
        ConfluenceReadError: Если не удалось прочитать страницу.
    """
    if not _is_confluence_url(url):
        raise ConfluenceReadError(f"URL не ведёт на Confluence: {url}")

    extracted = _extract_page_id_from_url(url)
    base_url = _extract_base_url_from_url(url)

    if not config:
        try:
            config = Config.load()
        except Exception as exc:
            raise ConfluenceReadError(f"Не удалось загрузить конфигурацию: {exc}") from exc

    if not config.has_confluence:
        raise ConfluenceReadError(
            "Confluence не настроен. Укажите CONFLUENCE_BASE_URL и CONFLUENCE_TOKEN в .env"
        )

    try:
        client = ConfluenceClient(
            base_url=config.confluence_base_url or base_url,
            token=config.confluence_token.get_secret_value(),
            timeout=30.0,
            verify_ssl=config.confluence_tls_verify,
        )

        page: ConfluencePage | None = None

        if "page_id" in extracted:
            page = client.get_page_by_id(extracted["page_id"])
        elif "space_title" in extracted:
            # Извлекаем из URL вида /display/SPACE/Title
            space = extracted["space_title"].split("/")[0]
            title = extracted["space_title"].split("/")[-1]
            try:
                page = client.get_page_by_title(title, space)
            except Exception:
                results = client.search(f'space = "{space}" AND title = "{title}"')
                if results:
                    page_id = _extract_page_id_from_search_result(results[0])
                    if page_id:
                        page = client.get_page_by_id(page_id)
        elif "shortcode" in extracted:
            results = client.search(f"title ~ '{extracted['shortcode']}'")
            if results:
                page_data = results[0]
                page_id = _extract_page_id_from_search_result(page_data)
                if page_id:
                    page = client.get_page_by_id(page_id)

        if page is None:
            try:
                results = client.search(
                    "type = page AND lastModified > startOfMonth('-7')",
                    limit=50,
                )
                if results:
                    page_id = _extract_page_id_from_search_result(results[0])
                    if page_id:
                        page = client.get_page_by_id(page_id)
            except Exception:
                pass

            if page is None:
                raise ConfluenceReadError(
                    f"Не удалось найти страницу по короткому коду "
                    f"'{extracted.get('shortcode')}'. Откройте страницу в браузере — "
                    "в адресной строке будет URL вида /pages/123456789 или "
                    "/display/SPACE/123456789. Скопируйте его и попробуйте снова."
                )

        body_html = page.body_html
        body_text = page.to_markdown()

        max_text_len = 50000
        if len(body_text) > max_text_len:
            body_text = body_text[:max_text_len] + "\n\n... (содержимое обрезано) ..."

        return {
            "title": page.title,
            "space_key": page.space_key,
            "page_id": page.page_id,
            "url": page.url,
            "body_html": body_html,
            "body_text": body_text,
            "error": None,
        }

    except ConfluenceReadError:
        raise
    except ConfluenceError as exc:
        raise ConfluenceReadError(f"Ошибка чтения Confluence: {exc}") from exc
    except Exception as exc:
        raise ConfluenceReadError(f"Ошибка чтения Confluence: {exc}") from exc
