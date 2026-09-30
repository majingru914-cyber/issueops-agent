"""GitHub API 边界使用的最小异常体系。"""


class GitHubApiError(RuntimeError):
    """GitHub API 普通请求或响应错误。"""

    error_code = "GITHUB_API_ERROR"

    retryable = False

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = self.__class__.retryable if retryable is None else retryable


class GitHubAuthenticationError(GitHubApiError):
    """GitHub 身份认证失败。"""

    error_code = "GITHUB_AUTH_ERROR"


class GitHubRateLimitError(GitHubApiError):
    """GitHub API 请求频率达到限制。"""

    error_code = "RATE_LIMIT"
    retryable = True

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        remaining: str | None = None,
        reset_at: str | None = None,
    ) -> None:
        super().__init__(message, status_code)
        self.remaining = remaining
        self.reset_at = reset_at


class GitHubNotFoundError(GitHubApiError):
    """GitHub 资源不存在或当前身份无权查看。"""

    error_code = "GITHUB_NOT_FOUND"


class GitHubRequestTimeoutError(GitHubApiError):
    """GitHub HTTP 请求超时。"""

    error_code = "TIMEOUT"
    retryable = True
