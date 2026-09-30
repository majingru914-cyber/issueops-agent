"""SQLite Persistent Memory 的结构化数据模型。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    """持久化任务的有限生命周期状态。"""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class TaskMetadata(BaseModel):
    """可查询的任务摘要，不替代完整 AgentState。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    user_query: str = Field(min_length=1)
    task_type: str | None = None
    goal: str | None = None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    final_answer: str | None = None
    review_passed: bool | None = None
    reflection_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)


class StateSnapshot(BaseModel):
    """一个按任务和序号排列的 AgentState JSON 快照。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    stage: str = Field(min_length=1)
    state: dict[str, Any]
    created_at: datetime


class TraceEvent(BaseModel):
    """执行、Review、Reflection 与 Re-plan 的统一 trace 事件。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    event_type: str = Field(min_length=1)
    step_id: int | None = Field(default=None, ge=0)
    payload: dict[str, Any]
    created_at: datetime


class PersistedTask(BaseModel):
    """任务元数据与最近 AgentState 的组合查询结果。"""

    model_config = ConfigDict(extra="forbid")

    metadata: TaskMetadata
    latest_state: dict[str, Any] | None = None
