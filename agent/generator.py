"""基于 Evidence 生成 Draft，并在 Review 后形成 Final Answer。"""

from agent.schemas import Evidence, ExecutionError, ReviewResult
from agent.state import AgentState
from tools.reliability import DEFAULT_MAX_TOOL_CALLS


def generate_draft_answer(state: AgentState) -> dict[str, object]:
    """只使用累计 Evidence 与 Error 生成待 Review 的确定性 Draft。"""

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

    return {"draft_answer": "\n".join(lines)}


def finalize_answer(state: AgentState) -> dict[str, object]:
    """Review Pass 时接受 Draft，否则明确输出未完全完成的降级答案。"""

    draft_answer = state.get("draft_answer", "").strip()
    raw_review = state.get("review")
    if state.get("review_passed") is True and raw_review:
        return {"final_answer": draft_answer}

    review = ReviewResult.model_validate(raw_review) if raw_review else None
    lines = [
        "任务未完全完成。",
        "当前结论基于已经获得的 Evidence，但仍未达到 Review 标准。",
    ]
    if draft_answer:
        lines.extend(["", draft_answer])
    if review is not None:
        lines.extend(["", "未解决问题："])
        lines.extend(f"- {issue}" for issue in review.issues)
        if review.missing_evidence:
            lines.extend(["", "缺失 Evidence："])
            lines.extend(f"- {item}" for item in review.missing_evidence)

    errors = [
        ExecutionError.model_validate(item) for item in state.get("errors", [])
    ]
    if errors:
        lines.extend(["", "主要 Error："])
        lines.extend(
            f"- {item.source}/{item.error_code}：{item.error_message}"
            for item in errors
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
    return "generate_draft"
