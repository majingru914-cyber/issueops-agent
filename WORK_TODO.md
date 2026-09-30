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

## 当前边界

当前可运行链路为：

```text
START
→ analyze_task
→ create_plan
→ execute_step
→ collect_evidence
→ more_steps?
├─ Yes → execute_step
└─ No  → generate_answer
          → END
```

Planner 通过 `tool_name` 和 `tool_args` 决定调用，Executor 只负责交给现有
`ToolRuntime.execute()` 执行。

独立 Tool System 链路为：

```text
Tool Request
→ ToolRuntime
→ ToolRegistry
→ BaseTool
→ Pydantic Args Schema
→ Concrete Tool
→ ToolResult
```

成功 ToolResult 进入 Evidence，失败 ToolResult 进入 Errors；当前失败步骤会
被记录并继续有限计划，不会自动 Retry 或 Re-plan。

当前默认 Registry 包含：

```text
list_directory
read_file
search_code
get_github_issue
get_github_pr
```

GitHub Tool 当前只读，自动化测试全部使用 Mock HTTP。

## 待开始

- Stage 05：Reliability，在现有 Runtime 和执行循环上增加受控可靠性能力。

当前没有实现 Retry、Fallback、MAX_TOOL_CALLS、通用 Runtime Timeout、
Reviewer、Reflection、Re-plan、持久化、Evaluation、FastAPI、Docker、
GitHub 写操作或 Multi-Agent。
