# SiftAlpha.com 网站受控发布操作手册（现行）

**三方职责、基线和验收门槛**以 [开发与发布手册](../DEVELOPMENT_HANDBOOK.md) 为准。本文件只记录网站生产的最小受控发布要求；旧版 GitHub Actions、首次 Compose adoption 和“禁止迁移”描述均不再代表实际流程。

## 生产现状和发布对象

- 网站正式分支：`release/siftalpha-web-v1`；已验收基线：**V1.1.4**，Commit `f8dc2948b1435034005b0bc7a041d6e5abc74e9f`。
- 网站服务固定为 `siftalpha-web-compose`；Oracle ARM64、持久化 SQLite、Cloudflare 配置不随业务版本发布改变。
- 仓库 `kuashan/huntalpha`；GHCR 镜像仓库 `ghcr.io/kuashan/siftalpha-web`。
- **ChatGPT 修改代码、提升版本、提交 PR；Codex 本地构建及部署；用户最终验收。**

## GitHub Actions 云端构建与发布门禁

1. ChatGPT 审查正式 PR、必要的 Django/前端/部署契约检查；测试失败立即停止，定位修复，不绕过安全门禁。
2. 代码合并到 `release/siftalpha-web-v1` 后，由 GitHub Actions 在标准 ARM64 Linux 运行器构建 **V1.1.6** 的 `linux/arm64` 镜像，推送 GHCR；不依赖本地 Windows，也不在 Oracle 生产服务器构建。
3. 构建前后核对正式分支完整 Commit、OCI source/revision、SHA-256 Registry **Digest** 和 ARM64 manifest；保留 BuildKit OCI provenance 及镜像来源验证，不把未经验证的标签当作发布许可。
4. 生产部署与云端构建隔离：构建成功**不自动部署**；须经用户单独授权指定 Digest，方可使用现有受控工具进行 `preflight` 和 `deploy`。Codex 不修改网站业务或数据库。
5. 受控预检用既有 SQLite `sqlite3.Connection.backup()` 生成备份并验证完整性；迁移白名单、独立恢复副本检查及回滚约束均保持不变。

## 服务器只走固定受控工具

通过现有授权入口调用 `sudo -n /usr/local/sbin/siftalpha-web-admin`；命令以实际安装工具支持为准。不得给运行账户开放 Docker Socket/管理员权限，或直接用 Docker CLI 替换生产容器。

1. 只读 `status` 与 `health`，核对基线。
2. 若此次迁移要求升级 root-owned 管理工具，仅使用既有 `upgrade <合并后正式 Commit>` 受控升级入口；升级后再次读状态。
3. 用户授权目标不可变 Digest 后，运行 `preflight <digest>`：核对 GHCR 来源/ARM64/正式 Commit、资源与容器；备份 SQLite，验证备份 SHA-256、独立恢复副本、完整性和批准的迁移演练。
4. 仅 `preflight: ok` 后运行 `deploy <digest>`。新增数据库迁移必须通过迁移白名单/哈希、保护旧表和受控迁移过程，不许直接执行 `manage.py migrate`。
5. 部署后只检查一次 `status`、`health`、运行镜像 Digest、必要 HTTP 响应；返回部署摘要。**Codex 无需重复或开展复杂页面功能验收。**
6. ChatGPT 协助检查实际页面功能；用户完成最终验收并决定是否冻结新基线。

## 异常与数据保护

- 保护用户账号、私人指标公式、会员、自选、工作区和所有已有 SQLite 数据；数据库备份、保护规则失败立即停止。
- 回滚优先按受控管理工具及既有快照机制；**数据库恢复不是自动回滚**，必须另行获用户许可。
- 不修改 Cloudflare Access/Tunnel、Crypto、Options Monitor 或其他无关容器。
- 禁止将凭据、令牌、备份文件、数据库内容、私有指标源码加入 Git、聊天报告或构建物。
- 完成报告只需 Commit、镜像 Digest、必要自动化构建检查、备份/迁移预检、部署状态与最小健康结果。失败应如实报告，严禁宣称已完成。

## 当前待发布任务

V1.1.5 四市场后台行情来源配置，任务 `docs/tasks/015-admin-market-source-selection.md`，开发分支 `feat/web-v1-1-5-market-source-admin`，PR #58。在用户最终验收以前 V1.1.4 仍是生产基线。
