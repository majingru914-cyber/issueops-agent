"""Agent 分析、计划、执行与证据的结构化模型。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tools.base import ToolResult


class TaskAnalysis(BaseModel):
    """任务分析节点的结构化结果。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_type: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    required_capabilities: list[str] = Field(min_length=1)


class PlanStep(BaseModel):
    """Executor 可直接消费的单个计划步骤。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int = Field(gt=0)
    goal: str = Field(min_length=1)
    tool_name: str | None
    tool_args: dict[str, Any]
    requires_tool: bool = True

    @model_validator(mode="after")
    def validate_tool_contract(self) -> "PlanStep":
        """保证 Tool 需求、名称和参数保持一致。"""

        if self.requires_tool and not self.tool_name:
            raise ValueError("需要执行 Tool 的步骤必须提供 tool_name。")
        if not self.requires_tool and self.tool_name is not None:
            raise ValueError("不需要 Tool 的步骤不能提供 tool_name。")
        if not self.requires_tool and self.tool_args:
            raise ValueError("不需要 Tool 的步骤不能提供 tool_args。")
        return self


class TaskPlan(BaseModel):
    """规划节点的结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step_order(self) -> "TaskPlan":
        """要求步骤 ID 从 1 开始连续递增。"""

        expected_ids = list(range(1, len(self.steps) + 1))
        actual_ids = [step.id for step in self.steps]
        if actual_ids != expected_ids:
            raise ValueError("计划步骤 ID 必须从 1 开始连续递增。")
        return self


class ToolCallRecord(BaseModel):
    """一次由 Planner 决定、Executor 发起的 Tool 调用。"""

    model_config = ConfigDict(extra="forbid")

    step_id: int = Field(gt=0)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ToolResultRecord(BaseModel):
    """能够关联计划步骤的现有 ToolResult。"""

    model_config = ConfigDict(extra="forbid")

    step_id: int = Field(gt=0)
    result: ToolResult


class Evidence(BaseModel):
    """从成功 ToolResult 提取且可追踪的证据。"""

    model_config = ConfigDict(extra="forbid")

    step_id: int = Field(gt=0)
    source_type: str = "tool"
    source: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    raw_result: Any | None = None


class ExecutionError(BaseModel):
    """从失败 ToolResult 提取的执行错误。"""

    model_config = ConfigDict(extra="forbid")

    step_id: int = Field(gt=0)
    source: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    retryable: bool = False
    last_error_code: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
