# SiftAlpha 统一行情架构对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 HuntAlpha 当前实时行情系统迁移到与 `kuashan/siftalpha-research` 已冻结实现一致的 provider-neutral MarketData 边界，同时接入 Tushare、Longbridge、Coinbase，并保留现有图表、指标、公式和实时共享能力。

**Architecture:** 在现有 `core/realtime` 状态、共享订阅和前端增量更新之上建立 `core/marketdata` 统一契约。`MarketDataRouter` 按 `MarketProfile` 和 Provider 优先级获取完整窗口，失败时整体切换，缓存按 market+symbol+timeframe+provider 隔离；视图、公式和 Vue 不再直接识别 Provider。

**Tech Stack:** Django 5.2/Python、Vue 3/Vite、现有 lightweight-charts、Tushare Pro、Longbridge Python SDK、Coinbase REST/WebSocket、SQLite 开发数据库。

**Spec:** `docs/superpowers/specs/2026-10-04-siftalpha-marketdata-alignment-design.md`

## Global Constraints

- 只在 `codex/006-unified-marketdata-siftalpha` 工作，不直接修改 `main`，不重写既有历史。
- 以 `siftalpha-research` 两个指定 commit 的真实实现为事实源；不复制 Yahoo 作为本网站 Provider。
- Provider 切换必须重新获取完整窗口，禁止拼接不同 Provider 的 K 线。
- 缓存键至少包含 market、symbol、timeframe、provider。
- `completed` 与 `forming` 必须分离；指标和公式算法保持不变。
- 没有凭据、权限不足、延迟、限流或不可用时明确返回状态，禁止假行情。
- Tushare/Longbridge secret 只从环境变量或服务器安全配置读取，不进入前端、数据库普通字段或 Git。
- 不加入交易、策略、BUY/SELL、C2、仓位或自动交易。
- 保留 `vendor/formula-ts` submodule 及其 commit `c149cb603ad0df7ea1acb259e6be6af06263bc6f`。

## Review Focus

- 相同 symbol 在不同 market 或 Provider 间的缓存污染：由 Task 1 的四维缓存测试固定。
- Provider 失败后的窗口完整性：由 Task 1/2 的 whole-window failover 测试固定。
- 午休、跨交易日和港股交易时段的 forming/closed 错判：由 Task 1 的 Profile/聚合测试固定。
- 实时 Registry 重连后重复订阅或旧 generation 回写：由 Task 4 的共享订阅回归测试固定。
- 无凭据时 UI 把 unavailable 误显示为实时：由 Task 2/5 的状态契约测试固定。

---

### Task 1: 建立 SLTD 对齐的统一契约、Profile 和四维缓存

**Files:**
- Create: `core/marketdata/__init__.py`
- Create: `core/marketdata/contracts.py`
- Create: `core/marketdata/profiles.py`
- Create: `core/marketdata/cache.py`
- Create: `core/marketdata/router.py`
- Test: `core/test_marketdata_core.py`

**Interfaces:**
- Consumes: 现有 `core/realtime/contracts.py` 的 `NormalizedBar`、`core/models.py` 的市场/代码语义。
- Produces: `MarketProfile`、`MarketDataFetch`、`MarketDataProvider` Protocol、`MarketDataRouter.fetch_window()`、`MarketDataRouter.provider_ids()`、`MarketDataCache.key()`。

- [ ] **Step 1: 写失败测试**：固定 `CRYPTO`、`US_EQUITY`、`CN_A_SHARE` 和 `HK_EQUITY` 的时区/时段；固定四维缓存键；固定 Provider 全窗口 failover；固定 completed/forming 分离。
- [ ] **Step 2: 运行 `python manage.py test core.test_marketdata_core`，确认新契约尚不存在而失败。**
- [ ] **Step 3: 实现 Profile、Fetch、Provider Protocol、四维缓存和 Router**：Router 按市场注册顺序选择 Provider；每次 fallback 使用相同完整请求；过期缓存只能回退同一四维键并标记 stale。
- [ ] **Step 4: 运行同一测试，确认通过。**
- [ ] **Step 5: 运行 `python manage.py test core.test_marketdata_core` 并提交 `feat: add SLTD-aligned market data contracts`。**

### Task 2: 实现 Provider 适配器和能力/状态边界

**Files:**
- Create: `core/marketdata/providers/__init__.py`
- Create: `core/marketdata/providers/base.py`
- Create: `core/marketdata/providers/tushare.py`
- Create: `core/marketdata/providers/longbridge.py`
- Create: `core/marketdata/providers/coinbase.py`
- Modify: `core/crypto_provider.py`
- Modify: `core/realtime/futu_provider.py` (仅实现兼容桥，不再作为默认路由基础)
- Modify: `requirements.txt`
- Modify: `.env.example`
- Test: `core/test_marketdata_providers.py`

**Interfaces:**
- Consumes: Task 1 的 `MarketDataProvider`、`MarketProfile`、`MarketDataFetch`；现有 Coinbase/Futu 真实传输代码。
- Produces: Tushare A 股 Provider、Longbridge HK/US Provider、Coinbase Provider；每个 Provider 实现 `list_securities`、`quote`、`fetch_window`、`fetch_recent`、`subscribe`、`unsubscribe`、`capabilities`、`status`。

- [ ] **Step 1: 写 Provider fake/contract 测试**：测试 provider id/profile、标准字段映射、凭据缺失状态、whole-window 调用次数和不暴露 secret。
- [ ] **Step 2: 运行 Provider 测试，确认失败。**
- [ ] **Step 3: 实现 Tushare Adapter**：使用 `TUSHARE_TOKEN`，支持 A 股目录、报价、日线和 1/5/15/30/60 分钟；分钟权限不足返回 `permission_denied`，不生成替代数据；高周期由 Profile 边界聚合。
- [ ] **Step 4: 实现 Longbridge Adapter**：使用官方 `longbridge` SDK 的 `longbridge.openapi` 接口和本地 OAuth/token 环境配置，支持 HK/US 目录、报价、历史/最近 K 线和可用订阅能力；无权限或未配置明确返回状态。仅使用行情上下文，不接入交易账户。
- [ ] **Step 5: 适配现有 Coinbase REST/WebSocket**：把现有真实 Coinbase 数据映射为统一 Fetch/Bar，保留公共行情与交易账户分离。
- [ ] **Step 6: 将 Futu 适配器降级为 legacy bridge**：保留回归所需能力但从默认 Provider 优先级移除；确认无调用方后再决定是否从 requirements 移除。
- [ ] **Step 7: 在 requirements 和 `.env.example` 增加非秘密依赖/占位变量；运行 Provider 测试和 `python manage.py check`；提交 `feat: add market data provider adapters`。**

### Task 3: 迁移目录、报价、历史 K 线和公式输入到统一服务

**Files:**
- Create: `core/marketdata/service.py`
- Modify: `core/views.py`
- Modify: `core/symbol_catalog.py`
- Modify: `core/management/commands/sync_symbol_catalog.py`
- Modify: `core/market_indices.py`
- Modify: `core/chan_runner.py`
- Test: `core/tests.py`, `core/test_marketdata_application.py`

**Interfaces:**
- Consumes: Task 1 Router 和 Task 2 Provider；现有 `MarketSymbol`、公式 runner、指标输出字段。
- Produces: Provider-neutral `catalog/search/quote/kline/history/formula snapshot` 服务；API payload 中统一返回 source/provider/status/mode。

- [ ] **Step 1: 写迁移前失败/回归测试**：视图层不再直接导入 Provider SDK；每个市场通过 Router；来源状态和完整窗口字段保持兼容。
- [ ] **Step 2: 运行应用测试，确认直接调用路径仍被命中。**
- [ ] **Step 3: 实现 service facade**：视图只调用统一 service；将目录、报价、历史、指数概览、公式历史窗口都改走 Router；保留私有公式源不返回浏览器。
- [ ] **Step 4: 更新 catalog sync**：按 market/provider scope 同步，失败不把其他 Provider 的目录标记 inactive。
- [ ] **Step 5: 运行 `python manage.py test core`，确认全部现有测试与新增测试通过；提交 `refactor: route application market data through unified service`。**

### Task 4: 把现有实时 Registry/State/SSE 接入统一 Router

**Files:**
- Modify: `core/realtime/router.py`
- Modify: `core/realtime/registry.py`
- Modify: `core/realtime/contracts.py`
- Modify: `core/realtime/futu_provider.py`
- Modify: `core/crypto_provider.py`
- Test: `core/test_realtime.py`, `core/test_marketdata_realtime.py`

**Interfaces:**
- Consumes: Task 1 Router/Profile、Task 2 Provider 的 subscribe/status/capabilities。
- Produces: 同一 `provider+market+symbol+period` 的共享订阅；历史 Fetch 与 forming bar 合并；旧 generation 不得写回；断线后明确 reconnecting/reconciled/live。

- [ ] **Step 1: 写共享订阅回归测试**：双消费者复用单底层订阅；释放引用后按 grace 释放；跨市场/周期不串流；closed bar 只由权威收盘/修订更新。
- [ ] **Step 2: 运行新增实时测试，确认当前 hard-coded Futu/Coinbase router 不满足。**
- [ ] **Step 3: 实现默认 Router 工厂**：从 MarketData Router 的配置生成实时 provider；复用现有 Registry/StateStore，不创建第二套实时状态。
- [ ] **Step 4: 保持前端需要的 SSE 事件结构并增加统一 source/mode/status 字段；运行完整实时测试。**
- [ ] **Step 5: 提交 `refactor: connect shared realtime state to market router`。**

### Task 5: 迁移 Vue 到 Provider-neutral API 并完成 SiftAlpha 品牌替换

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/MarketChart.vue`
- Modify: `frontend/src/components/AuthGate.vue`
- Modify: `frontend/src/components/PersonalCenter.vue`
- Rename/Modify: `frontend/src/components/HuntAlphaLogo.vue` → `SiftAlphaLogo.vue`
- Modify: `frontend/index.html`
- Add/Modify: `frontend/public` brand/favicons using an existing SiftAlpha asset only after visual inspection
- Test: `frontend/src/realtime/realtimeUiBuffer.test.mjs`, `frontend/src/indicators/commonIndicators.test.mjs`, `core/tests.py` UI contract assertions

**Interfaces:**
- Consumes: Task 3/4 provider-neutral API and status metadata；现有实时 buffer、历史 recovery、公式渲染。
- Produces: 页面只展示统一来源/模式/状态，不判断 Futu/Tushare/Longbridge/Coinbase；所有用户可见品牌显示 SiftAlpha，不显示 HuntAlpha/HUB。

- [ ] **Step 1: 更新失败契约测试**：API 来源文字来自 payload；无行情显示 unavailable；不存在 Futu provider branch；品牌残留只允许内部兼容变量。
- [ ] **Step 2: 运行前端指标/实时测试，确认旧文案断言失败。**
- [ ] **Step 3: 修改 API source/status 映射，保留 K 线原地更新、历史分页和指标刷新。**
- [ ] **Step 4: 替换用户可见品牌和 favicon；不改 GitHub 仓库名、不删除旧内部配置名。**
- [ ] **Step 5: 运行前端测试和 `npm run build`；提交 `feat: rebrand terminal as SiftAlpha`。**

### Task 6: 真实源验证、全量回归和阶段收尾

**Files:**
- Create: `docs/tasks/006-unified-marketdata-siftalpha.md`
- Modify: `WORKLOG.md`
- Modify: `docs/architecture/SYSTEM_OVERVIEW.md`
- Test/Probe: `scripts/` 中新增只读 Provider 验证脚本（不写 secret、不落库）

**Interfaces:**
- Consumes: Tasks 1–5 的统一 API、Provider status 和前端状态。
- Produces: `IMPLEMENTED_AND_VERIFIED` 证据清单；不报告 `ACCEPTED`，不合并 `main`。

- [ ] **Step 1: 运行 `python manage.py check`、`python manage.py test core`、`python manage.py makemigrations --check`、前端测试、`npm run build`、`git diff --check`。**
- [ ] **Step 2: 若本地配置了凭据，逐一验证 CN/HK/US/BTC/ETH 的搜索、报价、历史、forming/closed、成交量、指标、公式、来源、重连和错误；未配置的 Provider 验证明确 unavailable。**
- [ ] **Step 3: 扫描 `HuntAlpha/huntalpha/HUNTALPHA`，区分用户可见品牌与内部兼容标识；扫描 Provider 依赖和 submodule 状态。**
- [ ] **Step 4: 更新任务文档和 Worklog，记录 START_HEAD、最终 HEAD、分支、Provider 优先级、Futu legacy 状态、测试和限制；提交 `docs: record unified marketdata verification`。**
- [ ] **Step 5: 推送功能分支到 origin（不推 main），停止继续开发，等待审核。**
