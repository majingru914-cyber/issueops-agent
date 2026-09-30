"""ToolRegistry、BaseTool 和 ToolRuntime 测试。"""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from tools.base import BaseTool, ToolResult
from tools.filesystem import ReadFileTool
from tools.registry import (
    ToolAlreadyRegisteredError,
    ToolNotFoundError,
    ToolRegistry,
)
from tools.runtime import ToolRuntime, build_default_registry


class NoArgs(BaseModel):
    """测试 Tool 使用的空参数模型。"""

    model_config = ConfigDict(extra="forbid")


class FailingTool(BaseTool):
    """用于验证异常转换的测试 Tool。"""

    name: ClassVar[str] = "failing_tool"
    description: ClassVar[str] = "始终失败的测试 Tool。"
    args_schema: ClassVar[type[BaseModel]] = NoArgs

    def run(self, args: BaseModel) -> Any:
        """产生一个可预测的执行异常。"""

        raise RuntimeError("模拟失败")


def test_default_registry_exposes_all_distinct_schemas(tmp_path: Path) -> None:
    """默认 Registry 应提供五个可发现且 Schema 不同的 Tool。"""

    registry = build_default_registry(tmp_path)
    metadata = registry.list_tools()

    assert [item["name"] for item in metadata] == [
        "get_github_issue",
        "get_github_pr",
        "list_directory",
        "read_file",
        "search_code",
    ]
    schema_properties = {
        item["name"]: set(item["args_schema"]["properties"]) for item in metadata
    }
    assert schema_properties == {
        "get_github_issue": {"owner", "repo", "issue_number"},
        "get_github_pr": {"owner", "repo", "pull_number"},
        "list_directory": {"path"},
        "read_file": {"path", "max_chars"},
        "search_code": {"query", "path", "file_pattern", "max_results"},
    }


def test_runtime_executes_all_default_tools(tmp_path: Path) -> None:
    """统一 Runtime 应能驱动不同 Tool 并返回 ToolResult。"""

    (tmp_path / "README.md").write_text("class AgentState:\n    pass\n", encoding="utf-8")
    runtime = ToolRuntime(build_default_registry(tmp_path))

    list_result = runtime.execute("list_directory", {"path": "."})
    read_result = runtime.execute("read_file", {"path": "README.md"})
    search_result = runtime.execute("search_code", {"query": "AgentState"})

    assert isinstance(list_result, ToolResult)
    assert isinstance(read_result, ToolResult)
    assert isinstance(search_result, ToolResult)
    assert list_result.success is True
    assert read_result.success is True
    assert search_result.success is True
    assert search_result.data["matches"][0]["line_number"] == 1


def test_runtime_returns_invalid_argument_result(tmp_path: Path) -> None:
    """缺少必填 path 时必须返回 INVALID_ARGUMENT。"""

    runtime = ToolRuntime(build_default_registry(tmp_path))

    result = runtime.execute("read_file", {})

    assert result.success is False
    assert result.error_code == "INVALID_ARGUMENT"
    assert result.retryable is False
    assert len(result.attempts) == 1


def test_runtime_returns_tool_not_found_result(tmp_path: Path) -> None:
    """未知 Tool 必须转换为统一失败结果。"""

    runtime = ToolRuntime(build_default_registry(tmp_path))

    result = runtime.execute("unknown_tool", {})

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.tool_name == "unknown_tool"
    assert result.error_code == "TOOL_NOT_FOUND"
    assert result.retryable is False
    assert len(result.attempts) == 1


def test_runtime_returns_failure_for_missing_file(tmp_path: Path) -> None:
    """不存在的文件不得产生未捕获异常。"""

    runtime = ToolRuntime(build_default_registry(tmp_path))

    result = runtime.execute("read_file", {"path": "missing.txt"})

    assert result.success is False
    assert result.error_code == "FILE_NOT_FOUND"
    assert result.retryable is False
    assert len(result.attempts) == 1
    assert "不存在" in result.error_message


def test_runtime_returns_failure_for_path_escape(tmp_path: Path) -> None:
    """Runtime 路径逃逸必须形成统一失败结果。"""

    runtime = ToolRuntime(build_default_registry(tmp_path))

    result = runtime.execute("read_file", {"path": "../outside.txt"})

    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert "路径" in result.error_message


def test_registry_rejects_duplicate_registration(tmp_path: Path) -> None:
    """重复 name 不得静默覆盖。"""

    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_path))

    with pytest.raises(ToolAlreadyRegisteredError, match="已注册"):
        registry.register(ReadFileTool(tmp_path))


def test_registry_get_rejects_unknown_tool() -> None:
    """Registry.get 对未知 Tool 必须产生明确异常。"""

    with pytest.raises(ToolNotFoundError, match="未找到"):
        ToolRegistry().get("unknown_tool")


def test_base_tool_converts_unexpected_exception() -> None:
    """具体 Tool 异常必须转换为 EXECUTION_FAILED。"""

    result = FailingTool().invoke({})

    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert "模拟失败" in result.error_message
