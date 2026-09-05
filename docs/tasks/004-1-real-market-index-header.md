# Task 004.1 — 真实大盘指数顶部行情

Status: IMPLEMENTED

## 背景

Task 004 已完成并合并到 `main`。当前行情页顶部仍显示 4 个市场卡片，并用 `— / 暂未接入真实市场指数` 作为占位。

用户已经明确批准：顶部区域应显示真实主要大盘指数；任何价格、点位、涨跌幅、昨收或更新时间都必须来自真实市场数据源，禁止静态数字、模拟数据、随机数或假 fallback。

当前加密资产没有真实 provider，因此在主行情界面暂时隐藏，不保留空卡片。后端现有 crypto unavailable 能力可以保留，未来接入真实 provider 后再恢复。

## 产品目标

顶部作为“市场温度计”，只显示少量真实指数 snapshot；不加载指数 K 线，不计算指标，不扫描全市场。

目标指数：

### 沪深 A 股

- 上证指数
- 深证成指

### 港股

- 恒生指数
- 恒生科技指数

### 美股

- 标普 500
- 纳斯达克综合指数（如果当前 OpenD 的正式名称不同，以 provider 实际可验证的对应综合指数为准，并在 Completion Report 说明）
- 道琼斯工业平均指数

### 加密资产

- 当前前端主行情界面隐藏
- 不显示静态 BTC/ETH/SOL
- 不显示假的 crypto 指数

## 核心原则

1. 所有数值必须来自当前真实 Futu OpenD / SDK。
2. 禁止把静态点位、静态涨跌幅或历史截图数字写入代码。
3. provider symbol/code 可以作为真实指数身份映射配置，但必须先由当前本机 SDK/OpenD 实测确认，不能凭记忆猜代码。
4. 某个指数无法获取时，只显示该指数 `—` 和真实不可用状态；不能用其他来源的假数字补齐。
5. 页面只请求这 7 个指数的轻量 snapshot，不请求它们的大量历史 K 线，不运行 Formula/指标。
6. 优先使用 OpenD 支持的批量 snapshot 能力，避免前端 7 次独立直连 provider。
7. 前端仍通过 HuntAlpha 后端访问市场数据，不直接耦合 Futu SDK。

## 编码前必须完成的 OpenD 实测

Codex 在正式实现前，必须使用当前项目安装的 Futu SDK 和本机 OpenD 实际验证：

1. 上证指数真实 provider code
2. 深证成指真实 provider code
3. 恒生指数真实 provider code
4. 恒生科技指数真实 provider code
5. 标普 500 真实 provider code
6. 纳斯达克综合指数真实 provider code
7. 道琼斯工业平均指数真实 provider code
8. `get_market_snapshot` 是否能一次批量请求这些指数，或是否需要按市场拆批
9. 每个指数当前账户是否有 snapshot 权限
10. 返回字段中真实可用的：
   - last_price
   - prev_close_price
   - open_price（如有）
   - high_price（如有）
   - low_price（如有）
   - update_time
11. 非交易时段行为：是否返回最近收盘/更新时间，是否存在 0、NaN 或 N/A
12. 当前 SDK/OpenD 对指数证券类型/名称的正式返回值

不要只查询互联网文档后直接硬编码；最终必须以本机 OpenD 实测为准。

## 后端设计

新增清晰的市场指数定义/adapter 层，不要把业务逻辑散落在 Vue 模板中。

建议提供统一接口，例如：

`GET /api/market-index-snapshots/`

返回结构可类似：

```json
{
  "source": "futu-opend",
  "markets": [
    {
      "market": "cn",
      "items": [
        {
          "code": "<real provider code>",
          "name": "上证指数",
          "price": 0,
          "change": 0,
          "change_percent": 0,
          "updated_at": "...",
          "status": "ok"
        }
      ]
    }
  ]
}
```

这里只是字段契约示例，示例中的 `0` 绝不能作为运行时 fallback。

要求：

- 涨跌额 = 当前点位 - 昨收
- 涨跌幅 = `(当前点位 - 昨收) / 昨收 * 100`
- 如果当前点位或昨收无效，不计算伪涨跌幅
- 数值必须经过 finite/valid 检查
- 单个指数失败不应让其他指数全部失败
- 返回每个指数独立的 `status/error`
- 不把 provider 异常原始敏感信息直接暴露给浏览器
- 不缓存/硬编码静态市场点位作为 fallback

## 前端设计

顶部改为 3 个市场板块，不再显示加密资产卡片：

```text
沪深 A 股
上证指数   3,xxx.xx   +xx.xx   +x.xx%
深证成指  xx,xxx.xx   -xx.xx   -x.xx%

港股
恒生指数      xx,xxx.xx   +x.xx%
恒生科技指数   x,xxx.xx   -x.xx%

美股
标普500       x,xxx.xx   +x.xx%
纳斯达克      xx,xxx.xx   +x.xx%
道琼斯        xx,xxx.xx   -x.xx%
```

实际点位必须来自 API，不得把上面示例数字写进运行时代码。

UI 要求：

- 保持 HuntAlpha 当前深色、高密度终端风格
- 3 个市场卡片平均使用顶部宽度
- 一个卡片内支持 2～3 行指数
- 显示：指数名称、点位、涨跌额或涨跌幅（至少点位 + 涨跌幅）
- 上涨/下跌沿用当前行情终端颜色规则
- 非交易时段仍显示 provider 返回的最近有效值和更新时间（如果 provider 有）
- 单个指数不可用时只显示该行 `—`，不要把整个市场卡片清空
- loading 状态不能显示假价格
- crypto 从当前主行情市场按钮/顶部卡片中隐藏；不要删除未来重新接入所需的后端 unavailable 设计

## 刷新策略

目标是轻量 snapshot，不是高频行情引擎。

Codex 必须根据本机 OpenD 实测和现有 quote 调用方式选择保守刷新策略：

- 首次进入页面获取一次
- 页面停留期间可以低频刷新
- 不要为 7 个指数建立高频逐个轮询
- 优先一次/少数几次后端批量 snapshot
- 页面不可见/组件卸载时停止 timer
- 如果没有必要，不引入 websocket/streaming 架构

在 Completion Report 中说明实际刷新间隔和一次刷新对应多少次 OpenD 调用。

## 数据真实性与安全

严格禁止：

- fake index data
- hard-coded index prices
- random fallback
- 从第三方网页抓一个数字塞进页面
- provider 失败后继续显示一个没有明确 stale 标记的旧静态值
- 为了 UI 演示写死涨跌幅

允许：

- 经过实测确认后的 provider index symbol mapping
- provider 不可用时显示 `— / 暂不可用`

## 与 Task 004 的边界

保留 Task 004：

- MarketSymbol 全市场证券目录
- A/H/US 总市值 Top 5
- 名称/代码搜索
- 只对可见少量证券请求 quote

本任务不要重写 symbol catalog，同样不要修改 Formula 计算逻辑。

## 测试

至少覆盖：

- 7 个真实指数定义映射结构
- 后端批量 snapshot 正常返回
- 涨跌额/涨跌幅计算
- `prev_close=0/null/NaN` 不产生假百分比
- 单个指数 provider 失败时其他指数仍返回
- provider 整体不可用时无静态 fallback
- frontend 不再渲染 crypto 主市场卡片
- frontend loading/error 状态不出现假点位
- 页面只请求指数 snapshot API，不为顶部卡片请求 K 线/指标

运行：

```text
git diff --check
python manage.py check
python manage.py test core
npm run build
```

如果增加前端已有测试，则运行相关测试；不要为了这个小任务引入重型测试框架。

## 数据保护

本任务原则上不需要 DB migration，也不应修改正式用户数据。

如果 Codex 判断必须产生正式本地 DB 写入，先：

```text
python manage.py backup_local_db
```

确认：

`integrity_check: ok`

再继续。

禁止：

- flush
- reset
- 删除数据库
- 修改 Formula source

最终 Formula 数量仍应为 4，source 不变。

## 完成要求

实现分支建议：

`codex/004-1-real-market-index-header`

完成后创建 PR 到 `main`，不要自行合并。

Completion Report 必须包含：

- Branch
- Commit
- PR
- 当前 Futu SDK/OpenD 版本
- 7 个指数各自实测 provider code + provider 返回正式名称
- 每个指数 snapshot 是否成功
- 是否批量请求、每轮多少次 OpenD 调用
- 实际刷新间隔
- A 股实际返回值截图/文字验证
- 港股实际返回值截图/文字验证
- 美股实际返回值截图/文字验证
- crypto 是否已从主界面隐藏
- 是否存在任何静态点位/假 fallback（必须为 no）
- `python manage.py check`
- `python manage.py test core`
- `npm run build`
- `git diff --check`
- Formula 是否仍为 4
- Formula source 是否未改变
- 工作区是否干净
- OpenD 权限/指数支持已知限制

## Review

由 ChatGPT/用户验收后填写：

- Result:
- Notes:

## Completion Report

- Branch: `codex/004-1-real-market-index-header`
- Implementation: added the provider-neutral `core/market_indices.py` adapter and `GET /api/market-index-snapshots/`; the frontend now renders three real-data market cards and hides crypto from the main page.
- Verified SDK: `futu-api 10.10.7008`.
- Verified OpenD mappings and provider names:
  - `SH.000001` — 上证指数 — snapshot succeeded.
  - `SZ.399001` — 深证成指 — snapshot succeeded.
  - `HK.800000` — 恒生指数 — snapshot succeeded.
  - `HK.800700` — 恒生科技指数 — snapshot succeeded.
  - `US..SPX` — 标普500指数 — current OpenD returned “暂不支持美股指数”, so unavailable.
  - `US..IXIC` — 纳斯达克综合指数 — current OpenD returned “暂不支持美股指数”, so unavailable.
  - `US..DJI` — 道琼斯指数 — current OpenD returned “暂不支持美股指数”, so unavailable.
- OpenD snapshot strategy: one batch per CN/HK/US market per refresh (3 calls on the normal path); failed market batches are isolated and may be retried per symbol. Current OpenD cannot serve the three US index identities, and their rows remain `— / 暂不可用`; US ETFs are not used as proxies.
- Refresh strategy: one request on authenticated page entry, then one backend request every 60 seconds; the timer stops when the page is hidden or unmounted.
- Real public validation: CN and HK returned real `last_price`, `prev_close_price`, `open_price`, `high_price`, `low_price`, and `update_time`; US index snapshots were unavailable because of the provider limitation above.
- No hard-coded index prices, no static point fallback, no random data, and no fake fallback were added.
- No migration and no database write were performed. The local Formula table remained at 4 records; Formula source was not read or modified.
- Checks: `git diff --check`, `python manage.py check`, `python manage.py test core` (49 passed), and `npm run build` passed. Existing Django model warnings remain unchanged.
