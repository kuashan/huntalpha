# SiftAlpha 网站受控发布操作手册

本手册描述 `release/siftalpha-web-v1` 的未来网站发布流程。它建立发布能力，
不授权任何自动部署；构建成功也不等于允许替换 `siftalpha.com` 的网站容器。

## 固定边界

- 候选镜像只能是 `ghcr.io/kuashan/siftalpha-web@sha256:<digest>`；不得以标签作为
  部署输入。
- 只允许 `rdc-agent` 经 sudo 调用 `/usr/local/sbin/siftalpha-web-admin`。该账户不在
  Docker 组，不能读取 Docker Socket，也不能操作 Crypto、Options Monitor、Coolify、
  Cloudflare 或其他容器。
- 管理工具只接受 `status`、`health`、`preflight <digest>`、`deploy <digest>`、
  `rollback` 五种固定命令；不能接收容器名、镜像名、路径或任意 Docker 参数。
- 不运行迁移、不执行数据导入或清理；常规发布 does not run migrations。

## 候选构建与来源核验

发布分支 push 自动触发 `SiftAlpha Web CI and ARM64`。操作人必须从同一个成功的
GitHub Actions Run 收集完整 Commit、Run ID、Run URL、镜像地址和不可变 Digest。
在任何部署授权前，根权限工具必须同时验证：

1. GitHub Actions Run 属于 `kuashan/huntalpha`、固定 workflow 与
   `release/siftalpha-web-v1`，且状态为成功；
2. 该 Run 下载的 build manifest 将同一个 Commit、Run ID、Digest 和 `linux/arm64`
   绑定在一起；
3. 从 GHCR 读取的 BuildKit OCI SLSA provenance 确实作为 attestation manifest 关联到
   同一个 OCI Digest 的 `linux/arm64` 镜像；
4. 本地镜像 manifest 是 `linux/arm64`，并且 OCI source/revision/run-id/ref labels 与
  Actions 记录相符。

OCI labels are only a locator，不能单独证明镜像来源。BuildKit OCI provenance
(`buildkit-oci-slsa`) 是构建过程记录，不是 GitHub 官方的加密签名证明；BuildKit
provenance is not GitHub official encrypted signature proof. 它必须与 GitHub Actions Run、build
manifest、Digest、Commit、分支、标签和 ARM64 manifest 交叉核对。任一来源缺失、
不一致或无法从 GHCR 读取时，`preflight` 必须失败，不得部署。

## 未来的受控部署步骤

1. ChatGPT Work 展示已核验候选的 Commit、Run ID、Run URL、Digest 与镜像地址。
2. 取得 separate user deployment approval，且授权必须明确指向该不可变 Digest。
3. 运行 `sudo /usr/local/sbin/siftalpha-web-admin preflight <digest>`。它检查现有
   网站健康、数据卷、空间、ARM64、三方来源证明，并用 `sqlite3.Connection.backup()`
   创建一致性备份，再将备份恢复到独立临时数据库并运行 `PRAGMA integrity_check`。
   输出只可包含备份路径、大小、SHA-256 与完整性结果。
4. 预检通过后才可运行 `sudo /usr/local/sbin/siftalpha-web-admin deploy <digest>`。
   工具保存 root-only 配置、镜像与容器快照，只更新固定网站服务，并检查 `/`、
   `/account`、`/account/`、静态资源和 `/healthz/`。
5. 健康检查通过后，由用户在浏览器验收登录、行情、K 线、指标和个人中心。

任何步骤失败都应停止并报告真实错误；不得以重新构建、变更 DNS、变更 Tunnel 或修改
生产数据库掩盖问题。

## 首次 Compose adoption 与回滚

当前网站来自保留的 `docker run` 容器。first-adoption 仅在未来一次、单独批准的
部署窗口中发生：工具先记录 legacy 容器、原本地镜像、根权限配置和数据绑定；然后才
停止 legacy 容器并以不同的 Compose 容器名启动候选。different container names 是
硬性要求，旧容器及原本地镜像不会被删除。

如果首次候选启动或健康检查失败，工具只移除候选 Compose 容器并启动原 legacy 容器。
后续已采用 Compose 的版本由 root-only 快照恢复为上一个已验证 Digest。数据库迁移
不属于该流程，工具 does not restore the database automatically；数据库恢复需要单独的
人工授权和恢复任务。

rollback only with separate approval。回滚前再次记录当前状态，并且只恢复固定网站
服务；不修改 Cloudflare、Tunnel、Access、其他容器或业务数据。

## 验收与记录

每次仅记录非敏感事实：完整 Commit、GitHub Actions Run ID/URL、不可变 Digest、
镜像地址、预检摘要、备份 SHA-256、健康检查、旧容器/快照标识和用户浏览器验收结果。
不得记录 Token、环境变量、数据库内容、私有 Formula 源码、会话或密码。

本轮只建立此能力。除非用户另行授权，禁止调用 `deploy`、`rollback` 或进行首次
Compose 切换。
