# Task 001 — 标准认证流程与真实行情清理

Status: IMPLEMENTED

## 产品决定

PR #2 的最新 ChatGPT comment 已撤销本任务此前新增的“管理员专用审查模式”。本任务继续使用当前分支和 PR #2，不创建新 PR，也不合并 `main`。

保留本 PR 已完成的真实行情改造：富途 OpenD 真实报价、涨跌幅、OHLC、K 线，以及 OpenD 不可用时的明确不可用状态；禁止静态或生成行情回退。

## 背景

HuntAlpha 是准备正式上线、长期维护的真实产品。前端原有的登录、注册、访客入口和 Django Session 认证流程应保持可用；本次产品决定要求撤销新增的管理员专用入口和限制，恢复完整的用户进入流程。

另一方面，行情页面不能把演示数字当作实时数据。当前支持的报价、开高低和历史 K 线应统一来自本机富途 OpenD `127.0.0.1:11111`；数据源不可用时必须明确显示不可用，不得生成或展示假行情。

历史决策文档 `docs/decisions/0003-development-admin-review-and-real-data-policy.md` 记录了此前的管理员审查方案；本次 PR 产品决定已取代该方案的运行时实现范围，保留其真实数据与安全边界要求。

## 目标

1. 恢复原有完整的登录、注册、访客入口和正常用户 Session/终端 API 流程。
2. 移除本 PR 新增的管理员专用审查模式，包括环境开关、后端限制、前端专用文案/入口和仅用于该模式的测试。
3. 清除前端可见的静态/演示行情价格和涨跌幅；对于富途 OpenD 支持的数据，全部使用真实运行时数据。
4. OpenD 或真实数据不可用时明确显示不可用，不允许回退到模拟/生成行情。

## 范围

### 必须做

- 前端保留并可交互使用登录、注册和访客入口。
- 后端恢复正常的邮箱注册、普通用户登录、访客 Session 和终端 API 行为；不增加 staff-only 审查门槛。
- 移除 `HUNTALPHA_ADMIN_REVIEW_MODE`、`DEV_ADMIN_REVIEW_MODE` 及所有关联的管理员专用逻辑、文案和测试。
- 复用 Django 现有账户、密码校验和 Session，不创建硬编码账户或凭据。
- 当前支持证券的前端最新价、涨跌幅、开高低等展示改为调用后端真实行情接口 `/api/quote/<code>/`。
- 保留现有 `/api/kline/<code>/` 的真实 OpenD K 线数据流，不增加任何演示回退。
- 清理/停止使用 `frontend/src/data/marketData.js` 中的硬编码价格、涨跌幅和生成行情作为网页运行时数据。
- 如果市场/证券当前没有真实数据源（例如当前未接入的加密资产或 OpenD 不支持的代码），显示明确的“暂未接入真实数据/行情不可用”，不得显示模拟数字。
- 页面上的市场摘要如果目前只有静态值：要么接入已经确认可从 OpenD 获取的真实指数/市场数据，要么先显示不可用；不得保留静态数字冒充实时数据。
- 保留证券代码/名称的静态“导航清单”是允许的，但价格、涨跌、OHLC、历史行情等市场数据必须来自真实数据源。
- 为正常认证流程和真实行情展示保留相关自动测试。

### 不做

- 不在本任务中完成正式邮箱验证、找回密码或生产注册体系扩展。
- 不在本任务中完成生产部署、PostgreSQL、HTTPS、支付或邮件服务。
- 不把管理员用户名、邮箱、密码写入代码、`.env.example` 或 GitHub。
- 不创建自动登录、免密码后门或固定万能密码。
- 不为了补齐数据而抓取未经授权的网站行情。
- 不把离线通达信校准样本当成网页实时行情。
- 不对公式引擎做与本任务无关的重构。
- 不把历史决策文档中的管理员审查方案当作当前运行时要求。

## 相关文件/模块

- `AGENTS.md`
- `docs/decisions/0003-development-admin-review-and-real-data-policy.md`
- `frontend/src/App.vue`
- `frontend/src/components/AuthGate.vue`
- `frontend/src/components/MarketChart.vue`
- `frontend/src/data/marketData.js`
- `core/views.py`
- `quant_site/settings.py`
- `core/tests.py`
- 相关前端测试文件（如仓库已有测试框架）

## 技术与安全约束

- 遵守根目录 `AGENTS.md`。
- 不提交任何秘密信息、本地数据库、日志或用户数据。
- 不进行任务范围之外的重构。
- Django Session 继续作为本地开发阶段认证基础；账户权限由 Django 现有认证体系管理。
- 不因为 OpenD 失败而生成、缓存或展示假价格。
- 对真实数据接口错误应有清晰可见的 UI 状态。
- 指标源码仍只保留在服务端，前端/API 不返回公式正文。

## 实现要求

1. `AuthGate.vue` 恢复登录/注册切换、访客入口和 `?register=1` 注册入口行为。
2. 后端 `auth_register`、`auth_login`、`auth_guest`、`auth_session` 和终端 API 保持原有正常认证语义，不读取或执行管理员专用审查开关。
3. 进入终端后，对当前选择证券调用真实 `/api/quote/`，并将最新价、涨跌幅、开、高、低以及数据源状态用于页面展示。
4. `marketData.js` 可继续保存市场与证券的代码/名称清单，但移除或停止消费其中的硬编码实时行情字段；`makeBars()` 不得再作为网页运行时行情后备。
5. 市场顶部摘要不得继续展示静态行情数字。没有真实来源时显示 `—` / `暂未接入`；只有确认来自真实接口的数据才能展示数值。
6. OpenD 未启动、无权限、代码不支持或接口返回错误时，前端显示明确错误/不可用状态，K 线与报价均不得伪造。
7. 保持当前 `MarketChart.vue` 真实 `/api/kline/` 逻辑及“不回退假 K 线”的原则。
8. 完成后用至少一个 OpenD 当前可用证券进行人工验证，例如 `SH.600519`；报告实际使用的代码和数据源，但不要把本地账号或敏感信息写入报告。

## 验收标准

- [x] 登录、注册和访客入口全部恢复，`?register=1` 可进入注册态。
- [x] 普通登录用户和访客按原有权限进入终端；不存在管理员专用审查门槛。
- [x] `HUNTALPHA_ADMIN_REVIEW_MODE`、`DEV_ADMIN_REVIEW_MODE` 及相关运行时代码、文案、测试已移除。
- [x] 管理员凭据没有出现在 GitHub、源码或前端构建物中。
- [x] A/H/美股等 OpenD 当前支持的测试证券，其页面最新价、涨跌幅和 OHLC 来自 `/api/quote/` 的真实 OpenD 数据。
- [x] K 线继续来自 `/api/kline/` 的真实 OpenD 数据。
- [x] 前端不再把 `marketData.js` 中静态价格/涨跌幅当作运行时行情。
- [x] `makeBars()` 或其他生成行情不会在真实数据失败时自动接管页面。
- [x] 未接入真实数据的市场/证券显示不可用，而不是模拟数字。
- [x] 顶部市场摘要不再展示硬编码静态行情值。
- [x] OpenD 断开时，页面明确显示行情不可用，并且没有假数据。
- [x] 现有指标/图表基本功能没有被本任务破坏。

## 必须运行的检查

- [x] `git diff --check`
- [x] `python manage.py check`
- [x] Django 相关自动测试：`python manage.py test core`
- [x] 前端 `npm run build`
- [x] 如仓库存在前端自动测试则运行相关测试；当前仓库没有前端自动测试脚本。
- [x] 使用已开启的富途 OpenD 对至少一个真实证券进行报价 + K 线人工验证。
- [x] 验证 OpenD 不可用场景时页面不会出现生成/静态假行情。

## Codex Completion Report

- Branch: `codex/001-dev-admin-review-and-real-data`
- Commits: `e5c45ee`（本次恢复标准认证流程并移除管理员审查模式）；`564685f`（原 PR 的真实行情实现，现仍保留）。本 Completion Report 位于随后提交的 Task 001 文档更新中。
- Push: `e5c45ee` 已成功 Push 到 `origin/codex/001-dev-admin-review-and-real-data`；本次文档更新将在提交后 Push。
- Summary: 按 PR #2 最新产品决定撤销管理员专用审查模式，恢复完整登录/注册/访客流程；保留富途 OpenD 真实报价、涨跌幅、OHLC、K 线和 OpenD 不可用时的显式错误，不允许假数据回退。
- Files changed: 本次最终提交涉及 `.env.example`、`quant_site/settings.py`、`core/views.py`、`core/tests.py`、`frontend/src/App.vue`、`frontend/src/components/AuthGate.vue`、`frontend/src/i18n.js`、`docs/tasks/001-dev-admin-review-and-real-data.md`；真实行情改造涉及的 `frontend/src/components/MarketChart.vue` 和 `frontend/src/data/marketData.js` 保持在 PR 中。
- Checks run: `git diff --check` 通过；`python manage.py check` 通过，只有既有的两个 `core` 模型 `DEFAULT_AUTO_FIELD` warning；`python manage.py test core` 通过，20 项测试全部通过；`npm run build` 通过；`frontend/package.json` 没有前端自动测试脚本。代码静态核验确认运行时配置、后端和前端不再引用管理员审查模式或其文案。
- Real-data verification: 原 PR 已使用当前富途 OpenD 和 `SH.600519` 验证快照与日线 K 线：快照价 1330.0、开 1295.88、高 1338.86、低 1295.6，最新交易日 K 线收盘 1330.0，浏览器终端数值和图表来自 `/api/quote/`、`/api/kline/`。本次修改未触碰真实行情链路；按本次要求重试 `get_snapshot.py SH.600519 --json` 时，`127.0.0.1:11111` 当前未监听并返回 timeout，因此没有把重试失败伪称为新的实时数据验证。
- Authentication verification: `AuthenticationApiTests` 保留并通过正常注册、访客、未登录终端拦截和访客 AI 限制测试；真实行情 API 测试已改为普通登录用户上下文并通过。`AuthGate.vue` 恢复登录/注册切换、`?register=1` 和访客按钮。
- Design choices: `marketData.js` 仅保留代码/名称导航清单；删除 `makeBars()` 和静态行情摘要；OpenD 连接先做 1 秒 TCP 预检并返回 503，不生成任何行情回退；认证入口不再由管理员审查模式改变。
- Unresolved issues/risks: 当前富途 OpenD 端口 `127.0.0.1:11111` 在本次重试时未监听，若要复现实时人工验证需重新启动/确认 OpenD；顶部市场指数摘要当前显示“暂未接入真实市场指数”，待后续接入 OpenD 真实指数源；`python manage.py check` 的两个 `DEFAULT_AUTO_FIELD` warning 为既有问题；生产环境安全配置仍需独立任务处理。
- PR: [#2 — feat: add admin review gate and real market data](https://github.com/kuashan/huntalpha/pull/2)

## Review

由 ChatGPT/用户验收后填写：

- Result:
- Notes:
