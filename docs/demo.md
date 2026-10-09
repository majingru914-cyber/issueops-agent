# IssueOps Agent v0.1.0 Demo

本文档记录真实运行得到的 Demo Transcript。它不是手工构造的理想输出；完整 Final Answer 和 Trace 可以通过 API 使用同一 `task_id` 查询。

## 前置条件

以下任一服务已在 `http://127.0.0.1:8000` 启动：

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

或：

```bash
docker run --rm -p 8000:8000 -v issueops-data:/app/data issueops-agent:v0.1.0
```

## 自动 Demo

Windows PowerShell：

```powershell
.\scripts\demo.ps1
```

指定服务地址或任务：

```powershell
.\scripts\demo.ps1 -BaseUrl http://127.0.0.1:8000 -Query "查找项目中 AgentState 的定义"
```

脚本按固定上限执行：

```text
GET /health
→ POST /tasks
→ bounded polling GET /tasks/{task_id}
→ GET /trace
→ 输出结构化 JSON 摘要
```

## 真实 HTTP / Docker Transcript

Stage 11 Release smoke 在 2026-10-09 使用 `issueops-agent:v0.1.0`、全新 named volume、真实 FastAPI 和 Agent Runner 执行。

### Health

```http
GET /health
HTTP/1.1 200 OK
```

```json
{"status":"healthy","service":"issueops-agent"}
```

### Create Task

Request：

```json
{"query":"查找项目中 AgentState 的定义"}
```

真实响应在 10 ms 内返回：

```json
{
  "task_id": "c28070c951f44803bbe300e7ad2ed419",
  "status": "running"
}
```

### Poll Result

有限轮询后：

```json
{
  "task_id": "c28070c951f44803bbe300e7ad2ed419",
  "status": "completed",
  "review_passed": true,
  "reflection_count": 0,
  "retry_count": 0,
  "tool_call_count": 2
}
```

`final_answer` 非空，回答引用了 `search_code` 与 `read_file` 产生的真实 Repository Evidence。

### Trace

该任务产生 15 个事件：

```text
task_started
analysis
plan
tool_call
tool_attempt
tool_result
evidence
tool_call
tool_attempt
tool_result
evidence
draft
review
final
task_finished
```

### Persistence

Stage 10 持久化验收中，任务在 Container A 完成后，Container A 被正常停止和删除。Container B 与最终 Container C 使用同一 `issueops-stage10-data` named volume，均成功恢复：

```text
status=completed
final_answer present=true
trace events=15
```

这证明 Container lifecycle 与已完成 Agent Task 的 persistence lifecycle 已解耦。

## 真实 Evaluation Transcript

```text
Executed Cases              20
Passed Cases                19
Case Pass Rate              95%
Task Success Rate           100%
Tool Selection Accuracy     100%
Tool Argument Accuracy      100%
```

唯一失败为 `repo-007`，没有为 Release 修改预期或 Production Agent 来换取满分。完整证据见 `../eval/reports/evaluation-report.json` 和 `failure_cases.md`。

## Screenshot / GIF

本次自动化环境未生成 Screenshot 或 GIF，避免使用手工伪造图片。需要用于简历或演示时，可以在运行 `scripts/demo.ps1` 或访问 FastAPI `/docs` 时人工捕获；本文的 Transcript、正式 Evaluation Report 和 Docker E2E 作为可复现证据。
