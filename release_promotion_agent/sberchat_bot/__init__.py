"""Интерфейс чат-бота: диалог с инженером и оба чекпоинта подтверждения.

Реализуется как второй адаптер к оркестратору наравне с CLI: ядро не
зависит от способа общения с человеком.

Используется официальная SDK SberChat (dialog_bot_sdk).
"""

from release_promotion_agent.sberchat_bot.bot import SberChatBot, create_bot

__all__ = ["SberChatBot", "create_bot"]
