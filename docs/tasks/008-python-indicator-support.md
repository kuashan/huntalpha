# Task 008 — 受控 Python 指标支持

Status: `IMPLEMENTED`

## 范围

为现有服务端指标链增加受控 Python 指标适配层。第一版只注册仓库内置缠论，不提供任意 Python 上传或执行能力；现有通达信 Formula 引擎保持不变。

## 审计结论

- `formula_editor.models.Formula` 只有通达信源码、显示位置和版本字段，没有 Python runtime 类型或安全注册引用。
- `formula_editor.forms.FormulaAdminForm` 会用 `core/formula_runner.mjs` 对源码做通达信语法校验，因此不能直接接收普通 Python 文件。
- `core/views.py` 原先把 CHANLUN 硬编码为一个特殊分支，其他指标都从 Formula 表读取并交给 Node 通达信引擎；没有统一的 Python 指标注册/错误契约。
- `core/chan_runner.py` 通过子进程调用仓库内 `vendor/chan.py-main`，本任务保留该算法和绘图语义，只修正时间输入的时区确定性。

## 实现决定

- 新增 `core/python_indicators.py` 作为受控注册表和服务器端执行适配器；当前唯一 code 为 `CHANLUN`。
- Python 指标只接收服务端已经取得的真实 K 线，前端不接收 Python 源码；结果统一为 `lines`、`sticks`、`markers` 绘图契约。
- 运行时解释器优先使用 `HUNTALPHA_INDICATOR_PYTHON`，兼容已有 `HUNTALPHA_CHANLUN_PYTHON`，否则使用启动 Django 的 `sys.executable`。
- 依赖缺失、执行失败、超时、输入过大、输出过大和无效响应均有结构化状态；错误只影响指标响应，不清空 K 线。
- `core/chan_runner.py` 使用标的交易市场时区（日线 A 股为 `Asia/Shanghai`，港股为 `Asia/Hong_Kong`，美股为 `America/New_York`，加密货币为 `UTC`）构造 Chan.py 日历字段，并保留原始 epoch；不依赖 Windows/Linux 主机时区。
- 缠论计算窗口与图表可见窗口分离：图表仍最多展示 1000 根，受控 Python 指标默认最多计算 5000 根；这覆盖了已验证的 3637 根真实日线，同时保留输入资源上限。
- `SZ.002315` 真实日线验证产生 5,009,337 字节 JSON，因此输出上限从 4 MiB 调整为 16 MiB；CPU/地址空间限制由 `core/chan_runner.py` 在受控子进程内部应用，Django 父进程不再使用 `preexec_fn`。
- 不新增数据库字段或 migration；Formula 私有源码继续留在服务端管理边界。

## 验证记录

- 真实行情：`SZ.002315` 日线由当前统一行情服务返回 3637 根，未因输入长度拒绝；缠论运行约 2.79 秒，返回 221 条线、25 个中枢绘图集合、57 个买卖点标记，未因输出或内存限制失败。
- 与 PR #30 已验收版本：对同一批 3637 根真实输入比较笔、线段、中枢和买卖点结构签名，全部一致。PR #30 的旧记录未进入当前仓库，当前可复核基线为其 `49685756fe6ed6f5a2c7bb81fd23c33c1b475a5f` 提交。
- 真实验证使用当前公开统一行情 provider；没有 Oracle ARM64 真机执行条件，因此不声称 ARM64 真机测试通过。

## Completion Report

- 分支：`codex/python-indicator-adapter`
- 受控 Python 指标：`CHANLUN`；没有任意 Python 上传或执行入口。
- `python manage.py check_python_indicators`：`CHANLUN: ok`。
- `python manage.py test core`：212/212 通过（包含本次计算窗口、资源限制和市场时区回归）。
- `python manage.py check`：通过；仅保留既有 `core.AccountProfile` 和 `core.MarketSymbol` 的 `DEFAULT_AUTO_FIELD` warning。
- `python manage.py makemigrations --check`：`No changes detected`。
- `python -m compileall -q core quant_site formula_editor`：通过。
- 前端指标/实时 Node 契约测试：通过；`npm run build` 等价使用现有 Vite 依赖完成构建并通过。前端源码本任务未修改。
- `git diff --check`：通过。
- 数据库、Formula source、日志和凭据：未读取、未修改、未加入 Git。
- Oracle ARM64：当前没有可用真机执行条件，因此不声明 ARM64 真机测试通过；代码使用跨平台解释器配置、市场时区输入边界和子进程内 POSIX 限制。

实现提交：`6bdf95ed76dc71b394223f2543279ebf18ef5f98`。

独立 PR：[#31](https://github.com/kuashan/huntalpha/pull/31)，目标分支为 `main`，未自动合并。
