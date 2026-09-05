# HuntAlpha 证券目录同步

`sync_symbol_catalog` 从富途 OpenD 读取普通股票目录，并把 provider 数据映射为 HuntAlpha 的统一 `MarketSymbol` 记录。命令只同步真实 provider 数据，不使用静态证券名单或假市值。

## 手动同步

在项目根目录运行：

```powershell
python manage.py sync_symbol_catalog
```

也可以只同步一个市场：

```powershell
python manage.py sync_symbol_catalog --market cn
python manage.py sync_symbol_catalog --market hk
python manage.py sync_symbol_catalog --market us
```

每个市场会输出读取、新增、更新、停用和市值候选数量。OpenD 或某个市场失败时，其他市场仍会继续处理；失败不会用静态数据补齐。重复执行是幂等的，provider 不再返回的历史证券只标记为 inactive，不物理删除。成功但返回空的普通股票目录会被视为可疑空目录，既不会调用入库，也不会批量把既有证券设为 inactive。

目录基础资料来自 `get_stock_basicinfo(..., stock_type="STOCK")`。市值来自真实 `get_stock_filter` 的 `MARKET_VAL` 降序结果。沪深 A 股会分别请求 `Market.SH` 和 `Market.SZ`，每个交易所最多保留 200 个候选，再按统一的真实市值合并排序；当前 OpenD 版本的 A 股筛选页可能混合两类交易所，适配器会按 provider code 前缀隔离并翻页到各自 200 个候选。港股只把主交易柜台纳入市值榜单，人民币/alternate counter 仍保留在目录供搜索，但不写入可排名的市值缓存；如果 provider 提供显式币种则保存该币种，否则保持空币种，绝不按裸数字与 HKD 混排。页面 Top 5 只从本地目录中有效且市值大于 0 的记录产生。当前 OpenD 对 `get_stock_filter` 的单次结果上限为 200，`get_market_snapshot` 的单次代码上限为 400。

当前支持：沪深 A 股、港股、美股。加密资产没有真实目录 provider，因此 API 明确返回不可用，不生成排名。

## Windows 每日任务

安装或更新当前用户的每日任务（默认 04:00）：

```powershell
.\scripts\manage_symbol_catalog_task.ps1 -Action Install -Time 04:00
```

如需指定 Python：

```powershell
.\scripts\manage_symbol_catalog_task.ps1 -Action Install -Time 04:00 -Python 'C:\Path\to\python.exe'
```

移除：

```powershell
.\scripts\manage_symbol_catalog_task.ps1 -Action Remove
```

脚本只有在用户明确执行 `Install` 或 `Remove` 时才修改当前用户的计划任务。任务动作始终调用同一个 `python manage.py sync_symbol_catalog`，不复制同步逻辑，也不修改其他系统全局设置。
