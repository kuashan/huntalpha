# 通达信公式兼容范围

本项目使用唯一的服务端公式内核 `tdx-server-v2`。后台私有公式只在短进程中解析和计算；浏览器只接收线、色带、柱体、文字与图标坐标，不接收公式源码。

## 运行时行情边界

- 图表和指标试算统一使用本机富途 OpenD 的同一份历史/实时行情；历史 K 线显式采用前复权（`AuType.QFQ`），分时使用 OpenD 实时分时数据。
- `CalibrationDataset` 仅保存用户导入的通达信离线校准样本，供回归和差异定位使用；它不参与网页运行时数据回退，避免图表和指标计算混用不同数据源。
- `COST/WINNER/LWINNER` 的换手迁移优先使用 OpenD `turnover_rate`（百分比），其次用成交量与 OpenD `outstanding_shares` 推导；成交额字段只用于同一复权价格尺度下的成交均价判断。

“能够保存或执行”不等于“与通达信逐根、逐像素一致”。兼容能力按以下等级管理。

## A 级：OHLCV 可确定计算

- 基础行情与时间：`OPEN/HIGH/LOW/CLOSE`、`VOL`、`AMOUNT`、`REFC`、`AVGPRICE`、`TR`、`DATE/TIME/TIME2`、`YEAR/MONTH/DAY/HOUR/MINUTE`、`WEEKDAY/WEEKOFYEAR`、`PERIOD`、`DATETODAY/DAYTODATE`、`TIMETOSEC/SECTOTIME`。
- 均线与引用：`MA`、`EMA/EXPMA`、`MEMA/EXPMEMA`、`SMA`、`DMA/AMA`、`WMA`、`TMA`、`XMA`、`REF/REFV`、`REFX/REFXV`、`REFDATE`、`CONST`、`ALIGNRIGHT`。
- 极值、统计与逻辑：`HHV/LLV`、`HHVBARS/LLVBARS`、`HHVLLV`、`HOD/LOD`、`FINDHIGH/FINDLOW`、`FINDHIGHBARS/FINDLOWBARS`、`COUNT/SUM/MULAR`、`STD/STDP/STDDEV`、`VAR/VARP`、`DEVSQ/AVEDEV/MEDIAN`、`SLOPE/FORCAST/COVAR/RELATE/BETAEX`、`IF/IFF/IFN/IFC`、`CROSS/LONGCROSS`、`EVERY/EXIST/EXISTR/LAST/NDAY`、`FILTER/FILTERX/BACKSET`、`BARSLAST/BARSLASTS/BARSLASTCOUNT`、`BARSSINCE/BARSSINCEN/BARSNEXT`、`VALUEWHEN`。
- 数学与字符串：常用数学函数、`STRCAT/STRCAT6`、`VARCAT/VARCAT6`、`CON2STR/VAR2STR`、`STR2CON`、`STRSPACE`、`STRLEN/STRCMP/FINDSTR/SUBSTR`、`CODELIKE/NAMELIKE/NAMEINCLUDE`。
- 技术函数：`SAR/SARTURN`、`RSI`、`ZTPRICE/DTPRICE`。

其中 `XMA`、`REFX`、`BACKSET`、`BARSNEXT` 等是未来函数，最后若干根结果可能随后续 K 线变化。内地证券的 OpenD 成交量由“股”转换成通达信的“手”，`AMOUNT` 保持元；其他市场不做每手换算。

`REF` 在历史不足时产生无效值；`EMA/EXPMA/MEMA/SMA` 必须从第一个有效输入开始初始化，不能让开头的无效值污染整条后续序列。很多包含多级加权均线的趋势背景依赖这一规则。

## B 级：可计算但属于近似模型

- `COST/WINNER/LWINNER` 使用 `core/chip_distribution.mjs` 的可审计筹码分布模型。
- 该模型使用 OHLC、成交量、成交额和流通股本估算，不等同于通达信客户端的私有成本分布数据。
- 依赖这些函数的指标必须标注“近似”，不能宣称已与通达信逐根精确一致。

## C 级：已识别但依赖授权数据

- `FINANCE`、`INBLOCK`、行业/地域/概念字段、指数与跨品种序列、Level-2 资金流、专业财务、除权事件、盘口及不定周期字段。
- 解析器显式登记这些名称，使其与拼写错误可区分；未接入数据源时返回中性值，只为保留公式中不相关的可计算图层。
- `DYNAINFO` 目前只映射 OpenD K 线可确定的少量编号，不代表完整盘口支持。
- `TDXDLL*`、`USERFUNC*`、账户、持仓、交易信号与下单函数不在网站指标引擎中执行。

## D 级：绘图兼容

- 已结构化输出：`STICKLINE`、`DRAWLINE`、`POLYLINE/PLOYLINE`、`DRAWTEXT`、`DRAWNUMBER`、`DRAWICON`、`DRAWTEXT_FIX`、`DRAWNUMBER_FIX`、`DRAWBAND`、`DRAWKLINE`。
- `STICKLINE` 保留起点、终点、宽度、空心参数和背景/普通图层；宽度 4 作为标准柱宽，宽度 0 作为细线。
- 当前已区分实心、实线空心和虚线空心；`EMPTY=2/3` 的特殊中心画法仍待实现。
- `DRAWICON` 已能保留坐标并显示通用符号，但尚未逐一复刻通达信 1–51 号全部图标资源。
- `LINETHICK1–9`、常用颜色以及 `DOTLINE/POINTDOT/CROSSDOT/CIRCLEDOT` 的线型元数据会分别传递；`CIRCLEDOT` 按圆点与连接线共同显示。`DRAWLINE(...,EXPAND>=1)` 沿两个锚点确定的斜率向右延长，并在后续锚点完成时重算。`CROSSDOT` 暂以稀疏点线近似，特殊文字位置、图标形状和像素级抗锯齿仍需要截图校准。
- `DRAWNULL` 在比较表达式中按通达信空值标记处理：两个空值相等；数值与空值不等；任何大小比较遇到空值均不成立。这样 `BARSLAST(X!=DRAWNULL)` 只会定位实际数值点。

## 严格失败规则

- 词法器必须消费公式中的每一个字符，括号、引号、尾部词元或未知标识符有误时保存失败，不能静默忽略后输出错误图形。
- 目前不支持跨品种/跨周期的 `$`、`.`、`#` 引用，也不支持任意指标嵌套；出现时明确报错。
- 错误消息可包含缺少的函数或标识符名称，但不得包含私有公式正文。

## 新指标验收流程

1. 后台保存时使用合成 K 线执行严格语法与运行校验。
2. 对主图或副图调用指标渲染 API，确认返回预期的线、图元或信号。
3. 使用相同证券、周期、复权方式、历史长度和成交量单位，与通达信逐根校准。
4. 差异只通过函数语义、数据适配或渲染器修复，不修改用户公式；每次修复增加回归测试。
5. 每轮发布前对后台全部启用公式执行服务端回归，再运行 Django 检查、测试和 Vue 构建。
