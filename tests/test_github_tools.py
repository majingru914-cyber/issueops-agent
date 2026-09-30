"""GitHub Tool 与统一 ToolRuntime 的离线集成测试。"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tools.base import ToolResult
from tools.github_client import GitHubClient
from tools.runtime import ToolRuntime, build_default_registry


ISSUE_PAYLOAD = {
    "number": 7,
    "title": "修复登录问题",
    "body": "Issue body",
    "state": "open",
    "html_url": "https://github.com/octocat/Hello-World/issues/7",
    "user": {"login": "octocat"},
    "labels": [{"name": "bug"}],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
    "comments": 2,
}

PR_PAYLOAD = {
    "number": 8,
    "title": "增加测试",
    "body": None,
    "state": "open",
    "html_url": "https://github.com/octocat/Hello-World/pull/8",
    "user": {"login": "contributor"},
    "base": {"ref": "main"},
    "head": {"ref": "feature/tests"},
    "draft": False,
    "mergeable": True,
    "created_at": "2026-01-03T00:00:00Z",
    "updated_at": "2026-01-04T00:00:00Z",
    "changed_files": 3,
    "additions": 20,
    "deletions": 4,
}


def build_runtime(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
) -> ToolRuntime:
    """构建共享 Mock GitHubClient 的默认 Runtime。"""

    client = GitHubClient(transport=httpx.MockTransport(handler))
    return ToolRuntime(build_default_registry(tmp_path, client))


def test_runtime_gets_normalized_issue(tmp_path: Path) -> None:
    """Issue 必须通过统一 Runtime 返回稳定内部数据。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octocat/Hello-World/issues/7"
        return httpx.Response(200, json=ISSUE_PAYLOAD, request=request)

    runtime = build_runtime(tmp_path, handler)

    result = runtime.execute(
        "get_github_issue",
        {"owner": "octocat", "repo": "Hello-World", "issue_number": 7},
    )

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.tool_name == "get_github_issue"
    assert result.data == {
        "owner": "octocat",
        "repo": "Hello-World",
        "number": 7,
        "title": "修复登录问题",
        "body": "Issue body",
        "state": "open",
        "html_url": "https://github.com/octocat/Hello-World/issues/7",
        "user": "octocat",
        "labels": ["bug"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "comments": 2,
        "is_pull_request": False,
    }


def test_issue_tool_marks_pull_request_payload(tmp_path: Path) -> None:
    """Issue endpoint 返回 PR object 时必须明确标记。"""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {**ISSUE_PAYLOAD, "pull_request": {"url": "https://api.github.com/pr/7"}}
        return httpx.Response(200, json=payload, request=request)

    result = build_runtime(tmp_path, handler).execute(
        "get_github_issue",
        {"owner": "octocat", "repo": "Hello-World", "issue_number": 7},
    )

    assert result.success is True
    assert result.data["is_pull_request"] is True


def test_runtime_gets_normalized_pull_request(tmp_path: Path) -> None:
    """PR 必须通过同一 Runtime 返回稳定内部数据。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octocat/Hello-World/pulls/8"
        return httpx.Response(200, json=PR_PAYLOAD, request=request)

    result = build_runtime(tmp_path, handler).execute(
        "get_github_pr",
        {"owner": "octocat", "repo": "Hello-World", "pull_number": 8},
    )

    assert result.success is True
    assert result.tool_name == "get_github_pr"
    assert result.data["base_branch"] == "main"
    assert result.data["head_branch"] == "feature/tests"
    assert result.data["changed_files"] == 3


def test_invalid_arguments_do_not_send_http_request(tmp_path: Path) -> None:
    """Schema 失败必须发生在 HTTP 请求之前。"""

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=ISSUE_PAYLOAD, request=request)

    result = build_runtime(tmp_path, handler).execute(
        "get_github_issue",
        {"owner": "octocat", "repo": "Hello-World", "issue_number": "abc"},
    )

    assert result.success is False
    assert result.error_code == "INVALID_ARGUMENT"
    assert request_count == 0


@pytest.mark.parametrize(
    ("status_code", "headers", "expected_code"),
    [
        (404, {}, "GITHUB_NOT_FOUND"),
        (401, {}, "GITHUB_AUTH_ERROR"),
        (403, {"X-RateLimit-Remaining": "0"}, "RATE_LIMIT"),
        (500, {}, "GITHUB_API_ERROR"),
    ],
)
def test_github_http_failures_become_tool_results(
    tmp_path: Path,
    status_code: int,
    headers: dict[str, str],
    expected_code: str,
) -> None:
    """GitHub HTTP failure 必须稳定转换为 ToolResult。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"message": "API rate limit exceeded" if status_code == 403 else "error"},
            headers=headers,
            request=request,
        )

    result = build_runtime(tmp_path, handler).execute(
        "get_github_issue",
        {"owner": "octocat", "repo": "missing", "issue_number": 1},
    )

    assert result.success is False
    assert result.error_code == expected_code


def test_github_timeout_becomes_tool_result(tmp_path: Path) -> None:
    """HTTP timeout 必须转换为 TIMEOUT。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("模拟超时", request=request)

    result = build_runtime(tmp_path, handler).execute(
        "get_github_pr",
        {"owner": "octocat", "repo": "Hello-World", "pull_number": 8},
    )

    assert result.success is False
    assert result.error_code == "TIMEOUT"


def test_local_and_github_tools_share_one_runtime(tmp_path: Path) -> None:
    """本地 Tool 与 GitHub Tool 必须共存于同一个 Runtime。"""

    (tmp_path / "README.md").write_text("本地文件", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ISSUE_PAYLOAD, request=request)

    runtime = build_runtime(tmp_path, handler)
    local_result = runtime.execute("read_file", {"path": "README.md"})
    github_result = runtime.execute(
        "get_github_issue",
        {"owner": "octocat", "repo": "Hello-World", "issue_number": 7},
    )

    assert local_result.success is True
    assert github_result.success is True
    assert isinstance(local_result, ToolResult)
    assert isinstance(github_result, ToolResult)


@pytest.mark.parametrize(("token", "has_token"), [("test-token", True), (None, False)])
def test_default_registry_reads_optional_token_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
    has_token: bool,
) -> None:
    """默认 builder 只从 GITHUB_TOKEN 读取可选认证信息。"""

    if token is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", token)

    registry = build_default_registry(tmp_path)
    issue_tool = registry.get("get_github_issue")

    assert issue_tool.client.has_token is has_token
    issue_tool.client.close()
