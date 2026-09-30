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

## 当前边界

当前可运行链路为：

```text
START
→ analyze_task
→ create_plan
→ END
```

`tool_hint` 仅为计划字段，不会执行工具。

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

LangGraph 与 Tool System 尚未连接。

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

- Stage 04：Plan-and-Execute，届时才连接 Planner 与 Tool Runtime。

当前没有实现 Planner 自动 Tool execution、Executor、Evidence Collector、
Retry、Fallback、通用 Runtime Timeout、Reviewer、Reflection、持久化、
Evaluation、FastAPI、Docker、GitHub 写操作或 Multi-Agent。
