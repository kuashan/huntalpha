# HuntAlpha 工作日记 / Work Diary

用途：记录已经解决、已经实现、已经验收或已经明确关闭的 HuntAlpha 项目事项，作为完成历史和决策档案。它与 `docs/product-worklog.md` 配合使用：

- `product-worklog.md`：只放 **还没解决 / 还没实现 / 正在进行 / 暂缓** 的事项。
- `work-diary.md`：放 **已经解决 / 已经实现 / 已经关闭** 的事项和最终决定。
- 某事项完成后，从 worklog 移除并追加到本日记；不要让同一个事项长期同时存在于“未完成”和“已完成”两边。
- 当用户问“之前还有哪些没实现”，应比对 worklog、work diary、`docs/tasks/` 以及 GitHub PR/commit 状态。
- 本日记记录的是项目有效结论，不保存聊天逐字稿、密钥、密码、token、Formula source、用户私密数据或数据库内容。

---

## 截至 2026-09-05 的已完成基线

### Git / 协作基础

状态：`COMPLETED`

- GitHub 正式仓库：`kuashan/huntalpha`，Private，默认分支 `main`。
- 本地正式工作目录：`C:\Users\Administrator\Documents\ChatGPT\huntalpha-github`。
- 旧项目目录作为 legacy/archive 保留，不再作为正式 Git 工作区。
- 旧 Git 历史因包含 Django SECRET_KEY 未上传；已经保留本地 bundle 备份。
- 清洁 GitHub 初始提交：`6584a82d4d842bb60c5cc126094c4f7a4120db72`。
- 协作基础 PR #1 已合并，根目录 `AGENTS.md` 为权威协作规则；旧 `agent.md` 只作历史/领域参考。

### Task 001 — 正常登录/注册/访客 + 真实行情边界

状态：`IMPLEMENTED`

合并主线：`c61848c078659fc9261171f61454b4f7e0e4ba9c`

最终决定：
- 前端使用正常登录、注册、访客流程，不做管理员专用 review mode。
- 行情、OHLC、K 线来自真实 Futu OpenD；不使用静态运行时行情、假 candles 或 fake fallback。
- provider 不可用时显示 unavailable/错误。

### Task 002 — 本地数据保护与自动备份

状态：`IMPLEMENTED`

合并主线：`a7463c0adcc3c61abd6fad014560af4fef6177f9`

已完成：
- `python manage.py backup_local_db`
- SQLite 只读源 + SQLite backup API
- repo 外默认备份目录
- 时间戳文件名、原子发布、integrity check、SHA-256、retention
- 危险数据库操作前强制先备份；备份失败则停止。

长期规则：迁移、导入、批量修改、恢复、清理等操作前先运行 `backup_local_db`，确认 `integrity_check: ok`。

### Formula 数据恢复事故

状态：`RESOLVED`

- 清洁 Git 工作区最初没有 Formula 数据，但 legacy DB 中存在 4 条 Formula。
- 已通过事务化 DB-to-DB 方式恢复 4 条 Formula，不输出、不导出 Formula source。
- 恢复后记录：火焰山、一气三清、神龙通道、缠论顺势而为，共 4 条。
- Formula 数据库仍不进入 Git；Formula source 继续视为私有数据。

### Task 003 — 自定义指标性能优化

状态：`IMPLEMENTED`

合并主线：`b0e101ef9d2ef559a640875d7d54c94fad263e34`

核心解决：
- 原公式运行无条件计算筹码分布，COST 0..100 造成大量重复 full-map sort。
- 增加安全依赖扫描，仅公式实际使用 `COST/WINNER/LWINNER` 时计算筹码分布。
- 筹码分布改为每 bar 排序一次并一次遍历全部 percentile。
- 8 秒安全 timeout 保留。
- 真实 1211-bar Formula 性能从秒级/超时风险降至约 0.5–0.8 秒区间；合成 1200 bars 从约 8.2 秒降至约 0.1 秒量级。

### K 线历史深度决定

状态：`RESOLVED / NO_CHANGE`

最终决定：
- 当前最多 1000 根 K 线足够使用。
- 暂时不调整历史深度和 warm-up。
- 未来只有出现具体、可验证的公式偏差时再单独开 Task。

### Task 004 — 动态证券目录 + 市值榜单能力

状态：`IMPLEMENTED`

合并主线：`9f9149be1883d137cb04148828c6306049dbcc2e`

完成：
- A/H/US 真实 provider-neutral 证券目录同步。
- CN/HK/US 全量目录进入本地目录库；搜索覆盖完整同步目录。
- market-cap Top5 后端能力完成，排名按市场本地币种独立进行。
- 无真实 Crypto provider，因此 Crypto 后端仍保持 unavailable 架构。
- suspicious empty catalog 会拒绝覆盖既有目录。
- 市值和证券目录都来自真实 provider，不使用假榜单或静态市值。

后续产品决定：市值 Top5 不再作为左侧默认 UI，但 **后端 `market_leaders` 与 market_cap 能力保留**，供未来 Scanner/排行榜使用。

### Task 004.1 — 真实市场指数顶部行情

状态：`IMPLEMENTED`

合并主线：`c2b9b6419228d7e05a28b3be4f91bdef1aec7076`

真实 OpenD 验证：
- 上证指数 `SH.000001`：支持
- 深证成指 `SZ.399001`：支持
- 恒生指数 `HK.800000`：支持
- 恒生科技指数 `HK.800700`：支持
- 标普500 `US..SPX`：当前 OpenD 不支持
- 纳斯达克综合 `US..IXIC`：当前 OpenD 不支持
- 道琼斯 `US..DJI`：当前 OpenD 不支持

实现：
- `/api/market-index-snapshots/`
- CN/HK/US 按市场批量 snapshot
- 60 秒低频刷新，页面隐藏/卸载停止
- 美股指数不可用时显示 `— / 暂不可用`
- 不使用 SPY/QQQ/DIA 代替指数
- 美股个股行情与“美股指数 snapshot 不支持”明确区分

### 产品工作纪要机制（第一版）

状态：`IMPLEMENTED`

- `docs/product-worklog.md` 创建并进入 main，用于保存讨论过但未实现的产品方向。
- 后续升级为“未完成 worklog + 已完成 work diary”双文件机制，见本文件顶部规则。

### Task 004.2 — HuntAlpha 品牌 Header

状态：`IMPLEMENTED`

合并主线：`cdf72ae4929e217bfefeabc4232c2f2f7661dd0b`

完成：
- 用户可见 `QuantScope/Q` 品牌替换为 `HuntAlpha`。
- 品牌标签固定为 `HUB`，与账户等级解耦。
- 不伪造 Free/Pro badge。
- 新增原创、本地几何狼头 SVG；专业深色终端风格，保留轻微上升趋势语言，无隐藏 A。
- 登录页、Boot Screen、favicon/title 同步品牌。
- Task004/004.1 行情和目录逻辑未被破坏。

### Task 004.1.1 — 紧凑 Market Overview + BTC/ETH Preview

状态：`IMPLEMENTED`

当前 `main`：`c6103bec38c0f36a7b06df36b9e1b4305257c111`

完成：
- Market Overview 压缩到约 100px。
- 桌面端四列；约 800px 使用 2×2。
- A/H 继续显示真实 OpenD 指数。
- 美股三大指数继续真实 unavailable。
- Crypto 卡片恢复，显示 BTC / ETH 身份，但没有真实 provider 前价格/涨跌幅均为 `—`。
- Crypto 不标记为 `futu-opend`。
- BTC/ETH 不请求假 quote/K线，不进入假证券目录。
- `updated_at` 通过 tooltip/ARIA 保留。

### PR #13 — BTC/ETH 工作纪要临时更新

状态：`CLOSED / NOT_MERGED`

- 曾创建文档 PR #13。
- 用户随后明确：是否更新工作纪要由用户指示；该 PR 已关闭且未合并。
- 该临时规则现在已被 2026-09-05 的新长期记录机制覆盖：与项目有关的有效讨论由 ChatGPT 持续整理，完成项进 work diary，未完成项留 worklog。

---

## 2026-09-05 — 新工作记录机制确认

状态：`DECIDED`

用户确认以后不希望为了回忆产品方向反复翻聊天记录。

最终机制：
1. ChatGPT 持续整理与 HuntAlpha 项目有关的有效讨论和决定，不保存无关闲聊逐字稿。
2. 未解决/未实现/进行中/暂缓事项写入 `docs/product-worklog.md`。
3. 已解决/已实现/已关闭事项从 worklog 移除，追加到 `docs/work-diary.md`。
4. 当用户询问“之前还有哪些没实现”，ChatGPT 比对 worklog、work diary、`docs/tasks/` 和 GitHub PR/commit 后给出最新清单。
5. 方向被新决定覆盖时，以最新决定为准；例如 Watchlist Free 配额已经从旧的 5 更新为 10。
6. 不在这些文档中记录密钥、token、Formula source、用户私密数据或数据库内容。

### Task 005.1 — 账户自选列表 + 搜索星标收藏

状态：`IMPLEMENTED / MERGED`

PR：#17

合并主线：`6ff474feeb1c54c9ede00bf1343bd9130e16b176`

最终实现：
- 左侧默认从市值 Top5 改为账户自选列表；搜索框继续查询当前市场完整真实证券目录。
- 搜索和自选列表加入 `☆ / ★` 星标；收藏成功为黄色 `★`，星标点击不触发行选择。
- 新增 `WatchlistEntry(user, symbol, created_at)`，`(user, symbol)` 唯一；自选绑定真实账户并可跨登录持久化。
- Free Watchlist 额度为全账户 10 个；Pro 配置预留 20 个；CN/HK/US 与未来 Crypto 共用同一总额度。
- 当前项目尚无真实 Pro entitlement，因此真实账户统一按 Free=10 执行，不用 staff/superuser/用户名伪造 Pro。
- 后端强制额度；同用户新增时在事务中使用 `select_for_update()` 锁定用户行，再做重复检查、额度统计、额度判断和创建，避免未来并发数据库下突破额度。
- 重复收藏幂等；第 11 个 Free 收藏由后端 HTTP 409 拒绝。
- 写接口使用 Django CSRF；Visitor 不能持久收藏。
- 当前 Crypto 只有 BTC/ETH preview，没有真实 MarketSymbol/provider，因此不能收藏，也不会请求假 quote/K线。
- `market_leaders` 和 market_cap 后端能力继续保留，只是不再作为左栏默认入口。
- 自选列表只加载轻量 identity/quote/change，不批量加载 K线、Formula 或 AI。
- 数据库新增 migration `0007_watchlistentry.py` 与用于同步既有主键状态的 `0008_alter_calibrationdataset_id_alter_indicator_id_and_more.py`。
- 迁移前正式备份与迁移后验证备份均完成并通过 `integrity_check: ok`；未执行 flush/reset。
- 最终回归：`python manage.py test core` 65 项通过，`python manage.py check`、`python manage.py makemigrations --check`、`npm run build`、`git diff --check` 均通过。
- Formula 仍为 4 条；Formula source 未读取、修改或输出。

### Task 005.1.1 — Account Tier Identity Crest

状态：`IMPLEMENTED / MERGED`

PR：#19

合并主线：`f4c0e8ddd0f7883a4f9ead2ddb4f78de5d0b27c5`

最终实现：
- 新增可复用的账户等级身份徽章，以皇冠 + 中央头像区 + 等级带作为账户身份视觉。
- FREE 使用蓝色体系，PRO 预留金色体系；当前没有真实 Pro entitlement，因此 authenticated 用户只显示真实 FREE，Visitor 不显示正式等级徽章。
- 头像区当时使用用户名首字符 fallback，并为后续真实 `avatar_url` 保留接口。
- Watchlist entitlement 继续使用真实 Free=10；Pro=20 仅作未来真实 entitlement 配置预留。
- 无数据库迁移、无正式数据库内容修改。
- 最终验证包含 `python manage.py check`、`python manage.py test core`、`python manage.py makemigrations --check`、`npm run build`、`git diff --check`，共 67 项 core 测试通过。

### Task 005.1.2 — Account Menu + Personal Center

状态：`IMPLEMENTED / MERGED`

PR：#22

合并主线：`7a0aced882031583bc11aae5043d73bfaedf1449`

最终实现：
- authenticated Header 移除常驻用户名与独立退出按钮；账户皇冠徽章成为账户主入口，支持 hover 预览、click 固定/切换、Escape 与外部点击关闭。
- Header 右侧账户控制组整体靠右，顺序固定为账户皇冠 → 语言选择；Visitor 保留访客身份/退出与语言入口，窄屏仍保留语言控件。
- 新增 `/api/account/summary/`、独立 `/account` 个人中心及 Overview / Profile / Membership & AI Beans / Security / Preferences 五个真实 section。
- 新增 `AccountProfile` 一对一账户资料/偏好模型，支持显示名称、头像、涨跌配色、默认市场和默认 K 线周期；读取摘要不会无故创建 profile，实际写入时才建立。
- 头像上传/删除要求 authenticated + CSRF，真实解码 JPEG/PNG/WebP，限制文件/像素尺寸，统一裁切为 512×512 WebP 并去除 EXIF；使用 Django storage abstraction，默认用户媒体目录位于仓库外。
- 市场涨跌配色支持 `cn`（涨红跌绿，默认）和 `international`（涨绿跌红），真实作用于 Market Overview、Watchlist、当前报价和 K 线蜡烛；Formula/指标作者自定义颜色不被改写。
- 默认市场与默认周期绑定账户并在新的 terminal session 初次进入时应用；用户本次会话中的手动选择不会被持续覆盖。
- AccountPopover 的 Watchlist 数量使用 App 实时状态，避免摘要缓存过期；账户摘要首次请求失败后可在下次打开时重试，成功后才缓存。
- 密码修改使用当前密码、Django password validators、确认密码、CSRF 与 `update_session_auth_hash`，不使用 `csrf_exempt`。
- AI 豆语义固定为未来充值后永久账户余额；当前 `status=not_enabled`、`balance=null`、`permanent=true`，无 daily/monthly/reset 字段。会员状态继续来自真实后端；没有真实 Pro entitlement 时只显示 FREE。
- 新增 migration `0009_accountprofile.py`；正式本地数据库迁移前后均执行仓库外备份并通过 `integrity_check: ok`，未进行破坏性数据库操作。
- Python 运行依赖清单明确为 Django、futu-api、django-simpleui、Pillow 四个已验证 direct dependencies。
- 最终回归：`python manage.py test core` 78/78 通过；`python manage.py check`、`python manage.py makemigrations --check`、`npm run build`、`git diff --check` 均通过。
- Formula 数量仍为 4；Formula source 未读取、修改或输出。

---

维护要求：本文件以追加完成历史为主；不要因为 worklog 清理而删除已经完成的重要决策轨迹。