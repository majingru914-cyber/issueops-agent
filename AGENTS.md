# IssueOps Agent Engineering Rules

## Project Goal

Build a reliable and evaluable software-task AI Agent using LangGraph.

## Core Pipeline

Analyze
→ Plan
→ Execute Tool
→ Collect Evidence
→ Generate
→ Review
→ Reflect
→ Re-plan
→ Final

## Engineering Rules

1. Reuse existing modules before adding new modules.
2. Avoid duplicate Agent pipelines.
3. All Tools must use typed schemas.
4. All Tool executions must return ToolResult.
5. Tool errors must never be silently swallowed.
6. All retry loops must have explicit maximum limits.
7. LangGraph state is the authoritative runtime state.
8. Evaluation code must remain independent from production Agent code.
9. Secrets must never be committed.
10. Every Stage must contain tests.
11. Do not implement P1/P2 features before P0 is stable.
12. Do not introduce Multi-Agent before the single-Agent workflow is complete.
13. Keep the MVP runnable locally.
14. Update README and Work TODO when architecture changes.

## 语言规范

1. 代码符号、API、类名、函数名、文件路径和命令必须保留英文，不得翻译为中文。
2. 除上述必须保留英文的内容外，所有面向人的内容必须使用中文。
3. 中文内容包括但不限于：代码注释、文档字符串、项目文档、开发报告、测试说明，以及 Codex 与用户的对话回复。

## Definition of Done

A feature is complete only if:

- implementation exists;
- tests pass;
- failure behavior is defined;
- logs are observable;
- documentation is updated.
