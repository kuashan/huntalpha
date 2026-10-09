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
- `core/chan_runner.py` 使用 UTC 日历字段并保留原始 epoch，避免 Windows 与 Linux 本地时区改变 Chan.py 输入。
- 不新增数据库字段或 migration；Formula 私有源码继续留在服务端管理边界。

## 验证记录

## Completion Report

- 分支：`codex/python-indicator-adapter`
- 受控 Python 指标：`CHANLUN`；没有任意 Python 上传或执行入口。
- `python manage.py check_python_indicators`：`CHANLUN: ok`。
- `python manage.py test core`：209/209 通过。
- `python manage.py check`：通过；仅保留既有 `core.AccountProfile` 和 `core.MarketSymbol` 的 `DEFAULT_AUTO_FIELD` warning。
- `python manage.py makemigrations --check`：`No changes detected`。
- `python -m compileall -q core quant_site formula_editor`：通过。
- 前端指标/实时 Node 契约测试：通过；`npm run build` 等价使用现有 Vite 依赖完成构建并通过。前端源码本任务未修改。
- `git diff --check`：通过。
- 数据库、Formula source、日志和凭据：未读取、未修改、未加入 Git。
- Oracle ARM64：当前没有可用真机执行条件，因此不声明 ARM64 真机测试通过；代码使用跨平台解释器配置和 UTC 输入边界。

实现提交：`6bdf95ed76dc71b394223f2543279ebf18ef5f98`。

独立 PR：[#31](https://github.com/kuashan/huntalpha/pull/31)，目标分支为 `main`，未自动合并。
