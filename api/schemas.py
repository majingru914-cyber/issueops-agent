"""HTTP 边界使用的稳定 Request / Response Schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from memory import TaskStatus


MAX_QUERY_LENGTH = 10_000


class TaskCreateRequest(BaseModel):
    """创建 Agent 任务时允许的唯一外部输入。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """拒绝纯空白输入，并持久化去除首尾空白后的请求。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("query 不能为空。")
        return normalized


class TaskCreateResponse(BaseModel):
    """异步任务受理结果。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: TaskStatus
    created_at: datetime


class TaskResponse(BaseModel):
    """面向 Client 的过滤后任务摘要。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    query: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    final_answer: str | None = None
    review_passed: bool | None = None
    reflection_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)


class ServiceStatusResponse(BaseModel):
    """当前单进程 Agent Service 的可观察状态。"""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    active_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    partial_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)
    total_tasks: int = Field(ge=0)


class TraceEventResponse(BaseModel):
    """一条按 sequence 排序的持久化执行事件。"""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(gt=0)
    event_type: str
    step_id: int | None = None
    payload: dict[str, Any]
    created_at: datetime


class TraceResponse(BaseModel):
    """指定任务的完整持久化 trace。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    events: list[TraceEventResponse]


class ErrorDetail(BaseModel):
    """不泄漏内部异常的 HTTP 错误详情。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    """HTTP API 统一错误外壳。"""

    model_config = ConfigDict(extra="forbid")

    detail: ErrorDetail
