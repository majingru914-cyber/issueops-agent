"""受 workspace 边界保护的代码搜索 Tool。"""

import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.base import BaseTool
from tools.path_utils import (
    normalize_workspace_root,
    resolve_workspace_path,
    workspace_relative_path,
)


IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
}
MAX_SEARCH_FILE_BYTES = 1_000_000


class SearchCodeArgs(BaseModel):
    """search_code 的输入参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    path: str = Field(default=".", min_length=1)
    file_pattern: str | None = Field(default=None, min_length=1)
    max_results: int = Field(default=20, ge=1, le=200)


class SearchCodeTool(BaseTool):
    """在 workspace 内 UTF-8 文本文件中执行确定性搜索。"""

    name: ClassVar[str] = "search_code"
    description: ClassVar[str] = "在 workspace 内的文本代码中搜索字符串。"
    args_schema: ClassVar[type[BaseModel]] = SearchCodeArgs

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = normalize_workspace_root(workspace_root)

    def run(self, args: BaseModel) -> dict[str, Any]:
        """返回按路径和行号稳定排序的匹配项。"""

        validated_args = SearchCodeArgs.model_validate(args)
        target = resolve_workspace_path(self.workspace_root, validated_args.path)
        if not target.exists():
            raise FileNotFoundError(f"搜索路径不存在：{validated_args.path}")

        matches: list[dict[str, Any]] = []
        result_limit_reached = False
        for file_path in self._iter_files(target, validated_args.file_pattern):
            content = _read_searchable_text(file_path)
            if content is None:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if validated_args.query not in line:
                    continue
                matches.append(
                    {
                        "path": workspace_relative_path(self.workspace_root, file_path),
                        "line_number": line_number,
                        "line": line,
                    }
                )
                if len(matches) >= validated_args.max_results:
                    result_limit_reached = True
                    break
            if result_limit_reached:
                break

        return {
            "query": validated_args.query,
            "path": workspace_relative_path(self.workspace_root, target),
            "matches": matches,
            "truncated": result_limit_reached,
        }

    def _iter_files(self, target: Path, file_pattern: str | None):
        """以稳定顺序生成允许搜索的普通文件。"""

        if target.is_file():
            relative_path = target.relative_to(self.workspace_root)
            if not target.is_symlink() and _matches_pattern(relative_path, file_pattern):
                yield target
            return

        if not target.is_dir():
            raise ValueError("搜索目标既不是文件也不是目录。")

        for current_root, directory_names, file_names in os.walk(target):
            current_path = Path(current_root)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in IGNORED_DIRECTORY_NAMES
                and not (current_path / name).is_symlink()
            )
            for file_name in sorted(file_names):
                file_path = current_path / file_name
                if file_path.is_symlink() or not file_path.is_file():
                    continue
                relative_path = file_path.relative_to(self.workspace_root)
                if _matches_pattern(relative_path, file_pattern):
                    yield file_path


def _matches_pattern(relative_path: Path, file_pattern: str | None) -> bool:
    """判断相对路径是否满足可选 glob 模式。"""

    return file_pattern is None or relative_path.match(file_pattern)


def _read_searchable_text(file_path: Path) -> str | None:
    """读取大小受限的 UTF-8 文本；二进制和超大文件返回 None。"""

    if file_path.stat().st_size > MAX_SEARCH_FILE_BYTES:
        return None
    content = file_path.read_bytes()
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
