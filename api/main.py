"""IssueOps Agent FastAPI application 与 application factory。"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent.runner import run_agent
from api.schemas import (
    ErrorResponse,
    HealthResponse,
    ServiceStatusResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskResponse,
    TraceResponse,
)
from api.service import AgentRunner, AgentService
from memory import PersistenceError
from tools.github_client import GitHubClient
from tools.runtime import ToolRuntime, build_tool_runtime


LOGGER = logging.getLogger("issueops.api")
DEFAULT_DATABASE_PATH = Path("data/issueops.db")


def create_app(
    *,
    database_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    tool_runtime: ToolRuntime | None = None,
    runner: AgentRunner | None = None,
    runtime_close: Callable[[], None] | None = None,
) -> FastAPI:
    """创建可注入临时 SQLite、Runtime 和 Runner 的 FastAPI application。"""

    resolved_database_path = Path(
        database_path
        or os.environ.get("ISSUEOPS_DB_PATH", DEFAULT_DATABASE_PATH)
    )
    resolved_workspace_root = Path(workspace_root or Path.cwd()).resolve()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_runtime = tool_runtime
        active_close = runtime_close
        if active_runtime is None:
            github_client = GitHubClient(token=os.getenv("GITHUB_TOKEN"))
            active_runtime = build_tool_runtime(
                resolved_workspace_root,
                github_client=github_client,
            )
            active_close = github_client.close
        service = AgentService(
            resolved_database_path,
            active_runtime,
            runner=runner or run_agent,
            runtime_close=active_close,
        )
        service.initialize()
        application.state.agent_service = service
        try:
            yield
        finally:
            await service.shutdown()

    application = FastAPI(
        title="IssueOps Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request_handler(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "INVALID_REQUEST",
                    "message": "请求参数无效。",
                }
            },
        )

    @application.exception_handler(PersistenceError)
    async def persistence_error_handler(
        _request: Request,
        error: PersistenceError,
    ) -> JSONResponse:
        LOGGER.error(
            "event=api_internal_error error_type=%s",
            type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务暂时无法完成请求。",
                }
            },
        )

    @application.exception_handler(Exception)
    async def internal_error_handler(
        _request: Request,
        error: Exception,
    ) -> JSONResponse:
        LOGGER.error(
            "event=api_internal_error error_type=%s",
            type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务暂时无法完成请求。",
                }
            },
        )

    @application.post(
        "/tasks",
        response_model=TaskCreateResponse,
        status_code=202,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def create_task(payload: TaskCreateRequest) -> TaskCreateResponse:
        return await _service(application).submit(payload.query)

    @application.get(
        "/tasks/{task_id}",
        response_model=TaskResponse,
        responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def get_task(task_id: str) -> TaskResponse:
        task = _service(application).get_task(task_id)
        if task is None:
            raise _not_found(task_id)
        return task

    @application.get(
        "/trace",
        response_model=TraceResponse,
        responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def get_trace(task_id: str) -> TraceResponse:
        trace = _service(application).get_trace(task_id)
        if trace is None:
            raise _not_found(task_id)
        return trace

    @application.get(
        "/health",
        response_model=HealthResponse,
    )
    async def get_health() -> HealthResponse:
        """返回不触发 Agent、GitHub 或复杂数据库查询的部署健康状态。"""

        return HealthResponse(status="healthy", service="issueops-agent")

    @application.get(
        "/status",
        response_model=ServiceStatusResponse,
        responses={500: {"model": ErrorResponse}},
    )
    async def get_status() -> ServiceStatusResponse:
        return _service(application).get_status()

    return application


def _service(application: FastAPI) -> AgentService:
    return application.state.agent_service


def _not_found(task_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "TASK_NOT_FOUND",
            "message": f"任务不存在：{task_id}",
        },
    )


app = create_app()
