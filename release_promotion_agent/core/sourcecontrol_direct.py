"""
Прямой клиент для работы с Source Control API через PAT-токен.
Заменяет необходимость в MCP-сервере.
"""
import os
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

class SourceControlDirectClient:
    def __init__(self, base_url: str, token: str, project_key: str, repo_slug: str):
        """
        :param base_url: Базовый URL API (например, https://api.sc-ci.sber.ru/sc/api/v3)
        :param token: PAT-токен (Ключ развёртывания)
        :param project_key: Ключ проекта (часть ID репозитория до слэша, например SA-SDVP00001234 -> SA-SDVP00001234 или проект)
        :param repo_slug: Слаг репозитория (обычно совпадает с именем)
        
        Примечание: В Bitbucket/Stash API путь часто выглядит как /projects/KEY/repos/SLUG
        Если у вас полный ID репозитория 'sa-sdvp00001234', возможно, это и есть slug, а проект нужно узнать.
        Для упрощения предположим, что пользователь вводит Project Key и Repo Slug отдельно или мы парсим ID.
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.project_key = project_key
        self.repo_slug = repo_slug
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Atlassian-Token": "no-check"
        })
        # Отключаем проверку SSL если нужно (для корпоративных самоподписанных сертификатов)
        # self.session.verify = False 
        # warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    def _get_api_path(self, endpoint: str) -> str:
        # Стандартный путь для Bitbucket Server / Source Control
        return f"{self.base_url}/projects/{self.project_key}/repos/{self.repo_slug}/{endpoint}"

    def get_repository_info(self) -> Dict[str, Any]:
        """Получить метаданные репозитория"""
        url = f"{self.base_url}/projects/{self.project_key}/repos/{self.repo_slug}"
        resp = self.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        return {
            "name": data.get("name"),
            "description": data.get("description"),
            "default_branch": data.get("defaultBranch", "refs/heads/master"),
            "project": data.get("project", {}).get("key")
        }

    def get_list_branches(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Список веток"""
        url = self._get_api_path("branches")
        params = {"limit": limit}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        branches = []
        for item in data.get("values", []):
            branches.append({
                "name": item.get("displayId"),
                "latest_commit": item.get("latestCommit"),
                "is_default": item.get("isDefault", False)
            })
        return branches

    def create_branch(self, name: str, from_branch: str = "master") -> Dict[str, Any]:
        """Создать ветку"""
        # Сначала найдем хеш коммита исходной ветки
        branches = self.get_list_branches(limit=1000)
        start_point = None
        for b in branches:
            if b["name"] == from_branch or b["name"] == f"refs/heads/{from_branch}":
                start_point = b["latest_commit"]
                break
        
        if not start_point:
            # Если не нашли, попробуем взять master/main по умолчанию
            # В реальном API лучше сделать отдельный вызов get-commit
            raise ValueError(f"Исходная ветка {from_branch} не найдена")

        url = self._get_api_path("branches")
        payload = {
            "name": name,
            "startPoint": start_point
        }
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_file_content(self, path: str, at: str = "master") -> str:
        """Получить содержимое файла"""
        url = self._get_api_path("browse/" + path)
        params = {"at": at}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        # API возвращает JSON с lines или direct content в зависимости от версии
        data = resp.json()
        if "lines" in data:
            return "\n".join([line.get("text", "") for line in data["lines"]])
        elif "content" in data:
            return data["content"]
        return ""

    def create_or_update_file(self, path: str, content: str, message: str, branch: str):
        """Создать или обновить файл (через API commit)"""
        # Bitbucket Server API требует отправки файла в multipart или через специальный эндпоинт commit
        # Эндпоинт: /commit
        url = self._get_api_path("commit")
        
        # Формирование payload для коммита
        # Структура зависит от конкретной версии API SourceControl (Bitbucket/Stash)
        # Обычно это массив изменений
        changes = [
            {
                "path": path,
                "type": "MODIFY" if self._file_exists(path, branch) else "ADD",
                "content": content
            }
        ]
        
        payload = {
            "message": message,
            "branch": branch,
            "changes": changes
        }
        
        # Примечание: Реальный формат payload может отличаться в зависимости от версии SC API.
        # Часто используется multipart/form-data для файлов.
        # Ниже реализация через JSON, если API поддерживает, иначе нужна доработка под multipart.
        
        headers = self.session.headers.copy()
        # Попытка отправки JSON (если поддерживается версией API)
        resp = self.session.post(url, json=payload)
        
        if resp.status_code == 400 or resp.status_code == 415:
            # Если JSON не поддерживается, пробуем эмуляцию формы или другой формат
            # Для многих инсталляций Bitbucket Server нужен специфичный формат
            # Попробуем альтернативный путь: сначала получить файл, потом отправить patch? 
            # Нет, стандартный способ - это REST API commit.
            # Если ошибка, выведем её для отладки
            resp.raise_for_status()
            
        return resp.json()

    def _file_exists(self, path: str, branch: str) -> bool:
        try:
            self.get_file_content(path, branch)
            return True
        except:
            return False

    def list_commits(self, branch: str, limit: int = 10) -> List[Dict]:
        url = self._get_api_path("commits")
        params = {"until": branch, "limit": limit}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return [
            {"hash": c.get("id"), "message": c.get("message"), "author": c.get("authorDisplayName")}
            for c in data.get("values", [])
        ]
