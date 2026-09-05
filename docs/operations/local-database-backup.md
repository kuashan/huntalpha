# HuntAlpha 本地数据库备份

`db.sqlite3` 包含本地账户、Session、管理员记录和私有指标源码，只能保存在本机受保护的目录中，不得加入 Git、云盘同步目录或公开压缩包。

## 手动备份

在项目根目录运行：

```powershell
python manage.py backup_local_db
```

命令使用 SQLite 一致性备份能力，先写同一备份目录中的临时文件，再执行 `PRAGMA integrity_check`、SHA-256 和发布后校验；校验失败不会留下有效备份文件。成功时只输出备份路径、文件名、大小、SHA-256、完整性结果和清理数量，不输出任何表数据或公式源码。

默认目录是仓库外的：

```text
<项目父目录>\huntalpha-db-backups\
```

可以在当前进程中指定安全的仓库外目录，并调整保留数量：

```powershell
$env:HUNTALPHA_LOCAL_BACKUP_DIR = 'D:\HuntAlphaPrivate\db-backups'
$env:HUNTALPHA_LOCAL_BACKUP_KEEP = '30'
python manage.py backup_local_db
```

也可以只对本次命令指定保留数量：

```powershell
python manage.py backup_local_db --keep 30
```

目标目录如果位于项目/Git 仓库内，命令会拒绝执行。已有同名备份不会被覆盖。

## Windows 定时备份

安装或更新名为 `HuntAlpha Local DB Backup` 的当前用户定时任务，时间使用 24 小时制：

```powershell
.\scripts\manage_local_db_backup_task.ps1 -Action Install -Time 03:00
```

如需使用特定 Python：

```powershell
.\scripts\manage_local_db_backup_task.ps1 -Action Install -Time 02:30 -Python 'C:\Path\to\python.exe'
```

移除任务：

```powershell
.\scripts\manage_local_db_backup_task.ps1 -Action Remove
```

脚本只创建、更新或移除这个固定名称的用户级计划任务；计划任务的动作始终调用同一个 `python manage.py backup_local_db` 命令，不包含第二套复制逻辑。脚本不会修改执行策略或其他系统全局设置。安装前请按需要在运行任务的用户环境中配置 `HUNTALPHA_LOCAL_BACKUP_DIR`；未配置时使用默认目录。

## 从备份恢复

恢复不是自动操作。先停止 Django、前端和其他可能使用数据库的服务；把当前 `db.sqlite3` 复制到仓库外的独立目录并保留；确认待恢复备份的 SHA-256 和 `PRAGMA integrity_check`；再由人工执行最小范围恢复，并进行只读 ORM/API 验证。不要执行 `flush`、`reset` 或未经确认的覆盖操作，也不要删除 `huntalpha-db-recovery`。

恢复点和备份文件始终位于仓库之外，Git 只记录命令、脚本和本说明。
