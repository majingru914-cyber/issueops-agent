"""Smoke tests for the Stage 00 repository bootstrap."""

from importlib import import_module
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_packages_are_importable() -> None:
    """The empty package boundaries must be valid Python packages."""
    for package_name in ("agent", "tools", "memory", "api"):
        module = import_module(package_name)
        assert module.__name__ == package_name


def test_required_project_files_exist() -> None:
    """Stage 00 configuration and documentation files must be present."""
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
            f"Required project file is missing: {relative_path}"
        )


def test_required_project_directories_exist() -> None:
    """Stage 00 package and workspace directories must be present."""
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
            f"Required project directory is missing: {relative_path}"
        )
