# Task 001 — 开发阶段管理员审查入口与真实行情清理

Status: IMPLEMENTED

## 背景

HuntAlpha 仍处于开发阶段。当前前端每次打开都会进入完整登录/注册/访客页面，影响产品审查效率；同时部分前端展示数据仍来自 `frontend/src/data/marketData.js` 中的静态/演示值。

另一方面，Django 后端已经通过本机富途 OpenD `127.0.0.1:11111` 提供真实快照和历史 K 线，`MarketChart.vue` 的 K 线也已经走 `/api/kline/`，并且失败时不会生成假 K 线。

本任务依据：`docs/decisions/0003-development-admin-review-and-real-data-policy.md`。

## 目标

1. 在开发阶段提供一个只允许 Django 管理员/工作人员账户进入的前端审查模式，方便项目所有者直接审查网站。
2. 清除当前前端可见的静态/演示行情价格和涨跌幅；对于富途 OpenD 支持的数据，全部使用真实运行时数据。
3. OpenD 或真实数据不可用时明确显示不可用，不允许回退到模拟/生成行情。

## 范围

### 必须做

- 为开发环境增加明确的“管理员审查模式”配置。
- 管理员审查模式下：
  - 前端只保留管理员/工作人员登录；
  - 隐藏或禁用注册入口；
  - 隐藏或禁用访客入口；
  - 普通非 staff/superuser 用户不能通过该模式进入前端终端。
- 复用 Django 现有账户、密码校验和 Session，不创建硬编码管理员凭据。
- 将管理员审查模式做成环境化配置，默认值必须安全；不得形成无法关闭的生产后门。
- 当前支持证券的前端最新价、涨跌幅、开高低等展示改为调用后端真实行情接口 `/api/quote/<code>/`。
- 保留现有 `/api/kline/<code>/` 的真实 OpenD K 线数据流，不增加任何演示回退。
- 清理/停止使用 `frontend/src/data/marketData.js` 中的硬编码价格、涨跌幅和生成行情作为网页运行时数据。
- 如果市场/证券当前没有真实数据源（例如当前未接入的加密资产或 OpenD 不支持的代码），显示明确的“暂未接入真实数据/行情不可用”，不得显示模拟数字。
- 页面上的市场摘要如果目前只有静态值：要么接入已经确认可从 OpenD 获取的真实指数/市场数据，要么先显示不可用；不得保留静态数字冒充实时数据。
- 保留证券代码/名称的静态“导航清单”是允许的，但价格、涨跌、OHLC、历史行情等市场数据必须来自真实数据源。
- 为管理员审查模式和真实行情展示增加相关自动测试。

### 不做

- 不在本任务中完成正式用户注册/邮箱验证/找回密码体系。
- 不在本任务中完成生产部署、PostgreSQL、HTTPS、支付或邮件服务。
- 不把管理员用户名、邮箱、密码写入代码、`.env.example` 或 GitHub。
- 不创建自动登录、免密码后门或固定万能密码。
- 不为了补齐数据而抓取未经授权的网站行情。
- 不把离线通达信校准样本当成网页实时行情。
- 不对公式引擎做与本任务无关的重构。

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
- 管理员身份由 Django `is_staff` / `is_superuser` 等现有权限字段判断；不要在前端自行伪造管理员角色。
- 管理员审查模式必须由服务端配置决定，不能仅靠隐藏前端按钮实现权限控制。
- Django Session 继续作为本地开发阶段认证基础。
- 不因为 OpenD 失败而生成、缓存或展示假价格。
- 对真实数据接口错误应有清晰可见的 UI 状态。

## 实现要求

1. 在 Django 配置中增加开发审查模式开关，例如环境变量形式；名称可由 Codex 根据现有风格确定，但必须记录在 `.env.example`，且不得包含真实凭据。
2. 后端登录/会话返回应能让前端可靠判断当前用户是否为允许进入开发审查模式的管理员/工作人员；权限判断必须在后端执行。
3. 管理员审查模式启用时，普通用户、注册和访客不得绕过限制访问终端 API。
4. 前端 `AuthGate.vue` 在该模式下显示清晰的“管理员审查登录”状态，不显示公开注册/访客按钮。
5. 进入终端后，对当前选择证券调用真实 `/api/quote/`，并将最新价、涨跌幅、开、高、低以及数据源状态用于页面展示。
6. `marketData.js` 可继续保存市场与证券的代码/名称清单，但移除或停止消费其中的硬编码实时行情字段；`makeBars()` 不得再作为网页运行时行情后备。
7. 市场顶部摘要不得继续展示静态行情数字。没有真实来源时显示 `—` / `暂未接入`；只有确认来自真实接口的数据才能展示数值。
8. OpenD 未启动、无权限、代码不支持或接口返回错误时，前端显示明确错误/不可用状态，K 线与报价均不得伪造。
9. 保持当前 `MarketChart.vue` 真实 `/api/kline/` 逻辑及“不回退假 K 线”的原则。
10. 完成后用至少一个 OpenD 当前可用证券进行人工验证，例如 `SH.600519`；报告实际使用的代码和数据源，但不要把本地账号或敏感信息写入报告。

## 验收标准

- [ ] 开发审查模式开启时，前端登录页面只提供管理员/工作人员登录，不提供注册与访客入口。
- [ ] 普通非管理员用户无法绕过前端直接访问受保护终端 API。
- [ ] 管理员凭据没有出现在 GitHub、源码或前端构建物中。
- [ ] 管理员登录成功后可以正常进入前端终端并保持 Session。
- [ ] A/H/美股等 OpenD 当前支持的测试证券，其页面最新价、涨跌幅和 OHLC 来自 `/api/quote/` 的真实 OpenD 数据。
- [ ] K 线继续来自 `/api/kline/` 的真实 OpenD 数据。
- [ ] 前端不再把 `marketData.js` 中静态价格/涨跌幅当作运行时行情。
- [ ] `makeBars()` 或其他生成行情不会在真实数据失败时自动接管页面。
- [ ] 未接入真实数据的市场/证券显示不可用，而不是模拟数字。
- [ ] 顶部市场摘要不再展示硬编码静态行情值。
- [ ] OpenD 断开时，页面明确显示行情不可用，并且没有假数据。
- [ ] 现有指标/图表基本功能没有被本任务破坏。

## 必须运行的检查

- [ ] `git diff --check`
- [ ] `python manage.py check`
- [ ] Django 相关自动测试
- [ ] 前端 `npm run build`
- [ ] 如仓库存在前端自动测试则运行相关测试
- [ ] 使用已开启的富途 OpenD 对至少一个真实证券进行报价 + K 线人工验证
- [ ] 临时断开/模拟 OpenD 不可用场景，确认页面不会出现生成/静态假行情

## Codex Completion Report

- Branch: `codex/001-dev-admin-review-and-real-data`
- Commit: `564685f`（实现提交；本报告为后续文档提交）
- Push: 已成功 Push 到 `origin/codex/001-dev-admin-review-and-real-data`
- Summary: 增加开发阶段管理员审查模式；服务端强制 staff/superuser 权限；前端报价、OHLC 和 K 线只使用富途 OpenD 真实数据；OpenD 不可用时显示明确错误并保持空数据。
- Files changed: `.env.example`、`quant_site/settings.py`、`core/views.py`、`core/tests.py`、`frontend/src/App.vue`、`frontend/src/components/AuthGate.vue`、`frontend/src/components/MarketChart.vue`、`frontend/src/data/marketData.js`、`frontend/src/i18n.js`。
- Checks run: `git diff --check` 通过；`python manage.py check` 通过（仅有既有 AutoField warning）；`python manage.py test core`：24 项通过；`npm run build` 通过；仓库没有前端自动测试脚本。
- Real-data verification: 使用当前富途 OpenD 和 `SH.600519` 验证快照与日线 K 线；快照返回价 1330.0、开 1295.88、高 1338.86、低 1295.6，最新交易日 K 线收盘 1330.0。浏览器终端的数值和图表均来自 Django `/api/quote/`、`/api/kline/`。
- Admin-review verification: 开启 `HUNTALPHA_ADMIN_REVIEW_MODE=1` 后，登录页只显示管理员审查登录，注册/访客入口隐藏；服务端拒绝普通用户、访客和直接 API 绕过；staff 登录可保持 Django Session 并进入终端。用于验证的临时本地 staff 账户已删除。
- Design choices: 开关默认关闭且仅在 `DEBUG=True` 时生效；权限在后端 login/session/terminal API 三层执行；`marketData.js` 仅保留代码/名称导航清单；删除 `makeBars()` 和静态行情摘要；OpenD 连接先做 1 秒 TCP 预检并返回 503，不生成任何行情回退。
- Unresolved issues/risks: `python manage.py check` 仍报告 `core` 模型未显式设置 `DEFAULT_AUTO_FIELD` 的既有 warning；顶部市场指数摘要当前显示“暂未接入真实市场指数”，待后续接入 OpenD 真实指数源；当前 checkout 的本地数据库原为空，实际使用管理员审查模式前需由项目所有者在本地创建/保留自己的 staff/superuser 账户，凭据不会进入仓库。
- PR: [#2 — feat: add admin review gate and real market data](https://github.com/kuashan/huntalpha/pull/2)

## Review

由 ChatGPT/用户验收后填写：

- Result:
- Notes:
