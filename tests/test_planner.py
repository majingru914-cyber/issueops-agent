"""可执行 Planner Contract 测试。"""

from pathlib import Path

import pytest

from agent.analyzer import analyze_task
from agent.planner import create_plan
from agent.schemas import TaskPlan
from tools.runtime import build_default_registry


@pytest.mark.parametrize(
    ("user_query", "expected_tools"),
    [
        ("查找项目中 AgentState 的定义", ["search_code", "read_file"]),
        ("分析 octocat/Hello-World Issue #7", ["get_github_issue"]),
        ("分析 octocat/Hello-World PR #8", ["get_github_pr"]),
    ],
)
def test_planner_produces_executable_validated_steps(
    tmp_path: Path,
    user_query: str,
    expected_tools: list[str],
) -> None:
    """Planner 应决定 Tool 和参数，且参数通过对应 Tool Schema。"""

    analysis = analyze_task({"user_query": user_query})
    state = {"user_query": user_query, **analysis}
    result = create_plan(state)
    plan = TaskPlan.model_validate({"steps": result["plan"]})
    registry = build_default_registry(tmp_path)

    assert [step.id for step in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert [step.tool_name for step in plan.steps] == expected_tools
    assert all(step.tool_args for step in plan.steps)
    for step in plan.steps:
        tool = registry.get(step.tool_name or "")
        tool.args_schema.model_validate(step.tool_args)

    registry.get("get_github_issue").client.close()


def test_planner_initializes_execution_state() -> None:
    """新计划必须重置所有执行期集合和游标。"""

    user_query = "分析项目结构"
    result = create_plan({"user_query": user_query, **analyze_task({"user_query": user_query})})

    assert result["current_step"] == 0
    assert result["tool_calls"] == []
    assert result["tool_results"] == []
    assert result["evidence"] == []
    assert result["errors"] == []
