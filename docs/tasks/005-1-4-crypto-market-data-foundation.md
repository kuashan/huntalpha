# Task 005.1.4 — Crypto Market Data Foundation

Status: `IMPLEMENTED`

## Scope

将 Crypto 作为 HuntAlpha 的正式市场，第一阶段通过 Coinbase 官方公开 Market Data 接入：

- `BTC-USD` → `CC.BTC-USD`
- `ETH-USD` → `CC.ETH-USD`

Crypto 使用 `MarketSymbol`、`WatchlistEntry`、统一 Quote/Kline API、内置指标、自定义 Formula 和 `RealtimeRegistry`。不创建第二套 Crypto Registry、StateStore 或 Formula pipeline。

## Provider and data rules

- Provider: `coinbase`; exchange: `Coinbase`; security type: `CRYPTO_SPOT`。
- Catalog 从 Coinbase product metadata 同步；不预置假证券、价格或历史数据。
- Quote 由 Django 后端读取 Coinbase public ticker/stats；浏览器不直接连接 Coinbase。没有 provider 能提供的字段保持 `null`，不可用时明确返回 unavailable。
- Historical Kline 使用 Coinbase Exchange public `/products/{product_id}/candles`，单次最多 300 根，分页有上限，结果去重、升序、裁剪，不用上一根 close 补空 bar。
- 原生周期使用真实 candles；30 分钟、2 小时、4 小时、周线、月线由真实源 bar 按 UTC 固定边界聚合。缺少 amount/turnover rate 时保持 `null`。
- Realtime 使用 Coinbase Advanced Trade public `market_trades` 与 `heartbeats`。成交按 trade id 有界去重，按 UTC bucket 聚合 OHLCV；heartbeat 不生成 K 线。产品级上游订阅在进程内复用，序列缺口进入 reconnecting 并使用 REST 权威快照校准。
- 不保存 realtime tick/bar 到数据库，不保存 Coinbase credential，不允许静态、随机、网页抓取或 provider 失败假回退。

## Database and account behavior

- `MarketSymbol.market` 和 `AccountProfile.default_market` 增加 `crypto`，通过正式 migration 应用。
- `sync_symbol_catalog --market crypto` 只写入真实 Coinbase product catalog，单独 provider scope 不会把 Futu 证券标记 inactive。
- Crypto 自选继续使用既有 `WatchlistEntry` 与全市场 Free=10 / Pro=20 额度；BTC/ETH 只有在真实 catalog 同步成功后才可收藏。
- Formula source 保留在服务端，不读取、打印或提交到 Git；正式数据库中的 Formula 记录只验证数量为 4。

## Validation plan

自动测试覆盖：provider mapping/catalog isolation、REST 分页与 300 上限、空历史不补假 bar、UTC 聚合与缺失字段、Quote 路由、watchlist/search、trade 聚合/去重/边界、heartbeat、sequence gap、reconnect/reconcile、跨 period/product 共享和无数据库 tick 写入。

真实验收包括 Coinbase product/catalog、BTC/ETH quote、历史 K 线、2–5 分钟 BTC 1 分钟实时成交跨分钟边界、内置指标、一个现有私有 Formula、双消费者/跨周期共享及断线恢复。任何 provider 限制都必须显示 unavailable，不以测试数字替代真实数据。

## Completion Report

- Branch: `codex/005-1-4-crypto-market-data-foundation`，stacked on PR #25 head `92e009e033485e4bc3a6f2f26d92df11ec40a97d`。
- Coinbase product metadata for `BTC-USD` and `ETH-USD` returned online; the real catalog sync created two active `CRYPTO_SPOT` entries with provider symbols `BTC-USD` and `ETH-USD`。
- Real quote verification returned HTTP 200 through the Django view with `source=coinbase`; real 1-minute history returned 50 ascending bars with `source=coinbase` and `adjustment=UTC`。
- Real built-in indicator verification used 60 Coinbase BTC 1-minute bars: MA, MACD and RSI all produced drawing points through the existing frontend indicator implementation。
- One existing enabled private Formula was run against 1000 real Coinbase daily bars through the existing server Formula path; the response reported `engine=tdx-server-v2`, `source=coinbase`, and drawing data. Formula source was not printed, exported, or returned by the validation harness。
- A 130-second public Coinbase WebSocket soak subscribed to BTC 1-minute, BTC 5-minute and ETH 1-minute through one provider. It stayed `live`, crossed multiple UTC buckets, and reported product refcounts `BTC-USD=2`, `ETH-USD=1`。Heartbeat sequence messages are tracked for liveness but never become bars；sequence gaps enter reconnecting and trigger REST reconciliation。
- Migration: `core/migrations/0010_alter_accountprofile_default_market_and_more.py`。
- Migration safety backup: `C:\Users\Administrator\huntalpha-db-backups\huntalpha-local-db-20260906-112723-902738.sqlite3`; SHA-256 `44575d0f1b9c64b7e0c7981622c00333813887d02c029d01577a2822ee34aed9`; `integrity_check: ok`。
- Formal database migration and the real `sync_symbol_catalog --market crypto` completed without deleting or rebuilding data. Formula count remained 4。
- Validation: `python manage.py check` passed with the repository's existing auto-primary-key warnings; `python manage.py test core` passed 145/145; `python manage.py makemigrations --check` reported no changes; frontend realtime and indicator tests passed; `npm run build` passed; `git diff --check` passed。
- The local HTTP services returned 200 for the frontend root and Django Admin login page. The desktop browser automation helper was unavailable, so no screenshot/DOM claim is made here；the real provider/API and automated UI contract checks were completed instead。
- Known risks: Coinbase public REST/WebSocket rate limits and availability are external dependencies；production deployment still needs the existing task's SPA history fallback and process lifecycle configuration. No credential, tick, or realtime bar is persisted。
