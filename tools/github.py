"""复用统一 Tool Contract 的只读 GitHub Issue 和 PR Tool。"""

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.base import BaseTool
from tools.github_client import GitHubClient
from tools.github_errors import GitHubApiError


OWNER_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$"
REPOSITORY_PATTERN = r"^[A-Za-z0-9_.-]+$"


class GetGitHubIssueArgs(BaseModel):
    """get_github_issue 的严格输入参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=39, pattern=OWNER_PATTERN)
    repo: str = Field(min_length=1, max_length=100, pattern=REPOSITORY_PATTERN)
    issue_number: int = Field(gt=0)


class GetGitHubPullRequestArgs(BaseModel):
    """get_github_pr 的严格输入参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner: str = Field(min_length=1, max_length=39, pattern=OWNER_PATTERN)
    repo: str = Field(min_length=1, max_length=100, pattern=REPOSITORY_PATTERN)
    pull_number: int = Field(gt=0)


class GitHubIssueData(BaseModel):
    """适合 Agent 使用的稳定 Issue 数据。"""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    user: str | None
    labels: list[str]
    created_at: str | None
    updated_at: str | None
    comments: int
    is_pull_request: bool


class GitHubPullRequestData(BaseModel):
    """适合 Agent 使用的稳定 Pull Request 数据。"""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    user: str | None
    base_branch: str
    head_branch: str
    draft: bool
    mergeable: bool | None
    created_at: str | None
    updated_at: str | None
    changed_files: int
    additions: int
    deletions: int


class _GitHubTool(BaseTool):
    """共享 GitHubClient 和领域错误映射的内部 Tool 基类。"""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    def _map_execution_error(self, error: Exception) -> tuple[str, str]:
        """把 Client 和响应 Schema 错误转换为稳定 Tool error code。"""

        if isinstance(error, GitHubApiError):
            return error.error_code, str(error)
        if isinstance(error, ValidationError):
            return "GITHUB_API_ERROR", "GitHub API 响应结构不符合预期。"
        return super()._map_execution_error(error)


class GetGitHubIssueTool(_GitHubTool):
    """读取单个 GitHub Issue。"""

    name: ClassVar[str] = "get_github_issue"
    description: ClassVar[str] = "读取一个 GitHub Issue 的稳定只读数据。"
    args_schema: ClassVar[type[BaseModel]] = GetGitHubIssueArgs

    def run(self, args: BaseModel) -> dict[str, Any]:
        """请求 Issue endpoint 并规范化响应。"""

        validated_args = GetGitHubIssueArgs.model_validate(args)
        payload = self.client.get(
            f"/repos/{validated_args.owner}/{validated_args.repo}"
            f"/issues/{validated_args.issue_number}"
        )
        issue = GitHubIssueData(
            owner=validated_args.owner,
            repo=validated_args.repo,
            number=payload.get("number", validated_args.issue_number),
            title=payload.get("title", ""),
            body=payload.get("body"),
            state=payload.get("state", "unknown"),
            html_url=payload.get("html_url", ""),
            user=_user_login(payload.get("user")),
            labels=_label_names(payload.get("labels", [])),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            comments=payload.get("comments", 0),
            is_pull_request="pull_request" in payload,
        )
        return issue.model_dump()


class GetGitHubPullRequestTool(_GitHubTool):
    """读取单个 GitHub Pull Request。"""

    name: ClassVar[str] = "get_github_pr"
    description: ClassVar[str] = "读取一个 GitHub Pull Request 的稳定只读数据。"
    args_schema: ClassVar[type[BaseModel]] = GetGitHubPullRequestArgs

    def run(self, args: BaseModel) -> dict[str, Any]:
        """请求 Pull Request endpoint 并规范化响应。"""

        validated_args = GetGitHubPullRequestArgs.model_validate(args)
        payload = self.client.get(
            f"/repos/{validated_args.owner}/{validated_args.repo}"
            f"/pulls/{validated_args.pull_number}"
        )
        pull_request = GitHubPullRequestData(
            owner=validated_args.owner,
            repo=validated_args.repo,
            number=payload.get("number", validated_args.pull_number),
            title=payload.get("title", ""),
            body=payload.get("body"),
            state=payload.get("state", "unknown"),
            html_url=payload.get("html_url", ""),
            user=_user_login(payload.get("user")),
            base_branch=_branch_name(payload.get("base"), "base"),
            head_branch=_branch_name(payload.get("head"), "head"),
            draft=payload.get("draft", False),
            mergeable=payload.get("mergeable"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            changed_files=payload.get("changed_files", 0),
            additions=payload.get("additions", 0),
            deletions=payload.get("deletions", 0),
        )
        return pull_request.model_dump()


def _user_login(raw_user: Any) -> str | None:
    """从 GitHub user object 提取 login。"""

    if raw_user is None:
        return None
    if not isinstance(raw_user, dict):
        raise GitHubApiError("GitHub API user 字段格式无效。")
    login = raw_user.get("login")
    if login is not None and not isinstance(login, str):
        raise GitHubApiError("GitHub API user.login 字段格式无效。")
    return login


def _label_names(raw_labels: Any) -> list[str]:
    """从 GitHub label object 列表提取名称。"""

    if not isinstance(raw_labels, list):
        raise GitHubApiError("GitHub API labels 字段格式无效。")
    names = []
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict) or not isinstance(raw_label.get("name"), str):
            raise GitHubApiError("GitHub API label 字段格式无效。")
        names.append(raw_label["name"])
    return names


def _branch_name(raw_branch: Any, field_name: str) -> str:
    """从 GitHub branch object 提取 ref。"""

    if not isinstance(raw_branch, dict) or not isinstance(raw_branch.get("ref"), str):
        raise GitHubApiError(f"GitHub API {field_name}.ref 字段格式无效。")
    return raw_branch["ref"]
