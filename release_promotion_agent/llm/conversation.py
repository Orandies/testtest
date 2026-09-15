"""Управление историей диалога (conversation).

Использует LangChain Message API (HumanMessage / AIMessage),
чтобы совместимо с любым провайдером через langchain-core.

Системный промпт загружается из папки prompts/.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from release_promotion_agent.prompts import SYSTEM_PROMPT

__all__ = ["ConversationManager"]


class ConversationManager:
    """История переписки, которая уходит модели при каждом обращении.

    Первым сообщением всегда идёт системный промпт, дальше вопросы
    инженера и ответы модели по порядку. Модель не помнит прошлые
    обращения сама — контекст создаёт именно эта история.

    Обрезки по длине пока нет: в длинном диалоге история растёт, а вместе
    с ней и расход токенов на каждом запросе.
    """

    def __init__(self, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._system_prompt = system_prompt
        self._messages: list[HumanMessage | AIMessage | SystemMessage] = [
            SystemMessage(content=system_prompt)
        ]

    def add_user(self, text: str) -> None:
        self._messages.append(HumanMessage(content=text))

    def add_ai(self, text: str) -> None:
        self._messages.append(AIMessage(content=text))

    def get_messages(self) -> list[HumanMessage | AIMessage | SystemMessage]:
        return list(self._messages)

    def clear(self) -> None:
        # Сохраняем системное сообщение при очистке
        self._messages = [SystemMessage(content=self._system_prompt)]

    def __len__(self) -> int:
        return len(self._messages)
