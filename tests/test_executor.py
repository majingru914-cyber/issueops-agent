"""Executor 对统一 ToolRuntime 的消费测试。"""

from pathlib import Path

import pytest

from agent.evidence import collect_evidence
from agent.executor import execute_step
from tools.runtime import build_tool_runtime


def build_state(tool_name: str, tool_args: dict) -> dict:
    """构建单步骤执行状态。"""

    return {
        "user_query": "测试执行",
        "plan": [
            {
                "id": 1,
                "goal": "执行测试步骤",
                "tool_name": tool_name,
                "tool_args": tool_args,
                "requires_tool": True,
            }
        ],
        "current_step": 0,
        "tool_calls": [],
        "tool_results": [],
        "evidence": [],
        "errors": [],
    }


def test_executor_runs_repository_tool_and_records_state(tmp_path: Path) -> None:
    """Executor 必须通过 Runtime 读取文件并保存结构化记录。"""

    (tmp_path / "README.md").write_text("真实内容", encoding="utf-8")
    runtime = build_tool_runtime(tmp_path)
    state = build_state("read_file", {"path": "README.md"})

    update = execute_step(state, runtime)

    assert update["current_step"] == 1
    assert update["tool_call_count"] == 1
    assert update["retry_count"] == 0
    assert len(update["execution_attempts"]) == 1
    assert update["tool_calls"] == [
        {
            "step_id": 1,
            "tool_name": "read_file",
            "arguments": {"path": "README.md"},
        }
    ]
    assert update["tool_results"][0]["result"]["success"] is True
    assert update["tool_results"][0]["result"]["data"]["content"] == "真实内容"
    runtime.registry.get("get_github_issue").client.close()


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "error_code"),
    [
        ("unknown_tool", {}, "TOOL_NOT_FOUND"),
        ("read_file", {}, "INVALID_ARGUMENT"),
    ],
)
def test_executor_failure_enters_errors_without_traceback(
    tmp_path: Path,
    tool_name: str,
    tool_args: dict,
    error_code: str,
) -> None:
    """未知 Tool 和非法参数应进入 State.errors。"""

    runtime = build_tool_runtime(tmp_path)
    state = build_state(tool_name, tool_args)

    execution_update = execute_step(state, runtime)
    updated_state = {**state, **execution_update}
    evidence_update = collect_evidence(updated_state)

    assert execution_update["current_step"] == 1
    assert execution_update["tool_call_count"] == 1
    assert execution_update["retry_count"] == 0
    assert execution_update["tool_results"][0]["result"]["success"] is False
    assert evidence_update["errors"][0]["error_code"] == error_code
    runtime.registry.get("get_github_issue").client.close()
