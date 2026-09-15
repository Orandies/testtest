"""Ответ модели: текст и расход токенов."""

from dataclasses import dataclass

from release_promotion_agent.models.usage import UsageStats


@dataclass(slots=True)
class ChatResponse:
    """Ответ языковой модели."""

    text: str
    usage: UsageStats
