# V1.1.11 — 个股恐慌与贪婪指数（现成服务集成）

## 用户确认与最小范围（2026-10-24）

- 使用现成 [iwanlebron/stock-analysis](https://github.com/iwanlebron/stock-analysis)，**不重新开发或改写其计算公式**。
- 网站图表（包含全部副图）下方新增只读的“个股恐慌与贪婪指数”展示组件，随当前所选标的切换；固定上游 `freq=1d`、`window=252`，不受主图周期影响。
- 显示现成服务原始 0–100 分、原版情绪标签、数据日期与上游八项子分数；定期按现成服务缓存周期刷新。
- 支持转换 `US.ORCL`、`SH.600519`、`SZ.002315`、`HK.00772`、`CC.BTC-USD` 等内部代码；不在网站实现任何情绪评分逻辑。北交所等尚未验证的代码显示明确“不支持”，不能伪造。
- 匿名请求不可调用接口；现有登录用户和受限访客可读取。服务 URL 仅在 Django 服务器环境变量配置，浏览器无第三方服务地址、密钥和公式。
- 分数绑定经过目录确认的证券代码，检查响应 ticker 与 score、date；快速切换标的中止旧请求，不显示前一个标的的残留分数。
- 上游关闭、未配置、数据不全、失败都显示明确原因；不会改变原图、公式、历史行情、账户、会员、数据库和其他容器。
- 另一个“个股技术动能”项目已确定沿用 `daily_stock_analysis` 原版六维评分且盘中可更新；本次 PR 不重复实现它的公式，也不扩大到 AI 系统。

## 运行契约

只新增可选环境变量：

```text
SIFTALPHA_STOCK_FEAR_GREED_URL=http://stock-fear-greed:8000
```

指向已获批准、可从网站容器访问的现成 stock-analysis 服务的**根 URL**。Django 仅转发该服务的 `GET /fear-greed?ticker=...&freq=1d&window=252&lang=zh&tail=30`。无配置时接口返回 `status=not_configured`（HTTP 503），界面明确提示“恐贪数据服务尚未配置”。

**生产接通条件（尚未完成）：**

1. 上游仓库暂未查到明确 LICENSE；需要确认商业站点运行/再利用的许可和 Yahoo Finance 派生数据展示/再分发权限。公开源码或镜像不代表商用授权。
2. Docker Hub `iwanlebron/stock-analysis:latest` 的真实 `linux/arm64` manifest 及不可变 digest 尚需实际核验；不能直接依赖 `latest`、不能在生产服务器从源码构建。
3. 当前网站受控 Compose 只包含网站容器；要运行独立服务或让它与网站容器建立受控网络连接，应先获得相应独立部署批准与安全白名单，不擅改现有容器、Cloudflare、Docker 网络或其他项目。
4. 只有满足上述条件、网站正式镜像经 Actions 完成 ARM64 构建，且用户明确批准确切 Digest 后，才能走原有 `siftalpha-web-admin` 受控备份、预检与部署机制。

## 代码变更

- `core/stock_fear_greed.py`：轻量只读上游 API 适配，限定 symbol、URL 和响应校验，不包含评分公式。
- `core/views.py` + `quant_site/urls.py`：现有身份保护下新增 `GET /api/stock-fear-greed/<code>/`。
- `frontend/src/components/StockFearGreed.vue`：独立组件，只渲染当前标的上游分数和八项分值，不改变 MarketChart。
- `frontend/src/App.vue`、`frontend/src/i18n.js`：挂在图表下方及六语言词条。
- `core/test_stock_fear_greed.py`、`frontend/src/components/StockFearGreed.test.mjs`：定向错误、身份、周期、快速切换的静态/单元契约。
- `.github/workflows/stock-fear-greed-pr.yml`：PR 提供单元测试、前端构建门禁，**不触发生产镜像构建/部署**。
- 页脚及 GHCR 构建元数据更新为 **V1.1.11**。

## 交付状态

代码仅在独立开发分支，待 PR CI 验证及审查；未合并正式分支、未生成正式 ARM64 Digest、未部署、未触碰数据库或其他容器。用户真实网站验收前不宣称功能上线。
