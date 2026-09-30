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
