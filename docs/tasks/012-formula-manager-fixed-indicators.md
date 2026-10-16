# Task 012 — Django「公式管理器」与服务器固定公式

Status: `READY_FOR_CODEX`

## 背景

当前 Django Admin 应用 `formula_editor` 管理现有通达信 `Formula`，需要将后台展示名称调整为「公式管理器」，并分为「通达信公式」和「固定公式」。现有 4 条私人 Formula 属于数据而非 Git 文件，必须保留。已有固定 Python 公式 `CHANLUN` 注册在 `core/python_indicators.py`，通过 `core/chan_runner.py` 在服务器端计算，网页只接受绘图结果。不得重新实现 Chan.py 或把 Python 代码发送到浏览器。

## 必须实现

1. Django Admin 导航 / 页面以「公式管理器」呈现，清楚区分「通达信公式」与「固定公式」两类；原标题改名不能造成已有 Formula 表、主键或源代码迁移丢失。
2. 「通达信公式」现有 CRUD、服务器公式计算、版本、位置、启用状态、源码仅管理员可见及四个私有 Formula 内容全部保持不变；禁止通过新 API 泄露 `source`。
3. 固定公式**必须是仓库代码中明确注册的受控实现**，可复用 `core/python_indicators.py` 的定义/运行器。任何网页用户均不能上传、编辑或在浏览器执行 Python 代码；后台不提供固定公式 Python 源码编辑框。
4. 新增必要的轻量持久化状态，支持后台查看每个固定公式的代码、名称、版本、主图/副图、启用与停用；只有启用状态允许后台修改，其余元数据来自代码注册表且只读。拒绝对不存在或未注册的固定公式创建可执行入口。
5. `CHANLUN` 必须仍注册且默认启用（保持现有功能）；后续添加新的固定公式时只需经审核的服务端代码和受控注册，不允许任意文件路径、shell 命令、动态 import、`eval`。
6. 网站 `/api/indicators/` 应统一列出已启用的通达信/固定公式和原有常用指标；停用固定公式立即从正常列表移除，直接访问其 render API 也不得继续执行。启用后使用现有 `/api/indicator-render/<code>/<symbol>/` 服务器计算、网页绘图链路；FREE/PRO 登录用户均可使用（不要另加会员限制），沿用原 visitor 边界。
7. 保持 Chan.py 算法、输出绘图结构、真实行情 Provider、SSE/Bar 联动和渲染语义不变；已有 private Formula 不因新功能改用第二套执行引擎。

## 不做

- 新增具体策略/交易信号或新固定公式算法。
- 重构或修改 Chan.py 算法、通达信公式源码。
- 将 Python 代码、私有 Formula source 或服务器目录浏览权限暴露给网站用户。
- 允许后台上传任意可执行脚本、动态 Python 插件。

## 代码入口

`formula_editor/apps.py`、`formula_editor/models.py`、`formula_editor/admin.py`、`core/python_indicators.py`、`core/views.py::indicators/indicator_render`、`core/chan_runner.py`、`frontend/src/components/IndicatorManager.vue`、必要 migrations/tests。

## 验收

- [ ] Django Admin 顶级为「公式管理器」，含两个分类；四个原 Formula 内容与数量没有损失。
- [ ] 固定公式「缠论结构 / CHANLUN」显示名称、编号、版本、主图、状态且源码不可编辑；默认仍正常执行。
- [ ] 超级管理员（或现有 Django 规定的管理权限）可启停，开关立即影响指标列表和直接调用 API。
- [ ] 固定公式不可用/运行失败时返回明确原因，不使用假绘图数据。
- [ ] 普通成员（FREE、PRO）均可使用已启用固定公式；未认证/访客遵守现有边界。
- [ ] 不存在代码注册的固定公式不能仅凭数据库记录被执行。
- [ ] 私人源代码绝不会出现在元数据、浏览器构建、API 回包、日志与 Git。
- [ ] 真实或隔离样本验证 `CHANLUN` 计算线/中枢/买卖标记正常；原公式与常用指标回归无退化。
- [ ] `python manage.py check`、`python manage.py test core formula_editor`（或真实可用测试套件）、migration check、`npm run build`、`git diff --check`。

## 安全与实施纪律

遵守 `AGENTS.md`；先核查 PR #33 部署分支兼容性。任何目标库迁移前需独立备份并通过完整性检查；正式已有 4 条 Formula 仅核对数量/元数据，不打印正文。不改 Oracle 正式库、不自动部署或合并。

## Codex Completion Report

- Branch:
- Commit:
- Push:
- Summary:
- Files changed:
- Checks run:
- Data safety and migration/rollback evidence:
- Unresolved issues:
- PR:

## Review

由 ChatGPT/用户验收后从 `IMPLEMENTED` 变为 `ACCEPTED`。
