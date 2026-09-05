# HuntAlpha Task 工作流

本目录保存已经讨论并准备交给 Codex 的正式任务。

## 状态流转

`DRAFT` → `READY_FOR_CODEX` → `IN_PROGRESS` → `IMPLEMENTED` → `ACCEPTED`

如遇依赖、风险或需要人工决定，可进入 `BLOCKED`。

## 谁负责什么

- ChatGPT：把讨论结果整理成 task，定义范围与验收标准。
- Codex：读取 task，在独立分支实现、测试、提交、Push 并报告。
- ChatGPT/用户：检查实现是否满足 task；通过后标记 `ACCEPTED`。

## 文件命名

建议：

- `001-xxx.md`
- `002-xxx.md`
- `003-xxx.md`

编号只增不减，不重复使用。

## 开工规则

Codex 开工前必须：

1. 阅读仓库根目录 `AGENTS.md`；
2. 阅读指定 task；
3. 从最新 `main` 创建独立分支；
4. 确认工作区没有与任务无关的未提交改动。

## 完成规则

Codex 完成后：

- 将 task 状态改为 `IMPLEMENTED`；
- 写 Completion Report；
- Push 实现分支；
- 不得自行把状态改成 `ACCEPTED`。

ChatGPT 审查通过后再改为 `ACCEPTED`。

新任务请从 `TASK_TEMPLATE.md` 复制。