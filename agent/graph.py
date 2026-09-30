"""IssueOps Agent 的最小 LangGraph 定义。"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.analyzer import analyze_task
from agent.planner import create_plan
from agent.state import AgentState


def build_agent_graph() -> CompiledStateGraph:
    """构建并编译 Stage 01 的唯一运行图。"""

    graph = StateGraph(AgentState)
    graph.add_node("analyze_task", analyze_task)
    graph.add_node("create_plan", create_plan)
    graph.add_edge(START, "analyze_task")
    graph.add_edge("analyze_task", "create_plan")
    graph.add_edge("create_plan", END)
    return graph.compile()


compiled_graph = build_agent_graph()
