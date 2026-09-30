"""固定 Fixture 的示例测试。"""

from agent.service import LoginService


def test_login() -> None:
    assert LoginService().login("demo") is True
