"""把独立 Case Result 聚合为 Evaluation Metrics。"""

import math

from eval.schemas import (
    CategoryMetrics,
    EvaluationCategory,
    EvaluationCaseResult,
    EvaluationMetrics,
    ExpectedTaskStatus,
)


def calculate_metrics(results: list[EvaluationCaseResult]) -> EvaluationMetrics:
    """按文档定义的分母计算所有 Stage 08 指标。"""

    total = len(results)
    passed = sum(item.passed for item in results)
    normal_results = [
        item
        for item in results
        if item.expected_status is ExpectedTaskStatus.COMPLETED
    ]
    successful_tasks = sum(
        item.passed and item.task_status is ExpectedTaskStatus.COMPLETED
        for item in normal_results
    )
    argument_checks = [
        check for item in results for check in item.tool_argument_checks
    ]
    retry_cases = sum(item.retries > 0 for item in results)
    reflection_cases = sum(item.reflections > 0 for item in results)
    recovery_results = [
        item for item in results if item.recovery_eligible and item.reflections > 0
    ]
    latencies = sorted(item.latency_ms for item in results)

    return EvaluationMetrics(
        total_cases=total,
        passed_cases=passed,
        case_pass_rate=_divide(passed, total),
        task_success_eligible_cases=len(normal_results),
        successful_tasks=successful_tasks,
        task_success_rate=_divide(successful_tasks, len(normal_results)),
        tool_selection_accuracy=_divide(
            sum(item.tool_selection_correct for item in results),
            total,
        ),
        tool_argument_accuracy=_divide(
            sum(check.passed for check in argument_checks),
            len(argument_checks),
        ),
        avg_tool_calls=_average([item.tool_calls for item in results]),
        avg_execution_attempts=_average(
            [item.execution_attempts for item in results]
        ),
        avg_latency_ms=_average(latencies),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        retry_case_count=retry_cases,
        retry_rate=_divide(retry_cases, total),
        total_retries=sum(item.retries for item in results),
        avg_retries_per_case=_average([item.retries for item in results]),
        reflection_case_count=reflection_cases,
        reflection_rate=_divide(reflection_cases, total),
        avg_reflection_count=_average([item.reflections for item in results]),
        recovery_eligible_cases=len(recovery_results),
        recovered_cases=sum(item.recovered for item in recovery_results),
        recovery_rate=_divide(
            sum(item.recovered for item in recovery_results),
            len(recovery_results),
        ),
        timeout_count=sum(item.timeout_count for item in results),
        fallback_count=sum(item.fallback_count for item in results),
        max_retries_exceeded_count=sum(
            item.max_retries_exceeded_count for item in results
        ),
        max_tool_calls_exceeded_count=sum(
            item.max_tool_calls_exceeded_count for item in results
        ),
    )


def calculate_category_metrics(
    results: list[EvaluationCaseResult],
) -> dict[EvaluationCategory, CategoryMetrics]:
    """按四个固定分类计算 Case Pass Rate。"""

    output = {}
    for category in EvaluationCategory:
        category_results = [item for item in results if item.category is category]
        passed = sum(item.passed for item in category_results)
        output[category] = CategoryMetrics(
            total_cases=len(category_results),
            passed_cases=passed,
            pass_rate=_divide(passed, len(category_results)),
        )
    return output


def _divide(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def _average(values: list[int | float]) -> float:
    return 0.0 if not values else round(sum(values) / len(values), 3)


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(percentile * len(sorted_values)) - 1)
    return round(sorted_values[index], 3)
