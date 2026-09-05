# Decision 0002 — Secret 与本地数据策略

Status: ACCEPTED

## Context

HuntAlpha 的旧本地 Git 历史曾包含硬编码 Django `SECRET_KEY`，同时本地 SQLite 数据库包含用户记录、Session、密码哈希、私有指标和校准数据。

在首次上传 GitHub 前，项目已经创建新的干净 Git 历史，并将旧历史保留为本地 bundle，不上传远端。

## Decision

1. 真实 Secret 不进入 GitHub，即使仓库是 Private。
2. Django `SECRET_KEY` 通过 `DJANGO_SECRET_KEY` 环境变量注入。
3. `.env` 仅用于本地开发并由 `.gitignore` 排除。
4. `.env.example` 仅包含变量名、说明和占位符。
5. 本地数据库、备份、日志、Cookie/Session、私钥、证书、Token、credential 导出文件不得提交。
6. 生产环境不依赖仓库中的 `.env`；应使用服务器环境、容器 Secret 或专用密钥管理方案。
7. 发现秘密可能进入 Git 历史时，停止 Push，先轮换秘密并评估历史清理。
8. 用户数据和私有指标源码不以“Private 仓库”为理由上传到 GitHub。

## Consequences

- 本地开发需要单独配置环境变量；
- 部署系统必须有 Secret 注入机制；
- 仓库可以安全保存代码和模板，而不保存真实运行秘密；
- 数据备份需要独立于 Git 的机制。

## Revisit conditions

当引入正式云环境、容器平台或 CI/CD 时，选择具体 Secret Manager，并补充生产密钥轮换、权限和审计策略。