"""Системный промпт, собранный из четырёх частей.

Роль, правила, возможности и манера разговора лежат в отдельных файлах и
склеиваются в SYSTEM_PROMPT. Разделение не косметическое: правила меняются
редко и требуют внимания, манера разговора правится часто, — и правка
одного не задевает другое.
"""

from __future__ import annotations

from release_promotion_agent.prompts.capabilities import CAPABILITIES_PROMPT
from release_promotion_agent.prompts.conversation import CONVERSATION_PROMPT
from release_promotion_agent.prompts.role import ROLE_PROMPT
from release_promotion_agent.prompts.rules import RULES_PROMPT

__all__ = [
    "SYSTEM_PROMPT",
    "ROLE_PROMPT",
    "RULES_PROMPT",
    "CAPABILITIES_PROMPT",
    "CONVERSATION_PROMPT",
]

# ── Сборка полного системного промпта ──────────────────────────────────────


def _build_system_prompt() -> str:
    """Собирает полный системный промпт из отдельных частей."""
    parts = [ROLE_PROMPT, RULES_PROMPT, CAPABILITIES_PROMPT, CONVERSATION_PROMPT]
    return "\n\n".join(parts) + "\n"


SYSTEM_PROMPT = _build_system_prompt()
