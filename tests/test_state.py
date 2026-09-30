"""状态与结构化模型测试。"""

import pytest
from pydantic import ValidationError

from agent.schemas import PlanStep, TaskAnalysis, TaskPlan
from agent.state import AgentState


def test_agent_state_exposes_stage_01_fields() -> None:
    """AgentState 只暴露 Stage 01 所需字段。"""

    assert AgentState.__required_keys__ == frozenset({"user_query"})
    assert AgentState.__optional_keys__ == frozenset(
        {"task_type", "goal", "required_capabilities", "plan"}
    )


def test_structured_models_accept_valid_data() -> None:
    """合法分析和计划能够通过 Pydantic 验证。"""

    analysis = TaskAnalysis(
        task_type="repository_analysis",
        goal="分析项目结构",
        required_capabilities=["repository_inspection"],
    )
    step = PlanStep(id=1, goal="查看顶层目录", tool_hint="list_directory")
    plan = TaskPlan(steps=[step])

    assert analysis.task_type == "repository_analysis"
    assert plan.steps == [step]


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (TaskAnalysis, {"task_type": "", "goal": "目标", "required_capabilities": []}),
        (PlanStep, {"id": 0, "goal": "", "tool_hint": None}),
        (TaskPlan, {"steps": []}),
    ],
)
def test_structured_models_reject_invalid_data(model: type, data: dict) -> None:
    """非法结构必须被 Pydantic 拒绝。"""

    with pytest.raises(ValidationError):
        model.model_validate(data)
