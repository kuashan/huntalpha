# Task 005.1.4 — Crypto Market Data Foundation

Status: `IN_PROGRESS`

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

## First Review Fixes — in progress

本轮修复范围：

- Coinbase `market_trades` sequence 按 product 隔离；heartbeat sequence 不参与 product sequence。
- heartbeat 使用 monotonic freshness 参与 liveness；超时会主动关闭当前连接并触发重连，且按 connection generation 防止重复 close。
- desired products 与当前 connection 已实际订阅 products 分离，连接建立竞态和动态加入 BTC/ETH 通过同步差集处理。
- `snapshot` 只建立 sequence/dedup baseline，不作为增量成交；只有 `update` 驱动 OHLCV。
- REST authoritative reconciliation 不再按本机 receive time 盲目 replay；重连校准完成后通过 provider callback 发布到 Registry/StateStore。
- trade-id bounded FIFO eviction 保持 set/deque 一致。
- Coinbase Exchange quote 使用 `ticker.volume`，24h change 使用真实 `ticker.price` 与 `stats.open`，缺失时保持 `null`。
- Crypto 默认市场选项和 provider-aware UI 文案已更新；通用 disclaimer 不再错误声明所有行情来自 Futu OpenD。

本轮未新增 migration、未写入正式数据库，Task 与 Worklog 保持 `IN_PROGRESS`，等待 review 和浏览器验收。

## Completion Report

- Branch: `codex/005-1-4-crypto-market-data-foundation`，stacked on PR #25 head `92e009e033485e4bc3a6f2f26d92df11ec40a97d`。
- Coinbase product metadata for `BTC-USD` and `ETH-USD` returned online; the real catalog sync created two active `CRYPTO_SPOT` entries with provider symbols `BTC-USD` and `ETH-USD`。
- Real quote verification returned HTTP 200 through the Django view with `source=coinbase`; real 1-minute history returned 50 ascending bars with `source=coinbase` and `adjustment=UTC`。
- Real built-in indicator verification used 60 Coinbase BTC 1-minute bars: MA, MACD and RSI all produced drawing points through the existing frontend indicator implementation。
- One existing enabled private Formula was run against 1000 real Coinbase daily bars through the existing server Formula path; the response reported `engine=tdx-server-v2`, `source=coinbase`, and drawing data. Formula source was not printed, exported, or returned by the validation harness。
- A prior 130-second public Coinbase WebSocket soak subscribed to BTC 1-minute, BTC 5-minute and ETH 1-minute through one provider. First Review Fixes added a further 150-second active multi-product soak: dynamic ETH/BTC-period subscription stayed on one connection generation, heartbeat age remained sub-second at the final sample, no sequence-gap or heartbeat-timeout status occurred, and an intentional socket close recovered through a new generation, REST reconciliation, and `live` promotion with both products subscribed。
- Migration: `core/migrations/0010_alter_accountprofile_default_market_and_more.py`。
- Migration safety backup: `C:\Users\Administrator\huntalpha-db-backups\huntalpha-local-db-20260906-112723-902738.sqlite3`; SHA-256 `44575d0f1b9c64b7e0c7981622c00333813887d02c029d01577a2822ee34aed9`; `integrity_check: ok`。
- Formal database migration and the real `sync_symbol_catalog --market crypto` completed without deleting or rebuilding data. Formula count remained 4。
- Validation before this review round: `python manage.py check` passed with the repository's existing auto-primary-key warnings; `python manage.py test core` passed 145/145; `python manage.py makemigrations --check` reported no changes; frontend realtime and indicator tests passed; `npm run build` passed; `git diff --check` passed。First Review Fixes added deterministic state-machine and provider-aware UI coverage; the final core suite passed 154/154, with no migration changes。
- The local HTTP services returned 200 for the frontend root and Django Admin login page. The desktop browser automation helper was unavailable, so no screenshot/DOM claim is made here；the real provider/API and automated UI contract checks were completed instead。
- Known risks: Coinbase public REST/WebSocket rate limits and availability are external dependencies；production deployment still needs the existing task's SPA history fallback and process lifecycle configuration. No credential, tick, or realtime bar is persisted。
