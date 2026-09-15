"""Работа с языковой моделью: клиент, промпты и read-only инструменты.

Модель получает только инструменты чтения: diff веток, раздел инструкции,
текущий конфиг, отчёт сверки, проверка кандидата и его diff к текущему
состоянию. Инструментов записи у модели нет — ветки, коммиты и pull
request создаёт код агента после подтверждения человеком.

Клиент GigaChat поддерживает два режима аутентификации:
  - mTLS (сертификат + ключ)
  - Токен (credentials, OAuth)

Режим определяется автоматически на основе параметров конфигурации.
"""

from release_promotion_agent.llm.conversation import ConversationManager
from release_promotion_agent.llm.gigachat_client import GigaChatClient
from release_promotion_agent.llm.session import SessionManager
from release_promotion_agent.models.chat_response import ChatResponse
from release_promotion_agent.models.usage import UsageStats

__all__ = [
    "GigaChatClient",
    "ChatResponse",
    "UsageStats",
    "ConversationManager",
    "SessionManager",
]
