# HuntAlpha 工作纪要 / Product Worklog

用途：记录已经讨论并形成方向、但尚未正式实现或尚未合并的产品决策与后续事项，避免后续任务遗漏。真正进入开发时，应再转成独立 Task 文档并由 Codex 实现、ChatGPT/用户验收。

更新原则：
- 只记录已经讨论过、具有明确方向的事项。
- 不把这里的示例数值当成运行时数据。
- 所有行情、指数、新闻、信号、回测结果等业务数据必须来自真实 provider 或真实计算；禁止静态假数据、随机 fallback 或演示值冒充真实值。
- 状态建议使用：`PLANNED` / `IN_PROGRESS` / `IMPLEMENTED` / `DEFERRED`。

## 当前进行中

### Task 004.1 — 真实大盘指数顶部行情

状态：`IMPLEMENTED`

已完成：
- A 股：上证指数、深证成指
- 港股：恒生指数、恒生科技指数
- 美股：标普 500、纳斯达克综合指数、道琼斯工业平均指数；当前 OpenD 不支持这三个美股指数 snapshot，因此真实显示 unavailable
- 所有点位、昨收、涨跌额、涨跌幅、更新时间来自真实 Futu OpenD
- provider 不可用时显示 unavailable，不使用静态数字或 fake fallback

正式任务：`docs/tasks/004-1-real-market-index-header.md`

已合并 PR：`#12`

## 已批准、待实现

### 1. HuntAlpha 品牌 Header 重构

状态：`PLANNED`

实施顺序：Task 004.1 合并后再做，避免同时修改 Header / `App.vue`。

方向：
- 主品牌：`HuntAlpha`
- 产品标签：`HUB`
- 账户权益等级与品牌分离；未来真实显示 `Free / Pro`
- 不再使用旧的 `QuantScope` 主品牌和 `Q` Logo
- Logo：原创、极简、几何化狼头
- 风格：专业、金融科技、深色终端适配、青绿色主色
- 保留“极轻微上升趋势语言”
- 不隐藏字母 A，不做明显箭头、K 线拼图、电竞/卡通/咆哮风
- 优先使用仓库内可维护 SVG，不依赖外部图片/CDN

建议实施任务：`Task 004.2 — HuntAlpha Brand Header`

### 2. Task 005 第一阶段 — 扫描 + 自选 + 策略 + 资讯工作台

状态：`PLANNED`

目标导航/工作流：
`发现/扫描 → 研究/K线+指标+AI → 跟踪/自选 → 规则化/策略 → 信号 → 事件解释/资讯`

第一阶段页面：
- 扫描 Scanner
- 自选 Watchlist
- 策略 Strategy
- 资讯 News

原则：
- 先做真实数据可接入的专业工作台，不制造假股票、假信号、假回测、假新闻
- 页面之间围绕同一研究流程设计，不做互相孤立的栏目
- 指标 != 策略；策略应由股票池、价格/指标条件、风控规则等组成
- 资讯没有真实 provider 时明确 unavailable

### 3. 自选权益规则

状态：`APPROVED / WAITING_FOR_TASK_005`

已批准：
- 免费用户：最多 5 个自选证券
- 付费 / Pro 用户：最多 20 个自选证券
- 按账户 ID 限制，不按浏览器或设备限制
- 限制必须由后端执行，前端只负责提示
- 5 / 20 应作为可配置权益值，不写死到数据模型中
- 未来变更额度时不应重构 Watchlist 数据模型

已有 GitHub 记录：Issue #9 `Product decision: watchlist limits and on-demand market data loading`

### 4. 自选与搜索的按需加载策略

状态：`APPROVED / ARCHITECTURAL_RULE`

原则：
- 全市场证券目录可以完整保存在后端数据库
- 市场首页只展示少量结果，例如 Top 5
- 搜索只查询完整证券目录并返回匹配结果
- 用户搜索“茅台”并打开贵州茅台时，只加载该证券的重数据
- 自选页默认只加载轻量行情/状态
- K 线、私有指标、AI 分析等较重计算只在用户打开具体证券后运行
- 不因用户拥有 20 个自选就默认对 20 个证券全部计算 K 线和私有指标

### 5. 未来全市场扫描架构

状态：`PLANNED / ARCHITECTURAL_RULE`

原则：
- 不让浏览器逐只处理数千只股票
- 后台批处理 / 缓存扫描结果
- 前端只读取最终排名/筛选结果，例如 Top 20 / Top 50
- 可采用漏斗式扫描：
  1. 价格、涨跌幅、成交量等轻条件快速筛选
  2. MA/MACD/RSI 等技术指标筛选
  3. 复杂私有指标 / 策略仅对剩余小集合计算
- 后续 Scanner 需要根据真实 provider 限制设计批量和缓存策略

### 6. 市场榜单未来扩展

状态：`PLANNED`

Task 004 当前默认入口使用真实“总市值 Top 5”。未来榜单架构应能自然扩展，而不是写死只有市值：
- market_cap
- change
- turnover
- volume
- popularity / heat（仅在有真实定义和 provider 后）
- strategy_signal

每个市场独立排名；不同币种的市值不得直接跨市场混排。

### 7. Crypto 市场展示与未来数据接入

状态：`APPROVED / PROVIDER_DEFERRED`

当前批准方向：
- 主行情顶部重新显示加密资产板块
- 暂以 `BTC` 与 `ETH` 作为两个代表性资产名称
- 当前没有真实 crypto provider，因此 BTC / ETH 不显示任何静态价格、涨跌幅或假报价
- 未接入真实行情时，数值显示 `— / 暂不可用`
- 不使用 BTC/ETH 的网页抓取值、演示值、随机值或历史静态值冒充实时行情
- 后端现有 crypto unavailable 设计保留

未来：
- 接入真实 crypto provider 后，再为 BTC / ETH 以及其他交易对提供真实 quote / K 线
- 再讨论证券目录/交易对、行情、K 线、基准、权限和刷新策略
- 如未来扩展更多币种，仍必须遵守真实 provider 原则

### 8. K 线历史深度

状态：`NO_CHANGE_FOR_NOW`

当前决定：
- 现有最多 1000 根前端 K 线分页/展示目前够用
- 暂时不调整历史深度和指标 warm-up
- 如果以后发现具体公式在历史深度上出现可验证偏差，再单独建立 Task，不提前扩大计算量

### 9. Free / Pro 权益体系

状态：`PLANNED`

当前只批准了自选数量规则。

未来可讨论但尚未定稿：
- 私有指标使用额度
- 策略信号额度
- AI 分析额度
- 高级扫描
- 提醒数量
- 其他付费权益

要求：所有权益应由真实后端 entitlement 决定，不能仅通过前端标签伪造 `PRO`。

## 长期原则

### 数据真实性

HuntAlpha 所有面向用户的行情/研究数据坚持：
- 真实证券目录
- 真实报价
- 真实 K 线
- 真实指数
- 真实 provider 能力边界
- provider 失败时明确 unavailable
- 禁止 fake fallback

未来资讯、策略信号、回测结果同样遵守此原则。

### 性能原则

`全量目录保存，轻量行情按需加载，K线/复杂指标按需计算，全市场扫描后台批处理。`

### 数据安全原则

涉及正式本地数据库的迁移、批量修改、恢复、导入、清理等高风险操作之前：

```text
python manage.py backup_local_db
```

必须确认 `integrity_check: ok` 后再继续。不得因产品任务修改或泄露 Formula source、密钥、用户数据、数据库备份。

## 暂缓事项

### Oracle Cloud / 正式服务器部署

状态：`DEFERRED`

当前优先继续完善网站产品与本地/测试流程；OCI 公网部署、容量与成本问题以后单独讨论。正式上线前仍需先解决 production security/config blockers。

---

维护建议：每当讨论形成一个“以后要做但现在不做”的明确决定，就更新本文件；进入开发时再从这里拆出正式 Task，完成后将条目标记为 `IMPLEMENTED` 并链接对应 PR/Task。
