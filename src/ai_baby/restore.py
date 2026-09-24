"""Validate and restore an AI Baby SQLite backup without overwriting live data."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .backup import checksum_manifest_path, verify_checksum_manifest
from .memory import MemoryError, MemoryStore
from .migrations import MIGRATIONS, SCHEMA_VERSION
from .models import safe_output
from .state_validation import StateValidationError, validate_stored_states

EXIT_OK = 0
EXIT_INVALID = 1


def _stage_backup(
    source: Path,
    staging_dir: Path,
    *,
    require_checksum: bool = False,
) -> tuple[MemoryStore, dict[str, Any]]:
    """Copy *source* read-only into a disposable store and fully validate it there."""
    source = source.expanduser()
    if not source.is_file():
        raise ValueError("备份文件不存在或不是普通文件。")

    digest = verify_checksum_manifest(source, required=require_checksum)
    staged = staging_dir / "baby.sqlite3"
    try:
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader,
            closing(sqlite3.connect(staged)) as target,
        ):
            check = reader.execute("PRAGMA quick_check").fetchone()
            if check is None or check[0] != "ok":
                raise MemoryError("备份数据库完整性检查未通过；目标未修改。")
            source_version = reader.execute("PRAGMA user_version").fetchone()[0]
            if source_version not in {SCHEMA_VERSION, *MIGRATIONS}:
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
            validate_stored_states(restored.db)
        except StateValidationError:
            raise MemoryError("备份角色状态格式损坏；目标未修改。") from None
        target_version = restored.db.execute("PRAGMA user_version").fetchone()[0]
    except BaseException:
        restored.close()
        raise

    return restored, {
        "status": "ok",
        "backup": str(source),
        "checksum": digest,
        "checksum_manifest": str(checksum_manifest_path(source)) if digest else None,
        "source_schema_version": source_version,
        "target_schema_version": target_version,
        "migration_required": source_version != target_version,
    }


def check_restore_backup(source: Path, *, require_checksum: bool = False) -> dict[str, Any]:
    """Prove a backup can reach the current schema without touching a target data directory."""
    with TemporaryDirectory(prefix=".ai-baby-restore-check-") as temporary:
        restored, report = _stage_backup(
            source,
            Path(temporary),
            require_checksum=require_checksum,
        )
        restored.close()
    return report


def restore_backup(
    source: Path,
    data_dir: Path,
    *,
    require_checksum: bool = False,
) -> Path:
    """Restore *source* into a new data directory after full staged validation.

    The source backup is opened read-only, copied into disposable staging, migrated and
    validated there, then copied into the final destination. The final ``baby.sqlite3`` is
    created exclusively and is never allowed to replace an existing store. If an adjacent
    ``.sha256`` manifest exists, it is verified before SQLite is opened; callers may require
    the manifest for automation with ``require_checksum=True``.
    """
    source = source.expanduser()
    destination = data_dir.expanduser() / "baby.sqlite3"

    if destination.exists():
        raise ValueError("目标数据目录已经存在 baby.sqlite3；为避免覆盖现有宝宝，恢复已取消。")

    # Validate in system temporary storage first. Invalid input therefore cannot create the
    # requested data directory as a side effect of merely attempting recovery.
    with TemporaryDirectory(prefix=".ai-baby-restore-") as temporary:
        restored, _ = _stage_backup(
            source,
            Path(temporary),
            require_checksum=require_checksum,
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
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
        description="预检或恢复 AI Baby SQLite 备份，不覆盖已有 baby.sqlite3"
    )
    parser.add_argument(
        "backup", type=Path, help="由 /backup 或 ai-baby-backup 创建的 .sqlite3 文件"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="恢复目标数据目录；实际恢复时必填，若已有 baby.sqlite3 将拒绝覆盖",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="完整预检备份及必要迁移，但不创建目标数据目录或 baby.sqlite3",
    )
    parser.add_argument(
        "--require-checksum",
        action="store_true",
        help="要求相邻 .sha256 校验文件存在并匹配；默认兼容旧版无校验备份",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    if args.check and args.data_dir is not None:
        parser.error("--check 不接受 --data-dir；预检不会创建恢复目标。")
    if not args.check and args.data_dir is None:
        parser.error("实际恢复必须提供 --data-dir；只验证请使用 --check。")

    try:
        if args.check:
            result = check_restore_backup(
                args.backup,
                require_checksum=args.require_checksum,
            )
        else:
            destination = restore_backup(
                args.backup,
                args.data_dir,
                require_checksum=args.require_checksum,
            )
            result = {
                "status": "ok",
                "backup": str(args.backup.expanduser()),
                "restored": str(destination),
                "checksum_required": args.require_checksum,
            }
    except (MemoryError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        else:
            print(safe_output(str(exc)))
        return EXIT_INVALID
    except OSError:
        message = "无法读取备份或写入临时/目标目录；请检查路径、磁盘和权限。目标未被覆盖。"
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return EXIT_INVALID

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.check:
        print("恢复预检通过：" + safe_output(str(result["backup"])))
        if result["checksum"] is None:
            print("SHA-256：未提供校验文件（兼容旧版备份）。")
        else:
            print("SHA-256：" + str(result["checksum"]))
        if result["migration_required"]:
            print(
                "Schema：恢复时将从 v"
                f"{result['source_schema_version']} 升级到 v{result['target_schema_version']}。"
            )
        else:
            print("Schema：当前版本，可直接恢复。")
    else:
        print(f"恢复完成：{result['restored']}")
        print("原备份保持只读未修改；现在可用 ai-baby --data-dir 该目录启动。")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
