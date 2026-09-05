# Task 005.1.2 — Account Menu & Personal Center Foundation

Status: IMPLEMENTED

## 核心方向

- Task 005.1.1 的账户徽章作为 Header 唯一账户身份入口；徽章成熟后移除旁边常驻用户名。
- 桌面支持短延迟 hover 预览，但 click 必须可固定打开；移动端使用 click/tap。
- 账户浮层与个人中心必须保持 HuntAlpha 深色金融终端风格，动画克制并支持 `prefers-reduced-motion`。

## 账户浮层顺序

1. 身份区：头像/首字母、完整用户名、邮箱、真实 FREE/PRO。
2. 会员状态：真实计划；仅真实 Pro entitlement 存在时显示真实到期时间。FREE 不伪造到期日期。
3. AI 豆：显示真实永久余额。AI 豆定义为未来充值后长期有效的账户资产，不按天/月重置，不显示“下次重置时间”，也不周期清零。
4. 使用情况：当前 Watchlist 用量；未来 Task 005.2 后可显示真实工作区同步状态。
5. 快捷入口：个人中心、会员与权益、账户安全、偏好设置。
6. 退出登录：独立分隔并固定在浮层最底部。

当前若没有真实 AI 豆余额后端，不制造余额数字，显示 `—` / “暂未启用”或隐藏对应细节。

## 个人中心信息架构

独立账户页面建议包含：
- 概览：身份、会员、AI 豆余额、Watchlist 用量、未来工作区同步状态。
- 个人资料：真实头像、昵称、邮箱等；头像上传使用受限的本地媒体存储，不建立独立 Avatar 模型。
- 会员与 AI 豆：真实会员状态、真实到期信息（如存在）、AI 豆余额、未来充值/消费流水与权益说明。
- 研究工作区：未来展示真实自选、图表画线、指标布局、策略、提醒、研究笔记与同步状态；未实现的数据不展示假统计。
- 账户安全：修改密码、邮箱验证、未来二步验证、登录设备/会话安全能力。
- 偏好设置：默认市场、默认周期、涨跌颜色习惯；语言继续保留在 Header，时区暂缓。
- 通知：未来价格提醒、策略信号、资讯事件、账户安全通知等真实能力。
- 账单与发票：仅在真实付费体系接入后启用。

## UI / Motion

- 账户浮层：约 120–160ms opacity + `scale(.98 → 1)`。
- 页面/卡片切换：约 180–220ms 轻微淡入 + `translateY(4–6px → 0)`。
- 卡片 hover 仅轻微边框提亮/1–2px 位移，不持续发光或闪烁。
- 必须支持 `prefers-reduced-motion`。

## 数据真实性约束

- tier、会员到期、AI 豆余额、Watchlist 用量等必须来自真实后端状态。
- 当前没有真实 Pro entitlement 时，不伪造 PRO 或到期时间。
- AI 豆没有真实余额系统时，不使用静态/随机/demo 数字。
- AI 豆未来为充值后永久有效余额，不设置周期重置时间。

## 依赖

- 依赖 Task 005.1.1 账户等级徽章先合并到 `main`。
- 与 Task 005.2 用户工作区持久化协同，但个人中心第一版不应阻塞等待所有研究资产功能完成。

## Implementation / Completion Report

- AccountTierBadge 继续作为已登录账户的唯一 Header 入口；登录账户不再常驻显示用户名或独立退出按钮，visitor 保留访客身份与退出入口。
- 新增 AccountPopover：支持短延迟 hover、click 固定打开、键盘 focus、Escape 和外部点击关闭；入口使用真正的 button，并保留账户身份、会员、AI 豆、自选、快捷入口和底部退出顺序。
- 新增 `GET /api/account/summary/`，仅允许 authenticated user，返回真实用户摘要、统一 tier resolver 的 membership、真实全局 Watchlist 用量，以及 `status=not_enabled`、`balance=null`、`permanent=true` 的 AI 豆结构；没有周期重置字段。
- AI 豆被定义为未来充值后永久有效的账户资产；当前未建立余额或充值模型，不制造余额数字，不提供充值按钮。
- 新增 `POST /api/account/change-password/`，使用 Django 密码校验、CSRF 保护和 `update_session_auth_hash()`；密码修改只在测试数据库中验证。
- 新增 PersonalCenter：通过轻量 History API 提供 `/account` 与 section query，开放概览、个人资料、会员与 AI 豆、账户安全、偏好设置；未实现的研究工作区、通知、账单等不展示假统计。
- 当前没有真实 Pro entitlement，authenticated 账户返回并显示 FREE；visitor 不显示正式等级徽章。头像没有文件时使用用户名首字母，有文件时使用真实头像 URL。
- 新增 `core.AccountProfile`（用户一对一资料/偏好记录）：头像、涨跌颜色习惯、默认市场、默认周期；摘要读取不会自动创建，只有资料/偏好/头像写入时才创建。
- 新增资料、偏好和头像接口：`PATCH /api/account/profile/`、`PATCH /api/account/preferences/`、`POST/DELETE /api/account/avatar/`；均要求真实登录账户，写请求沿用 Django CSRF。
- 头像只接受 JPEG/PNG/WebP，原始文件上限 5 MB，校验真实解码格式和尺寸（不超过 4096×4096），服务器裁切为 512×512 WebP 并移除 EXIF；文件以不可预测 UUID 保存到仓库外的 `HUNTALPHA_MEDIA_ROOT`。
- 市场涨跌颜色通过 App 的统一语义 token 传递到概览、列表、当前报价和 MarketChart 蜡烛实体；公式自定义绘图颜色不被覆盖。中国习惯为涨红跌绿，国际习惯为涨绿跌红。
- 正式数据库迁移为 `core/migrations/0009_accountprofile.py`。迁移前已执行仓库外备份 `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-155719-597182.sqlite3`（SHA-256 `23fa478d91c889a7eec3c75853ac78c3dad341d037fa878f752eb92b14e2d87c`，`integrity_check: ok`），迁移后验证备份为 `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-155744-587170.sqlite3`（SHA-256 `aaf96082e00064e70987e22764b3d4576978c083af1f38c9dbf4c407128d5333`，`integrity_check: ok`）。
- 本轮没有读取、输出或修改 Formula source；正式数据库 Formula 数量仍为 4。数据库、媒体、备份和日志均不进入 Git。

### Final verification

- `python manage.py check`：通过（仅保留 Django `W042` 模型主键 warning）。
- `python manage.py test core`：78 tests passed。
- `python manage.py makemigrations --check`：No changes detected。
- `npm run build`：通过。
- `git diff --check`：通过。

## Continuation implementation / final scope

- Header authenticated 顺序固定为品牌/导航 → AccountPopover → 语言选择；认证账户不再常驻用户名或独立退出按钮，visitor 仍保留访客身份、退出入口和语言选择。账户浮层中的 Watchlist 数字优先使用 App 当前实时状态，避免摘要缓存导致旧计数。
- Personal Center 偏好页只保留涨跌颜色、默认市场和默认 K 线周期；语言仍由 Header 选择。偏好绑定真实用户并跨会话持久化，首次进入行情时应用默认市场/周期，用户之后的手动选择不会被自动覆盖。
- AccountProfile API 的显示名称写入 Django User 的 `first_name`（trim 后 1–50 个 Unicode 字符），邮箱、tier、额度、AI 豆和权限字段不可由资料接口修改。头像替换遵守“先保存新文件、再提交数据库、最后清理旧文件”；删除同样只操作当前账户。
- AI 豆仍是未来充值后永久有效的独立余额；当前 `status=not_enabled`、`balance=null`、`permanent=true`，不包含任何周期重置字段，也未伪造余额、Pro entitlement 或会员到期日。
- 最终验证：`python manage.py test core` 通过 78 个测试；`python manage.py check` 通过（仅有 Django `W042` 模型主键 warning）；`python manage.py makemigrations --check` 返回 No changes detected；`npm run build` 与 `git diff --check` 均通过。
