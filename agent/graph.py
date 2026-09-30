"""IssueOps Agent Reviewer / Reflection / Re-plan LangGraph。"""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.analyzer import analyze_task
from agent.evidence import collect_evidence
from agent.executor import execute_step, record_tool_budget_exceeded
from agent.generator import finalize_answer, generate_draft_answer, has_more_steps
from agent.planner import create_plan
from agent.reflection import ReflectionPolicy, reflect
from agent.replanner import replan
from agent.reviewer import review_answer, review_failure
from agent.state import AgentState
from memory.recorder import StateRecorder
from tools.runtime import ToolRuntime


AgentNode = Callable[[AgentState], dict[str, object]]


def build_agent_graph(
    tool_runtime: ToolRuntime,
    planner_node: AgentNode = create_plan,
    reviewer_node: AgentNode = review_answer,
    reflection_node: AgentNode = reflect,
    replanner_node: AgentNode = replan,
    reflection_policy: ReflectionPolicy | None = None,
    recorder: StateRecorder | None = None,
) -> CompiledStateGraph:
    """构建受 Tool 与 Reflection 双预算保护的完整核心 Agent 闭环。"""

    active_reflection_policy = reflection_policy or ReflectionPolicy()

    def executor_node(state: AgentState) -> dict[str, object]:
        """闭包捕获唯一 ToolRuntime。"""

        return execute_step(state, tool_runtime)

    def recorded_node(
        stage: str,
        node: AgentNode,
    ) -> AgentNode:
        """可选记录节点结果，但原样返回 update，避免改变 Graph 语义。"""

        if recorder is None:
            return node

        def run_and_record(state: AgentState) -> dict[str, object]:
            update = node(state)
            recorder.record_node(stage, dict(state), update)
            return update

        return run_and_record

    def budget_node(state: AgentState) -> dict[str, object]:
        """记录初始或普通计划执行期间的 Tool 预算耗尽。"""

        return record_tool_budget_exceeded(state, tool_runtime.policy.max_tool_calls)

    def safe_reviewer_node(state: AgentState) -> dict[str, object]:
        """Reviewer 异常按 fail closed 转换为结构化 Review。"""

        try:
            return reviewer_node(state)
        except Exception as error:
            return review_failure(state, error)

    def route_after_evidence(state: AgentState) -> str:
        """在计划步骤、Tool 预算与 Draft 之间路由。"""

        return has_more_steps(state, tool_runtime.policy.max_tool_calls)

    def route_after_review(state: AgentState) -> str:
        """Review Pass 或 Reflection 达上限时进入 Final。"""

        if state.get("review_passed") is True:
            return "finalize"
        if state.get("reflection_count", 0) >= active_reflection_policy.max_reflections:
            return "finalize"
        return "reflect"

    def route_after_replan(state: AgentState) -> str:
        """Re-plan 后只执行新增步骤，并继续服从 Stage 05 Tool 预算。"""

        if state.get("current_step", 0) < len(state.get("plan", [])):
            if (
                state.get("tool_call_count", 0)
                >= tool_runtime.policy.max_tool_calls
            ):
                return "budget_exceeded"
            return "execute"
        return "generate_draft"

    graph = StateGraph(AgentState)
    graph.add_node("analyze_task", recorded_node("analyzed", analyze_task))
    graph.add_node("create_plan", recorded_node("planned", planner_node))
    graph.add_node("execute_step", recorded_node("executed", executor_node))
    graph.add_node(
        "collect_evidence",
        recorded_node("evidence_collected", collect_evidence),
    )
    graph.add_node(
        "tool_budget_exceeded",
        recorded_node("budget_exceeded", budget_node),
    )
    graph.add_node(
        "generate_draft_answer",
        recorded_node("drafted", generate_draft_answer),
    )
    graph.add_node("review_answer", recorded_node("reviewed", safe_reviewer_node))
    graph.add_node("reflect", recorded_node("reflected", reflection_node))
    graph.add_node("replan", recorded_node("replanned", replanner_node))
    graph.add_node(
        "replan_budget_exceeded",
        recorded_node("budget_exceeded", budget_node),
    )
    graph.add_node("finalize_answer", recorded_node("finalized", finalize_answer))

    graph.add_edge(START, "analyze_task")
    graph.add_edge("analyze_task", "create_plan")
    graph.add_edge("create_plan", "execute_step")
    graph.add_edge("execute_step", "collect_evidence")
    graph.add_conditional_edges(
        "collect_evidence",
        route_after_evidence,
        {
            "execute": "execute_step",
            "budget_exceeded": "tool_budget_exceeded",
            "generate_draft": "generate_draft_answer",
        },
    )
    graph.add_edge("tool_budget_exceeded", "generate_draft_answer")
    graph.add_edge("generate_draft_answer", "review_answer")
    graph.add_conditional_edges(
        "review_answer",
        route_after_review,
        {
            "finalize": "finalize_answer",
            "reflect": "reflect",
        },
    )
    graph.add_edge("reflect", "replan")
    graph.add_conditional_edges(
        "replan",
        route_after_replan,
        {
            "execute": "execute_step",
            "budget_exceeded": "replan_budget_exceeded",
            "generate_draft": "generate_draft_answer",
        },
    )
    graph.add_edge("replan_budget_exceeded", "finalize_answer")
    graph.add_edge("finalize_answer", END)
    return graph.compile()
