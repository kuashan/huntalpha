# Task 004.1.1 — 紧凑市场概览 + 恢复 BTC / ETH 加密资产板块

Status: IMPLEMENTED

## 目标

- 将顶部市场卡片压缩为桌面端四列的 Market Overview Bar；
- 保留 A 股、港股、美股真实 Futu OpenD 指数状态；
- 恢复 Crypto preview，仅展示 BTC/ETH 身份和不可用状态；
- 不使用静态价格、假涨跌幅、网页数据、ETF 冒充指数或 fake fallback。

## 约束

- BTC/ETH 不进入证券目录、quote API、K 线 API 或数据库；
- Crypto 不标记为 `futu-opend`，而显示未接入真实数据源；
- 指数真实 `updated_at` 通过紧凑行的 tooltip/ARIA 保留，不为每个指数占用独立可视行；
- 不修改 symbol catalog、Top 5、搜索、quote/K 线、Formula、用户/权益系统或数据库。

## 验收

- [x] 顶部显示四列市场概览；
- [x] Crypto 显示 BTC/ETH 且价格、涨跌幅均为不可用；
- [x] A/H 指数保持真实数据，美股指数保持真实不可用；
- [x] 1920/1366 桌面四列和约 800px 的 2×2 布局无明显溢出；
- [x] 运行测试、Django check、前端 build 与 diff check；
- [x] Formula 仍为 4 条，未读取或修改 source，未新增 migration。

## Completion Report

- Branch: `codex/004-1-1-compact-market-overview`
- 实现：将市场区改为四列、约 100px 高的紧凑 Market Overview Bar；指数每项保持单行，真实 `updated_at` 通过 title/ARIA 保留。
- Crypto：恢复 BTC/ETH preview identity；不请求 quote/K 线，不进入证券目录，不设置 Futu source，价格和涨跌幅固定由无数据状态渲染为 `—`。
- 真实性：A/H 继续显示真实 OpenD snapshot；美股三项继续按 provider 实际不可用状态显示，不使用 ETF 或其他替代品。
- 兼容性：未修改 symbol catalog、Top 5、搜索、个股 quote、K 线、Formula、数据库或 migration。
- 浏览器：`http://127.0.0.1:5173/` 实测四列概览、A/H 真实指数、美股 unavailable、Crypto BTC/ETH preview、Top 5、搜索和 K 线区域均正常。
- Formula：只读计数为 4；本任务未读取、未修改 Formula source。
- 检查：`git diff --check`、`python manage.py check`、`python manage.py test core`（52/52）和 `npm run build` 均通过；Django 保留既有 3 个 W042 警告。
