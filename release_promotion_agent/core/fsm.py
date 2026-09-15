"""Конечный автомат сессии: состояния, разрешённые переходы и их запись.

Переход выполняется только если он есть в таблице TRANSITIONS. Каждый
переход отражается в состоянии сессии и в журнале аудита, поэтому по
журналу восстанавливается весь путь сессии.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import InvalidTransitionError
from release_promotion_agent.core.session import SessionStore


class SessionState(StrEnum):
    """Состояния сессии от старта до завершения.

    Порядок не произвольный: он повторяет ход работы инженера — сначала
    анализ, затем подтверждение плана, затем цикл по репозиториям. Какие
    переходы разрешены, задаёт таблица TRANSITIONS ниже; всё, чего в ней
    нет, считается ошибкой.

    Два состояния особые. AWAITING_PLAN_APPROVAL и AWAITING_PR_APPROVAL —
    это ожидание человека: сессия может стоять в них часами, и до выхода
    из первого агент не делает ни одной записи.
    """

    SESSION_STARTED = "SESSION_STARTED"
    PARAMS_COLLECTED = "PARAMS_COLLECTED"
    DIFF_ANALYZED = "DIFF_ANALYZED"
    PLAN_ANALYZED = "PLAN_ANALYZED"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    PLAN_CORRECTION = "PLAN_CORRECTION"
    PLAN_APPROVED = "PLAN_APPROVED"
    REPO_BRANCHING = "REPO_BRANCHING"
    REPO_COMMITTED = "REPO_COMMITTED"
    PR_OPENED = "PR_OPENED"
    AWAITING_PR_APPROVAL = "AWAITING_PR_APPROVAL"
    PR_CORRECTION = "PR_CORRECTION"
    REPO_DONE = "REPO_DONE"
    ALL_DONE = "ALL_DONE"


class RepoState(StrEnum):
    """Состояние отдельного репозитория внутри цикла по репозиториям."""

    PENDING = "PENDING"
    BRANCHING = "BRANCHING"
    COMMITTED = "COMMITTED"
    PR_OPENED = "PR_OPENED"
    AWAITING_PR_APPROVAL = "AWAITING_PR_APPROVAL"
    DONE = "DONE"


# Ключ — текущее состояние, значение — множество разрешённых следующих.
TRANSITIONS: MappingProxyType[SessionState, frozenset[SessionState]] = MappingProxyType(
    {
        # Анализ: параметры → diff веток → инструкция → предложенный план.
        SessionState.SESSION_STARTED: frozenset({SessionState.PARAMS_COLLECTED}),
        SessionState.PARAMS_COLLECTED: frozenset({SessionState.DIFF_ANALYZED}),
        SessionState.DIFF_ANALYZED: frozenset({SessionState.PLAN_ANALYZED}),
        SessionState.PLAN_ANALYZED: frozenset({SessionState.PLAN_PROPOSED}),
        SessionState.PLAN_PROPOSED: frozenset({SessionState.AWAITING_PLAN_APPROVAL}),
        # Цикл 1: инженер либо шлёт корректировки, либо подтверждает план.
        SessionState.AWAITING_PLAN_APPROVAL: frozenset(
            {SessionState.PLAN_CORRECTION, SessionState.PLAN_APPROVED}
        ),
        SessionState.PLAN_CORRECTION: frozenset({SessionState.PLAN_PROPOSED}),
        # После подтверждения плана начинается запись: цикл по репозиториям.
        SessionState.PLAN_APPROVED: frozenset({SessionState.REPO_BRANCHING}),
        SessionState.REPO_BRANCHING: frozenset({SessionState.REPO_COMMITTED}),
        SessionState.REPO_COMMITTED: frozenset({SessionState.PR_OPENED}),
        SessionState.PR_OPENED: frozenset({SessionState.AWAITING_PR_APPROVAL}),
        # Цикл 2: правки по ревью PR либо подтверждение репозитория.
        SessionState.AWAITING_PR_APPROVAL: frozenset(
            {SessionState.PR_CORRECTION, SessionState.REPO_DONE}
        ),
        SessionState.PR_CORRECTION: frozenset({SessionState.AWAITING_PR_APPROVAL}),
        # Есть ещё репозитории — следующий круг; иначе финал.
        SessionState.REPO_DONE: frozenset({SessionState.REPO_BRANCHING, SessionState.ALL_DONE}),
        # Терминальное состояние: переходов из него нет.
        SessionState.ALL_DONE: frozenset(),
    }
)


class SessionFSM:
    """Автомат одной сессии: хранит текущее состояние и разрешает переходы.

    Само состояние живёт не здесь, а в SessionStore — автомат только
    проверяет переход по таблице и записывает его. Поэтому у сессии одна
    точка правды и один журнал: каждый переход попадает в аудит, и по
    журналу восстанавливается весь путь сессии, а не только её текущее
    положение.

    Недопустимый переход поднимает InvalidTransitionError и состояние не
    меняет: порядок шагов нельзя нарушить ни случайно, ни намеренно.
    """

    def __init__(self, store: SessionStore, context: SessionContext) -> None:
        self._store = store
        self._context = context

    @property
    def state(self) -> SessionState:
        return SessionState(self._store.fsm_state)

    @property
    def context(self) -> SessionContext:
        return self._context

    @property
    def store(self) -> SessionStore:
        return self._store

    @classmethod
    def start(cls, context: SessionContext) -> SessionFSM:
        """Создаёт хранилище сессии и ставит начальное состояние."""
        store = SessionStore(
            session_id=context.session_id,
            user_id=context.user_id,
            fsm_state=SessionState.SESSION_STARTED,
            release_id=context.release_id,
        )
        store.append_audit("SESSION_STARTED", {"release_id": context.release_id})
        return cls(store, context)

    def can_transition(self, new_state: SessionState) -> bool:
        return new_state in TRANSITIONS[self.state]

    def transition_to(self, new_state: SessionState) -> None:
        current = self.state
        if not self.can_transition(new_state):
            raise InvalidTransitionError(
                f"переход {current} -> {new_state} отсутствует в таблице переходов"
            )
        self._store.set_fsm_state(new_state)
        self._store.append_audit("FSM_TRANSITION", {"from": str(current), "to": str(new_state)})
