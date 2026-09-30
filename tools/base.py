"""Tool System 的统一基础契约。"""

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tools.reliability import ErrorCode


class ToolAttemptRecord(BaseModel):
    """一次实际 Tool execution attempt 的可观察记录。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    attempt: int = Field(gt=0)
    task_id: str = Field(min_length=1)
    step_id: int = Field(ge=0)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]
    phase: Literal["initial", "retry", "fallback", "fallback_retry"]
    success: bool
    error_code: ErrorCode | None = None
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_attempt_state(self) -> "ToolAttemptRecord":
        """Attempt 的 success 与 error_code 必须一致。"""

        if self.success and self.error_code is not None:
            raise ValueError("成功 Attempt 不能包含错误码。")
        if not self.success and self.error_code is None:
            raise ValueError("失败 Attempt 必须包含错误码。")
        return self


class ToolResult(BaseModel):
    """所有正式 Tool 调用使用的统一结果。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    success: bool
    tool_name: str = Field(min_length=1)
    data: Any | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    retryable: bool = False
    latency_ms: float | None = Field(default=None, ge=0)
    attempts: list[ToolAttemptRecord] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    fallback_from: str | None = None
    last_error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "ToolResult":
        """保证成功结果和失败结果不会携带矛盾字段。"""

        if self.success:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("成功结果不能包含错误信息。")
            if self.retryable:
                raise ValueError("成功结果不能标记为 retryable。")
            if self.last_error_code is not None:
                raise ValueError("成功结果不能包含 last_error_code。")
        else:
            if not self.error_code or not self.error_message:
                raise ValueError("失败结果必须包含错误码和错误信息。")
            if self.data is not None:
                raise ValueError("失败结果不能包含数据。")
        if self.retry_count > max(0, len(self.attempts) - 1):
            raise ValueError("retry_count 不能超过可观察的额外 Attempt 数。")
        return self


class BaseTool(ABC):
    """所有具体 Tool 必须实现的最小接口。"""

    name: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[type[BaseModel]]

    def invoke(self, raw_args: dict[str, Any]) -> ToolResult:
        """验证原始参数、执行 Tool，并统一转换结果或异常。"""

        started_at = perf_counter()
        try:
            args = self.args_schema.model_validate(raw_args)
        except ValidationError as error:
            fields = ", ".join(
                ".".join(str(part) for part in item["loc"])
                for item in error.errors()
            )
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code=ErrorCode.INVALID_ARGUMENT,
                error_message=f"工具参数验证失败：{fields or '参数格式错误'}。",
                retryable=False,
                latency_ms=_elapsed_ms(started_at),
            )

        try:
            data = self.run(args)
        except Exception as error:
            error_code, error_message, retryable = self._map_execution_error(error)
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code=error_code,
                error_message=error_message,
                retryable=retryable,
                latency_ms=_elapsed_ms(started_at),
            )

        return ToolResult(
            success=True,
            tool_name=self.name,
            data=data,
            latency_ms=_elapsed_ms(started_at),
        )

    @abstractmethod
    def run(self, args: BaseModel) -> Any:
        """使用经过 Pydantic 验证的参数执行具体逻辑。"""

    def _map_execution_error(
        self,
        error: Exception,
    ) -> tuple[ErrorCode, str, bool]:
        """将执行异常映射为稳定错误码，子类可以按领域扩展。"""

        if isinstance(error, FileNotFoundError):
            return ErrorCode.FILE_NOT_FOUND, f"文件或路径不存在：{error}", False
        if isinstance(error, TimeoutError):
            return ErrorCode.TIMEOUT, f"工具执行超时：{error}", True
        return ErrorCode.EXECUTION_FAILED, f"工具执行失败：{error}", False


def _elapsed_ms(started_at: float) -> float:
    """计算非负的毫秒级执行时长。"""

    return max(0.0, (perf_counter() - started_at) * 1000)
