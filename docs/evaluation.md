# IssueOps Agent v0.1.0 评测基准

## 目标与边界

Stage 08 为现有单 Agent 核心闭环提供独立、可重复、可审查的离线评测。评测代码全部位于 `eval/`，只通过 `run_agent` 的公开注入点调用生产 Agent，运行结束后读取最终 `AgentState` 评分。它不修改 Planner、Tool Runtime、Reviewer、Reflection 或 Persistent Memory，也不实现新的 Agent 链路。

## 数据集

`eval/dataset.json` 是版本化 JSON 数据集，由 `EvaluationDataset` 严格验证。当前版本为 `0.1.0`，必须恰好包含 20 个唯一用例：

| 分类 | 数量 | 主要覆盖 |
| --- | ---: | --- |
| `repository` | 8 | 目录、文件、代码搜索、路径边界和缺失资源 |
| `github` | 4 | Issue、PR、404 和 rate limit |
| `reliability` | 4 | Retry 成功、Retry 耗尽、Fallback 和 `MAX_TOOL_CALLS` |
| `reflection` | 4 | 首轮通过、Recovery、Reflection 耗尽和预算交互 |

Repository 用例使用 `eval/fixtures/repos/sample_repo/`。GitHub 用例使用 `httpx.MockTransport` 和 `eval/fixtures/github/` 中的固定响应，不访问公网，也不需要 `GITHUB_TOKEN`。可靠性与 Reflection 用例仅在评测层注入确定性 Tool、Planner、Reviewer 或策略。

## 用例成功条件

每个 `EvaluationCase` 可声明以下期望：

- `expected_tools` 与 `expected_tool_args`：按 logical Tool call 顺序校验工具选择和结构化参数；
- `required_evidence_sources`：校验 Evidence 来源；
- `expected_error_codes`：校验终态 Tool 错误；
- `expected_status`：校验 `completed`、`partial` 或 `failed`；
- `expected_review_passed`、`expected_reflection`、`expected_retry` 和 `expected_fallback`：校验推理与可靠性路径；
- `final_answer_contains`：校验最终回答的必要内容。

只有所有已声明期望都满足时，该用例才计为通过。Retry attempt 仅记入 `execution_attempts`，不得重复计为 Planner 的 logical Tool call。

## 指标定义

| 指标 | 分子 | 分母 |
| --- | --- | --- |
| `case_pass_rate` | 满足全部用例期望的数量 | 本次执行用例数 |
| `task_success_rate` | 预期正常完成且实际通过的数量 | `expected_status=completed` 的用例数 |
| `tool_selection_accuracy` | Tool 序列完全一致的用例数 | 本次执行用例数 |
| `tool_argument_accuracy` | 通过 exact 或 subset 结构比较的参数检查数 | 所有参数检查数 |
| `avg_tool_calls` | logical Tool call 总数 | 本次执行用例数 |
| `avg_execution_attempts` | 包含 Retry/Fallback 的实际 attempt 总数 | 本次执行用例数 |
| `retry_rate` | `retry_count > 0` 的用例数 | 本次执行用例数 |
| `reflection_rate` | `reflection_count > 0` 的用例数 | 本次执行用例数 |
| `recovery_rate` | 首轮 Review Fail 后最终通过的 Recovery 数 | 已标记 `recovery_eligible` 且实际发生 Reflection 的用例数 |

延迟指标包含平均值、P50 和 P95。P50/P95 使用 nearest-rank 方法。正确性指标应在重复运行间一致；延迟可因本机负载变化。

## 失败隔离与分类

每个用例独立执行。Fixture 准备、Agent 运行或收尾过程的未处理异常会记录为 `RUNTIME_ERROR`，但不会中断后续用例。其他分类包含 `ANALYSIS_ERROR`、`PLAN_ERROR`、`TOOL_SELECTION_ERROR`、`TOOL_ARGUMENT_ERROR`、`TOOL_EXECUTION_ERROR`、`EVIDENCE_ERROR`、`REVIEW_ERROR`、`REFLECTION_ERROR`、`RELIABILITY_ERROR`、`BUDGET_EXCEEDED`、`UNEXPECTED_STATUS` 和 `FINAL_ANSWER_ERROR`。

## 运行方式

在仓库根目录运行完整基准评测：

```bash
python -m eval.evaluator
```

调试单个用例：

```bash
python -m eval.evaluator --case repo-001
```

指定数据集与输出位置：

```bash
python -m eval.evaluator --dataset eval/dataset.json --reports-dir eval/reports --failure-doc docs/failure_cases.md
```

默认输出：

- `eval/reports/evaluation-report.json`：完整机器可读报告；
- `eval/reports/evaluation-report.md`：人类可读摘要、指标、分类结果和局限；
- `docs/failure_cases.md`：当前失败用例的输入、预期、实际、根因和改进建议。

## v0.1.0 正式基线与解读

当前 20 个用例通过 19 个，用例通过率为 95%。正常完成路径、Tool 选择和 Tool 参数的当前准确率均为 100%。唯一失败 `repo-007` 正确进入 `partial` 路径，但路径边界错误的生产分类为 `EXECUTION_FAILED`，而数据集期望 `INVALID_ARGUMENT`。Stage 08 保留这一真实差异，不为提高评分而修改 Production Agent。

## 局限

- 20 个确定性 MVP 用例不能代表开放世界任务分布；
- Repository Fixture 较小，未覆盖大型 monorepo、二进制资源和复杂构建；
- GitHub 使用固定 Mock，无法衡量真实网络与 API 演化；
- 确定性 Planner 与 Reviewer 可能与数据集存在规则耦合；
- 当前延迟仅反映单机、20 个用例的运行，不是性能 SLA。
