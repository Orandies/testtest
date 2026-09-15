"""Иерархия ошибок агента.

Сбои внешних вызовов обрабатываются ретраями внутри операций и в главный
автомат сессии не выносятся.
"""

from __future__ import annotations


class AgentError(Exception):
    """Базовая ошибка агента."""


class ConfigError(AgentError):
    """Отсутствуют или некорректны параметры конфигурации и секреты.

    Поднимается при старте, до любого сетевого вызова, и содержит список
    всех обнаруженных проблем сразу.
    """


class InvalidTransitionError(AgentError):
    """Запрошен переход, которого нет в таблице переходов автомата."""


class UnauthorizedUserError(AgentError):
    """Команда пришла от пользователя вне списка разрешённых."""


class SourceControlError(AgentError):
    """Отказ SourceControl API: 4xx либо исчерпанные ретраи."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EscalationError(AgentError):
    """Автоматика остановлена, дальше нужен человек: три неудачные попытки
    подряд, повтор одной и той же ошибки или недоступность модели."""


class EngineUnavailableError(AgentError):
    """Модель недоступна дольше порога. Инженер получает исходный diff и
    инструкцию, чтобы продолжить вручную."""


class ConfluenceError(AgentError):
    """Отказ Confluence API: 4xx/5xx либо ошибка авторизации."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
