# Decision 0001 — GitHub / ChatGPT / Codex 协作流程

Status: ACCEPTED

## Context

HuntAlpha 是准备上线的真实项目。用户希望与 ChatGPT 讨论需求和方案，由 Codex 执行实现，同时确保修改可审查、可追踪、可回退。

测试仓库已经验证了以下链路可行：

ChatGPT → GitHub task → Codex → Git commit/Push → GitHub → ChatGPT review

真实项目不适合让 Codex 长期直接修改 `main`，因此需要比测试流程更严格的分支和审查机制。

## Decision

1. GitHub Private 仓库 `kuashan/huntalpha` 是正式代码与协作文档的事实来源。
2. `main` 表示已经认可的稳定版本。
3. ChatGPT 将批准后的实现需求写入 `docs/tasks/`。
4. Codex 为每个任务从最新 `main` 创建独立分支。
5. Codex 实现、测试、提交并 Push 分支，将 task 标记为 `IMPLEMENTED`。
6. ChatGPT 从 GitHub 检查实际 diff 和提交，不仅依赖 Codex 的文字汇报。
7. 审查通过后 task 标记为 `ACCEPTED`，再合并到 `main`。
8. 正式部署是合并之后的独立阶段；未来应通过 staging/production 流程执行。
9. 禁止在常规任务中直接对 `main` 做未经审查的开发提交。

## Consequences

优点：

- 每个需求有明确来源和验收标准；
- Codex 的实现可以被 ChatGPT 独立核对；
- `main` 更稳定；
- 出现问题时更容易回退或定位；
- 产品讨论、技术决策和代码历史彼此可追踪。

成本：

- 每个任务多一个分支/审查步骤；
- 需要维护 task 状态和文档；
- 紧急修改仍需遵守最小审查纪律。

## Revisit conditions

当项目引入团队成员、CI/CD、staging 环境或自动化部署后，可以升级流程，例如强制 PR、required checks、branch protection 和自动发布。