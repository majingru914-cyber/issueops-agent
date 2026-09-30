"""对 Draft、Goal、Plan、Evidence 与 Error 执行确定性 Review。"""

import logging

from agent.parsing import parse_github_reference
from agent.schemas import (
    Evidence,
    ExecutionError,
    ReviewResult,
    TaskPlan,
    ToolResultRecord,
)
from agent.state import AgentState


REVIEW_PASS_THRESHOLD = 0.8
LOGGER = logging.getLogger("issueops.agent")


def review_answer(state: AgentState) -> dict[str, object]:
    """以可解释规则审查任务完成度，并 fail closed 处理内部异常。"""

    try:
        review = _build_review(state)
    except Exception as error:  # Reviewer 不得使 Graph crash
        return review_failure(state, error)
    return _review_update(state, review)


def review_failure(state: AgentState, error: Exception) -> dict[str, object]:
    """把 Reviewer 内部异常转换为结构化失败，而不是抛出 Graph。"""

    round_number = len(state.get("review_history", [])) + 1
    review = ReviewResult(
        round=round_number,
        passed=False,
        score=0.0,
        criterion_scores={
            "goal_completion": 0.0,
            "evidence_completeness": 0.0,
            "execution_failure": 0.0,
            "plan_completion": 0.0,
            "answer_grounding": 0.0,
        },
        issues=[f"Reviewer 内部异常：{type(error).__name__}"],
        missing_evidence=[],
        reason="Reviewer 无法完成可靠判断，按 fail closed 处理。",
        recommended_action="检查 Reviewer 输入状态并补充可验证 Evidence。",
    )
    return _review_update(state, review)


def _build_review(state: AgentState) -> ReviewResult:
    """计算五类标准，并使用唯一 Threshold 得出 ReviewResult。"""

    plan = TaskPlan.model_validate({"steps": state.get("plan")})
    evidence = [
        Evidence.model_validate(item) for item in state.get("evidence", [])
    ]
    errors = [
        ExecutionError.model_validate(item) for item in state.get("errors", [])
    ]
    results = [
        ToolResultRecord.model_validate(item)
        for item in state.get("tool_results", [])
    ]
    draft_answer = state.get("draft_answer", "").strip()

    required_sources = _required_evidence_sources(state, plan)
    evidence_sources = {item.source for item in evidence}
    missing_sources = sorted(required_sources - evidence_sources)

    goal_completed = bool(evidence) and not missing_sources
    evidence_complete = bool(evidence) and required_sources.issubset(evidence_sources)
    result_step_ids = {item.step_id for item in results}
    plan_step_ids = {item.id for item in plan.steps}
    plan_completed = (
        state.get("current_step", 0) >= len(plan.steps)
        and plan_step_ids.issubset(result_step_ids)
    )
    answer_grounded = bool(draft_answer) and bool(evidence) and all(
        item.source in draft_answer and item.summary in draft_answer
        for item in evidence
    )

    critical_errors = [
        item
        for item in errors
        if (
            not evidence
            or item.source in missing_sources
            or (
                item.error_code == "MAX_TOOL_CALLS_EXCEEDED"
                and not goal_completed
            )
        )
    ]
    execution_acceptable = not critical_errors

    criteria = {
        "goal_completion": float(goal_completed),
        "evidence_completeness": float(evidence_complete),
        "execution_failure": float(execution_acceptable),
        "plan_completion": float(plan_completed),
        "answer_grounding": float(answer_grounded),
    }
    raw_score = sum(criteria.values()) / len(criteria)
    mandatory_passed = all(value == 1.0 for value in criteria.values())
    score = raw_score if mandatory_passed else min(raw_score, REVIEW_PASS_THRESHOLD - 0.01)
    passed = score >= REVIEW_PASS_THRESHOLD

    issues = []
    if not goal_completed:
        issues.append("当前 Evidence 尚未覆盖用户目标。")
    if not evidence_complete:
        issues.append("存在必需但尚未获得的 Evidence。")
    if critical_errors:
        issues.append("关键 Tool Error 阻止了任务完成。")
    if not plan_completed:
        issues.append("当前 Plan 尚未完整执行。")
    if not answer_grounded:
        issues.append("Draft Answer 未被当前 Evidence 完整支撑。")

    reason = (
        "Goal、Evidence、Plan 与 Draft 均通过确定性 Review。"
        if passed
        else "；".join(issues)
    )
    recommended_action = (
        None
        if passed
        else (
            f"补充 Evidence：{', '.join(missing_sources)}。"
            if missing_sources
            else "修复 Review 指出的缺口后重新生成 Draft。"
        )
    )
    return ReviewResult(
        round=len(state.get("review_history", [])) + 1,
        passed=passed,
        score=round(score, 4),
        criterion_scores=criteria,
        issues=issues,
        missing_evidence=missing_sources,
        reason=reason,
        recommended_action=recommended_action,
    )


def _required_evidence_sources(state: AgentState, plan: TaskPlan) -> set[str]:
    """从用户目标与任务类型确定本轮完成所需的 Evidence source。"""

    user_query = state.get("user_query", "")
    normalized_query = user_query.casefold()
    github_reference = parse_github_reference(user_query)
    if github_reference and github_reference.kind == "issue":
        return {"get_github_issue"}
    if github_reference and github_reference.kind == "pull_request":
        return {"get_github_pr"}

    required: set[str] = set()
    if "agentstate" in normalized_query or any(
        keyword in normalized_query for keyword in ("定义", "对应实现")
    ):
        required.update({"search_code", "read_file"})
    elif any(keyword in normalized_query for keyword in ("查找", "定位", "搜索")):
        required.add("search_code")

    if state.get("task_type") == "repository_analysis" and not required:
        required.update({"list_directory", "search_code"})
    elif state.get("task_type") == "issue_investigation" and not required:
        required.add("search_code")

    if not required:
        required.update(
            step.tool_name
            for step in plan.steps
            if step.requires_tool and step.tool_name is not None
        )
    return required


def _review_update(state: AgentState, review: ReviewResult) -> dict[str, object]:
    """写入当前 Review 和完整 Review history。"""

    LOGGER.info(
        "event=agent_review task_id=%s round=%s passed=%s score=%.4f "
        "issues=%s missing_evidence=%s",
        state.get("task_id", "unknown"),
        review.round,
        str(review.passed).lower(),
        review.score,
        len(review.issues),
        len(review.missing_evidence),
    )
    dumped = review.model_dump()
    return {
        "review": dumped,
        "review_score": review.score,
        "review_passed": review.passed,
        "review_history": [*state.get("review_history", []), dumped],
    }
