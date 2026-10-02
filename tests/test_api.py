"""Stage 09 FastAPI、异步执行、隔离和持久化测试。"""

from collections.abc import Callable
from pathlib import Path
import threading
import time
from typing import Any

from fastapi.testclient import TestClient

from api.main import create_app
from memory import SQLiteTaskStore, TaskStatus
from tools.runtime import ToolRuntime, build_tool_runtime


TERMINAL_STATUSES = {"completed", "partial", "failed"}
MAX_POLLS = 100
POLL_INTERVAL_SECONDS = 0.02


def test_post_runs_existing_agent_and_exposes_task_and_trace(tmp_path: Path) -> None:
    """真实 Agent Runner 必须复用同一 task_id 并生成可查询结果与 trace。"""

    workspace = tmp_path / "repo"
    (workspace / "agent").mkdir(parents=True)
    (workspace / "agent" / "state.py").write_text(
        "from typing import TypedDict\nclass AgentState(TypedDict):\n    pass\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "api.db"
    runtime = build_tool_runtime(workspace)
    app = create_app(
        database_path=database_path,
        workspace_root=workspace,
        tool_runtime=runtime,
        runtime_close=lambda: _close_runtime(runtime),
    )

    with TestClient(app) as client:
        created = client.post(
            "/tasks",
            json={"query": "  查找项目中 AgentState 的定义  "},
        )
        assert created.status_code == 202
        body = created.json()
        assert body["status"] == "running"
        task_id = body["task_id"]

        task = _poll_task(client, task_id)
        assert task["status"] == "completed"
        assert task["query"] == "查找项目中 AgentState 的定义"
        assert task["final_answer"]
        assert task["review_passed"] is True
        assert task["tool_call_count"] >= 1

        trace_response = client.get("/trace", params={"task_id": task_id})
        assert trace_response.status_code == 200
        trace = trace_response.json()
        assert trace["task_id"] == task_id
        sequences = [event["sequence"] for event in trace["events"]]
        assert sequences == sorted(sequences)
        event_types = {event["event_type"] for event in trace["events"]}
        assert {
            "task_started",
            "plan",
            "tool_call",
            "tool_result",
            "review",
            "final",
            "task_finished",
        }.issubset(event_types)

    with SQLiteTaskStore(database_path) as store:
        persisted = store.load_task(task_id)
    assert persisted is not None
    assert persisted.metadata.task_id == task_id
    assert persisted.latest_state is not None
    assert persisted.latest_state["task_id"] == task_id


def test_post_returns_while_slow_runner_is_still_running(tmp_path: Path) -> None:
    """POST 不得等待慢同步 Runner 完成，且 Event Loop 仍可响应查询。"""

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_runner(
        query: str,
        _runtime: ToolRuntime,
        *,
        store: SQLiteTaskStore,
        task_id: str,
        task_precreated: bool,
    ) -> dict[str, Any]:
        assert task_precreated is True
        started.set()
        assert release.wait(timeout=3)
        state = _complete_injected_task(store, task_id, query)
        finished.set()
        return state

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "slow.db",
        tool_runtime=runtime,
        runner=slow_runner,
        runtime_close=lambda: _close_runtime(runtime),
    )

    with TestClient(app) as client:
        response = client.post("/tasks", json={"query": "慢任务"})
        assert response.status_code == 202
        assert started.wait(timeout=1)
        assert finished.is_set() is False
        task_id = response.json()["task_id"]

        running = client.get(f"/tasks/{task_id}")
        assert running.status_code == 200
        assert running.json()["status"] == "running"
        assert running.json()["final_answer"] is None

        status = client.get("/status")
        assert status.status_code == 200
        assert status.json()["active_tasks"] == 1

        release.set()
        completed = _poll_task(client, task_id)
        assert completed["status"] == "completed"
        assert finished.is_set() is True


def test_concurrent_tasks_keep_state_and_trace_isolated(tmp_path: Path) -> None:
    """两个同步 Runner 经线程卸载后可并行，且记录不得串 task_id 或 query。"""

    barrier = threading.Barrier(2, timeout=3)

    def concurrent_runner(
        query: str,
        _runtime: ToolRuntime,
        *,
        store: SQLiteTaskStore,
        task_id: str,
        task_precreated: bool,
    ) -> dict[str, Any]:
        assert task_precreated is True
        barrier.wait()
        return _complete_injected_task(store, task_id, query)

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "concurrent.db",
        tool_runtime=runtime,
        runner=concurrent_runner,
        runtime_close=lambda: _close_runtime(runtime),
    )

    with TestClient(app) as client:
        first = client.post("/tasks", json={"query": "Task A"}).json()
        second = client.post("/tasks", json={"query": "Task B"}).json()
        assert first["task_id"] != second["task_id"]

        first_task = _poll_task(client, first["task_id"])
        second_task = _poll_task(client, second["task_id"])
        assert first_task["query"] == "Task A"
        assert first_task["final_answer"] == "完成：Task A"
        assert second_task["query"] == "Task B"
        assert second_task["final_answer"] == "完成：Task B"

        first_trace = client.get(
            "/trace", params={"task_id": first["task_id"]}
        ).json()
        second_trace = client.get(
            "/trace", params={"task_id": second["task_id"]}
        ).json()
        assert {event["payload"]["query"] for event in first_trace["events"]} == {
            "Task A"
        }
        assert {event["payload"]["query"] for event in second_trace["events"]} == {
            "Task B"
        }


def test_completed_task_survives_application_restart(tmp_path: Path) -> None:
    """App A 关闭后，App B 必须能从同一 SQLite 查询已完成任务。"""

    database_path = tmp_path / "restart.db"
    runner = _successful_runner()
    first_runtime = build_tool_runtime(tmp_path)
    first_app = create_app(
        database_path=database_path,
        tool_runtime=first_runtime,
        runner=runner,
        runtime_close=lambda: _close_runtime(first_runtime),
    )
    with TestClient(first_app) as client:
        task_id = client.post("/tasks", json={"query": "持久化任务"}).json()[
            "task_id"
        ]
        expected = _poll_task(client, task_id)

    second_runtime = build_tool_runtime(tmp_path)
    second_app = create_app(
        database_path=database_path,
        tool_runtime=second_runtime,
        runtime_close=lambda: _close_runtime(second_runtime),
    )
    with TestClient(second_app) as client:
        restored = client.get(f"/tasks/{task_id}")
        trace = client.get("/trace", params={"task_id": task_id})

    assert restored.status_code == 200
    assert restored.json() == expected
    assert trace.status_code == 200
    assert trace.json()["events"]


def test_background_exception_becomes_failed_without_leaking_message(
    tmp_path: Path,
) -> None:
    """未捕获 Runner 异常必须被消费、持久化，并只公开安全摘要。"""

    def crashing_runner(
        _query: str,
        _runtime: ToolRuntime,
        *,
        store: SQLiteTaskStore,
        task_id: str,
        task_precreated: bool,
    ) -> dict[str, Any]:
        assert store.load_task(task_id) is not None
        assert task_precreated is True
        raise RuntimeError("C:\\private\\GITHUB_TOKEN=secret")

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "failure.db",
        tool_runtime=runtime,
        runner=crashing_runner,
        runtime_close=lambda: _close_runtime(runtime),
    )

    with TestClient(app) as client:
        task_id = client.post("/tasks", json={"query": "异常任务"}).json()[
            "task_id"
        ]
        task = _poll_task(client, task_id)
        trace = client.get("/trace", params={"task_id": task_id})

    assert task["status"] == "failed"
    assert task["final_answer"] is None
    serialized = trace.text
    assert trace.status_code == 200
    assert trace.json()["events"][-1]["event_type"] == "task_failed"
    assert trace.json()["events"][-1]["payload"] == {"error_type": "RuntimeError"}
    assert "private" not in serialized
    assert "secret" not in serialized


def test_status_reports_persisted_terminal_counts(tmp_path: Path) -> None:
    """服务状态应组合进程内 active 数与 SQLite 终态统计。"""

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "status.db",
        tool_runtime=runtime,
        runner=_successful_runner(),
        runtime_close=lambda: _close_runtime(runtime),
    )
    with TestClient(app) as client:
        initial = client.get("/status")
        assert initial.status_code == 200
        assert initial.json() == {
            "status": "ok",
            "service": "issueops-agent",
            "active_tasks": 0,
            "completed_tasks": 0,
            "partial_tasks": 0,
            "failed_tasks": 0,
            "total_tasks": 0,
        }
        task_id = client.post("/tasks", json={"query": "统计任务"}).json()[
            "task_id"
        ]
        _poll_task(client, task_id)
        final = client.get("/status").json()

    assert final["active_tasks"] == 0
    assert final["completed_tasks"] == 1
    assert final["total_tasks"] == 1


def test_invalid_requests_have_stable_error_contract(tmp_path: Path) -> None:
    """空白、缺失和未知字段均返回稳定 INVALID_REQUEST。"""

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "invalid.db",
        tool_runtime=runtime,
        runtime_close=lambda: _close_runtime(runtime),
    )
    with TestClient(app) as client:
        responses = [
            client.post("/tasks", json={"query": ""}),
            client.post("/tasks", json={"query": "   "}),
            client.post("/tasks", json={}),
            client.post("/tasks", json={"query": "有效", "plan": []}),
        ]

    for response in responses:
        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "code": "INVALID_REQUEST",
                "message": "请求参数无效。",
            }
        }


def test_missing_task_and_trace_return_stable_404(tmp_path: Path) -> None:
    """不存在任务与不存在任务的 trace 不得混淆为空 trace。"""

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "missing.db",
        tool_runtime=runtime,
        runtime_close=lambda: _close_runtime(runtime),
    )
    with TestClient(app) as client:
        task_response = client.get("/tasks/unknown")
        trace_response = client.get("/trace", params={"task_id": "unknown"})

    for response in (task_response, trace_response):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_unexpected_endpoint_error_returns_safe_internal_error(
    tmp_path: Path,
) -> None:
    """HTTP 边界不得向 Client 暴露未知异常消息或 stack trace。"""

    runtime = build_tool_runtime(tmp_path)
    app = create_app(
        database_path=tmp_path / "internal.db",
        tool_runtime=runtime,
        runtime_close=lambda: _close_runtime(runtime),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        def crash_status() -> None:
            raise RuntimeError("C:\\private\\Authorization=secret")

        app.state.agent_service.get_status = crash_status
        response = client.get("/status")

    assert response.status_code == 500
    assert response.json() == {
        "detail": {
            "code": "INTERNAL_ERROR",
            "message": "服务暂时无法完成请求。",
        }
    }
    assert "private" not in response.text
    assert "secret" not in response.text


def _successful_runner() -> Callable[..., dict[str, Any]]:
    def runner(
        query: str,
        _runtime: ToolRuntime,
        *,
        store: SQLiteTaskStore,
        task_id: str,
        task_precreated: bool,
    ) -> dict[str, Any]:
        assert task_precreated is True
        return _complete_injected_task(store, task_id, query)

    return runner


def _complete_injected_task(
    store: SQLiteTaskStore,
    task_id: str,
    query: str,
) -> dict[str, Any]:
    state = {
        "user_query": query,
        "task_id": task_id,
        "final_answer": f"完成：{query}",
        "review_passed": True,
        "reflection_count": 0,
        "retry_count": 0,
        "tool_call_count": 1,
    }
    store.save_state(task_id, "finalized", state)
    store.save_trace(task_id, "task_finished", {"query": query})
    store.save_task(task_id, state, TaskStatus.COMPLETED)
    return state


def _poll_task(client: TestClient, task_id: str) -> dict[str, Any]:
    for _attempt in range(MAX_POLLS):
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["status"] in TERMINAL_STATUSES:
            return task
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"任务未在有限轮询内结束：{task_id}")


def _close_runtime(runtime: ToolRuntime) -> None:
    runtime.registry.get("get_github_issue").client.close()
