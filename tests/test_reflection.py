"""Reflection Schema、节点和硬上限策略测试。"""

import pytest
from pydantic import ValidationError

from agent.reflection import ReflectionPolicy, reflect
from agent.schemas import ReviewResult


def test_review_failure_becomes_structured_reflection() -> None:
    """Reflection 应保留失败原因、缺失 Evidence 和下一轮动作。"""

    review = ReviewResult(
        round=1,
        passed=False,
        score=0.6,
        criterion_scores={"evidence_completeness": 0.0},
        issues=["存在必需但尚未获得的 Evidence。"],
        missing_evidence=["read_file"],
        reason="缺少实现文件内容。",
        recommended_action="补充 read_file Evidence。",
    )

    update = reflect(
        {
            "user_query": "读取实现",
            "review": review.model_dump(),
            "reflection_count": 0,
            "reflection_history": [],
        }
    )

    assert update["reflection_count"] == 1
    assert update["reflection"]["failure_reason"] == "缺少实现文件内容。"
    assert update["reflection"]["missing_evidence"] == ["read_file"]
    assert update["reflection"]["proposed_actions"] == ["read_file"]
    assert update["reflection_history"] == [update["reflection"]]
    assert ReflectionPolicy().max_reflections == 2


@pytest.mark.parametrize("max_reflections", [-1, 6])
def test_reflection_policy_enforces_hard_limit(max_reflections: int) -> None:
    """Reflection 配置必须满足 0～5 的硬边界。"""

    with pytest.raises(ValidationError):
        ReflectionPolicy(max_reflections=max_reflections)
