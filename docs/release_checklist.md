# IssueOps Agent v0.1.0 Release Checklist

该清单只勾选已经由命令、文件或远端状态证明的项目。Release 准备期间会持续更新；Tag、Push 和 GitHub Release 在实际完成前保持未勾选。

## Engineering Gates

- [x] Stage 10 通过 `ff-only` 合并到 `main`
- [x] 全量 tests pass：`156 passed`
- [x] 两次 Evaluation correctness metrics 一致
- [x] `repo-007` 保持唯一真实 Failure Case
- [x] Docker `issueops-agent:v0.1.0` build
- [x] Release Container smoke：Health、Status、Task、Poll、Trace
- [x] 最终 Secret Audit：tracked source、history、Image、history、filesystem、logs
- [x] README v0.1.0
- [x] Architecture Diagram / Agent Workflow
- [x] 真实 Demo Transcript
- [x] Evaluation Report 与 Failure Cases
- [x] Roadmap
- [x] MIT License
- [x] Git diff audit：无 Production Agent 重写或误提交 Artifact

## Release State

- [ ] Stage 11 Release commit
- [ ] `release/11-v0.1.0` fast-forward 合并到 `main`
- [ ] local `v0.1.0` annotated tag
- [ ] `origin/main` push
- [ ] `origin/v0.1.0` push
- [ ] GitHub Release

最终远端状态必须以 GitHub 和 Release Report 为准，不因准备计划而预先勾选。
