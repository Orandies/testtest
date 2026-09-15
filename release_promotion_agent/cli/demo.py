"""Заглушки внешних систем и сборка демонстрационной сессии.

Позволяют пройти сценарий целиком, не обращаясь к сети: репозиторий живёт
в памяти, модель отдаёт заранее заданный план, решения инженера заданы
сценарием. Тот же оркестратор в рабочем режиме получает настоящие
реализации этих же интерфейсов.
"""

from __future__ import annotations

import hashlib

from release_promotion_agent.agents.release_agent import (
    Decision,
    Orchestrator,
    PlannedFileChange,
    ProposedPlan,
    RepoParams,
    SessionParams,
    SessionResult,
)
from release_promotion_agent.analyzers.intent import IntentChange, ReleaseIntent
from release_promotion_agent.analyzers.reconciliation import ReconciliationReport
from release_promotion_agent.core.context import SessionContext
from release_promotion_agent.core.errors import SourceControlError
from release_promotion_agent.tools.models import (
    BranchInfo,
    CompareFile,
    CompareResult,
    FileChangeStatus,
    PullRequestInfo,
    RepoRef,
)
from release_promotion_agent.validation.models import Env

DEMO_REF = RepoRef(tenant="demo-tenant", project="DEMO", repo="configs-core")

# Конфиг на базовой ветке и на релизной: в релизе увеличен таймаут.
BASE_CONFIG = "server:\n  port: 8080\n  timeout-seconds: 30\nlogging:\n  level: INFO\n"
RELEASE_CONFIG = "server:\n  port: 8080\n  timeout-seconds: 60\nlogging:\n  level: INFO\n"

# Кандидат, который предлагает модель: добавлено число повторов.
CANDIDATE_CONFIG = (
    "server:\n  port: 8080\n  timeout-seconds: 60\n  retries: 5\nlogging:\n  level: INFO\n"
)

CONFIG_PATH = "agents/PSI.yaml"


class InMemorySourceControl:
    """Репозиторий в памяти: ветки, содержимое файлов и pull request.

    Реализует тот же интерфейс, что и клиент настоящей системы контроля
    версий, поэтому оркестратор не замечает подмены. Ветка — это словарь
    «путь файла → содержимое», создание ветки копирует такой словарь.

    Проверок прав, конфликтов и сетевых сбоев здесь нет: заглушка нужна,
    чтобы пройти сценарий, а не чтобы изображать поведение сервера.
    """

    def __init__(self) -> None:
        self.trees: dict[tuple[str, str], dict[str, str]] = {
            (DEMO_REF.key, "master"): {CONFIG_PATH: BASE_CONFIG},
            (DEMO_REF.key, "release/v1.0"): {CONFIG_PATH: RELEASE_CONFIG},
        }
        self.branches: dict[tuple[str, str], BranchInfo] = {}
        self.prs: dict[tuple[str, str, str], PullRequestInfo] = {}
        self._counter = 0

    def compare(self, ref: RepoRef, base_ref: str, head_ref: str) -> CompareResult:
        base = self.trees[(ref.key, base_ref)]
        head = self.trees[(ref.key, head_ref)]
        files = []
        for path in sorted(set(base) | set(head)):
            if path not in head:
                files.append(CompareFile(path=path, status=FileChangeStatus.REMOVED))
            elif path not in base:
                files.append(CompareFile(path=path, status=FileChangeStatus.ADDED))
            elif base[path] != head[path]:
                files.append(CompareFile(path=path, status=FileChangeStatus.MODIFIED))
        return CompareResult(
            repo_key=ref.key, base_ref=base_ref, head_ref=head_ref, files=tuple(files)
        )

    def get_file(self, ref: RepoRef, path: str, branch: str) -> str:
        tree = self.trees.get((ref.key, branch))
        if tree is None or path not in tree:
            raise SourceControlError(f"нет файла {path} на ветке {branch}", status_code=404)
        return tree[path]

    def get_branch(self, ref: RepoRef, name: str) -> BranchInfo | None:
        return self.branches.get((ref.key, name))

    def create_branch(self, ref: RepoRef, name: str, from_ref: str) -> BranchInfo:
        self.trees[(ref.key, name)] = dict(self.trees[(ref.key, from_ref)])
        info = BranchInfo(name=name)
        self.branches[(ref.key, name)] = info
        return info

    def commit_files(self, ref: RepoRef, branch: str, message: str, files: dict[str, str]) -> str:
        self.trees[(ref.key, branch)].update(files)
        self._counter += 1
        return f"commit-{self._counter}"

    def find_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str
    ) -> PullRequestInfo | None:
        return self.prs.get((ref.key, source_branch, target_branch))

    def create_pull_request(
        self, ref: RepoRef, source_branch: str, target_branch: str, title: str, body: str
    ) -> PullRequestInfo:
        self._counter += 1
        pr = PullRequestInfo(
            index=self._counter,
            url=f"https://sourcecontrol.example/{ref.repo}/pulls/{self._counter}",
            source_branch=source_branch,
            target_branch=target_branch,
        )
        self.prs[(ref.key, source_branch, target_branch)] = pr
        return pr


class ScriptedEngine:
    """Модель-заглушка: всегда отдаёт один и тот же корректный план.

    Подставляется вместо настоящей модели, чтобы прогнать сценарий без
    сети и получить один и тот же результат при каждом запуске. План
    заведомо проходит проверку, поэтому демонстрация показывает путь
    сессии, а не поведение при ошибках модели.
    """

    def _plan(self) -> ProposedPlan:
        return ProposedPlan(
            release_id="R-1.0",
            changes=(
                PlannedFileChange(
                    repo_key=DEMO_REF.key,
                    env=Env.PSI,
                    file_path=CONFIG_PATH,
                    candidate_content=CANDIDATE_CONFIG,
                    allowed_key_paths=("server.retries",),
                    summary="добавить server.retries = 5",
                ),
            ),
            summary_text="Добавить в конфиг ПСИ параметр server.retries со значением 5.",
            prompt_hash=hashlib.sha256(b"demo-prompt").hexdigest(),
            response_hash=hashlib.sha256(b"demo-response").hexdigest(),
        )

    def propose(self, facts, intent, report, feedback) -> ProposedPlan:
        return self._plan()

    def revise(self, plan, correction, feedback) -> ProposedPlan:
        return self._plan()

    def pr_feedback(self, plan, repo_key, comment, feedback):
        return self._plan().changes


class ScriptedHuman:
    """Инженер-заглушка: решения на чекпоинтах заданы заранее.

    Списки решений разбираются по порядку — первый отвечает на первый
    вопрос, второй на второй. Так в демонстрации воспроизводится и
    подтверждение с первого раза, и путь с корректировками.

    Всё, что настоящий интерфейс показал бы инженеру, печатается в
    терминал: видно, на каком шаге сессия и что именно подтверждается.
    """

    def __init__(self, plan_decisions: list[Decision], pr_decisions: list[Decision]) -> None:
        self.plan_decisions = list(plan_decisions)
        self.pr_decisions = list(pr_decisions)
        self.notifications: list[str] = []

    def review_plan(self, plan: ProposedPlan, report: ReconciliationReport) -> Decision:
        decision = self.plan_decisions.pop(0)
        print(f"[чекпоинт 1] план: {plan.summary_text}")
        print(f"[чекпоинт 1] расхождений: {len(report.discrepancies)}")
        print(f"[чекпоинт 1] решение: {'подтверждено' if decision.approved else 'корректировка'}")
        return decision

    def review_pr(self, repo_key: str, pr_url: str) -> Decision:
        decision = self.pr_decisions.pop(0)
        print(f"[чекпоинт 2] {repo_key}: {pr_url}")
        print(f"[чекпоинт 2] решение: {'подтверждено' if decision.approved else 'правка'}")
        return decision

    def notify(self, text: str) -> None:
        self.notifications.append(text)
        print(text)


def demo_intent() -> ReleaseIntent:
    """Намерение релиза: инструкция требует увеличить таймаут до 60."""
    return ReleaseIntent(
        release_id="R-1.0",
        changes=(
            IntentChange(
                repo_key=DEMO_REF.key,
                file_path=CONFIG_PATH,
                key_path="server.timeout-seconds",
                new_value=60,
                comment="увеличить таймаут до 60 секунд",
            ),
        ),
    )


def run_demo_session(with_corrections: bool = False) -> SessionResult:
    """Прогоняет сессию целиком на заглушках и возвращает её результат."""
    plan_decisions = [Decision(approved=True)]
    pr_decisions = [Decision(approved=True)]
    if with_corrections:
        plan_decisions.insert(0, Decision(approved=False, comment="уточни значение retries"))
        pr_decisions.insert(0, Decision(approved=False, comment="поправь комментарий в файле"))

    orchestrator = Orchestrator(
        sourcecontrol=InMemorySourceControl(),
        engine=ScriptedEngine(),
        human=ScriptedHuman(plan_decisions, pr_decisions),
    )
    params = SessionParams(
        release_id="R-1.0",
        target_env=Env.PSI,
        repos=(RepoParams(ref=DEMO_REF, release_ref="release/v1.0", base_ref="master"),),
    )
    context = SessionContext.new(user_id="engineer", release_id="R-1.0")
    return orchestrator.run(context, params, demo_intent)
