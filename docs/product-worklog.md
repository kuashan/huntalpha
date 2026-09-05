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

当前没有已启动但尚未完成的正式 Task。

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

### Crypto 真实数据接入

状态：`DEFERRED`

当前：
- 主页面已经恢复 Crypto preview，显示 BTC / ETH 身份。
- 当前没有真实 crypto provider，因此价格、涨跌幅仍为 `—`，搜索/目录/收藏不可伪造。

未来接入真实 provider 后再实现：
- Crypto MarketSymbol/交易对目录
- 实时报价
- K 线
- 自选
- 指数/基准（如确有真实来源）
- 权限、刷新与 provider 失败处理

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

### Account Menu + Personal Center / 账户菜单与个人中心

状态：`IN_PROGRESS`

当前方向：
- 顶部固定用户名可在身份徽章成熟后移除；徽章本身作为账户主入口。完整用户名、邮箱等身份信息放进账户浮层/个人中心，而不是长期占用 Header 横向空间。
- 账户入口不能只依赖 hover：桌面可支持短延迟 hover 预览，但 click 必须是主交互，移动端只用 click/tap。
- 账户浮层从上到下优先展示：身份区（头像/首字母、用户名、邮箱、FREE/PRO）→ 会员状态/到期时间（必须来自真实 entitlement）→ AI 豆余额（未来充值后永久有效）→ Watchlist 用量 → 后续工作区云同步状态 → 个人中心/会员与账单/安全与设置等入口 → 退出登录放最底部。
- 当前没有真实 Pro entitlement 或真实会员到期时间时，不显示伪造的 PRO/到期日期；对应字段应隐藏、显示 `—` 或明确“未启用”，以真实后端数据为准。
- 个人中心建议使用独立路由页面，并保持 HuntAlpha 深色金融终端视觉。核心模块方向：概览、个人资料、会员与 AI 额度、研究工作区、账户安全、偏好设置、通知、账单/发票（仅真实付费体系接入后启用）。
- 金融类偏好可包括默认市场、默认周期、涨跌颜色习惯、时区/交易时段等；这些必须与实际产品能力对应，不能出现无效设置。
- 研究工作区可在 Task 005.2 后展示真实的自选、画线、指标布局、策略/提醒/笔记等资产数量与同步状态；未实现能力不伪造统计。
- UI 动画保持克制：浮层约 120–160ms 淡入+轻微缩放，页面/卡片约 180–220ms 淡入+小幅位移，Tab/边框做短过渡；禁止持续闪烁、夸张发光和影响金融数据阅读的动画，并支持 `prefers-reduced-motion`。

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
