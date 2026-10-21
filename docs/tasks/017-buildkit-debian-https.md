# V1.1.7 — Debian APT HTTPS 构建修复（仅构建环境）

## 原因和版本

- V1.1.6 已合并到正式分支（`52631346ad613b75495c676cd7439f76a4a9ed36`），尚无可发布的 V1.1.6 ARM64 Registry Digest，尚未部署。
- 本地 Docker BuildKit 在 `python:3.11-slim-trixie` 阶段访问 `deb.debian.org:80` 下载 `trixie/main arm64 Packages` 时连接失败；此前构建已停止。
- 因正式分支已包含 V1.1.6，本次新源码作为 **V1.1.7** 候选，不覆盖 V1.1.6 的既有提交。生产基线依旧为已验收的 V1.1.4。

## 最小修改

- 仅在 `deployment/web/Dockerfile` 两个基础镜像分别增加 `frontend-apt-https-check` 和 `runtime-apt-https-check` 构建检查阶段；它们检查 `ca-certificates` 已安装及 `/etc/ssl/certs/ca-certificates.crt` 非空。
- 各阶段先修改基础镜像中已有的 `/etc/apt/sources.list.d/debian.sources`，兼容旧镜像的 `/etc/apt/sources.list`，将 Debian 官方 APT 源从 HTTP 改为 HTTPS，再进行 `apt-get update -o APT::Update::Error-Mode=any`；找不到源文件、证书缺失或 HTTPS 连接失败则直接停止。
- 不关闭证书验证，不使用不安全的 APT 选项，不换基础镜像、Python、Node 或业务依赖。保留原有 APT 软件包安装内容、npm、pip、collectstatic、容器配置。
- 网站页脚和对应静态测试版本从 V1.1.6 升至 V1.1.7。

## 发布和安全门槛

1. ChatGPT 检查 Dockerfile 两个阶段的 CA 验证、APT 源覆盖、fail-closed 行为，运行可用的本地静态和版本测试；尚无可用 Docker Engine 时不得宣称已经联网构建成功。
2. Codex fetch 本 PR 并依正常规则合并后，在**本地 Docker Buildx** 针对两个检查阶段各做一次**不推送**的 HTTPS 网络检查（必须实际执行，不只看缓存）：
   ```bash
   docker buildx build --platform linux/arm64 --target frontend-apt-https-check -f deployment/web/Dockerfile --no-cache --progress=plain --output=type=cacheonly .
   docker buildx build --platform linux/arm64 --target runtime-apt-https-check -f deployment/web/Dockerfile --no-cache --progress=plain --output=type=cacheonly .
   ```
3. 两项通过后才继续本地 ARM64 完整构建并推送 GHCR，检查新 Registry Digest 与正式 HEAD / OCI Version V1.1.7。没有通过就停止，报告证书还是网络失败；若 HTTPS 443 不通，下一步只检查 Docker Desktop / BuildKit 代理配置，不反复等待、不改生产服务器。
4. 受控服务器操作仍仅 `status`、`health`、必要 `upgrade <正式 Commit>` 与 `preflight <新 Digest>`。备份、恢复副本、0015 迁移隔离演练和白名单保护不可跳过。预检通过后等待用户对特定 Digest 明确授权才可正式 `deploy`。

## 当前状态

- 仅提交候选代码和测试记录；**尚未完成本地 Docker / BuildKit 对外 HTTPS 连通性验证**。
- 未合并、未构建或推送 V1.1.7 镜像，没有新 Registry Digest；未修改生产服务器、数据库或其他容器。
