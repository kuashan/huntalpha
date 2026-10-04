# Task 006 — SLTD 对齐的统一行情基础设施

状态：`IMPLEMENTED_AND_VERIFIED`（当前分支等待审查，未推送、未合并 main）

## 事实源审计

本任务先读取了私有仓库 `kuashan/siftalpha-research` 的真实远端分支：

- `feature/market-data-provider-signal-decoupling-v1` @ `ca06ec3091ea6fc6adf092f3b2e704b7e58d80e7`
- `feature/sltd-shared-marketdata-5s-stocks-v1` @ `ce16312bc3651fefcf311f323377e7e2cdbb32c2`

审计文件包括行情边界规范、`shared_market_data` 契约、SLTD 数据 Provider/Router 和 Yahoo Provider。确认的事实是：业务层不识别供应商；MarketProfile 负责市场规则；供应商必须返回完整窗口；失败切换不能拼接窗口；completed/forming 分离；缓存按 market、symbol、timeframe、provider 隔离；行情凭据与交易账户隔离。

SLTD 当前的 Yahoo 只是 Provider 实现，不是本网站必须复制的供应商。本项目采用同一边界，Provider 候选为 Tushare（A 股）、Longbridge（港股/美股，未来可扩展 A 股备用）和 Coinbase 公共行情（加密）。新增港股 `HK_EQUITY`，时区为 `Asia/Hong_Kong`，正常交易时段为 09:30–12:00、13:00–16:00。

## 已实现

- `core/marketdata/` 统一契约、Profile、Router、四维 process-local cache 和同 Provider stale 回退。
- Tushare、Longbridge、Coinbase Provider 适配器；依赖和凭据均为惰性加载/环境变量读取。
- `MarketDataService` 接管报价、历史窗口、公式输入、目录同步和指数兼容入口。
- 旧 Futu OpenD 仅保留在显式 legacy 适配器和实时兼容桥中，未注册为历史/报价默认 Provider。
- 实时 Registry/StateStore/SSE 仍为单实例共享路径，状态键升级为 `provider + market + symbol + period`。
- Vue 图表错误提示不再按供应商分支；保留历史兼容的来源展示文字，但不参与路由或计算。
- 不加入任何策略、交易、仓位、BUY/SELL、C2 或自动交易逻辑。

## 凭据与不可用语义

Tushare、Longbridge 仅从本地 `.env` 或服务器环境读取；当前没有凭据时 Provider 返回 `not_configured`/`unavailable`，SDK、权限和实时能力不足也会显式报错。Coinbase 保持公共行情与交易账户分离。没有任何假行情或静态 K 线回退。

## 验证证据

- `python manage.py check`：通过；仅保留既有 `DEFAULT_AUTO_FIELD` 警告。
- `python manage.py makemigrations --check`：`No changes detected`。
- `python -m compileall -q core quant_site formula_editor`：通过。
- `python manage.py test core`：175/175，通过；仅保留既有 `DEFAULT_AUTO_FIELD` 警告。
- `python manage.py test core.test_marketdata_core`：6/6，通过。
- `python manage.py test core.test_marketdata_application`：通过。
- `python manage.py test core.test_marketdata_realtime core.tests.RealtimeCoreContractTests`：47/47，通过。
- `npm run test:indicators`：通过。
- `npm run test:realtime`：通过。
- `npm run build`：通过。
- `git diff --check`：通过。

## 已知边界

- Tushare 分钟权限、Longbridge SDK/权限和订阅能力需要由部署者配置并按 Provider 实际能力验证；未配置时不显示为实时。
- Futu legacy 适配器保留是为了迁移期间的 OpenD 回归和旧测试兼容，下一阶段应在 Longbridge/Tushare 实时能力落地后再评估移除。
- 当前 cache 为进程内缓存，生产多进程部署前应接入受控共享缓存，但必须保留四维隔离和同 Provider stale 语义。
- 真实行情授权、再分发许可、港股交易日/临时休市、生产 HTTPS/CORS/数据库仍需上线前专项审查。
