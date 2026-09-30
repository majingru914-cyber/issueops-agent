"""唯一正式 Tool 执行入口与默认 Registry 构建器。"""

import os
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.base import ToolResult
from tools.filesystem import ListDirectoryTool, ReadFileTool
from tools.github import GetGitHubIssueTool, GetGitHubPullRequestTool
from tools.github_client import GitHubClient
from tools.registry import ToolNotFoundError, ToolRegistry
from tools.repository import SearchCodeTool


class ToolRuntime:
    """通过 Registry 查找并统一调用 Tool。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行原始 Tool 请求并始终返回 ToolResult。"""

        started_at = perf_counter()
        try:
            tool = self.registry.get(tool_name)
        except ToolNotFoundError:
            return ToolResult(
                success=False,
                tool_name=tool_name or "unknown",
                error_code="TOOL_NOT_FOUND",
                error_message=f"未找到 Tool：{tool_name}",
                latency_ms=max(0.0, (perf_counter() - started_at) * 1000),
            )
        return tool.invoke(arguments)


def build_default_registry(
    workspace_root: Path,
    github_client: GitHubClient | None = None,
) -> ToolRegistry:
    """构建包含本地 Repository Tool 和只读 GitHub Tool 的 Registry。"""

    registry = ToolRegistry()
    registry.register(ListDirectoryTool(workspace_root))
    registry.register(ReadFileTool(workspace_root))
    registry.register(SearchCodeTool(workspace_root))
    shared_github_client = (
        github_client
        if github_client is not None
        else GitHubClient(token=os.getenv("GITHUB_TOKEN"))
    )
    registry.register(GetGitHubIssueTool(shared_github_client))
    registry.register(GetGitHubPullRequestTool(shared_github_client))
    return registry


def build_tool_runtime(
    workspace_root: Path,
    github_client: GitHubClient | None = None,
) -> ToolRuntime:
    """构建可直接使用的默认 ToolRuntime。"""

    return ToolRuntime(build_default_registry(workspace_root, github_client))
