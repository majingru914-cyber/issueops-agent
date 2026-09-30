"""增量 Re-plan、Step ID 与 Evidence Preservation 测试。"""

from pathlib import Path

from agent.replanner import replan
from agent.schemas import ReflectionResult, TaskPlan
from tools.runtime import build_default_registry


def _state() -> dict:
    """构建只有 search_code Evidence、缺少 read_file 的状态。"""

    reflection = ReflectionResult(
        round=1,
        failure_reason="缺少实现文件内容。",
        missing_information=["Evidence 不完整。"],
        missing_evidence=["read_file"],
        plan_problems=[],
        proposed_actions=["read_file"],
    )
    return {
        "user_query": "定位 AgentState 定义并读取对应实现",
        "plan": [
            {
                "id": 1,
                "goal": "定位 AgentState",
                "tool_name": "search_code",
                "tool_args": {"query": "AgentState", "path": "."},
                "requires_tool": True,
            }
        ],
        "current_step": 1,
        "evidence": [
            {
                "step_id": 1,
                "source_type": "tool",
                "source": "search_code",
                "summary": "定位到 agent/state.py。",
                "raw_result": {
                    "matches": [
                        {"path": "agent/state.py", "line_number": 6, "line": "class AgentState"}
                    ]
                },
            }
        ],
        "tool_calls": [{"step_id": 1, "tool_name": "search_code", "arguments": {}}],
        "tool_results": [{"step_id": 1, "result": {"success": True}}],
        "execution_attempts": [{"attempt": 1}],
        "errors": [],
        "reflection": reflection.model_dump(),
        "replan_count": 0,
        "replan_records": [],
    }


def test_replan_adds_only_missing_read_step_and_preserves_state(tmp_path: Path) -> None:
    """Re-plan 必须追加 read_file，保持旧 Evidence 和 Trace 不变。"""

    state = _state()
    update = replan(state)
    merged = {**state, **update}
    plan = TaskPlan.model_validate({"steps": merged["plan"]})

    assert [step.id for step in plan.steps] == [1, 2]
    assert [step.tool_name for step in plan.steps] == ["search_code", "read_file"]
    assert plan.steps[1].tool_args == {"path": "agent/state.py"}
    assert merged["current_step"] == 1
    assert merged["evidence"] == state["evidence"]
    assert merged["tool_calls"] == state["tool_calls"]
    assert merged["tool_results"] == state["tool_results"]
    assert merged["execution_attempts"] == state["execution_attempts"]
    assert update["replan_count"] == 1
    assert update["replan_records"][0]["added_steps"][0]["id"] == 2

    registry = build_default_registry(tmp_path)
    tool = registry.get(plan.steps[1].tool_name or "")
    tool.args_schema.model_validate(plan.steps[1].tool_args)
    registry.get("get_github_issue").client.close()


def test_replan_does_not_duplicate_existing_step() -> None:
    """已存在相同 read_file 步骤时不得复制旧 Plan。"""

    state = _state()
    state["plan"].append(
        {
            "id": 2,
            "goal": "读取实现",
            "tool_name": "read_file",
            "tool_args": {"path": "agent/state.py"},
            "requires_tool": True,
        }
    )

    update = replan(state)

    assert len(update["plan"]) == 2
    assert update["replan_records"][0]["added_steps"] == []
