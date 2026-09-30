"""LangGraph 权威运行时状态定义。"""

from typing import Any, NotRequired, Required, TypedDict


class AgentState(TypedDict):
    """Stage 05 Reliability-aware Plan-and-Execute 运行时状态。"""

    user_query: Required[str]
    task_id: NotRequired[str]
    task_type: NotRequired[str]
    goal: NotRequired[str]
    required_capabilities: NotRequired[list[str]]
    plan: NotRequired[list[dict[str, Any]]]
    current_step: NotRequired[int]
    tool_calls: NotRequired[list[dict[str, Any]]]
    tool_results: NotRequired[list[dict[str, Any]]]
    execution_attempts: NotRequired[list[dict[str, Any]]]
    tool_call_count: NotRequired[int]
    retry_count: NotRequired[int]
    evidence: NotRequired[list[dict[str, Any]]]
    errors: NotRequired[list[dict[str, Any]]]
    final_answer: NotRequired[str]
