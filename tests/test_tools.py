"""三个本地 Repository Tool 的独立测试。"""

from pathlib import Path

import pytest

from tools.filesystem import ListDirectoryTool, ReadFileTool
from tools.repository import SearchCodeTool


def test_list_directory_returns_sorted_typed_entries(tmp_path: Path) -> None:
    """list_directory 应稳定区分文件和目录。"""

    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("说明", encoding="utf-8")

    result = ListDirectoryTool(tmp_path).invoke({"path": "."})

    assert result.success is True
    assert result.data == {
        "path": ".",
        "entries": [
            {"name": "README.md", "type": "file"},
            {"name": "src", "type": "directory"},
        ],
    }


def test_read_file_returns_utf8_content(tmp_path: Path) -> None:
    """read_file 应返回完整 UTF-8 内容。"""

    (tmp_path / "hello.txt").write_text("hello issueops", encoding="utf-8")

    result = ReadFileTool(tmp_path).invoke({"path": "hello.txt"})

    assert result.success is True
    assert result.data == {
        "path": "hello.txt",
        "content": "hello issueops",
        "truncated": False,
    }


def test_read_file_truncates_at_max_chars(tmp_path: Path) -> None:
    """read_file 不应越过调用方给出的字符上限。"""

    (tmp_path / "long.txt").write_text("abcdef", encoding="utf-8")

    result = ReadFileTool(tmp_path).invoke({"path": "long.txt", "max_chars": 3})

    assert result.success is True
    assert result.data["content"] == "abc"
    assert result.data["truncated"] is True


def test_read_file_rejects_binary_content(tmp_path: Path) -> None:
    """read_file 应明确拒绝明显二进制文件。"""

    (tmp_path / "binary.dat").write_bytes(b"text\x00binary")

    result = ReadFileTool(tmp_path).invoke({"path": "binary.dat"})

    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert "二进制" in result.error_message


def test_search_code_returns_path_line_number_and_line(tmp_path: Path) -> None:
    """search_code 应返回准确文件、行号和匹配行。"""

    source_directory = tmp_path / "src"
    source_directory.mkdir()
    (source_directory / "state.py").write_text(
        "class AgentState:\n    pass\n",
        encoding="utf-8",
    )

    result = SearchCodeTool(tmp_path).invoke({"query": "AgentState"})

    assert result.success is True
    assert result.data["matches"] == [
        {
            "path": "src/state.py",
            "line_number": 1,
            "line": "class AgentState:",
        }
    ]


def test_search_code_returns_empty_matches_for_missing_symbol(tmp_path: Path) -> None:
    """无匹配是成功的空结果。"""

    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")

    result = SearchCodeTool(tmp_path).invoke(
        {"query": "THIS_SYMBOL_DOES_NOT_EXIST"}
    )

    assert result.success is True
    assert result.data["matches"] == []


def test_search_code_honors_pattern_limit_and_ignored_directories(
    tmp_path: Path,
) -> None:
    """搜索应遵守文件模式、结果上限并跳过无意义目录。"""

    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "first.py").write_text("needle\nneedle\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle\n", encoding="utf-8")

    result = SearchCodeTool(tmp_path).invoke(
        {"query": "needle", "file_pattern": "*.py", "max_results": 1}
    )

    assert result.success is True
    assert result.data["matches"] == [
        {"path": "first.py", "line_number": 1, "line": "needle"}
    ]
    assert result.data["truncated"] is True


@pytest.mark.parametrize(
    ("tool_factory", "arguments"),
    [
        (ListDirectoryTool, {"path": "../outside"}),
        (ReadFileTool, {"path": "../outside.txt"}),
        (SearchCodeTool, {"query": "secret", "path": "../outside"}),
    ],
)
def test_repository_tools_reject_parent_path_escape(
    tmp_path: Path,
    tool_factory: type,
    arguments: dict,
) -> None:
    """三个 Tool 都必须拒绝包含父目录的路径。"""

    result = tool_factory(tmp_path).invoke(arguments)

    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert "路径" in result.error_message


def test_read_file_rejects_absolute_path(tmp_path: Path) -> None:
    """绝对路径不得进入 workspace 文件读取逻辑。"""

    result = ReadFileTool(tmp_path).invoke({"path": str(tmp_path / "inside.txt")})

    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert "绝对路径" in result.error_message
