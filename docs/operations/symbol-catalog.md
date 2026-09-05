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

每个市场会输出读取、新增、更新、停用和市值候选数量。OpenD 或某个市场失败时，其他市场仍会继续处理；失败不会用静态数据补齐。重复执行是幂等的，provider 不再返回的历史证券只标记为 inactive，不物理删除。

目录基础资料来自 `get_stock_basicinfo(..., stock_type="STOCK")`。市值来自 `get_stock_filter` 的 `MARKET_VAL` 降序结果，每市场缓存最多 200 个真实市值候选；页面 Top 5 只从本地目录中有效且市值大于 0 的记录产生。当前 OpenD 对 `get_stock_filter` 的单次结果上限为 200，`get_market_snapshot` 的单次代码上限为 400。

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
