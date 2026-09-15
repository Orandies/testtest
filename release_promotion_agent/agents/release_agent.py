"""Оркестратор — единственное место, где сходятся все модули.

Схема работы: модель предлагает изменения, детерминированный код их
проверяет, человек подтверждает, детерминированный код записывает.
Модель не получает инструментов записи: ветки, коммиты и pull request
создаёт только код агента и только после подтверждения человеком.

Внешние зависимости приходят интерфейсами (Protocol), поэтому ядро не
знает, кто именно за ними стоит:

- PlanEngine        — источник плана изменений (языковая модель);
- HumanInterface    — канал общения с инженером (CLI, чат-бот);
- SourceControlPort — система контроля версий.

Порядок сессии:

1. Сбор параметров: релиз, репозитории, ветки, целевой стенд.
2. Факт: diff релизной ветки к базовой по каждому репозиторию.
3. Намерение: план установки из инструкции к релизу.
4. Сверка факта и намерения, расхождения выносятся человеку.
5. Модель предлагает изменения конфигов, кандидаты проходят валидацию.
6. Чекпоинт 1: инженер подтверждает план или присылает корректировки.
7. По каждому репозиторию: временная ветка, коммит, pull request.
8. Чекпоинт 2: инженер подтверждает PR или присылает правки.
9. Итоговый отчёт со ссылками на все PR.

Слияние PR и деплой выполняются штатным CI/CD и в агент не входят.

Условия остановки цикла подготовки кандидатов:

- успех — валидация прошла и изменения не выходят за границы плана;
- три неудачные попытки подряд — эскалация человеку;
- одна и та же ошибка дважды подряд — эскалация без третьей попытки;
- модель недоступна — инженер получает исходные материалы для ручной работы.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from release_promotion_agent.analyzers.branch_diff import (
    BranchDiff,
    ChangedFileInput,
    analyze_branch_diff,
)
from release_promotion_agent.analyzers.intent import ReleaseIntent
from release_promotion_agent.analyzers.reconciliation import (
    DiscrepancyKind,
    ReconciliationReport,
    reconcile,
)
from release_promotion_agent.core import audit_chain, redaction
from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import (
    EngineUnavailableError,
    EscalationError,
    SourceControlError,
)
from release_promotion_agent.core.fsm import RepoState, SessionFSM, SessionState
from release_promotion_agent.core.logging_setup import set_log_context
from release_promotion_agent.core.redaction import Redactor
from release_promotion_agent.core.session import PlanItem, SessionStore
from release_promotion_agent.tools.models import (
    CompareResult,
    PullRequestInfo,
    RepoRef,
)
from release_promotion_agent.validation.checks import validate_candidate
from release_promotion_agent.validation.models import CandidateFile, Env

MAX_CANDIDATE_ATTEMPTS = 3


# ── параметры сессии ─────────────────────────────────────────────────


class RepoParams(BaseModel):
    """Репозиторий цикла: координаты в SourceControl и пара веток для diff."""

    model_config = ConfigDict(frozen=True)

    ref: RepoRef
    release_ref: str  # релизная ветка: head для diff и цель для PR
    base_ref: str  # базовая ветка, с которой сравниваем

    @property
    def repo_key(self) -> str:
        return self.ref.key


class SessionParams(BaseModel):
    """Параметры запуска: релиз, целевой стенд и список репозиториев."""

    model_config = ConfigDict(frozen=True)

    release_id: str
    target_env: Env
    repos: tuple[RepoParams, ...]


# ── план изменений ───────────────────────────────────────────────────


class PlannedFileChange(BaseModel):
    """Кандидат на запись: новое содержимое файла и границы допустимых правок.

    allowed_key_paths задаёт, какие ключи конфига разрешено менять. Всё, что
    кандидат меняет за пределами этого списка, валидация отклоняет.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    env: Env
    file_path: str
    candidate_content: str
    allowed_key_paths: tuple[str, ...]
    summary: str


class ProposedPlan(BaseModel):
    """План изменений, предложенный моделью, с хэшами промпта и ответа."""

    model_config = ConfigDict(frozen=True)

    release_id: str
    changes: tuple[PlannedFileChange, ...]
    summary_text: str
    prompt_hash: str
    response_hash: str

    def stable_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def changes_for(self, repo_key: str) -> tuple[PlannedFileChange, ...]:
        return tuple(c for c in self.changes if c.repo_key == repo_key)


class Decision(BaseModel):
    """Решение инженера на чекпоинте: подтверждение либо текст корректировки."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    comment: str | None = None


class SessionResult(BaseModel):
    """Итог сессии: конечное состояние и ссылки на созданные PR."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    final_state: SessionState
    pr_urls: dict[str, str]
    store: SessionStore


# ── интерфейсы внешних модулей ───────────────────────────────────────


class PlanEngine(Protocol):
    """Источник плана изменений. За сессию вызывается в трёх режимах:
    первичный анализ, пересчёт после корректировки, правка по ревью PR.

    feedback содержит текст ошибок предыдущей валидации либо None на
    первой попытке.
    """

    def propose(
        self,
        facts: Sequence[BranchDiff],
        intent: ReleaseIntent,
        report: ReconciliationReport,
        feedback: str | None,
    ) -> ProposedPlan: ...

    def revise(self, plan: ProposedPlan, correction: str, feedback: str | None) -> ProposedPlan: ...

    def pr_feedback(
        self, plan: ProposedPlan, repo_key: str, comment: str, feedback: str | None
    ) -> tuple[PlannedFileChange, ...]: ...


class HumanInterface(Protocol):
    """Канал общения с инженером: показать план и PR, получить решение."""

    def review_plan(self, plan: ProposedPlan, report: ReconciliationReport) -> Decision: ...

    def review_pr(self, repo_key: str, pr_url: str) -> Decision: ...

    def notify(self, text: str) -> None: ...


class SourceControlPort(Protocol):
    """Операции системы контроля версий, нужные оркестратору.

    Слияния здесь нет: агент готовит изменения, но не вливает их.
    """

    def compare(self, ref: RepoRef, base_ref: str, head_ref: str) -> CompareResult: ...

    def get_file(self, ref: RepoRef, path: str, branch: str) -> str: ...

    def get_branch(self, ref: RepoRef, name: str) -> object | None: ...

    def create_branch(self, ref: RepoRef, name: str, from_ref: str) -> object: ...

    def commit_files(
        self, ref: RepoRef, branch: str, message: str, files: dict[str, str]
    ) -> str: ...

    def find_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str
    ) -> PullRequestInfo | None: ...

    def create_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str, title: str, body: str
    ) -> PullRequestInfo: ...


# ── оркестратор ──────────────────────────────────────────────────────


class Orchestrator:
    """Ведёт сессию от параметров до открытых pull request.

    Единственное место, которое знает порядок шагов целиком. Модули друг
    друга не вызывают: анализ diff, сверка, проверка кандидатов и работа
    с системой контроля версий связываются здесь. Поэтому ход сессии
    читается в одном файле, а не собирается по вызовам между модулями.

    Три внешние зависимости приходят интерфейсами и подменяются целиком:
    система контроля версий, источник плана изменений и канал общения с
    инженером. За ними может стоять живой API или заглушка — оркестратор
    об этом не знает, и на этом же шве работает прогон без сети.

    Порядок работы:

    1. По каждому репозиторию снимается diff релизной ветки к базовой —
       это ФАКТ.
    2. Читается план установки — это НАМЕРЕНИЕ.
    3. Источники сверяются, расхождения складываются в отчёт.
    4. Модель предлагает изменения конфигов, кандидаты проходят проверку.
    5. Чекпоинт 1: инженер подтверждает план либо присылает корректировки,
       и тогда шаг 4 повторяется. До подтверждения не делается ни одной
       записи — всё, что было выше, только читало.
    6. По каждому репозиторию: ветка, коммит, pull request.
    7. Чекпоинт 2: инженер подтверждает pull request либо присылает
       правки, и тогда добавляется ещё один коммит.
    8. Итоговый отчёт со ссылками на все pull request.

    Слияние и деплой сюда не входят и не появятся: на открытом pull
    request агент останавливается, дальше работает штатный процесс.

    Записывает всегда обычный код этого класса, а не модель. Модель
    только предлагает содержимое файлов, и её предложение до записи
    проходит проверку и подтверждение человеком.
    """

    def __init__(
        self,
        sourcecontrol: SourceControlPort,
        engine: PlanEngine,
        human: HumanInterface,
        redactor: Redactor | None = None,
    ) -> None:
        self._sc = sourcecontrol
        self._engine = engine
        self._human = human
        self._redactor = redactor or redaction.Redactor()

    # ── сценарий сессии ──────────────────────────────────────────────

    def run(
        self,
        context: SessionContext,
        params: SessionParams,
        intent_provider: Callable[[], ReleaseIntent],
    ) -> SessionResult:
        """Проводит сессию целиком: от параметров до отчёта со ссылками на PR."""
        set_log_context(context.session_id, context.user_id)
        fsm = SessionFSM.start(context)
        store = fsm.store
        fsm.transition_to(SessionState.PARAMS_COLLECTED)

        # Факт: что реально изменилось в релизной ветке. Только чтение.
        facts = self._analyze_diffs(store, params)
        fsm.transition_to(SessionState.DIFF_ANALYZED)

        # Намерение: что должно измениться по инструкции к релизу.
        intent = intent_provider()
        self._audit(store, audit_chain.EVENT_INTENT_READ, {"plan_hash": intent.stable_hash()})
        fsm.transition_to(SessionState.PLAN_ANALYZED)

        # Сверка двух источников. Расхождения не решаются автоматически:
        # они попадают в план и уходят человеку вместе с ним.
        report = reconcile(list(facts.values()), intent)
        self._store_plan_items(store, report)
        self._audit(
            store,
            audit_chain.EVENT_RECONCILIATION_DONE,
            {
                "report_hash": report.stable_hash(),
                "matched": len(report.matched),
                "discrepancies": len(report.discrepancies),
            },
        )

        # Модель предлагает изменения; кандидаты проходят валидацию.
        plan = self._build_plan(store, params, facts, intent, report)
        fsm.transition_to(SessionState.PLAN_PROPOSED)
        fsm.transition_to(SessionState.AWAITING_PLAN_APPROVAL)

        # Чекпоинт 1. До этой точки во внешние системы ничего не записано.
        plan = self._plan_checkpoint(fsm, params, plan, report)

        # Запись идёт последовательно, по одному репозиторию.
        pr_urls: dict[str, str] = {}
        for repo_params in params.repos:
            fsm.transition_to(SessionState.REPO_BRANCHING)
            pr_urls[repo_params.repo_key] = self._process_repo(fsm, repo_params, plan)
        fsm.transition_to(SessionState.ALL_DONE)

        self._audit(store, audit_chain.EVENT_SESSION_COMPLETED, {"pr_urls": pr_urls})
        lines = "\n".join(f"  {repo}: {url}" for repo, url in sorted(pr_urls.items()))
        self._human.notify(
            f"Сессия {context.session_id} завершена. PR по репозиториям:\n{lines}\n"
            "Слияние и деплой выполняются штатным CI/CD."
        )
        return SessionResult(
            session_id=context.session_id,
            final_state=fsm.state,
            pr_urls=pr_urls,
            store=store,
        )

    # ── этап анализа ─────────────────────────────────────────────────

    def _analyze_diffs(self, store: SessionStore, params: SessionParams) -> dict[str, BranchDiff]:
        """Строит нормализованный diff по каждому репозиторию.

        Сначала compare даёт список изменённых файлов, затем читаются обе
        версии каждого файла и раскладываются в структуру файл → ключ → значения.
        """
        facts: dict[str, BranchDiff] = {}
        for repo in params.repos:
            compare = self._sc.compare(repo.ref, repo.base_ref, repo.release_ref)
            files = []
            for changed in compare.files:
                # None означает, что на этой ветке файла нет.
                base_text = self._read_file_or_none(repo.ref, changed.path, repo.base_ref)
                head_text = self._read_file_or_none(repo.ref, changed.path, repo.release_ref)
                files.append(
                    ChangedFileInput(path=changed.path, base_text=base_text, head_text=head_text)
                )
            diff = analyze_branch_diff(repo.repo_key, repo.base_ref, repo.release_ref, files)
            facts[repo.repo_key] = diff
            self._audit(
                store,
                audit_chain.EVENT_DIFF_ANALYZED,
                {"repo_key": repo.repo_key, "diff_hash": diff.stable_hash()},
            )
        return facts

    def _read_file_or_none(self, ref: RepoRef, path: str, branch: str) -> str | None:
        """Отсутствие файла на ветке — штатная ситуация, остальные отказы
        пробрасываются дальше."""
        try:
            return self._sc.get_file(ref, path, branch)
        except SourceControlError as exc:
            if exc.status_code == 404:
                return None
            raise

    def _store_plan_items(self, store: SessionStore, report: ReconciliationReport) -> None:
        """Сохраняет результат сверки: совпадения и расхождения с источником."""
        items = [
            PlanItem(
                repo_key=m.repo_key,
                file_path=m.file_path,
                key_path=m.key_path,
                change_kind=(m.fact.change_kind if m.fact else "FILE"),
                source="BOTH",
                status="MATCHED",
            )
            for m in report.matched
        ]
        source_by_kind = {
            DiscrepancyKind.FACT_ONLY: "FACT",
            DiscrepancyKind.INTENT_ONLY: "INTENT",
            DiscrepancyKind.VALUE_MISMATCH: "BOTH",
            DiscrepancyKind.FACT_UNPARSED: "FACT",
        }
        items += [
            PlanItem(
                repo_key=d.repo_key,
                file_path=d.file_path,
                key_path=d.key_path,
                change_kind=(d.fact.change_kind if d.fact else "FILE"),
                source=source_by_kind[d.kind],
                status=str(d.kind),
            )
            for d in report.discrepancies
        ]
        store.add_plan_items(items)

    # ── план и чекпоинт 1 ────────────────────────────────────────────

    def _build_plan(
        self,
        store: SessionStore,
        params: SessionParams,
        facts: dict[str, BranchDiff],
        intent: ReleaseIntent,
        report: ReconciliationReport,
    ) -> ProposedPlan:
        """Первичный план изменений конфигов целевого стенда."""

        def produce(feedback: str | None) -> ProposedPlan:
            return self._engine.propose(list(facts.values()), intent, report, feedback)

        plan = self._validated_plan(
            store,
            params,
            produce,
            purpose="analyze",
            degradation_facts=facts,
            degradation_intent=intent,
        )
        self._audit(
            store,
            audit_chain.EVENT_PLAN_PROPOSED,
            {
                "proposal_hash": plan.stable_hash(),
                "prompt_hash": plan.prompt_hash,
                "response_hash": plan.response_hash,
            },
        )
        return plan

    def _plan_checkpoint(
        self,
        fsm: SessionFSM,
        params: SessionParams,
        plan: ProposedPlan,
        report: ReconciliationReport,
    ) -> ProposedPlan:
        """Показывает план и расхождения инженеру, пока он не подтвердит.
        Каждое решение фиксируется в состоянии сессии."""
        store = fsm.store
        while True:
            decision = self._human.review_plan(plan, report)
            store.add_approval(
                checkpoint="PLAN",
                decision="approved" if decision.approved else "correction",
                comment=decision.comment,
            )
            if decision.approved:
                self._audit(
                    store,
                    audit_chain.EVENT_PLAN_APPROVED,
                    {"approved_by": fsm.context.user_id, "proposal_hash": plan.stable_hash()},
                )
                fsm.transition_to(SessionState.PLAN_APPROVED)
                return plan

            fsm.transition_to(SessionState.PLAN_CORRECTION)
            correction = decision.comment or ""

            # План и текст корректировки фиксируются аргументами по умолчанию,
            # чтобы замыкание не изменилось на следующей итерации цикла.
            def produce(
                feedback: str | None,
                plan_arg: ProposedPlan = plan,
                correction_arg: str = correction,
            ) -> ProposedPlan:
                return self._engine.revise(plan_arg, correction_arg, feedback)

            plan = self._validated_plan(store, params, produce, purpose="recalc")
            self._audit(
                store,
                audit_chain.EVENT_PLAN_PROPOSED,
                {
                    "proposal_hash": plan.stable_hash(),
                    "prompt_hash": plan.prompt_hash,
                    "response_hash": plan.response_hash,
                },
            )
            fsm.transition_to(SessionState.PLAN_PROPOSED)
            fsm.transition_to(SessionState.AWAITING_PLAN_APPROVAL)

    # ── цикл по одному репозиторию ───────────────────────────────────

    def _process_repo(self, fsm: SessionFSM, repo: RepoParams, plan: ProposedPlan) -> str:
        """Временная ветка, коммит, pull request и чекпоинт 2.
        Возвращает ссылку на открытый PR."""
        store = fsm.store
        context = fsm.context
        # Имя ветки выводится из идентификатора сессии, поэтому повторный
        # проход по тому же репозиторию попадёт в ту же ветку.
        branch = f"rpa/{context.session_id[:8]}/{repo.ref.repo}"
        store.upsert_repo_task(repo.repo_key, RepoState.BRANCHING, branch)

        # Существующая ветка сессии переиспользуется.
        if self._sc.get_branch(repo.ref, branch) is None:
            self._sc.create_branch(repo.ref, branch, from_ref=repo.release_ref)
            self._audit(
                store,
                audit_chain.EVENT_BRANCH_CREATED,
                {"repo_key": repo.repo_key, "branch": branch, "from_ref": repo.release_ref},
            )

        # Подтверждённые кандидаты записывает код агента, не модель.
        changes = plan.changes_for(repo.repo_key)
        files = {c.file_path: c.candidate_content for c in changes}
        commit_id = self._sc.commit_files(
            repo.ref, branch, self._commit_message(context, plan), files
        )
        self._audit(
            store,
            audit_chain.EVENT_COMMIT_CREATED,
            {"repo_key": repo.repo_key, "commit_id": commit_id, "files": sorted(files)},
        )
        store.upsert_repo_task(repo.repo_key, RepoState.COMMITTED, branch)
        fsm.transition_to(SessionState.REPO_COMMITTED)

        # Открытый PR из этой ветки переиспользуется: на репозиторий за
        # сессию создаётся не больше одного pull request.
        pr = self._sc.find_pull_request(repo.ref, branch, repo.release_ref)
        if pr is None:
            pr = self._sc.create_pull_request(
                repo.ref,
                branch,
                repo.release_ref,
                title=f"[{plan.release_id}] конфиги {repo.ref.repo} ({context.session_id[:8]})",
                body=self._pr_body(context, plan),
            )
        self._audit(
            store,
            audit_chain.EVENT_PR_OPENED,
            {"repo_key": repo.repo_key, "pr_url": pr.url, "pr_index": pr.index},
        )
        store.upsert_repo_task(repo.repo_key, RepoState.PR_OPENED, branch, pr_url=pr.url)
        fsm.transition_to(SessionState.PR_OPENED)
        fsm.transition_to(SessionState.AWAITING_PR_APPROVAL)
        store.upsert_repo_task(repo.repo_key, RepoState.AWAITING_PR_APPROVAL)

        # Чекпоинт 2: инженер описывает правки текстом, модель превращает их
        # в изменения файлов, агент добавляет коммит в ту же ветку.
        while True:
            decision = self._human.review_pr(repo.repo_key, pr.url)
            store.add_approval(
                checkpoint="PR",
                decision="approved" if decision.approved else "correction",
                repo_key=repo.repo_key,
                comment=decision.comment,
            )
            if decision.approved:
                self._audit(
                    store,
                    audit_chain.EVENT_PR_APPROVED,
                    {"repo_key": repo.repo_key, "approved_by": context.user_id},
                )
                store.upsert_repo_task(repo.repo_key, RepoState.DONE)
                fsm.transition_to(SessionState.REPO_DONE)
                return pr.url

            fsm.transition_to(SessionState.PR_CORRECTION)
            comment = decision.comment or ""
            # Кандидаты сверяются с текущим содержимым временной ветки,
            # границы правок берутся из подтверждённого плана.
            candidates = self._validated_candidates(
                store,
                produce=lambda fb, c=comment: self._engine.pr_feedback(plan, repo.repo_key, c, fb),
                current_lookup=lambda c: self._sc.get_file(repo.ref, c.file_path, branch),
                scope_lookup=lambda c: self._scope_for(plan, c.repo_key, c.file_path),
                purpose="edit",
            )
            extra_commit_id = self._sc.commit_files(
                repo.ref,
                branch,
                f"[{plan.release_id}] правка по ревью PR: {comment[:80]}",
                {c.file_path: c.candidate_content for c in candidates},
            )
            self._audit(
                store,
                audit_chain.EVENT_PR_EXTRA_COMMIT,
                {"repo_key": repo.repo_key, "commit_id": extra_commit_id},
            )
            fsm.transition_to(SessionState.AWAITING_PR_APPROVAL)

    # ── подготовка и проверка кандидатов ─────────────────────────────

    def _validated_plan(
        self,
        store: SessionStore,
        params: SessionParams,
        produce: Callable[[str | None], ProposedPlan],
        purpose: str,
        degradation_facts: dict[str, BranchDiff] | None = None,
        degradation_intent: ReleaseIntent | None = None,
    ) -> ProposedPlan:
        """Проверяет план целиком: каждый кандидат сверяется с текущим
        содержимым файла на релизной ветке своего репозитория."""
        repo_by_key = {r.repo_key: r for r in params.repos}
        plan_holder: dict[str, ProposedPlan] = {}

        def produce_candidates(feedback: str | None) -> tuple[PlannedFileChange, ...]:
            try:
                plan = produce(feedback)
            except EngineUnavailableError:
                # Модель недоступна: отдаём инженеру исходные материалы,
                # чтобы он мог продолжить вручную, и останавливаемся.
                if degradation_facts is not None and degradation_intent is not None:
                    raw = "\n".join(
                        f"{key}: diff_hash={diff.stable_hash()}"
                        for key, diff in sorted(degradation_facts.items())
                    )
                    self._human.notify(
                        "Модель недоступна. Исходный diff и инструкция для ручной работы:\n"
                        f"{raw}\nplan_hash={degradation_intent.stable_hash()}"
                    )
                raise EscalationError("модель недоступна, нужен человек") from None
            plan_holder["plan"] = plan
            return plan.changes

        self._validated_candidates(
            store,
            produce=produce_candidates,
            current_lookup=lambda c: self._sc.get_file(
                repo_by_key[c.repo_key].ref,
                c.file_path,
                repo_by_key[c.repo_key].release_ref,
            ),
            scope_lookup=lambda c: c.allowed_key_paths,
            purpose=purpose,
        )
        return plan_holder["plan"]

    def _validated_candidates(
        self,
        store: SessionStore,
        produce: Callable[[str | None], Sequence[Any]],
        current_lookup: Callable[[Any], str],
        scope_lookup: Callable[[Any], Sequence[str]],
        purpose: str,
    ) -> Sequence[Any]:
        """До трёх попыток получить валидных кандидатов. Каждая попытка
        фиксируется в состоянии сессии вместе с итогом валидации."""
        feedback: str | None = None
        previous_errors: tuple[str, ...] | None = None

        for attempt in range(1, MAX_CANDIDATE_ATTEMPTS + 1):
            # На повторных попытках модель получает текст прошлых ошибок.
            candidates = produce(feedback)

            # Каждый кандидат проверяется дважды: корректность YAML и
            # непревышение границ подтверждённого плана.
            all_errors: list[str] = []
            for item in candidates:
                result = validate_candidate(
                    self._as_candidate_file(item),
                    current_lookup(item),
                    allowed_key_paths=tuple(scope_lookup(item)),
                )
                all_errors.extend(result.errors)

            store.record_llm_call(
                purpose=purpose,
                prompt_hash=hashlib.sha256(f"{purpose}:{feedback or ''}".encode()).hexdigest(),
                response_hash=hashlib.sha256(
                    json.dumps(
                        [self._as_candidate_file(i).content for i in candidates],
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest(),
                attempts=attempt,
                validation_result="valid" if not all_errors else "; ".join(all_errors)[:500],
            )

            if not all_errors:
                self._audit(
                    store,
                    audit_chain.EVENT_VALIDATION_RESULT,
                    {"purpose": purpose, "valid": True, "attempts": attempt},
                )
                return candidates

            # Повтор той же ошибки означает, что модель ходит по кругу.
            errors_signature = tuple(all_errors)
            if previous_errors is not None and errors_signature == previous_errors:
                raise EscalationError(
                    "одна и та же ошибка валидации на двух попытках подряд: "
                    + "; ".join(all_errors)
                )
            previous_errors = errors_signature
            feedback = "исправь ошибки валидации: " + "; ".join(all_errors)

        raise EscalationError(
            f"{MAX_CANDIDATE_ATTEMPTS} неудачные попытки валидации подряд: "
            + "; ".join(previous_errors or ())
        )

    @staticmethod
    def _as_candidate_file(item: Any) -> CandidateFile:
        """Приводит позицию плана к форме, которую принимает валидация."""
        return CandidateFile(
            repo_key=item.repo_key,
            env=item.env,
            file_path=item.file_path,
            content=item.candidate_content,
        )

    @staticmethod
    def _scope_for(plan: ProposedPlan, repo_key: str, file_path: str) -> tuple[str, ...]:
        """Границы правок для файла берутся из подтверждённого плана."""
        for change in plan.changes:
            if change.repo_key == repo_key and change.file_path == file_path:
                return change.allowed_key_paths
        return ()

    # ── служебное ────────────────────────────────────────────────────

    def _commit_message(self, context: SessionContext, plan: ProposedPlan) -> str:
        """Инициатор указывается явно: на сервере коммиты создаются под
        технической учётной записью, и по автору инженера не определить."""
        return (
            f"[{plan.release_id}] обновление конфигов по подтверждённому плану\n\n"
            f"Сессия: {context.session_id}\nИнициатор: {context.user_id}"
        )

    def _pr_body(self, context: SessionContext, plan: ProposedPlan) -> str:
        return (
            f"Автоматически подготовлено агентом.\n\n"
            f"Релиз: {plan.release_id}\nСессия: {context.session_id}\n"
            f"Инициатор: {context.user_id}\n"
            f"План подтвердил: {context.user_id} (чекпоинт 1)\n\n"
            f"{plan.summary_text}\n\nСлияние выполняется вне агента."
        )

    def _audit(self, store: SessionStore, event_type: str, payload: dict[str, Any]) -> None:
        """Записывает событие аудита, вырезав из него секреты."""
        store.append_audit(event_type, audit_chain.redact_payload(self._redactor, payload))
