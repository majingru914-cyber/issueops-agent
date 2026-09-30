"""只读、同步且可注入 MockTransport 的 GitHub REST Client。"""

from typing import Any

import httpx

from tools.github_errors import (
    GitHubApiError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRequestTimeoutError,
)


DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 10.0


class GitHubClient:
    """集中处理 GitHub 认证、HTTP、超时和 API 错误。"""

    def __init__(
        self,
        token: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_GITHUB_API_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")

        normalized_token = token.strip() if token else None
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "issueops-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if normalized_token:
            headers["Authorization"] = f"Bearer {normalized_token}"

        self.timeout_seconds = timeout_seconds
        self.has_token = normalized_token is not None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    def get(self, endpoint: str) -> dict[str, Any]:
        """发送一次只读 GET 请求并返回 JSON object。"""

        normalized_endpoint = f"/{endpoint.lstrip('/')}"
        try:
            response = self._client.get(normalized_endpoint)
        except httpx.TimeoutException as error:
            raise GitHubRequestTimeoutError("GitHub API 请求超时。") from error
        except httpx.RequestError as error:
            raise GitHubApiError(
                f"GitHub API 网络请求失败：{error}",
                retryable=True,
            ) from error

        error_message = _response_message(response)
        if response.status_code == 401:
            raise GitHubAuthenticationError(
                "GitHub API 身份认证失败。",
                status_code=response.status_code,
            )
        if _is_rate_limited(response, error_message):
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_at = response.headers.get("X-RateLimit-Reset")
            details = []
            if remaining is not None:
                details.append(f"remaining={remaining}")
            if reset_at is not None:
                details.append(f"reset={reset_at}")
            suffix = f"（{', '.join(details)}）" if details else ""
            raise GitHubRateLimitError(
                f"GitHub API rate limit 已达到{suffix}。",
                status_code=response.status_code,
                remaining=remaining,
                reset_at=reset_at,
            )
        if response.status_code == 404:
            raise GitHubNotFoundError(
                "GitHub 资源不存在或当前身份无权查看。",
                status_code=response.status_code,
            )
        if response.is_error:
            message = error_message or response.reason_phrase or "未知错误"
            raise GitHubApiError(
                f"GitHub API 返回 HTTP {response.status_code}：{message}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise GitHubApiError("GitHub API 返回了无效 JSON。") from error
        if not isinstance(payload, dict):
            raise GitHubApiError("GitHub API 返回的 JSON 不是 object。")
        return payload

    def close(self) -> None:
        """关闭底层 httpx.Client。"""

        self._client.close()


def _response_message(response: httpx.Response) -> str | None:
    """安全提取 GitHub error message。"""

    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return None


def _is_rate_limited(response: httpx.Response, message: str | None) -> bool:
    """根据状态码、header 和 GitHub message 识别 rate limit。"""

    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return message is not None and "rate limit" in message.casefold()
