"""把 Review Fail 转换为结构化 Reflection，不执行任何 Tool。"""

import logging

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas import ReflectionResult, ReviewResult
from agent.state import AgentState


DEFAULT_MAX_REFLECTIONS = 2
MAX_REFLECTIONS_HARD_LIMIT = 5
LOGGER = logging.getLogger("issueops.agent")


class ReflectionPolicy(BaseModel):
    """限制单次 Agent 运行中的 Reflection / Re-plan 次数。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_reflections: int = Field(
        default=DEFAULT_MAX_REFLECTIONS,
        ge=0,
        le=MAX_REFLECTIONS_HARD_LIMIT,
    )


def reflect(state: AgentState) -> dict[str, object]:
    """解释 Review 未通过原因并提出缺失 Evidence 动作。"""

    review = ReviewResult.model_validate(state.get("review"))
    reflection_round = state.get("reflection_count", 0) + 1
    proposed_actions = list(review.missing_evidence)
    if not proposed_actions and review.recommended_action:
        proposed_actions.append(review.recommended_action)

    reflection = ReflectionResult(
        round=reflection_round,
        failure_reason=review.reason,
        missing_information=list(review.issues),
        missing_evidence=list(review.missing_evidence),
        plan_problems=[
            issue for issue in review.issues if "Plan" in issue or "计划" in issue
        ],
        proposed_actions=proposed_actions,
    )
    LOGGER.info(
        "event=agent_reflection task_id=%s round=%s missing_evidence=%s "
        "proposed_actions=%s",
        state.get("task_id", "unknown"),
        reflection.round,
        len(reflection.missing_evidence),
        len(reflection.proposed_actions),
    )
    dumped = reflection.model_dump()
    return {
        "reflection": dumped,
        "reflection_count": reflection_round,
        "reflection_history": [
            *state.get("reflection_history", []),
            dumped,
        ],
    }
