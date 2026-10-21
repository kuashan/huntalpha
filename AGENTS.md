# AGENTS.md

本文件定义仓库协作和安全边界。**SiftAlpha.com 网站的最新分工、开发、构建及发布流程以 [docs/DEVELOPMENT_HANDBOOK.md](docs/DEVELOPMENT_HANDBOOK.md) 为准**；旧的 Codex 开发、`main` 或 GitHub Actions 构建约定不适用于网站。

## 1. 项目定位

HuntAlpha 是准备正式上线、长期维护的真实产品，不是演示项目。任何修改都应优先保证：

1. 用户数据与密钥安全；
2. 可回退、可审查；
3. 不破坏现有可用功能；
4. 不泄露私有指标源码、凭据或本地业务数据；
5. 为未来生产部署保留清晰边界。

## 2. 三方角色（网站）

- **用户：**需求与发布授权、最终真实网站验收、认可基线。
- **ChatGPT：**负责定位问题、修改代码、**执行发布前必要的 Linux Bash/Django/迁移/前端自动测试**、提升版本号、提交并 Push GitHub；部署后协助核查真实页面。
- **Codex：**只负责本地 ARM64 构建及其固有的依赖/前端构建步骤、GHCR 推送、服务器受控预检/备份/迁移与部署，以及**一次最小技术健康检查**。不重复 ChatGPT 已负责的 Linux Bash/Django/迁移回归，不承担业务开发修复。
- **GitHub：**代码和审查记录事实源。以 `docs/DEVELOPMENT_HANDBOOK.md` 为完整操作依据。

## 3. 开始工作前

ChatGPT 开发时必须核查真实远端 HEAD、已认可基线和最小需求边界，再提交代码与必要测试。

Codex 执行构建与部署时必须先读 `AGENTS.md`、`docs/DEVELOPMENT_HANDBOOK.md`、当前 `docs/tasks/` 的任务文件，核对分支、版本及真实 Commit，并读取 ChatGPT 的发布前测试报告。若构建或受控预检失败，应停止并交由 ChatGPT 修复代码，不自行扩大开发范围，不反复尝试。

除非明确需要，不使用含大量旧约定的 `agent.md` 替代当前操作规则。

## 4. 分支和版本规则

- 网站正式分支是 **`release/siftalpha-web-v1`**，当前已认可基线 V1.1.4；后续修复必须升级版本号。
- ChatGPT 在独立 `feat/`、`fix/`、`docs/` 分支上开发和提交 PR，不直接在正式分支或生产环境开发。
- Codex 使用**合并后正式分支的完整 Commit SHA**本地构建；禁止 GitHub Actions 或生产服务器构建。
- 其他项目若使用 `main`，遵循其各自规则，不将网站发布流程混入其他项目。
- 不得未经授权 force push、重写历史、大范围删除或不可逆操作。

## 5. 状态与验收

- **开发完成：**ChatGPT 完成代码、版本号、GitHub 提交及已执行的针对性检查。
- **构建完成：**Codex 完成本地 ARM64 镜像并验证 GHCR Digest。
- **部署完成：**受控预检、数据保护、部署和最小技术健康检查通过。
- **最终验收完成：**用户在真实网站确认功能正常，才可冻结为新的基线。

任何角色不得提前宣称下一阶段已通过。

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

## 11. 测试职责

- ChatGPT 负责运行适用的语法、Linux POSIX Bash 契约、Django、数据库迁移、前端及逻辑测试；未运行的必须明确记录，不得当作通过。
- Codex 不重跑 ChatGPT 的发布前自动测试；仅做镜像构建自身不可省略的依赖安装、前端构建及产物、平台、OCI 标签与 Digest 校验。失败时报告并等待 ChatGPT 改代码。受控工具内的数据库备份、恢复副本与迁移预检仍不可省略。
- 部署后 Codex 仅核对固定容器、目标 Digest、受控 `status` / `health` 和基本 HTTP 状态；**不重复进行复杂业务功能验证**。页面检查由 ChatGPT 协助，用户最终验收。
- 密钥、数据库、私有公式及用户资料绝不能进入日志或 Git。

## 12. 生产环境原则

网站已正式上线，使用受控 `siftalpha-web-admin`、`siftalpha-web-compose` 和持久化 SQLite。需要迁移时必须先进行真实备份、独立恢复校验与白名单核验，禁止直接对生产数据库 `migrate`。不操作 Cloudflare、Crypto、Options Monitor 或其他无关容器。

Codex 在本地构建 `linux/arm64` 镜像并推送 GHCR，以不可变 Digest 预检与受控部署。**禁止 GitHub Actions 构建**。数据库恢复需要单独授权。详见 `docs/DEVELOPMENT_HANDBOOK.md`。

## 13. 分工交接报告

ChatGPT 交付：修改范围、版本号、开发分支、PR/Commit、针对性检查结果及未验证项。

Codex 交付：合并后正式 HEAD、本地必要构建检查、ARM64 镜像/真实 GHCR Digest、数据库备份和迁移预检、部署及最小健康检查结论。不要向 Codex 要求反复的部署后人工功能巡检。

异常停止并报告，由 ChatGPT 定位代码问题；不可擅自更改全局服务器设置。

## 14. 审查与最终验收

1. ChatGPT 完成业务开发修复并提交独立 PR。
2. ChatGPT 提交发布前测试结论后，Codex 按正常保护流程合并 PR，在本地构建 ARM64 镜像并推送 GHCR，不重复执行 Linux 测试。
3. 依据用户发布授权，Codex 经受控工具完成备份、迁移预检、部署和最小技术检查。
4. ChatGPT 协助真实网页检查；**用户最终决定验收是否通过、是否冻结为新基线**。

`docs/DEVELOPMENT_HANDBOOK.md` 优先于旧角色和发布描述。
