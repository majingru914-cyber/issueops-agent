"""Plan-and-Execute Graph 的结构与端到端测试。"""

from pathlib import Path

import httpx
import pytest

from agent.graph import build_agent_graph
from tools.github_client import GitHubClient
from tools.runtime import build_tool_runtime


def test_graph_compiles_with_execution_loop(tmp_path: Path) -> None:
    """Graph 必须包含 Executor、Evidence、条件循环和 Final 节点。"""

    runtime = build_tool_runtime(tmp_path)
    graph_description = build_agent_graph(runtime).get_graph()

    assert {
        "analyze_task",
        "create_plan",
        "execute_step",
        "collect_evidence",
        "generate_answer",
    }.issubset(graph_description.nodes)
    assert {
        ("__start__", "analyze_task"),
        ("analyze_task", "create_plan"),
        ("create_plan", "execute_step"),
        ("execute_step", "collect_evidence"),
        ("collect_evidence", "execute_step"),
        ("collect_evidence", "generate_answer"),
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
        ("read_file", {"path": "missing.txt"}, "EXECUTION_FAILED"),
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
    assert result["errors"][0]["error_code"] == expected_code
    assert "错误" in result["final_answer"]
    runtime.registry.get("get_github_issue").client.close()
