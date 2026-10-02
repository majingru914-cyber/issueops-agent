# IssueOps Agent 工作清单

## 已完成

- Stage 00：完成仓库初始化、基础依赖、工程规则和冒烟测试。
- Stage 01：完成最小 `AgentState`、结构化模型、`analyze_task`、
  `create_plan`、LangGraph 编译调用、CLI 和失败路径测试。
- Stage 02：完成统一 `BaseTool`、`ToolResult`、`ToolRegistry`、
  `ToolRuntime`、workspace 路径边界，以及 `list_directory`、`read_file`、
  `search_code`。
- Stage 03：完成共享 `GitHubClient`、`get_github_issue`、`get_github_pr`、
  可选环境认证、HTTP timeout、rate-limit 检测和 GitHub API 错误映射。
- Stage 04：完成可执行 `PlanStep`、Executor、结构化 Tool Call / Result、
  Evidence、Error、条件步骤循环和基于证据的最终回答。
- Stage 05：完成统一错误分类、`retryable` Contract、有限 Retry、通用 Tool
  timeout、确定性一级 Fallback、attempt trace、`MAX_TOOL_CALLS` 和结构化日志。
- Stage 06：完成结构化 Reviewer、Draft/Final 分离、Reflection、增量 Re-plan、
  `MAX_REFLECTIONS`、Review history 和完整核心 Agent 闭环。
- Stage 07：完成 Working Memory 边界、`SQLiteTaskStore`、任务生命周期、状态快照、
  execution trace、重启查询、CLI 自动持久化和 `--load-task`。
- Stage 08：完成独立评测层、20 用例版本化数据集、离线 Fixture、自动评分、
  聚合指标、失败分类、JSON/Markdown 报告和可重复性验证。
- Stage 08 Git 边界：`main` 已 fast-forward 到 `ccf4780`，Stage 09 开始前
  136 项基线测试通过，correctness 指标保持既有结果。
- Stage 09：完成 FastAPI application factory、HTTP Schema、`AgentService`、
  `POST /tasks`、`GET /tasks/{task_id}`、`GET /status`、`GET /trace`、
  同步 Runner 的线程卸载、SQLite 查询、并发隔离、后台异常边界和 API 测试。
- Stage 09 Git 边界：`main` 已通过 `ff-only` 合并到 `d96bd44`，合并后
  146 项测试通过，Evaluation correctness baseline 保持 19/20。
- Stage 10：实现 `Dockerfile`、`.dockerignore`、non-root 单进程 Uvicorn、
  `/health`、`/app/data` SQLite Volume、runtime environment 注入和 Docker
  packaging contract 测试；Docker Engine E2E 验证以实际执行结果为准。

## 当前边界

当前可运行链路为：

```text
START
→ analyze_task
→ create_plan
→ execute_step
  → ToolRuntime Validation / Timeout / Retry / Fallback
→ collect_evidence
→ more_steps?
├─ Yes → execute_step
├─ Budget Exhausted → tool_budget_exceeded
└─ No → generate_draft_answer
          → review_answer
          → review_passed?
             ├─ Yes → finalize_answer → END
             └─ No → reflect
                       → replan
                       ├─ New Step → execute_step
                       ├─ Tool Budget Exhausted → finalize_answer → END
                       └─ No New Step → generate_draft_answer
```

Planner 通过 `tool_name` 和 `tool_args` 决定 logical Tool call，Executor 只负责
向现有 `ToolRuntime.execute()` 传递当前步骤和剩余预算。Runtime 是 Retry、
Timeout 与 Fallback 的唯一权威实现，每次 Retry 仍属于同一 PlanStep。

独立 Tool System 链路为：

```text
Tool Request
→ ToolRuntime
→ ToolRegistry
→ BaseTool
→ Pydantic Args Schema
→ Execute Attempt with Timeout
→ Error Classification
→ Retry / Fallback Policy
→ ToolResult
```

最终成功 ToolResult 进入 Evidence，终态失败 ToolResult 进入 Errors。所有实际
Attempt 进入 `execution_attempts`，并计入 `tool_call_count`；达到
`MAX_TOOL_CALLS` 时 Graph 记录错误，禁止任何新增 Tool execution，并通过 Review
或明确降级路径安全形成 Final Answer。

Reviewer 检查 Goal Completion、Evidence Completeness、关键 Error、Plan Completion
和 Answer Grounding。Review Fail 后，Reflection 只分析缺口，Re-plan 只追加缺失
`PlanStep`；旧 Evidence、ToolResult、ToolCall、Error 和 attempt trace 均保留。

当前默认 Registry 包含：

```text
list_directory
read_file
search_code
get_github_issue
get_github_pr
```

GitHub Tool 当前只读，自动化测试全部使用 Mock HTTP。

默认可靠性边界：

```text
max_retries = 2
timeout_seconds = 10
max_tool_calls = 20
max_reflections = 2
```

`retry_count` 统计同一 Tool Step 的 Runtime Retry；`reflection_count` 统计
Review Fail 后的推理与增量 Re-plan，两者完全分离。

Stage 07 不修改上述推理状态契约。`AgentState` 仍是唯一权威 Working Memory；
`AgentRunner` 在任务开始时生成稳定 `task_id`，`TaskRecorder` 只观察节点 update，
并通过统一 `SQLiteTaskStore` 写入：

```text
tasks
state_snapshots ORDER BY sequence
execution_traces ORDER BY sequence
```

任务状态为：

```text
created → running → completed | partial | failed
```

默认 CLI 数据库为 `data/issueops.db`，可使用 `--database` 或
`ISSUEOPS_DB_PATH` 覆盖。Persistent Memory 关闭时，Agent 推理与最终结果语义保持
不变。

Stage 08 评测代码仅位于 `eval/`，通过现有 `run_agent` 注入点运行生产
Agent，并在运行结束后读取最终 `AgentState`。数据集严格包含：

```text
repository = 8
github = 4
reliability = 4
reflection = 4
```

GitHub 用例使用 `httpx.MockTransport`，不访问公网。当前代表性报告为
20 个用例通过 19 个；`repo-007` 保留了 `EXECUTION_FAILED` 与预期
`INVALID_ARGUMENT` 的真实分类差异，未因评测结果修改 Production Agent。

Stage 09 的 HTTP 层不复制 Agent Pipeline。外部仅提交 `query`，服务先创建唯一
`task_id` 并写入 `running`，再通过：

```text
FastAPI
→ AgentService
→ asyncio.create_task
→ asyncio.to_thread(run_agent)
→ LangGraph / ToolRuntime
→ SQLiteTaskStore
```

执行现有单 Agent。进程内 registry 只保存正在运行的 `asyncio.Task` 引用；任务、
结果与 trace 的持久化来源仍是 SQLite。每个后台 worker 和 HTTP 查询使用独立
SQLite connection，满足单进程并发边界。运行中进程退出后的任务恢复、跨进程
协调、Authentication、分页和分布式 Worker 不属于 Stage 09。

Stage 10 只封装现有 `api.main:app`：

```text
Host :8000
→ Docker Container
→ Uvicorn 0.0.0.0:8000（single process）
→ FastAPI / AgentService
→ IssueOps Agent
→ /app/data/issueops.db
→ Docker named volume
```

Container 使用 non-root `issueops` 用户。`.env`、开发 SQLite、Git metadata、venv
和 cache 均不进入 Build Context；`GITHUB_TOKEN` 只允许通过 `docker run -e` 或
`--env-file` 在 runtime 注入。`/health` 只表达 deployment health，`/status` 继续
表达 application task statistics。

## 下一阶段

- Stage 11：尚未开始，等待后续规格。

当前没有实现 Docker Compose、Kubernetes、Redis、Celery、分布式 Worker、
Nginx、Cloud Deployment、Frontend、Authentication、GitHub 写操作或 Multi-Agent。Reviewer 与
Reflection 均不直接执行 Tool；Stage 05 Retry 语义未被 Stage 06 Reflection、
Stage 07 Persistence、Stage 09 HTTP Service 或 Stage 10 Docker Packaging 改变。
