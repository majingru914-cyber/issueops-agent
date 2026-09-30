# IssueOps Agent 评测报告

## 摘要

- 数据集版本：`0.1.0`
- 执行时间：`2026-09-30T13:51:43+00:00`
- Python：`3.12.14`
- 执行用例：`20`
- 通过用例：`19`

正确性指标由固定数据集和结构化 `AgentState` 决定；延迟属于运行时性能指标，允许不同运行间波动。

## 基准评测组成

| 分类 | 用例数 | 通过数 | 通过率 |
| --- | ---: | ---: | ---: |
| `repository` | 8 | 7 | 87.50% |
| `github` | 4 | 4 | 100.00% |
| `reliability` | 4 | 4 | 100.00% |
| `reflection` | 4 | 4 | 100.00% |

## 指标

| 指标 | 数值 |
| --- | ---: |
| 用例通过率 | 95.00% |
| 任务成功率 | 100.00% |
| 工具选择准确率 | 100.00% |
| 工具参数准确率 | 100.00% |
| 平均 logical Tool 调用数 | 1.250 |
| 平均执行尝试数 | 1.500 |
| 平均延迟 | 8.896 ms |
| P50 延迟 | 8.791 ms |
| P95 延迟 | 10.585 ms |
| Retry 发生率 | 15.00% |
| Reflection 发生率 | 50.00% |
| Recovery 成功率 | 100.00% |

## 分类结果

每类结果均按行为是否符合用例期望计算，预期失败路径不会提高任务成功率。

## 失败用例

### `repo-007`

- 分类：`repository`
- 预期状态：`partial`
- 实际状态：`partial`
- 失败分类：`TOOL_EXECUTION_ERROR`
- 原因：Error code 期望 ['INVALID_ARGUMENT']，实际 ['EXECUTION_FAILED']。

## 可靠性结果

- 发生 Retry 的用例：`3`
- Retry 总数：`4`
- Timeout 总数：`4`
- Fallback 总数：`1`
- MAX_RETRIES_EXCEEDED：`2`
- MAX_TOOL_CALLS_EXCEEDED：`2`

## Reflection 结果

- 发生 Reflection 的用例：`10`
- 平均 Reflection 次数：`0.800`
- 可 Recovery 用例：`1`
- Recovery 成功用例：`1`

## 局限

- 数据集只有 20 个确定性 MVP 用例，不能代表开放世界软件研发任务。
- Repository Fixture 规模很小，未覆盖大型 monorepo、编码差异和复杂构建系统。
- GitHub 使用固定 Mock 响应，不包含真实网络抖动和完整 API 变化。
- Planner 与 Reviewer 为规则实现，指标会受到数据集与规则耦合影响。
- 延迟受本机负载影响，P95 在 20 个用例的样本下仅作为辅助信息。
