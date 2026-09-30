"""任务分析节点测试。"""

import pytest

from agent.analyzer import analyze_task
from agent.schemas import TaskAnalysis


def test_analyze_repository_task() -> None:
    """项目结构请求应生成完整且可验证的分析。"""

    result = analyze_task({"user_query": "分析项目结构"})
    analysis = TaskAnalysis.model_validate(result)

    assert analysis.task_type == "repository_analysis"
    assert analysis.goal
    assert analysis.required_capabilities == ["repository_inspection"]


def test_analyzer_rejects_empty_query() -> None:
    """空请求不得生成伪造分析。"""

    with pytest.raises(ValueError, match="不能为空"):
        analyze_task({"user_query": "   "})


@pytest.mark.parametrize(
    ("query", "task_type"),
    [
        ("分析 octocat/Hello-World Issue #7", "github_issue_analysis"),
        ("分析 octocat/Hello-World PR #8", "github_pr_analysis"),
    ],
)
def test_analyze_github_reference(query: str, task_type: str) -> None:
    """GitHub Issue 和 PR 引用应得到明确任务类型。"""

    result = analyze_task({"user_query": query})

    assert result["task_type"] == task_type
    assert result["required_capabilities"] == ["github_api"]
