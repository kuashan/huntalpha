# Task 005.1.1 — 账户等级皇冠徽章（FREE / PRO）

Status: IMPLEMENTED

## 范围

在主界面右上角账户名后增加账户等级展示层，不改变认证、Watchlist、额度、市场或行情业务逻辑。

## 实现摘要

- 复用 `frontend/src/components/AccountTierBadge.vue`，使用仓库内原创内联 SVG 现代金融身份徽章：顶部几何皇冠、中央头像圆形、轻量对称装饰和底部等级横幅。
- FREE 使用克制的蓝色皇冠/头像环/横幅，PRO 使用同一结构体系的金色变体。
- `FREE` / `PRO` 文本位于底部横幅内部，不使用皇冠外部文字、emoji、第三方图标或外部资源。
- 头像槽优先支持未来真实 `avatarUrl`；当前使用用户名称首字母，缺少名称时使用中性几何用户符号。
- 右上角仅对已登录账户渲染徽章；访客保留访客身份文字但不显示正式等级徽章。
- `core/watchlist.py` 增加统一 `resolve_account_tier()`、`resolve_watchlist_limit()` 和 `account_tier_payload()`。
- 当前没有真实 subscription/entitlement 模型，因此所有 authenticated 用户真实返回 `tier: free`、`tier_label: FREE`、`watchlist_limit: 10`；`PRO` 和 20 的配置入口保留给未来真实 entitlement resolver。
- auth/session、register、login 返回 tier 字段；匿名/访客返回 `tier: null`、`tier_label: null`、`watchlist_limit: null`。

## Completion Report

- 分支：`codex/005-1-1-account-tier-badge`
- 设计方向：现代金融身份徽章（Account Crest），由皇冠、中央头像圆形和底部等级横幅组成。
- FREE：蓝色、标准版、克制的几何皇冠与横幅，横幅内部显示 `FREE`。
- PRO：金色、同一套皇冠/头像/装饰/横幅结构，横幅内部显示 `PRO`；当前不会为任何真实账户伪造 PRO。
- 中央头像圆形：双层圆环，当前 fallback 为用户名称首字母；支持未来传入 `avatarUrl`，本轮没有头像上传系统。
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
