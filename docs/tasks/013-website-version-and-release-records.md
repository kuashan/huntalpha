# Task 013 — SiftAlpha 网站版本标识、更新记录与发布溯源

Status: `READY_FOR_CODEX`

## 背景

用户批准在网站最底部以小字号、克制风格显示统一版本标识，例如 `SiftAlpha.com • V1.0.0`。该字符串仅为设计示例，**当前未宣布真实首个正式版本，不得写死 V1.0.0 假装已经发布**。点击版本号须查看版本更新记录。主交易页面和个人中心读同一来源。

## 必须实现

1. 为网站建立一个**可追溯、受版本控制、唯一可信**的版本元数据来源（发布清单/受控构建注入/后端只读接口的组合）；前台交易页、个人中心、版本记录弹窗使用同一后端/构建来源，不得分散写死版本字串。
2. 展示：`SiftAlpha.com • Vx.y.z`；点击版本号打开可关闭、可键盘操作且移动端可用的更新记录界面。只实现更新记录展示，不擅自创建公开发布博客、营销文案或第三方依赖。
3. 遵循 SemVer 三段：Patch 修复（如 V1.0.1）、Minor 新功能（如 V1.1.0）、Major 重大版本（如 V2.0.0）。首个正式版本号应由真实上线/发布决定；未正式发布的 staging/开发构建明确显示 DEV/预发布，不能冒充正式发布。
4. 每条正式发布记录必须有：版本号、发布日期、更新内容、Git Commit SHA、Git Tag、部署制品标识（如镜像 digest / artifact ID）、与数据库变更相关的备份和回滚兼容性说明。不涉及数据库变更时明确标注不适用。
5. 构建的 Git commit、tag、制品标识与部署记录必须能在发布过程核实对应；无法获得可信元数据时显示「构建信息未提供」或明确预发布状态，禁止填入虚构 SHA、digest、tag、日期。
6. 网站 footer 尽量轻量并完整覆盖主交易页面和个人中心；不要侵入图表、改变行情刷新、布局拖拽或公式运行逻辑。
7. 保留历史发布记录，但不暴露秘密、内部服务器地址、数据库、个人信息或私人公式源码。
8. 记录实际构建、部署、数据库迁移和回滚边界：单纯改版本号不代表镜像能回退，也不代表 DB schema/数据能回退。

## 不做

- 不发布或强行把当前 staging 标记为 V1.0.0 正式版。
- 不代替 GitHub Releases/Tags 或 CI 创建虚假的生产发布。
- 不自动修改 Oracle 生产容器、Cloudflare 路由或 PR #33。
- 不更改支付、会员、指标或行情算法。

## 代码入口

`frontend/src/App.vue`、`frontend/src/components/PersonalCenter.vue`、共用底部版本展示组件、`frontend/src/api.js`、`quant_site/urls.py`、可审计的发布元数据与构建/部署文档。注意 PR #34 已更新 App.vue，实施时需基于其真实差异合并，不能覆盖 PR #34 的全市场 UI。

## 验收

- [ ] 交易页面和个人中心显示同一个版本标识，样式小、克制，桌面/手机无覆盖/布局问题。
- [ ] 点击弹出真实更新记录，支持关闭、Escape、键盘焦点及移动端。
- [ ] 开发/staging 未正式发布时明确 DEV；生产发布版本满足 SemVer 且为真实发布。
- [ ] release manifest 包含所需字段，并有真实性校验、缺失提示和安全回退。
- [ ] commit/tag/artifact 对不上时不得显示为正式已发布状态。
- [ ] 与 PR #34 已实现的市场卡片、自选/搜索逻辑兼容。
- [ ] 文档清晰说明如何生成正式 release、记录回滚制品和迁移兼容性。
- [ ] `python manage.py check`（如后端改变）、相关测试、`npm run build`、`git diff --check` 有实际结果。

## 安全与实施纪律

先读 `AGENTS.md`、真实 HEAD、PR #34 和 PR #33 的最新提交。单独代码分支实施，未经过审核不合并、不部署；发行数据只包含公开可分享的标识，不包含 token/凭据或 Formula 私有源。

## Codex Completion Report

- Branch:
- Commit:
- Push:
- Summary:
- Files changed:
- Checks run:
- Release metadata provenance:
- Unresolved issues:
- PR:

## Review

由 ChatGPT/用户验收后从 `IMPLEMENTED` 变为 `ACCEPTED`。
