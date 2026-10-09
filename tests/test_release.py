"""Stage 11 Release artifact 与文档一致性测试。"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_artifacts_exist() -> None:
    """Release 必需文件必须存在且非空。"""

    required = (
        "LICENSE",
        "docs/architecture.md",
        "docs/demo.md",
        "docs/roadmap.md",
        "docs/release_checklist.md",
        "docs/releases/v0.1.0.md",
        "scripts/demo.ps1",
    )
    for relative_path in required:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        assert path.stat().st_size > 0, relative_path


def test_release_version_is_consistent() -> None:
    """Python metadata、README 与 Release Notes 使用同一版本。"""

    with (ROOT / "pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)
    assert metadata["project"]["version"] == "0.1.0"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notes = (ROOT / "docs/releases/v0.1.0.md").read_text(encoding="utf-8")
    assert "v0.1.0" in readme
    assert "IssueOps Agent v0.1.0" in notes


def test_readme_metrics_match_official_report() -> None:
    """README 的 correctness 与行为指标必须来自正式 JSON 报告。"""

    report = json.loads(
        (ROOT / "eval/reports/evaluation-report.json").read_text(encoding="utf-8")
    )
    metrics = report["metrics"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    expected = (
        f"| Benchmark Cases | {metrics['total_cases']} |",
        f"| Passed | {metrics['passed_cases']} |",
        f"| Case Pass Rate | {metrics['case_pass_rate']:.0%} |",
        f"| Task Success Rate | {metrics['task_success_rate']:.0%} |",
        f"| Tool Selection Accuracy | {metrics['tool_selection_accuracy']:.0%} |",
        f"| Tool Argument Accuracy | {metrics['tool_argument_accuracy']:.0%} |",
        f"| Avg Tool Calls | {metrics['avg_tool_calls']:.2f} |",
        f"| Avg Execution Attempts | {metrics['avg_execution_attempts']:.2f} |",
        f"| Retry Rate | {metrics['retry_rate']:.0%} |",
        f"| Reflection Rate | {metrics['reflection_rate']:.0%} |",
        f"| Recovery Rate | {metrics['recovery_rate']:.0%} |",
    )
    for row in expected:
        assert row in readme, row


def test_environment_example_contains_only_supported_variables() -> None:
    """示例环境文件不得保留代码未读取的配置或真实值。"""

    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in content.splitlines()
        if line and not line.startswith("#")
    }
    assert set(assignments) == {"GITHUB_TOKEN", "ISSUEOPS_DB_PATH"}
    assert assignments["GITHUB_TOKEN"] == ""
    assert assignments["ISSUEOPS_DB_PATH"] == "data/issueops.db"


def test_local_markdown_links_are_relative_and_resolve() -> None:
    """GitHub 文档不得包含本机绝对路径，所有本地链接必须可解析。"""

    markdown_files = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    windows_path = re.compile(r"^[A-Za-z]:[\\/]")

    for document in markdown_files:
        content = document.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:\\", content), document
        for raw_target in link_pattern.findall(content):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            assert not windows_path.match(path_part), (document, target)
            assert not Path(path_part).is_absolute(), (document, target)
            assert (document.parent / path_part).resolve().exists(), (
                document,
                target,
            )
