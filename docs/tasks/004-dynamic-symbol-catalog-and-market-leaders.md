# Task 004 — 动态证券目录与市场市值 Top 5

Status: IMPLEMENTED

## 背景

HuntAlpha 当前前端 `frontend/src/data/marketData.js` 仍然手工写死少量测试标的，例如 A 股仅列出贵州茅台、宁德时代、平安银行等少数证券。真实行情链路已经能够根据证券代码从 Futu OpenD 获取报价和 K 线，但网站还没有“全市场证券目录”与自动同步能力。

用户已确认新的产品方向：

1. 每个已接入真实证券数据源的市场，默认展示按总市值排序最大的 5 只证券。
2. 用户仍然能够搜索该市场的完整证券目录，而不是只能看到这 5 只。
3. 证券目录应由真实数据源自动同步，不再依赖前端手工添加证券。
4. 当前尚未接入真实加密资产数据源，因此加密资产不得伪造 Top 5、行情或证券目录；继续明确显示“数据源未接入/不可用”。

## 目标体验

```text
用户进入 A 股
    ↓
左侧默认展示：真实数据中的总市值 Top 5
    ↓
用户输入股票名称或代码
    ↓
从 HuntAlpha 的完整 A 股证券目录搜索
    ↓
点击证券
    ↓
现有 OpenD 真实报价 / K线 / 指标链路继续工作
```

港股、美股同理。Top 5 只是默认推荐入口，不代表市场里只有 5 只证券。

## 核心原则

- 不再由前端维护完整证券白名单。
- 不允许静态/虚构市场排名作为运行时回退。
- “证券目录”和“实时行情”分离：同步几千只证券的基础资料，不等于同时请求几千只实时 K 线。
- 页面只对当前需要展示的少量证券请求实时报价。
- 搜索完整市场目录时优先查询 HuntAlpha 后端/本地目录，不应让浏览器直接逐只请求 OpenD。
- 设计需为未来 Futu、TDX、iFinD、IBKR 等多数据源保留适配层，不把前端绑定到 Futu SDK 字段。
- Formula source、数据库备份和其他敏感数据规则继续遵守 `AGENTS.md`。

## 第一阶段支持范围

### 市场

- 沪深 A 股：使用当前真实数据能力能够可靠覆盖的交易所/证券类型。北交所是否能由当前 Futu OpenD 版本完整提供，必须由 Codex 先实测确认，不得凭假设硬编码。
- 港股。
- 美股。
- 加密资产：当前无真实目录/市值数据源，本任务不伪造实现，只保留明确不可用状态。

### 证券类型

默认 Top 5 应是“股票/普通上市公司”语义，不应把 ETF、债券、期权、窝轮等因为市值字段异常而混入。

Codex 必须检查当前 Futu SDK 返回的证券类型字段并建立明确过滤规则，记录实测结果。

## 数据架构

### 1. HuntAlpha 统一证券目录

优先实现一个后端可持久化的证券目录模型（名称可由 Codex根据现有项目结构确定），至少包含：

- canonical code（例如 `SH.600519`）
- display name
- HuntAlpha market（A 股 / 港股 / 美股）
- exchange / provider market（如可获得）
- security type
- active/listed 状态（如数据源支持）
- provider（当前 `futu-opend`）
- provider symbol
- market cap（如果数据源能够可靠提供）
- market cap currency（如需要）
- market cap updated_at
- catalog updated_at

不要把 provider 私有字段直接暴露为前端业务模型。

如果需要 Django migration：

1. 先运行 `python manage.py backup_local_db`。
2. 必须确认 `integrity_check: ok`。
3. 只允许正常新增 migration，不允许 `flush`、重建数据库或删除现有用户数据。
4. Formula 记录必须保持 4 条且 source 不变。

### 2. 自动同步命令

新增明确的 Django management command，例如：

```text
python manage.py sync_symbol_catalog
```

具体命名可以调整，但职责必须单一、可测试。

要求：

- 从真实 provider 获取证券基础资料。
- 幂等 upsert：重复执行不会产生重复证券。
- 新上市证券可自动加入。
- 退市/失效证券不要物理删除用户相关历史；优先标记 inactive。
- 单个市场失败不能破坏其他已经成功同步的市场。
- 输出非敏感同步摘要：市场、读取数、新增数、更新数、停用数、失败原因。
- 不打印 Formula source、用户数据或秘密。

### 3. 自动化入口

本任务提供 Windows 可执行的自动同步入口，风格参考 Task 002 的计划任务脚本。

目标默认：每天一次同步证券目录即可，不要高频轮询。

如果需要 Windows Task Scheduler：

- 提供安装/移除脚本或扩展现有安全模式。
- 不默认静默修改用户系统；由用户显式执行安装命令。
- 计划任务调用同一个 Django management command，不复制业务逻辑。

## 市值 Top 5

### 数据来源必须真实

Codex 在编码前必须先实测当前 Futu/OpenD SDK：

- 如何获取全市场证券列表；
- 如何高效获得总市值字段；
- 是否存在批量 snapshot、filter 或其他更适合的接口；
- API 批量上限、速率/权限限制；
- A 股、港股、美股字段是否一致。

不要为了 Top 5 在每次网页打开时逐只请求几千个 snapshot。

推荐方向：同步阶段批量刷新/缓存 market cap，页面读取 HuntAlpha 本地目录中的最近有效结果。

如果当前 provider 对某个市场无法在合理成本和权限下提供可靠全市场总市值：

- 不要伪造排名；
- 返回 `leaders_available: false` 或明确的 unavailable 状态；
- 在 Completion Report 记录具体 provider 限制；
- 不得使用手写的 5 只股票作为假 Top 5。

### 排名规则

- 使用总市值（total market cap），不是流通市值，除非 provider 明确只有流通市值；如只能获得其他口径必须先报告并在 API 字段中标注口径。
- 过滤无效、0、NaN 市值。
- 同一市场按市值降序取 5。
- 市值显示格式和币种要正确，不得把人民币、港币、美元直接混合比较；Top 5 只在各自市场内部排序。

## 后端 API

请提供清晰、最小的 API。具体 URL 可遵循现有项目风格，至少支持：

### 市场默认列表 / leaders

返回当前市场 Top 5，包括：

- code
- name
- market cap（可用时）
- market cap currency / unit
- source
- updated_at

### 证券搜索

支持按：

- code
- name

搜索完整已同步目录。

要求：

- 后端分页/limit；
- 空搜索不能一次把几千条全部塞给前端；
- 对用户输入做合理长度限制；
- 只返回前端需要的公开证券信息。

## 前端改造

当前 `frontend/src/data/marketData.js` 的静态证券列表必须退出“真实运行时证券目录”角色。

允许保留：

- 市场名称常量；
- 内置指标常量；
- 测试 fixture（仅测试环境）。

不应继续保留：

- A 股/港股/美股运行时手工 3～4 只证券列表作为真实目录。

前端行为：

1. 切换市场后加载该市场 Top 5。
2. 默认选中第一只可用证券。
3. 搜索输入后调用后端证券搜索，建议防抖；避免每次按键都无控制地打 API。
4. 清空搜索后恢复 Top 5。
5. 只给当前页面展示的 5～有限搜索结果请求报价；不要对全市场证券批量 `refreshQuotes()`。
6. OpenD 不可用或目录未同步时显示明确错误/空状态，不回退到静态测试证券。
7. 加密资产在真实 provider 接入前继续不可用，不显示伪造 Top 5。

## 多数据源准备

不要在 Vue 里写 `if provider === futu`。

后端应把 provider 数据转换为统一 HuntAlpha symbol payload。未来新增数据源时，只需要增加 provider adapter / mapping，而不是重写整个前端证券选择逻辑。

本任务不要求真正接入 TDX/iFinD/IBKR，只要求当前结构不要阻塞未来扩展。

## 测试要求

自动测试不得依赖实时互联网或真实用户数据库。

至少覆盖：

- 证券目录同步的 upsert 幂等性。
- 新增证券。
- 更新名称/状态。
- provider 缺失证券的安全 inactive 逻辑（若实现）。
- 不误删未知/历史记录。
- Top 5 排序正确。
- 无效市值过滤。
- 不同市场独立排序。
- 搜索 code/name。
- API limit/pagination。
- provider 失败时无静态假数据回退。
- 前端不再依赖手工证券列表。

真实 OpenD 验证只报告非敏感信息，例如：

- 各市场同步证券数量；
- Top 5 的名称/代码/市值（这些是公开市场数据，可以报告）；
- API 成功/失败；
- 不报告任何用户私有 Formula source。

## 安全与数据保护

- 严格遵守 `AGENTS.md`。
- 如涉及 migration 或任何正式本地 DB 写入：先 `python manage.py backup_local_db` 并确认 `integrity_check: ok`。
- 禁止 `flush`、reset、重建数据库。
- Formula 必须保持 4 条，source 不变。
- 数据库、备份、日志不得被 Git 跟踪。
- 不提交 API 密钥、Token、OpenD 凭据。
- 不修改 Task 001/002/003 已验收的真实行情、备份和指标性能语义。

## 验收标准

- [ ] A 股/港股/美股不再依赖前端手工证券列表。
- [ ] 有真实证券目录同步能力。
- [ ] 同步命令幂等、可重复、安全。
- [ ] 页面默认展示每个已支持市场真实总市值 Top 5。
- [ ] Top 5 不是静态硬编码。
- [ ] 用户可按名称或代码搜索完整已同步证券目录。
- [ ] 页面不会同时请求全市场实时报价/K线。
- [ ] provider 不可用时不使用假数据。
- [ ] 加密资产在未接真实数据源前仍明确不可用。
- [ ] 为未来多 provider 保留清晰后端抽象。
- [ ] 如有 migration，备份和完整性检查已执行并记录。
- [ ] Formula 数量仍为 4，source 不变。
- [ ] `python manage.py check` 通过。
- [ ] `python manage.py test core` 通过。
- [ ] 新增目录相关测试通过。
- [ ] `npm run build` 通过。
- [ ] `git diff --check` 通过。
- [ ] Git 工作区干净。

## Codex Completion Report

完成后填写：

- Branch: `codex/004-dynamic-symbol-catalog`
- Commit: `fe80c1e`
- PR: [#8](https://github.com/kuashan/huntalpha/pull/8), open against `main`; not merged
- Provider capability investigation: Futu SDK `10.10.7008` with the local OpenD. `get_stock_basicinfo(..., stock_type="STOCK")` returned the complete ordinary-stock catalogs; CN required combining `SH` and `SZ`. `ETF`, `BOND`, and `WARRANT` are separate provider security-type queries and are excluded. `get_stock_filter` with `MARKET_VAL` and descending sort returned the real market-cap candidates, with a 200-row maximum. `get_market_snapshot` accepted 400 codes and rejected 401, but is not needed on every page or for the daily leader cache.
- A 股 catalog count: 5347
- 港股 catalog count: 3777
- 美股 catalog count: 13046
- 北交所 support result: unsupported by this OpenD/SDK version; no `Market.BJ`, `get_stock_basicinfo("BJ", ...)` and `get_market_snapshot(["BJ.*"])` both failed. No BJ static fallback was added.
- Market-cap source/method: real Futu `get_stock_filter` `StockField.MARKET_VAL` descending results; cached per-market in local currency (`CNY`, `HKD`, `USD`) for up to 200 candidates. The API sorts the local cached values independently and returns the top 5 only when the value is positive and valid.
- A 股 Top 5: `SH.688825` 长鑫科技（3,720,048,629,419.6 CNY）, `SH.601398` 工商银行（2,897,582,870,133.57 CNY）, `SH.601939` 建设银行（2,872,372,188,419.82 CNY）, `SH.601288` 农业银行（2,435,881,915,756.08 CNY）, `SH.600941` 中国移动（2,175,601,046,696.2 CNY）
- 港股 Top 5: `HK.00700` 腾讯控股（4,030,876,536,735.6 HKD）, `HK.80700` 腾讯控股-R（3,457,377,842,484.6 HKD）, `HK.00005` 汇丰控股（2,861,687,522,026.1 HKD）, `HK.01398` 工商银行（2,742,546,142,299.85 HKD）, `HK.03750` 宁德时代（2,658,079,605,545 HKD）
- 美股 Top 5: `US.NVDA` 英伟达（5,551,676,000,000 USD）, `US.AAPL` 苹果（4,669,699,774,600 USD）, `US.GOOGL` 谷歌-A（4,139,365,800,000 USD）, `US.GOOG` 谷歌-C（4,100,841,300,000 USD）, `US.MSFT` 微软（3,710,545,081,852.7 USD）
- Search verification: API name search, code search, market scoping, limit and page pagination passed; empty search returns Top 5. Provider failure returns an error/unavailable state and no static data. Frontend runtime catalog no longer contains hand-written securities and only requests quotes for the visible result set.
- Automatic sync command: `python manage.py sync_symbol_catalog`；可用 `--market cn|hk|us` 单独同步市场。
- Scheduler entry point: `scripts/manage_symbol_catalog_task.ps1 -Action Install -Time 04:00`；移除使用 `-Action Remove`。脚本只在用户明确执行时安装/移除当前用户每日任务，任务动作只调用 `python manage.py sync_symbol_catalog`。
- DB migration: yes, `core/migrations/0006_marketsymbol.py`
- Backup path / integrity_check（如涉及 DB 写入）: `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-062709-981756.sqlite3`; `integrity_check: ok`，SHA-256 `e8540d24cb5ec56f7e5b8c9b552cddac66e239876f35bf0d3fd5c84267eabcd5`
- Formula count before/after: 4 / 4
- Formula source changed: no
- Tests: `python manage.py test core` passed, 38 tests; temporary databases and synthetic provider fixtures only.
- `python manage.py check`: passed; existing `models.W042` warnings remain for the three core models using the project's historical AutoField convention.
- `npm run build`: passed
- `git diff --check`: passed
- Unresolved provider limitations: OpenD must be running and account permissions determine data availability. The provider's stock filter exposes only the top 200 market-cap candidates per request, so non-leader catalog rows may have no current market-cap cache; if the market-cap request fails, stale values are cleared and leaders are reported unavailable. Northbound/BJ coverage is not available in this SDK version. Crypto remains unavailable until a real provider is connected.

## Review

由 ChatGPT/用户验收后填写：

- Result:
- Notes:
