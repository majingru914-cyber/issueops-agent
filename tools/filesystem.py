"""受 workspace 边界保护的本地文件系统 Tool。"""

from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.base import BaseTool
from tools.path_utils import (
    normalize_workspace_root,
    resolve_workspace_path,
    workspace_relative_path,
)


class ListDirectoryArgs(BaseModel):
    """list_directory 的输入参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    path: str = Field(default=".", min_length=1)


class ReadFileArgs(BaseModel):
    """read_file 的输入参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    path: str = Field(min_length=1)
    max_chars: int = Field(default=100_000, ge=1, le=1_000_000)


class ListDirectoryTool(BaseTool):
    """列出 workspace 内一个目录的直接子项。"""

    name: ClassVar[str] = "list_directory"
    description: ClassVar[str] = "列出 workspace 内目录的直接子项。"
    args_schema: ClassVar[type[BaseModel]] = ListDirectoryArgs

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = normalize_workspace_root(workspace_root)

    def run(self, args: BaseModel) -> dict[str, Any]:
        """返回名称稳定排序的目录项。"""

        validated_args = ListDirectoryArgs.model_validate(args)
        target = resolve_workspace_path(self.workspace_root, validated_args.path)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在：{validated_args.path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录：{validated_args.path}")

        entries = []
        for entry in sorted(target.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if entry.is_symlink():
                entry_type = "other"
            elif entry.is_dir():
                entry_type = "directory"
            elif entry.is_file():
                entry_type = "file"
            else:
                entry_type = "other"
            entries.append({"name": entry.name, "type": entry_type})

        return {
            "path": workspace_relative_path(self.workspace_root, target),
            "entries": entries,
        }


class ReadFileTool(BaseTool):
    """读取 workspace 内一个 UTF-8 文本文件。"""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = "读取 workspace 内的 UTF-8 文本文件。"
    args_schema: ClassVar[type[BaseModel]] = ReadFileArgs

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = normalize_workspace_root(workspace_root)

    def run(self, args: BaseModel) -> dict[str, Any]:
        """按字符上限读取文本并报告是否截断。"""

        validated_args = ReadFileArgs.model_validate(args)
        target = resolve_workspace_path(self.workspace_root, validated_args.path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在：{validated_args.path}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是普通文件：{validated_args.path}")

        try:
            with target.open("r", encoding="utf-8") as file:
                content = file.read(validated_args.max_chars + 1)
        except UnicodeDecodeError as error:
            raise ValueError("目标文件不是有效的 UTF-8 文本。") from error

        if "\x00" in content:
            raise ValueError("目标文件可能是二进制文件。")

        truncated = len(content) > validated_args.max_chars
        if truncated:
            content = content[: validated_args.max_chars]

        return {
            "path": workspace_relative_path(self.workspace_root, target),
            "content": content,
            "truncated": truncated,
        }
