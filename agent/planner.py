"""确定性任务规划节点。"""

from agent.schemas import PlanStep, TaskAnalysis, TaskPlan
from agent.state import AgentState


def create_plan(state: AgentState) -> dict[str, object]:
    """根据分析结果生成经过验证且不执行工具的计划。"""

    user_query = state.get("user_query", "").strip()
    if not user_query:
        raise ValueError("用户请求不能为空。")

    analysis = TaskAnalysis.model_validate(
        {
            "task_type": state.get("task_type"),
            "goal": state.get("goal"),
            "required_capabilities": state.get("required_capabilities"),
        }
    )

    if analysis.task_type == "repository_analysis":
        steps = [
            PlanStep(id=1, goal="查看项目顶层目录", tool_hint="list_directory"),
            PlanStep(id=2, goal="识别主要代码模块", tool_hint="search_repository"),
            PlanStep(id=3, goal="整理项目结构结论"),
        ]
    elif analysis.task_type == "issue_investigation":
        steps = [
            PlanStep(id=1, goal="定位与问题相关的代码模块", tool_hint="search_repository"),
            PlanStep(id=2, goal="检查相关实现与潜在故障点", tool_hint="read_file"),
            PlanStep(id=3, goal="整理问题原因与后续处理建议"),
        ]
    else:
        steps = [
            PlanStep(id=1, goal=f"澄清任务范围：{user_query}"),
            PlanStep(id=2, goal="整理可执行的后续步骤"),
        ]

    task_plan = TaskPlan(steps=steps)
    return {"plan": [step.model_dump() for step in task_plan.steps]}
