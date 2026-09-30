"""把 Graph 节点更新投影为状态快照和执行 trace。"""

from typing import Any, Protocol

from memory.sqlite_store import SQLiteTaskStore


class StateRecorder(Protocol):
    """Graph 依赖的最小持久化观察接口。"""

    def record_node(
        self,
        stage: str,
        state: dict[str, Any],
        update: dict[str, object],
    ) -> None:
        """保存节点更新后的状态和派生事件。"""


class TaskRecorder:
    """只观察节点输入输出，不参与 Agent 推理或路由。"""

    def __init__(self, store: SQLiteTaskStore, task_id: str) -> None:
        self.store = store
        self.task_id = task_id
        self.latest_state: dict[str, Any] | None = None

    def record_node(
        self,
        stage: str,
        state: dict[str, Any],
        update: dict[str, object],
    ) -> None:
        """合并节点更新用于只读观察，并保存结构化历史。"""

        snapshot = {**state, **update}
        snapshot["task_id"] = self.task_id
        self.store.save_state(self.task_id, stage, snapshot)
        self.latest_state = snapshot
        self._record_events(stage, state, snapshot)

    def _record_events(
        self,
        stage: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        if stage == "analyzed":
            self._save("analysis", {
                "task_type": after.get("task_type"),
                "goal": after.get("goal"),
                "required_capabilities": after.get("required_capabilities", []),
            })
        elif stage == "planned":
            self._save("plan", {"steps": after.get("plan", [])})
        elif stage == "executed":
            self._record_execution_events(before, after)
        elif stage in {"evidence_collected", "budget_exceeded"}:
            for item in _new_items(before, after, "evidence"):
                self._save("evidence", item, item.get("step_id"))
            for item in _new_items(before, after, "errors"):
                event_type = (
                    "budget_exceeded"
                    if item.get("error_code") == "MAX_TOOL_CALLS_EXCEEDED"
                    else "error"
                )
                self._save(event_type, item, item.get("step_id"))
        elif stage == "drafted":
            self._save("draft", {"draft_answer": after.get("draft_answer", "")})
        elif stage == "reviewed" and after.get("review"):
            self._save("review", _as_dict(after["review"]))
        elif stage == "reflected" and after.get("reflection"):
            self._save("reflection", _as_dict(after["reflection"]))
        elif stage == "replanned":
            records = _new_items(before, after, "replan_records")
            for item in records:
                self._save("replan", item)
        elif stage == "finalized":
            self._save(
                "final",
                {
                    "final_answer": after.get("final_answer", ""),
                    "review_passed": after.get("review_passed", False),
                },
            )

    def _record_execution_events(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        for item in _new_items(before, after, "tool_calls"):
            self._save("tool_call", item, item.get("step_id"))
        for item in _new_items(before, after, "execution_attempts"):
            step_id = item.get("step_id")
            self._save("tool_attempt", item, step_id)
            phase = item.get("phase")
            if phase in {"retry", "fallback_retry"}:
                self._save("retry", item, step_id)
            if phase in {"fallback", "fallback_retry"}:
                self._save("fallback", item, step_id)
        for item in _new_items(before, after, "tool_results"):
            self._save("tool_result", item, item.get("step_id"))

    def _save(
        self,
        event_type: str,
        payload: dict[str, Any],
        step_id: int | None = None,
    ) -> None:
        self.store.save_trace(
            self.task_id,
            event_type,
            payload,
            step_id=step_id,
        )


def _new_items(
    before: dict[str, Any],
    after: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    previous_length = len(before.get(key, []))
    raw_items = after.get(key, [])[previous_length:]
    return [_as_dict(item) for item in raw_items]


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"Trace payload 必须是 dict：{type(value).__name__}")
