"""Stage 00 仓库初始化冒烟测试。"""

from importlib import import_module
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_packages_are_importable() -> None:
    """核心包边界必须能够正常导入。"""
    for package_name in ("agent", "tools", "memory", "api"):
        module = import_module(package_name)
        assert module.__name__ == package_name


def test_required_project_files_exist() -> None:
    """Stage 00 配置文件和文档必须存在。"""
    required_files = (
        "README.md",
        "requirements.txt",
        "pyproject.toml",
        ".gitignore",
        ".env.example",
        "AGENTS.md",
    )

    for relative_path in required_files:
        assert (PROJECT_ROOT / relative_path).is_file(), (
            f"缺少必要项目文件：{relative_path}"
        )


def test_required_project_directories_exist() -> None:
    """Stage 00 包目录和工作目录必须存在。"""
    required_directories = (
        "agent",
        "tools",
        "memory",
        "api",
        "eval",
        "eval/reports",
        "tests",
        "examples",
        "docs",
    )

    for relative_path in required_directories:
        assert (PROJECT_ROOT / relative_path).is_dir(), (
            f"缺少必要项目目录：{relative_path}"
        )
