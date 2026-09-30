# IssueOps Agent

## 项目概述

IssueOps Agent 是一个基于 Python 和 LangGraph 的软件研发任务自主处理
Agent。项目最终将支持任务分析、仓库检查、工具执行、证据收集、审查、
反思和重新规划。

当前仓库只实现了最小 LangGraph 闭环，后续能力会按阶段逐步加入。

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

Stage 01 当前已完成的真实链路为：

```text
User
→ Analyze
→ Plan
→ Final
```

对应的 LangGraph 为：

```text
START
→ analyze_task
→ create_plan
→ END
```

这里的 `Final` 表示 CLI 输出最终 State 中经过 Pydantic 验证的任务分析和
计划，不包含独立的答案生成节点。

## 当前状态

**Current Status: Stage 01 — Minimal LangGraph Loop**

当前已实现：

- 使用 `TypedDict` 定义的最小 `AgentState`；
- 使用 Pydantic 定义的 `TaskAnalysis`、`PlanStep` 和 `TaskPlan`；
- 确定性的 `analyze_task` 和 `create_plan` 节点；
- 基于真实 `StateGraph` 的节点、边、编译与调用；
- 输出结构化 JSON 的 CLI；
- 空输入与缺失参数的明确错误处理。

**Tool execution is not implemented yet.**

计划中的 `tool_hint` 只是未来工具能力的提示字段。目前不会调用文件系统、
仓库搜索、GitHub API 或其他外部工具。

## 项目结构

```text
issueops-agent/
├── agent/
│   ├── analyzer.py     # 任务分析节点
│   ├── graph.py        # LangGraph 构建与编译
│   ├── planner.py      # 任务规划节点
│   ├── schemas.py      # Pydantic 结构化模型
│   └── state.py        # LangGraph 运行时状态
├── api/                # 后续阶段使用
├── docs/               # 项目文档
├── eval/               # 后续阶段使用
├── examples/           # 后续阶段使用
├── memory/             # 后续阶段使用
├── tests/              # 自动化测试
├── tools/              # 后续阶段使用
├── main.py             # CLI 入口
└── WORK_TODO.md        # 阶段状态与开发边界
```

## 环境要求

- Python 3.12 或更高版本
- `venv`
- `pip`

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

运行最小工作流：

```bash
python main.py "分析项目结构"
```

CLI 会输出包含以下字段的 JSON：

- `task_type`
- `goal`
- `required_capabilities`
- `plan`

## 测试

在仓库根目录运行：

```bash
python -m pytest -v
```

## 开发路线

- Stage 00：仓库初始化；
- Stage 01：最小 LangGraph 闭环；
- Stage 02 及后续阶段：在保持单 Agent 管线可测试的前提下逐步加入工具、
  证据、审查和反思能力。

README 中的后续能力仅表示规划，不代表已经实现。
