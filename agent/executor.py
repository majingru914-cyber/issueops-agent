"""按 Planner 权威计划调用现有 ToolRuntime。"""

from tools.base import ToolResult
from tools.runtime import ToolRuntime

from agent.schemas import PlanStep, TaskPlan, ToolCallRecord, ToolResultRecord
from agent.state import AgentState


def execute_step(state: AgentState, runtime: ToolRuntime) -> dict[str, object]:
    """执行当前步骤，记录 ToolCall、ToolResult 并推进游标。"""

    plan = TaskPlan.model_validate({"steps": state.get("plan")})
    current_step = state.get("current_step", 0)
    if current_step >= len(plan.steps):
        return {}

    step: PlanStep = plan.steps[current_step]
    tool_name = step.tool_name or "no_tool"
    tool_call = ToolCallRecord(
        step_id=step.id,
        tool_name=tool_name,
        arguments=step.tool_args,
    )

    if step.requires_tool and step.tool_name:
        result = runtime.execute(step.tool_name, step.tool_args)
    else:
        result = ToolResult(
            success=False,
            tool_name=tool_name,
            error_code="EXECUTION_FAILED",
            error_message="计划步骤未提供可执行 Tool。",
        )

    result_record = ToolResultRecord(step_id=step.id, result=result)
    return {
        "current_step": current_step + 1,
        "tool_calls": [
            *state.get("tool_calls", []),
            tool_call.model_dump(),
        ],
        "tool_results": [
            *state.get("tool_results", []),
            result_record.model_dump(),
        ],
    }
