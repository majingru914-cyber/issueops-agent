# IssueOps Agent v0.1.0 失败用例

数据集版本：`0.1.0`

## `repo-007`

- 输入：验证路径边界
- 预期：status=partial, tools=['read_file']
- 实际：status=partial, tools=['read_file']
- 失败分类：TOOL_EXECUTION_ERROR
- 根因：Error code 期望 ['INVALID_ARGUMENT']，实际 ['EXECUTION_FAILED']。
- 可能的改进：先扩充独立用例与诊断证据，再决定是否修改 Production Agent。
