"""固定 AgentState Fixture。"""

from typing import TypedDict


class AgentState(TypedDict):
    """Benchmark 使用的最小状态。"""

    user_query: str
    final_answer: str
