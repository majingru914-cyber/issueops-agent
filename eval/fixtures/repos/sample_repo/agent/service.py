"""固定 Service Fixture。"""


class LoginService:
    """提供可被 search_code 定位的 login 方法。"""

    def login(self, username: str) -> bool:
        return bool(username)
