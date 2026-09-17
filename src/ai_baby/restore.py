"""Validate and restore an AI Baby SQLite backup without overwriting live data."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from .backup import verify_checksum_manifest
from .memory import MemoryError, MemoryStore
from .migrations import MIGRATIONS, SCHEMA_VERSION
from .models import safe_output


def restore_backup(source: Path, data_dir: Path) -> Path:
    """Restore *source* into a new data directory after full staged validation.

    The source backup is opened read-only, copied through SQLite's backup API, migrated and
    validated in a private temporary directory, then copied into the final destination. The
    final ``baby.sqlite3`` is created exclusively and is never allowed to replace an existing
    store. If an adjacent ``.sha256`` manifest exists, it is verified before SQLite is opened.
    """
    source = source.expanduser()
    destination = data_dir.expanduser() / "baby.sqlite3"

    if not source.is_file():
        raise ValueError("备份文件不存在或不是普通文件。")
    if destination.exists():
        raise ValueError("目标数据目录已经存在 baby.sqlite3；为避免覆盖现有宝宝，恢复已取消。")

    verify_checksum_manifest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ai-baby-restore-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "baby.sqlite3"
        try:
            with (
                closing(
                    sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
                ) as reader,
                closing(sqlite3.connect(staged)) as target,
            ):
                check = reader.execute("PRAGMA quick_check").fetchone()
                if check is None or check[0] != "ok":
                    raise MemoryError("备份数据库完整性检查未通过；目标未修改。")
                version = reader.execute("PRAGMA user_version").fetchone()[0]
                if version not in {SCHEMA_VERSION, *MIGRATIONS}:
                    raise MemoryError("备份数据库版本不受支持；目标未修改。")
                reader.backup(target)
        except sqlite3.Error as exc:
            raise MemoryError("备份文件不是可恢复的 SQLite 数据库；目标未修改。") from exc

        try:
            restored = MemoryStore(staged)
        except MemoryError as exc:
            raise MemoryError("备份数据库版本或结构无法验证；目标未修改。") from exc
        try:
            if restored.db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise MemoryError("备份数据库引用完整性检查未通过；目标未修改。")
            try:
                restored.backup(destination)
            except FileExistsError as exc:
                raise ValueError(
                    "目标数据目录在恢复期间出现了 baby.sqlite3；为避免覆盖，恢复已取消。"
                ) from exc
        finally:
            restored.close()

    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="验证 AI Baby SQLite 备份并恢复到一个不含 baby.sqlite3 的数据目录"
    )
    parser.add_argument(
        "backup", type=Path, help="由 /backup 或 ai-baby-backup 创建的 .sqlite3 文件"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="恢复目标数据目录；若其中已有 baby.sqlite3 将拒绝覆盖",
    )
    args = parser.parse_args(argv)

    try:
        destination = restore_backup(args.backup, args.data_dir)
    except (MemoryError, ValueError) as exc:
        print(safe_output(str(exc)))
        return 1
    except OSError:
        print("无法读取备份或写入目标目录；请检查路径、磁盘和权限。目标未被覆盖。")
        return 1

    print(f"恢复完成：{destination}")
    print("原备份保持只读未修改；现在可用 ai-baby --data-dir 该目录启动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
