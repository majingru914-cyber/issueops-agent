"""状态与结构化模型测试。"""

import pytest
from pydantic import ValidationError

from agent.schemas import (
    Evidence,
    PlanStep,
    ReflectionResult,
    ReviewResult,
    TaskAnalysis,
    TaskPlan,
    ToolCallRecord,
)
from agent.state import AgentState


def test_agent_state_exposes_stage_06_fields() -> None:
    """AgentState 应包含执行、Review、Reflection 和 Re-plan 字段。"""

    assert AgentState.__required_keys__ == frozenset({"user_query"})
    assert AgentState.__optional_keys__ == frozenset(
        {
            "task_id",
            "task_type",
            "goal",
            "required_capabilities",
            "plan",
            "current_step",
            "tool_calls",
            "tool_results",
            "execution_attempts",
            "tool_call_count",
            "retry_count",
            "evidence",
            "errors",
            "draft_answer",
            "review",
            "review_score",
            "review_passed",
            "review_history",
            "reflection",
            "reflection_count",
            "reflection_history",
            "replan_count",
            "replan_records",
            "final_answer",
        }
    )


def test_structured_models_accept_valid_data() -> None:
    """合法分析和计划能够通过 Pydantic 验证。"""

    analysis = TaskAnalysis(
        task_type="repository_analysis",
        goal="分析项目结构",
        required_capabilities=["repository_inspection"],
    )
    step = PlanStep(
        id=1,
        goal="查看顶层目录",
        tool_name="list_directory",
        tool_args={"path": "."},
    )
    plan = TaskPlan(steps=[step])
    tool_call = ToolCallRecord(
        step_id=1,
        tool_name="list_directory",
        arguments={"path": "."},
    )
    evidence = Evidence(
        step_id=1,
        source="list_directory",
        summary="发现项目目录。",
        raw_result={"entries": []},
    )
    review = ReviewResult(
        round=1,
        passed=True,
        score=1.0,
        criterion_scores={"goal_completion": 1.0},
        issues=[],
        missing_evidence=[],
        reason="Evidence 充分。",
    )
    reflection = ReflectionResult(
        round=1,
        failure_reason="缺少 Evidence。",
        missing_information=[],
        missing_evidence=["read_file"],
        plan_problems=[],
        proposed_actions=["read_file"],
    )

    assert analysis.task_type == "repository_analysis"
    assert plan.steps == [step]
    assert tool_call.arguments == {"path": "."}
    assert evidence.source_type == "tool"
    assert review.passed is True
    assert reflection.proposed_actions == ["read_file"]


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (TaskAnalysis, {"task_type": "", "goal": "目标", "required_capabilities": []}),
        (
            PlanStep,
            {
                "id": 0,
                "goal": "",
                "tool_name": None,
                "tool_args": {},
                "requires_tool": True,
            },
        ),
        (TaskPlan, {"steps": []}),
    ],
)
def test_structured_models_reject_invalid_data(model: type, data: dict) -> None:
    """非法结构必须被 Pydantic 拒绝。"""

    with pytest.raises(ValidationError):
        model.model_validate(data)
