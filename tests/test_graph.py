"""Plan-and-Execute Graph 的结构与端到端测试。"""

from pathlib import Path
import logging
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from agent.graph import build_agent_graph
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
    """Graph 必须包含 Executor、Evidence、条件循环和 Final 节点。"""

    runtime = build_tool_runtime(tmp_path)
    graph_description = build_agent_graph(runtime).get_graph()

    assert {
        "analyze_task",
        "create_plan",
        "execute_step",
            "collect_evidence",
            "tool_budget_exceeded",
            "generate_answer",
    }.issubset(graph_description.nodes)
    assert {
        ("__start__", "analyze_task"),
        ("analyze_task", "create_plan"),
        ("create_plan", "execute_step"),
        ("execute_step", "collect_evidence"),
        ("collect_evidence", "execute_step"),
        ("collect_evidence", "tool_budget_exceeded"),
        ("collect_evidence", "generate_answer"),
        ("tool_budget_exceeded", "generate_answer"),
        ("generate_answer", "__end__"),
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
    assert "MAX_TOOL_CALLS_EXCEEDED" in result["final_answer"]
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=tool_budget_exceeded" in logs
    assert "max_tool_calls=2" in logs
    runtime.registry.get("get_github_issue").client.close()
