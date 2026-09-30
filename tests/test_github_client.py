"""GitHubClient 的离线 HTTP 边界测试。"""

from collections.abc import Callable

import httpx
import pytest

from tools.github_client import GitHubClient
from tools.github_errors import (
    GitHubApiError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRequestTimeoutError,
)


def build_client(
    handler: Callable[[httpx.Request], httpx.Response],
    token: str | None = None,
) -> GitHubClient:
    """使用 MockTransport 构建不会访问公网的 Client。"""

    return GitHubClient(token=token, transport=httpx.MockTransport(handler))


def test_client_parses_success_and_sends_authentication() -> None:
    """有 Token 时应发送 Bearer header 并解析 JSON object。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.extensions["timeout"]["read"] == 10.0
        return httpx.Response(200, json={"number": 1}, request=request)

    client = build_client(handler, token="test-token")

    assert client.get("/repos/octocat/Hello-World/issues/1") == {"number": 1}
    assert client.has_token is True
    client.close()


def test_client_supports_anonymous_read_only_request() -> None:
    """无 Token 时不发送 Authorization header，也不会在初始化阶段失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"state": "open"}, request=request)

    client = build_client(handler)

    assert client.get("/repos/octocat/Hello-World/issues/1") == {"state": "open"}
    assert client.has_token is False
    client.close()


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, GitHubAuthenticationError),
        (404, GitHubNotFoundError),
    ],
)
def test_client_maps_authentication_and_not_found(
    status_code: int,
    error_type: type[GitHubApiError],
) -> None:
    """401 和 404 应映射为稳定领域异常。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "error"}, request=request)

    client = build_client(handler)

    with pytest.raises(error_type):
        client.get("/resource")
    client.close()


def test_client_detects_rate_limit() -> None:
    """rate-limit header 必须优先映射为 GitHubRateLimitError。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "12345"},
            request=request,
        )

    client = build_client(handler)

    with pytest.raises(GitHubRateLimitError) as captured:
        client.get("/resource")

    assert captured.value.remaining == "0"
    assert captured.value.reset_at == "12345"
    client.close()


def test_client_treats_http_429_as_rate_limit_without_headers() -> None:
    """HTTP 429 即使没有 rate-limit header 也必须稳定识别。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "slow down"}, request=request)

    client = build_client(handler)

    with pytest.raises(GitHubRateLimitError):
        client.get("/resource")
    client.close()


def test_client_maps_request_timeout() -> None:
    """httpx timeout 不得穿透 Client 边界。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("模拟超时", request=request)

    client = build_client(handler)

    with pytest.raises(GitHubRequestTimeoutError):
        client.get("/resource")
    client.close()


def test_client_rejects_invalid_json() -> None:
    """成功状态下的非 JSON 响应必须被视为 API 错误。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>error</html>", request=request)

    client = build_client(handler)

    with pytest.raises(GitHubApiError, match="无效 JSON"):
        client.get("/resource")
    client.close()


def test_client_maps_unexpected_http_error() -> None:
    """普通 HTTP error 应映射为 GitHubApiError。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "server error"}, request=request)

    client = build_client(handler)

    with pytest.raises(GitHubApiError, match="HTTP 500"):
        client.get("/resource")
    client.close()
