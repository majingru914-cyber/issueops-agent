"""产生可由 Executor 直接消费的确定性计划。"""

from agent.parsing import parse_github_reference
from agent.schemas import PlanStep, TaskAnalysis, TaskPlan
from agent.state import AgentState


def create_plan(state: AgentState) -> dict[str, object]:
    """根据分析结果选择 Tool 并生成完整参数。"""

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

    github_reference = parse_github_reference(user_query)

    if github_reference and github_reference.kind == "issue":
        steps = [
            PlanStep(
                id=1,
                goal="读取 GitHub Issue 详情",
                tool_name="get_github_issue",
                tool_args={
                    "owner": github_reference.owner,
                    "repo": github_reference.repo,
                    "issue_number": github_reference.number,
                },
            )
        ]
    elif github_reference and github_reference.kind == "pull_request":
        steps = [
            PlanStep(
                id=1,
                goal="读取 GitHub Pull Request 详情",
                tool_name="get_github_pr",
                tool_args={
                    "owner": github_reference.owner,
                    "repo": github_reference.repo,
                    "pull_number": github_reference.number,
                },
            )
        ]
    elif "agentstate" in user_query.casefold():
        steps = [
            PlanStep(
                id=1,
                goal="搜索 AgentState 定义",
                tool_name="search_code",
                tool_args={"query": "AgentState", "path": ".", "file_pattern": "*.py"},
            ),
            PlanStep(
                id=2,
                goal="读取 AgentState 定义文件",
                tool_name="read_file",
                tool_args={"path": "agent/state.py"},
            ),
        ]
    elif analysis.task_type == "repository_analysis":
        steps = [
            PlanStep(
                id=1,
                goal="查看项目顶层目录",
                tool_name="list_directory",
                tool_args={"path": "."},
            ),
            PlanStep(
                id=2,
                goal="识别主要 Python 模块",
                tool_name="search_code",
                tool_args={"query": "class ", "path": "agent", "file_pattern": "*.py"},
            ),
        ]
    elif analysis.task_type == "issue_investigation":
        query = "login" if "登录" in user_query else user_query
        steps = [
            PlanStep(
                id=1,
                goal="定位与问题相关的代码",
                tool_name="search_code",
                tool_args={"query": query, "path": ".", "file_pattern": "*.py"},
            )
        ]
    else:
        steps = [
            PlanStep(
                id=1,
                goal="查看项目顶层目录以建立任务上下文",
                tool_name="list_directory",
                tool_args={"path": "."},
            )
        ]

    task_plan = TaskPlan(steps=steps)
    return {
        "plan": [step.model_dump() for step in task_plan.steps],
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
