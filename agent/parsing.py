"""用户请求中的轻量确定性结构提取。"""

import re
from typing import NamedTuple


class GitHubReference(NamedTuple):
    """用户请求中的 GitHub 仓库资源引用。"""

    kind: str
    owner: str
    repo: str
    number: int


PULL_REQUEST_PATTERN = re.compile(
    r"(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.-]+)\s+"
    r"(?:pull\s*request|pr)\s*#?(?P<number>\d+)",
    re.IGNORECASE,
)
ISSUE_PATTERN = re.compile(
    r"(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.-]+)\s+"
    r"issue\s*#?(?P<number>\d+)",
    re.IGNORECASE,
)


def parse_github_reference(user_query: str) -> GitHubReference | None:
    """解析 Issue 或 PR 引用；无法解析时返回 None。"""

    for kind, pattern in (
        ("pull_request", PULL_REQUEST_PATTERN),
        ("issue", ISSUE_PATTERN),
    ):
        match = pattern.search(user_query)
        if match:
            return GitHubReference(
                kind=kind,
                owner=match.group("owner"),
                repo=match.group("repo"),
                number=int(match.group("number")),
            )
    return None
