# Task 011 — FREE / PRO 会员等级与自选冻结规则

Status: `READY_FOR_CODEX`

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
