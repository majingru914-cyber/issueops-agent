"""ToolResult 到 Evidence / Error 的转换测试。"""

from agent.evidence import collect_evidence
from tools.base import ToolResult


def result_state(result: ToolResult) -> dict:
    """构建包含一个结果记录的最小 State。"""

    return {
        "tool_results": [{"step_id": 1, "result": result.model_dump()}],
        "evidence": [],
        "errors": [],
    }


def test_successful_tool_result_becomes_traceable_evidence() -> None:
    """成功结果的数据必须原样进入可追踪 Evidence。"""

    data = {"path": "README.md", "content": "真实内容", "truncated": False}
    update = collect_evidence(
        result_state(ToolResult(success=True, tool_name="read_file", data=data))
    )

    evidence = update["evidence"][0]
    assert evidence["step_id"] == 1
    assert evidence["source"] == "read_file"
    assert evidence["raw_result"] == data
    assert "真实内容" in evidence["summary"]


def test_read_file_summary_does_not_end_with_truncated_whitespace() -> None:
    """固定长度预览不得以空白结尾，避免 Draft grounding 逐字比较误判。"""

    content = f"{'x' * 239} 后续内容"
    update = collect_evidence(
        result_state(
            ToolResult(
                success=True,
                tool_name="read_file",
                data={"path": "sample.py", "content": content, "truncated": False},
            )
        )
    )

    assert not update["evidence"][0]["summary"].endswith(" ")


def test_failed_tool_result_becomes_execution_error() -> None:
    """失败结果不得伪造 Evidence，而应进入 errors。"""

    update = collect_evidence(
        result_state(
            ToolResult(
                success=False,
                tool_name="read_file",
                error_code="INVALID_ARGUMENT",
                error_message="缺少 path。",
            )
        )
    )

    assert "evidence" not in update
    assert update["errors"] == [
        {
            "step_id": 1,
            "source": "read_file",
            "error_code": "INVALID_ARGUMENT",
            "error_message": "缺少 path。",
            "retryable": False,
            "last_error_code": None,
            "attempt_count": 0,
            "retry_count": 0,
        }
    ]
