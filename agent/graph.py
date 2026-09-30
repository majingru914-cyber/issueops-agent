"""IssueOps Agent Plan-and-Execute LangGraph。"""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.analyzer import analyze_task
from agent.evidence import collect_evidence
from agent.executor import execute_step, record_tool_budget_exceeded
from agent.generator import generate_answer, has_more_steps
from agent.planner import create_plan
from agent.state import AgentState
from tools.runtime import ToolRuntime


PlannerNode = Callable[[AgentState], dict[str, object]]


def build_agent_graph(
    tool_runtime: ToolRuntime,
    planner_node: PlannerNode = create_plan,
) -> CompiledStateGraph:
    """使用注入的唯一 Runtime 构建并编译执行循环。"""

    def executor_node(state: AgentState) -> dict[str, object]:
        """闭包捕获 ToolRuntime，避免与 LangGraph Runtime 注入冲突。"""

        return execute_step(state, tool_runtime)

    def budget_node(state: AgentState) -> dict[str, object]:
        """使用 Runtime Policy 的同一全局预算记录终止原因。"""

        return record_tool_budget_exceeded(
            state,
            tool_runtime.policy.max_tool_calls,
        )

    def route_after_evidence(state: AgentState) -> str:
        """把 Policy 中的预算注入条件边判断。"""

        return has_more_steps(state, tool_runtime.policy.max_tool_calls)

    graph = StateGraph(AgentState)
    graph.add_node("analyze_task", analyze_task)
    graph.add_node("create_plan", planner_node)
    graph.add_node("execute_step", executor_node)
    graph.add_node("collect_evidence", collect_evidence)
    graph.add_node("tool_budget_exceeded", budget_node)
    graph.add_node("generate_answer", generate_answer)

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
            "generate_answer": "generate_answer",
        },
    )
    graph.add_edge("tool_budget_exceeded", "generate_answer")
    graph.add_edge("generate_answer", END)
    return graph.compile()
