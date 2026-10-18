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

## 2026-10-18 — 正式开放前最后一项：前台公开、后台保留 Cloudflare Access

状态：`DECIDED / NOT IMPLEMENTED`（用户已确认访问模式；只记录决定，尚未切换或部署）

此项确定为 **SiftAlpha.com 正式向公网开放之前，最后执行的访问控制切换事项**。不代表其他上线前安全检查已通过，也不要求现在实施。

- **普通用户前端公开：** `https://siftalpha.com/`、前端账户页面以及前端正常工作所必需的 API，不再要求先通过 Cloudflare Access 身份认证。用户直接看到网站，使用 SiftAlpha 自身的登录、注册或访客模式；FREE / PRO 权限仍由 Django 服务端判断。
- **管理后台继续双重认证：** `https://siftalpha.com/admin/` 及其子路径继续受到 Cloudflare Access 保护；管理员先通过 Cloudflare Access，再使用 Django Admin 自身账号登录。不得因放开前端而一并放开后台。
- **Cloudflare 继续代理整个网站：** 保留 Cloudflare 的网站流量入口和安全防护（区别于 Access 身份认证）；需要防止其他主机名或源站直连绕过后台保护。
- **执行顺序：** 先完成上线前安全评估与经用户批准的必要最小整改，再将上述 Access 保护范围调整作为正式开放前的最后一步；变更前再次取得用户明确授权。调整后只验证前台无需 Access、后台仍必须 Access + Django 登录，以及没有绕过后台保护的公开入口。
- **范围限制：** 本条仅记录上线决策；不得自行修改 Cloudflare Access/WAF、DNS、服务器防火墙、Docker、代码、部署或数据。Task 010–013、图表对齐的已验收成果保持不变，Task 014-A 继续暂停。禁止借此事项重构现有功能。

## 当前进行中

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
