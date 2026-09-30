"""Tool System 的统一基础契约。"""

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ToolResult(BaseModel):
    """所有正式 Tool 调用使用的统一结果。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    tool_name: str = Field(min_length=1)
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_result_state(self) -> "ToolResult":
        """保证成功结果和失败结果不会携带矛盾字段。"""

        if self.success:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("成功结果不能包含错误信息。")
        else:
            if not self.error_code or not self.error_message:
                raise ValueError("失败结果必须包含错误码和错误信息。")
            if self.data is not None:
                raise ValueError("失败结果不能包含数据。")
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
                error_code="INVALID_ARGUMENT",
                error_message=f"工具参数验证失败：{fields or '参数格式错误'}。",
                latency_ms=_elapsed_ms(started_at),
            )

        try:
            data = self.run(args)
        except Exception as error:
            error_code, error_message = self._map_execution_error(error)
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code=error_code,
                error_message=error_message,
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

    def _map_execution_error(self, error: Exception) -> tuple[str, str]:
        """将执行异常映射为稳定错误码，子类可以按领域扩展。"""

        return "EXECUTION_FAILED", f"工具执行失败：{error}"


def _elapsed_ms(started_at: float) -> float:
    """计算非负的毫秒级执行时长。"""

    return max(0.0, (perf_counter() - started_at) * 1000)
