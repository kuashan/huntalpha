# HuntAlpha 工作纪要 / Product Worklog

用途：只保存 **尚未解决、尚未实现、正在开发或明确暂缓** 的 HuntAlpha 项目事项。这里不是聊天全文，也不是完成历史；它是“接下来还要做什么”的唯一待办纪要。

维护规则：
- 与项目有关的有效讨论结论，由 ChatGPT 持续整理为简明决策，不要求以后再翻聊天记录。
- 已经完成并验收/合并的事项，从本文件移除，并追加到 `docs/work-diary.md`。
- 未完成事项继续留在本文件；方向变化时直接更新为最新决定，不保留已被覆盖的旧规则。
- 当用户问“之前还有哪些没实现”，应同时核对本文件、`docs/work-diary.md`、`docs/tasks/` 和 GitHub PR/commit 状态，再回答。
- 不把聊天中的示例价格、演示数字当成运行时数据。
- 不记录密钥、密码、token、Formula source、用户私密数据、数据库内容等敏感信息。
- 行情、指数、新闻、信号、回测等业务数据必须来自真实 provider 或真实计算；失败时明确 unavailable，禁止 fake fallback。

---

## 当前进行中

### V2.0.2 — 分析卡片来源链接隐藏

状态：`IN_DEVELOPMENT`。用户要求隐藏恐慌与贪婪、技术动能卡片顶部的“来源”显示，算法、数据和后台来源元数据不变；详见 `docs/tasks/023-v2-0-2-analysis-card-source-visibility.md`。焦点科技 2026-09-04 Yahoo 26.46 元 vs 腾讯前复权 25.96 元差异已定位为 2026-09-09 每股 0.50 元现金分红调整；目前不授权改变行情复权口径。


### V2.0.1 — 行情来源切换与日/周/月时间戳一致性

状态：`DEPLOYED / USER PAGE ACCEPTANCE PENDING`。正式 Commit `60f8ea71ab9e7fe91c2223d7d0477ac5473dd734`，ARM64 Digest `sha256:d41d6bb8b9b6fc646fc4807702223740aeee5629d3cf7f54cc6d251257fb1102`。2026-10-24 受控备份和预检通过、生产部署成功，状态/Health/HTTP 检查正常。**用户页面最终验收待确认，不提前标记 ACCEPTED。**

从 Yahoo Finance 切换到腾讯财经导致日线重复。已定位交易所日期与 Unix 时间锚点不一致，及旧来源实时状态残留。已提出覆盖所有五类 Provider、中港美/加密市场的统一规范，并加入前后端定点修复。**PR/CI/正式构建/受控生产部署已完成，当前仅待实际页面验收。生产现运行 V2.0.1。**


### Task 006 — SLTD 对齐的统一行情基础设施

状态：`IMPLEMENTED_AND_VERIFIED`（分支 `codex/006-unified-marketdata-siftalpha`，待审查；未推送、未合并）

已完成真实 `siftalpha-research` 分支审计，并将统一行情契约、港股 MarketProfile、Provider Router、四维缓存、Tushare/Longbridge/Coinbase 适配器和应用层入口迁移到 HuntAlpha。详见 `docs/tasks/006-unified-marketdata-siftalpha.md`。本任务不加入交易策略；无凭据或权限不足时必须显示 unavailable。

### Task 005.1.3 — Real-time Market Data & Indicator Pipeline Foundation

状态：`ACCEPTED`

核心原则：
> Provider 负责提供真实市场数据；Indicator / Formula 保持原有算法；实时行情更新当前正在形成的 bar；当前 bar 变化驱动技术指标重新计算。

正式范围：
- Provider-neutral realtime architecture，先以 Futu 作为真实 provider 验证，并为未来 Coinbase 接入同一管线保留边界。
- current live bar、closed bar 语义、provider timestamp、market timezone / session boundaries。
- realtime quote / Kline linkage、built-in indicator 与 Custom Formula realtime update。
- throttle / coalescing、Formula single-flight、stale response protection、reconnect / reconciliation、shared subscription registry、in-place chart update。
- 当前本地阶段使用 process-local realtime bus/cache；不因本任务提前部署 Redis。
- 全程不使用 fake fallback；缺失字段必须 unavailable/null，不得用 0 或静态值冒充。

明确不包含：2FA、登录设备、account session management、邮箱安全、支付和 Notification；这些属于未来各自任务。

### Task 005.1.4 — Crypto Market Data Foundation

状态：`IN_PROGRESS`

Task 005.1.3 已完成 review、合并和浏览器验收，状态为 `ACCEPTED`。本任务沿用统一 MarketSymbol、Watchlist、Kline、Indicator、Formula 和 RealtimeRegistry 管线，不创建第二套 Crypto runtime。

---

## 已确认、暂缓开发

### V2.1.0 — 个人行情 API（沪深 A 股 / 美股 / 港股）

状态：`DEFERRED / NOT STARTED`（用户于 2026-10-24 明确要求仅记入开发日志，当前不开发）。完整任务边界：`docs/tasks/024-v2-1-0-personal-market-data-api.md`。

- 用户在个人中心新增「行情 API」功能，为**沪深 A 股、美股、港股**配置经授权的个人行情 API；**加密货币不纳入**，继续沿用当前来源。
- 三个股票市场各自独立的「系统行情 / 用户行情」开关；连接及权限验证成功后该市场**默认优先用户行情**，也可随时主动改为系统行情；未连接或移除用户 API 则使用系统行情。
- 用户选择的来源须一致提供**实时报价 + 历史 K 线 + OHLCV/成交量 + 基于相同数据的技术指标**。切换来源应重载完整历史、清除旧实时状态，不能跨供应商混接、混复权。
- 用户行情不可用时如实提示，**不得静默混入系统行情**；真实/延时状态必须按供应商的实际权限确认，不能把接入成功等同实时。
- 用户账户级凭证加密、缓存/订阅/指标计算隔离、许可合规、无凭证泄露，是启动开发时不可省略的安全边界。独立上游的「恐慌与贪婪」及 AI 分析不自动跟随改用个人 API，不改变其原算法。
- Longbridge、Tushare 属于**待审核候选供应商**，首批具体支持范围、授权条款、账号权益尚未最终确认。自建任意 URL API 暂不包含。
- **未获新授权，不开始代码开发、迁移、构建或生产部署；V2.1.0 只是未来规划，不代表当前运行版本。**

---

## 已批准、待实现

### Task 005.2 — User Workspace Persistence Foundation

状态：`PLANNED`

核心原则：

> 行情数据来自真实市场，研究结果属于用户；真实市场数据按需计算，用户研究成果自动持久化。

需要账户级、跨设备保存的长期状态：
- 图表画线与文字标注
- 指标组合
- 指标参数
- 主/副图布局与副图高度
- 筹码峰开关
- 常用周期及其他长期图表偏好
- 后续策略、提醒、扫描预设、研究备注等用户主动建立的成果

不需要永久保存：
- 鼠标十字光标位置
- hover 状态
- 拖动过程的每一个像素
- loading 等瞬时 UI 状态

架构要求：
- 用户长期状态默认绑定真实账户并由服务器持久化，不能只保存在 localStorage。
- 当前 `MarketChart.vue` 中 `quantscope:sub-pane-heights` 的浏览器级 localStorage 属于后续迁移对象。
- 自动保存应使用 debounce；例如操作结束约 300–800ms 后保存，而不是每个 pointer move 都写数据库。
- 所有读写必须按 `request.user` 隔离，用户 A 不能读取或修改用户 B 的工作区。

### Task 005.3 — Chart Drawing Tools

状态：`PLANNED`

第一版建议工具：
- 选择 / 移动
- 趋势线
- 水平线
- 垂直线
- 射线
- 矩形区间
- Fibonacci 回撤
- 文字标注
- 撤销 / 重做 / 删除

数据设计原则：
- 画线锚点保存为 **时间 + 价格**，不能保存屏幕像素坐标。
- 默认作用域：`user + symbol + period`。
- 例如日线和 30 分钟画线默认分别保存，避免不同周期互相污染。
- 推荐通用模型语义：`ChartDrawing(user, symbol, period, drawing_type, geometry, style, created_at, updated_at)`；geometry/style 可使用结构化 JSON，以免每新增一种工具就改表。
- 画线显示后自动保存；移动/编辑结束后 debounce 保存。
- 换浏览器、换电脑或重新登录后必须恢复。
- 前端继续基于现有 `lightweight-charts` 与自定义 primitive 扩展，不因画线功能重写整个 K 线系统。

### Task 005.4 — 右侧筹码峰 / Chip Profile

状态：`PLANNED`

方向：
- 筹码峰显示在主图右侧，与主图价格纵轴对齐。
- 建议可开关，开启时占约 100–140px，关闭后恢复 K 线完整宽度。
- 复用现有 `core/chip_distribution.mjs` 计算核心，不另造一套相互矛盾的算法。
- 现有算法使用真实 K 线、成交量/成交额、换手率、流通股本等数据进行透明近似；不能宣传为交易所或券商提供的“真实投资者持仓成本”。
- 用户可见名称/说明应明确类似“筹码分布（HuntAlpha 模型）/ 基于真实成交与换手数据估算”。
- 不为每个用户保存一份筹码分布计算结果；只保存用户的“是否开启”等偏好。相同证券/周期的计算结果可未来做公共缓存。
- 不允许为了筹码峰制造静态数据或 fake fallback。

### Task 005 后续第一阶段 — Scanner + Strategy + News

状态：`PLANNED`

总体研究流程：

`发现/扫描 → 研究/K线+指标+AI → 跟踪/自选 → 规则化/策略 → 信号 → 事件解释/资讯`

待实现：
- Scanner：涨跌、成交活跃、放量、突破、新高、趋势、策略信号、自定义条件等；后台批处理/缓存，不让浏览器逐只扫描数千证券。
- Strategy：我的策略 / 信号中心 / 回测研究；指标 != 策略，策略需要股票池 + 条件 + 风控；所有信号和回测结果必须真实计算。
- News：全部/自选/财报/公司/宏观/异动等；没有真实 provider 时明确 unavailable，禁止假新闻。

### 市场榜单未来扩展

状态：`PLANNED`

当前 `market_leaders` 后端能力继续保留。未来可扩展：
- market_cap
- change
- turnover
- volume
- popularity / heat（必须有真实定义和 provider）
- strategy_signal

每个市场独立排名，不跨币种直接比较市值。

### 美股三大指数真实数据源

状态：`DEFERRED / PROVIDER_LIMITATION`

当前 Futu OpenD 环境可以处理美股个股，但实测不支持 HuntAlpha 当前映射的三个美股指数 snapshot：
- 标普 500
- 纳斯达克综合指数
- 道琼斯工业平均指数

当前正确行为是显示 `— / 暂不可用`，不使用 SPY/QQQ/DIA 冒充指数。未来若接入另一个真实 provider，可再补充真实指数数据。

### Free / Pro 真实权益体系

状态：`PLANNED`

当前已批准的明确权益：
- Watchlist：Free=10，Pro=20，账户全局共享。

尚未定稿：
- 私有指标额度
- 策略信号额度
- AI 分析额度
- 高级 Scanner
- 提醒数量
- 其他付费权益

要求：所有权益必须由真实后端 entitlement 决定；没有真实 entitlement 时不能伪造 PRO 状态。

---

## 长期架构原则

### 数据真实性

- 真实证券目录
- 真实报价
- 真实 K 线
- 真实指数
- 真实 provider 能力边界
- 真实计算结果
- provider 失败时明确 unavailable
- 禁止 static/random/demo/fake fallback

### 性能

`全量目录保存，轻量行情按需加载，K线/复杂指标按需计算，全市场扫描后台批处理。`

### 用户持久化

`长期研究成果与长期偏好绑定账户自动保存；瞬时交互状态不进入长期存储。`

### 数据安全

涉及正式本地数据库的迁移、批量修改、恢复、导入、清理等风险操作之前：

```text
python manage.py backup_local_db
```

必须确认 `integrity_check: ok` 后再继续。不得因产品任务泄露 Formula source、密钥、用户数据或数据库备份。

---

## 暂缓事项

### Oracle Cloud / 正式服务器部署

状态：`DEFERRED`

当前优先继续完善产品。正式公网部署前仍需解决 production security/config blockers，包括 DEBUG/ALLOWED_HOSTS、数据库、静态文件、CSRF/安全 Cookie/HTTPS/HSTS、邮件、内部 API 地址和真实权益/计费配置等。

---

维护方法：**未完成留在本文件；完成后从本文件移除并写入 `docs/work-diary.md`。**
