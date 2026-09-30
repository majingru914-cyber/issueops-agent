"""ToolRuntime 使用的统一可靠性策略与错误分类。"""

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from tools.base import ToolResult


DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_HARD_LIMIT = 5
DEFAULT_TOOL_TIMEOUT_SECONDS = 10.0
MAX_TOOL_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_TOOL_CALLS = 20
MAX_TOOL_CALLS_HARD_LIMIT = 1_000


class ErrorCode(StrEnum):
    """所有 Tool failure 共用的稳定错误码。"""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    GITHUB_AUTH_ERROR = "GITHUB_AUTH_ERROR"
    GITHUB_NOT_FOUND = "GITHUB_NOT_FOUND"
    GITHUB_API_ERROR = "GITHUB_API_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"
    MAX_TOOL_CALLS_EXCEEDED = "MAX_TOOL_CALLS_EXCEEDED"


class ReliabilityPolicy(BaseModel):
    """限制 Retry、Timeout、Fallback 和 Agent Tool 总预算。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES,
        ge=0,
        le=MAX_RETRIES_HARD_LIMIT,
    )
    timeout_seconds: float = Field(
        default=DEFAULT_TOOL_TIMEOUT_SECONDS,
        gt=0,
        le=MAX_TOOL_TIMEOUT_SECONDS,
    )
    max_tool_calls: int = Field(
        default=DEFAULT_MAX_TOOL_CALLS,
        ge=1,
        le=MAX_TOOL_CALLS_HARD_LIMIT,
    )
    fallbacks: dict[str, str] = Field(default_factory=dict)
    fallback_error_codes: frozenset[ErrorCode] = Field(
        default_factory=lambda: frozenset(
            {ErrorCode.TOOL_NOT_FOUND, ErrorCode.EXECUTION_FAILED}
        )
    )

    @field_validator("fallbacks")
    @classmethod
    def validate_fallback_names(cls, value: dict[str, str]) -> dict[str, str]:
        """Fallback name 必须明确且不能包含空白名称。"""

        for original, fallback in value.items():
            if not original.strip() or not fallback.strip():
                raise ValueError("Fallback Tool name 不能为空。")
        return value

    @model_validator(mode="after")
    def validate_fallback_cycles(self) -> "ReliabilityPolicy":
        """拒绝直接自循环；Runtime 本身也只执行一级 Fallback。"""

        for original, fallback in self.fallbacks.items():
            if original == fallback:
                raise ValueError("Fallback Tool 不能指向自身。")
        return self

    def fallback_for(self, tool_name: str, result: "ToolResult") -> str | None:
        """按显式 Tool 映射和错误码决定是否使用一级 Fallback。"""

        if result.success or result.error_code is None:
            return None
        if ErrorCode(result.error_code) not in self.fallback_error_codes:
            return None
        return self.fallbacks.get(tool_name)


def is_retryable(result: "ToolResult") -> bool:
    """只依赖 ToolResult.retryable 判断是否允许同步骤重试。"""

    return not result.success and result.retryable
