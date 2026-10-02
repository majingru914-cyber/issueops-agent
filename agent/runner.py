"""Agent 单次运行与可选 Persistent Memory 生命周期协调。"""

import logging
from typing import Any
from uuid import uuid4

from agent.graph import AgentNode, build_agent_graph
from agent.reflection import ReflectionPolicy
from memory.recorder import TaskRecorder
from memory.schemas import TaskStatus
from memory.sqlite_store import PersistenceError, SQLiteTaskStore
from tools.runtime import ToolRuntime


LOGGER = logging.getLogger("issueops.agent")


def run_agent(
    user_query: str,
    tool_runtime: ToolRuntime,
    store: SQLiteTaskStore | None = None,
    task_id: str | None = None,
    planner_node: AgentNode | None = None,
    reviewer_node: AgentNode | None = None,
    reflection_node: AgentNode | None = None,
    replanner_node: AgentNode | None = None,
    reflection_policy: ReflectionPolicy | None = None,
    task_precreated: bool = False,
) -> dict[str, Any]:
    """运行一个 Agent 任务，并在启用时持久化完整生命周期。"""

    active_task_id = task_id or uuid4().hex
    initial_state: dict[str, Any] = {
        "user_query": user_query,
        "task_id": active_task_id,
    }
    recorder = TaskRecorder(store, active_task_id) if store is not None else None

    if task_precreated and store is None:
        raise ValueError("task_precreated=True 时必须提供 SQLiteTaskStore。")

    if store is not None:
        if task_precreated:
            if store.load_task(active_task_id) is None:
                raise PersistenceError("预创建任务不存在。")
        else:
            store.create_task(active_task_id, user_query)
        store.save_state(active_task_id, "created", initial_state)
        store.save_trace(
            active_task_id,
            "task_started",
            {"status": TaskStatus.RUNNING.value},
        )
        store.save_task(active_task_id, initial_state, TaskStatus.RUNNING)

    graph_kwargs: dict[str, object] = {
        "recorder": recorder,
        "reflection_policy": reflection_policy,
    }
    if planner_node is not None:
        graph_kwargs["planner_node"] = planner_node
    if reviewer_node is not None:
        graph_kwargs["reviewer_node"] = reviewer_node
    if reflection_node is not None:
        graph_kwargs["reflection_node"] = reflection_node
    if replanner_node is not None:
        graph_kwargs["replanner_node"] = replanner_node

    try:
        graph = build_agent_graph(tool_runtime, **graph_kwargs)
        final_state = dict(graph.invoke(initial_state))
        if store is not None:
            status = (
                TaskStatus.COMPLETED
                if final_state.get("review_passed") is True
                else TaskStatus.PARTIAL
            )
            store.save_task(active_task_id, final_state, status)
            store.save_trace(
                active_task_id,
                "task_finished",
                {"status": status.value},
            )
        return final_state
    except Exception as error:
        if store is not None:
            failed_state = recorder.latest_state if recorder else None
            failed_state = failed_state or initial_state
            try:
                store.save_task(active_task_id, failed_state, TaskStatus.FAILED)
                store.save_trace(
                    active_task_id,
                    "task_failed",
                    {"error_type": type(error).__name__},
                )
            except PersistenceError as persistence_error:
                LOGGER.error(
                    "event=persistence_status_update_failed task_id=%s "
                    "error_type=%s",
                    active_task_id,
                    type(persistence_error).__name__,
                )
        raise
