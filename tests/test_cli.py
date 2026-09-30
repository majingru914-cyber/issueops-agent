"""命令行入口测试。"""

import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(
    *arguments: str,
    database_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """使用非 UTF-8 默认编码运行真实 CLI。"""

    environment = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp936"}
    if database_path is not None:
        environment["ISSUEOPS_DB_PATH"] = str(database_path)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


def test_cli_outputs_plan_and_execute_result(tmp_path: Path) -> None:
    """正常输入应输出计划、调用、证据和最终回答。"""

    result = run_cli("分析项目结构", database_path=tmp_path / "cli.db")
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
    assert (tmp_path / "cli.db").is_file()


def test_cli_executes_agent_state_multi_step(tmp_path: Path) -> None:
    """CLI 应真实执行 search_code 和 read_file 两个步骤。"""

    result = run_cli(
        "查找项目中 AgentState 的定义",
        database_path=tmp_path / "cli.db",
    )
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


def test_cli_rejects_missing_input(tmp_path: Path) -> None:
    """缺少参数时应显示用法并返回非零退出码。"""

    result = run_cli(database_path=tmp_path / "cli.db")

    assert result.returncode != 0
    assert "usage:" in result.stderr
    assert "必须提供用户请求" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_empty_input(tmp_path: Path) -> None:
    """空字符串不得生成计划。"""

    result = run_cli("", database_path=tmp_path / "cli.db")

    assert result.returncode != 0
    assert "用户请求不能为空" in result.stderr
    assert not result.stdout
    assert "Traceback" not in result.stderr


def test_cli_loads_persisted_task(tmp_path: Path) -> None:
    """CLI 应能够按 task_id 检查重启后仍存在的任务。"""

    database_path = tmp_path / "cli.db"
    run_result = run_cli("分析项目结构", database_path=database_path)
    task_id = json.loads(run_result.stdout)["task_id"]

    load_result = run_cli(
        "--load-task",
        task_id,
        database_path=database_path,
    )
    output = json.loads(load_result.stdout)

    assert load_result.returncode == 0
    assert output["task"]["task_id"] == task_id
    assert output["task"]["status"] == "completed"
    assert output["latest_state"]["final_answer"]
    assert output["state_history"][0]["stage"] == "created"
    assert output["trace"]
