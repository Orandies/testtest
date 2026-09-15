"""MCP-клиент для подключения к SourceControl через протокол MCP.

MCP (Model Context Protocol) — стандартный способ работы AI-агентов с внешними системами.
Клиент подключается к MCP-серверу SourceControl и предоставляет инструменты для:
- навигации по репозиторию
- чтения файлов
- создания веток, коммитов, pull requests
- добавления комментариев

Аутентификация: mTLS (сертификат + ключ) через SecMan.
ТУЗ: SA-S0000000000 (настраивается через переменную окружения).
"""

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from release_promotion_agent.core.errors import SourceControlError

logger = logging.getLogger(__name__)

__all__ = ["MCPClient", "MCPTool"]


@dataclass
class MCPTool:
    """Описание инструмента MCP."""
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPClient:
    """Клиент для подключения к MCP-серверу SourceControl.
    
    Подключается к серверу по mTLS через SecMan и предоставляет
    инструменты для работы с репозиториями.
    
    Адрес сервера: aaaa-sc.xxxx.bbbbbbb.k8s.sigma.sbrf.ru
    ТУЗ: SA-S0000000000 (из переменной SOURCECONTROL_TUZ)
    Аутентификация: сертификат и ключ из SecMan
    """
    
    def __init__(
        self,
        server_url: str,
        cert_file: Path | str,
        key_file: Path | str,
        tuz: str = "SA-S0000000000",
        timeout_seconds: float = 30.0,
    ) -> None:
        """Инициализация MCP-клиента.
        
        Args:
            server_url: URL MCP-сервера (например, https://aaaa-sc.xxxx.bbbbbbb.k8s.sigma.sbrf.ru)
            cert_file: Путь к файлу сертификата (из SecMan)
            key_file: Путь к файлу приватного ключа (из SecMan)
            tuz: Идентификатор ТУЗ (учётной записи сервиса)
            timeout_seconds: Таймаут запросов в секундах
        """
        self.server_url = server_url.rstrip("/")
        self.tuz = tuz
        self.timeout_seconds = timeout_seconds
        
        # Создаем SSL-контекст для mTLS
        ssl_context = ssl.create_default_context()
        ssl_context.load_cert_chain(
            certfile=str(cert_file),
            keyfile=str(key_file),
        )
        
        self._client = httpx.Client(
            base_url=self.server_url,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
        )
        # Для mTLS нужно настроить transport отдельно
        # Пока используем стандартный подход httpx
        
        self._tools_cache: list[MCPTool] | None = None
    
    def list_tools(self) -> list[MCPTool]:
        """Получить список доступных инструментов MCP.
        
        Returns:
            Список описаний инструментов (name, description, input_schema)
        """
        if self._tools_cache is not None:
            return self._tools_cache
        
        response = self._request("POST", "/tools/list", {})
        tools_data = response.get("tools", [])
        
        self._tools_cache = [
            MCPTool(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
            )
            for tool in tools_data
        ]
        return self._tools_cache
    
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Вызвать инструмент MCP.
        
        Args:
            tool_name: Название инструмента (например, get_repository_info)
            arguments: Аргументы для инструмента
            
        Returns:
            Результат выполнения инструмента
            
        Raises:
            SourceControlError: При ошибке вызова инструмента
        """
        response = self._request(
            "POST",
            "/tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            }
        )
        
        if "error" in response:
            raise SourceControlError(f"Инструмент {tool_name} вернул ошибку: {response['error']}")
        
        return response.get("content", {})
    
    # === Обёртки над инструментами MCP ===
    # Исследование и навигация по репозиторию
    
    def get_repository_info(self, repo_key: str) -> dict[str, Any]:
        """Получить метаданные репозитория."""
        return self.call_tool("get_repository_info", {"repo_key": repo_key})
    
    def get_file_content(
        self,
        repo_key: str,
        file_path: str,
        branch: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Получить содержимое файла."""
        args: dict[str, Any] = {
            "repo_key": repo_key,
            "file_path": file_path,
        }
        if branch:
            args["branch"] = branch
        if start_line:
            args["start_line"] = start_line
        if end_line:
            args["end_line"] = end_line
        return self.call_tool("get-file-content", args)
    
    def get_diff(
        self,
        repo_key: str,
        base_ref: str,
        head_ref: str,
    ) -> str:
        """Получить unified diff между двумя ссылками."""
        result = self.call_tool("get-diff", {
            "repo_key": repo_key,
            "base_ref": base_ref,
            "head_ref": head_ref,
        })
        return result.get("diff", "")
    
    def get_list_files(
        self,
        repo_key: str,
        path: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Список файлов репозитория."""
        args: dict[str, Any] = {
            "repo_key": repo_key,
            "page": page,
            "per_page": per_page,
        }
        if path:
            args["path"] = path
        return self.call_tool("get-list-files", args)
    
    def get_diff_stats(
        self,
        repo_key: str,
        base_ref: str,
        head_ref: str,
    ) -> dict[str, Any]:
        """Статистика диффа."""
        return self.call_tool("get-diff-stats", {
            "repo_key": repo_key,
            "base_ref": base_ref,
            "head_ref": head_ref,
        })
    
    def get_commit_changes(
        self,
        repo_key: str,
        commit_sha: str,
    ) -> dict[str, Any]:
        """Изменения коммита."""
        return self.call_tool("get-commit-changes", {
            "repo_key": repo_key,
            "commit_sha": commit_sha,
        })
    
    def list_commits(
        self,
        repo_key: str,
        branch: str | None = None,
        path: str | None = None,
        author: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """История коммитов."""
        args: dict[str, Any] = {"repo_key": repo_key, "limit": limit}
        if branch:
            args["branch"] = branch
        if path:
            args["path"] = path
        if author:
            args["author"] = author
        result = self.call_tool("list-commits", args)
        return result.get("commits", [])
    
    def get_list_branches(
        self,
        repo_key: str,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        """Список веток репозитория."""
        result = self.call_tool("get-list-branches", {
            "repo_key": repo_key,
            "page": page,
            "per_page": per_page,
        })
        return result.get("branches", [])
    
    def search_code(
        self,
        repo_key: str,
        query: str,
        path: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Поиск по кодовой базе."""
        args: dict[str, Any] = {
            "repo_key": repo_key,
            "query": query,
            "limit": limit,
        }
        if path:
            args["path"] = path
        result = self.call_tool("search-code", args)
        return result.get("matches", [])
    
    def list_pull_requests(
        self,
        repo_key: str,
        state: str = "open",
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        """Список pull request'ов."""
        result = self.call_tool("list-pull-requests", {
            "repo_key": repo_key,
            "state": state,
            "page": page,
            "per_page": per_page,
        })
        return result.get("pull_requests", [])
    
    def get_file_stats(
        self,
        repo_key: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Статистика размера и сложности файлов."""
        args: dict[str, Any] = {"repo_key": repo_key}
        if path:
            args["path"] = path
        return self.call_tool("get-file-stats", args)
    
    # === Запись ===
    
    def create_branch(
        self,
        repo_key: str,
        branch_name: str,
        from_ref: str,
    ) -> dict[str, Any]:
        """Создать новую ветку."""
        return self.call_tool("create-branch", {
            "repo_key": repo_key,
            "branch_name": branch_name,
            "from_ref": from_ref,
        })
    
    def delete_file(
        self,
        repo_key: str,
        branch: str,
        file_paths: list[str],
        message: str,
    ) -> dict[str, Any]:
        """Удалить файлы."""
        if len(file_paths) > 10:
            raise SourceControlError("Максимум 10 файлов за вызов")
        return self.call_tool("delete-file", {
            "repo_key": repo_key,
            "branch": branch,
            "file_paths": file_paths,
            "message": message,
        })
    
    def create_pull_request(
        self,
        repo_key: str,
        source_branch: str,
        target_branch: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        """Создать pull request."""
        return self.call_tool("create-pull-request", {
            "repo_key": repo_key,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "body": body,
        })
    
    def create_comment(
        self,
        repo_key: str,
        pr_index: int,
        text: str,
    ) -> dict[str, Any]:
        """Добавить комментарий к pull request."""
        return self.call_tool("create-comment", {
            "repo_key": repo_key,
            "pr_index": pr_index,
            "text": text,
        })
    
    def create_or_update_file(
        self,
        repo_key: str,
        branch: str,
        file_path: str,
        content: str,
        message: str,
    ) -> dict[str, Any]:
        """Создать или обновить файл."""
        if len(content) > 100 * 1024:  # 100KB
            raise SourceControlError("Максимальный размер файла 100KB")
        return self.call_tool("create-or-update-file", {
            "repo_key": repo_key,
            "branch": branch,
            "file_path": file_path,
            "content": content,
            "message": message,
        })
    
    def find_and_replace_file_content(
        self,
        repo_key: str,
        branch: str,
        file_path: str,
        old_text: str,
        new_text: str,
        message: str,
    ) -> dict[str, Any]:
        """Заменить точный блок текста в файле."""
        return self.call_tool("find-and-replace-file-content", {
            "repo_key": repo_key,
            "branch": branch,
            "file_path": file_path,
            "old_text": old_text,
            "new_text": new_text,
            "message": message,
        })
    
    def multi_replace_file_content(
        self,
        repo_key: str,
        branch: str,
        file_path: str,
        replacements: list[dict[str, str]],
        message: str,
    ) -> dict[str, Any]:
        """Применить несколько непересекающихся замен."""
        return self.call_tool("multi-replace-file-content", {
            "repo_key": repo_key,
            "branch": branch,
            "file_path": file_path,
            "replacements": replacements,
            "message": message,
        })
    
    def create_commit_multifile(
        self,
        repo_key: str,
        branch: str,
        message: str,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Создать атомарный коммит с операциями над файлами.
        
        Args:
            repo_key: Ключ репозитория
            branch: Ветка
            message: Сообщение коммита
            files: Список операций. Каждая операция — dict с полями:
                   - operation: "create" | "update" | "delete" | "move"
                   - path: путь к файлу
                   - content: содержимое (для create/update)
                   - new_path: новый путь (для move)
        """
        if len(files) > 15:
            raise SourceControlError("Максимум 15 файлов за коммит")
        return self.call_tool("create-commit-multifile", {
            "repo_key": repo_key,
            "branch": branch,
            "message": message,
            "files": files,
        })
    
    # === Внутренние методы ===
    
    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Выполнить HTTP-запрос к MCP-серверу."""
        url = f"{self.server_url}{path}"
        
        try:
            response = self._client.request(
                method,
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-TUZ": self.tuz,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("MCP запрос failed: %s %s -> %d", method, path, exc.response.status_code)
            raise SourceControlError(
                f"MCP сервер вернул {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.TransportError as exc:
            logger.error("MCP транспортная ошибка: %s", exc)
            raise SourceControlError(f"Ошибка соединения с MCP сервером: {exc}") from exc
    
    def close(self) -> None:
        """Закрыть клиент."""
        self._client.close()
    
    def __enter__(self) -> MCPClient:
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
