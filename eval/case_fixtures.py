"""离线 Benchmark 的固定 Repository、GitHub 与 Reliability Fixture。"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict

from agent.graph import AgentNode
from agent.reflection import ReflectionPolicy
from agent.schemas import ReviewResult
from eval.schemas import EvaluationCase, EvaluationScenario
from tools.base import BaseTool
from tools.github_client import GitHubClient
from tools.reliability import ReliabilityPolicy
from tools.runtime import ToolRuntime, build_default_registry


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
REPOSITORY_FIXTURE = FIXTURE_ROOT / "repos" / "sample_repo"
GITHUB_FIXTURE_ROOT = FIXTURE_ROOT / "github"


class NoArgs(BaseModel):
    """Evaluation-only Tool 使用的空参数。"""

    model_config = ConfigDict(extra="forbid")


class FlakyEvaluationTool(BaseTool):
    """第一次 Timeout、第二次成功。"""

    name: ClassVar[str] = "flaky_evaluation_tool"
    description: ClassVar[str] = "验证 Retry Recovery。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def __init__(self) -> None:
        self.call_count = 0

    def run(self, args: BaseModel) -> Any:
        self.call_count += 1
        if self.call_count == 1:
            raise TimeoutError("Evaluation 模拟临时 Timeout。")
        return {"status": "recovered"}


class AlwaysTimeoutEvaluationTool(BaseTool):
    """每次执行都返回可 Retry 的 Timeout。"""

    name: ClassVar[str] = "always_timeout_evaluation_tool"
    description: ClassVar[str] = "验证 Retry Exhaustion。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        raise TimeoutError("Evaluation 模拟永久 Timeout。")


class PrimaryFailureEvaluationTool(BaseTool):
    """触发一级 Fallback 的主 Tool。"""

    name: ClassVar[str] = "primary_failure_evaluation_tool"
    description: ClassVar[str] = "验证 Fallback。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        raise RuntimeError("Evaluation 模拟主 Tool 失败。")


class FallbackEvaluationTool(BaseTool):
    """Fallback 后返回成功 Evidence。"""

    name: ClassVar[str] = "fallback_evaluation_tool"
    description: ClassVar[str] = "返回固定 Fallback Evidence。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        return {"status": "fallback-success"}


class StableEvaluationTool(BaseTool):
    """用于 Reflection 与 Tool Budget Case 的稳定 Tool。"""

    name: ClassVar[str] = "stable_evaluation_tool"
    description: ClassVar[str] = "返回固定成功 Evidence。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        return {"status": "ok"}


@dataclass
class CaseExecution:
    """一个 Case 的 Runtime 与公开 Agent Runner 注入参数。"""

    runtime: ToolRuntime
    github_client: GitHubClient
    runner_kwargs: dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        self.github_client.close()


def prepare_case(case: EvaluationCase) -> CaseExecution:
    """根据固定 scenario 构造完全离线的执行环境。"""

    client = GitHubClient(transport=httpx.MockTransport(_github_handler(case)))
    registry = build_default_registry(REPOSITORY_FIXTURE, client)
    policy = ReliabilityPolicy()
    runner_kwargs: dict[str, Any] = {}
    scenario = case.scenario

    if scenario is EvaluationScenario.READ_README:
        runner_kwargs["planner_node"] = _single_tool_planner(
            "read_file", {"path": "README.md"}
        )
    elif scenario is EvaluationScenario.MISSING_FILE:
        runner_kwargs["planner_node"] = _single_tool_planner(
            "read_file", {"path": "missing.txt"}
        )
    elif scenario is EvaluationScenario.MISSING_SYMBOL:
        runner_kwargs["planner_node"] = _single_tool_planner(
            "search_code",
            {"query": "MissingWidget", "path": ".", "file_pattern": "*.py"},
        )
    elif scenario is EvaluationScenario.PATH_ESCAPE:
        runner_kwargs["planner_node"] = _single_tool_planner(
            "read_file", {"path": "../secret.txt"}
        )
    elif scenario is EvaluationScenario.RETRY_SUCCESS:
        tool = FlakyEvaluationTool()
        registry.register(tool)
        policy = ReliabilityPolicy(max_retries=2)
        runner_kwargs["planner_node"] = _single_tool_planner(tool.name, {})
    elif scenario is EvaluationScenario.RETRY_EXHAUSTED:
        tool = AlwaysTimeoutEvaluationTool()
        registry.register(tool)
        policy = ReliabilityPolicy(max_retries=2)
        runner_kwargs["planner_node"] = _single_tool_planner(tool.name, {})
    elif scenario is EvaluationScenario.FALLBACK:
        primary = PrimaryFailureEvaluationTool()
        fallback = FallbackEvaluationTool()
        registry.register(primary)
        registry.register(fallback)
        policy = ReliabilityPolicy(
            max_retries=0,
            fallbacks={primary.name: fallback.name},
        )
        runner_kwargs["planner_node"] = _single_tool_planner(primary.name, {})
    elif scenario is EvaluationScenario.MAX_TOOL_CALLS:
        stable = StableEvaluationTool()
        registry.register(stable)
        policy = ReliabilityPolicy(max_retries=0, max_tool_calls=2)
        runner_kwargs["planner_node"] = _repeated_tool_planner(stable.name, 3)
    elif scenario is EvaluationScenario.FIRST_PASS:
        runner_kwargs["planner_node"] = _single_tool_planner(
            "read_file", {"path": "README.md"}
        )
    elif scenario is EvaluationScenario.REFLECTION_RECOVERY:
        runner_kwargs["planner_node"] = _search_only_planner
    elif scenario is EvaluationScenario.REFLECTION_EXHAUSTED:
        stable = StableEvaluationTool()
        registry.register(stable)
        policy = ReliabilityPolicy(max_retries=0)
        runner_kwargs.update(
            {
                "planner_node": _single_tool_planner(stable.name, {}),
                "reviewer_node": _always_fail_reviewer,
                "reflection_policy": ReflectionPolicy(max_reflections=1),
            }
        )
    elif scenario is EvaluationScenario.REFLECTION_BUDGET:
        policy = ReliabilityPolicy(max_retries=0, max_tool_calls=1)
        runner_kwargs["planner_node"] = _search_only_planner
    elif scenario is EvaluationScenario.GITHUB_RATE_LIMIT:
        policy = ReliabilityPolicy(max_retries=1)

    return CaseExecution(
        runtime=ToolRuntime(registry, policy),
        github_client=client,
        runner_kwargs=runner_kwargs,
    )


def _single_tool_planner(
    tool_name: str,
    arguments: dict[str, Any],
) -> AgentNode:
    def planner(state: dict[str, Any]) -> dict[str, object]:
        return _plan_update(
            [
                {
                    "id": 1,
                    "goal": "执行固定 Evaluation Tool 步骤",
                    "tool_name": tool_name,
                    "tool_args": arguments,
                    "requires_tool": True,
                }
            ]
        )

    return planner


def _repeated_tool_planner(tool_name: str, count: int) -> AgentNode:
    def planner(state: dict[str, Any]) -> dict[str, object]:
        return _plan_update(
            [
                {
                    "id": index,
                    "goal": f"执行固定步骤 {index}",
                    "tool_name": tool_name,
                    "tool_args": {},
                    "requires_tool": True,
                }
                for index in range(1, count + 1)
            ]
        )

    return planner


def _search_only_planner(state: dict[str, Any]) -> dict[str, object]:
    return _plan_update(
        [
            {
                "id": 1,
                "goal": "只定位 AgentState 定义",
                "tool_name": "search_code",
                "tool_args": {
                    "query": "AgentState",
                    "path": ".",
                    "file_pattern": "*.py",
                },
                "requires_tool": True,
            }
        ]
    )


def _plan_update(steps: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "plan": steps,
        "current_step": 0,
        "tool_calls": [],
        "tool_results": [],
        "execution_attempts": [],
        "tool_call_count": 0,
        "retry_count": 0,
        "evidence": [],
        "errors": [],
        "review_history": [],
        "reflection_count": 0,
        "reflection_history": [],
        "replan_count": 0,
        "replan_records": [],
    }


def _always_fail_reviewer(state: dict[str, Any]) -> dict[str, object]:
    review = ReviewResult(
        round=len(state.get("review_history", [])) + 1,
        passed=False,
        score=0.2,
        criterion_scores={"goal_completion": 0.0},
        issues=["Evaluation Case 要求 Reviewer 持续失败。"],
        missing_evidence=[],
        reason="Evaluation Case 要求 Reviewer 持续失败。",
        recommended_action="继续检查。",
    )
    dumped = review.model_dump()
    return {
        "review": dumped,
        "review_score": review.score,
        "review_passed": False,
        "review_history": [*state.get("review_history", []), dumped],
    }


def _github_handler(case: EvaluationCase):
    fixture_name = {
        EvaluationScenario.GITHUB_PR: "pull_request.json",
        EvaluationScenario.GITHUB_404: "not_found.json",
        EvaluationScenario.GITHUB_RATE_LIMIT: "rate_limit.json",
    }.get(case.scenario, "issue.json")
    fixture = _load_github_fixture(fixture_name)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            fixture["status_code"],
            json=fixture["json"],
            headers=fixture.get("headers", {}),
            request=request,
        )

    return handler


def _load_github_fixture(name: str) -> dict[str, Any]:
    with (GITHUB_FIXTURE_ROOT / name).open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"GitHub Fixture 顶层必须是 object：{name}")
    return value
