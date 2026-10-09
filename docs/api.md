# Stage 09 HTTP API

## 架构

Stage 09 只增加 transport / service layer，不复制 Analyzer、Planner、Executor、
Reviewer、Reflection、Tool Runtime 或 Memory：

```text
Client
→ HTTP
→ FastAPI
→ AgentService
→ asyncio.create_task
→ asyncio.to_thread(run_agent)
→ LangGraph Agent
→ ToolRuntime
→ SQLiteTaskStore
→ HTTP Query
```

`AgentState` 仍是运行时权威状态，SQLite 仍是任务摘要、状态快照和 execution
trace 的唯一持久化来源。进程内 `dict[task_id, asyncio.Task]` 只用于管理当前
process 的后台 coroutine，不构成第二套 Memory。

## Application 生命周期

`api.main.create_app()` 支持注入：

- 临时 SQLite 路径；
- workspace 根目录；
- `ToolRuntime`；
- 同步 Runner；
- Runtime 关闭回调。

FastAPI lifespan 在 startup 初始化 SQLite Schema，在 shutdown 等待当前已受理任务
收尾并关闭默认 `GitHubClient`。默认数据库由 `ISSUEOPS_DB_PATH` 指定，未设置时为
`data/issueops.db`。

SQLite connection 不跨线程共享。提交、查询和每个后台 Agent worker 都创建并关闭
自己的 `SQLiteTaskStore`，以符合 `sqlite3` thread affinity，并支持 Stage 09 的
single-process 并发任务。

## Task 生命周期

服务复用 Stage 07 状态：

```text
created → running → completed
                  → partial
                  → failed
```

`POST /tasks` 在返回前创建任务并写入 `running`。后台 Runner 使用显式
`task_precreated=True` 复用同一个 `task_id`，不会生成第二个 API 专用 ID。

Stage 09 不恢复进程退出时仍处于 `running` 的任务。已完成并写入 SQLite 的任务在
application 重启后仍可查询。

## Endpoint

### `GET /health`

返回 HTTP `200`：

```json
{
  "status": "healthy",
  "service": "issueops-agent"
}
```

该接口只用于 deployment health，不运行 Agent、不请求 GitHub，也不执行复杂数据库
统计。`GET /status` 继续负责 application task statistics。

### `POST /tasks`

Request：

```json
{
  "query": "查找项目中 AgentState 的定义"
}
```

`query` 会去除首尾空白，不能为空，最大长度为 10000 字符；未知字段被拒绝。
Client 不能提交 `plan`、`tool_calls`、Review 或 Reflection 等内部状态。

成功响应为 HTTP `202 Accepted`：

```json
{
  "task_id": "7df5d6f51700411b8e3b721583d864b3",
  "status": "running",
  "created_at": "2026-10-01T08:00:00.000Z"
}
```

请求只等待初始持久化与后台调度，不等待完整 Agent 执行。

### `GET /tasks/{task_id}`

存在任务返回 HTTP `200`。运行中 `final_answer`、`review_passed` 可为 `null`：

```json
{
  "task_id": "7df5d6f51700411b8e3b721583d864b3",
  "query": "查找项目中 AgentState 的定义",
  "status": "running",
  "created_at": "2026-10-01T08:00:00.000Z",
  "updated_at": "2026-10-01T08:00:00.001Z",
  "final_answer": null,
  "review_passed": null,
  "reflection_count": 0,
  "retry_count": 0,
  "tool_call_count": 0
}
```

终态响应使用同一结构，附带最终回答和计数。内部完整 `AgentState` 不通过此接口
公开。

### `GET /trace?task_id=<task_id>`

存在任务返回 HTTP `200`：

```json
{
  "task_id": "7df5d6f51700411b8e3b721583d864b3",
  "events": [
    {
      "sequence": 1,
      "event_type": "task_started",
      "step_id": null,
      "payload": {"status": "running"},
      "created_at": "2026-10-01T08:00:00.010Z"
    }
  ]
}
```

`events` 直接来自 Stage 07 `execution_traces`，按 `sequence ASC` 返回。存在但尚未
写入事件的任务可返回空 `events`；不存在任务返回 `404`。

### `GET /status`

返回 HTTP `200`：

```json
{
  "status": "ok",
  "service": "issueops-agent",
  "active_tasks": 1,
  "completed_tasks": 10,
  "partial_tasks": 1,
  "failed_tasks": 1,
  "total_tasks": 13
}
```

`active_tasks` 来自当前进程的 background task registry；其余计数来自 SQLite。
该接口表达 Agent Service 状态，不替代 Stage 10 的 `/health` deployment endpoint。

## Async 模型

路由为 `async def`。受理流程为：

1. 生成一次 `task_id`；
2. 持久化任务并标记 `running`；
3. 使用 `asyncio.create_task()` 保存后台 coroutine 引用；
4. 使用 `asyncio.to_thread()` 在线程池调用同步 `run_agent()`；
5. Runner 写入状态快照、trace 和终态；
6. coroutine 在 `finally` 中移除进程内引用。

后台边界捕获并消费未处理异常。若注入 Runner 未自行写入失败状态，Service 会将
任务标记为 `failed`，并仅持久化异常类型，不持久化异常消息或 stack trace。

## Error Contract

稳定 HTTP 错误结构为：

```json
{
  "detail": {
    "code": "TASK_NOT_FOUND",
    "message": "任务不存在：unknown"
  }
}
```

| 场景 | HTTP status | code |
| --- | ---: | --- |
| Pydantic 请求校验失败 | 422 | `INVALID_REQUEST` |
| 任务不存在 | 404 | `TASK_NOT_FOUND` |
| SQLite 服务边界失败 | 500 | `INTERNAL_ERROR` |

Tool 层 `ErrorCode` 不直接用作 HTTP API Error Code。Client 响应不包含绝对路径、
SQL、stack trace、Token 或 Authorization 内容。

## 已知限制

- background task registry 仅存在于单个 process；运行中进程退出不会自动恢复；
- SQLite 未提供多进程 sequence 协调，Stage 09 只支持 single-process Uvicorn；
- 同步 Agent 共用默认线程池，高并发下可能发生 thread pool saturation；
- Python 无法强制终止已经超时但仍在执行的同步 Tool thread；
- `GET /trace` 未分页，大型 trace 会形成较大响应；
- 未实现 Authentication、CORS policy system、rate limiting 或公网部署保护；
- 未实现 Redis、Celery、WebSocket、Frontend 或 Multi-Agent。
