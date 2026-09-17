"""Export user-visible AI Baby data to a versioned, privacy-aware JSON document."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .doctor import diagnose_database
from .memory import MemoryError
from .models import safe_output
from .storage_files import reserve_private_file

EXIT_OK = 0
EXIT_INVALID = 1
FORMAT_NAME = "ai-baby-privacy-export"
FORMAT_VERSION = 1


def _default_data_dir() -> Path:
    """Match the app default without importing provider configuration."""
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def _row_dicts(db: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    rows = db.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _parse_state(rows: list[sqlite3.Row]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for row in rows:
        try:
            value = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise MemoryError("保存的角色状态格式损坏；请先从已验证备份恢复。") from exc
        if not isinstance(value, dict):
            raise MemoryError("保存的角色状态格式损坏；请先从已验证备份恢复。")
        state[row["key"]] = value
    return state


def build_privacy_export(
    database: Path,
    *,
    include_history: bool = False,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Build a deterministic JSON-ready export without modifying the SQLite database."""
    database = database.expanduser()
    report = diagnose_database(database)
    if report["status"] == "upgrade_required":
        raise MemoryError("数据库需要先由当前 AI Baby 正常启动并完成 schema 升级后再导出。")
    if report["status"] != "ok":
        raise MemoryError(str(report["message"]))

    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")

        profile_row = db.execute(
            "SELECT name,gender,address,created_at FROM profile WHERE id=1"
        ).fetchone()
        state_rows = db.execute("SELECT key,value FROM state ORDER BY key").fetchall()
        baby_name_row = db.execute("SELECT value FROM settings WHERE key='baby_name'").fetchone()

        fact_filter = "" if include_inactive else " WHERE active=1"
        episode_filter = "" if include_inactive else " WHERE active=1"
        facts = _row_dicts(
            db,
            "SELECT id,kind,subject,predicate,value,active,created_at FROM facts"
            + fact_filter
            + " ORDER BY id",
        )
        episodes = _row_dicts(
            db,
            "SELECT id,kind,summary,importance,active,fact_id,created_at FROM episodes"
            + episode_filter
            + " ORDER BY id",
        )

        payload: dict[str, Any] = {
            "format": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "schema_version": report["schema_version"],
            "options": {
                "include_history": include_history,
                "include_inactive": include_inactive,
            },
            "profile": dict(profile_row) if profile_row else None,
            "baby": {
                "name": baby_name_row[0] if baby_name_row else "AI 宝宝",
                "state": _parse_state(state_rows),
            },
            "facts": facts,
            "episodes": episodes,
            "omitted_internal_tables": [
                "candidates",
                "curiosity",
                "episode_tokens",
                "experience",
                "fact_tokens",
                "revision",
                "turn_receipts",
            ],
        }
        if include_history:
            payload["history"] = {
                "messages": _row_dicts(
                    db,
                    "SELECT id,role,content,created_at FROM messages ORDER BY id",
                ),
                "journals": _row_dicts(
                    db,
                    "SELECT id,through_episode,through_turn,summary,created_at "
                    "FROM journals ORDER BY id",
                ),
            }
        return payload


def write_privacy_export(
    database: Path,
    output: Path,
    *,
    include_history: bool = False,
    include_inactive: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    """Validate source first, then exclusively create an owner-private JSON export."""
    database = database.expanduser()
    output = output.expanduser()
    if database.resolve() == output.resolve():
        raise ValueError("导出目标不能与 AI Baby 数据库相同。")

    payload = build_privacy_export(
        database,
        include_history=include_history,
        include_inactive=include_inactive,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        reserve_private_file(output)
    except FileExistsError as exc:
        raise ValueError("导出目标已存在；为避免覆盖私人数据，AI Baby 不会改写它。") from exc
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.write("\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "只读导出 AI Baby 的用户可见资料、状态、记忆与事件为版本化 JSON；"
            "默认不包含原始聊天记录"
        )
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--data-dir", type=Path, help="宝宝数据目录；导出其中 baby.sqlite3")
    location.add_argument("--database", type=Path, help="直接导出指定 AI Baby SQLite 文件")
    parser.add_argument("--output", type=Path, required=True, help="新 JSON 文件路径；绝不覆盖已有文件")
    parser.add_argument(
        "--include-history",
        action="store_true",
        help="显式包含原始 messages 与 journal 摘要；它们可能包含敏感聊天内容",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="显式包含已停用/被替代的 facts 与 episodes",
    )
    parser.add_argument("--pretty", action="store_true", help="将导出文件格式化为易读的缩进 JSON")
    parser.add_argument("--json", action="store_true", help="CLI 状态也输出稳定 JSON，便于脚本使用")
    args = parser.parse_args(argv)

    database = args.database or (args.data_dir or _default_data_dir()) / "baby.sqlite3"
    try:
        payload = write_privacy_export(
            database,
            args.output,
            include_history=args.include_history,
            include_inactive=args.include_inactive,
            pretty=args.pretty,
        )
    except (MemoryError, ValueError) as exc:
        message = str(exc)
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(safe_output(message))
        return EXIT_INVALID
    except (OSError, sqlite3.Error):
        message = "无法读取数据库或写入导出文件；请检查路径、磁盘和权限。"
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return EXIT_INVALID

    result = {
        "status": "ok",
        "output": str(args.output.expanduser()),
        "format": payload["format"],
        "format_version": payload["format_version"],
        "facts": len(payload["facts"]),
        "episodes": len(payload["episodes"]),
        "history_included": "history" in payload,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("隐私导出完成：" + safe_output(str(args.output.expanduser())))
        print(f"facts={result['facts']} episodes={result['episodes']}")
        if "history" not in payload:
            print("原始聊天记录未包含；如确有需要，请显式使用 --include-history。")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
