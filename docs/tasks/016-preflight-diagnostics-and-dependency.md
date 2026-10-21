# V1.1.6 — 受控迁移预检诊断与间接依赖安全补丁

## 事故与边界

- V1.1.5 候选 Commit `7104a3c2999388db46cd9f0300d8f50d1d316376` 已本地构建推送，但**未部署**。Oracle 网站保留已验收基线 V1.1.4。
- 目标候选 Digest `sha256:67490d98b8fc6562c724f855c24b0581ee4eea8c3e195bd3297b4dba3df9b004` 的受控预检报 `candidate migration plan inspection failed`。
- 管理工具在启动临时只读候选镜像探针时捕获了 stderr，但原先只打印通用提示，故缺少可确认的具体故障类别。
- **没有证据证明 0015 迁移本身失败**。不能关闭白名单、跳过备份/迁移验证或执行 deploy。

## 最小修改

1. `siftalpha-web-admin-lib.sh` 只从探针失败的 stderr 匹配**固定异常类别**，如 Python 模块缺失、SQLite 操作错误、Django 设置错误、Docker 容器错误。不能泄露 traceback、敏感路径、数据库数据或密钥；成功路径和迁移白名单完全不变。
2. `frontend/package-lock.json` 将 `source-map-js` 仅从 1.2.1 更新到 1.2.2，补充准确的 npm Registry 包 SHA-512 integrity。修复公开高危 DoS 漏洞 `GHSA-68fv-2mgg-jv7q`，不改变 Vue/Vite/业务代码。
3. 页脚版本升级为 `V1.1.6`；补充预检错误分类的安全回归。

## 下一次受控操作

- ChatGPT 负责全部可执行的发布前自动测试并提交测试结论与 PR；Codex **不重复 Linux Bash/Django 回归**，只在本地完成镜像构建必需的依赖安装、ARM64 构建、推送 GHCR，并从新正式 HEAD 取得**新 Digest**。
- 必要时通过已批准的 `upgrade <正式 HEAD>` 更新 root-owned 管理工具；服务器只运行受控 `status`、`health`、`preflight <新 Digest>`。
- 若探针仍失败，Codex 提供**固定错误类别**，不重复复杂排查、不直接 Docker 调试生产或修改数据库。由 ChatGPT 基于类别继续定位最小根因。
- 只有 `preflight: ok`、备份/恢复副本及 0015 迁移演练全部通过，并获得用户明确授权，方可 `deploy`。之后用户实际网页验收。
