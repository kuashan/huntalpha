# SiftAlpha.com 开发与发布手册

> 本手册适用于 `kuashan/huntalpha` 网站、正式分支 `release/siftalpha-web-v1` 及其功能/修复分支。**三方分工由用户于 2026-10-21 确认**。本手册比仓库旧的 Codex 开发角色说明及旧 GitHub Actions 发布说明优先；其他项目（Crypto、Options Monitor、SiftAlpha X）不在此范围内。

## 一、职责分工（硬规则）

| 角色 | 主要责任 | 不承担 |
| --- | --- | --- |
| **ChatGPT（开发、修复与测试负责人）** | 从真实 GitHub HEAD 排查问题；设计最小范围；**修改业务代码并负责 Linux Bash 契约、Django/迁移等适用的发布前自动测试**；提升版本号；提交并 Push 到 GitHub；检查 diff；向 Codex 交付测试结论和发布指令；部署后协助检查实际页面功能 | 不把开发修复转交 Codex；不以“构建部署”为理由扩大业务需求；未获授权不变更生产 |
| **Codex（本地构建与部署执行者）** | 获取 ChatGPT 已提交并确认测试门槛的 Commit；使用本地 Docker 构建 `linux/arm64` 并完成镜像构建自身的必要检查；推送 GHCR 并核对真实 Digest；使用现有受控部署管理器进行不可省略的备份、迁移预检、部署、最小健康检查和异常停止/受控回滚 | **不承担常规业务开发/修复**；不进行多轮、复杂的部署后页面业务测试；不触发 GitHub Actions；不直接操作其他容器 |
| **用户（需求及最终验收负责人）** | 确认需求与范围；授权发布/部署；最终在真实网站验收；批准将版本冻结为新基线 | 不需代替开发或部署执行者解决代码/环境问题 |

**页面检查与最终验收是两个阶段：** 部署完成后，ChatGPT 在工具可访问的实际页面做合理的初步功能检查或根据用户提供的页面/截图核查，不把这份工作强加给 Codex；**只有用户确认，才算最终验收通过**。若后台受登录/Cloudflare Access 限制，ChatGPT 必须如实说明无法直接访问，不能谎称已检查。

## 二、版本、分支与事实源

- 当前已验收网站基线：**V1.1.4**，正式分支 `release/siftalpha-web-v1`，Commit `f8dc2948b1435034005b0bc7a041d6e5abc74e9f`。
- 每次正式业务功能/修复须增加版本号；下一计划版本是 **V1.1.5**，不修改已经验收通过的 V1.1.4 基线内容。
- **先 fetch 真实远端 HEAD**，再审计变动；不凭旧 SHA 覆盖他人提交。
- **ChatGPT 在独立分支提交所有代码修改**，通过 GitHub PR 审查后才允许合并至 `release/siftalpha-web-v1`；不在 `main` 或生产上直接开发。
- 必须记录版本、完整 Commit、分支、PR 和变更说明。GitHub 仓库为代码事实来源；运行状态以受控工具/生产健康检查为准。
- 不得无授权 force push、清空数据库、删除用户数据、泄露私有公式、凭据与密钥。

## 三、ChatGPT 的开发及交付流程

1. 明确问题与最小范围，核对真实远端 HEAD、现有逻辑和历史已验收内容。
2. 修改代码、必要测试、相关迁移保护及版本号；避免过度修复。
3. **负责发布前自动测试**：在隔离 Linux 环境执行 POSIX 部署 Bash 契约、可运行的 Django、迁移与前端回归；**未实际运行的测试如实标注**。Linux 系统测试不得交给 Codex 的 Windows Git Bash，也不得以无法下载测试 Docker 镜像为由无限重试。
4. 创建/更新开发分支、提交 Push、整理 PR；给 Codex 交付**确定的代码提交**与必要的构建检查，不要求 Codex重新开发。
5. 若 Codex 报告构建检查或预检失败，Codex 停止；由 ChatGPT 定位并修复代码，再提交新 Commit，之后 Codex 才重试。

## 四、Codex 的一次性本地构建/部署流程

1. 读取 `AGENTS.md`、本手册、当前任务说明；fetch 远端，核实指定开发分支/PR/Commit。
2. 读取 ChatGPT 的发布前测试报告，**不重复执行其 Linux Bash/Django/迁移回归**。在本地只执行构建固有步骤与构建结果校验（如前端依赖安装、前端产物构建、镜像平台与标签校验）；构建失败时停止并交由 ChatGPT 修复，不做无关测试或重复尝试。
3. 代码符合发布门槛后，以正式流程合并 PR 至 `release/siftalpha-web-v1`，记录**合并后新的完整 HEAD**。
4. 从该正式 Commit **本地 Docker Buildx 构建 `linux/arm64`**，设置正确 OCI source/revision/version，推送 `ghcr.io/kuashan/siftalpha-web`；从 GHCR 读取不可变 Digest、核对 ARM64 manifest。不得使用 GitHub Actions 或让生产服务器代替本地构建。
5. 获得用户对该不可变 Digest 的部署授权后，通过已有 `/usr/local/sbin/siftalpha-web-admin` 的固定管理命令部署；若 V1.1.5 新增迁移，先按受控 `upgrade <official SHA>` 升级工具（仅在确有需要时），再 `preflight <digest>`，确认备份 SHA、完整性、恢复副本及迁移演练全部通过，之后 `deploy <digest>`。
6. **部署后只做最小技术检查**：`status`、`health`、固定网站服务/镜像 Digest、必要的首页与后台 HTTP 状态。检查一次即可，不安排重复的全站业务巡检、人工点点点、长时间观察或额外功能回归。
7. 报告 Commit、Digest、检查结果、实际版本与可能风险，**把真实浏览器功能验收交还 ChatGPT/用户**。异常停止并说明；不得自行清库、直接 Docker 替换容器或改 Cloudflare。

**部署不可省略的安全检查与部署后复杂功能验收不是一回事。** 前者是必须的（数据库保护、迁移备份、镜像一致性、容器健康），后者不属于 Codex 的职责。

## 五、数据与回滚边界

- 所有版本沿用现有 `siftalpha-web-compose` 与 SQLite 持久化数据卷。保护四条私人公式、会员、自选、工作区及其他所有用户数据。
- 数据库迁移必须使用现有管理工具的允许列表/哈希审查、独立恢复副本演练和备份；禁止直接对生产数据库运行 `migrate`。
- 记录上一个镜像 Digest、受控备份及可用回滚路径。发现异常按现有受控机制停止并报告；回滚不等于自动恢复数据库，数据库恢复需要单独的用户授权。
- 不修改 Crypto、Options Monitor、其他容器、Cloudflare Tunnel/Access 或无关域名。

## 六、版本验收定义

- **开发与测试完成**：ChatGPT 完成代码、版本提升、GitHub Push、发布前自动测试及检查结果汇报；未完成项明确列出，不能视为通过。
- **构建完成**：Codex 本地构建与 GHCR 真实 Digest 核验通过。
- **部署完成**：受控预检/备份/迁移、镜像切换及最小健康检查通过。
- **用户验收完成**：用户在实际网站确认功能正常，才能将新版本冻结为下一基线。

任何阶段未完成，不得提前宣称后续阶段成功。

## 七、V1.1.5 本轮交接

- 功能：后台“行情来源”四市场独立选择（美股 / 沪深 A 股 / 港股 / 加密货币）。
- 代码分支：`feat/web-v1-1-5-market-source-admin`，草稿 PR [#58](https://github.com/kuashan/huntalpha/pull/58)。
- 现有生产仍是 V1.1.4；不得提前把 V1.1.5 宣称为已部署或已验收。
- 对应任务记录：`docs/tasks/015-admin-market-source-selection.md`。
