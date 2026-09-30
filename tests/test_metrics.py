"""Evaluation Metrics 的 golden test。"""

from eval.metrics import calculate_category_metrics, calculate_metrics
from eval.schemas import (
    ArgumentMatchMode,
    EvaluationCaseResult,
    EvaluationCategory,
    ExpectedTaskStatus,
    ToolArgumentCheck,
)


def _result(
    case_id: str,
    *,
    passed: bool = True,
    category: EvaluationCategory = EvaluationCategory.REPOSITORY,
    expected_status: ExpectedTaskStatus = ExpectedTaskStatus.COMPLETED,
    task_status: ExpectedTaskStatus = ExpectedTaskStatus.COMPLETED,
    selection: bool = True,
    argument: bool = True,
    tool_calls: int = 1,
    attempts: int = 1,
    retries: int = 0,
    reflections: int = 0,
    latency_ms: float = 10.0,
    recovery_eligible: bool = False,
    recovered: bool = False,
    timeout_count: int = 0,
    fallback_count: int = 0,
    max_retries: int = 0,
    max_tool_calls: int = 0,
) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        case_id=case_id,
        category=category,
        description="Golden Case",
        user_query="测试",
        passed=passed,
        expected_status=expected_status,
        task_status=task_status,
        expected_tools=["read_file"],
        actual_tools=["read_file"] if selection else ["search_code"],
        tool_selection_correct=selection,
        tool_argument_checks=[
            ToolArgumentCheck(
                call_index=0,
                tool_name="read_file",
                mode=ArgumentMatchMode.EXACT,
                expected={"path": "README.md"},
                actual={"path": "README.md" if argument else "other.md"},
                passed=argument,
                reason="golden",
            )
        ],
        tool_argument_accuracy=1.0 if argument else 0.0,
        required_evidence_sources=[],
        actual_evidence_sources=[],
        expected_error_codes=[],
        actual_error_codes=[],
        tool_calls=tool_calls,
        execution_attempts=attempts,
        retries=retries,
        reflections=reflections,
        fallback_count=fallback_count,
        timeout_count=timeout_count,
        max_retries_exceeded_count=max_retries,
        max_tool_calls_exceeded_count=max_tool_calls,
        recovery_eligible=recovery_eligible,
        recovered=recovered,
        latency_ms=latency_ms,
        final_answer_non_empty=True,
    )


def test_metrics_golden_calculation() -> None:
    """4 个手工结果必须得到精确可复核的分母与数值。"""

    results = [
        _result("case-1", latency_ms=10),
        _result(
            "case-2",
            passed=False,
            task_status=ExpectedTaskStatus.PARTIAL,
            selection=False,
            argument=False,
            tool_calls=2,
            attempts=3,
            retries=1,
            reflections=1,
            latency_ms=20,
            timeout_count=1,
            max_retries=1,
        ),
        _result(
            "case-3",
            category=EvaluationCategory.RELIABILITY,
            expected_status=ExpectedTaskStatus.PARTIAL,
            task_status=ExpectedTaskStatus.PARTIAL,
            retries=2,
            reflections=2,
            latency_ms=30,
            fallback_count=1,
            max_tool_calls=1,
        ),
        _result(
            "case-4",
            category=EvaluationCategory.REFLECTION,
            expected_status=ExpectedTaskStatus.PARTIAL,
            task_status=ExpectedTaskStatus.PARTIAL,
            tool_calls=0,
            attempts=0,
            reflections=1,
            latency_ms=40,
            recovery_eligible=True,
            recovered=True,
        ),
    ]

    metrics = calculate_metrics(results)

    assert metrics.total_cases == 4
    assert metrics.passed_cases == 3
    assert metrics.case_pass_rate == 0.75
    assert metrics.task_success_eligible_cases == 2
    assert metrics.successful_tasks == 1
    assert metrics.task_success_rate == 0.5
    assert metrics.tool_selection_accuracy == 0.75
    assert metrics.tool_argument_accuracy == 0.75
    assert metrics.avg_tool_calls == 1.0
    assert metrics.avg_execution_attempts == 1.25
    assert metrics.avg_latency_ms == 25.0
    assert metrics.p50_latency_ms == 20.0
    assert metrics.p95_latency_ms == 40.0
    assert metrics.retry_rate == 0.5
    assert metrics.total_retries == 3
    assert metrics.avg_retries_per_case == 0.75
    assert metrics.reflection_rate == 0.75
    assert metrics.avg_reflection_count == 1.0
    assert metrics.recovery_rate == 1.0
    assert metrics.timeout_count == 1
    assert metrics.fallback_count == 1
    assert metrics.max_retries_exceeded_count == 1
    assert metrics.max_tool_calls_exceeded_count == 1


def test_category_metrics_keep_empty_categories_visible() -> None:
    """报告必须固定展示四类，即使单 Case 调试时部分分类为空。"""

    metrics = calculate_category_metrics([_result("case-1")])

    assert metrics[EvaluationCategory.REPOSITORY].pass_rate == 1.0
    assert metrics[EvaluationCategory.GITHUB].total_cases == 0
    assert metrics[EvaluationCategory.GITHUB].pass_rate == 0.0
