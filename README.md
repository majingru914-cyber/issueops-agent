# IssueOps Agent

## 项目概述

IssueOps Agent 是一个基于 Python 和 LangGraph 的软件研发任务自主处理
Agent。项目最终将支持任务分析、仓库检查、工具执行、证据收集、审查、
反思和重新规划。

当前仓库已经实现完整的单 Agent 核心闭环与 SQLite Persistent Memory。Planner
生成结构化 Tool 调用，Executor 通过统一 ToolRuntime 执行本地 Repository Tool
和只读 GitHub Tool；Evidence 形成 Draft Answer 后，由确定性 Reviewer 判断完成度。
Review Fail 会进入 Reflection，并由 Re-plan 只追加缺失步骤后重新执行。运行时
`AgentState` 仍是唯一权威 Working Memory，SQLite 只保存任务、状态快照和执行
trace 的持久化副本。独立的 Stage 08 离线评测基准使用 20 个版本化用例
衡量任务、Tool、Retry、Reflection 和 Recovery 行为。Stage 09 通过 FastAPI、
`AgentService` 和 `asyncio.to_thread()` 将同一 Agent Runner 暴露为异步 HTTP
任务服务，任务结果与 trace 仍以 SQLite 为持久化来源。Stage 10 使用
`python:3.12-slim`、单进程 Uvicorn 和 `/app/data` Volume 提供可部署的 Docker
运行形态。

## 项目目标

构建一个可靠、可在本地运行且可评估的软件研发 Agent，并保持架构清晰、
行为可验证。

## 核心链路

完整规划链路如下：

```text
Analyze
→ Plan
→ Execute
→ Evidence
→ Generate
→ Review
→ Reflect
→ Re-plan
→ Final
```

当前 LangGraph 链路为：

```text
User
→ Analyze
→ Plan
→ Execute Tool
→ Validation
→ Retry / Timeout / Fallback
→ Collect Evidence
→ More Steps?
├─ Yes → Execute Tool
├─ Budget Exhausted → Record Error
└─ No → Generate Draft Answer
          → Reviewer
          → Passed?
             ├─ Yes → Final Answer
             └─ No → Reflection
                       → Re-plan
                       → Execute Tool
```

Graph 使用条件边逐步执行有限计划，并分别受到 `MAX_RETRIES`、
`MAX_TOOL_CALLS` 和 `MAX_REFLECTIONS` 保护。最终成功的 ToolResult 进入
Evidence，终态失败进入 Errors；只有 Review Pass 或 Reflection 达到上限时才会
形成 Final Answer。

当前 Tool System 链路为：

```text
Tool Request
→ ToolRuntime
→ ToolRegistry
→ BaseTool
→ Pydantic Args Schema
→ Execute Attempt with Timeout
→ Error Classification
→ Retry Policy
├─ Retry Same Step
├─ Deterministic Fallback
└─ Return
→ ToolResult
```

当前已注册的 Tool 类型为：

```text
               ┌→ Repository Tools
ToolRuntime ────┤
               └→ GitHub Tools → GitHubClient → GitHub REST API
```

Planner 与 Tool System 已通过 Executor 正式连接，但 ToolRuntime 仍保持独立、
可单独测试。

## 当前状态

**Current Status: Stage 10 — Docker Deployment**

当前已实现：

- 使用 `TypedDict` 定义的最小 `AgentState`；
- 使用 Pydantic 定义的 `TaskAnalysis`、`PlanStep` 和 `TaskPlan`；
- 确定性的 `analyze_task` 和 `create_plan` 节点；
- 基于真实 `StateGraph` 的节点、边、编译与调用；
- 输出结构化 JSON 的 CLI；
- 空输入与缺失参数的明确错误处理；
- 统一的 `BaseTool`、`ToolRegistry`、`ToolRuntime` 和 `ToolResult`；
- Pydantic Tool 输入 Schema 与可发现 metadata；
- 受 workspace 路径边界保护的 `list_directory`、`read_file`、
  `search_code`；
- 共享同一个 `GitHubClient` 的 `get_github_issue` 和 `get_github_pr`；
- GitHub Bearer/匿名只读请求、明确 HTTP timeout、rate-limit 检测和稳定错误映射；
- 包含 `tool_name` 和 `tool_args` 的可执行 `PlanStep`；
- 结构化 Tool Call / Tool Result 记录；
- `execute_step`、`collect_evidence`、条件循环和 `generate_answer` 节点。
- 统一 `ErrorCode` 和带 `retryable` 的 `ToolResult`；
- `ReliabilityPolicy` 对 `max_retries`、`timeout_seconds` 和
  `max_tool_calls` 设置可配置值与硬上限；
- 同一 PlanStep 内的有限 Retry，以及 `MAX_RETRIES_EXCEEDED` 终态；
- 跨平台可测试的同步 Tool wall-clock timeout；
- 由显式 Tool 映射和允许错误码驱动的一级 Fallback；
- 区分 logical Tool call 与实际 execution attempt 的完整 trace；
- `MAX_TOOL_CALLS` Graph 终止保护；
- 不记录 Tool arguments 或环境变量的结构化 `key=value` 日志。
- 明确区分 `draft_answer` 与 `final_answer`；
- 结构化 `ReviewResult`，检查 Goal、Evidence、关键错误、Plan 与 Draft grounding；
- `REVIEW_PASS_THRESHOLD = 0.8` 的唯一确定性 Review 阈值；
- 结构化 `ReflectionResult` 与可观察的 Review / Reflection history；
- 复用 `PlanStep` 的增量 Re-plan，并保留全部旧 Evidence、Error 与 trace；
- `MAX_REFLECTIONS = 2` 默认推理循环上限；
- Review Pass、Reflection Recovery、Reflection Exhaustion 和 Tool Budget 交互路径。
- 以 `AgentState` 为唯一权威状态的 Working Memory；
- 标准库 `sqlite3` 实现的 `SQLiteTaskStore`，数据库路径可配置；
- `tasks`、`state_snapshots`、`execution_traces` 三表及稳定 sequence 索引；
- `created`、`running`、`completed`、`failed`、`partial` 任务状态；
- 节点级状态快照，以及 Tool、Retry、Fallback、Review、Reflection、Re-plan trace；
- JSON-only 序列化、显式损坏 JSON 错误和敏感键值脱敏；
- 关闭并重开 Store 后的任务、最新状态、历史和 trace 查询；
- CLI 默认写入 `data/issueops.db`，并支持 `--load-task` 检查历史任务。
- 严格版本化的 20 用例评测数据集，分类固定为 8/4/4/4；
- 与 Production Agent 分离的 Pydantic 评测 Schema、评分器和指标计算；
- 固定 Repository Fixture 与基于 `httpx.MockTransport` 的离线 GitHub Fixture；
- 用例级异常隔离、失败分类、JSON/Markdown 报告与失败用例文档；
- 任务成功率、用例通过率、Tool 选择/参数准确率、延迟、Retry、
  Reflection、Recovery 和可靠性事件指标。
- FastAPI application factory 与独立的 Pydantic HTTP Schema；
- `POST /tasks` 异步受理、`GET /tasks/{task_id}` 结果查询、`GET /trace`
  执行证据查询和 `GET /status` 服务状态；
- `asyncio.create_task()` 管理进程内后台生命周期，`asyncio.to_thread()`
  桥接现有同步 `run_agent()`；
- API、AgentState、SQLite task 和 execution trace 全程复用同一 `task_id`；
- 每个后台执行和查询使用独立 SQLite connection，支持单进程并发任务隔离；
- 稳定的 `INVALID_REQUEST`、`TASK_NOT_FOUND` 和 `INTERNAL_ERROR` HTTP 错误边界。
- 基于 `python:3.12-slim` 的 non-root Docker Image 与单 Uvicorn process；
- 轻量 `GET /health` deployment health endpoint 和 stdlib Docker HEALTHCHECK；
- `/app/data/issueops.db` 默认容器数据库路径与 named volume 持久化设计；
- 排除 `.git`、`.venv`、`.env`、SQLite 和测试缓存的最小 Build Context。

Planner 是 Tool 选择和参数的权威来源；Executor 不从自然语言重新猜测 Tool，
也不实现 Retry loop。Retry 与 Fallback 只存在于唯一的 `ToolRuntime.execute()`
入口；Retry 只重试同一 PlanStep，绝不等同于 Re-plan。

默认可靠性配置为：

```text
max_retries = 2
timeout_seconds = 10
max_tool_calls = 20
```

`INVALID_ARGUMENT`、`TOOL_NOT_FOUND`、`FILE_NOT_FOUND`、
`GITHUB_AUTH_ERROR` 和 `GITHUB_NOT_FOUND` 不可重试；`TIMEOUT`、
`RATE_LIMIT` 与临时 `GITHUB_API_ERROR` 可重试。Retry 耗尽后返回
`MAX_RETRIES_EXCEEDED`，并通过 `last_error_code` 保留最后原始错误。

三个硬限制职责不同：

```text
MAX_RETRIES     = 同一 Tool Step 的临时失败重试上限
MAX_TOOL_CALLS  = 单次 Agent 运行的实际 Tool attempt 总预算
MAX_REFLECTIONS = Review Fail 后的 Reflection / Re-plan 上限
```

Reviewer 和 Reflection 不调用 ToolRuntime；Re-plan 也不执行 Tool，只生成现有
`PlanStep` Contract。所有新增步骤仍由 Executor 和唯一 ToolRuntime 执行。

Persistent Memory 位于核心闭环外围：

```text
User Request
→ AgentRunner 生成 task_id 并创建任务
→ LangGraph / AgentState（唯一权威运行时状态）
   ├─ 节点 update 原样返回 Graph
   └─ TaskRecorder → SQLiteTaskStore
                     ├─ tasks
                     ├─ state_snapshots
                     └─ execution_traces
→ Final Answer
→ completed / partial；未处理异常 → failed
```

启用或禁用 Store 不会改变 Analyze、Plan、Execute、Review、Reflection 或 Re-plan
的节点输入、输出和路由。`task_id` 在 `AgentRunner` 启动时生成，Retry、Fallback、
Reflection 和 Re-plan 全程复用同一个值。

HTTP 服务链路为：

```text
Client
→ FastAPI
→ AgentService
→ asyncio.create_task
→ asyncio.to_thread(run_agent)
→ LangGraph / ToolRuntime
→ SQLiteTaskStore
→ HTTP Query
```

GitHub Tool 仅执行读取操作，不会修改 Issue、发表评论、创建 PR 或写入仓库。

## 项目结构

```text
issueops-agent/
├── agent/
│   ├── analyzer.py     # 任务分析节点
│   ├── evidence.py     # ToolResult 到 Evidence / Error
│   ├── executor.py     # 通过 ToolRuntime 执行 PlanStep
│   ├── generator.py    # 基于 Evidence 生成回答
│   ├── graph.py        # LangGraph 构建与编译
│   ├── parsing.py      # GitHub 引用结构提取
│   ├── planner.py      # 任务规划节点
│   ├── reflection.py   # Reflection 与次数上限
│   ├── replanner.py    # 增量 Re-plan
│   ├── reviewer.py     # 确定性 Reviewer
│   ├── runner.py       # 任务生命周期与可选持久化协调
│   ├── schemas.py      # Pydantic 结构化模型
│   └── state.py        # LangGraph 运行时状态
├── api/
│   ├── main.py         # FastAPI application factory 与路由
│   ├── schemas.py      # HTTP Request / Response Schema
│   └── service.py      # 异步任务、Runner bridge 与查询服务
├── docs/               # 项目文档
├── eval/
│   ├── dataset.json    # 20 个版本化评测用例
│   ├── evaluator.py    # 用例执行与 CLI
│   ├── fixtures/       # Repository 与 GitHub 固定 Fixture
│   ├── metrics.py      # 聚合指标
│   ├── reporting.py    # JSON、Markdown 和失败文档
│   ├── schemas.py      # Pydantic 评测 Schema
│   └── scoring.py      # 最终 AgentState 自动评分
├── examples/           # 后续阶段使用
├── memory/
│   ├── recorder.py     # Graph update 到快照与 trace 的投影
│   ├── schemas.py      # Task、Snapshot 与 Trace model
│   └── sqlite_store.py # SQLite Schema、事务与查询
├── tests/              # 自动化测试
├── tools/
│   ├── base.py         # BaseTool 与 ToolResult
│   ├── filesystem.py   # list_directory 与 read_file
│   ├── github.py       # get_github_issue 与 get_github_pr
│   ├── github_client.py # GitHub REST Client
│   ├── github_errors.py # GitHub 领域错误
│   ├── path_utils.py   # 共享 workspace 路径边界
│   ├── registry.py     # Tool 注册与发现
│   ├── reliability.py  # 错误码与可靠性策略
│   ├── repository.py   # search_code
│   └── runtime.py      # 统一执行入口与默认构建器
├── main.py             # CLI 入口
└── WORK_TODO.md        # 阶段状态与开发边界
```

## 环境要求

- Python 3.12 或更高版本
- `venv`
- `pip`
- `httpx`
- `fastapi`
- `uvicorn`

## 安装

创建虚拟环境：

```bash
python -m venv .venv
```

在 Windows PowerShell 中激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

在 macOS 或 Linux 中激活：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

## 使用方法

运行 Plan-and-Execute 工作流：

```bash
python main.py "分析项目结构"
```

运行成功后默认写入：

```text
data/issueops.db
```

可使用参数或环境变量覆盖数据库路径：

```bash
python main.py --database local/memory.db "分析项目结构"
```

```text
ISSUEOPS_DB_PATH=local/memory.db
```

按输出中的 `task_id` 检查持久化任务：

```bash
python main.py --load-task <task_id>
```

该命令返回 Task metadata、最新 State、按 sequence 排列的 State history 和
execution trace；未知任务返回明确的非零退出码。

CLI 会输出包含以下字段的 JSON：

- `task_type`
- `task_id`
- `goal`
- `required_capabilities`
- `plan`
- `tool_calls`
- `tool_results`
- `tool_call_count`
- `retry_count`
- `execution_attempts`
- `evidence`
- `errors`
- `draft_answer`
- `review_score`
- `review_passed`
- `review`
- `reflection_count`
- `reflection`
- `replan_count`
- `final_answer`

执行本地多步骤场景：

```bash
python main.py "查找项目中 AgentState 的定义"
```

独立构建 Tool Runtime：

```python
from pathlib import Path

from tools import build_tool_runtime

runtime = build_tool_runtime(Path.cwd())
result = runtime.execute("read_file", {"path": "README.md"})
```

所有正式 Tool 调用都返回 `ToolResult`。每次实际 Attempt 保存 `attempt`、
`task_id`、`step_id`、`tool_name`、`arguments`、`phase`、`success`、
`error_code` 和 `latency_ms`；
日志不会输出 `arguments`。用户路径必须是 workspace 内的相对路径；绝对路径
和包含 `..` 的路径会被拒绝。

可在测试或调用端注入可靠性策略：

```python
from tools import ReliabilityPolicy, build_tool_runtime

policy = ReliabilityPolicy(
    max_retries=2,
    timeout_seconds=10,
    max_tool_calls=20,
    fallbacks={"primary_tool": "fallback_tool"},
)
runtime = build_tool_runtime(Path.cwd(), policy=policy)
```

Fallback 只执行一级，并且默认只允许 `TOOL_NOT_FOUND` 或
`EXECUTION_FAILED` 触发；生产默认没有配置任何 Fallback Tool 映射。

读取公开 GitHub 资源时，`GITHUB_TOKEN` 是可选配置。未设置 Token 时使用
GitHub 匿名只读请求；设置后以 Bearer header 发送。Token 只从环境变量读取：

请在运行进程的环境中通过组织认可的密钥管理方式设置 `GITHUB_TOKEN`，不要
把实际值写入仓库文件或命令示例。

通过同一个 Runtime 调用 GitHub Tool：

```python
result = runtime.execute(
    "get_github_issue",
    {"owner": "octocat", "repo": "Hello-World", "issue_number": 1},
)
```

自动化测试使用 `httpx.MockTransport`，不访问公网，也不要求真实 Token。

## API

本地启动 HTTP 服务：

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

创建任务会在 SQLite 中预先写入唯一 `task_id`，以 HTTP `202 Accepted` 快速
返回 `running`；完整 Agent 在后台线程中继续执行：

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"查找项目中 AgentState 的定义\"}"
```

查询任务状态和过滤后的最终结果：

```bash
curl http://127.0.0.1:8000/tasks/<task_id>
```

查询 Stage 07 持久化的执行 trace：

```bash
curl "http://127.0.0.1:8000/trace?task_id=<task_id>"
```

查询当前单进程服务状态：

```bash
curl http://127.0.0.1:8000/status
```

部署层健康检查：

```bash
curl http://127.0.0.1:8000/health
```

`POST /tasks` 仅接受 `query`，拒绝 Agent 内部 `plan`、`tool_calls`、Review 或
Reflection 字段。已完成任务在 application 重启后仍可通过相同 SQLite 文件查询；
运行中任务的跨进程恢复不属于 Stage 09。完整 Contract 见 `docs/api.md`。

## Docker

构建默认镜像：

```bash
docker build -t issueops-agent .
```

创建 named volume 并启动单进程服务：

```bash
docker volume create issueops-data
docker run --rm --name issueops-agent \
  -p 8000:8000 \
  -v issueops-data:/app/data \
  issueops-agent
```

Windows PowerShell 可使用单行命令：

```powershell
docker run --rm --name issueops-agent -p 8000:8000 -v issueops-data:/app/data issueops-agent
```

验证 deployment health：

```bash
curl http://127.0.0.1:8000/health
```

预期响应：

```json
{"status":"healthy","service":"issueops-agent"}
```

创建并查询任务：

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"查找项目中 AgentState 的定义\"}"
curl http://127.0.0.1:8000/tasks/<task_id>
curl "http://127.0.0.1:8000/trace?task_id=<task_id>"
```

Container 默认设置 `ISSUEOPS_DB_PATH=/app/data/issueops.db`。可选的只读 GitHub
认证只允许在运行时注入：

```bash
docker run --rm -p 8000:8000 \
  -v issueops-data:/app/data \
  -e GITHUB_TOKEN=<runtime-secret> \
  issueops-agent
```

也可以使用本地且不提交 Git 的 `.env`：

```bash
docker run --rm -p 8000:8000 \
  -v issueops-data:/app/data \
  --env-file .env \
  issueops-agent
```

不要把 Secret 写入 `Dockerfile`、Image 或已提交文件。删除并重新创建 Container
时，只要继续挂载同一 `issueops-data` Volume，已完成任务、最终回答和 trace 仍可
查询。详细设计、持久化验证步骤和排障见 `docs/docker.md`。

## Persistent Memory

`SQLiteTaskStore` 的主要接口为：

```python
from memory import SQLiteTaskStore, TaskStatus

with SQLiteTaskStore("data/issueops.db") as store:
    store.create_task(task_id, user_query)
    store.save_task(task_id, state, TaskStatus.RUNNING)
    store.save_state(task_id, "planned", state)
    store.save_trace(task_id, "review", review_payload)
    task = store.load_task(task_id)
    latest_state = store.load_latest_state(task_id)
    history = store.list_state_history(task_id)
    trace = store.list_trace(task_id)
```

数据库 Schema：

| Table | 主要列 | Key / Index |
| --- | --- | --- |
| `tasks` | `task_id`, `user_query`, `task_type`, `goal`, `status`, `final_answer`, Review/Retry/Reflection/Tool 计数、时间戳 | `task_id` 主键 |
| `state_snapshots` | `task_id`, `sequence`, `stage`, `state_json`, `created_at` | `(task_id, sequence)` 唯一约束和索引 |
| `execution_traces` | `task_id`, `sequence`, `event_type`, `step_id`, `payload_json`, `created_at` | `(task_id, sequence)` 唯一约束和索引 |

状态历史与 trace 均按 sequence 排序，不依赖时间戳猜测先后。典型状态阶段包括
`created`、`analyzed`、`planned`、`executed`、`evidence_collected`、`drafted`、
`reviewed`、`reflected`、`replanned` 和 `finalized`。

持久化边界只接受 JSON-safe 数据，不使用 pickle。`token`、`secret`、`password`、
`authorization`、`credential` 和 `api_key` 等敏感键会在写入前替换为
`[REDACTED]`，常见 Bearer 与 GitHub Token 字符串也会脱敏。SQLite 文件、WAL/SHM
旁文件和其他本地数据库格式已加入 `.gitignore`。

## Agent Evaluation Benchmark

运行完整离线基准评测：

```bash
python -m eval.evaluator
```

调试单个用例：

```bash
python -m eval.evaluator --case repo-001
```

默认生成 `eval/reports/evaluation-report.json`、
`eval/reports/evaluation-report.md` 和 `docs/failure_cases.md`。GitHub 用例全部
使用 `httpx.MockTransport`，运行时不访问公网，也不需要
`GITHUB_TOKEN`。

当前基线为 20 个用例通过 19 个，用例通过率 95%，正常任务成功率、
Tool 选择准确率和 Tool 参数准确率均为 100%。失败用例
`repo-007` 暴露了路径边界错误分类与数据集期望不一致，Stage 08 保留该真实
差异，未修改 Production Agent。详细设计、指标分母和局限见
`docs/evaluation.md`。

## 测试

在仓库根目录运行：

```bash
python -m pytest -v
```

## 开发路线

- Stage 00：仓库初始化；
- Stage 01：最小 LangGraph 闭环；
- Stage 02：统一 Tool Runtime 和本地 Repository Tool；
- Stage 03：只读 GitHub Issue / PR Tool；
- Stage 04：Plan-and-Execute、Evidence 和确定性最终回答；
- Stage 05：统一错误分类、Retry、Timeout、Fallback、执行预算和结构化日志；
- Stage 06：Reviewer、Reflection、增量 Re-plan 与完整核心 Agent 闭环；
- Stage 07：Working Memory、SQLite Persistent Memory、历史与 trace 查询；
- Stage 08：独立、离线、可重复的 Agent Evaluation Benchmark；
- Stage 09：FastAPI、异步任务执行、SQLite 查询、并发隔离与稳定错误 Contract；
- Stage 10：Docker Image、non-root Uvicorn、health、环境配置和 SQLite Volume；
- Stage 11 及后续阶段：按后续规格继续扩展。

当前尚未实现 Compose、Kubernetes、分布式 Worker、任务恢复、Authentication 或
Multi-Agent。
README 中的后续能力仅表示规划，不代表已经实现。

## 已知可靠性边界

- Retry 没有退避等待，仍可能放大临时服务压力，但受每 Tool 重试硬上限和
  Agent 全局 Attempt 预算约束；
- Python 无法安全强制终止正在运行的同步线程，通用 timeout 返回后，超时的
  daemon worker 可能继续运行；因此有副作用的 Tool 仍需自行提供取消或幂等保障；
- attempt trace 保存在 AgentState，长计划会增长状态体积，但当前最多保留
  `MAX_TOOL_CALLS` 条；
- Fallback 共用原 Tool arguments，仅适用于输入契约兼容的显式 Tool 映射。
- 当前 Reviewer 为规则实现，对复杂自然语言目标可能出现 false positive 或
  false negative；
- Re-plan 只支持现有已知 Evidence 缺口，无法为未知业务目标临时发明新 Tool；
- Review、Reflection、Plan 与 Evidence history 均保存在 AgentState，虽受硬上限
  保护，仍会随循环增加状态体积；
- 当前 Store 面向单机同步 MVP。单进程内 sequence 写入具有事务保护，但没有提供
  多进程写入协调、分布式锁或服务端数据库语义；
- HTTP 后台任务引用只保存在当前 FastAPI 进程内；进程在任务运行中退出时不会
  自动恢复该任务，已完成任务仍可从 SQLite 查询；
- 同步 Agent 使用默认线程池执行，高并发下可能出现 thread pool 饱和；
- `GET /trace` 当前一次返回完整 trace，尚未提供 pagination；
- Stage 09 未实现 Authentication，服务只适合受信任的本地或受控网络环境；
- Container 中运行中的任务若在停止期间被中断，不会在重启后自动续跑；
- named volume 在 Docker 管理的 Volume 上可写；改用 Host bind mount 时必须自行
  确保 non-root `issueops` 用户具有目录写权限；
- Docker Desktop、Linux Engine 与 Host bind mount 的路径语法不同，README 默认
  使用跨平台 named volume 避免路径差异；
- 每个有意义节点保存完整 State snapshot，便于恢复和审计，但任务量或 Evidence
  很大时数据库会持续增长，当前没有自动归档与压缩；
- `--load-task` 用于恢复读取与检查，不会自动从历史中间节点续跑 Graph；
- SQLite 同步 I/O 与 Agent 同线程执行，极高写入量下会增加节点延迟。
- 评测数据集只有 20 个确定性 MVP 用例，不代表开放世界任务分布；
- Repository Fixture 规模较小，GitHub 使用固定 Mock，不覆盖真实网络抖动；
- 评测延迟受本机负载影响，不应解读为性能 SLA。
