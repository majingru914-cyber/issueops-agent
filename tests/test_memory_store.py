"""SQLiteTaskStore 的 Schema、序列化、恢复与隔离测试。"""

import sqlite3
from pathlib import Path

import pytest

from agent.schemas import (
    Evidence,
    PlanStep,
    ReflectionResult,
    ReplanRecord,
    ReviewResult,
    ToolResultRecord,
)
from memory import (
    PersistenceError,
    SQLiteTaskStore,
    StoreClosedError,
    TaskStatus,
)
from tools.base import ToolResult


def test_store_initializes_idempotent_schema(tmp_path: Path) -> None:
    """首次打开自动建库，重复 initialize 不得破坏 Schema。"""

    database_path = tmp_path / "memory.db"
    with SQLiteTaskStore(database_path) as store:
        store.initialize()
        store.initialize()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {"tasks", "state_snapshots", "execution_traces"}.issubset(tables)


def test_store_saves_loads_history_and_trace_in_order(tmp_path: Path) -> None:
    """任务摘要、完整状态历史和 trace 必须可稳定排序读取。"""

    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        store.create_task("task-1", "检查仓库")
        store.save_task(
            "task-1",
            {"user_query": "检查仓库", "task_id": "task-1"},
            TaskStatus.RUNNING,
        )
        store.save_state("task-1", "created", {"round": 0})
        store.save_state("task-1", "planned", {"round": 1, "plan": []})
        store.save_trace("task-1", "plan", {"steps": []})
        store.save_trace("task-1", "review", {"passed": True})
        store.save_task(
            "task-1",
            {
                "task_type": "repository_analysis",
                "goal": "检查仓库",
                "final_answer": "完成",
                "review_passed": True,
                "reflection_count": 1,
                "retry_count": 2,
                "tool_call_count": 3,
            },
            TaskStatus.COMPLETED,
        )

        task = store.load_task("task-1")
        history = store.list_state_history("task-1")
        trace = store.list_trace("task-1")

    assert task is not None
    assert task.metadata.status is TaskStatus.COMPLETED
    assert task.metadata.final_answer == "完成"
    assert task.metadata.reflection_count == 1
    assert task.metadata.retry_count == 2
    assert task.latest_state == {"plan": [], "round": 1}
    assert [item.sequence for item in history] == [1, 2]
    assert [item.stage for item in history] == ["created", "planned"]
    assert [item.sequence for item in trace] == [1, 2]
    assert [item.event_type for item in trace] == ["plan", "review"]


def test_store_reopens_and_keeps_tasks_isolated(tmp_path: Path) -> None:
    """进程式重开后数据仍存在，不同 task_id 不得串数据。"""

    database_path = tmp_path / "memory.db"
    with SQLiteTaskStore(database_path) as store:
        for task_id in ("task-a", "task-b"):
            store.create_task(task_id, f"请求 {task_id}")
            store.save_state(task_id, "created", {"task_id": task_id})
            store.save_trace(task_id, "marker", {"task_id": task_id})

    with SQLiteTaskStore(database_path) as reopened:
        task_a = reopened.load_task("task-a")
        task_b = reopened.load_task("task-b")
        trace_a = reopened.list_trace("task-a")
        trace_b = reopened.list_trace("task-b")

    assert task_a is not None and task_b is not None
    assert task_a.latest_state == {"task_id": "task-a"}
    assert task_b.latest_state == {"task_id": "task-b"}
    assert trace_a[0].payload == {"task_id": "task-a"}
    assert trace_b[0].payload == {"task_id": "task-b"}


def test_store_redacts_secrets_and_rejects_unknown_objects(tmp_path: Path) -> None:
    """敏感字段和常见 Token 不能原样进入 SQLite。"""

    database_path = tmp_path / "memory.db"
    with SQLiteTaskStore(database_path) as store:
        store.create_task("secret-task", "Bearer query-visible-token")
        store.save_state(
            "secret-task",
            "created",
            {
                "api_token": "plain-secret-value",
                "headers": {"Authorization": "Bearer visible-token"},
                "text": "ghp_123456789012345678901234567890",
            },
        )
        store.save_task(
            "secret-task",
            {
                "final_answer": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            },
            TaskStatus.PARTIAL,
        )
        with pytest.raises(PersistenceError, match="serialize_json"):
            store.save_state("secret-task", "invalid", {"value": object()})

    raw_database = database_path.read_bytes()
    assert b"plain-secret-value" not in raw_database
    assert b"visible-token" not in raw_database
    assert b"query-visible-token" not in raw_database
    assert b"ghp_123456789012345678901234567890" not in raw_database
    assert b"ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in raw_database


def test_agent_models_round_trip_as_json(tmp_path: Path) -> None:
    """核心 Agent model 经 SQLite 往返后应保留主要语义字段。"""

    step = PlanStep(
        id=1,
        goal="读取 README",
        tool_name="read_file",
        tool_args={"path": "README.md"},
    )
    tool_result = ToolResultRecord(
        step_id=1,
        result=ToolResult(
            success=True,
            tool_name="read_file",
            data={"content": "示例"},
        ),
    )
    evidence = Evidence(
        step_id=1,
        source="read_file",
        summary="读取成功",
        raw_result={"content": "示例"},
    )
    review = ReviewResult(
        round=1,
        passed=False,
        score=0.5,
        criterion_scores={"evidence": 0.5},
        issues=["证据不足"],
        missing_evidence=["实现内容"],
        reason="需要补证。",
        recommended_action="继续读取。",
    )
    reflection = ReflectionResult(
        round=1,
        failure_reason="证据不足",
        missing_information=["实现内容"],
        missing_evidence=["文件内容"],
        plan_problems=["只定位未读取"],
        proposed_actions=["读取文件"],
    )
    replan = ReplanRecord(
        round=1,
        reason="补充读取",
        previous_plan=[step],
        added_steps=[step.model_copy(update={"id": 2})],
        resulting_plan=[step, step.model_copy(update={"id": 2})],
    )
    state = {
        "plan": [step],
        "tool_results": [tool_result],
        "evidence": [evidence],
        "review": review,
        "reflection": reflection,
        "replan_records": [replan],
    }

    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        store.create_task("round-trip", "测试 JSON 往返")
        store.save_state("round-trip", "replanned", state)
        loaded = store.load_latest_state("round-trip")

    assert loaded is not None
    assert loaded["plan"][0]["tool_name"] == "read_file"
    assert loaded["tool_results"][0]["result"]["success"] is True
    assert loaded["evidence"][0]["summary"] == "读取成功"
    assert loaded["review"]["passed"] is False
    assert loaded["reflection"]["round"] == 1
    assert loaded["replan_records"][0]["added_steps"][0]["id"] == 2


def test_store_reports_corrupted_json_and_closed_usage(tmp_path: Path) -> None:
    """损坏 JSON 与关闭后访问都必须显式失败。"""

    database_path = tmp_path / "memory.db"
    store = SQLiteTaskStore(database_path)
    store.create_task("task-1", "检查损坏状态")
    store.save_state("task-1", "created", {"ok": True})
    store.close()

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE state_snapshots SET state_json = ? WHERE task_id = ?",
            ("{broken-json", "task-1"),
        )
        connection.commit()

    with SQLiteTaskStore(database_path) as reopened:
        with pytest.raises(PersistenceError, match="deserialize_state_json"):
            reopened.load_latest_state("task-1")

    with pytest.raises(StoreClosedError):
        store.load_task("task-1")


def test_missing_task_returns_none_and_foreign_key_is_enforced(tmp_path: Path) -> None:
    """未知任务返回 None，孤立状态不得写入。"""

    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        assert store.load_task("missing") is None
        with pytest.raises(PersistenceError):
            store.save_state("missing", "created", {"task_id": "missing"})
