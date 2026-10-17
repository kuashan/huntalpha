# Task 011 — FREE / PRO 会员等级与自选冻结规则

Status: `IN_PROGRESS / VALIDATION_PENDING`（独立开发分支已经实现主体，未合并、未部署）

## 背景与已批准决定

当前 `core/watchlist.py::resolve_account_tier()` 将全部已登录账户视为 FREE；前端 FREE / PRO 徽章只是已存在的显示基础。用户已经批准 Django Admin 为用户设置真实 FREE / PRO 等级：新注册默认 FREE；FREE 自选最多 10 个，PRO 最多 20 个。后台工作人员 / 超级管理员身份与 PRO 互不等价。其余高级会员权益不在本任务实现。

## 必须实现

1. 增加**持久化、单一事实源**的账户会员等级（FREE / PRO），允许既有账户无缝回填或默认 FREE；迁移不丢失用户、Session、WatchlistEntry 或 AccountProfile。
2. Django Admin「用户」列表显示会员等级，编辑表单允许**真正具备 is_superuser 权限**的管理员设置等级；其他 staff 无权通过表单、admin action、直接提交 POST 或批量编辑绕过权限。等级变化只修改会员状态，不修改 Django 的 `is_staff`/`is_superuser`。
3. `resolve_account_tier()`、`resolve_watchlist_limit()`、`account_tier_payload()` 及所有相关 API 从后端真实会员状态计算，前端右上角徽章、个人中心、收藏配额展示使用同一后端结果，禁止仅靠前端标记或用户身份猜测。
4. 后端 WatchlistEntry 按 `(created_at ASC, id ASC)` 决定**原始收藏顺序**。账户可用的最前 N 条为活动收藏，超出等级额度的剩余记录为冻结收藏：FREE N=10、PRO N=20。
5. PRO→FREE 例子：原有 18 条，最早 10 条仍活动、后 8 条冻结；冻结行不删除、不出现在正常自选 API/列表中，保留创建时间、ID、用户与证券关系。FREE 删掉活动收藏后，后续最早的冻结行自动进入前 10，无需额外手工操作。FREE→PRO 时按原顺序恢复最多 20 条，不得重新按升级时间排序。
6. API 的活动收藏数量、剩余可用配额均按当前真实活动状态计算；冻结历史行不能当作可用空位。已满额度新增拒绝（现有 409 语义保持）。重复收藏不重排 `created_at`、不重复建行，也不能借此越过冻结规则。保留原有事务/并发保护和 CSRF/权限控制。
7. 与 PR #34 的全市场统一自选页面兼容：正常自选仅显示活动记录，且不依顶部市场筛选；账户切换、后台修改会员等级后，API 能反映实际最新等级。若 PR #34 尚未合并，以其已完成实现为集成基线，避免重做 UI。

## 不做

- 支付、订阅扣费、到期续费、价格、AI/Scanner/指标权益、会员等级历史账单。
- 以 `is_staff`、`is_superuser`、用户名、固定邮箱等推断 PRO。
- 删除冻结数据、复制/迁移正式数据库、重建图表或行情链路。
- 修改 PR #26 Coinbase、PR #33 部署或 Oracle 其他项目。

## 代码入口

`core/watchlist.py`、`core/models.py` 或独立 entitlement 模型、`core/views.py`、`core/admin.py` / Django UserAdmin、`frontend/src/components/AccountPopover.vue`、`frontend/src/components/PersonalCenter.vue`、`frontend/src/App.vue`、相应 migrations/tests。实施前检查真实 HEAD 和 PR #34 diff。

## 验收

- [ ] 新注册与旧账户默认为 FREE；仅管理员实际授权等级显示 PRO。
- [ ] staff 非 superuser 无法修改等级，包括伪造 POST；superuser 可从「用户」编辑并立即生效。
- [ ] FREE=10、PRO=20 的服务器 409 边界测试及竞态测试。
- [ ] 同一用户 18 条 PRO→FREE：活动恰好最早 10 条、冻结 8 条、数据库仍保留 18 条。
- [ ] 删除一条活动后自动解冻原第 11 条；重复收藏不改变顺序；再次升级 PRO 18 条全部可见。
- [ ] 四市场混合收藏依然按全账户、全市场排序与额度执行。
- [ ] Web 顶栏、个人中心与后端 tier 一致，浏览器不得通过修改客户端数据升级 PRO。
- [ ] migration 可在干净库与含现有 4 Formula / 原 WatchlistEntry 的库上安全执行。
- [ ] `python manage.py check`、相关后端 tests、`python manage.py makemigrations --check`、`npm run build`、`git diff --check` 有真实结果。

## 安全与实施纪律

阅读 `AGENTS.md`；从最新可审计 HEAD 开独立分支。数据迁移前需生成本地/目标独立恢复点并确认 SQLite `integrity_check: ok`，不得对用户真实数据直接做试验；新迁移可先用独立测试库验证。禁止输出 Formula source、真实用户数据或密钥。不要合并未验收 PR、不要自动部署服务器。

## Codex Completion Report

- Branch:
- Commit:
- Push:
- Summary:
- Files changed:
- Checks run:
- Migration/rollback evidence:
- Unresolved issues:
- PR:

## Review

由 ChatGPT/用户验收后从 `IMPLEMENTED` 变为 `ACCEPTED`。


## Task 011 implementation progress — 2026-10-17

- 基线：站点目前已验收的 PR #34 + Task 013 PR #36，目标代码基线 SHA `2dcef7b7d43877f32b9bf88ff6bedf1a8cfe5a60`；由于 PR #34/#36 仍未合并到 main，**本任务采用独立 stacked branch/PR**，不能覆盖线上已验收版本。用户已报告 Task 013 由 Codex 部署并完成网页验收，本任务不再重复处理版本号。
- Branch: `feat/011-free-pro-membership-watchlist-20261017`。
- 新增持久化 AccountMembership FREE/PRO；新用户用信号默认 FREE；`0011_accountmembership` 将旧用户平滑回填 FREE。后端权限源为数据库，不通过 staff/superuser 判定会员等级。
- Django UserAdmin 的已注册用户列表展示会员等级；编辑会员 inline 只向真正的 superuser 开放，未单独注册可绕过的 Membership Admin。
- 四市场全账户自选最早 N 条 active（按 created_at/id），其余冻结记录不删除；自选 API、搜索 watchlisted 标记和数量统计均排除冻结项；删除 active 后下一个 frozen 自动上位，前端重新载入自选列表。
- 实际独立服务器测试：新增会员/冻结测试 + 原有自选测试 **21/21 PASS**，其中包含真实管理员页面 POST（superuser 可授权、普通 staff 伪造字段无效）。Django `makemigrations --check --dry-run` **No changes detected**。Python ast parse PASS。现有 staging 临时副本与 Task011 前端 overlay 执行 `npm ci` 和 `npm run build` **PASS**。非精确分支全量前端校验，不能冒充 CI。
- 单独的旧版 SQLite 合成回填试验 PASS：迁移前备份 `PRAGMA integrity_check=ok`，旧用户 1、12 条自选和四条**合成**测试公式经 `0011` 后完整保留，旧用户会员默认 FREE；所有合成数据库及备份均已清理。
- 两项既有 Django W042 AutoField 警告来自未修改的 AccountProfile、MarketSymbol；Task011 新 AccountMembership 使用与当前项目一致的 AutoField，没有新增迁移差异。
- **尚待**：精确代码/前端全量验证、完整 Django 套件、后台浏览器验收及正式数据库独立备份/迁移规划。不能因为上述隔离 PASS 而声明生产已更新。
- **禁止合并、部署、迁移或修改 Cloudflare、其他容器**，待正式审核和用户单独批准。

## Task 011 production API address blocker — 2026-10-17

- 用户明确要求只使用正式线上网站，并批准将前端 API 地址修复作为 Task 011 必需的上线修复。
- Codex 在精确 PR #38 旧提交 `66b8e6ed1299ce8363c0203eb227fd03fe0d2fcd` 上验证：Django core 225/225 PASS、migrations / check / production frontend build PASS；但发现编译后静态文件仍将请求发向访客计算机的 `http://127.0.0.1:8003`，因此**中止正式备份/迁移/部署**。生产仍运行 Task 013 PR36 镜像，没有动数据库。
- 本次只调整前端 API 请求地址（不会改变业务 API、会员额度、指标权限或图表逻辑）：`frontend/src/apiBase.js` 在正式生产构建中固定使用**当前域名同源的** `/api/...`；本地 Vite 开发通过 `vite.config.js` 的 `/api` 代理访问本地 Django，可在本地开发时使用 `VITE_API_BASE_URL` 覆盖。包括登录、访客、会员摘要、个人中心、自选、行情、SSE、图表和指标在内的七个 Vue 组件都复用同一个 API_BASE。
- Oracle **只读**探测现有网站本机访问 `/api/csrf/` 返回 200 JSON、未登录 `/api/auth/session/` 返回 401 JSON、`/api/indicators/` 返回 401 JSON，说明 Django 当前同源 /api 端点存在；这不是已认证浏览器验收。
- 新增 `frontend/src/apiBase.test.mjs`：3/3 PASS，核对生产同源强制、开发覆盖和七个 Vue 组件禁止本机 URL。
- 在旧 staging 只读副本加上当前 API 修复文件的**隔离混合源码**执行 `npm ci --ignore-scripts`、`npm run build` PASS；设置 `VITE_API_BASE_URL=http://127.0.0.1:8003` 后生产构建产物不包含该本机 URL：PASS。**这不等于精确 PR SHA 全源码构建、正式上线验收或 Django 全量回归**。
- 后续 Codex 必须在 PR #38 **最终 HEAD** 重跑 Django 完整测试、迁移检查、前端精确构建和静态产物检查；通过后按用户已批准的正式站部署流程先创建并核验数据库备份与回滚计划，再迁移、部署。任何失败停止。未经本次批准不得扩展到 Task 012、Cloudflare 配置或其他服务。
