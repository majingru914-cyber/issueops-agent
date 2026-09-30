"""命令行入口测试。"""

import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    """使用非 UTF-8 默认编码运行真实 CLI。"""

    environment = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp936"}
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


def test_cli_outputs_plan_and_execute_result() -> None:
    """正常输入应输出计划、调用、证据和最终回答。"""

    result = run_cli("分析项目结构")
    output = json.loads(result.stdout)

    assert result.returncode == 0
    assert output["task_type"]
    assert output["task_id"]
    assert output["goal"]
    assert output["required_capabilities"]
    assert output["plan"]
    assert output["tool_calls"]
    assert output["tool_results"]
    assert output["tool_call_count"] == len(output["execution_attempts"])
    assert output["retry_count"] == 0
    assert output["evidence"]
    assert output["errors"] == []
    assert output["draft_answer"]
    assert output["review_passed"] is True
    assert output["review_score"] == 1.0
    assert output["review"]
    assert output["reflection_count"] == 0
    assert output["reflection"] is None
    assert output["replan_count"] == 0
    assert output["final_answer"]
    assert "event=tool_execute" in result.stderr
    assert "task_id=" in result.stderr


def test_cli_executes_agent_state_multi_step() -> None:
    """CLI 应真实执行 search_code 和 read_file 两个步骤。"""

    result = run_cli("查找项目中 AgentState 的定义")
    output = json.loads(result.stdout)

    assert result.returncode == 0
    assert [item["tool_name"] for item in output["tool_calls"]] == [
        "search_code",
        "read_file",
    ]
    assert len(output["evidence"]) == 2
    assert output["tool_call_count"] == 2
    assert len(output["execution_attempts"]) == 2
    assert output["review_passed"] is True
    assert output["reflection_count"] == 0
    assert output["draft_answer"] == output["final_answer"]
    assert "AgentState" in output["final_answer"]


def test_cli_rejects_missing_input() -> None:
    """缺少参数时应显示用法并返回非零退出码。"""

    result = run_cli()

    assert result.returncode != 0
    assert "usage:" in result.stderr
    assert "必须提供用户请求" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_empty_input() -> None:
    """空字符串不得生成计划。"""

    result = run_cli("")

    assert result.returncode != 0
    assert "用户请求不能为空" in result.stderr
    assert not result.stdout
    assert "Traceback" not in result.stderr
