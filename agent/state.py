"""LangGraph 运行时状态定义。"""

from typing import NotRequired, Required, TypedDict


class AgentState(TypedDict):
    """Stage 01 最小运行时状态。"""

    user_query: Required[str]
    task_type: NotRequired[str]
    goal: NotRequired[str]
    required_capabilities: NotRequired[list[str]]
    plan: NotRequired[list[dict[str, object]]]
