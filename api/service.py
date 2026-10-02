"""异步 HTTP 服务与同步 Agent Runner 之间的薄服务层。"""

import asyncio
from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from agent.runner import run_agent
from memory import PersistenceError, SQLiteTaskStore, TaskStatus
from tools.runtime import ToolRuntime

from api.schemas import (
    ServiceStatusResponse,
    TaskCreateResponse,
    TaskResponse,
    TraceEventResponse,
    TraceResponse,
)


LOGGER = logging.getLogger("issueops.api")
SERVICE_NAME = "issueops-agent"


class AgentRunner(Protocol):
    """Service 调用现有同步 Runner 所需的最小契约。"""

    def __call__(
        self,
        user_query: str,
        tool_runtime: ToolRuntime,
        *,
        store: SQLiteTaskStore,
        task_id: str,
        task_precreated: bool,
    ) -> dict[str, Any]:
        """运行一个使用既有 task_id 的持久化 Agent 任务。"""


class AgentService:
    """协调任务受理、线程卸载、持久化查询和进程内任务引用。"""

    def __init__(
        self,
        database_path: str | Path,
        tool_runtime: ToolRuntime,
        *,
        runner: AgentRunner = run_agent,
        runtime_close: Callable[[], None] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.tool_runtime = tool_runtime
        self.runner = runner
        self.runtime_close = runtime_close
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def initialize(self) -> None:
        """在 application startup 显式初始化 SQLite Schema。"""

        with self._open_store():
            pass

    async def submit(self, query: str) -> TaskCreateResponse:
        """先持久化任务，再调度后台 coroutine 并立即返回。"""

        if self._closed:
            raise RuntimeError("AgentService 已关闭。")
        task_id = uuid4().hex
        initial_state = {"user_query": query, "task_id": task_id}
        with self._open_store() as store:
            metadata = store.create_task(task_id, query)
            metadata = store.save_task(task_id, initial_state, TaskStatus.RUNNING)

        background_task = asyncio.create_task(
            self._execute(task_id, query),
            name=f"issueops-task-{task_id}",
        )
        self._tasks[task_id] = background_task
        LOGGER.info("event=api_task_submitted task_id=%s", task_id)
        return TaskCreateResponse(
            task_id=task_id,
            status=metadata.status,
            created_at=metadata.created_at,
        )

    def get_task(self, task_id: str) -> TaskResponse | None:
        """从 SQLite 读取过滤后的任务摘要，不等待后台执行。"""

        with self._open_store() as store:
            task = store.load_task(task_id)
        if task is None:
            return None
        metadata = task.metadata
        return TaskResponse(
            task_id=metadata.task_id,
            query=metadata.user_query,
            status=metadata.status,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            final_answer=metadata.final_answer,
            review_passed=metadata.review_passed,
            reflection_count=metadata.reflection_count,
            retry_count=metadata.retry_count,
            tool_call_count=metadata.tool_call_count,
        )

    def get_trace(self, task_id: str) -> TraceResponse | None:
        """从 SQLite 读取任务及其按 sequence 排列的 trace。"""

        with self._open_store() as store:
            if store.load_task(task_id) is None:
                return None
            events = store.list_trace(task_id)
        return TraceResponse(
            task_id=task_id,
            events=[
                TraceEventResponse(
                    sequence=event.sequence,
                    event_type=event.event_type,
                    step_id=event.step_id,
                    payload=event.payload,
                    created_at=event.created_at,
                )
                for event in events
            ],
        )

    def get_status(self) -> ServiceStatusResponse:
        """组合进程内 active 数与 SQLite 终态统计。"""

        with self._open_store() as store:
            counts = store.count_tasks_by_status()
        return ServiceStatusResponse(
            status="ok",
            service=SERVICE_NAME,
            active_tasks=len(self._tasks),
            completed_tasks=counts.get(TaskStatus.COMPLETED, 0),
            partial_tasks=counts.get(TaskStatus.PARTIAL, 0),
            failed_tasks=counts.get(TaskStatus.FAILED, 0),
            total_tasks=sum(counts.values()),
        )

    async def shutdown(self) -> None:
        """等待已受理任务收尾并释放共享 Runtime 资源。"""

        self._closed = True
        pending = list(self._tasks.values())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self.runtime_close is not None:
            self.runtime_close()

    async def _execute(self, task_id: str, query: str) -> None:
        """在线程池运行同步 Agent，并消费所有后台异常。"""

        try:
            await asyncio.to_thread(self._run_sync, task_id, query)
            LOGGER.info("event=api_task_finished task_id=%s", task_id)
        except Exception as error:  # 防御性 background task 边界
            LOGGER.error(
                "event=api_task_failed task_id=%s error_type=%s",
                task_id,
                type(error).__name__,
            )
            self._persist_unhandled_failure(task_id, query, error)
        finally:
            self._tasks.pop(task_id, None)

    def _run_sync(self, task_id: str, query: str) -> None:
        """为当前 worker thread 创建独立 SQLite connection。"""

        with self._open_store() as store:
            self.runner(
                query,
                self.tool_runtime,
                store=store,
                task_id=task_id,
                task_precreated=True,
            )

    def _persist_unhandled_failure(
        self,
        task_id: str,
        query: str,
        error: Exception,
    ) -> None:
        """确保注入 Runner 或 Runner 外层异常也形成安全 failed 终态。"""

        try:
            with self._open_store() as store:
                task = store.load_task(task_id)
                if task is None or task.metadata.status is TaskStatus.FAILED:
                    return
                failed_state = task.latest_state or {
                    "user_query": query,
                    "task_id": task_id,
                }
                store.save_task(task_id, failed_state, TaskStatus.FAILED)
                store.save_trace(
                    task_id,
                    "task_failed",
                    {"error_type": type(error).__name__},
                )
        except PersistenceError as persistence_error:
            LOGGER.error(
                "event=api_failure_persistence_failed task_id=%s error_type=%s",
                task_id,
                type(persistence_error).__name__,
            )

    def _open_store(self) -> SQLiteTaskStore:
        return SQLiteTaskStore(self.database_path)
