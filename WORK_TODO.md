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
└─ No → generate_answer
          → END
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
`MAX_TOOL_CALLS` 时 Graph 记录错误并直接生成最终回答。

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
```

## 待开始

- Stage 06：Reviewer / Reflection / Re-plan。

当前没有实现 Reviewer、Reflection、Re-plan、持久化、Evaluation、FastAPI、
Docker、GitHub 写操作或 Multi-Agent。Stage 05 的 Retry 仅针对同一 Tool Step，
不改变 Planner 计划。
