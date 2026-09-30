"""任务规划节点测试。"""

from agent.schemas import TaskPlan
from agent.planner import create_plan


def test_create_repository_plan() -> None:
    """合法分析状态应生成有序且非空的计划。"""

    state = {
        "user_query": "分析项目结构",
        "task_type": "repository_analysis",
        "goal": "分析当前项目的目录和模块结构",
        "required_capabilities": ["repository_inspection"],
    }

    result = create_plan(state)
    plan = TaskPlan.model_validate({"steps": result["plan"]})

    assert plan.steps
    assert [step.id for step in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert all(step.goal for step in plan.steps)
