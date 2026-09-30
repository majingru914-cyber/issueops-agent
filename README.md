# IssueOps Agent

## 项目概述

IssueOps Agent 是一个基于 Python 和 LangGraph 的软件研发任务自主处理
Agent。项目最终将支持任务分析、仓库检查、工具执行、证据收集、审查、
反思和重新规划。

当前仓库已经实现完整的单 Agent 核心闭环。Planner 生成结构化 Tool 调用，
Executor 通过统一 ToolRuntime 执行本地 Repository Tool 和只读 GitHub Tool；
Evidence 形成 Draft Answer 后，由确定性 Reviewer 判断完成度。Review Fail 会
进入 Reflection，并由 Re-plan 只追加缺失步骤后重新执行。

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

**Current Status: Stage 06 — Reviewer / Reflection / Re-plan**

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
│   ├── schemas.py      # Pydantic 结构化模型
│   └── state.py        # LangGraph 运行时状态
├── api/                # 后续阶段使用
├── docs/               # 项目文档
├── eval/               # 后续阶段使用
├── examples/           # 后续阶段使用
├── memory/             # 后续阶段使用
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
- Stage 07 及后续阶段：逐步加入持久化 Memory 和 Evaluation。

当前尚未实现 Persistent Memory、Evaluation Benchmark、FastAPI、Async API、
Docker 或 Multi-Agent。README 中的后续能力仅表示规划，不代表已经实现。

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
  保护，仍会随循环增加状态体积。
