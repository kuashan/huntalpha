# SiftAlpha 统一行情架构对齐设计

## 事实来源与审计结论

本设计以私有仓库 `kuashan/siftalpha-research` 的真实远端代码为事实源：

- `feature/market-data-provider-signal-decoupling-v1` @ `ca06ec3091ea6fc6adf092f3b2e704b7e58d80e7`
  - `integrations/5s_crypto_binance_usdm_v1/MARKET_DATA_BOUNDARY_v1.md`
  - `integrations/5s_crypto_binance_usdm_v1/market_data.py`
- `feature/sltd-shared-marketdata-5s-stocks-v1` @ `ce16312bc3651fefcf311f323377e7e2cdbb32c2`
  - `integrations/shared_market_data/__init__.py`
  - `integrations/sltd_v7_siftalpha_v1/data_provider.py`
  - `integrations/sltd_v7_siftalpha_v1/providers/yahoo.py`

SLTD 的冻结事实是：策略/业务只消费标准化行情；市场规则独立于供应商；路由按市场和供应商优先级选择；失败切换必须重新获取完整窗口；缓存至少按 provider、symbol、timeframe 隔离；completed 与 forming K 线分离；行情与交易执行账户分离。HuntAlpha 不复制 Yahoo 这个具体 Provider，而是复用上述边界并扩展网站所需的目录、报价、历史、实时订阅、能力和状态接口。

## 目标

把当前 `codex/005-1-4-crypto-market-data-foundation` 上的 HuntAlpha 实时基础设施迁移到 provider-neutral 的 `core/marketdata/` 统一入口，保留既有共享实时 Registry/State/SSE、前端增量 K 线、内置指标、自定义公式、缠论和历史分页；供应商只存在于适配器和路由层。

产品品牌的用户可见文字改为 `SiftAlpha`，GitHub 仓库地址和历史保持 `kuashan/huntalpha` 不变。

## 非目标

- 不加入 SLTD 12 条规则、C2、BUY/SELL、仓位、退出或自动交易。
- 不修改现有指标算法、公式算法、缠论算法或公式源私有性边界。
- 不重写既有 Git 历史，不直接修改 `main`，不删除数据库、日志、备份或本地用户数据。
- 不把任何 Provider 凭据暴露给浏览器、数据库普通字段或 Git。

## 目标架构

```text
图表 / 指标 / 公式
        ↓
core.marketdata 统一行情入口
        ↓
MarketDataRouter（市场 → Provider 优先级）
        ↓
MarketProfile（时区、交易时段、完成语义、聚合边界）
        ↓
Provider Adapter
        ↓
真实行情源
```

### MarketProfile

沿用 SLTD 的 `MarketProfile` 语义，并加入网站需要的港股：

- `CRYPTO`：UTC，连续 24 小时。
- `CN_A_SHARE`：Asia/Shanghai，09:30–11:30、13:00–15:00。
- `HK_EQUITY`：Asia/Hong_Kong；按港交所正常交易日和早市/午市时段定义，不能套用 A 股或美股规则。
- `US_EQUITY`：America/New_York，09:30–16:00。

Profile 独立于 Provider。K 线边界使用 Provider 时间戳与 Profile 时区/交易时段，禁止服务器本地时间和固定秒数跨市场切割。

### 统一数据契约

保留现有 `NormalizedBar` 的丰富字段，并由统一 Fetch 外层返回：

```text
MarketDataFetch(
  market_id,
  provider_id,
  provider_label,
  symbol,
  timeframe,
  completed,
  forming,
  meta,
  stream,
)
```

每根标准化 K 线至少包含：`provider, market, symbol, period, time, open, high, low, close, volume, amount, is_closed, timestamp, sequence, revision, mode`。`mode` 能表达 real-time、delayed、historical、cache、unavailable；缺失的成交额、换手率等字段保持 `null`。

### Provider 接口

所有 Provider 通过统一 Protocol/抽象接口接入，具体名称可按现有代码风格实现，但语义必须覆盖：

- `list_securities(market, query, page)`
- `quote(symbol)`
- `fetch_window(symbol, timeframe, window, ...)`
- `fetch_recent(symbol, timeframe, ...)`
- `subscribe(symbol, timeframe, callback)`
- `unsubscribe(symbol, timeframe)`
- `capabilities(market)`
- `status(market, symbol=None)`

历史/最近窗口获取必须返回 completed/forming 分离的完整窗口。实时订阅继续复用现有进程级 Registry 和 StateStore，不在每个浏览器页面创建独立底层订阅。

### 路由、故障切换和缓存

`MarketDataRouter` 先按 market profile，再按配置的 Provider 优先级路由。Provider 失败时，下一 Provider 必须重新获取同一请求的完整窗口，禁止跨 Provider 拼接。

缓存键至少为：

```text
market + symbol + timeframe + provider
```

缓存内容必须带同样的身份字段；网络失败时最多回退到同一 market、symbol、timeframe、provider 的过期缓存，并明确标记 `cache/stale`。不能用另一只股票、另一个市场或另一个 Provider 的数据冒充当前请求。

### 供应商配置

- A 股：Tushare 为主要候选，Longbridge 可配置为备用。
- 港股：Longbridge 为主要候选。
- 美股：Longbridge 为主要候选。
- 加密货币：Coinbase 公共行情为主要来源，不引入交易账户凭据。
- Futu OpenD 不再作为统一行情架构基础；迁移期间可隔离保留旧适配器以完成回归，确认无应用依赖后再移除运行依赖。

Tushare、Longbridge 的凭据只从本地 `.env` 或服务器安全环境读取。未配置、权限不足、延迟、限流、重连和不可用都必须显式返回，不能生成或静默替换成假行情。

### 应用迁移边界

`core/views.py`、公式执行路径和 Vue 页面只调用统一 MarketData Service/Router，不导入 Futu、Tushare、Longbridge 或 Coinbase SDK。已有 Coinbase Provider 和 Futu 实时状态代码被适配到统一边界；前端保留历史分页、实时最后一根原地更新、指标调度和公式服务端计算。

### 品牌边界

用户可见的页面标题、登录页、启动页、顶栏、Logo、favicon、后台可见名称、错误和加载文案使用 `SiftAlpha`，移除 `HuntAlpha`/`HUB` 的用户可见残留。内部环境变量、数据库迁移历史、GitHub 仓库名和兼容路径可暂时保留旧标识，以避免破坏数据和部署。

## 实施验收

后端执行 `python manage.py check`、`python manage.py test core`、`python manage.py makemigrations --check`；前端执行既有指标/实时测试和 `npm run build`；执行 `git diff --check`。

自动测试覆盖：Profile 与时段、完整窗口 failover、四维缓存隔离、同 Provider 过期缓存、completed/forming、Provider capability/status、实时 Registry 复用、历史与实时合并、来源状态、无凭据和权限错误。

如果本地配置了真实凭据，验证 A 股、港股、美股、BTC、ETH 的搜索、报价、历史、形成中 K 线、收盘转化、成交量、指标/公式刷新、来源显示、重连和错误状态；没有凭据的市场必须验证为清晰的 unavailable，而不是用测试数字替代。

阶段收尾状态只能报告 `IMPLEMENTED_AND_VERIFIED`，不得自行报告 `ACCEPTED` 或合并 `main`。
