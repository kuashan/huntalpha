# Python 指标受控适配层实施计划

## 目标

在不改变通达信公式引擎和现有缠论算法的前提下，为服务端增加一个受控的 Python 指标执行适配层。第一版只注册仓库内置的 `CHANLUN`，不允许用户上传或提交任意 Python 源码。

## 约束

- Python 指标仅在 Django 服务端子进程执行；前端只接收统一绘图数据和非敏感状态。
- 指标失败、超时或依赖缺失时返回结构化错误，不能影响 K 线响应。
- Python 运行时通过配置或当前解释器解析，不写死 Windows 路径；依赖探测、超时、输入条数和输出大小均受限。
- `Formula` 继续表示管理员维护的通达信源码；不新增数据库字段，不读取或修改真实私有源码。
- 缠论时间字段以 UTC 字段和原始 epoch 构造，避免服务器本地时区改变计算输入。
- 本地 Windows 与 Linux/ARM64 只做可重复的代码和环境契约验证；没有 Oracle ARM64 真机时不声称真机通过。

## 实施步骤

1. 先补充 Python 适配器、注册表、运行时解析、依赖探测、资源限制和统一输出契约的失败测试；补充 UTC 时间转换测试。
2. 实现 `core/python_indicators.py`，将现有 `CHANLUN` 纳入受控定义，并保留旧错误代码语义。
3. 让 `core/views.py` 的指标列表和绘图入口通过注册表调用 Python 指标；通达信 Formula 分支保持原样。
4. 修正 `core/chan_runner.py` 的时间戳转换，仅改变时区确定性，不改变 Chan.py 算法和绘图含义。
5. 增加跨平台运行说明和 Chan.py 运行依赖说明，不把未使用的研究/交易依赖引入运行时。
6. 运行 Django 检查、核心测试、Python 编译检查、前端构建和差异检查；确认数据库、Formula source、日志和凭据未被触碰。

## 验收重点

- 原有通达信计算仍通过既有回归。
- CHANLUN 通过受控 Python 适配器仍返回 `lines/sticks/markers` 统一绘图形状。
- 未注册 Python code、缺失解释器、依赖缺失、超时、无效 JSON/超大输出均有明确结构化错误。
- 运行时错误只影响指标请求，不会清空 K 线。
- `python manage.py test core`、`python manage.py check`、`npm run build` 和 `git diff --check` 通过。
