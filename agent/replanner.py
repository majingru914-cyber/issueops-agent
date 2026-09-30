"""根据 Reflection 追加缺失 PlanStep，保留全部既有执行状态。"""

import json
import logging
from typing import Any

from agent.schemas import Evidence, PlanStep, ReflectionResult, ReplanRecord, TaskPlan
from agent.state import AgentState


LOGGER = logging.getLogger("issueops.agent")


def replan(state: AgentState) -> dict[str, object]:
    """只补充缺失步骤，不执行 Tool，也不清空旧 Evidence 或 Trace。"""

    plan = TaskPlan.model_validate({"steps": state.get("plan")})
    reflection = ReflectionResult.model_validate(state.get("reflection"))
    evidence = [
        Evidence.model_validate(item) for item in state.get("evidence", [])
    ]
    successful_sources = {item.source for item in evidence}
    existing_fingerprints = {
        _step_fingerprint(step.tool_name, step.tool_args) for step in plan.steps
    }

    added_steps: list[PlanStep] = []
    next_step_id = len(plan.steps) + 1
    for source in _ordered_missing_sources(reflection.missing_evidence):
        if source in successful_sources:
            continue
        step = _build_missing_step(
            source=source,
            step_id=next_step_id,
            state=state,
            evidence=evidence,
        )
        if step is None:
            continue
        fingerprint = _step_fingerprint(step.tool_name, step.tool_args)
        if fingerprint in existing_fingerprints:
            continue
        added_steps.append(step)
        existing_fingerprints.add(fingerprint)
        next_step_id += 1

    resulting_plan = TaskPlan(steps=[*plan.steps, *added_steps])
    replan_round = state.get("replan_count", 0) + 1
    record = ReplanRecord(
        round=replan_round,
        reason=reflection.failure_reason,
        previous_plan=plan.steps,
        added_steps=added_steps,
        resulting_plan=resulting_plan.steps,
    )
    LOGGER.info(
        "event=agent_replan task_id=%s round=%s previous_steps=%s "
        "added_steps=%s resulting_steps=%s",
        state.get("task_id", "unknown"),
        replan_round,
        len(plan.steps),
        len(added_steps),
        len(resulting_plan.steps),
    )
    return {
        "plan": [step.model_dump() for step in resulting_plan.steps],
        "replan_count": replan_round,
        "replan_records": [
            *state.get("replan_records", []),
            record.model_dump(),
        ],
    }


def _ordered_missing_sources(missing_evidence: list[str]) -> list[str]:
    """按依赖关系稳定排序缺失的 Tool Evidence。"""

    priority = {
        "search_code": 0,
        "read_file": 1,
        "list_directory": 2,
        "get_github_issue": 3,
        "get_github_pr": 4,
    }
    return sorted(set(missing_evidence), key=lambda item: (priority.get(item, 99), item))


def _build_missing_step(
    *,
    source: str,
    step_id: int,
    state: AgentState,
    evidence: list[Evidence],
) -> PlanStep | None:
    """把 Reviewer 指出的已知 Evidence 缺口转换为现有 PlanStep Contract。"""

    user_query = state.get("user_query", "")
    if source == "search_code":
        query = "AgentState" if "agentstate" in user_query.casefold() else user_query
        return PlanStep(
            id=step_id,
            goal="补充与用户目标相关的代码定位 Evidence",
            tool_name="search_code",
            tool_args={"query": query, "path": ".", "file_pattern": "*.py"},
        )
    if source == "read_file":
        path = _first_search_match_path(evidence)
        if path is None and "agentstate" in user_query.casefold():
            path = "agent/state.py"
        if path is None:
            return None
        return PlanStep(
            id=step_id,
            goal="读取已定位文件以补充实现 Evidence",
            tool_name="read_file",
            tool_args={"path": path},
        )
    if source == "list_directory":
        return PlanStep(
            id=step_id,
            goal="补充项目目录 Evidence",
            tool_name="list_directory",
            tool_args={"path": "."},
        )
    return None


def _first_search_match_path(evidence: list[Evidence]) -> str | None:
    """从既有 search_code Evidence 提取第一个稳定文件路径。"""

    for item in evidence:
        if item.source != "search_code" or not isinstance(item.raw_result, dict):
            continue
        matches = item.raw_result.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if isinstance(match, dict) and isinstance(match.get("path"), str):
                return match["path"]
    return None


def _step_fingerprint(tool_name: str | None, tool_args: dict[str, Any]) -> str:
    """生成 Tool 与参数的稳定标识，避免无理由重复旧步骤。"""

    return f"{tool_name}:{json.dumps(tool_args, ensure_ascii=False, sort_keys=True)}"
