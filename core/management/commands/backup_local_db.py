import argparse
import hashlib
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


BACKUP_PREFIX = "huntalpha-local-db-"
BACKUP_SUFFIX = ".sqlite3"
BACKUP_PATTERN = re.compile(
    rf"{re.escape(BACKUP_PREFIX)}(?P<timestamp>\d{{8}}-\d{{6}}-\d{{6}}){re.escape(BACKUP_SUFFIX)}$"
)
DEFAULT_RETENTION = 30
BACKUP_DIR_ENV = "HUNTALPHA_LOCAL_BACKUP_DIR"
RETENTION_ENV = "HUNTALPHA_LOCAL_BACKUP_KEEP"


def _positive_integer(value):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def _is_within(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _repository_root(base_dir):
    base_dir = base_dir.resolve()
    for candidate in (base_dir, *base_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    return base_dir


def _database_path():
    database = settings.DATABASES.get("default", {})
    if database.get("ENGINE") != "django.db.backends.sqlite3":
        raise CommandError("backup_local_db 仅支持 SQLite 数据库，当前数据库引擎已拒绝备份")
    name = database.get("NAME")
    if not name or str(name) == ":memory:":
        raise CommandError("backup_local_db 需要一个现有的 SQLite 文件数据库")
    path = Path(name)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    path = path.resolve()
    if not path.is_file():
        raise CommandError("当前 SQLite 数据库文件不存在，未生成备份")
    return path


def _backup_directory():
    configured = os.environ.get(BACKUP_DIR_ENV, "").strip()
    path = Path(configured).expanduser() if configured else Path(settings.BASE_DIR).parent / "huntalpha-db-backups"
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _validate_backup_directory(path):
    repository = _repository_root(Path(settings.BASE_DIR))
    if _is_within(path, repository):
        raise CommandError("备份目录必须位于 Git 仓库之外，未生成备份")
    if path.exists() and not path.is_dir():
        raise CommandError("备份目标路径不是目录，未生成备份")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _readonly_uri(path):
    return f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"


def _integrity_check(path):
    connection = sqlite3.connect(_readonly_uri(path), uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise CommandError("SQLite integrity_check 未通过，未发布备份文件")
    return result[0]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_sqlite_backup(source_path, temporary_path):
    source = sqlite3.connect(_readonly_uri(source_path), uri=True)
    target = sqlite3.connect(str(temporary_path))
    try:
        source.backup(target, pages=0, sleep=0.25)
        target.commit()
    finally:
        target.close()
        source.close()


def _publish_without_overwrite(temporary_path, destination):
    try:
        # The hard link is an atomic, non-overwriting publish on the same
        # filesystem. The temporary file is created in the destination dir.
        os.link(temporary_path, destination)
    except FileExistsError as exc:
        raise CommandError("目标备份文件已存在，不覆盖已有备份") from exc
    except OSError as exc:
        raise CommandError("备份文件无法安全发布，未生成有效备份") from exc
    else:
        temporary_path.unlink()


def _automatic_backups(directory):
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and not path.is_symlink() and BACKUP_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def _remove_old_backups(directory, keep):
    removed = 0
    for path in _automatic_backups(directory)[keep:]:
        path.unlink()
        removed += 1
    return removed


class Command(BaseCommand):
    help = "Create and verify a consistent backup of the local SQLite database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            type=_positive_integer,
            default=None,
            help=f"保留自动备份数量（默认 {DEFAULT_RETENTION}，也可由 {RETENTION_ENV} 设置）",
        )

    def handle(self, *args, **options):
        source_path = _database_path()
        try:
            backup_directory = _validate_backup_directory(_backup_directory())
        except CommandError:
            raise
        except OSError as exc:
            raise CommandError("备份目录无法创建或访问，未生成备份") from exc
        keep = options.get("keep")
        if keep is None:
            configured_keep = os.environ.get(RETENTION_ENV, str(DEFAULT_RETENTION)).strip()
            try:
                keep = _positive_integer(configured_keep)
            except argparse.ArgumentTypeError as exc:
                raise CommandError(f"{RETENTION_ENV} 必须是正整数") from exc

        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = backup_directory / f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}"
        if destination.exists():
            raise CommandError("目标备份文件已存在，不覆盖已有备份")

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{BACKUP_PREFIX}{timestamp}-",
                suffix=".tmp",
                dir=backup_directory,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            _create_sqlite_backup(source_path, temporary_path)
            integrity = _integrity_check(temporary_path)
            digest = _sha256(temporary_path)
            size = temporary_path.stat().st_size
            _publish_without_overwrite(temporary_path, destination)
            temporary_path = None
            if _sha256(destination) != digest or destination.stat().st_size != size:
                destination.unlink(missing_ok=True)
                raise CommandError("备份发布后校验不一致，已移除无效备份")
            removed = _remove_old_backups(backup_directory, keep)
        except CommandError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise CommandError(f"备份失败（{type(exc).__name__}），未生成有效备份") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        self.stdout.write("备份已完成")
        self.stdout.write(f"path: {destination}")
        self.stdout.write(f"filename: {destination.name}")
        self.stdout.write(f"size: {size}")
        self.stdout.write(f"sha256: {digest}")
        self.stdout.write(f"integrity_check: {integrity}")
        self.stdout.write(f"retention_keep: {keep}")
        self.stdout.write(f"retention_removed: {removed}")
