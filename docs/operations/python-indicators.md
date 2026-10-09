# Python 指标运行说明

HuntAlpha 的 Python 指标是服务端受控运行时，不是用户脚本上传功能。当前注册的唯一 Python 指标是 `CHANLUN`，其运行文件和依赖入口由仓库内 `core/python_indicators.py` 固定注册；前端和 API 不接收、返回或回显 Python 源码。

## 检查运行环境

在项目目录执行：

```powershell
python manage.py check_python_indicators
```

命令只输出受控指标代码和 `ok`/`unavailable` 状态，不读取数据库，不读取 Formula source。依赖检查会用实际选择的 Python 解释器导入 `vendor/chan.py-main` 的运行时模块。

## 选择 Python 解释器

默认使用启动 Django 的 `sys.executable`。如需隔离环境，可在 Windows PowerShell 或 Linux shell 中设置同一个跨平台变量：

```powershell
$env:HUNTALPHA_INDICATOR_PYTHON = 'C:\Path\to\python.exe'
python manage.py check_python_indicators
```

```bash
export HUNTALPHA_INDICATOR_PYTHON=/opt/siftalpha-venv/bin/python
python manage.py check_python_indicators
```

为兼容已有本地配置，仍接受 `HUNTALPHA_CHANLUN_PYTHON`；新部署优先使用 `HUNTALPHA_INDICATOR_PYTHON`。代码不假设 Windows 的 `Scripts\python.exe` 路径，也不把解释器路径提交到仓库。

## 依赖边界

当前 Web 适配器调用 Chan.py 的核心结构计算模块，这部分使用仓库内代码和 Python 标准库即可运行。`vendor/chan.py-main/Script/requirements.txt` 中的 Baostock、绘图、研究数据和交互式 UI 依赖属于上游研究脚本，不是本网站请求路径的隐式依赖；需要运行那些脚本时，应在单独的隔离环境按该文件安装。

每次指标请求仍有最大输入 K 线数、超时、输出大小限制；在支持 `resource` 的 Linux/Unix 环境额外设置 CPU 和地址空间上限，Windows 使用跨平台的超时、输入和输出限制。依赖缺失、超时、无效响应和计算失败都会返回结构化不可用/失败状态，K 线响应不会因此被清空。

## 时间一致性

`core/chan_runner.py` 将 provider epoch 转成 UTC 日历字段，并把原始 epoch 写入 Chan.py 时间对象。这样同一组输入不会因 Windows 与 Oracle Linux 的本地时区不同而改变日期字段。当前环境没有 Oracle ARM64 真机验证条件，因此本任务不声称 ARM64 真机已通过。

## 扩展边界

新增 Python 指标必须由代码审查后加入受控注册表和对应依赖探测，返回现有 `lines`、`sticks`、`markers` 绘图契约。不得通过指标管理表单上传或执行任意 Python 文件；现有 `Formula` 模型和 Node 通达信校验路径保持不变。
