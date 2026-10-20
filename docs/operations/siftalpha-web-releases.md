# SiftAlpha.com 网站受控发布操作手册（现行）

**三方职责、基线和验收门槛**以 [开发与发布手册](../DEVELOPMENT_HANDBOOK.md) 为准。本文件只记录网站生产的最小受控发布要求；旧版 GitHub Actions、首次 Compose adoption 和“禁止迁移”描述均不再代表实际流程。

## 生产现状和发布对象

- 网站正式分支：`release/siftalpha-web-v1`；已验收基线：**V1.1.4**，Commit `f8dc2948b1435034005b0bc7a041d6e5abc74e9f`。
- 网站服务固定为 `siftalpha-web-compose`；Oracle ARM64、持久化 SQLite、Cloudflare 配置不随业务版本发布改变。
- 仓库 `kuashan/huntalpha`；GHCR 镜像仓库 `ghcr.io/kuashan/siftalpha-web`。
- **ChatGPT 修改代码、提升版本、提交 PR；Codex 本地构建及部署；用户最终验收。**

## Codex 构建前及本地构建

1. Fetch GitHub 最新 HEAD，阅读 `AGENTS.md`、`docs/DEVELOPMENT_HANDBOOK.md` 与当前任务文档，核对 PR 代码和版本。
2. **一次**执行必要的构建门槛检查，覆盖此次变化的 Django 业务、迁移、安全保护及前端构建。测试失败就暂停，通知 ChatGPT 修复，不由 Codex 长期开发，也不无休止验证。
3. 通过后按批准的发布流程合并，记录 `release/siftalpha-web-v1` 的**合并后完整 40 位 Commit**，不要使用开发分支旧 SHA 冒充正式来源。
4. 使用 Codex 所在**本地**计算机 Docker Buildx 构建 `linux/arm64`，OCI source、revision、版本标签必须与正式分支/版本一致。推送 GHCR 后，重新读取**Registry 真实 Digest** 并核实 ARM64 manifest。
5. 不触发 GitHub Actions；不得将构建移至 Oracle 生产服务器。若本地构建工具不可用，暂停并报告。

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
