"""生成机器可读 JSON、中文 Markdown 与 failure cases 文档。"""

import json
from pathlib import Path

from eval.schemas import EvaluationDataset, EvaluationReport


def write_reports(
    report: EvaluationReport,
    dataset: EvaluationDataset,
    reports_directory: Path,
    failure_document_path: Path,
) -> tuple[Path, Path]:
    """覆盖最新代表性报告，并同步 failure cases 文档。"""

    reports_directory.mkdir(parents=True, exist_ok=True)
    json_path = reports_directory / "evaluation-report.json"
    markdown_path = reports_directory / "evaluation-report.md"
    json_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    failure_document_path.parent.mkdir(parents=True, exist_ok=True)
    failure_document_path.write_text(
        _render_failure_cases(report, dataset),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _render_markdown(report: EvaluationReport) -> str:
    metrics = report.metrics
    failed = [item for item in report.case_results if not item.passed]
    lines = [
        "# IssueOps Agent 评测报告",
        "",
        "## 摘要",
        "",
        f"- 数据集版本：`{report.dataset_version}`",
        f"- 执行时间：`{report.timestamp}`",
        f"- Python：`{report.python_version}`",
        f"- 执行用例：`{metrics.total_cases}`",
        f"- 通过用例：`{metrics.passed_cases}`",
        "",
        "正确性指标由固定数据集和结构化 `AgentState` 决定；延迟属于运行时性能指标，允许不同运行间波动。",
        "",
        "## 基准评测组成",
        "",
        "| 分类 | 用例数 | 通过数 | 通过率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, value in report.category_results.items():
        lines.append(
            f"| `{category.value}` | {value.total_cases} | {value.passed_cases} | "
            f"{_percent(value.pass_rate)} |"
        )
    lines.extend(
        [
            "",
            "## 指标",
            "",
            "| 指标 | 数值 |",
            "| --- | ---: |",
            f"| 用例通过率 | {_percent(metrics.case_pass_rate)} |",
            f"| 任务成功率 | {_percent(metrics.task_success_rate)} |",
            f"| 工具选择准确率 | {_percent(metrics.tool_selection_accuracy)} |",
            f"| 工具参数准确率 | {_percent(metrics.tool_argument_accuracy)} |",
            f"| 平均 logical Tool 调用数 | {metrics.avg_tool_calls:.3f} |",
            f"| 平均执行尝试数 | {metrics.avg_execution_attempts:.3f} |",
            f"| 平均延迟 | {metrics.avg_latency_ms:.3f} ms |",
            f"| P50 延迟 | {metrics.p50_latency_ms:.3f} ms |",
            f"| P95 延迟 | {metrics.p95_latency_ms:.3f} ms |",
            f"| Retry 发生率 | {_percent(metrics.retry_rate)} |",
            f"| Reflection 发生率 | {_percent(metrics.reflection_rate)} |",
            f"| Recovery 成功率 | {_percent(metrics.recovery_rate)} |",
            "",
            "## 分类结果",
            "",
            "每类结果均按行为是否符合用例期望计算，预期失败路径不会提高任务成功率。",
            "",
            "## 失败用例",
            "",
        ]
    )
    if failed:
        for item in failed:
            lines.extend(
                [
                    f"### `{item.case_id}`",
                    "",
                    f"- 分类：`{item.category.value}`",
                    f"- 预期状态：`{item.expected_status.value}`",
                    f"- 实际状态：`{item.task_status.value}`",
                    "- 失败分类："
                    + ", ".join(f"`{value.value}`" for value in item.failure_categories),
                    "- 原因：" + "；".join(item.failure_reasons),
                    "",
                ]
            )
    else:
        lines.extend(["本轮基准评测未观察到失败用例。", ""])
    lines.extend(
        [
            "## 可靠性结果",
            "",
            f"- 发生 Retry 的用例：`{metrics.retry_case_count}`",
            f"- Retry 总数：`{metrics.total_retries}`",
            f"- Timeout 总数：`{metrics.timeout_count}`",
            f"- Fallback 总数：`{metrics.fallback_count}`",
            f"- MAX_RETRIES_EXCEEDED：`{metrics.max_retries_exceeded_count}`",
            f"- MAX_TOOL_CALLS_EXCEEDED：`{metrics.max_tool_calls_exceeded_count}`",
            "",
            "## Reflection 结果",
            "",
            f"- 发生 Reflection 的用例：`{metrics.reflection_case_count}`",
            f"- 平均 Reflection 次数：`{metrics.avg_reflection_count:.3f}`",
            f"- 可 Recovery 用例：`{metrics.recovery_eligible_cases}`",
            f"- Recovery 成功用例：`{metrics.recovered_cases}`",
            "",
            "## 局限",
            "",
            "- 数据集只有 20 个确定性 MVP 用例，不能代表开放世界软件研发任务。",
            "- Repository Fixture 规模很小，未覆盖大型 monorepo、编码差异和复杂构建系统。",
            "- GitHub 使用固定 Mock 响应，不包含真实网络抖动和完整 API 变化。",
            "- Planner 与 Reviewer 为规则实现，指标会受到数据集与规则耦合影响。",
            "- 延迟受本机负载影响，P95 在 20 个用例的样本下仅作为辅助信息。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_failure_cases(
    report: EvaluationReport,
    dataset: EvaluationDataset,
) -> str:
    case_by_id = {case.id: case for case in dataset.cases}
    failed = [item for item in report.case_results if not item.passed]
    lines = [
        "# Stage 08 失败用例",
        "",
        f"数据集版本：`{report.dataset_version}`",
        "",
    ]
    if not failed:
        lines.extend(
            [
                "本轮基准评测未观察到失败用例。",
                "",
                "这不表示 Agent 已覆盖所有软件研发任务；当前结论仅适用于固定的 20 个离线 MVP 用例。",
                "",
            ]
        )
        return "\n".join(lines)

    for result in failed:
        case = case_by_id[result.case_id]
        lines.extend(
            [
                f"## `{result.case_id}`",
                "",
                f"- 输入：{case.user_query}",
                f"- 预期：status={case.expected_status.value}, tools={case.expected_tools}",
                f"- 实际：status={result.task_status.value}, tools={result.actual_tools}",
                "- 失败分类："
                + ", ".join(item.value for item in result.failure_categories),
                "- 根因：" + "；".join(result.failure_reasons),
                "- 可能的改进：先扩充独立用例与诊断证据，再决定是否修改 Production Agent。",
                "",
            ]
        )
    return "\n".join(lines)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
