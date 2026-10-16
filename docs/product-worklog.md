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

## 2026-10-16 — 已批准的新功能与 PR 状态（未合并）

### Task 010 — 全市场自选 / 统一搜索 / 紧凑市场卡片

状态：`BROWSER_ACCEPTED / MERGE_PENDING / NOT_MERGED`（PR [#34](https://github.com/kuashan/huntalpha/pull/34)，HEAD `97d4c57dc71a368b1a463b09b9b4acb4a1a868f9`，查询于 2026-10-16）

已有 PR 实现：四市场自选默认全显、跨市场真实证券目录搜索与代码精确匹配优先、证券名称/代码/市场标识、选中证券与顶部市场高亮同步、搜索/市场切换不错误清空图表、四市场卡片约 70px。Codex 报告 217 项 `core` tests 和前端构建通过；**2026-10-16 用户已完成 8/8 浏览器验收 PASS**：四市场全局自选、跨市场搜索、精确代码优先、证券/市场同步、切换不清空图表、桌面/手机紧凑布局、原有行情与指标无回归，以及自选新增→刷新仍保留→取消收藏→数量同步、K 线保留。验收记录见 [PR #34 评论](https://github.com/kuashan/huntalpha/pull/34)。远端此 SHA 没有 GitHub Actions/Checks 记录，不能宣称 CI 已通过；后续仍需明确合并授权，PR 尚未合并。**不要重复开发，不得将未合并工作写成正式完成**。

### Task 011 — FREE / PRO 真实会员与冻结自选

状态：`READY_FOR_CODEX`；规格：[`docs/tasks/011-free-pro-membership-watchlist-freeze.md`](tasks/011-free-pro-membership-watchlist-freeze.md)。

已批准：新注册默认 FREE；后台仅真正的 superuser 可改 FREE/PRO；后端账户权益为 FREE 10 / PRO 20；PRO 降级 FREE 时按原 `created_at,id` 顺序前 10 活动、其余冻结不删除；删一个活动自动解冻最早冻结；升级后按原顺序恢复。前台徽章和个人中心以服务器等级为准；不引入支付及其他 PRO 权益。需兼容 PR #34 的统一自选。

### Task 012 — 公式管理器 / 固定公式

状态：`READY_FOR_CODEX`；规格：[`docs/tasks/012-formula-manager-fixed-indicators.md`](tasks/012-formula-manager-fixed-indicators.md)。

已批准：Django Admin「通达信公式编辑器」改为「公式管理器」，含「通达信公式」「固定公式」。4 条私有 Formula 及其运行机制不变；固定 Python 指标在代码中注册、服务器执行，后台只读元数据并能启停；保留现有 CHANLUN 与 Chan.py，FREE/PRO 都可使用；不提供网页 Python 源码编辑功能。

### Task 013 — SiftAlpha 正式版 V1.0.0 极简底部标识（优先于 Task 011）

状态：`IN_PROGRESS / PR #36 OPEN / BUILD_PENDING`；规格：[`docs/tasks/013-website-version-and-release-records.md`](tasks/013-website-version-and-release-records.md)。

**2026-10-16 用户最终更正并批准**：从当前站点直接以正式产品版本 **SiftAlpha.com • V1.0.0** 持续完善，不在网页显示 DEV/staging/测试版。主交易页和个人中心底部使用同一小型静态版本文字；**不可以点击版本号，不要网页更新记录、弹窗、发布历史页或发布管理系统**。版本值单一维护，未来升级须再获用户确认。当前 Access、环境保护和真实构建/备份事实保持不变，不能用版本号替代工程发布/恢复核验。

**2026-10-16 代码进展：** 已创建 [PR #36](https://github.com/kuashan/huntalpha/pull/36)，以已验收 PR #34 分支为基线，仅涉及两页面、一份共用版本组件及静态测试。远端源文件静态断言 9/9 PASS；真实 `npm run build`、Node 测试、网页展示及合并/部署均未完成。必须先检查再验收，禁止把代码提交当成线上已经更新。

**用户批准规则（全项目）**：任何助手或 Codex 主动提出的新功能、额外优化、界面入口、扩大范围等，必须先与用户讨论、取得明确确认，然后才能开发；不得自行实现。具体边界同步见 `AGENTS.md` 第 6.1 节。

### 相关未合并 PR

PR [#33](https://github.com/kuashan/huntalpha/pull/33) 为 Oracle staging 部署，PR [#26](https://github.com/kuashan/huntalpha/pull/26) 为 Coinbase 历史开发；继续保持隔离，不能因上述任务自动合并、覆盖或重新开发。新任务从真实远端 HEAD 开工并评估 PR #34 的集成点。

---


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

### Oracle 站点的正式版本定位与工程安全核验

状态：`SITE_RUNNING / OPERATIONS_REVIEW_PENDING`

现有 `siftalpha.com` 通过 Cloudflare Access 访问 Oracle Task 009 容器，PR #34 已经在现有站点运行并完成 8/8 浏览器验收。**用户决定把网站作为 V1.0.0 正式产品持续完善**，不再使用网页测试版标签；但这不代表已经移除 Access 或所有正式运营安全条件都经过验证。任何公网开放、配置变更、发布/回滚操作都应独立征得明确批准。此前发现 ARM64 Longbridge 固定版本安装失败、npm 高危依赖告警，仍需另行审查，不得擅自扩大 Task 013。

---

维护方法：**未完成留在本文件；完成后从本文件移除并写入 `docs/work-diary.md`。**
