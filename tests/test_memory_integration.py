"""Persistent Memory 与完整 Agent 闭环的集成测试。"""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from agent.reflection import ReflectionPolicy
from agent.runner import run_agent
from agent.schemas import ReviewResult
from memory import SQLiteTaskStore, TaskStatus
from tools.base import BaseTool
from tools.reliability import ReliabilityPolicy
from tools.runtime import ToolRuntime, build_default_registry, build_tool_runtime


class NoArgs(BaseModel):
    """可靠性集成测试的空参数。"""

    model_config = ConfigDict(extra="forbid")


class FlakyMemoryTool(BaseTool):
    """第一次超时、第二次成功的持久化测试 Tool。"""

    name: ClassVar[str] = "flaky_memory_tool"
    description: ClassVar[str] = "验证 Retry trace 持久化。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def __init__(self) -> None:
        self.call_count = 0

    def run(self, args: BaseModel) -> Any:
        self.call_count += 1
        if self.call_count == 1:
            raise TimeoutError("模拟临时超时")
        return {"status": "recovered"}


class PrimaryFailureTool(BaseTool):
    """触发确定性 Fallback 的主 Tool。"""

    name: ClassVar[str] = "primary_failure_tool"
    description: ClassVar[str] = "总是失败。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        raise RuntimeError("模拟主 Tool 失败")


class FallbackMemoryTool(BaseTool):
    """确定性成功的 Fallback Tool。"""

    name: ClassVar[str] = "fallback_memory_tool"
    description: ClassVar[str] = "返回 Fallback 证据。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        return {"status": "fallback-success"}


def _single_tool_planner(tool_name: str):
    def planner(state: dict) -> dict[str, object]:
        return {
            "plan": [
                {
                    "id": 1,
                    "goal": "执行持久化测试",
                    "tool_name": tool_name,
                    "tool_args": {},
                    "requires_tool": True,
                }
            ],
            "current_step": 0,
            "tool_calls": [],
            "tool_results": [],
            "execution_attempts": [],
            "tool_call_count": 0,
            "retry_count": 0,
            "evidence": [],
            "errors": [],
            "review_history": [],
            "reflection_count": 0,
            "reflection_history": [],
            "replan_count": 0,
            "replan_records": [],
        }

    return planner


def _search_only_planner(state: dict) -> dict[str, object]:
    return {
        "plan": [
            {
                "id": 1,
                "goal": "只定位 AgentState 定义",
                "tool_name": "search_code",
                "tool_args": {
                    "query": "AgentState",
                    "path": ".",
                    "file_pattern": "*.py",
                },
                "requires_tool": True,
            }
        ],
        "current_step": 0,
        "tool_calls": [],
        "tool_results": [],
        "execution_attempts": [],
        "tool_call_count": 0,
        "retry_count": 0,
        "evidence": [],
        "errors": [],
        "review_history": [],
        "reflection_count": 0,
        "reflection_history": [],
        "replan_count": 0,
        "replan_records": [],
    }


def test_complete_agent_run_survives_store_reopen(tmp_path: Path) -> None:
    """完整 Agent 运行的最终状态、状态历史和 trace 必须可重启恢复。"""

    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("# 示例仓库\n", encoding="utf-8")
    database_path = tmp_path / "memory.db"
    runtime = build_tool_runtime(workspace)
    with SQLiteTaskStore(database_path) as store:
        result = run_agent(
            "分析项目结构",
            runtime,
            store=store,
            task_id="complete-task",
        )
    _close_runtime(runtime)

    with SQLiteTaskStore(database_path) as reopened:
        task = reopened.load_task("complete-task")
        stages = [
            item.stage for item in reopened.list_state_history("complete-task")
        ]
        event_types = [
            item.event_type for item in reopened.list_trace("complete-task")
        ]

    assert task is not None
    assert task.metadata.status is TaskStatus.COMPLETED
    assert task.latest_state == result
    assert stages[0] == "created"
    assert {"planned", "executed", "reviewed", "finalized"}.issubset(stages)
    assert {"tool_call", "tool_result", "review", "final"}.issubset(event_types)


def test_reflection_and_replan_are_persisted(tmp_path: Path) -> None:
    """Review Fail 后的 Reflection、Re-plan 和二次执行必须全部保留。"""

    workspace = tmp_path / "repo"
    agent_directory = workspace / "agent"
    agent_directory.mkdir(parents=True)
    (agent_directory / "state.py").write_text(
        "from typing import TypedDict\nclass AgentState(TypedDict):\n    pass\n",
        encoding="utf-8",
    )
    runtime = build_tool_runtime(workspace)
    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        result = run_agent(
            "定位 AgentState 定义并读取对应实现",
            runtime,
            store=store,
            task_id="reflection-task",
            planner_node=_search_only_planner,
        )
    _close_runtime(runtime)

    with SQLiteTaskStore(tmp_path / "memory.db") as reopened:
        trace = reopened.list_trace("reflection-task")
        stages = [
            item.stage for item in reopened.list_state_history("reflection-task")
        ]
        task = reopened.load_task("reflection-task")

    event_types = [item.event_type for item in trace]
    assert result["reflection_count"] == 1
    assert result["replan_count"] == 1
    assert task is not None
    assert task.metadata.reflection_count == 1
    assert task.metadata.status is TaskStatus.COMPLETED
    assert "reflected" in stages
    assert "replanned" in stages
    assert event_types.count("review") == 2
    assert "reflection" in event_types
    assert "replan" in event_types
    assert event_types.count("tool_call") == 2


def test_retry_attempts_and_success_are_persisted(tmp_path: Path) -> None:
    """一次失败、一次 Retry 和最终成功必须形成可查询 trace。"""

    registry = build_default_registry(tmp_path)
    flaky_tool = FlakyMemoryTool()
    registry.register(flaky_tool)
    runtime = ToolRuntime(registry, ReliabilityPolicy(max_retries=2))
    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        result = run_agent(
            "测试 Retry 持久化",
            runtime,
            store=store,
            task_id="retry-task",
            planner_node=_single_tool_planner(flaky_tool.name),
        )
    _close_runtime(runtime)

    with SQLiteTaskStore(tmp_path / "memory.db") as reopened:
        trace = reopened.list_trace("retry-task")

    attempts = [item for item in trace if item.event_type == "tool_attempt"]
    assert result["retry_count"] == 1
    assert [item.payload["success"] for item in attempts] == [False, True]
    assert len([item for item in trace if item.event_type == "retry"]) == 1
    assert any(item.event_type == "tool_result" for item in trace)


def test_fallback_attempt_is_persisted(tmp_path: Path) -> None:
    """主 Tool 失败后的 Fallback 必须具有独立 trace。"""

    registry = build_default_registry(tmp_path)
    primary = PrimaryFailureTool()
    fallback = FallbackMemoryTool()
    registry.register(primary)
    registry.register(fallback)
    runtime = ToolRuntime(
        registry,
        ReliabilityPolicy(
            max_retries=0,
            fallbacks={primary.name: fallback.name},
        ),
    )
    database_path = tmp_path / "memory.db"
    with SQLiteTaskStore(database_path) as store:
        result = run_agent(
            "测试 Fallback 持久化",
            runtime,
            store=store,
            task_id="fallback-task",
            planner_node=_single_tool_planner(primary.name),
        )
    _close_runtime(runtime)

    with SQLiteTaskStore(database_path) as reopened:
        trace = reopened.list_trace("fallback-task")

    fallback_events = [item for item in trace if item.event_type == "fallback"]
    assert result["tool_results"][0]["result"]["fallback_from"] == primary.name
    assert len(fallback_events) == 1
    assert fallback_events[0].payload["tool_name"] == fallback.name


def test_review_failure_finishes_as_partial(tmp_path: Path) -> None:
    """正常降级 Final 不应误标 failed，而应保存为 partial。"""

    def failing_reviewer(state: dict) -> dict[str, object]:
        review = ReviewResult(
            round=1,
            passed=False,
            score=0.1,
            criterion_scores={"goal_completion": 0.0},
            issues=["测试要求失败。"],
            missing_evidence=[],
            reason="测试要求失败。",
        )
        dumped = review.model_dump()
        return {
            "review": dumped,
            "review_score": review.score,
            "review_passed": False,
            "review_history": [dumped],
        }

    runtime = build_tool_runtime(tmp_path)
    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        result = run_agent(
            "分析项目结构",
            runtime,
            store=store,
            task_id="partial-task",
            reviewer_node=failing_reviewer,
            reflection_policy=ReflectionPolicy(max_reflections=0),
        )
        task = store.load_task("partial-task")
    _close_runtime(runtime)

    assert result["review_passed"] is False
    assert task is not None
    assert task.metadata.status is TaskStatus.PARTIAL


def test_persistence_does_not_change_agent_semantics(tmp_path: Path) -> None:
    """相同输入与 task_id 在启停持久化时应产生同等业务状态。"""

    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("# 示例仓库\n", encoding="utf-8")
    runtime_without_store = build_tool_runtime(workspace)
    without_store = run_agent(
        "分析项目结构",
        runtime_without_store,
        task_id="same-task",
    )
    _close_runtime(runtime_without_store)

    runtime_with_store = build_tool_runtime(workspace)
    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        with_store = run_agent(
            "分析项目结构",
            runtime_with_store,
            store=store,
            task_id="same-task",
        )
    _close_runtime(runtime_with_store)

    assert _without_latency(with_store) == _without_latency(without_store)


def test_runner_marks_unhandled_failure(tmp_path: Path) -> None:
    """Graph 未处理异常必须向上传播，同时任务状态变为 failed。"""

    def crashing_planner(state: dict) -> dict[str, object]:
        raise RuntimeError("模拟 Planner 崩溃")

    runtime = build_tool_runtime(tmp_path)
    with SQLiteTaskStore(tmp_path / "memory.db") as store:
        with pytest.raises(RuntimeError, match="模拟 Planner 崩溃"):
            run_agent(
                "测试失败状态",
                runtime,
                store=store,
                task_id="failed-task",
                planner_node=crashing_planner,
                reflection_policy=ReflectionPolicy(max_reflections=0),
            )
        task = store.load_task("failed-task")
        trace = store.list_trace("failed-task")
    _close_runtime(runtime)

    assert task is not None
    assert task.metadata.status is TaskStatus.FAILED
    assert trace[-1].event_type == "task_failed"
    assert trace[-1].payload["error_type"] == "RuntimeError"


def _without_latency(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_latency(item)
            for key, item in value.items()
            if key != "latency_ms"
        }
    if isinstance(value, list):
        return [_without_latency(item) for item in value]
    return value


def _close_runtime(runtime: ToolRuntime) -> None:
    runtime.registry.get("get_github_issue").client.close()
