# Task 005.1.3 — Real-time Market Data & Indicator Pipeline Foundation

Status: `IN_PROGRESS`

## Goal

建立 HuntAlpha 的统一实时行情基础设施，使真实行情能够持续驱动当前 K 线、内置指标和自定义 Formula 更新，而不是只刷新页面上的最新价格。

核心原则：

> Provider 负责提供真实市场数据；Indicator / Formula 保持原有算法；实时行情更新当前正在形成的 bar；当前 bar 变化驱动技术指标重新计算。

本任务先以 Futu OpenD 作为真实 provider 验证，但实时架构必须 provider-neutral，为后续 Coinbase 和商业行情 Vendor 接入保留统一边界。

## Current baseline

- 当前历史 K 线统一来自真实 Futu OpenD，失败时显示 unavailable，不生成假 candles。
- `MarketChart.vue` 当前按 `symbol / period / installedIndicators` 触发完整 draw：请求约 1000 根 K 线、计算指标、创建 chart/series；尚无持续 realtime stream。
- 内置指标通过前端 `commonDrawing(code, bars)` 计算。
- 自定义 Formula 继续通过后端 `/api/indicator-render/...` 计算；Formula source 不返回浏览器。
- 左拖历史分页必须继续保留。
- 当前账户行情颜色偏好和 Formula 自定义绘图颜色已经分离，实时化不得破坏这一点。

## Architecture target

```text
Exchange / Data Vendor
        ↓
Realtime Provider Adapter
        ↓
Normalized Market Event / Bar Snapshot
        ↓
Shared Realtime State + Subscription Registry
        ↓
Current Live Bar / Closed Bar
        ↓
Indicator Scheduler
        ↓
Built-in Indicators + Custom Formula
        ↓
Lightweight Charts in-place update
```

### Provider-neutral contract

Provider 层只负责真实数据，不允许出现 `FutuMACD / CoinbaseMACD / USMACD` 一类 provider-specific 指标实现。

统一事件/Bar 至少考虑：

- provider / source
- market
- symbol
- period
- time
- open / high / low / close
- volume
- amount（缺失必须为 `null`，不能伪造成 0）
- turnover_rate（缺失必须为 `null`，不能伪造成 0）
- is_closed（provider 可提供时使用）
- provider_timestamp / sequence（可获得时保留）
- revision

指标只根据自己需要的字段计算。Provider 缺少必要字段时必须明确 `unsupported / unavailable`，禁止静态默认值或伪造替代。

## Live bar semantics

实时行情不是只更新最新价。

当前未完成 bar 必须随真实行情更新：

- Open
- High
- Low
- Close
- Volume
- Amount / Turnover rate（仅 provider 真正提供时）

当前 bar 对应的指标值允许盘中变化。周期结束后 bar 进入 closed 状态；普通后续 quote 事件不能随意修改已收盘历史。若 provider 后续返回权威修正，应走 reconciliation/correction 语义，不与普通 live update 混淆。

不能用本地电脑时间简单猜所有市场的 bar 边界。优先使用 provider timestamp；若未来需要从 trades 聚合，则必须根据明确 market timezone / session 定义。

## Shared subscriptions

不能让每个浏览器对同一 `provider + symbol + period` 各自建立一份 OpenD subscription。

本任务建立 process-local：

- Provider abstraction
- Subscription Registry
- reference counting
- grace-period unsubscribe
- Realtime State / Bar Cache
- revision

当前本地阶段不部署 Redis。必须通过接口隔离，文档明确未来多进程/多服务器需要共享 Pub/Sub（例如 Redis 或专用 market gateway）。

## Browser transport

行情主要为 server → browser 单向推送。

优先使用 SSE / EventSource 等轻量可靠方案；如审查证明当前 Django runtime 下 SSE 明显不合适，可采用其他轻量 transport，但不得为了本任务无必要引入完整 Channels + Redis + Celery 基础设施。

Stream 权限必须复用现有 terminal 访问语义：真实登录账户和现有合法 Visitor 可访问；真正匿名不能意外新增公开实时行情出口。

## Historical + realtime merge

初次加载继续使用现有真实 `/api/kline/` 历史页。

合并规则：

- realtime `time == loadedBars[-1].time` → 更新当前最后一根
- realtime `time > loadedBars[-1].time` → append 新 bar，上一根进入 closed
- realtime 明显更旧 → 不得覆盖最新 state
- 同 timestamp 乱序事件不得让 High 降低或 Low 升高；provider 返回权威完整 snapshot 时可按 timestamp/sequence 做 replacement

初始化必须处理 race：历史请求完成后开启/恢复 realtime 时要获取最新 snapshot/revision 并 reconcile，不能假设历史请求结束时就是实时起点。

## Chart lifecycle

实时行情事件不能执行：

`chart.remove() → createChart()`

市场实时更新必须优先使用 Lightweight Charts 原位 update（如 `CandlestickSeries.update()`）。

完整重建仍可用于：

- symbol change
- period change
- 指标 pane 结构变化
- 需要重建 layout 的结构性操作

允许把当前巨型 `draw()` 适度拆分为初始化、历史加载、实时更新、指标刷新和 destroy 生命周期，但不得借机重写整个图表系统。

历史向左分页、visible range preservation、副图高度保存都必须继续工作。

## Indicator correctness

本任务禁止改变现有指标算法语义，包括但不限于：

- MA / EMA
- MACD
- RSI
- KDJ
- BOLL
- VOL
- REF / HHV / LLV / CROSS
- COST / WINNER / LWINNER
- 自定义 Formula 的现有函数语义

验收原则：对同一组最终 closed bars，实时路径最终结果必须与重新完整加载 bars 后的 full recalculation 一致（仅允许合理浮点误差）。

### Built-in indicators

MA、BOLL、VOL、MACD、KDJ、RSI 必须随 current bar 更新。

正确性优先于过早做复杂增量算法。可以先做受控 tail/full-light recomputation + series 原位更新；若实现真正 incremental，必须有一致性测试证明结果等价。

### Custom Formula

Formula source 继续只在后端保存，不读取、不打印、不返回浏览器。

实时 Formula 调度必须具备：

- throttle / coalescing
- single-flight
- latest revision wins
- stale response discard
- symbol/period generation protection

若 revision 100 正在计算，期间来了 101/102/103/104，不得形成 4 个排队任务；只保留 latest pending revision，100 完成后直接追最新状态。

## Refresh cadence

Provider event 可以高频接收，但事件频率不能直接等于 UI/API 请求频率。

第一版目标区间（以 benchmark 为准，不是永久写死规则）：

- 前端 bar/UI：约 200–500ms 合并更新
- 轻量 built-in indicators：与 UI 同级或等价受控节流
- Custom Formula：约 750–1000ms 级别，必须 single-flight + coalescing

不得产生 Formula backlog。

## Reconnect / reconciliation

Provider 断线时状态必须从 `live` 变为 `reconnecting / unavailable`，不能继续伪装 live。

恢复流程：

1. 重新连接 provider
2. 获取最新权威 K 线 / snapshot
3. reconcile 当前或最近 bars
4. 更新 realtime revision/state
5. 重新计算最新指标状态
6. 恢复 `live`

浏览器 transport 重连后也必须获取 latest snapshot/revision；不能断线几十秒后直接从新事件继续导致中间状态缺失。

页面隐藏时降低/暂停高频图表和 Formula 刷新；恢复 visible 后先 reconcile 最新真实状态再继续。

## Futu first adapter

先检查当前安装的 Futu SDK/OpenD 实际 push/subscription 能力和权限。

优先使用真实 push。若某市场/周期当前权限不支持 push，可使用后端共享、低频、受控的真实 polling fallback，并显式标记 `mode=polling`；不得让每个浏览器自己高频 polling OpenD。

如果 push 和真实 polling 都不可用，则显示 unavailable，禁止 synthetic tick/test provider 进入运行时。

## Crypto boundary

本任务不接 Coinbase，不创建 fake BTC/ETH MarketSymbol，不实现 Coinbase WebSocket。

下一任务 `Task 005.1.4 — Coinbase Crypto Market Data` 只需实现 Coinbase adapter 并接入本任务建立的统一 realtime pipeline，不应再次重写 MarketChart realtime architecture。

## Persistence / infrastructure

本任务实时行情状态不写 SQLite：

- 每个 tick/quote/revision 不写数据库
- 不新增实时行情 DB migration
- 当前 process-local realtime bus/cache 仅用于开发阶段

预计本任务无 migration。若实现过程中发现必须 migration，先停止并说明原因；对正式 DB 的任何迁移仍必须先执行 `python manage.py backup_local_db` 并确认 path/SHA/integrity check。

## Tests and acceptance

至少覆盖：

- 同 symbol/period 多 consumer 只建立一个 provider subscription
- reference count / grace unsubscribe
- 同 timestamp current bar update
- 新 timestamp append + previous close
- out-of-order protection
- revision 单调增加
- missing amount/turnover_rate 保持 null
- provider unavailable 不产生 fake fallback
- reconnect reconciliation
- authenticated/Visitor/anonymous 权限边界
- Formula scheduler single-flight/coalescing/stale discard
- test provider 只存在 tests
- MA/BOLL/VOL/MACD/KDJ/RSI realtime final result 与 full recalculation 一致
- Formula 通过既有公开接口/fixture 验证最终结果一致，不读取 Formula source
- realtime bar 更新路径不因每个事件调用 `chart.remove()`
- hidden tab 与 symbol/period 切换不发生旧请求污染

人工验证至少包括：

- 一个 Futu 当前真实可用证券
- 初始真实 K 线 → live 状态
- current bar OHLC/volume 更新
- MA/MACD/RSI 与自定义 Formula 更新
- 左拖历史继续可用
- 两个 Tab 同 symbol/period 复用一份 provider subscription
- 关闭一个 Tab subscription 仍存在；最后 consumer 离开后 grace unsubscribe
- OpenD 断开显示 reconnecting/unavailable，恢复后 reconcile
- 2–5 分钟 soak：无内存持续上涨、无 Formula queue 累积、无重复 subscription/timer/EventSource leak

## Validation

开发完成至少运行：

```text
python manage.py check
python manage.py test core
python manage.py makemigrations --check
npm run build
git diff --check
```

并确认：

- Formula 数量仍为 4
- Formula source 未读取、未修改、未输出
- DB/backup/media/log/secrets 不进入 Git
- worktree clean

## Out of scope

- Coinbase 接入（Task 005.1.4）
- 2FA / 登录设备 / account session security
- 支付 / Billing
- Notification
- User Workspace persistence（Task 005.2）
- Drawing Tools（Task 005.3）
- Chip Profile UI（Task 005.4）
- Redis/生产级多节点 realtime bus 部署

## Review Fixes

- `RealtimeRegistry` now derives its key and state source from the injected provider identity. Futu remains selected only by the application-level default registry factory, so a future Coinbase adapter can be injected without changing the registry, state store, SSE core, or chart.
- Subscription initialization now has an explicit `subscribed` lifecycle. A failed first subscription immediately removes the entry, closes the consumer, clears callbacks, and records `unavailable`; the grace period is only used after a real subscription succeeded.
- Live same-bar updates and authoritative reconciliation now have separate semantics. Futu push events do not claim `time_key` is an event sequence; stale cumulative volume/amount is rejected, while reconnect snapshots can replace an erroneous high/low/volume state.
- The browser uses a 300 ms latest-payload UI buffer. Hidden tabs disconnect and cancel realtime/formula work; visible tabs reconnect and receive a fresh server snapshot. Formula requests remain separately throttled at approximately 850 ms.
- Formula calculations capture one immutable realtime snapshot before loading history and return that captured revision. Same symbol/period/formula/version/revision requests share a process-local in-flight result after authorization, preventing duplicate subprocess work without retaining completed results or bypassing permissions.
- Formula layer updates now create newly appearing sticks, markers, and fixed texts, clear disappearing data, rebuild only the affected layer when line structure changes, and call Lightweight Charts `requestUpdate` from custom primitives.
- Realtime payloads and Formula responses now carry a process-local epoch together with the monotonic revision. The browser accepts a lower revision from a new epoch, rejects lower revisions within the same epoch, and discards stale Formula responses from an older epoch.
- The 300 ms UI coalescer now carries a stream-generation guard and applies `last_closed_bar` before the current bar, preserving the final state across a bar boundary without allowing buffered live data to revive a reconnecting or unavailable status.
- Formula history input is bounded at the captured current-bar timestamp; newer history rows are removed and the captured bar authoritatively overlays same-time provider history before calculation.
- Futu reconnect notifications now distinguish `reconnecting` from terminal `unavailable`, and Formula duplicate suppression is in-flight-only so completed results are not reused after historical or float-share inputs may change.
- Formula in-flight keys now include a canonical SHA-256 fingerprint of the actual calculation inputs (`calculation_bars` and `float_shares`, plus explicitly supplied parameters when present). The fingerprint is computed from non-secret inputs only and never includes Formula source; identical inputs share one in-flight run, while changed bars or float shares start a distinct run.
- Repeated backend `last_closed_bar` metadata is now classified separately from live current-bar changes. The first boundary or authoritative closed-bar correction performs one full candlestick `setData`, while later same-closed-bar updates use incremental `update` for the current bar instead of repeatedly replacing the full history.
- Futu OpenD contexts now carry a monotonic connection generation under the provider lock. Reconnect and close invalidate the old generation before closing its context, and late frames or errors from an old context are ignored before they can notify callbacks or revive provider state.
- Realtime version reconciliation now returns explicit reasons (`accepted`, `new_epoch`, `stale_revision`, `missing_epoch`, or `invalid_revision`). A stale revision from the same epoch is silently discarded and does not mark the stream unavailable; a lower revision from a new epoch remains acceptable.
- Code-level and deterministic tests pass, but final real trading-hours validation is still pending. Do not treat this task as fully validated until live push, two-tab sharing, and the 2–5 minute soak are observed during an actual trading session.

## Completion rule

实现分支完成后创建 PR 到 `main`，由 ChatGPT 复查真实 diff、权限、性能、reconnect、指标一致性与 no-fake 行为。未经用户确认不得 merge。

## Completion Report

- Branch: `codex/005-1-3-realtime-market-indicator-pipeline`
- Scope: provider-neutral process-local realtime pipeline with a real Futu OpenD adapter, shared subscriptions, explicit subscription lifecycle, normalized bars, revisions, SSE transport, in-place chart updates, built-in indicator refresh, and coalesced custom Formula refresh.
- Provider: local `futu-api 10.10.7008`, OpenD server version `1010`. The installed SDK/OpenD accepted real K-line subscriptions for the supported 1/5/15/30/60/120/240-minute, day, week, and month periods. No synthetic runtime provider or fake fallback was added. The separate `分时` path remains explicitly unavailable for this K-line stream because it uses different OpenD semantics.
- Transport: `GET /api/realtime/market-stream/<code>/?period=<period>` using SSE. Access reuses the existing terminal API boundary: authenticated users and valid visitors are allowed; anonymous requests are rejected. The registry shares one provider subscription per provider/symbol/period, tracks consumers, and delays unsubscribe through a grace period.
- Normalization: market timezones are explicit, missing `amount` and `turnover_rate` remain `null`, real zero values are preserved, live same-timestamp bars use monotonic high/low and cumulative volume/amount protection, authoritative reconciliation can replace the current bar, newer bars append and close the prior bar, and stale/out-of-order events are rejected.
- Calculation consistency: one immutable realtime snapshot (epoch, revision, and current bar) is captured before Formula history loading; history is bounded to that captured bar and the response returns the exact captured epoch/revision. Authorized duplicate requests share only one process-local in-flight result after the Formula permission check, keyed by provider/symbol/period/Formula identity/version, epoch/revision, and a canonical SHA-256 fingerprint of the actual calculation bars and float shares; completed results are not retained.
- Frontend: `MarketChart.vue` buffers latest realtime payloads and flushes every 300 ms, applies `last_closed_bar` before the current bar, performs one full `setData` for a new/corrected closed bar and incremental `update` for later current-bar changes, updates the existing candlestick series without a structural chart rebuild, refreshes built-in MA/BOLL/VOL/MACD/KDJ/RSI layers, disconnects hidden tabs, reconnects/reconciles visible tabs, and protects epoch/stream/symbol generations from stale responses. Custom Formula refresh uses an approximately 850 ms throttle with single-flight, latest-pending coalescing, epoch/revision checks, and stale-response discard. Dynamic sticks, markers, fixed texts, and changed line structures update or rebuild only their own indicator layer.
- Tests: `python manage.py test core` passed `122` tests; the indicator consistency Node contract passed append `6/6` and same-bar update `6/6`; the realtime UI buffer contract passed `100 events -> 2 flushes`, 50 repeated closed-bar payloads with one full-history update decision, and deterministic epoch/bar-boundary/status checks; `python manage.py check`, `python manage.py makemigrations --check`, `npm run build`, and `git diff --check` passed. Django retains the repository's existing auto-primary-key warnings only.
- Real OpenD verification: a real `SH.600519` subscription and snapshot succeeded, including OHLC-related fields and provider health. The manual probe was performed outside trading hours, so no live callback event was expected; the browser displayed the explicit unavailable state rather than synthetic values. No private Formula source or business data was printed.
- Persistence: no migration and no formal database write were needed. The local database still contains `4` Formula records; Formula source was not read or modified. Database files, backups, logs, sessions, secrets, and private data remain outside Git.
- Known limits: the registry is intentionally process-local for this development task; multi-process deployment needs a shared market gateway/pub-sub layer. A full 2–5 minute trading-hours soak, two simultaneous browser tabs with live push, and continuous trading-hours Formula refresh were not reproduced during the non-trading manual probe. Trading-hours final validation remains pending; deterministic registry, snapshot, scheduler, primitive, and UI-buffer tests cover the code contracts.
