"""Расход токенов на один запрос к модели."""

from dataclasses import dataclass


@dataclass(slots=True)
class UsageStats:
    """Статистика использования токенов GigaChat."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hits: int = 0
