"""确定性任务分析节点。"""

from agent.schemas import TaskAnalysis
from agent.state import AgentState


def analyze_task(state: AgentState) -> dict[str, object]:
    """分析用户请求并返回经过验证的状态增量。"""

    user_query = state.get("user_query", "").strip()
    if not user_query:
        raise ValueError("用户请求不能为空。")

    normalized_query = user_query.casefold()

    if any(
        keyword in normalized_query
        for keyword in ("问题", "错误", "缺陷", "异常", "bug", "定位", "排查")
    ):
        analysis = TaskAnalysis(
            task_type="issue_investigation",
            goal=f"定位并分析软件问题：{user_query}",
            required_capabilities=["code_inspection", "problem_analysis"],
        )
    elif any(
        keyword in normalized_query
        for keyword in ("项目结构", "仓库", "目录", "模块", "repository")
    ):
        analysis = TaskAnalysis(
            task_type="repository_analysis",
            goal="分析当前项目的目录和模块结构",
            required_capabilities=["repository_inspection"],
        )
    else:
        analysis = TaskAnalysis(
            task_type="software_task",
            goal=user_query,
            required_capabilities=["task_analysis"],
        )

    return analysis.model_dump()
