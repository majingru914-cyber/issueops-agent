# IssueOps Agent

## 项目概述

IssueOps Agent 是一个基于 Python 和 LangGraph 的软件研发任务自主处理
Agent。项目最终将支持任务分析、仓库检查、工具执行、证据收集、审查、
反思和重新规划。

当前仓库已经实现最小 LangGraph 闭环，以及一套与 LangGraph 解耦、同时
支持本地 Repository Tool 和只读 GitHub Tool 的统一 Tool System。后续能力
会按阶段逐步加入。

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

当前 Tool System 链路为：

```text
Tool Request
→ ToolRuntime
→ ToolRegistry
→ BaseTool
→ Pydantic Args Schema
→ Concrete Tool
→ ToolResult
```

当前已注册的 Tool 类型为：

```text
               ┌→ Repository Tools
ToolRuntime ────┤
               └→ GitHub Tools → GitHubClient → GitHub REST API
```

这两条链路已经存在，但尚未连接。

## 当前状态

**Current Status: Stage 03 — GitHub Tools**

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
- GitHub Bearer/匿名只读请求、明确 HTTP timeout、rate-limit 检测和稳定错误映射。

**Planner is not connected to Tool Runtime yet.**

Planner 中的 `tool_hint` 仍然只是规划字段。当前 Agent 不能自主执行 Tool；
Tool System 只能通过独立的 `ToolRuntime.execute()` 入口调用。两条链路将在
Stage 04 — Plan-and-Execute 连接。

GitHub Tool 仅执行读取操作，不会修改 Issue、发表评论、创建 PR 或写入仓库。

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
├── tools/
│   ├── base.py         # BaseTool 与 ToolResult
│   ├── filesystem.py   # list_directory 与 read_file
│   ├── github.py       # get_github_issue 与 get_github_pr
│   ├── github_client.py # GitHub REST Client
│   ├── github_errors.py # GitHub 领域错误
│   ├── path_utils.py   # 共享 workspace 路径边界
│   ├── registry.py     # Tool 注册与发现
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

运行最小工作流：

```bash
python main.py "分析项目结构"
```

CLI 会输出包含以下字段的 JSON：

- `task_type`
- `goal`
- `required_capabilities`
- `plan`

独立构建 Tool Runtime：

```python
from pathlib import Path

from tools import build_tool_runtime

runtime = build_tool_runtime(Path.cwd())
result = runtime.execute("read_file", {"path": "README.md"})
```

所有正式 Tool 调用都返回 `ToolResult`。用户路径必须是 workspace 内的相对
路径；绝对路径和包含 `..` 的路径会被拒绝。

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
- Stage 04 及后续阶段：在保持单 Agent 管线可测试的前提下逐步加入
  Plan-and-Execute、证据、审查和反思能力。

README 中的后续能力仅表示规划，不代表已经实现。
