"""Create and verify checksum-protected AI Baby SQLite backups."""

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .doctor import diagnose_database
from .memory import MemoryError, MemoryStore
from .models import safe_output
from .storage_files import reserve_private_file

EXIT_OK = 0
EXIT_INVALID = 1
_CHUNK_SIZE = 1024 * 1024


def _default_data_dir() -> Path:
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def checksum_manifest_path(backup: Path) -> Path:
    """Return the adjacent checksum sidecar path for *backup*."""
    return backup.with_name(backup.name + ".sha256")


def sha256_file(path: Path) -> str:
    """Hash a file without loading private database contents into memory at once."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum_manifest(backup: Path) -> tuple[Path, str]:
    """Exclusively create an owner-only SHA-256 sidecar for an existing backup."""
    digest = sha256_file(backup)
    manifest = checksum_manifest_path(backup)
    reserve_private_file(manifest)
    try:
        with manifest.open("w", encoding="ascii", newline="\n") as output:
            output.write(f"{digest}  {backup.name}\n")
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    return manifest, digest


def _manifest_checksum(backup: Path, *, required: bool) -> str | None:
    manifest = checksum_manifest_path(backup)
    if not manifest.exists():
        if required:
            raise MemoryError("备份缺少 SHA-256 校验文件。")
        return None
    if not manifest.is_file():
        raise MemoryError("备份 SHA-256 校验路径不是普通文件。")
    try:
        if manifest.stat().st_size > 512:
            raise MemoryError("备份 SHA-256 校验文件格式无效。")
        lines = manifest.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise MemoryError("无法读取备份 SHA-256 校验文件。") from exc
    if len(lines) != 1:
        raise MemoryError("备份 SHA-256 校验文件格式无效。")
    expected, separator, filename = lines[0].partition("  ")
    if (
        separator != "  "
        or filename != backup.name
        or len(expected) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in expected)
    ):
        raise MemoryError("备份 SHA-256 校验文件格式无效。")
    return expected.casefold()


def verify_checksum_manifest(backup: Path, *, required: bool = False) -> str | None:
    """Verify the adjacent checksum when present; optionally require it."""
    expected = _manifest_checksum(backup, required=required)
    if expected is None:
        return None
    try:
        actual = sha256_file(backup)
    except OSError as exc:
        raise MemoryError("无法读取备份文件以验证 SHA-256。") from exc
    if not hmac.compare_digest(actual, expected):
        raise MemoryError("备份 SHA-256 校验失败；文件可能损坏或已被修改。")
    return actual


def _healthy_backup_report(path: Path) -> dict[str, Any]:
    report = diagnose_database(path)
    if report["status"] not in {"ok", "upgrade_required"}:
        raise MemoryError(str(report["message"]))
    return report


def backup_open_store(memory: MemoryStore, destination: Path) -> tuple[Path, str]:
    """Back up an already-open store and atomically pair it with a checksum sidecar."""
    memory.backup(destination)
    try:
        return write_checksum_manifest(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def backup_database(source: Path, destination: Path) -> tuple[Path, str, dict[str, Any]]:
    """Create a verified backup from a live database without migrating or modifying it."""
    source = source.expanduser()
    destination = destination.expanduser()
    if not source.is_file():
        raise ValueError("数据库文件不存在或不是普通文件。")
    if source.resolve() == destination.resolve():
        raise ValueError("备份目标不能与正在备份的数据库相同。")

    _healthy_backup_report(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reserve_private_file(destination)
    try:
        uri = source.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True, timeout=2)) as reader,
            closing(sqlite3.connect(destination, timeout=2)) as target,
        ):
            reader.backup(target)
        report = _healthy_backup_report(destination)
        manifest, digest = write_checksum_manifest(destination)
        return manifest, digest, report
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def verify_backup(path: Path, *, require_checksum: bool = False) -> dict[str, Any]:
    """Verify checksum (when present) plus SQLite/schema health without writing the backup."""
    path = path.expanduser()
    if not path.is_file():
        raise ValueError("备份文件不存在或不是普通文件。")
    digest = verify_checksum_manifest(path, required=require_checksum)
    report = _healthy_backup_report(path)
    return {
        "status": "ok",
        "backup": str(path),
        "checksum": digest,
        "checksum_manifest": str(checksum_manifest_path(path)) if digest else None,
        "schema_status": report["status"],
        "schema_version": report["schema_version"],
        "target_schema_version": report["target_schema_version"],
    }


def _default_destination(data_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return data_dir / "backups" / f"baby-{stamp}.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="创建或只读验证带 SHA-256 校验文件的 AI Baby SQLite 备份"
    )
    parser.add_argument("--data-dir", type=Path, help="宝宝数据目录；默认 ~/.ai-baby")
    parser.add_argument("--output", type=Path, help="备份输出路径；默认写入数据目录/backups")
    parser.add_argument("--verify", type=Path, help="只读验证指定备份，不创建新备份")
    parser.add_argument(
        "--require-checksum",
        action="store_true",
        help="验证时要求存在 .sha256 校验文件；默认兼容旧版无校验备份",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    if args.verify is not None and (args.data_dir is not None or args.output is not None):
        parser.error("--verify 不能与 --data-dir 或 --output 同时使用。")
    if args.verify is None and args.require_checksum:
        parser.error("--require-checksum 仅用于 --verify。")

    try:
        if args.verify is not None:
            result = verify_backup(args.verify, require_checksum=args.require_checksum)
        else:
            data_dir = (args.data_dir or _default_data_dir()).expanduser()
            source = data_dir / "baby.sqlite3"
            destination = (args.output or _default_destination(data_dir)).expanduser()
            manifest, digest, report = backup_database(source, destination)
            result = {
                "status": "ok",
                "backup": str(destination),
                "checksum": digest,
                "checksum_manifest": str(manifest),
                "schema_status": report["status"],
                "schema_version": report["schema_version"],
                "target_schema_version": report["target_schema_version"],
            }
    except (MemoryError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        else:
            print(safe_output(str(exc)))
        return EXIT_INVALID
    except (OSError, sqlite3.Error):
        message = "无法读取数据库或写入备份；请检查路径、磁盘和权限。"
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return EXIT_INVALID

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.verify is not None:
        print("备份验证通过：" + safe_output(str(result["backup"])))
        if result["checksum"] is None:
            print("SHA-256：未提供校验文件（兼容旧版备份）。")
        else:
            print("SHA-256：" + str(result["checksum"]))
    else:
        print("备份完成：" + safe_output(str(result["backup"])))
        print("SHA-256：" + str(result["checksum"]))
        print("校验文件：" + safe_output(str(result["checksum_manifest"])))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
