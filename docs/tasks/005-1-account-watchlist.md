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
- 正式本地迁移前备份：`C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-130406-832263.sqlite3`。
- 备份 SHA-256：`028e428644eb029081268e1aa839745200ae7f7e8bc5d0b80a14ee1fb74c5cd4`；`integrity_check: ok`。

## Completion Report

- 分支：`codex/005-1-account-watchlist`
- Commit：待提交
- PR：待创建
- 自动测试：`python manage.py test core`，64 项全部通过。
- `python manage.py check`：通过，保留既有 MarketSymbol AutoField warning。
- `npm run build`：通过。
- `git diff --check`：通过。
- `python manage.py makemigrations --check`：通过，No changes detected。
- 正式数据库 Formula 总数仍为 4；未读取、输出或修改 Formula source。
- 正式数据库、备份、日志、session、密钥和 `.env` 未加入 Git。
- 未实现或伪造 Pro entitlement；当前账户额度按 Free=10。
- 浏览器已验证真实搜索、☆→黄色★、★→☆、额度计数和 Crypto unavailable 行为。
