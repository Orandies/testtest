"""Клиент GigaChat с поддержкой двух режимов аутентификации.

Режим выбирается автоматически при создании клиента:
  - mTLS: если заданы GIGACHAT_CERT_FILE + GIGACHAT_KEY_FILE.
  - Токен: если задан GIGACHAT_CREDENTIALS.
"""

from __future__ import annotations

from gigachat import session_id_cvar
from langchain_gigachat.chat_models import GigaChat

from release_promotion_agent.config import Config
from release_promotion_agent.models.chat_response import ChatResponse
from release_promotion_agent.models.usage import UsageStats

__all__ = ["GigaChatClient"]


class GigaChatClient:
    """Клиент для работы с GigaChat.

    Поддерживает два режима аутентификации:
    1. mTLS (взаимная TLS) — через файлы сертификата и ключа.
    2. Token — через токен (credentials), полученный по OAuth.

    Режим определяется автоматически на основе параметров конфигурации.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._llm = self._create_llm(config)

    @staticmethod
    def _create_llm(config: Config) -> GigaChat:
        """Создаёт экземпляр GigaChat с соответствующей аутентификацией."""
        kwargs: dict = {}

        if config.use_mtls:
            # mTLS-аутентификация.
            kwargs["cert_file"] = config.gigachat_cert_file
            kwargs["key_file"] = config.gigachat_key_file
            if config.gigachat_key_file_password is not None:
                kwargs["key_file_password"] = config.gigachat_key_file_password.get_secret_value()
        elif config.use_token:
            # Токен (credentials).
            kwargs["credentials"] = config.gigachat_credentials.get_secret_value()
            if config.gigachat_scope:
                kwargs["scope"] = config.gigachat_scope
            kwargs["model_name"] = config.gigachat_model
            kwargs["auth_url"] = config.gigachat_auth_url
            kwargs["base_url"] = config.gigachat_base_url
            kwargs["verify_ssl_certs"] = config.gigachat_verify_ssl
        else:
            # На случай если конфигурация прошла валидацию, но ни один режим
            # не активен (не должно случаться).
            raise ValueError(
                "Не определён режим аутентификации GigaChat: "
                "необходимо GIGACHAT_CERT_FILE+GIGACHAT_KEY_FILE (mTLS) "
                "или GIGACHAT_CREDENTIALS."
            )

        return GigaChat(**kwargs)

    def ask(self, messages: list, session_id: str | None = None) -> ChatResponse:
        """Отправить запрос к модели и вернуть ответ.

        Args:
            messages: Список сообщений (формат LangChain).
            session_id: Идентификатор сессии для LangChain.

        Returns:
            ChatResponse с текстом ответа и статистикой использования.
        """
        session_token: object | None = None

        if session_id:
            session_token = session_id_cvar.set(session_id)

        try:
            response = self._llm.invoke(messages)
        finally:
            if session_token is not None:
                session_id_cvar.reset(session_token)

        # Извлекаем метаданные о использовании.
        usage_meta = response.usage_metadata
        if usage_meta:
            input_details = usage_meta.get("input_token_details", {})
            cache_hits = input_details.get("cache_read", 0)
        else:
            cache_hits = 0

        content = response.content
        if isinstance(content, list):
            # Некоторые модели возвращают список блоков.
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        return ChatResponse(
            text=str(content),
            usage=UsageStats(
                input_tokens=usage_meta.get("input_tokens", 0) if usage_meta else 0,
                output_tokens=usage_meta.get("output_tokens", 0) if usage_meta else 0,
                total_tokens=usage_meta.get("total_tokens", 0) if usage_meta else 0,
                cache_hits=cache_hits,
            ),
        )
