# Task 007 — SiftAlpha 用户可见品牌改名

Status: IMPLEMENTED

## 目标

将现有用户可见的 `HuntAlpha` 品牌名称改为 `SiftAlpha`，为后续
`siftalpha.com` 上线准备品牌层，不改变统一行情、账户、公式或数据安全边界。

## 范围

- Header、登录页、Boot Screen、个人中心和浏览器页面标题显示 `SiftAlpha`；
- 继续复用现有原创狼头 SVG 与 `HUB` 产品标签；
- 不修改 API、数据库、迁移、Formula、行情 Provider、session key、localStorage key、
  仓库地址或内部环境变量命名；
- 历史 Task 004.2 文档保留原样，作为 HuntAlpha → HuntAlpha 品牌阶段的历史记录；
- 不在本任务处理域名 DNS、OCI 部署、HTTPS 或生产配置。

## 验收

- 用户可见主品牌显示 `SiftAlpha`；
- 用户可见区域不再显示 `HuntAlpha` 或 `QuantScope`；
- `HUB`、狼头 Logo、登录/注册/访客流程保持可用；
- 统一行情、真实不可用语义、账户入口与个人中心不受影响；
- `python manage.py check`、相关 Django tests、`npm run build` 和
  `git diff --check` 通过；
- 无数据库写入、无 migration，Formula 记录仍为 4 条且源码未读取/修改。

## Completion Report

- Branch: `codex/007-siftalpha-brand-rename`
- 用户可见品牌：Header、登录页、Boot Screen、个人中心和浏览器标题均使用 `SiftAlpha`；
- 保留：原创狼头 SVG、`HUB`、登录/注册/访客、账户入口和统一行情；
- 未修改：API、数据库、migration、Formula、行情 Provider、session/localStorage key、仓库地址；
- 验证：Django tests 193/193、`python manage.py check`、`python manage.py makemigrations --check --dry-run`、
  前端指标/实时测试、`npm run build` 和 `git diff --check` 通过；
- Formula：只读计数 4，source 未读取/修改；
- 状态：已完成，等待 PR 审查，未合并 `main`。
