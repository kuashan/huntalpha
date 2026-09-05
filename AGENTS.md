# AGENTS.md

本文件是 HuntAlpha 仓库中 Codex 开始任何实现工作前必须阅读的最高级协作规则。

## 1. 项目定位

HuntAlpha 是准备正式上线、长期维护的真实产品，不是演示项目。任何修改都应优先保证：

1. 用户数据与密钥安全；
2. 可回退、可审查；
3. 不破坏现有可用功能；
4. 不泄露私有指标源码、凭据或本地业务数据；
5. 为未来生产部署保留清晰边界。

## 2. 角色

- **用户**：产品方向、业务目标、最终取舍与验收意见。
- **ChatGPT**：澄清需求、检查 GitHub 当前状态、形成任务规格、记录关键决策、审查实现结果。
- **Codex**：读取任务与仓库、在独立分支实现、运行检查、提交并 Push、报告结果。
- **GitHub**：代码、任务、架构、决策和审查历史的事实来源（source of truth）。

## 3. 开工前必须做的事

每次收到实现任务时，Codex 必须按顺序：

1. 阅读本文件 `AGENTS.md`；
2. 阅读被指定的 `docs/tasks/<task>.md`；
3. 阅读该任务引用的 `docs/architecture/` 或 `docs/decisions/` 文件；
4. 检查当前分支、Git 状态和相关现有代码；
5. 若需求与仓库现状冲突或存在歧义，停止并报告，不得静默猜测。

除非任务明确要求，否则不要把 `agent.md` 当成当前流程规则。`agent.md` 保留了大量历史项目约定和领域细节，可用于理解背景；如与本文件、正式 task 或 `docs/decisions/` 冲突，以本文件和较新的正式文档为准。

## 4. 分支与 main 规则

`main` 代表已经认可的稳定版本。

- 常规功能、修复、重构、生产配置修改：**不得直接在 `main` 上开发**。
- 每个任务使用独立分支，例如：
  - `feat/<short-name>`
  - `fix/<short-name>`
  - `chore/<short-name>`
  - `docs/<short-name>`
- 开始任务前应从最新 `main` 创建分支。
- Codex 完成后 Push 分支并报告 commit / PR。
- 在 ChatGPT 审查和用户需要的验证完成前，不合并到 `main`。
- 禁止未经明确授权的 force push、历史重写、`reset --hard`、大范围删除或不可逆操作。

仓库首次协作基础设施搭建可作为例外，但完成后应执行上述规则。

## 5. Task 状态

正式任务使用以下状态：

- `DRAFT`：仍在讨论，Codex 不得实施。
- `READY_FOR_CODEX`：方案已批准，可以开始。
- `IN_PROGRESS`：Codex 已开始实现。
- `BLOCKED`：因依赖、风险或决策无法继续。
- `IMPLEMENTED`：Codex 已完成并 Push，等待审查。
- `ACCEPTED`：ChatGPT/用户审查通过。

Codex 不得自行把任务从 `IMPLEMENTED` 改成 `ACCEPTED`。

## 6. 实现范围

- 只实现 task 明确批准的范围。
- 不做与任务无关的“顺手重构”。
- 不因个人偏好替换技术栈、目录结构或既有架构。
- 修改前先阅读现有实现；优先小而可审查的改动。
- 如必须扩大范围才能安全完成，先在报告中说明并等待决定。

## 7. 安全与秘密信息

永远不要提交：

- `.env` 或真实环境变量文件；
- Django `SECRET_KEY`；
- API Key / Token / 密码；
- SSH 私钥、证书、service account；
- Cookie / Session；
- 本地数据库及用户数据；
- 本地日志、备份、运行缓存；
- 任何真实支付、邮件、云服务或 AI 服务凭据。

当前约定：

- Django `SECRET_KEY` 必须从 `DJANGO_SECRET_KEY` 环境变量读取；
- `.env.example` 只能包含占位符；
- 生产环境应由服务器环境、容器 Secret 或专用密钥管理机制注入秘密；
- 如发现秘密已经进入 Git 历史，立即停止相关 Push 并报告。

### 7.1 本地数据库高风险操作前恢复点

在执行 `migrate`、数据导入、批量数据修改、数据恢复、数据清理或其他可能影响本地 SQLite 数据库的操作前，必须先运行：

```powershell
python manage.py backup_local_db
```

并确认命令成功输出备份路径、SHA-256 和 `integrity_check: ok`。备份必须位于 Git 仓库之外；不得把数据库、备份、日志或其中的用户数据/私有指标源码加入 Git。若备份失败，必须停止高风险数据库操作并报告原因。

## 8. 数据与私有资产边界

以下内容属于本地或私有资产，不应进入公开 API、前端构建物或 GitHub：

- 用户账号/Session/密码哈希等数据库内容；
- 私有通达信指标源码；
- 私有校准数据和本地备份；
- 未授权再分发的行情数据。

指标源码只能保留在服务端；前端/API 仅返回必要的元数据和绘图结果，不得返回公式正文。

## 9. 当前技术架构约束

当前项目主要结构：

- 后端：Python / Django；
- 前端：Vue 3 / Vite / Lightweight Charts；
- 开发数据库：SQLite（仅开发用途）；
- 本地授权行情：富途 OpenD；
- Django Admin + SimpleUI；
- `vendor/formula-ts` 为 Git submodule，上游研究参考，不得擅自改成普通目录。

公开页面和交互优先在 `frontend/src/` 实现；Django 负责 API、业务逻辑和管理后台。

## 10. 公式与金融图表关键不变量

除非正式 task 明确改变，必须保持以下原则：

1. 服务端公式运行标识为 `tdx-server-v2`；
2. `frontend/src/indicators/tongdaxinFormula.js` 是当前严格通达信解析/计算核心，`core/formula_runner.mjs` 负责服务端调用和绘图数据转换；
3. 禁止通过 API 或前端暴露私有公式源码；
4. `vendor/formula-ts` 仅为上游研究参考，不得恢复运行时双引擎静默回退；
5. 不得使用 `eval` 执行用户公式；
6. 图表与指标计算应以真实授权数据流为准；离线样本仅用于校准/回归，不得伪装为实时行情；
7. 没有授权原始数据时，不得把近似模型或占位数据声明为通达信/数据商的精确原始结果；
8. 修改公式引擎或绘图语义时，必须运行相关回归并检查已启用指标。

更细的历史公式规则目前仍可参考 `agent.md`；未来逐步迁入 `docs/architecture/`。

## 11. 测试与检查

根据改动类型，至少执行适用的检查：

### 后端

- `python manage.py check`
- 相关 Django tests
- 涉及模型时检查 migrations

### 前端

- `npm run build`
- 相关 lint/test（仓库存在时）

### 通用

- `git diff --check`
- 检查 Git diff 仅包含任务范围
- 检查没有秘密、本地数据库、日志或构建产物被意外加入

如果某项检查因环境条件无法运行，必须明确报告原因，不得写成“通过”。

## 12. 生产环境原则

当前仓库仍包含开发配置。正式上线前必须通过独立任务处理至少：

- `DEBUG=False` 与环境化配置；
- 正式 `ALLOWED_HOSTS`；
- PostgreSQL 或其他生产数据库方案；
- 静态文件部署；
- HTTPS、HSTS、Secure Cookie；
- CSRF / CORS 正式策略；
- 正式邮件服务；
- AI 服务与支付/点数的凭据、幂等、审计和合规；
- 日志、备份、监控、恢复和发布回滚。

不得为了“先上线再说”跳过安全边界。

## 13. Codex 完成报告

每个任务完成后必须报告：

- 实现摘要；
- 修改文件；
- 测试/检查及结果；
- 重要设计选择；
- 未解决问题或风险；
- 分支名；
- commit hash；
- Push 是否成功；
- PR（如有）。

若 Push、测试、认证或网络失败，保留现场并报告具体错误，不要擅自修改全局系统设置。

## 14. 审查与合并

当状态为 `IMPLEMENTED`：

1. ChatGPT 从 GitHub 检查实际 diff、提交和测试证据；
2. 若不通过，任务继续修改；
3. 若通过，任务标记 `ACCEPTED`；
4. 再按约定合并到 `main`；
5. 涉及上线的任务还需通过部署/测试环境验证，不能仅以代码合并代表生产上线成功。
