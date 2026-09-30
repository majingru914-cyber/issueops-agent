"""LangGraph 构建与端到端测试。"""

from agent.graph import build_agent_graph
from agent.schemas import TaskAnalysis, TaskPlan


def test_graph_compiles_with_expected_nodes() -> None:
    """Graph 必须成功编译并包含两个 Stage 01 节点。"""

    graph = build_agent_graph()
    graph_description = graph.get_graph()

    assert "analyze_task" in graph_description.nodes
    assert "create_plan" in graph_description.nodes
    assert {
        (edge.source, edge.target) for edge in graph_description.edges
    } == {
        ("__start__", "analyze_task"),
        ("analyze_task", "create_plan"),
        ("create_plan", "__end__"),
    }


def test_graph_end_to_end() -> None:
    """用户请求必须依次得到分析状态和结构化计划。"""

    graph = build_agent_graph()
    result = graph.invoke({"user_query": "分析项目结构"})
    analysis = TaskAnalysis.model_validate(
        {
            "task_type": result["task_type"],
            "goal": result["goal"],
            "required_capabilities": result["required_capabilities"],
        }
    )
    plan = TaskPlan.model_validate({"steps": result["plan"]})

    assert analysis.task_type
    assert analysis.goal
    assert analysis.required_capabilities
    assert plan.steps
