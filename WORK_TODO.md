# IssueOps Agent 工作清单

## 已完成

- Stage 00：完成仓库初始化、基础依赖、工程规则和冒烟测试。
- Stage 01：完成最小 `AgentState`、结构化模型、`analyze_task`、
  `create_plan`、LangGraph 编译调用、CLI 和失败路径测试。

## 当前边界

当前可运行链路为：

```text
START
→ analyze_task
→ create_plan
→ END
```

`tool_hint` 仅为计划字段，不会执行工具。

## 待开始

- Stage 02：工具系统。进入该阶段前需先完成 Stage 01 Review。

当前没有实现 Tool Runtime、GitHub API、Reviewer、Reflection、持久化、
Evaluation、FastAPI、Docker 或 Multi-Agent。
