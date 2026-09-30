"""Dataset、Case Scoring、Evaluator 与 Report 测试。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import eval.evaluator as evaluator_module
from eval.evaluator import AgentEvaluator, load_dataset, main
from eval.reporting import write_reports
from eval.schemas import (
    ArgumentMatchMode,
    EvaluationCase,
    EvaluationCategory,
    ExpectedTaskStatus,
    FailureCategory,
)
from eval.scoring import arguments_match, score_case


def test_dataset_has_valid_versioned_8_4_4_4_composition() -> None:
    """真实 Dataset 必须严格包含 20 Case 与四类规定数量。"""

    dataset = load_dataset()
    counts = {
        category: sum(case.category is category for case in dataset.cases)
        for category in EvaluationCategory
    }

    assert dataset.version == "0.1.0"
    assert len(dataset.cases) == 20
    assert counts == {
        EvaluationCategory.REPOSITORY: 8,
        EvaluationCategory.GITHUB: 4,
        EvaluationCategory.RELIABILITY: 4,
        EvaluationCategory.REFLECTION: 4,
    }


def test_dataset_rejects_misaligned_tool_arguments() -> None:
    """Tool sequence 与参数期望数量不一致时 Schema 必须拒绝。"""

    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(
            {
                "id": "repo-999",
                "category": "repository",
                "description": "无效 Case",
                "user_query": "测试",
                "expected_tools": ["read_file"],
                "expected_tool_args": [],
                "expected_status": "completed",
            }
        )


@pytest.mark.parametrize(
    ("expected", "actual", "mode", "matched"),
    [
        ({"path": "a.py"}, {"path": "a.py"}, ArgumentMatchMode.EXACT, True),
        (
            {"path": "."},
            {"path": ".", "max_results": 20},
            ArgumentMatchMode.SUBSET,
            True,
        ),
        (
            {"nested": {"value": 1}},
            {"nested": {"value": 1, "extra": 2}},
            ArgumentMatchMode.SUBSET,
            True,
        ),
        ({"path": "a.py"}, {"path": "b.py"}, ArgumentMatchMode.EXACT, False),
        ({"path": "a.py"}, {}, ArgumentMatchMode.SUBSET, False),
    ],
)
def test_structured_argument_matching(
    expected: dict,
    actual: dict,
    mode: ArgumentMatchMode,
    matched: bool,
) -> None:
    """参数评分必须覆盖 exact、subset、incorrect 与 missing。"""

    assert arguments_match(expected, actual, mode) is matched


def test_tool_selection_uses_logical_calls_not_retry_attempts() -> None:
    """Retry attempt 不得被误计为新的 Planner Tool Selection。"""

    case = EvaluationCase.model_validate(
        {
            "id": "repo-999",
            "category": "repository",
            "description": "logical calls",
            "user_query": "测试",
            "expected_tools": ["search_code", "read_file"],
            "expected_tool_args": [
                {"tool_name": "search_code", "arguments": {}},
                {"tool_name": "read_file", "arguments": {}},
            ],
            "expected_status": "completed",
            "expected_review_passed": True,
            "expected_retry": True,
        }
    )
    state = {
        "tool_calls": [
            {"tool_name": "search_code", "arguments": {}},
            {"tool_name": "read_file", "arguments": {}},
        ],
        "execution_attempts": [
            {"tool_name": "search_code", "error_code": None},
            {"tool_name": "read_file", "error_code": "TIMEOUT"},
            {"tool_name": "read_file", "error_code": None},
        ],
        "retry_count": 1,
        "reflection_count": 0,
        "review_passed": True,
        "review_history": [{"passed": True}],
        "final_answer": "完成",
    }

    result = score_case(case, state, 1.0)

    assert result.tool_selection_correct is True
    assert result.actual_tools == ["search_code", "read_file"]
    assert result.execution_attempts == 3
    assert result.passed is True


def test_scoring_classifies_selection_argument_and_status_failures() -> None:
    """Case Fail 必须保存可用于分析的分类与原因。"""

    dataset = load_dataset()
    case = next(item for item in dataset.cases if item.id == "repo-008")
    state = {
        "task_type": "software_task",
        "tool_calls": [{"tool_name": "search_code", "arguments": {}}],
        "execution_attempts": [],
        "evidence": [],
        "errors": [],
        "review_passed": False,
        "review_history": [{"passed": False}],
        "reflection_count": 0,
        "retry_count": 0,
        "final_answer": "未完成",
    }

    result = score_case(case, state, 2.0)

    assert result.passed is False
    assert FailureCategory.TOOL_SELECTION_ERROR in result.failure_categories
    assert FailureCategory.TOOL_ARGUMENT_ERROR in result.failure_categories
    assert FailureCategory.EVIDENCE_ERROR in result.failure_categories
    assert FailureCategory.UNEXPECTED_STATUS in result.failure_categories


def test_single_case_evaluator_runs_existing_agent_offline() -> None:
    """单 Case 调试应调用现有 Agent 并返回结构化结果。"""

    report = AgentEvaluator(load_dataset()).run("github-001")

    assert report.metrics.total_cases == 1
    assert report.metrics.passed_cases == 1
    assert report.case_results[0].actual_tools == ["get_github_issue"]
    assert report.case_results[0].passed is True


def test_runtime_exception_isolated_and_next_cases_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一个 Case 的系统异常不得阻断剩余 Dataset。"""

    dataset = load_dataset()
    original_prepare = evaluator_module.prepare_case

    def prepare_with_one_failure(case: EvaluationCase):
        if case.id == "repo-001":
            raise RuntimeError("模拟 Evaluation Case 异常")
        return original_prepare(case)

    monkeypatch.setattr(evaluator_module, "prepare_case", prepare_with_one_failure)

    report = AgentEvaluator(dataset).run()

    assert len(report.case_results) == 20
    assert report.case_results[0].passed is False
    assert FailureCategory.RUNTIME_ERROR in report.case_results[0].failure_categories
    assert report.case_results[-1].case_id == "reflection-004"


def test_report_generation_writes_json_markdown_and_failure_document(
    tmp_path: Path,
) -> None:
    """报告生成器必须产出三类可审查文件。"""

    dataset = load_dataset()
    report = AgentEvaluator(dataset).run("repo-007")
    reports_directory = tmp_path / "reports"
    failure_path = tmp_path / "failure_cases.md"

    json_path, markdown_path = write_reports(
        report,
        dataset,
        reports_directory,
        failure_path,
    )
    raw_json = json.loads(json_path.read_text(encoding="utf-8"))

    assert raw_json["dataset_version"] == "0.1.0"
    assert raw_json["metrics"]["total_cases"] == 1
    assert "IssueOps Agent 评测报告" in markdown_path.read_text(encoding="utf-8")
    assert "repo-007" in failure_path.read_text(encoding="utf-8")


def test_cli_smoke_writes_reports(tmp_path: Path) -> None:
    """Evaluation CLI 单 Case smoke 必须返回 0 并生成报告。"""

    reports_directory = tmp_path / "reports"
    failure_path = tmp_path / "failure_cases.md"
    exit_code = main(
        [
            "--case",
            "repo-001",
            "--reports-dir",
            str(reports_directory),
            "--failure-doc",
            str(failure_path),
        ]
    )

    assert exit_code == 0
    assert (reports_directory / "evaluation-report.json").is_file()
    assert (reports_directory / "evaluation-report.md").is_file()
    assert failure_path.is_file()
