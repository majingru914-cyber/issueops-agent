"""Evaluation Dataset、Case Result、Metrics 与 Report Schema。"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationCategory(StrEnum):
    """Stage 08 四类 Benchmark Case。"""

    REPOSITORY = "repository"
    GITHUB = "github"
    RELIABILITY = "reliability"
    REFLECTION = "reflection"


class EvaluationScenario(StrEnum):
    """选择固定 Fixture 和注入配置，不携带任意 Python 逻辑。"""

    DEFAULT = "default"
    READ_README = "read_readme"
    MISSING_FILE = "missing_file"
    MISSING_SYMBOL = "missing_symbol"
    PATH_ESCAPE = "path_escape"
    GITHUB_ISSUE = "github_issue"
    GITHUB_PR = "github_pr"
    GITHUB_404 = "github_404"
    GITHUB_RATE_LIMIT = "github_rate_limit"
    RETRY_SUCCESS = "retry_success"
    RETRY_EXHAUSTED = "retry_exhausted"
    FALLBACK = "fallback"
    MAX_TOOL_CALLS = "max_tool_calls"
    FIRST_PASS = "first_pass"
    REFLECTION_RECOVERY = "reflection_recovery"
    REFLECTION_EXHAUSTED = "reflection_exhausted"
    REFLECTION_BUDGET = "reflection_budget"


class ExpectedTaskStatus(StrEnum):
    """Evaluator 从最终 AgentState 推导的任务状态。"""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ArgumentMatchMode(StrEnum):
    """Tool arguments 的结构化比较方式。"""

    EXACT = "exact"
    SUBSET = "subset"


class FailureCategory(StrEnum):
    """Evaluation 层失败分类，不复用 Tool ErrorCode。"""

    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    PLAN_ERROR = "PLAN_ERROR"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_ARGUMENT_ERROR = "TOOL_ARGUMENT_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    REVIEW_ERROR = "REVIEW_ERROR"
    REFLECTION_ERROR = "REFLECTION_ERROR"
    RELIABILITY_ERROR = "RELIABILITY_ERROR"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    UNEXPECTED_STATUS = "UNEXPECTED_STATUS"
    FINAL_ANSWER_ERROR = "FINAL_ANSWER_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"


class ToolArgumentExpectation(BaseModel):
    """一个 logical Tool Call 的期望参数。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    mode: ArgumentMatchMode = ArgumentMatchMode.SUBSET


class EvaluationCase(BaseModel):
    """一个具备明确成功条件的 Benchmark Case。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, pattern=r"^[a-z]+-[0-9]{3}$")
    category: EvaluationCategory
    description: str = Field(min_length=1)
    scenario: EvaluationScenario = EvaluationScenario.DEFAULT
    user_query: str = Field(min_length=1)
    expected_task_type: str | None = None
    expected_tools: list[str] = Field(default_factory=list)
    expected_tool_args: list[ToolArgumentExpectation] = Field(default_factory=list)
    required_evidence_sources: list[str] = Field(default_factory=list)
    expected_error_codes: list[str] = Field(default_factory=list)
    expected_status: ExpectedTaskStatus
    expected_review_passed: bool | None = None
    expected_reflection: bool | None = None
    expected_retry: bool | None = None
    expected_fallback: bool | None = None
    recovery_eligible: bool = False
    final_answer_contains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expectations(self) -> "EvaluationCase":
        """Tool sequence 与参数期望必须按 logical call 一一对应。"""

        if len(self.expected_tool_args) != len(self.expected_tools):
            raise ValueError("expected_tool_args 必须与 expected_tools 等长。")
        for tool_name, expectation in zip(
            self.expected_tools,
            self.expected_tool_args,
            strict=True,
        ):
            if tool_name != expectation.tool_name:
                raise ValueError("Tool 参数期望的 tool_name 必须与序列一致。")
        if self.recovery_eligible and self.expected_reflection is not True:
            raise ValueError("Recovery Case 必须期望发生 Reflection。")
        return self


class EvaluationDataset(BaseModel):
    """固定版本且严格包含 20 个 MVP Case 的 Dataset。"""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def validate_composition(self) -> "EvaluationDataset":
        """保证 ID 唯一及 8/4/4/4 分类组成。"""

        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("Evaluation Case id 必须唯一。")
        expected_counts = {
            EvaluationCategory.REPOSITORY: 8,
            EvaluationCategory.GITHUB: 4,
            EvaluationCategory.RELIABILITY: 4,
            EvaluationCategory.REFLECTION: 4,
        }
        actual_counts = {
            category: sum(case.category == category for case in self.cases)
            for category in expected_counts
        }
        if actual_counts != expected_counts:
            raise ValueError("Dataset 分类必须严格为 8/4/4/4。")
        return self


class ToolArgumentCheck(BaseModel):
    """一次 Tool 参数结构化评分结果。"""

    model_config = ConfigDict(extra="forbid")

    call_index: int = Field(ge=0)
    tool_name: str
    mode: ArgumentMatchMode
    expected: dict[str, Any]
    actual: dict[str, Any] | None
    passed: bool
    reason: str


class EvaluationCaseResult(BaseModel):
    """单 Case 的完整自动评分与 failure analysis 输入。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: EvaluationCategory
    description: str
    user_query: str
    passed: bool
    expected_status: ExpectedTaskStatus
    task_status: ExpectedTaskStatus
    expected_review_passed: bool | None = None
    review_passed: bool | None = None
    expected_tools: list[str]
    actual_tools: list[str]
    tool_selection_correct: bool
    tool_argument_checks: list[ToolArgumentCheck]
    tool_argument_accuracy: float = Field(ge=0.0, le=1.0)
    required_evidence_sources: list[str]
    actual_evidence_sources: list[str]
    expected_error_codes: list[str]
    actual_error_codes: list[str]
    tool_calls: int = Field(ge=0)
    execution_attempts: int = Field(ge=0)
    retries: int = Field(ge=0)
    reflections: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    max_retries_exceeded_count: int = Field(ge=0)
    max_tool_calls_exceeded_count: int = Field(ge=0)
    first_review_passed: bool | None = None
    recovery_eligible: bool = False
    recovered: bool = False
    latency_ms: float = Field(ge=0.0)
    final_answer_non_empty: bool
    failure_categories: list[FailureCategory] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    exception_summary: str | None = None


class CategoryMetrics(BaseModel):
    """单个分类的通过情况。"""

    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class EvaluationMetrics(BaseModel):
    """20 Case 聚合后的可量化指标。"""

    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    case_pass_rate: float = Field(ge=0.0, le=1.0)
    task_success_eligible_cases: int = Field(ge=0)
    successful_tasks: int = Field(ge=0)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    tool_argument_accuracy: float = Field(ge=0.0, le=1.0)
    avg_tool_calls: float = Field(ge=0.0)
    avg_execution_attempts: float = Field(ge=0.0)
    avg_latency_ms: float = Field(ge=0.0)
    p50_latency_ms: float = Field(ge=0.0)
    p95_latency_ms: float = Field(ge=0.0)
    retry_case_count: int = Field(ge=0)
    retry_rate: float = Field(ge=0.0, le=1.0)
    total_retries: int = Field(ge=0)
    avg_retries_per_case: float = Field(ge=0.0)
    reflection_case_count: int = Field(ge=0)
    reflection_rate: float = Field(ge=0.0, le=1.0)
    avg_reflection_count: float = Field(ge=0.0)
    recovery_eligible_cases: int = Field(ge=0)
    recovered_cases: int = Field(ge=0)
    recovery_rate: float = Field(ge=0.0, le=1.0)
    timeout_count: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    max_retries_exceeded_count: int = Field(ge=0)
    max_tool_calls_exceeded_count: int = Field(ge=0)


class EvaluationReport(BaseModel):
    """机器可读 Evaluation Report。"""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    dataset_version: str
    python_version: str
    metrics: EvaluationMetrics
    category_results: dict[EvaluationCategory, CategoryMetrics]
    case_results: list[EvaluationCaseResult]
