"""基于 State 中 Evidence 和 Error 生成最小最终回答。"""

from agent.schemas import Evidence, ExecutionError
from agent.state import AgentState
from tools.reliability import DEFAULT_MAX_TOOL_CALLS


def generate_answer(state: AgentState) -> dict[str, object]:
    """只使用已收集证据与错误生成确定性回答。"""

    evidence_items = [
        Evidence.model_validate(item) for item in state.get("evidence", [])
    ]
    error_items = [
        ExecutionError.model_validate(item) for item in state.get("errors", [])
    ]

    lines = [
        f"任务：{state.get('goal', state.get('user_query', ''))}",
        f"已执行 {state.get('current_step', 0)} 个计划步骤。",
        "",
        "证据：",
    ]
    if evidence_items:
        lines.extend(
            f"- 步骤 {item.step_id}（{item.source}）：{item.summary}"
            for item in evidence_items
        )
    else:
        lines.append("- 未获得成功的 Tool 证据。")

    if error_items:
        lines.extend(["", "错误："])
        lines.extend(
            f"- 步骤 {item.step_id}（{item.source}/{item.error_code}）："
            f"{item.error_message}"
            for item in error_items
        )

    return {"final_answer": "\n".join(lines)}


def has_more_steps(
    state: AgentState,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> str:
    """同时根据计划游标和实际 Tool attempt 预算选择下一条边。"""

    if state.get("current_step", 0) < len(state.get("plan", [])):
        if state.get("tool_call_count", 0) >= max_tool_calls:
            return "budget_exceeded"
        return "execute"
    return "generate_answer"
