"""Read-only health checks for an AI Baby SQLite database."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .migrations import MIGRATIONS, SCHEMA_VERSION, validate_schema
from .models import safe_output
from .state_validation import StateValidationError, validate_stored_states

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_UPGRADE_REQUIRED = 3


def _default_data_dir() -> Path:
    """Match the app's data-dir default without loading unrelated provider configuration."""
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def _report(path: Path, *, check: str) -> dict[str, Any]:
    return {
        "status": "error",
        "code": "unknown",
        "database": str(path),
        "schema_version": None,
        "target_schema_version": SCHEMA_VERSION,
        "integrity_check": check,
        "counts": None,
        "message": "",
    }


def diagnose_database(path: Path, *, full: bool = False) -> dict[str, Any]:
    """Inspect *path* without creating, migrating, or updating the database."""
    path = path.expanduser()
    check = "integrity_check" if full else "quick_check"
    result = _report(path, check=check)
    if not path.is_file():
        result.update(code="missing", message="数据库文件不存在或不是普通文件。")
        return result

    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")

            rows = db.execute(f"PRAGMA {check}").fetchall()
            if len(rows) != 1 or rows[0][0] != "ok":
                result.update(code="integrity_failed", message="SQLite 完整性检查未通过。")
                return result

            version = db.execute("PRAGMA user_version").fetchone()[0]
            result["schema_version"] = version
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }

            if version == 0:
                if tables:
                    result.update(
                        code="unversioned_database",
                        message="数据库包含表但没有 AI Baby schema 版本；不会自动修改。",
                    )
                else:
                    result.update(
                        code="uninitialized_database",
                        message="这是空 SQLite 文件，不是已初始化的 AI Baby 数据库。",
                    )
                return result

            if version < SCHEMA_VERSION and version in MIGRATIONS:
                result.update(
                    status="upgrade_required",
                    code="upgrade_required",
                    message=(
                        f"数据库 schema v{version} 可由当前版本升级到 v{SCHEMA_VERSION}；"
                        "doctor 保持只读，未执行迁移。"
                    ),
                )
                return result

            if version != SCHEMA_VERSION:
                result.update(
                    code="unsupported_schema",
                    message=(
                        f"数据库 schema v{version} 不受当前程序支持；"
                        f"当前支持版本为 v{SCHEMA_VERSION}。"
                    ),
                )
                return result

            try:
                validate_schema(db)
            except (sqlite3.Error, ValueError):
                result.update(
                    code="schema_invalid",
                    message="数据库版本正确，但必需表、列或并发保护结构不完整。",
                )
                return result

            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                result.update(
                    code="foreign_key_failed",
                    message="数据库存在引用完整性错误。",
                )
                return result

            try:
                validate_stored_states(db)
            except StateValidationError:
                result.update(
                    code="state_invalid",
                    message="保存的角色状态格式或数值无效；原数据未修改。",
                )
                return result

            counts = {
                "profile": db.execute("SELECT count(*) FROM profile").fetchone()[0],
                "active_facts": db.execute("SELECT count(*) FROM facts WHERE active=1").fetchone()[
                    0
                ],
                "active_episodes": db.execute(
                    "SELECT count(*) FROM episodes WHERE active=1"
                ).fetchone()[0],
                "messages": db.execute("SELECT count(*) FROM messages").fetchone()[0],
            }
            result.update(
                status="ok",
                code="ok",
                counts=counts,
                message="数据库完整性、当前 schema、外键引用和角色状态检查均通过。",
            )
            return result
    except sqlite3.Error:
        result.update(code="not_sqlite", message="无法以只读方式检查该 SQLite 数据库。")
        return result
    except OSError:
        result.update(code="unreadable", message="无法读取数据库文件；请检查路径和权限。")
        return result


def _print_human(report: dict[str, Any]) -> None:
    labels = {"ok": "OK", "upgrade_required": "UPGRADE REQUIRED", "error": "ERROR"}
    print(f"AI Baby doctor: {labels[report['status']]}")
    print("database: " + safe_output(str(report["database"])))
    version = report["schema_version"]
    if version is not None:
        print(f"schema: v{version} / current v{report['target_schema_version']}")
    print("integrity: " + str(report["integrity_check"]))
    counts = report["counts"]
    if counts is not None:
        print(
            "records: "
            f"profile={counts['profile']} active_facts={counts['active_facts']} "
            f"active_episodes={counts['active_episodes']} messages={counts['messages']}"
        )
    print(safe_output(str(report["message"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只读检查 AI Baby 数据库完整性、schema 和外键，不迁移也不写入"
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--data-dir", type=Path, help="宝宝数据目录；检查其中 baby.sqlite3")
    location.add_argument("--database", type=Path, help="直接检查指定 SQLite 文件")
    parser.add_argument(
        "--full",
        action="store_true",
        help="使用较慢的 SQLite integrity_check；默认使用 quick_check",
    )
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    database = args.database or (args.data_dir or _default_data_dir()) / "baby.sqlite3"
    report = diagnose_database(database, full=args.full)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report)

    if report["status"] == "ok":
        return EXIT_OK
    if report["status"] == "upgrade_required":
        return EXIT_UPGRADE_REQUIRED
    return EXIT_UNHEALTHY


if __name__ == "__main__":
    raise SystemExit(main())
