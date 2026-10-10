# Task 009 — SiftAlpha Oracle ARM64 Web 部署准备及隔离测试环境

Status: `IN_PROGRESS`

## 目标

在不影响现有 Oracle 服务的前提下，为 SiftAlpha 建立可回退的 ARM64
staging 部署准备，并验证生产配置、统一公开行情、K 线、实时 SSE、
通达信指标和受控 Python 缠论链路。

本任务不部署正式生产环境、不迁移正式数据库、不修改交易策略，也不修改
原始 Chan.py 算法。

## 本轮同步基线

- 本地 `main` 已安全 fast-forward 到
  `086d87c0c270def1ef8ac19ca6e5f0c3bc111eec`。
- 开发分支：`codex/009-oracle-arm64-deployment-prep`。
- PR：`#33`。
- 远端提交、SSH 私钥、数据库、Formula source 和运行日志不进入本仓库。

## Oracle 只读审计

新的公网 SSH 基线已验证成功。现有密钥仅用于 SSH 身份认证，没有读取或提交
私钥内容。只读审计结果：

- 架构：`aarch64`。
- Docker：`29.8.1`；Compose v5.5.1。
- 资源：2 vCPU，约 11 GiB 内存（约 9.4 GiB 可用），约 48 GiB 磁盘（约
  34 GiB 可用），当前无 swap。
- Coolify、Traefik、PostgreSQL、Redis、Realtime、既有 staging 应用和
  SiftAlpha Agent 均在运行。
- WireGuard、Xray、Cloudflare Tunnel 和既有 Python web staging 服务均在
  运行；本任务没有停止、删除、更新或重路由任何现有服务。
- 现有公网 Tunnel 只指向既有 web-staging 服务；没有为本任务新建域名或
  公网 HTTPS 路由。`siftalpha.com` 当前不能从该主机 DNS 解析为已批准的
  staging 入口。

审计结论：CPU、内存、磁盘、Docker 和 Coolify 具备创建隔离测试容器的
条件；但新的公网安全入口尚未获批，手机浏览器 HTTPS 验收保持 `PENDING`。

## 已实现的部署适配

- 前端 API 和实时 SSE 地址通过 `VITE_API_BASE_URL` 环境变量配置；生产构建
  默认使用同源 `/api/`，本地 Vite 开发才使用 loopback 后端。
- Vite 生产静态资源使用 `/static/` 前缀。
- Django 的 `DEBUG`、`ALLOWED_HOSTS`、数据库路径、静态目录、CSRF/CORS
  来源、Cookie Secure、反向代理 HTTPS 和 HSTS 参数均由环境变量控制。
- API CORS 只响应已配置的 `Origin`，不再写死本机开发端口。
- 提供最小 `/healthz/`，只返回 `{"status":"ok"}`。
- 增加 WhiteNoise 静态文件支持和 Gunicorn 生产入口。
- 增加多阶段 Dockerfile。运行时固定为单 Gunicorn worker，以保持当前进程内
  realtime registry 的边界；前端、Django 和 Python 指标依赖在同一镜像中。
- staging 数据库必须挂载到独立 `/data` 目录，禁止挂载正式数据库；回滚只
  操作带唯一名称的 staging 容器和 staging 数据目录。
- 增加不含真实凭据的 `.env.example` 和 Oracle ARM64 staging runbook。

## ARM64 隔离 staging 验收

以下证据已在 Oracle aarch64 真机、独立镜像和全新 staging SQLite 卷上完成：

- 镜像 `siftalpha-task009:c8df985` 构建成功，包含 ARM64 Python 依赖、Vue
  构建和 Django `collectstatic`。
- 容器仅绑定服务器 loopback 临时端口，`/healthz/` 和首页均返回 HTTP 200，
  未登录会话返回 HTTP 401，容器状态为 `running/healthy`。
- 使用临时 staging 账户和真实公开行情，`SZ.002315` 日线返回 3636 根 K
  线；缠论返回 221 条线、20 个标记和 7 个绘图项；实时 SSE 握手返回 HTTP
  200。
- 容器内 `python manage.py check_python_indicators` 返回 `CHANLUN: ok`，
  `migrate --check` 没有待执行迁移。

## 未完成的公开 staging 验收

以下项目没有在本任务中虚报通过：

- 手机浏览器通过 HTTPS 的验收：`PENDING`，当前没有新的安全公网路由。
- 新 staging 的公开域名、HTTPS 反向代理、完整浏览器交互验收：`PENDING`。

现有主机上的旧 web-staging 不是本任务的验收对象；不得用它代替新的
SiftAlpha staging 证据。

## 数据与回滚边界

- 未执行本地正式数据库迁移、导入、清理或修改；未读取、导出或提交 Formula
  source、Session、密钥或用户数据。
- 本任务的 staging 迁移（如执行）只能针对新建的远程 staging SQLite 卷，
  不得使用正式本地数据库或既有生产卷。
- 正式数据库、备份、日志、私有指标源码和凭据不得进入 Git。
- 不得改动现有 Coolify 项目、反向代理、Cloudflare Tunnel、WireGuard、
  Xray、交易服务或生产 Agent。
