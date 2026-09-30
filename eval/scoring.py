"""在 Agent Run 结束后执行 Case 评分，不修改 AgentState。"""

from typing import Any

from eval.schemas import (
    ArgumentMatchMode,
    EvaluationCase,
    EvaluationCaseResult,
    ExpectedTaskStatus,
    FailureCategory,
    ToolArgumentCheck,
)


def score_case(
    case: EvaluationCase,
    final_state: dict[str, Any],
    latency_ms: float,
    exception: Exception | None = None,
) -> EvaluationCaseResult:
    """根据结构化状态和期望契约计算单 Case 结果。"""

    actual_calls = [
        item for item in final_state.get("tool_calls", []) if isinstance(item, dict)
    ]
    actual_tools = [str(item.get("tool_name", "")) for item in actual_calls]
    actual_evidence_sources = sorted(
        {
            str(item.get("source", ""))
            for item in final_state.get("evidence", [])
            if isinstance(item, dict) and item.get("source")
        }
    )
    actual_error_codes = sorted(
        {
            str(item.get("error_code", ""))
            for item in final_state.get("errors", [])
            if isinstance(item, dict) and item.get("error_code")
        }
    )
    attempts = [
        item
        for item in final_state.get("execution_attempts", [])
        if isinstance(item, dict)
    ]
    tool_results = [
        item for item in final_state.get("tool_results", []) if isinstance(item, dict)
    ]
    reviews = [
        item for item in final_state.get("review_history", []) if isinstance(item, dict)
    ]
    review_passed = final_state.get("review_passed")
    if exception is not None:
        task_status = ExpectedTaskStatus.FAILED
    elif review_passed is True:
        task_status = ExpectedTaskStatus.COMPLETED
    else:
        task_status = ExpectedTaskStatus.PARTIAL

    argument_checks = _score_arguments(case, actual_calls)
    argument_accuracy = _rate(sum(item.passed for item in argument_checks), len(argument_checks))
    tool_selection_correct = actual_tools == case.expected_tools
    retries = int(final_state.get("retry_count", 0))
    reflections = int(final_state.get("reflection_count", 0))
    fallback_count = sum(
        bool(item.get("result", {}).get("fallback_from"))
        for item in tool_results
        if isinstance(item.get("result"), dict)
    )
    timeout_count = sum(item.get("error_code") == "TIMEOUT" for item in attempts)
    max_retries_count = actual_error_codes.count("MAX_RETRIES_EXCEEDED")
    max_tool_calls_count = actual_error_codes.count("MAX_TOOL_CALLS_EXCEEDED")
    first_review_passed = (
        bool(reviews[0].get("passed")) if reviews else None
    )
    recovered = (
        bool(reviews)
        and first_review_passed is False
        and review_passed is True
        and reflections > 0
    )
    final_answer = final_state.get("final_answer")
    final_answer_non_empty = isinstance(final_answer, str) and bool(final_answer.strip())

    categories: list[FailureCategory] = []
    reasons: list[str] = []

    def fail(category: FailureCategory, reason: str) -> None:
        if category not in categories:
            categories.append(category)
        reasons.append(reason)

    if exception is not None:
        fail(
            FailureCategory.RUNTIME_ERROR,
            f"Agent Run 抛出 {type(exception).__name__}。",
        )
    if (
        case.expected_task_type is not None
        and final_state.get("task_type") != case.expected_task_type
    ):
        fail(
            FailureCategory.ANALYSIS_ERROR,
            f"task_type 期望 {case.expected_task_type}，实际 "
            f"{final_state.get('task_type')}。",
        )
    if not tool_selection_correct:
        fail(
            FailureCategory.TOOL_SELECTION_ERROR,
            f"Tool 序列期望 {case.expected_tools}，实际 {actual_tools}。",
        )
    if not all(item.passed for item in argument_checks):
        fail(FailureCategory.TOOL_ARGUMENT_ERROR, "至少一个 Tool 参数检查未通过。")
    if not set(case.required_evidence_sources).issubset(actual_evidence_sources):
        fail(
            FailureCategory.EVIDENCE_ERROR,
            f"Evidence source 期望至少 {case.required_evidence_sources}，实际 "
            f"{actual_evidence_sources}。",
        )
    if set(case.expected_error_codes) != set(actual_error_codes):
        failure_category = (
            FailureCategory.BUDGET_EXCEEDED
            if "MAX_TOOL_CALLS_EXCEEDED" in actual_error_codes
            else FailureCategory.TOOL_EXECUTION_ERROR
        )
        fail(
            failure_category,
            f"Error code 期望 {sorted(case.expected_error_codes)}，实际 "
            f"{actual_error_codes}。",
        )
    if task_status != case.expected_status:
        fail(
            FailureCategory.UNEXPECTED_STATUS,
            f"任务状态期望 {case.expected_status}，实际 {task_status}。",
        )
    if (
        case.expected_review_passed is not None
        and review_passed is not case.expected_review_passed
    ):
        fail(
            FailureCategory.REVIEW_ERROR,
            f"Review 期望 {case.expected_review_passed}，实际 {review_passed}。",
        )
    if (
        case.expected_reflection is not None
        and (reflections > 0) is not case.expected_reflection
    ):
        fail(
            FailureCategory.REFLECTION_ERROR,
            f"Reflection 期望 {case.expected_reflection}，实际次数 {reflections}。",
        )
    if case.expected_retry is not None and (retries > 0) is not case.expected_retry:
        fail(
            FailureCategory.RELIABILITY_ERROR,
            f"Retry 期望 {case.expected_retry}，实际次数 {retries}。",
        )
    if (
        case.expected_fallback is not None
        and (fallback_count > 0) is not case.expected_fallback
    ):
        fail(
            FailureCategory.RELIABILITY_ERROR,
            f"Fallback 期望 {case.expected_fallback}，实际次数 {fallback_count}。",
        )
    if not final_answer_non_empty and exception is None:
        fail(FailureCategory.FINAL_ANSWER_ERROR, "Final Answer 为空。")
    for required_text in case.final_answer_contains:
        if not isinstance(final_answer, str) or required_text not in final_answer:
            fail(
                FailureCategory.FINAL_ANSWER_ERROR,
                f"Final Answer 未包含要求文本：{required_text}。",
            )

    return EvaluationCaseResult(
        case_id=case.id,
        category=case.category,
        description=case.description,
        user_query=case.user_query,
        passed=not reasons,
        expected_status=case.expected_status,
        task_status=task_status,
        expected_review_passed=case.expected_review_passed,
        review_passed=review_passed if isinstance(review_passed, bool) else None,
        expected_tools=case.expected_tools,
        actual_tools=actual_tools,
        tool_selection_correct=tool_selection_correct,
        tool_argument_checks=argument_checks,
        tool_argument_accuracy=argument_accuracy,
        required_evidence_sources=case.required_evidence_sources,
        actual_evidence_sources=actual_evidence_sources,
        expected_error_codes=case.expected_error_codes,
        actual_error_codes=actual_error_codes,
        tool_calls=len(actual_calls),
        execution_attempts=len(attempts),
        retries=retries,
        reflections=reflections,
        fallback_count=fallback_count,
        timeout_count=timeout_count,
        max_retries_exceeded_count=max_retries_count,
        max_tool_calls_exceeded_count=max_tool_calls_count,
        first_review_passed=first_review_passed,
        recovery_eligible=case.recovery_eligible,
        recovered=recovered,
        latency_ms=max(0.0, latency_ms),
        final_answer_non_empty=final_answer_non_empty,
        failure_categories=categories,
        failure_reasons=reasons,
        exception_summary=(
            f"{type(exception).__name__}: {exception}" if exception else None
        ),
    )


def arguments_match(
    expected: dict[str, Any],
    actual: dict[str, Any],
    mode: ArgumentMatchMode,
) -> bool:
    """比较结构化参数；subset 支持嵌套 dict。"""

    if mode is ArgumentMatchMode.EXACT:
        return expected == actual
    return _is_subset(expected, actual)


def _score_arguments(
    case: EvaluationCase,
    actual_calls: list[dict[str, Any]],
) -> list[ToolArgumentCheck]:
    checks = []
    for index, expectation in enumerate(case.expected_tool_args):
        actual_call = actual_calls[index] if index < len(actual_calls) else None
        raw_actual = actual_call.get("arguments") if actual_call else None
        actual_arguments = raw_actual if isinstance(raw_actual, dict) else None
        actual_tool = actual_call.get("tool_name") if actual_call else None
        passed = (
            actual_tool == expectation.tool_name
            and actual_arguments is not None
            and arguments_match(
                expectation.arguments,
                actual_arguments,
                expectation.mode,
            )
        )
        checks.append(
            ToolArgumentCheck(
                call_index=index,
                tool_name=expectation.tool_name,
                mode=expectation.mode,
                expected=expectation.arguments,
                actual=actual_arguments,
                passed=passed,
                reason=(
                    "参数匹配。"
                    if passed
                    else f"期望 {expectation.arguments}，实际 {actual_arguments}。"
                ),
            )
        )
    return checks


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _is_subset(value, actual[key])
            for key, value in expected.items()
        )
    return expected == actual


def _rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else round(numerator / denominator, 6)
