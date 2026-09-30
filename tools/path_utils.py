"""Repository Tool 共享的 workspace 路径边界。"""

from pathlib import Path


class WorkspacePathError(ValueError):
    """用户路径违反 workspace 边界。"""


def normalize_workspace_root(workspace_root: Path) -> Path:
    """验证并规范化 workspace 根目录。"""

    root = workspace_root.resolve(strict=False)
    if not root.exists():
        raise ValueError(f"workspace 根目录不存在：{workspace_root}")
    if not root.is_dir():
        raise ValueError(f"workspace 根路径不是目录：{workspace_root}")
    return root


def resolve_workspace_path(workspace_root: Path, raw_path: str) -> Path:
    """将用户相对路径安全解析到 workspace 内。"""

    user_path = Path(raw_path)
    if user_path.is_absolute() or user_path.drive or user_path.anchor:
        raise WorkspacePathError("不允许使用绝对路径。")
    if ".." in user_path.parts:
        raise WorkspacePathError("路径不能包含 '..'。")

    candidate = (workspace_root / user_path).resolve(strict=False)
    if not candidate.is_relative_to(workspace_root):
        raise WorkspacePathError("路径超出 workspace 范围。")
    return candidate


def workspace_relative_path(workspace_root: Path, path: Path) -> str:
    """返回使用正斜杠的稳定 workspace 相对路径。"""

    relative_path = path.relative_to(workspace_root)
    return relative_path.as_posix() or "."
