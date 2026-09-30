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

## 下一阶段

- Stage 08：Evaluation（尚未开始）。

当前没有实现 Evaluation、FastAPI、Async API、Docker、GitHub 写操作或
Multi-Agent。Reviewer 与 Reflection 均不直接执行 Tool；Stage 05 Retry 语义未被
Stage 06 Reflection 或 Stage 07 Persistence 改变。
