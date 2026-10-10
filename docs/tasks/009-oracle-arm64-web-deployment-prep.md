# Task 009 — SiftAlpha Oracle ARM64 Web 部署准备及隔离测试环境

Status: `BLOCKED`

## 目标

在不影响现有 Oracle 服务的前提下，为 SiftAlpha 建立可回退的 ARM64 staging 部署准备，并验证生产配置、统一公开行情、K 线、实时 SSE、通达信指标和受控 Python 缠论链路。

## 本轮审计结果

- 本地 `main` 已安全 fast-forward 到 `086d87c0c270def1ef8ac19ca6e5f0c3bc111eec`。
- 本地开发数据库仍存在且未被 Git 跟踪；本轮未执行迁移、导入、清理或数据库写入。
- 本机只读 SSH 材料中发现的主机记录为 `192.168.18.72:8022`；使用现有 SSH 密钥进行只读 `uname` 探测时连接超时，未能建立远端会话。
- 因 SSH 不可达，未检查 ARM64、Docker、Coolify、反向代理、现有容器、端口、资源和域名，也未停止、删除或覆盖任何远端服务。

## 本地生产适配阻碍

在未修改代码的只读检查中确认：

- 前端多个组件仍直接使用 `http://127.0.0.1:8003`，包括 K 线、指标、实时 SSE、账户和 AI 请求。
- Django 当前开发配置仍为 `DEBUG=True`、空 `ALLOWED_HOSTS`，并使用本地开发 CSRF/CORS 来源。
- 仓库未提供 Docker/Coolify/反向代理部署文件，不能在未知服务器拓扑上安全推断部署方式。

## 暂停条件

待用户恢复到 Oracle 服务器的可达 SSH/VPN 路径，并提供 SSH 主机别名或可达主机地址及登录用户名后，继续进行只读服务器审计。服务器可达前不创建 staging 容器、不修改反向代理、不部署公网服务、不迁移正式数据库。

## 数据与回滚边界

- 不读取、导出或提交 Formula source、Session、密钥或用户数据。
- 不使用正式业务数据库作为 staging 数据库。
- 后续任何本地数据库迁移或写入前，先执行 `python manage.py backup_local_db` 并确认 `integrity_check: ok`。
- staging 必须使用独立目录/容器、独立数据库和可删除的部署配置；正式服务变更前需保留现状和回滚点。
