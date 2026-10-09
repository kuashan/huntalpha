# HuntAlpha System Overview

## 1. 产品定位

HuntAlpha 是准备正式上线的金融分析/量化网站。当前代码库已经具备 Django 后端、Vue 前端、金融图表、通达信公式兼容层、指标管理和本地行情接入等能力，但仍处于开发阶段。

## 2. 主要技术栈

### 后端

- Python
- Django
- Django Admin + SimpleUI
- 开发数据库：SQLite

### 前端

- Vue 3
- Vite
- Lightweight Charts

### 行情与分析

- `core/marketdata`：统一 MarketProfile/Router/Provider 入口；接入 Yahoo Finance、腾讯财经公开行情、Coinbase 公共行情，并预留 Tushare、Longbridge 可选增强 Provider；股票、加密资产与顶部指数均通过该入口取得数据
- 富途 OpenD：仅保留隔离的 legacy 兼容代码，不是历史行情、报价、指数或实时行情的默认运行时路径
- 通达信公式兼容层：服务端计算，前端只消费绘图结果
- `vendor/formula-ts`：Git submodule，上游研究参考
- `vendor/chan.py-main`：用于内置缠论结构适配的第三方代码，须保留许可证

## 3. 当前高层数据流

浏览器/Vue
→ Django API
→ `core.marketdata.MarketDataService`
→ `MarketDataRouter`
→ `MarketProfile`
→ Provider
→ 服务端指标或分析计算
→ 返回必要的元数据、坐标与信号
→ 前端绘图

Provider 失败时重新获取同一完整窗口，不拼接供应商数据；缓存至少隔离
`market + symbol + timeframe + provider`。实时页面继续使用单进程共享
Registry/StateStore/SSE，实时状态键同时包含 provider、market、symbol、period。

私有通达信公式正文不得沿这条链路返回给浏览器。

## 4. 公式引擎边界

当前约定：

- 运行标识：`tdx-server-v2`
- 核心解析/计算：`frontend/src/indicators/tongdaxinFormula.js`
- 服务端调用与绘图转换：`core/formula_runner.mjs`
- `vendor/formula-ts` 仅作研究参考，不参与运行时双引擎静默回退
- 禁止使用 `eval`

对于依赖授权专有数据的函数，如财务、板块、Level-2、通达信私有成本分布等，没有真实数据源时必须明确能力边界，不得伪造精确结果。

## 5. 私有资产边界

以下内容必须留在服务端或本地，不进入 GitHub/公开前端：

- 私有指标源码
- 本地 SQLite 业务数据
- 用户账号、Session、密码哈希
- 私有校准数据/备份
- API Key、Token、SECRET_KEY、支付/邮件/云服务密钥

`.env` 永不提交；`.env.example` 只记录变量名和占位符。

## 6. 当前开发环境

已知本地端口约定：

- Vue：`127.0.0.1:5173`
- Django Admin/API：`127.0.0.1:8003`
- `daily_stock_analysis`：`127.0.0.1:8000`
- 富途 OpenD：`127.0.0.1:11111`

这些地址是开发环境约定，不代表未来生产拓扑。

## 7. 当前尚未完成的生产能力

上线前至少需要独立任务完成：

1. 环境化 `DEBUG`、`ALLOWED_HOSTS`；
2. 生产数据库方案（优先评估 PostgreSQL）；
3. 数据迁移、备份、恢复策略；
4. `STATIC_ROOT` 与静态资源部署；
5. 正式域名与 HTTPS；
6. HSTS、Secure Cookie、SameSite；
7. 正式 CSRF/CORS 策略；
8. 邮件服务；
9. AI 服务密钥、调用边界和故障处理；
10. 点数/支付的账本、幂等、补偿、审计与合规；
11. 日志、监控、告警；
12. staging/production 分离；
13. 发布与回滚流程；
14. 数据授权、市场数据再分发和地区合规边界。

## 8. GitHub 与开发流程

- `main`：已认可的稳定版本
- task：`docs/tasks/`
- 开发：独立分支
- Codex 完成后：Push 分支并标记 `IMPLEMENTED`
- ChatGPT/用户审查通过：`ACCEPTED`
- 通过后再合并 `main`

生产上线不等于合并 `main`。未来应增加独立部署和环境验证阶段。

## 9. 历史文档

根目录 `agent.md` 和 `WORKLOG.md` 包含大量开发历史与细节。它们目前仍有参考价值，但并非所有描述都保证是最新架构事实。

如内容冲突：

1. 当前代码事实优先；
2. `AGENTS.md` 与正式 task/decision 优先；
3. 本目录的最新架构文档优先于历史记录。
