# SiftAlpha 网站 GitHub ARM64 构建与受控部署设计

## 状态与决策

本设计与实施计划已由用户确认。用户现批准按四个任务顺序实施发布分支代码、
GitHub ARM64 构建和网站专用最小权限工具；仍未批准替换/重启当前正式网站容器、
真实 `deploy`、`rollback`、首次 Compose 切换、数据库变更或 Cloudflare 修改。

- 发布分支：`release/siftalpha-web-v1`
- 精确基线：`ebd23f4248219fb70fe457ac800d5603fbf47ef1`
- 线上网站：`siftalpha.com`
- 运行平台：Oracle Cloud ARM64（aarch64）
- 正式版本展示：`SiftAlpha.com • V1.0.0`

发布分支暂时独立。它不合并现有 PR，也不修改 `main`；这是用户对
`AGENTS.md`“从最新 main 创建分支”规则作出的明确、有限例外：该分支必须以当前
用户验收且在线运行的 `ebd23f4…` 为唯一业务源码基线。GitHub Actions 产出镜像
不等于批准部署。每次生产部署仍须由用户单独、明确批准。

## 已核实的现状

只读审计在 2026-10-17 得到以下事实：

- GitHub `main` 是 `086d87c0c270def1ef8ac19ca6e5f0c3bc111eec`，而线上已验收
  源码是 `ebd23f4248219fb70fe457ac800d5603fbf47ef1`，后者位于尚未合并的
  发布链上。`main` 是该提交的祖先，但不是当前线上完整功能的同一版本。
- 线上容器为 `siftalpha-task011-ebd23f4`，只监听 `127.0.0.1:19091`，挂载
  既有 SiftAlpha 数据目录；容器镜像本地标记为 `siftalpha-task011:ebd23f4`。
  本设计不改变 Cloudflare Tunnel、Access、域名、端口或数据卷。
- 当前网站仓库没有 GitHub Actions workflow，线上镜像也不是由 GHCR 构建而来。
  已部署的源码提交本身没有 Dockerfile；线上构建曾依赖 Task 009 工作区中的
  Dockerfile。这阻止从精确源码提交可重复构建镜像，必须在发布分支补齐受版本
  控制的构建定义。
- 进一步核对显示，`ebd23f4…` 也不包含当前线上容器使用的生产 settings、
  `/healthz/` 与 healthcheck 文件。当前 V1 镜像实质上是“Task 009 已验收运行层
  加上 `ebd23f4…` 业务树”的混合构建，不能视为可重复的 Git 基线。发布分支必须
  只迁入这一小组非业务部署文件，并以逐文件审查和回归测试证明没有引入业务逻辑
  变化。
- Oracle 主机运行 Docker 29.8.1，具有现成 GHCR Crypto 镜像和受控管理工具。
  `rdc-agent` 不在 Docker 组、不能直接访问 `/var/run/docker.sock`，目前只可
  通过 sudo 调用根权限的 `/usr/local/sbin/siftalpha-crypto-admin`。
- Crypto 工具已经证明“root 拥有的参数校验脚本 + 单一 sudoers 入口 + Digest
  固定镜像”的权限模式可用，但其接口不足以直接管理网站；网站必须拥有独立
  容器名、配置、数据和回滚目录。

## 目标与非目标

### 目标

1. GitHub Actions 在 Linux ARM64 上可重复构建当前网站功能一致的镜像，并推送
   到 GHCR，输出源码提交、完整镜像引用和不可变 `sha256` Digest。
2. 服务器提供独立的 `/usr/local/sbin/siftalpha-web-admin`，供 `rdc-agent`
   通过受控 sudo 调用 `status`、`preflight`、`deploy`、`rollback`、`health`。
3. 每次真正部署都备份并校验 SQLite 数据库，保存旧的根权限配置快照和旧镜像
   标识，并在新版本健康检查失败时自动恢复旧版本。
4. 部署能力只管理 SiftAlpha 网站容器，不扩大到 Crypto、Options Monitor、
   Coolify、VPN、Agent、Cloudflare 或任意 Docker 命令。

### 非目标

- 不在本任务自动合并、自动发布或自动替换 `siftalpha.com` 容器。
- 不改变网站业务逻辑、交易逻辑、行情 Provider、指标/缠论算法、私有公式或 UI。
- 不执行数据库迁移、`flush`、重建数据库、数据导入或数据清理。
- 不创建第二个管理平台，不赋予 `rdc-agent` Docker Socket 或 Docker 组权限。
- 不修改 Cloudflare Tunnel、Access、DNS、反向代理或其他现有服务。

## 版本与镜像构建架构

### 发布分支与来源

`release/siftalpha-web-v1` 以 `ebd23f4…` 创建，确保构建输入与当前用户验收过的
网站代码一致。后续网站变更先经过正常 PR 审查；只有进入此发布分支的精确提交
才是可构建、可部署候选。整理 PR 链并合入 `main` 是单独的仓库治理任务。

### Docker 构建输入

发布分支新增受版本控制的 `deployment/web/Dockerfile`、`.dockerignore` 和构建
契约测试。为复现线上混合运行层，实施前先从已验收的 Task 009 提交迁入且仅迁入
以下非业务运行文件/语义：环境化 Django production settings、`/healthz/`、
`frontend_index`、`/`、`/account` 与 `/account/` 的 SPA 入口、
`docker/healthcheck.py`、WhiteNoise 静态服务与 Gunicorn 入口；迁入后逐一审查，
不得同时携带行情、账户、公式、指标或前端业务差异。Dockerfile 以经过 Task 009
证明可在 ARM64 运行的多阶段模式为基础：

- Node 22 阶段执行现有前端 `npm ci` 和生产构建；生产静态资源继续使用 Django
  的 `/static/` 前缀。
- Python 3.11 slim Trixie 运行阶段保留既有 `requirements.txt` 的安装方式、
  Node.js 运行时、`collectstatic`、Gunicorn 单 worker 和已有 healthcheck。选择
  Trixie 是为了在 ARM64 构建中继续保留 `longbridge==5.2.0`，不降低 SDK 版本。
- 继续使用项目现有依赖版本，特别是不改写或“升级修复” `longbridge==5.2.0` 的
  安装语义；镜像构建阶段必须执行 `from longbridge.openapi import Config` 导入检查，
  以便在产生镜像前验证安装结果。
- 构建元数据写入 OCI labels：`org.opencontainers.image.source`、
  `org.opencontainers.image.revision`、`org.opencontainers.image.version` 和
  `org.opencontainers.image.created`。

此 Dockerfile 仅封装已验收的运行方式，不包含数据库迁移、种子数据或任何私有
配置。生产 `DJANGO_SECRET_KEY`、数据库路径和 Provider 凭据始终由服务器的
根权限环境文件注入，绝不进入镜像、GitHub Actions 日志或仓库。

### GitHub Actions

新增 `SiftAlpha Web CI and ARM64` workflow。第一阶段只采用发布分支 push 自动
构建：由于 workflow 尚未进入默认分支，不把 `workflow_dispatch` 作为可靠的人工
构建入口。它遵循现有 Crypto workflow 的安全分层：

| 触发 | 校验 | GHCR 推送 | 部署 |
| --- | --- | --- | --- |
| 同仓库 PR（后续启用） | Django、前端与 Docker 构建验证 | 否 | 否 |
| 推送到 `release/siftalpha-web-v1` | Django、前端、ARM64 镜像与 provenance 校验 | 是 | 否 |
| `workflow_dispatch` | 第一阶段不依赖；进入默认分支后另行评估 | 否 | 否 |

fork PR 不取得包写入权限。第一阶段工作流仅在可信发布分支使用 `contents: read` 与
`packages: write`；没有 deploy 权限、
服务器凭据、Cloudflare 凭据或任何数据库凭据。Buildx 使用 `linux/arm64`；镜像推送至
`ghcr.io/kuashan/siftalpha-web`，并至少创建两个可追溯标签：

```text
ghcr.io/kuashan/siftalpha-web:sha-<full-commit>
ghcr.io/kuashan/siftalpha-web:v1.0.0-sha-<full-commit>
```

部署输入永远使用工作流输出的不可变引用：

```text
ghcr.io/kuashan/siftalpha-web@sha256:<64 lowercase hexadecimal characters>
```

工作流必须把完整 Git Commit、GitHub Actions Run ID、Run URL、workflow 名、发布
分支、平台、标签和 Digest 同时写入 job summary、构建 manifest artifact 和 OCI labels；
并以 `provenance: mode=max` 发布 BuildKit OCI SLSA provenance。`preflight` 只接受固定
GHCR 仓库的 Digest，并核对 ARM64 manifest 与 OCI source/revision/run-id/ref labels。

正式候选还必须通过多来源交叉核验，不能只相信 OCI 标签：根权限工具从 GitHub API
读取对应 Actions Run（同一仓库、固定 workflow、`success` 结论、相同 head SHA 和
发布分支），下载该 Run 生成的不可变 build manifest 并核对 Digest/Commit/Run ID/标签，
再从 GHCR 读取同一 Digest 的 OCI image index，确认 `linux/arm64` manifest 关联了
BuildKit provenance attestation，并解析其 SLSA provenance。用于此只读核验的 GitHub
凭据只可放在 root-only token file；GitHub CLI、token、Run record、manifest、OCI
provenance 或任一关联关系不可用、不一致时，`preflight` 与 `deploy` 必须 fail closed。
BuildKit provenance 是构建过程记录，不是 GitHub 官方的加密签名证明；它不能被描述
为签名或不可伪造的供应链证明。标签仅用于候选定位，绝不能单独构成部署来源证明。

## 服务器受控部署边界

### 根权限配置边界

后续实施将在服务器创建以下 root-owned 文件；它们不提交凭据，也不由 ChatGPT
Work 写入：

```text
/usr/local/sbin/siftalpha-web-admin                 root:root 0750
/etc/siftalpha-web-admin.conf                       root:root 0600
/etc/siftalpha-web-admin.env                        root:root 0600
/etc/siftalpha-web-admin.github-token               root:root 0600
/usr/local/libexec/siftalpha-web-admin/gh            root:root 0750
/srv/siftalpha/web-deployment/compose.yaml          root:root 0600
/var/lib/siftalpha-web-admin/rollbacks/              root:root 0700
/var/lib/siftalpha-web-admin/backups/                root:root 0700
/var/lib/siftalpha-web-admin/recovery-checks/        root:root 0700
/etc/sudoers.d/rdc-agent-siftalpha-web               root:root 0440
```

配置文件将固定且只包含以下类别：目标服务名、固定容器名、允许镜像仓库
`ghcr.io/kuashan/siftalpha-web`、当前 loopback 端口、现有数据卷路径、health
probe 路径、回滚目录和根权限环境文件路径。环境文件可含敏感值，但永远不显示、
复制到 Git、写进命令输出或保存在普通用户目录。

网站当前是手动 `docker run` 容器。首次真实部署前，root 必须执行一次受控
adoption：从已验证的固定字段创建 Compose 清单，并在受控环境中逐项核对端口、
数据卷、运行参数、镜像 ID 与根权限环境文件；不得把未过滤的 `docker inspect`
输出作为可执行 shell 命令。adoption 还要保存原容器名、原本地镜像引用/ID、原
配置校验值及原数据卷绑定的 root-only 快照。

首次真正 `deploy` 时，工具必须先拉取并校验候选镜像、创建数据库备份和配置快照，
再停止但不删除原 `docker run` 容器，并以不同于原容器名的固定 Compose 容器名启动
Compose 服务。若新服务未通过健康
检查，工具必须停止/移除候选 Compose 容器后直接启动保留的原容器；这使原本地
镜像、原配置和原数据卷可完整恢复。首次切换成功后，原容器和原本地镜像继续保留，
直到用户在后续单独授权的维护任务中批准清理。配置会拒绝 Legacy 与 Compose 容器
名相同的安装，避免首次 adoption 因命名冲突覆盖原容器。

### `siftalpha-web-admin` 命令契约

脚本使用固定 `PATH`、`set -Eeuo pipefail`、`umask 077`，不接受路径、镜像名称、
容器名、Compose 文件、环境变量或任意 shell/Docker 子命令。允许的唯一输入为：

```text
status
health
preflight sha256:<64 lowercase hexadecimal characters>
deploy sha256:<64 lowercase hexadecimal characters>
rollback
```

- `status`：报告固定网站容器的状态、实际固定镜像引用、OCI revision/version、
  端口与健康状态；不输出环境变量或数据内容。
- `health`：对固定 loopback 网站执行首页、`/account`、`/account/`、静态资源、
  `/healthz/`、登录页以及配置好的
  无副作用 API probes，接受明确的预期认证状态，拒绝 5xx 和不符合契约的响应。
- `preflight`：验证 Digest 格式、固定 GHCR 仓库、远端/本地 ARM64 manifest、
  OCI source/revision/run-id/ref labels，以及 GitHub Actions Run、manifest artifact 与
  BuildKit OCI provenance 的多来源交叉证明；可用磁盘、现有容器健康、数据卷可读、备份目录
  与 SQLite `integrity_check`。它还必须用 `sqlite3.Connection.backup()` 创建
  root-only 临时副本、从该副本实际恢复到独立临时数据库、再次运行完整性检查，
  然后安全删除临时检查文件；不输出数据库内容。它可以拉取候选镜像到本地缓存，
  但绝不停止或重建容器。
- `deploy`：仅在显式用户授权后使用。它再次执行 preflight，创建原子 SQLite
  backup（Python `sqlite3.Connection.backup()`）、SHA-256 和
  `PRAGMA integrity_check`，快照 root 配置及当前镜像引用，随后只重建固定网站
  服务。健康检查失败、Compose 错误或启动失败时，自动恢复快照中的旧固定镜像及
  Compose 配置并重新检查健康。
- `rollback`：只恢复最近一次已验证部署快照的固定网站 Compose 镜像；不回滚
  数据库，因为正常网站部署禁止迁移。它也先检查当前容器和快照完整性。

脚本使用直接参数数组调用 Docker/Compose，不使用 `eval`、拼接 shell 字符串或
来自调用方的环境。所有状态、快照和备份记录仅保存元数据、Digest、时间与校验值；
不会保存数据库内容到日志。

### `rdc-agent` 最小权限

`rdc-agent` 保持不在 Docker 组，不能读取 Docker Socket。sudoers 仅授予：

```sudoers
rdc-agent ALL=(root) NOPASSWD: /usr/local/sbin/siftalpha-web-admin
```

sudo 的 `env_reset` 和 `secure_path` 继续生效。即使 sudoers 允许调用该单个文件，
root-owned 脚本也会拒绝所有未列出的动词、错误参数、非 SHA-256 格式和非网站
GHCR 仓库，从而不能被用作任意 Docker 或 shell 入口。Crypto 的 sudoers 条目和
工具完全不改动。

## 数据保护、部署与回滚流程

### 部署前

1. ChatGPT Work 显示 GitHub Actions 的 Run ID、完整 Commit、GHCR 镜像引用和
   Digest，并由工具交叉核验 Actions Run、build manifest 与 provenance；任一来源
   缺失或不一致即拒绝候选。随后才向用户请求该 Digest 的一次性部署确认。
2. Work 以 `rdc-agent` 身份调用 `siftalpha-web-admin preflight <digest>`。
   任一健康、架构、卷、磁盘或 SQLite 校验失败都阻止部署。
3. `deploy` 创建仓库外的 SQLite 一致性备份，输出仅包括备份路径、大小、
   SHA-256 和 `integrity_check: ok`，并保存 root-only Compose/镜像快照。

### 部署中与部署后

1. 工具仅修改固定网站 Compose 的 `image:` 行为目标 Digest，不运行
   `migrate`、`collectstatic`、种子命令或数据转换。
2. 工具只重建固定网站服务，保留既有数据卷、根权限环境文件、端口
   `127.0.0.1:19091` 和 Cloudflare 现有入口。
3. 工具检查网站首页、`/account`、`/account/`、构建生成的静态资源、`/healthz/`、
   登录页和受控的业务 API 合约；不以假数据或
   仅“容器启动”宣布成功。
4. 失败时自动恢复旧 Compose 快照和旧 Digest；成功时保留旧镜像及快照，供显式
   `rollback` 使用。

Cloudflare Tunnel、Access、DNS、反向代理和任何其他容器均不在此流程中。外部
浏览器验收在工具 `health` 之后由用户完成，且不会被自动替代。

## 验收标准

实施阶段必须产生可复核证据：

1. GitHub Actions 在 ARM64 成功执行 Django、前端与镜像构建，并报告真实 Run ID、
   Commit、镜像地址和不可变 Digest。
2. 构建镜像的 OCI revision 与触发提交一致，且 GitHub Actions Run、build manifest、
   GHCR Digest、ARM64 manifest 与 BuildKit OCI provenance 均绑定相同 Commit/Run ID/分支，才可在 Oracle
   ARM64 通过 `preflight` 验证；未使用 `latest` 部署。
3. `rdc-agent` 可以运行网站 `status`；直接 `docker ps` 继续因 Docker Socket
   权限不足而失败。
4. `preflight` 能接受合法网站 Digest，拒绝格式错误、非网站仓库、非 ARM64 或
   不能验证的镜像，且不重启网站。
5. 数据备份例程以隔离测试副本或 dry-run 合约验证 SHA-256、完整性和失败清理；
   在本次能力建立中不替换线上容器、不做测试部署。
6. `rollback` 的快照发现与命令路径通过静态/隔离测试验证；真正线上回滚仅在未来
   已部署候选出现问题且用户明确批准时执行。
7. Crypto、Options Monitor、Coolify、Cloudflare、VPN、Agent 及其他容器名称、
   镜像、网络和运行状态保持不变。

## 实施顺序与证据门槛

实施严格按以下顺序进行：先将运行层、Actions 工作流、受控工具和操作手册全部在
发布分支提交；随后一次性 push 该精确提交并等待 GitHub Actions ARM64 构建。只有
同一成功 Run 的完整 Commit、Run ID、build manifest、BuildKit OCI provenance 与
不可变 Digest 相互一致，才可进入服务器工具安装和隔离验收。OCI 标签仅作候选定位，
不能替代交叉核验；BuildKit provenance 也不是 GitHub 官方加密签名证明。

服务器侧安装仅写入 root-owned 工具、配置模板、sudoers 和状态目录，不调用
`deploy`、`rollback` 或 Compose 切换。首次实际切换仍需要单独用户授权，并必须使用
不同于 legacy `docker run` 容器的 Compose 容器名；原容器和本地镜像在验证窗口内保留。
任何缺失的 GitHub 核验 token、固定校验和 CLI、映像来源证明或健康前置条件都会阻止
预检与部署，而不是降低校验强度。

## 已知风险与后续决策

- 当前线上源代码未完全进入 `main`。在发布分支稳定后，必须由单独的审查/合并
  工作整理现有 PR 链；在此之前，`release/siftalpha-web-v1` 是唯一部署候选事实源。
- GHCR 包的可见性、服务器拉取凭据及只读 GitHub API token 须在
  实施时以最小权限验证。不能将 PAT、`GITHUB_TOKEN`、Docker config 或任何凭据提交
  进仓库；若 root-only token 或固定校验和 GitHub CLI 不可用，工具必须拒绝部署。
- 当前手动容器需要一次受控 adoption 才能切换为 root-owned Compose 管理；该动作
  必须在未来用户明确批准的首次部署窗口中执行，并带有完整备份和自动回滚。
- 由于本设计阶段明确禁止替换网站容器，真实部署与真实回滚只能标记为 `PENDING`，
  不得虚报为已验证。

## 用户未来使用方式

构建成功但未部署时，ChatGPT Work 应报告候选，例如：

```text
Commit: <40-character SHA>
Image: ghcr.io/kuashan/siftalpha-web@sha256:<digest>
Run: <GitHub Actions URL>
```

用户随后单独明确授权：

```text
部署 SiftAlpha 网站，镜像 Digest：sha256:<digest>
```

Work 再调用 `preflight`，展示结果后执行受控 `deploy`；部署失败时工具自动尝试
恢复旧版本，并将成功或失败的实际证据报告给用户。
