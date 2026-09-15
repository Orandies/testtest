"""Ядро агента: управление состоянием сессии."""

from __future__ import annotations

from release_promotion_agent.core.audit_chain import (
    EVENT_BRANCH_CREATED,
    EVENT_COMMIT_CREATED,
    EVENT_DIFF_ANALYZED,
    EVENT_INTENT_READ,
    EVENT_PLAN_APPROVED,
    EVENT_PLAN_PROPOSED,
    EVENT_PR_APPROVED,
    EVENT_PR_OPENED,
    EVENT_RECONCILIATION_DONE,
    EVENT_SESSION_COMPLETED,
    EVENT_VALIDATION_RESULT,
)
from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import (
    ConfigError,
    EngineUnavailableError,
    EscalationError,
    SourceControlError,
)
from release_promotion_agent.core.fsm import RepoState, SessionFSM, SessionState
from release_promotion_agent.core.logging_setup import set_log_context
from release_promotion_agent.core.redaction import Redactor
from release_promotion_agent.core.session import (
    Approval,
    AuditEvent,
    LlmCall,
    PlanItem,
    RepoTask,
    SessionStore,
)

__all__ = [
    "SessionContext",
    "SessionStore",
    "SessionFSM",
    "SessionState",
    "RepoState",
    "RepoTask",
    "PlanItem",
    "Approval",
    "LlmCall",
    "AuditEvent",
    "set_log_context",
    "Redactor",
    "EngineUnavailableError",
    "EscalationError",
    "SourceControlError",
    "ConfigError",
    # События аудита
    "EVENT_BRANCH_CREATED",
    "EVENT_COMMIT_CREATED",
    "EVENT_DIFF_ANALYZED",
    "EVENT_INTENT_READ",
    "EVENT_PLAN_APPROVED",
    "EVENT_PLAN_PROPOSED",
    "EVENT_PR_OPENED",
    "EVENT_PR_APPROVED",
    "EVENT_RECONCILIATION_DONE",
    "EVENT_SESSION_COMPLETED",
    "EVENT_VALIDATION_RESULT",
]
