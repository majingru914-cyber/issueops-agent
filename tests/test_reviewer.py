"""确定性 Reviewer Contract 与判断标准测试。"""

from agent.reviewer import REVIEW_PASS_THRESHOLD, review_answer
from tools.base import ToolResult


def _result(step_id: int, tool_name: str, success: bool = True) -> dict:
    """构建 Reviewer 使用的最小 ToolResultRecord。"""

    result = (
        ToolResult(success=True, tool_name=tool_name, data={"ok": True})
        if success
        else ToolResult(
            success=False,
            tool_name=tool_name,
            error_code="FILE_NOT_FOUND",
            error_message="文件不存在。",
        )
    )
    return {"step_id": step_id, "result": result.model_dump()}


def _evidence(step_id: int, source: str, summary: str) -> dict:
    """构建 Reviewer 使用的最小 Evidence。"""

    return {
        "step_id": step_id,
        "source_type": "tool",
        "source": source,
        "summary": summary,
        "raw_result": {"ok": True},
    }


def _state() -> dict:
    """构建已定位并读取 AgentState 的充分状态。"""

    search_summary = "已定位 agent/state.py。"
    read_summary = "已读取 AgentState 实现。"
    return {
        "user_query": "查找项目中 AgentState 的定义",
        "goal": "定位并读取 AgentState 定义",
        "task_type": "repository_analysis",
        "plan": [
            {
                "id": 1,
                "goal": "定位定义",
                "tool_name": "search_code",
                "tool_args": {"query": "AgentState", "path": "."},
                "requires_tool": True,
            },
            {
                "id": 2,
                "goal": "读取实现",
                "tool_name": "read_file",
                "tool_args": {"path": "agent/state.py"},
                "requires_tool": True,
            },
        ],
        "current_step": 2,
        "tool_results": [
            _result(1, "search_code"),
            _result(2, "read_file"),
        ],
        "evidence": [
            _evidence(1, "search_code", search_summary),
            _evidence(2, "read_file", read_summary),
        ],
        "errors": [],
        "draft_answer": (
            f"证据：search_code：{search_summary}\nread_file：{read_summary}"
        ),
        "review_history": [],
    }


def test_sufficient_evidence_passes_review() -> None:
    """Goal、Evidence、Plan 与 Draft 均充分时必须直接通过。"""

    update = review_answer(_state())

    assert update["review_passed"] is True
    assert update["review_score"] >= REVIEW_PASS_THRESHOLD
    assert update["review"]["missing_evidence"] == []
    assert update["review"]["criterion_scores"] == {
        "goal_completion": 1.0,
        "evidence_completeness": 1.0,
        "execution_failure": 1.0,
        "plan_completion": 1.0,
        "answer_grounding": 1.0,
    }


def test_missing_read_file_evidence_fails_review() -> None:
    """只有 search_code 时应明确指出缺少 read_file Evidence。"""

    state = _state()
    state["plan"] = state["plan"][:1]
    state["current_step"] = 1
    state["tool_results"] = state["tool_results"][:1]
    state["evidence"] = state["evidence"][:1]
    state["draft_answer"] = "证据：search_code：已定位 agent/state.py。"

    update = review_answer(state)

    assert update["review_passed"] is False
    assert update["review_score"] < REVIEW_PASS_THRESHOLD
    assert update["review"]["missing_evidence"] == ["read_file"]
    assert "补充 Evidence" in update["review"]["recommended_action"]


def test_critical_error_fails_review() -> None:
    """必需 read_file 执行失败且缺少对应 Evidence 时必须失败。"""

    state = _state()
    state["tool_results"][1] = _result(2, "read_file", success=False)
    state["evidence"] = state["evidence"][:1]
    state["errors"] = [
        {
            "step_id": 2,
            "source": "read_file",
            "error_code": "FILE_NOT_FOUND",
            "error_message": "文件不存在。",
            "retryable": False,
            "last_error_code": None,
            "attempt_count": 1,
            "retry_count": 0,
        }
    ]
    state["draft_answer"] = "证据：search_code：已定位 agent/state.py。"

    update = review_answer(state)

    assert update["review_passed"] is False
    assert update["review"]["criterion_scores"]["execution_failure"] == 0.0
    assert "关键 Tool Error" in update["review"]["reason"]


def test_harmless_error_does_not_force_review_failure() -> None:
    """目标 Evidence 已充分时，无关失败不得导致一律 Fail。"""

    state = _state()
    state["plan"].append(
        {
            "id": 3,
            "goal": "可选目录检查",
            "tool_name": "list_directory",
            "tool_args": {"path": "missing"},
            "requires_tool": True,
        }
    )
    state["current_step"] = 3
    state["tool_results"].append(_result(3, "list_directory", success=False))
    state["errors"] = [
        {
            "step_id": 3,
            "source": "list_directory",
            "error_code": "FILE_NOT_FOUND",
            "error_message": "目录不存在。",
            "retryable": False,
            "last_error_code": None,
            "attempt_count": 1,
            "retry_count": 0,
        }
    ]

    update = review_answer(state)

    assert update["review_passed"] is True
    assert update["review"]["criterion_scores"]["execution_failure"] == 1.0


def test_reviewer_internal_error_fails_closed() -> None:
    """非法 Reviewer 输入不得使 Graph 逻辑直接抛出。"""

    update = review_answer({"user_query": "非法状态", "plan": None})

    assert update["review_passed"] is False
    assert update["review_score"] == 0.0
    assert "Reviewer 内部异常" in update["review"]["issues"][0]
