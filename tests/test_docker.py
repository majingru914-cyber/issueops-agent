"""Stage 10 Docker packaging contract 的离线静态测试。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_expected_single_process_service_contract() -> None:
    """Image 必须使用 Python 3.12、现有依赖和单 Uvicorn process。"""

    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12-slim\n")
    assert "RUN pip install --no-cache-dir -r requirements.txt" in dockerfile
    assert 'ISSUEOPS_DB_PATH=/app/data/issueops.db' in dockerfile
    assert 'VOLUME ["/app/data"]' in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert 'USER issueops' in dockerfile
    assert 'api.main:app' in dockerfile
    assert '"--host", "0.0.0.0"' in dockerfile
    assert '"--port", "8000"' in dockerfile
    assert "--workers" not in dockerfile
    assert "GITHUB_TOKEN=" not in dockerfile
    assert "COPY .env" not in dockerfile


def test_docker_healthcheck_uses_stdlib_without_extra_server_stack() -> None:
    """Healthcheck 不应为 curl 引入 OS 包或增加额外 Server。"""

    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "HEALTHCHECK" in dockerfile
    assert "urllib.request" in dockerfile
    assert "http://127.0.0.1:8000/health" in dockerfile
    assert "apt-get" not in dockerfile
    assert "gunicorn" not in dockerfile.casefold()
    assert "nginx" not in dockerfile.casefold()


def test_dockerignore_excludes_local_state_and_secrets() -> None:
    """Build Context 不得包含 Git、venv、Secret 或开发 SQLite。"""

    patterns = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert ".git" in patterns
    assert ".venv" in patterns
    assert ".env" in patterns
    assert "data/" in patterns
    assert "*.db" in patterns
    assert "*.sqlite" in patterns
    assert ".pytest_cache" in patterns
    assert "__pycache__" in patterns


def test_stage_does_not_add_compose_or_orchestration_files() -> None:
    """Stage 10 不得提前引入 Compose 或 Kubernetes artifacts。"""

    forbidden_names = {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
    root_names = {path.name.casefold() for path in PROJECT_ROOT.iterdir()}

    assert root_names.isdisjoint(forbidden_names)
    assert not any(PROJECT_ROOT.glob("*.helm"))
