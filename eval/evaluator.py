"""可重复运行的 IssueOps Agent Evaluation Benchmark CLI。"""

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import sys
from time import perf_counter

from pydantic import ValidationError

from agent.runner import run_agent
from eval.case_fixtures import CaseExecution, prepare_case
from eval.metrics import calculate_category_metrics, calculate_metrics
from eval.reporting import write_reports
from eval.schemas import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationReport,
)
from eval.scoring import score_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"
DEFAULT_REPORTS_DIRECTORY = Path(__file__).resolve().parent / "reports"
DEFAULT_FAILURE_DOCUMENT = PROJECT_ROOT / "docs" / "failure_cases.md"
LOGGER = logging.getLogger("issueops.evaluation")


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> EvaluationDataset:
    """加载并严格验证版本化 JSON Dataset。"""

    try:
        raw_value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法加载 Evaluation Dataset：{path}") from error
    return EvaluationDataset.model_validate(raw_value)


class AgentEvaluator:
    """逐 Case 调用现有 Agent，并在运行结束后评分。"""

    def __init__(self, dataset: EvaluationDataset) -> None:
        self.dataset = dataset

    def run(self, case_id: str | None = None) -> EvaluationReport:
        """运行完整 Dataset 或单个 Case；单 Case 异常不会中断后续运行。"""

        cases = self.dataset.cases
        if case_id is not None:
            cases = [case for case in cases if case.id == case_id]
            if not cases:
                raise ValueError(f"Evaluation Case 不存在：{case_id}")

        results = [self._run_case(case) for case in cases]
        return EvaluationReport(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            dataset_version=self.dataset.version,
            python_version=platform.python_version(),
            metrics=calculate_metrics(results),
            category_results=calculate_category_metrics(results),
            case_results=results,
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationCaseResult:
        execution: CaseExecution | None = None
        final_state: dict[str, object] = {}
        error: Exception | None = None
        started_at = perf_counter()
        try:
            execution = prepare_case(case)
            started_at = perf_counter()
            final_state = run_agent(
                case.user_query,
                execution.runtime,
                store=None,
                task_id=f"eval-{case.id}",
                **execution.runner_kwargs,
            )
        except Exception as caught_error:
            error = caught_error
            LOGGER.error(
                "event=evaluation_case_error case_id=%s error_type=%s",
                case.id,
                type(caught_error).__name__,
            )
        finally:
            latency_ms = max(0.0, (perf_counter() - started_at) * 1000)
            if execution is not None:
                execution.close()

        result = score_case(case, final_state, latency_ms, error)
        LOGGER.info(
            "event=evaluation_case_result case_id=%s category=%s passed=%s "
            "latency_ms=%.3f",
            case.id,
            case.category.value,
            str(result.passed).lower(),
            latency_ms,
        )
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 IssueOps Agent Evaluation。")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Evaluation Dataset JSON 路径。",
    )
    parser.add_argument("--case", help="只运行指定 Case ID。")
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIRECTORY,
        help="JSON 与 Markdown 报告输出目录。",
    )
    parser.add_argument(
        "--failure-doc",
        type=Path,
        default=DEFAULT_FAILURE_DOCUMENT,
        help="失败案例文档输出路径。",
    )
    return parser


def _display_path(path: Path) -> str:
    """将项目内文件显示为相对路径，外部文件保留完整路径。"""

    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        report = AgentEvaluator(dataset).run(args.case)
        json_path, markdown_path = write_reports(
            report,
            dataset,
            args.reports_dir,
            args.failure_doc,
        )
    except (OSError, ValueError, ValidationError) as error:
        print(f"Evaluation 失败：{error}", file=sys.stderr)
        return 1

    metrics = report.metrics
    print(
        json.dumps(
            {
                "dataset_version": report.dataset_version,
                "executed_cases": metrics.total_cases,
                "passed_cases": metrics.passed_cases,
                "case_pass_rate": metrics.case_pass_rate,
                "task_success_rate": metrics.task_success_rate,
                "tool_selection_accuracy": metrics.tool_selection_accuracy,
                "tool_argument_accuracy": metrics.tool_argument_accuracy,
                "avg_tool_calls": metrics.avg_tool_calls,
                "avg_latency_ms": metrics.avg_latency_ms,
                "retry_rate": metrics.retry_rate,
                "reflection_rate": metrics.reflection_rate,
                "recovery_rate": metrics.recovery_rate,
                "json_report": _display_path(json_path),
                "markdown_report": _display_path(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
