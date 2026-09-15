"""Диалоговый режим: вопрос инженера, ответ модели.

Отдельный от релизного сценария путь. Здесь модель отвечает текстом и
ничего не меняет: ни веток, ни файлов, ни pull request.

Если в вопросе есть ссылка на страницу Confluence, агент читает её и
подкладывает содержимое в диалог — иначе модель отвечала бы про страницу,
которой не видела.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from release_promotion_agent.config import Config
from release_promotion_agent.llm import ConversationManager, GigaChatClient, SessionManager
from release_promotion_agent.models.chat_response import ChatResponse
from release_promotion_agent.tools.confluence_tool import (
    ConfluenceReadError,
    read_confluence_url,
)

__all__ = ["ChatAgent", "ConfluenceReadError"]

_log = logging.getLogger(__name__)

# Ссылка на страницу в тексте вопроса. Хвостовая пунктуация обрезается
# отдельно: точка в конце предложения не часть адреса.
_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


class ChatAgent:
    """Диалог с моделью: вопрос на входе, текстовый ответ на выходе.

    Хранит историю переписки, поэтому следующий вопрос понимается в
    контексте предыдущих, и считает израсходованные токены.

    Если в вопросе есть ссылка на страницу Confluence, агент читает её
    сам и добавляет содержимое в диалог перед тем, как обратиться к
    модели. Не прочиталась — вопрос всё равно уходит модели, просто без
    страницы: диалог не должен обрываться из-за недоступной ссылки.

    Инструментов записи у модели здесь нет. Это осознанно: диалоговый
    режим существует, чтобы разобраться и спросить, а не чтобы менять
    конфиги в обход подтверждений релизного сценария.
    """

    def __init__(
        self,
        config: Config | None = None,
    ) -> None:
        if config is None:
            config = Config.load()
        self._config = config
        self._client = GigaChatClient(config)
        self._conversation = ConversationManager()
        self._session = SessionManager()

    def process(self, request: str) -> ChatResponse:
        """Обработать запрос пользователя и вернуть ответ LLM.

        Если в запросе есть URL Confluence, страница будет автоматически
        прочитана и подставлена в контекст перед отправкой к GigaChat.

        Args:
            request: Текст запроса пользователя.

        Returns:
            ChatResponse с текстом ответа и метаданными.
        """
        # Проверяем, есть ли в запросе URL Confluence
        confluence_content: dict[str, Any] | None = None
        if "confluence" in request.lower() or self._mentions_confluence_host(request):
            confluence_content = self._try_read_confluence(request)

        # Добавляем пользовательский запрос в историю
        self._conversation.add_user(request)

        # Формируем сообщения для отправки в GigaChat
        messages = list(self._conversation.get_messages())

        if confluence_content:
            # Конфлюенс-контент вставляем как ДОПОЛНЕНИЕ к текущему запросу,
            # а не как system message — иначе GigaChatClient не добавит
            # свой системный промпт (он проверяет наличие SystemMessage).
            context_block = (
                f"\n\n--- Confluence page: {confluence_content['title']} ---\n"
                f"{confluence_content['body_text'][:10000]}\n"
                f"--- end ---\n"
            )
            # Дополняем последнее user сообщение (текущий запрос) контекстом
            if messages:
                last = messages[-1]
                if isinstance(last, dict):
                    last["content"] += context_block
                else:
                    messages.append({"role": "user", "content": context_block})

        try:
            response = self._client.ask(messages, session_id=self._session.id)
        except Exception as exc:
            # При ошибке LLM добавляем сообщение об ошибке в историю
            self._conversation.add_ai(
                f"Ошибка при обработке запроса: {exc}. Пожалуйста, попробуйте ещё раз."
            )
            raise

        # Обновляем историю
        self._conversation.add_ai(response.text)

        return response

    def _mentions_confluence_host(self, request: str) -> bool:
        """Упомянут ли в запросе адрес нашего Confluence.

        Адрес берётся из конфигурации: у разных контуров он разный, и держать
        его константой в коде значит привязать агент к одному стенду.
        """
        base_url = self._config.confluence_base_url
        if not base_url:
            return False
        host = base_url.split("//")[-1].split("/")[0]
        return bool(host) and host in request

    def _try_read_confluence(self, request: str) -> dict[str, Any] | None:
        """Читает страницу Confluence по первой рабочей ссылке из вопроса.

        Ссылок в тексте может быть несколько, и не каждая ведёт на
        Confluence, поэтому перебираются все до первой успешной. Если не
        прочиталась ни одна, возвращается None: вопрос уйдёт модели без
        страницы, а причина останется в журнале.
        """
        for raw_url in _URL.findall(request):
            url = raw_url.rstrip(".,;:!?)]\"'")
            try:
                return read_confluence_url(url, self._config)
            except ConfluenceReadError as exc:
                _log.info("страница не прочитана: %s (%s)", url, exc)
        return None
