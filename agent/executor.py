"""按 Planner 权威计划调用现有 ToolRuntime。"""

import logging
from uuid import uuid4

from tools.base import ToolResult
from tools.reliability import ErrorCode
from tools.runtime import ToolRuntime

from agent.schemas import (
    ExecutionError,
    PlanStep,
    TaskPlan,
    ToolCallRecord,
    ToolResultRecord,
)
from agent.state import AgentState


LOGGER = logging.getLogger("issueops.agent")


def execute_step(state: AgentState, runtime: ToolRuntime) -> dict[str, object]:
    """执行当前逻辑步骤，并把 Runtime attempt trace 回写权威 State。"""

    plan = TaskPlan.model_validate({"steps": state.get("plan")})
    current_step = state.get("current_step", 0)
    if current_step >= len(plan.steps):
        return {}

    step: PlanStep = plan.steps[current_step]
    tool_name = step.tool_name or "no_tool"
    task_id = state.get("task_id") or uuid4().hex
    tool_call_count = state.get("tool_call_count", 0)
    remaining_attempts = max(0, runtime.policy.max_tool_calls - tool_call_count)
    tool_call = ToolCallRecord(
        step_id=step.id,
        tool_name=tool_name,
        arguments=step.tool_args,
    )

    if step.requires_tool and step.tool_name:
        result = runtime.execute(
            step.tool_name,
            step.tool_args,
            attempt_budget=remaining_attempts,
            task_id=task_id,
            step_id=step.id,
        )
    else:
        result = ToolResult(
            success=False,
            tool_name=tool_name,
            error_code=ErrorCode.EXECUTION_FAILED,
            error_message="计划步骤未提供可执行 Tool。",
            retryable=False,
        )

    result_record = ToolResultRecord(step_id=step.id, result=result)
    return {
        "task_id": task_id,
        "current_step": current_step + 1,
        "tool_call_count": tool_call_count + len(result.attempts),
        "retry_count": state.get("retry_count", 0) + result.retry_count,
        "execution_attempts": [
            *state.get("execution_attempts", []),
            *(item.model_dump() for item in result.attempts),
        ],
        "tool_calls": [
            *state.get("tool_calls", []),
            tool_call.model_dump(),
        ],
        "tool_results": [
            *state.get("tool_results", []),
            result_record.model_dump(),
        ],
    }


def record_tool_budget_exceeded(
    state: AgentState,
    max_tool_calls: int,
) -> dict[str, object]:
    """停止 Graph Tool loop，并为尚未执行的步骤记录预算错误。"""

    if any(
        item.get("error_code") == ErrorCode.MAX_TOOL_CALLS_EXCEEDED
        for item in state.get("errors", [])
    ):
        return {}

    current_step = state.get("current_step", 0)
    plan = state.get("plan", [])
    raw_step = plan[current_step] if current_step < len(plan) else {}
    step_id = raw_step.get("id", current_step + 1)
    source = raw_step.get("tool_name") or "tool_runtime"
    task_id = state.get("task_id", "unknown")
    LOGGER.error(
        "event=tool_budget_exceeded task_id=%s step_id=%s tool=%s "
        "max_tool_calls=%s",
        task_id,
        step_id,
        source,
        max_tool_calls,
    )
    error = ExecutionError(
        step_id=step_id,
        source=source,
        error_code=ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
        error_message=(
            f"Tool execution attempt 已达到上限 {max_tool_calls}，"
            "剩余计划步骤未执行。"
        ),
        retryable=False,
        attempt_count=0,
        retry_count=0,
    )
    return {"errors": [*state.get("errors", []), error.model_dump()]}
