# Task 005.1 — 账户自选列表、搜索星标收藏与全市场额度

Status: IMPLEMENTED

## 范围

将左侧证券区域从默认市值榜单改为真实账户自选列表；保留当前市场完整证券目录搜索，并通过服务器确认后的星标状态添加或取消自选。`market_leaders` 后端能力、MarketSymbol 目录、真实报价和 Crypto unavailable preview 均保留。

## 实现摘要

- 新增 `core.WatchlistEntry`，关联 Django 内置 User 与 `MarketSymbol`，只保存账户—证券关系和创建时间。
- 通过唯一约束 `(user, symbol)` 防止重复收藏；用户删除时级联删除关系，证券使用 `PROTECT`，目录不会因自选关系被物理删除。
- 新增 `GET/POST /api/watchlist/` 与 `DELETE /api/watchlist/<code>/`。
- 自选额度由后端 resolver 统一执行：Free=10、未来 Pro=20；当前仓库没有真实 entitlement/subscription 模型，因此所有真实账户按 Free=10，未使用 staff、superuser 或用户名伪造 Pro。
- 搜索结果一次查询当前账户的收藏 code set，返回 `watchlisted`，避免逐证券 N+1 查询。
- 写接口沿用 Django CSRF 校验，增加 `/api/csrf/` 取 token，并扩展开发 CORS 对 DELETE 与 `X-CSRFToken` 的支持。
- 前端无搜索词只请求 `/api/watchlist/?market=...`；有搜索词仍请求当前市场完整目录；列表显示轻量身份与真实 quote/change，不批量请求 K 线、指标或 AI。
- Crypto 继续只显示 BTC/ETH preview；没有真实 Crypto MarketSymbol/provider，因此不能收藏、不能请求假 quote/K 线。

## 数据库变更

- `core/migrations/0007_watchlistentry.py`：创建自选关系表、唯一约束和用户查询索引。
- `core/migrations/0008_alter_calibrationdataset_id_alter_indicator_id_and_more.py`：同步仓库既有主键迁移状态，避免 `makemigrations --check` 报遗漏；不涉及 Formula 业务字段。

### Migration safety

迁移前正式备份：

- path: `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-130022-326987.sqlite3`
- SHA-256: `79a208c0e3e8697c47a286996901de90149d76f7a6eecdc71ca60d520ecd5625`
- `integrity_check: ok`

应用迁移：

- `core/migrations/0007_watchlistentry.py`
- `core/migrations/0008_alter_calibrationdataset_id_alter_indicator_id_and_more.py`

迁移后验证备份：

- path: `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-130406-832263.sqlite3`
- SHA-256: `028e428644eb029081268e1aa839745200ae7f7e8bc5d0b80a14ee1fb74c5cd4`
- `integrity_check: ok`

## Completion Report

- 分支：`codex/005-1-account-watchlist`
- 实现 Commit：`b7ad4e5`（后续 Completion Report 文档更新另有提交）
- PR：[#17](https://github.com/kuashan/huntalpha/pull/17)，目标 `main`，未合并
- 本轮 review 修复：用户级 `select_for_update()` 锁定当前认证用户行；锁内按“重复检查 → 全局额度统计 → 创建”顺序执行，保留 `(user, symbol)` 唯一约束。
- 自动测试：`python manage.py test core`，65 项全部通过（含本轮用户行锁顺序契约测试）。
- `python manage.py check`：通过，保留既有 MarketSymbol AutoField warning。
- `npm run build`：通过。
- `git diff --check`：通过。
- `python manage.py makemigrations --check`：通过，No changes detected。
- 正式数据库 Formula 总数仍为 4；未读取、输出或修改 Formula source。
- 正式数据库、备份、日志、session、密钥和 `.env` 未加入 Git。
- 未实现或伪造 Pro entitlement；当前账户额度按 Free=10。
- 浏览器已验证真实搜索、☆→黄色★、★→☆、额度计数和 Crypto unavailable 行为。

### 验收明细

- 模型：`WatchlistEntry(user, symbol, created_at)`；`user` 使用 Django 内置认证用户，`symbol` 关联 `MarketSymbol`，`(user, symbol)` 唯一，`(user, created_at)` 索引。
- API：`GET/POST /api/watchlist/`、`DELETE /api/watchlist/<code>/`；写接口需要 Django CSRF token，账户身份始终来自 session `request.user`。
- 额度：全市场共享，Free=10、预留 Pro=20；当前没有真实 Pro entitlement，所有账户按 Free=10。第 11 条由后端以 `watchlist_limit_reached`/HTTP 409 拒绝；重复 POST 幂等。
- Visitor：可读取空状态但不能创建持久自选；Crypto BTC/ETH preview 不是 `MarketSymbol`，不可收藏、不可请求假 quote/K 线。
- 左栏：无搜索词加载当前市场自选；有搜索词加载当前市场真实目录并带一次性 `watchlisted` 标记；保留 `market_leaders` 后端，不再作为左栏默认请求；移除市值列；☆/★ 点击阻止行选择事件。
- 性能边界：自选/搜索仅请求可见证券的轻量 quote/change；未为整个列表加载 K 线、Formula 或 AI。
- 迁移：正式数据库已在备份并确认 `integrity_check: ok` 后应用 `0007`、`0008`；未执行 flush/reset，Formula 仍为 4 条。
- 并发边界：本地 SQLite 无法完整模拟 PostgreSQL `SELECT FOR UPDATE` 的并发阻塞语义；实现使用数据库无关的 Django ORM 用户行锁，并以稳定的代码契约与额度/重复收藏回归测试验证锁和检查顺序。
- 浏览器：真实搜索 `600519` 返回真实证券与 OpenD 报价；添加后显示黄色 ★ 与 `1 / 10`，取消后恢复 ☆ 与 `0 / 10`；Crypto 显示 unavailable，无假价格。
