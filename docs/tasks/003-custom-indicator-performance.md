# Task 003 — 自定义指标计算性能修复

Status: IMPLEMENTED

## 背景

HuntAlpha 当前 4 个用户自建私有指标在完整真实历史数据上都会返回：

`指标计算超时，请检查公式是否包含过大的递归或回看范围`

现有验证表明：同一批私有指标在少量 K 线下可以进入并完成公式计算，但在约 1200 根日线历史上会统一触发 8 秒超时。因此本任务首先按“公式执行管线性能问题”处理，不应直接修改用户公式源码来迁就超时。

当前公式执行路径中，`core/formula_runner.mjs` 会在每次私有公式执行前无条件调用 `calculateChipDistribution()`。这意味着即使公式完全没有使用 `COST`、`WINNER`、`LWINNER` 等筹码函数，也会承担完整筹码分布计算成本。

当前 `core/chip_distribution.mjs` 在每根 K 线上计算 0% 到 100% 共 101 个成本分位数，而每个分位数都会对筹码价格表重新复制、排序。这个复杂度会被完整历史窗口放大，并可能在真正公式计算开始前就耗尽 Django 为 Node 进程设置的 8 秒超时。

## 目标

1. 让不使用筹码函数的私有公式完全跳过筹码分布计算。
2. 优化真正使用 `COST` / `WINNER` / `LWINNER` 的筹码计算，消除同一根 K 线内对筹码表的重复排序。
3. 保留现有完整历史计算语义，不通过任意缩短历史窗口来“解决”超时。
4. 保留服务端公式源码保护，不向浏览器、日志、测试输出或 GitHub 暴露私有 Formula source。
5. 保留合理的执行超时保护；不要简单把 8 秒改成一个很大的数字来掩盖性能问题。
6. 修复误导性的超时提示，让用户知道这是“指标计算耗时过长”，而不是默认断言公式存在递归错误。
7. 最终用本地真实数据库里的 4 个私有指标逐个验证完整历史计算能够完成，且公式记录和源码完全不被修改。

## 范围

### 必须做

- 检查并优化 `core/formula_runner.mjs` 的筹码计算触发条件。
- 为公式建立可靠的筹码依赖判断：只有公式运行时真正需要 `COST`、`WINNER` 或 `LWINNER` 时才计算筹码分布。
- 依赖判断不能因为注释、字符串文本或名称中偶然包含相关单词而误判；优先复用公式解析/编译阶段产生的结构信息，或实现可测试的安全预检。
- 不使用筹码函数的公式，必须完全不调用 `calculateChipDistribution()`。
- 优化 `core/chip_distribution.mjs`：同一根 K 线不能为了 101 个分位点对同一筹码集合重复排序 101 次。
- 优化后的 `COST` / `WINNER` 结果要与当前实现的小型确定性基准结果保持一致，允许仅存在合理的浮点误差。
- 保留 `history_bars()` 的完整有界真实 OpenD 历史语义，包括 `BARSCOUNT`、`BACKSET` 等可能依赖历史起点的公式行为。
- 保留 `tdx-server-v2` 服务端执行边界。
- 保留 Formula source 只存在于服务端子进程输入中的安全原则；不得把源码加入 API、浏览器、异常消息、日志或测试快照。
- 更新超时错误文案，使其不再默认指责用户公式包含递归或超大回看范围。
- 为非筹码公式“跳过筹码计算”增加自动回归测试。
- 为筹码算法增加正确性回归测试，至少覆盖 `COST` 和 `WINNER` 所依赖的数据结构。
- 增加约 1200 根 K 线规模的性能回归验证。性能测试应尽量避免依赖极其脆弱的毫秒级阈值，但必须能够防止恢复到“每根 K 线 × 101 次排序”的实现。
- 在实现完成后，用本地真实 OpenD 和正式本地数据库逐个验证当前 4 个私有指标。

### 不做

- 不修改 4 个私有指标的 Formula source。
- 不在 GitHub、PR、Completion Report、日志或终端输出中打印 Formula source。
- 不把用户私有公式复制成测试 fixture。
- 不减少真实历史窗口，仅为了规避性能问题。
- 不恢复静态行情、生成 K 线或其他假数据。
- 不改变 Task 001 的标准登录/注册/访客与真实 OpenD 数据基线。
- 不重写整个通达信公式引擎。
- 不在本任务中处理生产部署、Oracle Cloud、PostgreSQL、CSRF/HTTPS 等无关事项。
- 不执行 `migrate`、`flush`、数据库清理或任何不必要的数据写操作。

## 建议实现方向

### 1. 筹码计算按需执行

当前：

```text
每个私有公式
    ↓
无条件 calculateChipDistribution(...)
    ↓
compileFormula(...)
```

目标：

```text
公式预检 / 编译依赖分析
    ↓
是否真正需要 COST / WINNER / LWINNER？
    ├─ 否 → 不创建筹码分布，直接执行公式
    └─ 是 → 计算优化后的筹码分布，再执行公式
```

不要仅用不区分注释和字符串的粗糙 `source.includes('COST')` 作为最终实现。

### 2. 筹码分位数单次有序遍历

当前 `quantile()` 每次都复制并排序 `chips.entries()`。在同一根 K 线上 101 次调用会产生大量重复工作。

目标至少应做到：

- 同一根 K 线的筹码价格分布最多排序一次；
- 最好维护天然有序的价格桶/数组，避免重复排序；
- 一次累计遍历即可依次填出 0..100 的所有成本分位点；
- `WINNER` 的结果继续基于同一份归一化筹码分布计算。

### 3. 超时仍然是保护，不是性能方案

Django 的子进程 timeout 应继续存在，用来阻止真实死循环或异常复杂公式拖死服务。

如果实现后 8 秒已经足够，不要修改 timeout。

只有在完成算法优化、证明主要性能瓶颈已消除后，才可以基于实测提出一个小幅、明确有理由的 timeout 调整；任何调整都必须在 Completion Report 中单独说明理由和前后实测数据。

## 相关文件

- `core/formula_runner.mjs`
- `core/chip_distribution.mjs`
- `core/views.py`
- `frontend/src/indicators/tongdaxinFormula.js`
- `core/tests.py`
- 如新增 Node 侧测试，可新增最小必要的测试文件/命令
- `docs/tasks/003-custom-indicator-performance.md`

## 安全与数据规则

- 遵守根目录 `AGENTS.md`。
- 正式本地数据库只做必要的只读验证。
- 若任何操作会写数据库，必须先执行 `python manage.py backup_local_db` 并确认 `integrity_check: ok`。
- 自动测试只能使用临时测试数据或合成公式，不得读取/复制真实 Formula source。
- 最终真实验证只能报告：指标名称、是否成功、总耗时、K 线数量、错误类型等非敏感信息；不得报告源码片段。
- 任何性能诊断日志都不得包含 `item.source`、完整公式文本或公式表达式片段。

## 验收标准

- [ ] 不使用 `COST` / `WINNER` / `LWINNER` 的公式不会调用筹码分布计算。
- [ ] 使用筹码函数的公式仍能获得正确的 `COST` / `WINNER` 数据。
- [ ] 同一根 K 线不会再为 101 个 COST 分位数重复排序筹码集合。
- [ ] 优化前后小型确定性筹码样本结果一致（仅允许合理浮点误差）。
- [ ] 约 1200 根 K 线的非筹码公式可以在现有子进程超时保护内稳定完成。
- [ ] 约 1200 根 K 线的筹码计算有明确性能改善，并且不会恢复旧的重复排序复杂度。
- [ ] 本地 4 个私有指标在完整真实 OpenD 日线历史验证中逐个完成，不再统一出现当前超时错误。
- [ ] 4 条 Formula 记录数量不变。
- [ ] 4 条 Formula source 不变。
- [ ] API/浏览器仍然不会收到 Formula source。
- [ ] OpenD 仍是运行时真实行情源，不存在假数据回退。
- [ ] 超时错误文案不再默认声称用户公式有递归或超大回看问题。
- [ ] `python manage.py check` 通过。
- [ ] `python manage.py test core` 通过。
- [ ] Node/前端相关新增测试通过。
- [ ] `npm run build` 通过（如前端源码或共享公式引擎文件发生变化则必须运行）。
- [ ] `git diff --check` 通过。
- [ ] Git 工作区干净，数据库、备份、日志未被跟踪。

## Codex Completion Report

完成后报告：

- Branch: `codex/003-custom-indicator-performance`
- Commit: `11782c7`
- Push: success (`codex/003-custom-indicator-performance`)
- Root cause confirmed: yes. Non-chip formulas paid for unconditional chip distribution, and the old implementation copied and sorted the chip map once for each of 101 quantiles on every bar.
- Implementation summary: added a comment/string-aware call dependency pre-check; non-chip formulas pass directly to the compiler without invoking chip distribution; chip data is sorted once per bar and one cumulative traversal fills COST 0..100 while WINNER reuses the same normalized sorted data; retained the 8-second subprocess timeout and changed its message to a neutral long-running calculation message.
- Files changed: `core/chip_distribution.mjs`, `core/formula_dependencies.mjs`, `core/formula_runner.mjs`, `core/formula_runner_core.mjs`, `core/tests.py`, `core/formula_runner.test.mjs`, `core/views.py`, and this task document.
- Non-chip lazy calculation verification: passed. An injected calculator was not called for a synthetic non-chip formula; comments, strings, ordinary identifiers, and similarly named functions were not detected as dependencies.
- Chip calculation correctness verification: passed. Synthetic COST/WINNER/LWINNER calls enabled calculation, and the optimized deterministic fixture matched the pre-optimization result within floating-point tolerance.
- 1200-bar performance verification: the same synthetic non-chip runner benchmark decreased from 8220 ms before the change to 102 ms after the change. The structural chip regression processed 1200 bars with exactly 1200 sorts, never 101 sorts per bar.
- Private Formula verification（仅名称/成功失败/耗时/K线数量，不含 source）:
  - 火焰山 — success, 1211 bars, 560.2 ms, `tdx-server-v2`
  - 一气三清 — success, 1211 bars, 473.2 ms, `tdx-server-v2`
  - 神龙通道 — success, 1211 bars, 548.0 ms, `tdx-server-v2`
  - 缠论顺势而为 — success, 1211 bars, 770.7 ms, `tdx-server-v2`
- Formula count before/after: 4 / 4
- Formula source changed: no
- `python manage.py check`: passed; existing `models.W042` warnings remain for two models.
- `python manage.py test core`: passed, 27 tests.
- Node/frontend tests: `node --test core/formula_runner.test.mjs` passed, 5 tests.
- `npm run build`: passed.
- `git diff --check`: passed.
- Unresolved risks: the chip model remains an auditable triangular-turnover approximation rather than a proprietary terminal's exact COST model; OpenD remains a required runtime dependency and the 8-second safety timeout remains in force.
- PR: [#6](https://github.com/kuashan/huntalpha/pull/6), open against `main`; not merged.

## Review

由 ChatGPT/用户验收后填写：

- Result:
- Notes:
