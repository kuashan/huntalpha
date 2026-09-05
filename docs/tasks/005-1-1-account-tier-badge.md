# Task 005.1.1 — 账户等级皇冠徽章（FREE / PRO）

Status: IMPLEMENTED

## 范围

在主界面右上角账户名后增加账户等级展示层，不改变认证、Watchlist、额度、市场或行情业务逻辑。

## 实现摘要

- 新增 `frontend/src/components/AccountTierBadge.vue`，使用仓库内原创内联 SVG 几何皇冠。
- FREE 使用克制的蓝色渐变皇冠，PRO 使用同一轮廓体系的金色渐变皇冠。
- `FREE` / `PRO` 文本位于皇冠主体内部，不使用皇冠外部文字、emoji、第三方图标或外部资源。
- 右上角仅对已登录账户渲染徽章；访客保留访客身份文字但不显示正式等级徽章。
- `core/watchlist.py` 增加统一 `resolve_account_tier()`、`resolve_watchlist_limit()` 和 `account_tier_payload()`。
- 当前没有真实 subscription/entitlement 模型，因此所有 authenticated 用户真实返回 `tier: free`、`tier_label: FREE`、`watchlist_limit: 10`；`PRO` 和 20 的配置入口保留给未来真实 entitlement resolver。
- auth/session、register、login 返回 tier 字段；匿名/访客返回 `tier: null`、`tier_label: null`、`watchlist_limit: null`。

## Completion Report

- 分支：`codex/005-1-1-account-tier-badge`
- 设计方向：嵌字皇冠章。
- FREE：蓝色、标准版、克制的几何皇冠，内部嵌入 `FREE`。
- PRO：金色、同一套外轮廓与尺寸体系，内部嵌入 `PRO`；当前不会为任何真实账户伪造 PRO。
- 当前没有真实 Pro entitlement；已登录普通用户实际显示 FREE，访客不显示正式等级徽章。
- 后端 tier 返回：`tier`、`tier_label`、`watchlist_limit`，同时出现在 auth/session 状态和 user payload 中。
- Watchlist 配置仍为 Free=10、Pro=20；当前真实账户使用 Free=10。
- 无数据库迁移，无数据库写入。
- Formula 及其 source 未读取、未修改。

### 验证

- `python manage.py check`：通过，保留既有 `MarketSymbol` AutoField warning。
- `python manage.py test core`：通过，包含认证 tier、访客 null tier、非 Pro 推断和徽章契约测试。
- `python manage.py makemigrations --check`：通过，No changes detected。
- `npm run build`：通过。
- `git diff --check`：通过。
