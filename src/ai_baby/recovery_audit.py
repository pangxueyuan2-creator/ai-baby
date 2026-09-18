"""Audit whether stored AI Baby backups are actually restorable."""

import argparse
import json
import math
import os
import time
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


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须至少为 1")
    return parsed


def _positive_hours(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是大于 0 的小时数") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的有限小时数")
    return parsed


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
    min_recoverable_backups: int = 1,
    max_backup_age_hours: float | None = None,
) -> dict[str, Any]:
    """Read-only audit the live database and every stored SQLite backup.

    Each backup goes through the same staged migration/schema/foreign-key validation as
    ``ai-baby-restore --check``. Optional policy gates can additionally require multiple
    recoverable copies and at least one sufficiently recent copy. Source files are never
    migrated or modified.
    """
    if min_recoverable_backups < 1:
        raise ValueError("min_recoverable_backups must be at least 1")
    if max_backup_age_hours is not None and (
        not math.isfinite(max_backup_age_hours) or max_backup_age_hours <= 0
    ):
        raise ValueError("max_backup_age_hours must be a finite value greater than 0")

    data_dir = data_dir.expanduser()
    backup_dir = (backup_dir or data_dir / "backups").expanduser()
    current = _current_database_report(data_dir / "baby.sqlite3")
    backups = sorted(backup_dir.glob("*.sqlite3")) if backup_dir.is_dir() else []
    audit_time = time.time() if max_backup_age_hours is not None else None

    backup_reports: list[dict[str, Any]] = []
    for backup in backups:
        try:
            modified_at = backup.stat().st_mtime if audit_time is not None else None
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
        backup_report: dict[str, Any] = {
            "name": backup.name,
            "status": "ok",
            "checksum_present": report["checksum"] is not None,
            "source_schema_version": report["source_schema_version"],
            "target_schema_version": report["target_schema_version"],
            "migration_required": report["migration_required"],
        }
        if audit_time is not None and modified_at is not None and max_backup_age_hours is not None:
            age_hours = max(0.0, (audit_time - modified_at) / 3600.0)
            backup_report["age_hours"] = round(age_hours, 3)
            backup_report["fresh"] = age_hours <= max_backup_age_hours
        backup_reports.append(backup_report)

    orphans = _orphan_manifests(backup_dir)
    recoverable = sum(report["status"] == "ok" for report in backup_reports)
    invalid = len(backup_reports) - recoverable
    fresh_recoverable = None
    if max_backup_age_hours is not None:
        fresh_recoverable = sum(report.get("fresh") is True for report in backup_reports)

    policy_violations: list[str] = []
    if recoverable < min_recoverable_backups:
        policy_violations.append(
            f"至少需要 {min_recoverable_backups} 个可恢复备份，当前只有 {recoverable} 个。"
        )
    if max_backup_age_hours is not None and fresh_recoverable == 0:
        policy_violations.append(f"没有在最近 {max_backup_age_hours:g} 小时内创建且可恢复的备份。")

    if current["status"] == "error" or invalid or orphans:
        status = "error"
        message = "当前数据库或至少一个恢复工件未通过检查。"
    elif not backup_reports:
        status = "no_backups"
        message = "未发现可恢复备份；当前数据没有经过灾备副本验证。"
    elif policy_violations:
        status = "policy_failed"
        message = "备份完整性检查通过，但未达到配置的恢复就绪策略。"
    else:
        status = "ok"
        message = "当前数据库可读取，全部备份可恢复，并满足配置的恢复就绪策略。"

    return {
        "status": status,
        "message": message,
        "checksum_policy": "required" if require_checksum else "optional",
        "recovery_policy": {
            "min_recoverable_backups": min_recoverable_backups,
            "max_backup_age_hours": max_backup_age_hours,
            "fresh_recoverable": fresh_recoverable,
            "violations": policy_violations,
        },
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
    labels = {
        "ok": "OK",
        "no_backups": "NOT READY",
        "policy_failed": "NOT READY",
        "error": "ERROR",
    }
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
    policy = report["recovery_policy"]
    max_age = policy["max_backup_age_hours"]
    max_age_text = "disabled" if max_age is None else f"{max_age:g}h"
    print(
        "recovery policy: "
        f"min-recoverable={policy['min_recoverable_backups']} max-age={max_age_text}"
    )
    if policy["fresh_recoverable"] is not None:
        print(f"fresh recoverable backups: {policy['fresh_recoverable']}")
    for backup in report["backups"]:
        if backup["status"] == "ok":
            migration = " migration-required" if backup["migration_required"] else ""
            checksum = " checksum" if backup["checksum_present"] else " no-checksum"
            freshness = ""
            if "fresh" in backup:
                state = "fresh" if backup["fresh"] else "stale"
                freshness = f" {state} age={backup['age_hours']:g}h"
            print(f"[OK] {safe_output(backup['name'])}{checksum}{migration}{freshness}")
        else:
            print(f"[ERROR] {safe_output(backup['name'])}: {safe_output(backup['message'])}")
    for manifest in report["orphan_manifests"]:
        print("[ERROR] orphan checksum manifest: " + safe_output(manifest))
    for violation in policy["violations"]:
        print("[POLICY] " + safe_output(violation))
    print(safe_output(str(report["message"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "只读审计 AI Baby 当前数据库与全部备份，并验证可恢复性、备份数量和恢复点新鲜度"
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
    parser.add_argument(
        "--min-recoverable-backups",
        type=_positive_int,
        default=1,
        help="至少需要多少个可恢复备份；默认 1",
    )
    parser.add_argument(
        "--max-backup-age-hours",
        type=_positive_hours,
        help="要求至少一个可恢复备份不早于给定小时数；默认不检查新鲜度",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    try:
        report = audit_recovery_readiness(
            args.data_dir or _default_data_dir(),
            backup_dir=args.backup_dir,
            require_checksum=args.require_checksum,
            min_recoverable_backups=args.min_recoverable_backups,
            max_backup_age_hours=args.max_backup_age_hours,
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
