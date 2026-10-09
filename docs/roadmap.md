# IssueOps Agent Roadmap

Roadmap 只描述 Future Work，不代表当前已经实现。v0.1.0 的真实能力以 README、测试和 Evaluation 报告为准。

## v0.1.0 — 已实现

- 单 Agent LangGraph Plan-and-Execute Pipeline；
- typed Repository / GitHub Tools 与统一 `ToolRuntime`；
- Retry、Timeout、Fallback、执行预算与结构化错误；
- Evidence、Reviewer、Reflection 和有限 Re-plan；
- SQLite Task、State Snapshot 与 Execution Trace；
- 20-case 离线 Evaluation Benchmark；
- FastAPI 异步任务服务；
- Docker 单进程部署和 SQLite Volume 持久化。

## v0.2 — 候选方向

- 接入真实 LLM Planner / Reviewer，同时保留确定性测试替身；
- 扩展只读 GitHub Tool 和 Error Taxonomy；
- 为 HTTP 服务加入 Authentication 与更明确的并发限制；
- 增加运行中任务的恢复/重放协议；
- 扩大 Benchmark、Repository Fixture 与回归场景；
- 为 Trace 增加分页与归档策略。

## v0.3+ — 长期方向

- RAG 与可审查的外部知识检索；
- Multi-Agent 角色协作与职责隔离；
- Distributed Worker 与持久化 Queue；
- Metrics、Tracing 和告警等 Observability；
- PostgreSQL 等服务端 Persistence；
- Cloud Deployment 与横向扩展。

上述方向需要新的架构和验收阶段，不在 v0.1.0 Release 中实现。
