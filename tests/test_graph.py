"""Plan-and-Execute Graph 的结构与端到端测试。"""

from pathlib import Path
import logging
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from agent.graph import build_agent_graph
from agent.reflection import ReflectionPolicy
from agent.schemas import ReviewResult
from tools.base import BaseTool
from tools.github_client import GitHubClient
from tools.reliability import ReliabilityPolicy
from tools.runtime import ToolRuntime, build_default_registry, build_tool_runtime


class NoArgs(BaseModel):
    """Graph 可靠性测试使用的空参数。"""

    model_config = ConfigDict(extra="forbid")


class FlakyGraphTool(BaseTool):
    """第一次超时、第二次成功的测试 Tool。"""

    name: ClassVar[str] = "flaky_graph_tool"
    description: ClassVar[str] = "用于验证 Graph Retry 成功。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def __init__(self) -> None:
        self.call_count = 0

    def run(self, args: BaseModel) -> Any:
        """第一次返回可重试错误，后续返回成功证据。"""

        self.call_count += 1
        if self.call_count == 1:
            raise TimeoutError("模拟临时超时")
        return {"status": "recovered"}


class AlwaysTimeoutGraphTool(BaseTool):
    """始终产生可重试超时的测试 Tool。"""

    name: ClassVar[str] = "always_timeout_graph_tool"
    description: ClassVar[str] = "用于验证 Graph Retry Exhaustion。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """每次执行都失败。"""

        raise TimeoutError("模拟永久超时")


class StableGraphTool(BaseTool):
    """用于构造超过全局预算的多步骤计划。"""

    name: ClassVar[str] = "stable_graph_tool"
    description: ClassVar[str] = "用于验证 MAX_TOOL_CALLS。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """返回固定成功结果。"""

        return {"status": "ok"}


def test_graph_compiles_with_execution_loop(tmp_path: Path) -> None:
    """Graph 必须包含 Review conditional edge 与 Reflection/Re-plan 闭环。"""

    runtime = build_tool_runtime(tmp_path)
    graph_description = build_agent_graph(runtime).get_graph()

    assert {
        "analyze_task",
        "create_plan",
        "execute_step",
        "collect_evidence",
        "tool_budget_exceeded",
        "generate_draft_answer",
        "review_answer",
        "reflect",
        "replan",
        "replan_budget_exceeded",
        "finalize_answer",
    }.issubset(graph_description.nodes)
    assert {
        ("__start__", "analyze_task"),
        ("analyze_task", "create_plan"),
        ("create_plan", "execute_step"),
        ("execute_step", "collect_evidence"),
        ("collect_evidence", "execute_step"),
        ("collect_evidence", "tool_budget_exceeded"),
        ("collect_evidence", "generate_draft_answer"),
        ("tool_budget_exceeded", "generate_draft_answer"),
        ("generate_draft_answer", "review_answer"),
        ("review_answer", "finalize_answer"),
        ("review_answer", "reflect"),
        ("reflect", "replan"),
        ("replan", "execute_step"),
        ("replan", "replan_budget_exceeded"),
        ("replan", "generate_draft_answer"),
        ("replan_budget_exceeded", "finalize_answer"),
        ("finalize_answer", "__end__"),
    } == {(edge.source, edge.target) for edge in graph_description.edges}
    runtime.registry.get("get_github_issue").client.close()


def test_repository_multi_step_graph_uses_real_tools(tmp_path: Path) -> None:
    """本地 Graph 必须依次真实执行 search_code 和 read_file。"""

    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()
    (agent_directory / "state.py").write_text(
        "from typing import TypedDict\n\nclass AgentState(TypedDict):\n    pass\n",
        encoding="utf-8",
    )
    runtime = build_tool_runtime(tmp_path)
    graph = build_agent_graph(runtime)

    result = graph.invoke({"user_query": "查找项目中 AgentState 的定义"})

    assert result["current_step"] == len(result["plan"]) == 2
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "search_code",
        "read_file",
    ]
    assert all(item["result"]["success"] for item in result["tool_results"])
    assert len(result["evidence"]) == 2
    assert not result["errors"]
    assert result["review_passed"] is True
    assert result["review_score"] == 1.0
    assert result["reflection_count"] == 0
    assert len(result["review_history"]) == 1
    assert result["draft_answer"] == result["final_answer"]
    assert "AgentState" in result["final_answer"]
    assert "search_code" in result["final_answer"]
    assert "read_file" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def test_github_one_step_graph_with_mock_transport(tmp_path: Path) -> None:
    """GitHub Issue 必须从 Planner 经 Runtime 进入 Evidence 和回答。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "number": 7,
                "title": "修复登录问题",
                "body": "Issue body",
                "state": "open",
                "html_url": "https://github.com/octocat/Hello-World/issues/7",
                "user": {"login": "octocat"},
                "labels": [{"name": "bug"}],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "comments": 2,
            },
            request=request,
        )

    client = GitHubClient(transport=httpx.MockTransport(handler))
    runtime = build_tool_runtime(tmp_path, client)

    result = build_agent_graph(runtime).invoke(
        {"user_query": "分析 octocat/Hello-World Issue #7"}
    )

    assert result["current_step"] == 1
    assert result["tool_calls"][0]["tool_name"] == "get_github_issue"
    assert result["tool_results"][0]["result"]["success"] is True
    assert result["evidence"][0]["source"] == "get_github_issue"
    assert result["review_passed"] is True
    assert result["reflection_count"] == 0
    assert "修复登录问题" in result["final_answer"]
    client.close()


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "expected_code"),
    [
        ("unknown_tool", {}, "TOOL_NOT_FOUND"),
        ("read_file", {}, "INVALID_ARGUMENT"),
        ("read_file", {"path": "missing.txt"}, "FILE_NOT_FOUND"),
    ],
)
def test_tool_failure_graph_finishes_without_retry(
    tmp_path: Path,
    tool_name: str,
    tool_args: dict,
    expected_code: str,
) -> None:
    """Tool 失败应记录错误、推进一次并正常生成最终回答。"""

    def failing_planner(state: dict) -> dict[str, object]:
        return {
            "plan": [
                {
                    "id": 1,
                    "goal": "触发 Tool 失败",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "requires_tool": True,
                }
            ],
            "current_step": 0,
            "tool_calls": [],
            "tool_results": [],
            "evidence": [],
            "errors": [],
        }

    runtime = build_tool_runtime(tmp_path)
    graph = build_agent_graph(runtime, planner_node=failing_planner)

    result = graph.invoke({"user_query": "测试失败步骤"})

    assert result["current_step"] == 1
    assert len(result["tool_calls"]) == 1
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["result"]["error_code"] == expected_code
    assert result["tool_call_count"] == 1
    assert result["retry_count"] == 0
    assert result["errors"][0]["error_code"] == expected_code
    assert result["review_passed"] is False
    assert result["reflection_count"] == 2
    assert "任务未完全完成" in result["final_answer"]
    assert "错误" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def _single_tool_planner(tool_name: str):
    """返回只包含一个指定测试 Tool 的 Planner。"""

    def planner(state: dict) -> dict[str, object]:
        return {
            "plan": [
                {
                    "id": 1,
                    "goal": "执行可靠性测试",
                    "tool_name": tool_name,
                    "tool_args": {},
                    "requires_tool": True,
                }
            ],
            "current_step": 0,
            "tool_calls": [],
            "tool_results": [],
            "evidence": [],
            "errors": [],
        }

    return planner


def test_graph_retries_then_collects_final_success_evidence(tmp_path: Path) -> None:
    """Graph 应保留失败 Attempt，并只从最终成功结果生成 Evidence。"""

    registry = build_default_registry(tmp_path)
    tool = FlakyGraphTool()
    registry.register(tool)
    runtime = ToolRuntime(registry, ReliabilityPolicy(max_retries=2))

    result = build_agent_graph(
        runtime,
        planner_node=_single_tool_planner(tool.name),
    ).invoke({"user_query": "测试 Retry 成功"})

    assert tool.call_count == 2
    assert result["tool_call_count"] == 2
    assert result["retry_count"] == 1
    assert [item["success"] for item in result["execution_attempts"]] == [
        False,
        True,
    ]
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["raw_result"] == {"status": "recovered"}
    assert not result["errors"]
    assert result["retry_count"] == 1
    assert result.get("reflection_count", 0) == 0
    assert result["review_passed"] is True
    assert "证据" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def test_graph_retry_exhaustion_reaches_normal_end(tmp_path: Path) -> None:
    """永久失败必须有限重试、进入 Errors、生成 Final 并正常 END。"""

    registry = build_default_registry(tmp_path)
    tool = AlwaysTimeoutGraphTool()
    registry.register(tool)
    runtime = ToolRuntime(registry, ReliabilityPolicy(max_retries=2))

    result = build_agent_graph(
        runtime,
        planner_node=_single_tool_planner(tool.name),
    ).invoke({"user_query": "测试永久失败"})

    assert result["current_step"] == 1
    assert result["tool_call_count"] == 3
    assert result["retry_count"] == 2
    assert result["errors"][0]["error_code"] == "MAX_RETRIES_EXCEEDED"
    assert result["errors"][0]["last_error_code"] == "TIMEOUT"
    assert not result["evidence"]
    assert result["reflection_count"] == 2
    assert result["retry_count"] == 2
    assert "MAX_RETRIES_EXCEEDED" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def test_graph_stops_before_attempt_beyond_max_tool_calls(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """3 步计划在预算为 2 时不得发起第 3 次 Tool attempt。"""

    registry = build_default_registry(tmp_path)
    registry.register(StableGraphTool())
    runtime = ToolRuntime(
        registry,
        ReliabilityPolicy(max_retries=0, max_tool_calls=2),
    )
    caplog.set_level(logging.INFO, logger="issueops.agent")

    def three_step_planner(state: dict) -> dict[str, object]:
        return {
            "plan": [
                {
                    "id": step_id,
                    "goal": f"执行步骤 {step_id}",
                    "tool_name": "stable_graph_tool",
                    "tool_args": {},
                    "requires_tool": True,
                }
                for step_id in range(1, 4)
            ],
            "current_step": 0,
            "tool_calls": [],
            "tool_results": [],
            "evidence": [],
            "errors": [],
        }

    result = build_agent_graph(runtime, planner_node=three_step_planner).invoke(
        {"user_query": "测试 Tool 预算"}
    )

    assert result["current_step"] == 2
    assert result["tool_call_count"] == 2
    assert len(result["execution_attempts"]) == 2
    assert len(result["tool_calls"]) == 2
    assert result["errors"][-1]["error_code"] == "MAX_TOOL_CALLS_EXCEEDED"
    assert result["reflection_count"] == 1
    assert "MAX_TOOL_CALLS_EXCEEDED" in result["final_answer"]
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_budget_exceeded" in logs
    assert "max_tool_calls=2" in logs
    runtime.registry.get("get_github_issue").client.close()


def _search_only_planner(state: dict) -> dict[str, object]:
    """故意只定位 AgentState，不读取实现，用于强制 Reflection。"""

    return {
        "plan": [
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
        ],
        "current_step": 0,
        "tool_calls": [],
        "tool_results": [],
        "evidence": [],
        "errors": [],
        "review_history": [],
        "reflection_count": 0,
        "reflection_history": [],
        "replan_count": 0,
        "replan_records": [],
    }


def test_review_fail_reflect_replan_execute_then_review_pass(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """第一轮缺少 read_file 时必须增量补证，并在第二轮 Review Pass。"""

    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()
    (agent_directory / "state.py").write_text(
        "from typing import TypedDict\n\nclass AgentState(TypedDict):\n    pass\n",
        encoding="utf-8",
    )
    runtime = build_tool_runtime(tmp_path)
    caplog.set_level(logging.INFO, logger="issueops.agent")

    result = build_agent_graph(runtime, planner_node=_search_only_planner).invoke(
        {"user_query": "定位 AgentState 定义并读取对应实现"}
    )

    assert [item["passed"] for item in result["review_history"]] == [False, True]
    assert result["reflection_count"] == 1
    assert result["replan_count"] == 1
    assert result["retry_count"] == 0
    assert result["review_passed"] is True
    assert [item["round"] for item in result["review_history"]] == [1, 2]
    assert result["reflection_history"][0]["round"] == 1
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "search_code",
        "read_file",
    ]
    assert [item["source"] for item in result["evidence"]] == [
        "search_code",
        "read_file",
    ]
    assert [step["id"] for step in result["plan"]] == [1, 2]
    replan_record = result["replan_records"][0]
    assert [step["tool_name"] for step in replan_record["previous_plan"]] == [
        "search_code"
    ]
    assert [step["tool_name"] for step in replan_record["added_steps"]] == [
        "read_file"
    ]
    assert result["evidence"][0]["step_id"] == 1
    assert result["evidence"][1]["step_id"] == 2
    assert result["draft_answer"] == result["final_answer"]
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=agent_review" in logs
    assert "event=agent_reflection" in logs
    assert "event=agent_replan" in logs
    runtime.registry.get("get_github_issue").client.close()


def _always_fail_reviewer(state: dict) -> dict[str, object]:
    """构造无法通过的确定性 Review，用于验证 MAX_REFLECTIONS。"""

    review = ReviewResult(
        round=len(state.get("review_history", [])) + 1,
        passed=False,
        score=0.2,
        criterion_scores={"goal_completion": 0.0},
        issues=["测试要求 Reviewer 始终失败。"],
        missing_evidence=[],
        reason="测试要求 Reviewer 始终失败。",
        recommended_action="继续检查。",
    )
    dumped = review.model_dump()
    return {
        "review": dumped,
        "review_score": review.score,
        "review_passed": False,
        "review_history": [*state.get("review_history", []), dumped],
    }


def test_reflection_limit_forces_degraded_final(tmp_path: Path) -> None:
    """Reviewer 持续失败时只允许一次 Reflection，然后必须正常 END。"""

    registry = build_default_registry(tmp_path)
    registry.register(StableGraphTool())
    runtime = ToolRuntime(registry, ReliabilityPolicy(max_retries=0))

    result = build_agent_graph(
        runtime,
        planner_node=_single_tool_planner("stable_graph_tool"),
        reviewer_node=_always_fail_reviewer,
        reflection_policy=ReflectionPolicy(max_reflections=1),
    ).invoke({"user_query": "测试 Reflection 上限"})

    assert result["reflection_count"] == 1
    assert result["replan_count"] == 1
    assert len(result["review_history"]) == 2
    assert len(result["tool_calls"]) == 1
    assert result["review_passed"] is False
    assert "任务未完全完成" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def test_replan_cannot_execute_after_tool_budget_exhausted(tmp_path: Path) -> None:
    """Reflection 可发生，但新增 read_file 不得越过 Stage 05 Tool 预算。"""

    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()
    (agent_directory / "state.py").write_text(
        "class AgentState:\n    pass\n",
        encoding="utf-8",
    )
    runtime = build_tool_runtime(
        tmp_path,
        policy=ReliabilityPolicy(max_retries=0, max_tool_calls=1),
    )

    result = build_agent_graph(runtime, planner_node=_search_only_planner).invoke(
        {"user_query": "定位 AgentState 定义并读取对应实现"}
    )

    assert result["reflection_count"] == 1
    assert result["replan_count"] == 1
    assert len(result["plan"]) == 2
    assert result["current_step"] == 1
    assert result["tool_call_count"] == 1
    assert len(result["tool_calls"]) == 1
    assert result["errors"][-1]["error_code"] == "MAX_TOOL_CALLS_EXCEEDED"
    assert result["review_passed"] is False
    assert "任务未完全完成" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()


def test_reviewer_exception_fails_closed_and_graph_ends(tmp_path: Path) -> None:
    """Reviewer Node 异常必须结构化失败，并受 Reflection limit 约束。"""

    def crashing_reviewer(state: dict) -> dict[str, object]:
        raise RuntimeError("模拟 Reviewer 异常")

    registry = build_default_registry(tmp_path)
    registry.register(StableGraphTool())
    runtime = ToolRuntime(registry, ReliabilityPolicy(max_retries=0))

    result = build_agent_graph(
        runtime,
        planner_node=_single_tool_planner("stable_graph_tool"),
        reviewer_node=crashing_reviewer,
        reflection_policy=ReflectionPolicy(max_reflections=0),
    ).invoke({"user_query": "测试 Reviewer 异常"})

    assert result["review_passed"] is False
    assert result.get("reflection_count", 0) == 0
    assert "Reviewer 内部异常" in result["review"]["issues"][0]
    assert "任务未完全完成" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()
