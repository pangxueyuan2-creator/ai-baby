"""Audit whether stored AI Baby backups are actually restorable."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .doctor import diagnose_database
from .memory import MemoryError
from .models import safe_output
from .restore import check_restore_backup

EXIT_OK = 0
EXIT_NOT_READY = 1
_IO_ERROR_MESSAGE = "无法读取备份目录、备份文件或临时验证目录；请检查路径和权限。"


def _default_data_dir() -> Path:
    """Match the app default without loading model/provider configuration."""
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def _current_database_report(database: Path) -> dict[str, Any]:
    """Return only privacy-safe doctor fields, never the absolute database path."""
    report = diagnose_database(database)
    return {
        "status": report["status"],
        "code": report["code"],
        "schema_version": report["schema_version"],
        "target_schema_version": report["target_schema_version"],
        "counts": report["counts"],
        "message": report["message"],
    }


def _orphan_manifests(backup_dir: Path) -> list[str]:
    if not backup_dir.is_dir():
        return []
    result: list[str] = []
    for manifest in sorted(backup_dir.glob("*.sqlite3.sha256")):
        backup = manifest.with_name(manifest.name[: -len(".sha256")])
        if not backup.is_file():
            result.append(manifest.name)
    return result


def audit_recovery_readiness(
    data_dir: Path,
    *,
    backup_dir: Path | None = None,
    require_checksum: bool = False,
) -> dict[str, Any]:
    """Read-only audit the live database and every stored SQLite backup.

    Each backup goes through the same staged migration/schema/foreign-key validation as
    ``ai-baby-restore --check``. The source files are never migrated or modified.
    """
    data_dir = data_dir.expanduser()
    backup_dir = (backup_dir or data_dir / "backups").expanduser()
    current = _current_database_report(data_dir / "baby.sqlite3")
    backups = sorted(backup_dir.glob("*.sqlite3")) if backup_dir.is_dir() else []

    backup_reports: list[dict[str, Any]] = []
    for backup in backups:
        try:
            report = check_restore_backup(backup, require_checksum=require_checksum)
        except (MemoryError, ValueError) as exc:
            backup_reports.append(
                {
                    "name": backup.name,
                    "status": "error",
                    "message": str(exc),
                }
            )
            continue
        except OSError:
            backup_reports.append(
                {
                    "name": backup.name,
                    "status": "error",
                    "message": _IO_ERROR_MESSAGE,
                }
            )
            continue
        backup_reports.append(
            {
                "name": backup.name,
                "status": "ok",
                "checksum_present": report["checksum"] is not None,
                "source_schema_version": report["source_schema_version"],
                "target_schema_version": report["target_schema_version"],
                "migration_required": report["migration_required"],
            }
        )

    orphans = _orphan_manifests(backup_dir)
    recoverable = sum(report["status"] == "ok" for report in backup_reports)
    invalid = len(backup_reports) - recoverable

    if current["status"] == "error" or invalid or orphans:
        status = "error"
        message = "当前数据库或至少一个恢复工件未通过检查。"
    elif not backup_reports:
        status = "no_backups"
        message = "未发现可恢复备份；当前数据没有经过灾备副本验证。"
    else:
        status = "ok"
        message = "当前数据库可读取，且所有发现的备份均通过完整恢复预检。"

    return {
        "status": status,
        "message": message,
        "checksum_policy": "required" if require_checksum else "optional",
        "current_database": current,
        "backup_summary": {
            "checked": len(backup_reports),
            "recoverable": recoverable,
            "invalid": invalid,
            "orphan_manifests": len(orphans),
        },
        "backups": backup_reports,
        "orphan_manifests": orphans,
    }


def _print_human(report: dict[str, Any]) -> None:
    labels = {"ok": "OK", "no_backups": "NOT READY", "error": "ERROR"}
    print("AI Baby recovery audit: " + labels[report["status"]])
    current = report["current_database"]
    version = current["schema_version"]
    schema = "unknown" if version is None else f"v{version}"
    print(f"current database: {current['status']} ({schema})")
    summary = report["backup_summary"]
    print(
        "backups: "
        f"checked={summary['checked']} recoverable={summary['recoverable']} "
        f"invalid={summary['invalid']} orphan_manifests={summary['orphan_manifests']}"
    )
    print("checksum policy: " + report["checksum_policy"])
    for backup in report["backups"]:
        if backup["status"] == "ok":
            migration = " migration-required" if backup["migration_required"] else ""
            checksum = " checksum" if backup["checksum_present"] else " no-checksum"
            print(f"[OK] {safe_output(backup['name'])}{checksum}{migration}")
        else:
            print(f"[ERROR] {safe_output(backup['name'])}: {safe_output(backup['message'])}")
    for manifest in report["orphan_manifests"]:
        print("[ERROR] orphan checksum manifest: " + safe_output(manifest))
    print(safe_output(str(report["message"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "只读审计当前 AI Baby 数据库与全部备份，并用真实恢复路径验证每个备份是否可恢复"
        )
    )
    parser.add_argument("--data-dir", type=Path, help="宝宝数据目录；默认 ~/.ai-baby")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="要审计的备份目录；默认 DATA_DIR/backups",
    )
    parser.add_argument(
        "--require-checksum",
        action="store_true",
        help="要求每个备份都有匹配的 .sha256；适合 CI 和灾备演练",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    try:
        report = audit_recovery_readiness(
            args.data_dir or _default_data_dir(),
            backup_dir=args.backup_dir,
            require_checksum=args.require_checksum,
        )
    except OSError:
        if args.json:
            print(json.dumps({"status": "error", "message": _IO_ERROR_MESSAGE}, ensure_ascii=False))
        else:
            print(_IO_ERROR_MESSAGE)
        return EXIT_NOT_READY

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report)
    return EXIT_OK if report["status"] == "ok" else EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
