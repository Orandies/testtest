"""Инструменты агента: SourceControl и Confluence.

Публичные имена перечислены в _EXPORTS и подгружаются по требованию —
в момент первого обращения, а не при импорте пакета. Так сделано ради
одного свойства: работа с SourceControl не должна тянуть за собой
Confluence.

Раньше `import release_promotion_agent.tools.git_tool` подтягивал весь
Confluence-стек (atlassian, bs4, langchain), потому что этот файл
импортировал его сразу. Клиент SourceControl обходится одним httpx,
и запускать его тесты или контейнер, где Confluence не нужен, стало
невозможно без лишних зависимостей.

Confluence:
    ConfluenceClient          обёртка над atlassian.Confluence
    ConfluencePage            доменная модель страницы
    DeployPlan, DeployPlanChange   модели плана установки
    read_confluence_url       чтение страницы по URL (для ChatAgent)
    get_confluence_page_by_id      LangChain @tool: чтение страницы
    extract_deploy_plan_from_page  LangChain @tool: разбор плана релиза

SourceControl:
    SourceControlClient       ветки, коммиты, pull request. Без merge()

Разбор diff веток живёт не здесь, а в release_promotion_agent.analyzers:
это анализ, а не поход во внешнюю систему.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Имя → модуль, в котором оно живёт. Единственный источник правды
# и для __getattr__, и для __all__: список не разъедется с реальностью.
_EXPORTS: dict[str, str] = {
    "ConfluenceClient": "confluence_tool",
    "ConfluencePage": "confluence_tool",
    "ConfluenceReadError": "confluence_tool",
    "DeployPlan": "confluence_tool",
    "DeployPlanChange": "confluence_tool",
    "extract_deploy_plan_from_page": "confluence_tool",
    "get_confluence_page_by_id": "confluence_tool",
    "read_confluence_url": "confluence_tool",
    "SourceControlClient": "git_tool",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Подгружает модуль только тогда, когда из него что-то понадобилось."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value  # второй раз импорт уже не понадобится
    return value


def __dir__() -> list[str]:
    return __all__
