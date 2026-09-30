"""基于标准库 sqlite3 的任务、状态与 trace 持久化。"""

from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any

from pydantic import BaseModel

from memory.schemas import (
    PersistedTask,
    StateSnapshot,
    TaskMetadata,
    TaskStatus,
    TraceEvent,
)


LOGGER = logging.getLogger("issueops.memory")
REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+")
_GITHUB_TOKEN_PATTERN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")


class PersistenceError(RuntimeError):
    """SQLite 或 JSON 边界失败的稳定领域异常。"""


class StoreClosedError(PersistenceError):
    """关闭后继续使用 Store 时抛出。"""


class SQLiteTaskStore:
    """管理单个 SQLite 文件中的 Persistent Memory。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._connection: sqlite3.Connection | None = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                self.database_path,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self.initialize()
        except PersistenceError:
            self.close()
            raise
        except (OSError, sqlite3.Error) as error:
            self.close()
            self._connection = None
            self._raise("open", error)

    def __enter__(self) -> "SQLiteTaskStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def initialize(self) -> None:
        """幂等创建任务、状态快照和执行 trace 三张表。"""

        connection = self._require_connection()
        schema = """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            user_query TEXT NOT NULL,
            task_type TEXT,
            goal TEXT,
            status TEXT NOT NULL CHECK (
                status IN ('created', 'running', 'completed', 'failed', 'partial')
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            final_answer TEXT,
            review_passed INTEGER,
            reflection_count INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            tool_call_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS state_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            stage TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, sequence),
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS execution_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            step_id INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, sequence),
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_state_snapshots_task_sequence
            ON state_snapshots(task_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_execution_traces_task_sequence
            ON execution_traces(task_id, sequence);
        """
        try:
            with connection:
                connection.executescript(schema)
        except sqlite3.Error as error:
            self._raise("initialize", error)

    def create_task(self, task_id: str, user_query: str) -> TaskMetadata:
        """创建处于 created 状态的任务。"""

        now = _utc_now()
        connection = self._require_connection()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, user_query, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        _redact_string(user_query),
                        TaskStatus.CREATED.value,
                        now,
                        now,
                    ),
                )
        except sqlite3.Error as error:
            self._raise("create_task", error, task_id)
        task = self.load_task(task_id)
        if task is None:
            raise PersistenceError("任务创建后无法读取。")
        return task.metadata

    def update_task(
        self,
        task_id: str,
        state: dict[str, Any],
        status: TaskStatus,
    ) -> TaskMetadata:
        """由权威 AgentState 更新任务摘要和生命周期状态。"""

        connection = self._require_connection()
        now = _utc_now()
        review_passed = state.get("review_passed")
        review_value = None if review_passed is None else int(bool(review_passed))
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE tasks
                    SET task_type = ?, goal = ?, status = ?, updated_at = ?,
                        final_answer = ?, review_passed = ?,
                        reflection_count = ?, retry_count = ?, tool_call_count = ?
                    WHERE task_id = ?
                    """,
                    (
                        _redact_optional_text(state.get("task_type")),
                        _redact_optional_text(state.get("goal")),
                        status.value,
                        now,
                        _redact_optional_text(state.get("final_answer")),
                        review_value,
                        int(state.get("reflection_count", 0)),
                        int(state.get("retry_count", 0)),
                        int(state.get("tool_call_count", 0)),
                        task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(f"任务不存在：{task_id}")
        except PersistenceError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as error:
            self._raise("update_task", error, task_id)
        task = self.load_task(task_id)
        if task is None:
            raise PersistenceError("任务更新后无法读取。")
        return task.metadata

    def save_task(
        self,
        task_id: str,
        state: dict[str, Any],
        status: TaskStatus,
    ) -> TaskMetadata:
        """保存现有任务的可查询摘要；任务创建仍由 create_task 负责。"""

        return self.update_task(task_id, state, status)

    def save_state(
        self,
        task_id: str,
        stage: str,
        state: dict[str, Any],
    ) -> StateSnapshot:
        """追加完整、脱敏且 JSON-safe 的 AgentState 快照。"""

        state_json = _dump_json(state)
        now = _utc_now()
        connection = self._require_connection()
        try:
            with connection:
                sequence = self._next_sequence(
                    connection,
                    "state_snapshots",
                    task_id,
                )
                connection.execute(
                    """
                    INSERT INTO state_snapshots (
                        task_id, sequence, stage, state_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, sequence, stage, state_json, now),
                )
        except (sqlite3.Error, TypeError, ValueError) as error:
            self._raise("save_state", error, task_id)
        return StateSnapshot(
            task_id=task_id,
            sequence=sequence,
            stage=stage,
            state=_load_json_object(state_json, "state_json"),
            created_at=now,
        )

    def load_latest_state(self, task_id: str) -> dict[str, Any] | None:
        """读取任务最近一次状态；无快照时返回 None。"""

        connection = self._require_connection()
        try:
            row = connection.execute(
                """
                SELECT state_json FROM state_snapshots
                WHERE task_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        except sqlite3.Error as error:
            self._raise("load_latest_state", error, task_id)
        if row is None:
            return None
        return _load_json_object(row["state_json"], "state_json")

    def list_state_history(self, task_id: str) -> list[StateSnapshot]:
        """按稳定 sequence 返回任务全部状态历史。"""

        connection = self._require_connection()
        try:
            rows = connection.execute(
                """
                SELECT task_id, sequence, stage, state_json, created_at
                FROM state_snapshots
                WHERE task_id = ? ORDER BY sequence ASC
                """,
                (task_id,),
            ).fetchall()
        except sqlite3.Error as error:
            self._raise("list_state_history", error, task_id)
        return [
            StateSnapshot(
                task_id=row["task_id"],
                sequence=row["sequence"],
                stage=row["stage"],
                state=_load_json_object(row["state_json"], "state_json"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_trace(
        self,
        task_id: str,
        event_type: str,
        payload: dict[str, Any],
        step_id: int | None = None,
    ) -> TraceEvent:
        """追加一条脱敏、可排序的执行事件。"""

        payload_json = _dump_json(payload)
        now = _utc_now()
        connection = self._require_connection()
        try:
            with connection:
                sequence = self._next_sequence(
                    connection,
                    "execution_traces",
                    task_id,
                )
                connection.execute(
                    """
                    INSERT INTO execution_traces (
                        task_id, sequence, event_type, step_id,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, sequence, event_type, step_id, payload_json, now),
                )
        except (sqlite3.Error, TypeError, ValueError) as error:
            self._raise("save_trace", error, task_id)
        return TraceEvent(
            task_id=task_id,
            sequence=sequence,
            event_type=event_type,
            step_id=step_id,
            payload=_load_json_object(payload_json, "payload_json"),
            created_at=now,
        )

    def list_trace(self, task_id: str) -> list[TraceEvent]:
        """按稳定 sequence 返回任务全部执行 trace。"""

        connection = self._require_connection()
        try:
            rows = connection.execute(
                """
                SELECT task_id, sequence, event_type, step_id,
                       payload_json, created_at
                FROM execution_traces
                WHERE task_id = ? ORDER BY sequence ASC
                """,
                (task_id,),
            ).fetchall()
        except sqlite3.Error as error:
            self._raise("list_trace", error, task_id)
        return [
            TraceEvent(
                task_id=row["task_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                step_id=row["step_id"],
                payload=_load_json_object(row["payload_json"], "payload_json"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def load_task(self, task_id: str) -> PersistedTask | None:
        """读取任务摘要与最近状态，不存在时返回 None。"""

        connection = self._require_connection()
        try:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        except sqlite3.Error as error:
            self._raise("load_task", error, task_id)
        if row is None:
            return None
        metadata = TaskMetadata(
            task_id=row["task_id"],
            user_query=row["user_query"],
            task_type=row["task_type"],
            goal=row["goal"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            final_answer=row["final_answer"],
            review_passed=(
                None if row["review_passed"] is None else bool(row["review_passed"])
            ),
            reflection_count=row["reflection_count"],
            retry_count=row["retry_count"],
            tool_call_count=row["tool_call_count"],
        )
        return PersistedTask(
            metadata=metadata,
            latest_state=self.load_latest_state(task_id),
        )

    def close(self) -> None:
        """幂等关闭数据库连接。"""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise StoreClosedError("SQLiteTaskStore 已关闭。")
        return self._connection

    @staticmethod
    def _next_sequence(
        connection: sqlite3.Connection,
        table_name: str,
        task_id: str,
    ) -> int:
        if table_name not in {"state_snapshots", "execution_traces"}:
            raise ValueError("不支持的 sequence 表。")
        row = connection.execute(
            f"SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            f"FROM {table_name} WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["next_sequence"])

    @staticmethod
    def _raise(operation: str, error: Exception, task_id: str = "-") -> None:
        LOGGER.error(
            "event=persistence_error operation=%s task_id=%s error_type=%s",
            operation,
            task_id,
            type(error).__name__,
        )
        raise PersistenceError(f"持久化操作失败：{operation}。") from error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _dump_json(value: Any) -> str:
    """在拒绝未知对象前先转换并脱敏。"""

    try:
        safe_value = _to_json_safe(value)
        return json.dumps(
            safe_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        SQLiteTaskStore._raise("serialize_json", error)


def _to_json_safe(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, BaseModel):
        return _to_json_safe(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _to_json_safe(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(item_key): _to_json_safe(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_json_safe(item) for item in value]
    raise TypeError(f"对象无法安全序列化为 JSON：{type(value).__name__}")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    value = _BEARER_PATTERN.sub(r"\1[REDACTED]", value)
    return _GITHUB_TOKEN_PATTERN.sub(REDACTED, value)


def _redact_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("任务文本字段必须是 str 或 None。")
    return _redact_string(value)


def _load_json_object(raw_value: str, column: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as error:
        SQLiteTaskStore._raise(f"deserialize_{column}", error)
    if not isinstance(value, dict):
        SQLiteTaskStore._raise(
            f"deserialize_{column}",
            TypeError("持久化 JSON 顶层必须是 object。"),
        )
    return value
