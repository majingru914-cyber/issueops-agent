# Stage 10 Docker Deployment

## 架构

```text
Host
↓ TCP :8000
Docker Container
↓
Uvicorn 0.0.0.0:8000（single process）
↓
FastAPI api.main:app
↓
AgentService / asyncio.to_thread
↓
IssueOps Agent / ToolRuntime / LangGraph
↓
SQLite /app/data/issueops.db
↓
Docker named volume
```

Docker 只封装现有 HTTP Service，不复制或修改 Agent Pipeline。Container 默认只有
一个 Uvicorn process，与 Stage 09 的 background registry 和 SQLite 并发边界一致。

## Build

在仓库根目录执行：

```bash
docker build -t issueops-agent .
```

验收标签可以单独构建：

```bash
docker build -t issueops-agent:stage10 .
```

基础镜像为 `python:3.12-slim`。依赖只从现有 `requirements.txt` 安装，没有第二份
Container dependency list。

`.dockerignore` 排除 Git metadata、venv、Python cache、`.env`、开发 SQLite、
Evaluation 输出和测试目录。开发机的 `data/issueops.db` 不会进入 Build Context。

## Run

推荐使用 named volume，避免不同 Host 的 bind mount 路径和权限差异：

```bash
docker volume create issueops-data
docker run --name issueops-agent-a \
  -p 8000:8000 \
  -v issueops-data:/app/data \
  issueops-agent:stage10
```

Windows PowerShell 单行形式：

```powershell
docker run --name issueops-agent-a -p 8000:8000 -v issueops-data:/app/data issueops-agent:stage10
```

Container 使用 non-root `issueops` 用户。Docker 管理的空 named volume 会从 Image
中的 `/app/data` 初始化；使用 Host bind mount 时，Host 目录必须允许该用户写入。

## Environment

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ISSUEOPS_DB_PATH` | `/app/data/issueops.db` | SQLite 文件路径 |
| `GITHUB_TOKEN` | 未设置 | 可选，只读 GitHub API 认证 |

运行时注入示例：

```bash
docker run --rm -p 8000:8000 \
  -v issueops-data:/app/data \
  -e GITHUB_TOKEN=<runtime-secret> \
  issueops-agent:stage10
```

禁止在 `Dockerfile` 使用 `ENV GITHUB_TOKEN=...`，也不要把 `.env` 提交 Git 或复制
到 Image。自动测试不需要真实 Token，也不访问公网 GitHub。

## Health 与 Status

Deployment health：

```bash
curl http://127.0.0.1:8000/health
```

```json
{"status":"healthy","service":"issueops-agent"}
```

Application status：

```bash
curl http://127.0.0.1:8000/status
```

Image 的 `HEALTHCHECK` 使用 Python stdlib `urllib.request`，不额外安装 curl 或 OS
package。Health request 不运行 Agent、不请求 GitHub、不做复杂 SQLite 统计。

## Agent Smoke

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"查找项目中 AgentState 的定义\"}"
```

保存返回的 `task_id`，有限轮询：

```bash
curl http://127.0.0.1:8000/tasks/<task_id>
```

终态后查询 Trace：

```bash
curl "http://127.0.0.1:8000/trace?task_id=<task_id>"
```

非法输入仍应返回 HTTP `422`：

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"\"}"
```

## Volume Persistence 验证

1. 使用 `issueops-agent-a` 和 `issueops-data` 启动 Container A。
2. 创建任务，轮询到 `completed` 并记录 `task_id`。
3. 查询并记录非空 Trace。
4. 执行 `docker stop issueops-agent-a` 和 `docker rm issueops-agent-a`。
5. 使用同一 `issueops-data` 创建 Container B：

```bash
docker run --name issueops-agent-b \
  -p 8000:8000 \
  -v issueops-data:/app/data \
  issueops-agent:stage10
```

6. 使用原 `task_id` 查询 `/tasks/{task_id}` 和 `/trace`。

任务状态、最终回答和 Trace 都存在，才证明 Container lifecycle 与 Agent
persistence lifecycle 已解耦。

## Shutdown 与 Logs

```bash
docker stop issueops-agent-a
docker logs issueops-agent-a
```

Uvicorn 收到停止信号后进入 FastAPI lifespan shutdown；Service 等待已受理的后台
任务收尾，再关闭共享 `GitHubClient`。强制终止或 Host 崩溃不保证运行中任务完成，
且 Stage 10 不提供自动恢复。

日志应包含 Uvicorn startup、listening 和结构化 task 事件，不应出现 Token、
Authorization、`.env` 内容或未处理 traceback。

## Secret 与 Image 检查

构建后建议执行：

```bash
docker history --no-trunc issueops-agent:stage10
docker inspect issueops-agent:stage10
docker run --rm issueops-agent:stage10 sh -c "test ! -f /app/.env"
```

检查 Image config 与 filesystem 中不存在真实 `GITHUB_TOKEN`、API Key、Credential、
Authorization 或 `.env`。`ISSUEOPS_DB_PATH` 是非敏感运行配置，可以存在于 Image
Environment。

## Troubleshooting

- `docker` 命令不存在：安装并启动 Docker Engine 或 Docker Desktop，然后重新打开
  terminal 使 CLI 进入 PATH。
- 无法连接 daemon：确认 Docker Desktop/Engine 已启动，并执行 `docker version`。
- Host 端口被占用：将 `-p 8000:8000` 的左侧改为其他端口，例如
  `-p 8001:8000`。
- SQLite `permission denied`：优先使用 named volume；若使用 bind mount，修正 Host
  目录权限，使 Container 内 non-root 用户可以写入。
- Windows bind mount：使用 Docker Desktop 接受的绝对路径语法；named volume 不受
  Host 路径格式影响。
- 首次 build 拉取基础镜像失败：检查 registry 网络或代理。这是 Docker
  infrastructure 依赖，不是 Agent runtime 的公网依赖。

## 已知限制

- 仅支持单 Uvicorn process，不支持 multi-worker 或 horizontal scaling；
- Container 停止时运行中的任务不会在新 Container 自动续跑；
- 同步 Agent 使用线程池，高并发时可能出现 thread pool saturation；
- SQLite 适合当前单机 MVP，不提供多进程协调；
- Image 未做 multi-stage 或极限体积优化；
- 不包含 Compose、Kubernetes、Redis、Celery、Nginx 或 Cloud Deployment。
