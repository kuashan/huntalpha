# Task 002 — 本地数据保护与自动备份

Status: ACCEPTED

## 背景

HuntAlpha 当前本地开发仍使用 SQLite `db.sqlite3`。该数据库包含本地账户、密码哈希、Session、管理员操作数据以及后台保存的私有指标源码，因此必须继续排除在 Git/GitHub 之外。

2026-09-05 曾因切换到新的正式工作目录而使用了一份新的空数据库，导致后台看起来像是“指标全部消失”。最终确认旧数据库数据仍在，并已通过独立恢复备份、SHA-256 校验和事务性定向迁移安全恢复。

本任务只解决一个小问题：让本地 SQLite 数据库拥有稳定、可验证、位于 Git 仓库之外的自动备份与恢复点机制，降低再次出现“换目录/误操作后无法恢复”的风险。

## 目标

1. 提供一个安全、可重复执行的本地 SQLite 备份命令，生成一致性备份并做完整性与 SHA-256 校验。
2. 备份必须位于 Git 仓库之外，并保留多个历史版本。
3. 为 Windows 本地开发提供可配置的自动定时备份入口；任何可能修改本地数据库的维护操作前，Codex 必须先创建恢复点。

## 范围

### 必须做

- 新增 Django management command，例如：`python manage.py backup_local_db`。
- 仅针对当前本地 SQLite 开发数据库工作；如果数据库引擎不是 SQLite，命令必须明确拒绝执行，而不是猜测。
- 使用 SQLite 的一致性备份能力（例如 Python `sqlite3.Connection.backup()` 或等价安全机制），不得在数据库正在使用时仅做未经校验的裸文件复制。
- 默认备份目录必须在仓库目录之外；允许通过本地环境变量 `HUNTALPHA_LOCAL_BACKUP_DIR` 覆盖。
- 命令必须检查目标路径，若目标位于 Git 仓库/项目目录内部则拒绝执行。
- 每个备份使用不可覆盖的时间戳文件名，并先写临时文件、校验成功后再原子完成，避免留下“看似成功但实际不完整”的备份。
- 对备份文件执行 SQLite 完整性检查（至少 `PRAGMA integrity_check`）并计算 SHA-256。
- 记录非敏感备份元数据：时间、文件名、大小、SHA-256、完整性结果；不得读取/输出表数据或私有公式正文。
- 提供历史保留策略。默认仅清理本命令自己创建且明确匹配命名规则的旧自动备份；不得删除未知文件、手工恢复目录或现有 `huntalpha-db-recovery` 内容。保留数量应可配置，默认建议 30 份。
- 提供 Windows 定时备份脚本/安装入口（例如 PowerShell + Task Scheduler），时间参数必须可配置；实现过程中不得无提示修改系统全局设置。
- 定时任务只调用上述同一个备份命令，不复制第二套备份逻辑。
- 更新 `AGENTS.md`：任何 Codex 任务若要执行 `migrate`、数据导入、批量数据修改、恢复/清理等可能影响本地数据库的操作，必须先运行本任务提供的备份命令并确认成功；不得把备份加入 Git。
- 增加简短操作文档，说明：手动备份、查看校验结果、设置/移除 Windows 定时任务、从备份恢复时应先停服务并保留当前库副本。
- 增加自动测试，使用临时 SQLite 测试库/临时目录，不读取或复制用户真实 `db.sqlite3` 内容。

### 不做

- 不把 `db.sqlite3`、数据库备份、用户数据、密码哈希、Session 或私有公式源码提交到 GitHub。
- 不把私有公式正文导出成 JSON/CSV/文本作为备份方案。
- 不整体迁移到 PostgreSQL；生产数据库方案另开任务。
- 不实现云端数据库备份、对象存储或第三方备份服务。
- 不在本任务中实现复杂加密/密钥管理系统；备份目录本身必须明确标记为敏感本地数据，不应放入公共同步目录。
- 不自动执行数据库恢复；恢复仍需人工确认和单独验证，避免误覆盖当前数据库。
- 不修改公式引擎、认证流程、行情逻辑或 PR #2 的业务功能。

## 相关文件/模块

- `AGENTS.md`
- `manage.py`
- Django management commands（新增）
- SQLite / Django database settings 读取逻辑
- `scripts/`（如新增 Windows 定时任务脚本）
- `docs/operations/`（如新增本地数据库备份说明）
- 相关自动测试

## 技术与安全约束

- 遵守根目录 `AGENTS.md`。
- 不提交任何秘密信息、本地数据库、日志或用户数据。
- 不进行任务范围之外的重构。
- 真实数据库只允许作为备份命令的运行时输入；测试必须使用临时数据库。
- 命令输出只能包含非敏感元数据，不得显示任意数据库行内容、密码哈希、Session、用户资料或 Formula `source`。
- 任何失败必须返回非零退出状态；失败的临时备份不得被当作有效备份保留。
- 不覆盖已有备份文件。
- 不删除任务命名规则之外的任何文件。

## 实现要求

1. 先检查现有 Django/SQLite 配置与 `.gitignore`，确认真实数据库继续被排除。
2. 实现 `backup_local_db`，至少支持：默认安全目录、`HUNTALPHA_LOCAL_BACKUP_DIR`、可配置历史保留数量、SHA-256、SQLite 完整性检查和清晰退出码。
3. 默认备份目录必须解析为仓库外路径；若无法可靠确定安全路径，应拒绝执行并要求设置 `HUNTALPHA_LOCAL_BACKUP_DIR`。
4. 备份成功时输出：备份路径、大小、SHA-256、integrity check 结果；不得输出数据库内容。
5. 实现 Windows 定时任务脚本/说明，时间参数可配置；安装和移除均应可重复执行，名称固定且清晰，例如 `HuntAlpha Local DB Backup`。
6. 自动备份失败时必须留下可诊断的非敏感错误，但不得在仓库内生成含用户数据的日志。
7. 更新 `AGENTS.md` 数据库操作前恢复点规则。
8. 编写测试覆盖至少：成功备份、hash 一致、integrity check、拒绝仓库内目标目录、不会覆盖同名备份、只清理自身旧备份、非 SQLite 明确拒绝。
9. 不在测试中读取当前用户的真实 `db.sqlite3`。

## 验收标准

- [x] `db.sqlite3` 仍未被 Git 跟踪，现有本地数据没有进入 GitHub。
- [x] 一条命令可以在仓库外生成一致性 SQLite 备份。
- [x] 每份有效备份都有可核验的 SHA-256 和 SQLite 完整性检查结果。
- [x] 备份命令不会输出任何数据库业务内容或私有公式源码。
- [x] 目标目录位于仓库内部时命令会拒绝执行。
- [x] 默认不会覆盖已有备份。
- [x] 历史清理只作用于本命令创建的自动备份，不会删除未知/手工恢复文件。
- [x] Windows 定时备份入口可配置、可安装、可移除，并复用同一 Django 备份命令。
- [x] `AGENTS.md` 明确要求数据库高风险操作前先建立恢复点。
- [x] 自动测试完全使用临时数据库/临时目录，不接触真实用户数据库。
- [x] 备份失败时返回失败状态，且不会把不完整文件伪装成有效备份。

## 必须运行的检查

- [x] `git diff --check`
- [x] `python manage.py check`
- [x] 相关 Django/management command 自动测试
- [x] 使用临时 SQLite 数据库完成一次成功备份、SHA-256 与 `PRAGMA integrity_check` 验证
- [x] 验证仓库内部目标路径会被拒绝
- [x] 验证保留策略不会删除未知文件
- [x] 验证 `git status` 中没有数据库、备份或敏感运行产物

## Codex Completion Report

- Branch: `codex/002-local-data-protection-and-backup`
- Commit: `f714071`（实现提交）、`d8d9020`（状态与 Completion Report）、本次 PR 信息更新提交见分支最新历史
- Push: 已成功推送到 `origin/codex/002-local-data-protection-and-backup`
- Summary: 新增安全的 SQLite 一致性备份命令、SHA-256/integrity_check 校验、仓库内路径拒绝、不可覆盖发布和自动备份保留策略；新增 Windows 计划任务入口、操作说明和临时数据库测试。
- Files changed: `AGENTS.md`、`core/management/commands/backup_local_db.py`、`core/tests.py`、`docs/operations/local-database-backup.md`、本任务文档、`scripts/manage_local_db_backup_task.ps1`
- Checks run: `git diff --check` 通过；`python manage.py check` 通过（仅有既存的两个 `DEFAULT_AUTO_FIELD` 警告）；`python manage.py test core` 23/23 通过；PowerShell 脚本语法检查通过。
- Backup command example: `python manage.py backup_local_db`；可用 `--keep 30` 或 `HUNTALPHA_LOCAL_BACKUP_KEEP` 配置保留数量。
- Default / configured backup directory behavior: 默认使用仓库父目录下的 `huntalpha-db-backups`；可用 `HUNTALPHA_LOCAL_BACKUP_DIR` 指定仓库外目录；仓库内路径一律拒绝。
- Retention behavior: 默认保留 30 份，只处理严格匹配 `huntalpha-local-db-YYYYMMDD-HHMMSS-ffffff.sqlite3` 的自动备份，不删除未知文件、手工恢复目录或其他文件。
- Windows scheduled-task behavior: `scripts/manage_local_db_backup_task.ps1 -Action Install -Time 03:00` 创建/更新固定名称的当前用户每日任务；`-Action Remove` 可重复移除；任务动作只调用 `python manage.py backup_local_db`。
- Design choices: 源库以只读 SQLite URI 打开，使用 `Connection.backup()` 生成一致性副本；临时文件先完成完整性和哈希校验，再通过同目录非覆盖原子发布；失败时清理临时文件且不输出数据库内容。
- Real local backup verification: `C:\Users\Administrator\Documents\ChatGPT\huntalpha-db-backups\huntalpha-local-db-20260905-031549-149897.sqlite3`，180224 bytes，SHA-256 `251C994F9A8D2716340158694F6657031EC9D95190C5349B09398F7A13E22A37`，`integrity_check: ok`；只读 ORM 确认 Formula 仍为 4 条。
- Unresolved issues/risks: 本地备份未加密，备份目录必须按敏感本地数据保护；计划任务运行账户需能访问已配置的备份目录；Django 仍有两个既存的主键类型警告。
- PR: [#4](https://github.com/kuashan/huntalpha/pull/4)，不在本任务中自动合并

## Review

由 ChatGPT/用户验收后填写：

- Result: ACCEPTED
- Notes: ChatGPT 已直接检查 PR #4 的实际改动。备份命令使用 SQLite 一致性备份、完整性检查和 SHA-256，拒绝仓库内目标目录且不覆盖既有备份；保留策略只清理严格匹配的自动备份；自动测试使用临时数据库；GitHub PR 中未出现数据库、备份或私有公式源码。真实本地备份验证成功，Formula 仍为 4 条。Windows 计划任务当前采用当前用户交互式登录上下文，因此只有在该用户已登录时才会按计划运行；这是已知的非阻塞限制，后续若需要“注销后仍运行/错过时间后补跑”可另开小任务增强。
