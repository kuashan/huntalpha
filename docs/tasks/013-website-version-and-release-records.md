# Task 013 — SiftAlpha 正式版本号 V1.0.0（最小范围）

Status: `IN_PROGRESS`（代码 PR #36 已提交；真实构建与网页验收待完成）

## 用户最终确认（2026-10-16，覆盖此前版本管理草案）

用户明确决定：现有 `siftalpha.com` 站点**从 V1.0.0 作为正式产品版本开始持续完善**，不再在网页上标记为「测试版」「DEV」或「staging」。页面底部只显示：

`SiftAlpha.com • V1.0.0`

**不提供网页更新记录**；版本号不是按钮、链接或可点击入口。此前草案中的「点击版本号打开更新记录」「构建更新记录弹窗」「发布记录 API」「发行管理面板」等均撤销，不得顺手开发。

用户同时明确：**任何新功能、附加优化或需求扩展，无论建议多好，必须先提出并获得用户确认，才能实施**。这包括版本历史页、自动更新提醒、版本详情等任何未批准的界面。

## 目标与范围

1. 在网站底部以小字号、简洁、克制的静态文本显示 `SiftAlpha.com • V1.0.0`。
2. 主交易页面和个人中心均展示**同一版本**；桌面和手机布局正常，不遮挡 K 线、价格、账号操作。
3. 版本号由**代码中一个可维护的单一版本常量或现有等价配置**提供；不要在两个页面散落不同的硬编码值。
4. 初始版本统一为 `V1.0.0`；未来版本变化按用户确认的版本号更新，可沿用 X.Y.Z（Patch / Minor / Major）规范；**本任务不主动升级版本号**。
5. 不改现有行情、指标、缠论、登录、会员、统一自选、权限和交易相关逻辑。兼容 PR #34 已实现并经用户 8/8 浏览器验收的前台修改。
6. 把「产品版本号展示」与「真实构建/部署/数据库回滚能力」明确区分：现有实际 Git HEAD、镜像和数据库恢复点仍应在既有工程/部署记录中真实可追踪，不能因显示 V1.0.0 就虚构发布 Tag、Digest 或一键回滚能力。**不新增发布管理系统**。

## 明确不做

- 网页更新记录、弹窗、详情页、点击版本号、版本更新通知。
- DEV/staging 等版本标签及测试版视觉提示（但不得因此移除当前 Cloudflare Access 或弱化真实环境的安全配置）。
- 新建 release manifest、发布记录 API、GitHub Releases/Tags 自动化、版本控制面板、回滚按钮。
- 自行发布 V1.0.1、V1.1.0 或其他版本。
- 自动修改 Oracle 容器、Cloudflare Tunnel/Access、生产数据库，或合并 PR #33/#34/#35。

## 实施位置

优先复用现有 Vue 组件架构与共用版本常量；检查 `frontend/src/App.vue`、个人中心 `frontend/src/components/PersonalCenter.vue` 和当前公共布局。不要为简单的底部版本显示新增 Django API、模型或 migrations。实现前以 GitHub 真实 HEAD、PR #34 的前端为基础，避免覆盖已验收 UI。

## 验收

- [ ] 主交易页面最底部显示 **SiftAlpha.com • V1.0.0**。
- [ ] 个人中心最底部显示**相同**文本。
- [ ] 版本号不可点击；不存在网页更新记录 UI。
- [ ] 版本值唯一维护且后续可明确更新，不在多个位置散落版本字面量。
- [ ] 桌面/手机不遮挡内容，保留现有行情、图表、账户与指标功能。
- [ ] 没有引入额外功能、后端 API、数据迁移或未获批准的优化。
- [ ] `npm run build`、相关自动测试、`git diff --check` 真实执行并报告；如后端未修改，不做无意义的后端重构。

## 执行纪律

阅读 `AGENTS.md` 与真实 Git HEAD；本任务已获批准，仅在独立分支实现，提交/Push、报告新 PR。**合并、部署、开放 Cloudflare Access 或进行额外功能开发仍必须逐项获得用户确认**。若发现与实际生产安全、构建、依赖或数据迁移有关的阻塞，明确报告，不得自行扩大范围。

## Implementation Progress — 2026-10-16

- Code PR: [#36](https://github.com/kuashan/huntalpha/pull/36)（Draft / OPEN，基于已通过浏览器验收的 PR #34 分支；不涉及 PR #35 文档分支的代码合并）
- Branch: `feat/013-official-v1-footer-20261016`
- HEAD: `2dcef7b7d43877f32b9bf88ff6bedf1a8cfe5a60`
- 变更范围：`App.vue`、`PersonalCenter.vue`、新增共用 `SiteVersionFooter.vue`、静态回归测试；不涉及后端、数据库或服务器部署。
- 检查：连接器读取真实源文件，9 项静态契约断言 PASS；与 PR #34 对比仅 4 个文件，diff 新增行无尾随空白。
- **尚未通过的要求**：在真实隔离 checkout 运行 `node src/components/SiteVersionFooter.test.mjs`、`npm run build`、`git diff --check`；桌面/手机实际布局及上线后显示仍待独立授权的部署验收。
- 无 GitHub Actions/Checks 记录。不得宣布 CI PASS、代码已被合并或网站已更新。
- 完成真实构建验证并提交报告后，再根据仓库任务流程评估 `IMPLEMENTED`；未获用户批准不得合并或部署。

## Codex Completion Report

- Branch: `feat/013-official-v1-footer-20261016`
- Commit: `2dcef7b7d43877f32b9bf88ff6bedf1a8cfe5a60`
- Push: 已通过 GitHub 提交
- Summary: 共用、不可点击的正式 `V1.0.0` 底部版本文字
- Files changed: 4（仅前端）
- Checks run: 9 项源码静态契约通过；真实 build/test 待执行
- Unresolved issues / scope deviations: 隔离构建、浏览器验收尚待完成；未扩大产品范围
- PR: [#36](https://github.com/kuashan/huntalpha/pull/36)

## Review

由 ChatGPT/用户验收后从 `IMPLEMENTED` 变为 `ACCEPTED`。
