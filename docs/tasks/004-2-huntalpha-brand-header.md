# Task 004.2 — HuntAlpha Brand Header 与狼头 Logo

Status: IMPLEMENTED

## 目标

将当前用户可见的旧 QuantScope/Q 品牌替换为 HuntAlpha 品牌体系：

- 品牌区域固定显示原创狼头 Logo、`HuntAlpha` 与 `HUB`；
- `HUB` 是产品标签，不代表账户权益；
- 账户区域只显示真实用户名或 Visitor 状态及退出操作；
- 登录页与 Boot Screen 使用 HuntAlpha；
- 保持 Task 004 的证券目录/Top 5/搜索，以及 Task 004.1 的真实 OpenD 指数行情不变。

## 范围与约束

- Logo 使用仓库内维护的简洁原创 SVG，不依赖外部网络资源；
- 不修改 API、session/localStorage key、数据库、Formula、行情 provider、迁移或 Task 005 页面业务；
- 不伪造 Free/Pro entitlement；
- 不使用静态指数价格或 fake fallback。

## 验收检查

- [x] 用户可见品牌不再显示 QuantScope 或 Q Logo；
- [x] Header 与登录页显示 HuntAlpha/HUB；
- [x] Logo 在窄屏保持可识别且不造成布局溢出；
- [x] Task 004/004.1 运行时契约保持；
- [x] 完成 `git diff --check`、Django checks/tests 与前端 build；
- [x] Formula 记录保持 4 条且源码未读取、未修改；

## Completion Report

- Branch: `codex/004-2-huntalpha-brand-header`
- 实现：新增本地原创几何狼头 SVG 与 `HuntAlphaLogo.vue`，更新终端 Header、登录页、Boot Screen 和 favicon/title。
- 品牌：用户可见区域使用 `HuntAlpha`；品牌标签固定为 `HUB`，与 Visitor/账户权益解耦；未伪造 Free/Pro。
- 兼容性：保留 Task 004 证券目录/Top 5/搜索和 Task 004.1 真实 OpenD 指数请求；未修改 API、行情、公式、数据库或内部 localStorage key。
- 真实浏览器验证：前端页面显示 HuntAlpha，沪深/港股指数返回真实 OpenD 数据，美股在当前环境显示不可用；Top 5、紧凑市值、真实报价和搜索区域保持可用。
- Formula：只读计数为 4；本任务未读取、未修改 Formula source；未新增 migration。
- 检查：`git diff --check`、`python manage.py check`、`python manage.py test core`（52/52）和 `npm run build` 均通过。Django 保留既有 3 个 W042 警告。
