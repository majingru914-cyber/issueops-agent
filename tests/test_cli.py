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


def test_cli_outputs_structured_result() -> None:
    """正常输入应输出包含分析和计划的 JSON。"""

    result = run_cli("分析项目结构")
    output = json.loads(result.stdout)

    assert result.returncode == 0
    assert output["task_type"]
    assert output["goal"]
    assert output["required_capabilities"]
    assert output["plan"]


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
