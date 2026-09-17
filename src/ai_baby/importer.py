"""Import a default privacy export into a new AI Baby database."""

import argparse
import json
import math
import os
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Any

from .doctor import diagnose_database
from .export import FORMAT_NAME, FORMAT_VERSION
from .memory import MemoryError, MemoryStore
from .models import (
    Emotion,
    Growth,
    GrowthMetrics,
    PersonalityState,
    Profile,
    Relationship,
    clean_text,
    record,
    safe_output,
)

EXIT_OK = 0
EXIT_INVALID = 1
MAX_EXPORT_BYTES = 20 * 1024 * 1024

_STATE_TYPES = {
    "growth": Growth,
    "growth_metrics": GrowthMetrics,
    "relationship": Relationship,
    "emotion": Emotion,
    "personality": PersonalityState,
}


def _default_data_dir() -> Path:
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"隐私导出中的 {label} 格式无效。")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"隐私导出中的 {label} 格式无效。")
    return value


def _export_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValueError(f"隐私导出中的 {label} ID 无效。")
    return value


def _validate_state(key: str, value: Any) -> Any:
    cls = _STATE_TYPES.get(key)
    if cls is None:
        raise ValueError(f"隐私导出包含当前版本不支持的状态：{key}。")
    data = _as_object(value, f"baby.state.{key}")
    names = {field.name for field in fields(cls)}
    if set(data) != names:
        raise ValueError(f"隐私导出中的 {key} 状态字段不完整或不受支持。")

    defaults = record(cls())
    for name, item in data.items():
        expected = defaults[name]
        if isinstance(expected, (int, float)):
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                or item < 0
            ):
                raise ValueError(f"隐私导出中的 {key}.{name} 数值无效。")
        elif not isinstance(item, str):
            raise ValueError(f"隐私导出中的 {key}.{name} 文本无效。")

    if key in {"relationship", "personality"} and any(item > 100 for item in data.values()):
        raise ValueError(f"隐私导出中的 {key} 数值超出范围。")
    if key == "emotion" and (
        data["label"] not in {"calm", "happy", "curious", "sad", "playful", "nervous", "annoyed"}
        or data["intensity"] > 1
    ):
        raise ValueError("隐私导出中的 emotion 状态无效。")
    if key == "growth" and data["stage"] not in {
        "newborn",
        "baby",
        "child",
        "growing",
        "mature",
    }:
        raise ValueError("隐私导出中的 growth.stage 无效。")
    return cls(**data)


def load_privacy_export(source: Path) -> dict[str, Any]:
    """Read and validate a portable default privacy export without creating a database."""
    source = source.expanduser()
    if not source.is_file():
        raise ValueError("隐私导出文件不存在或不是普通文件。")
    try:
        if source.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("隐私导出文件过大；当前版本最多导入 20 MiB。")
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError("无法读取隐私导出文件。") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("隐私导出不是有效 JSON。") from exc

    payload = _as_object(payload, "根对象")
    if payload.get("format") != FORMAT_NAME or payload.get("format_version") != FORMAT_VERSION:
        raise ValueError("不支持这个隐私导出格式或版本。")

    options = _as_object(payload.get("options"), "options")
    if options.get("include_history") is not False or options.get("include_inactive") is not False:
        raise ValueError(
            "导入仅接受默认隐私导出；请重新导出且不要使用 --include-history 或 --include-inactive。"
        )
    if "history" in payload:
        raise ValueError("默认隐私导出不应包含聊天历史；已拒绝导入。")

    profile_payload = payload.get("profile")
    profile = None
    if profile_payload is not None:
        profile_data = _as_object(profile_payload, "profile")
        try:
            profile = Profile.create(
                profile_data["name"], profile_data["gender"], profile_data["address"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("隐私导出中的 profile 无效。") from exc

    baby = _as_object(payload.get("baby"), "baby")
    try:
        baby_name = clean_text(baby["name"], 80)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("隐私导出中的宝宝名字无效。") from exc
    state_payload = _as_object(baby.get("state"), "baby.state")
    states = {key: _validate_state(key, value) for key, value in state_payload.items()}

    facts: list[dict[str, Any]] = []
    seen_fact_ids: set[int] = set()
    for raw in _as_list(payload.get("facts"), "facts"):
        item = _as_object(raw, "facts 项")
        old_id = _export_id(item.get("id"), "fact")
        if old_id in seen_fact_ids:
            raise ValueError("隐私导出包含重复 fact ID。")
        seen_fact_ids.add(old_id)
        if item.get("active") != 1 or isinstance(item.get("active"), bool):
            raise ValueError("默认隐私导出只能包含有效 facts。")
        try:
            fact = {
                "id": old_id,
                "kind": clean_text(item["kind"], 500),
                "subject": clean_text(item["subject"], 500),
                "predicate": clean_text(item["predicate"], 500),
                "value": clean_text(item["value"], 500),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("隐私导出包含无效 fact。") from exc
        facts.append(fact)

    episodes: list[dict[str, Any]] = []
    seen_episode_ids: set[int] = set()
    for raw in _as_list(payload.get("episodes"), "episodes"):
        item = _as_object(raw, "episodes 项")
        old_id = _export_id(item.get("id"), "episode")
        if old_id in seen_episode_ids:
            raise ValueError("隐私导出包含重复 episode ID。")
        seen_episode_ids.add(old_id)
        if item.get("active") != 1 or isinstance(item.get("active"), bool):
            raise ValueError("默认隐私导出只能包含有效 episodes。")
        importance = item.get("importance")
        if (
            isinstance(importance, bool)
            or not isinstance(importance, (int, float))
            or not math.isfinite(importance)
            or not 0 <= importance <= 1
        ):
            raise ValueError("隐私导出包含无效 episode importance。")
        fact_id = item.get("fact_id")
        if fact_id is not None:
            fact_id = _export_id(fact_id, "episode fact")
        try:
            episode = {
                "id": old_id,
                "kind": clean_text(item["kind"], 80),
                "summary": clean_text(item["summary"], 500),
                "importance": float(importance),
                "fact_id": fact_id,
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("隐私导出包含无效 episode。") from exc
        episodes.append(episode)

    return {
        "profile": profile,
        "baby_name": baby_name,
        "states": states,
        "facts": facts,
        "episodes": episodes,
    }


def _cleanup_database(database: Path) -> None:
    for candidate in (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
    ):
        candidate.unlink(missing_ok=True)


def import_privacy_export(source: Path, data_dir: Path) -> dict[str, Any]:
    """Create one new database from visible active data; never overwrite an existing baby."""
    portable = load_privacy_export(source)
    data_dir = data_dir.expanduser()
    database = data_dir / "baby.sqlite3"
    if os.path.lexists(database):
        raise ValueError("目标数据目录已经包含 baby.sqlite3；为避免覆盖，导入已拒绝。")

    memory: MemoryStore | None = None
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        memory = MemoryStore(database)
        fact_ids: dict[int, int] = {}
        with memory.transaction():
            if portable["profile"] is not None:
                memory.save_profile(portable["profile"])
            memory.set_setting("baby_name", portable["baby_name"])
            for key, state in portable["states"].items():
                memory.save_state(key, state)

            for fact in portable["facts"]:
                memory.learn(fact["kind"], fact["subject"], fact["predicate"], fact["value"])
                row = memory.db.execute(
                    "SELECT id FROM facts WHERE kind=? AND subject=? AND predicate=? "
                    "AND normalized=? AND active=1 ORDER BY id DESC LIMIT 1",
                    (
                        fact["kind"],
                        fact["subject"],
                        fact["predicate"],
                        memory.normalize(fact["value"]),
                    ),
                ).fetchone()
                if row is None:
                    raise ValueError("无法重建导出的 fact；目标数据库未保留。")
                fact_ids[fact["id"]] = row["id"]

            for episode in portable["episodes"]:
                old_fact_id = episode["fact_id"]
                new_fact_id = None
                if old_fact_id is not None:
                    new_fact_id = fact_ids.get(old_fact_id)
                    if new_fact_id is None:
                        raise ValueError("episode 引用了未包含在默认隐私导出中的 fact。")
                memory.episode(
                    episode["kind"],
                    episode["summary"],
                    episode["importance"],
                    new_fact_id,
                )
        memory.close()
        memory = None

        report = diagnose_database(database)
        if report["status"] != "ok":
            raise MemoryError("导入后的数据库未通过完整性检查；目标数据库未保留。")
        return {
            "status": "ok",
            "database": str(database),
            "facts": len(portable["facts"]),
            "episodes": len(portable["episodes"]),
            "profile_imported": portable["profile"] is not None,
            "schema_version": report["schema_version"],
        }
    except BaseException:
        if memory is not None:
            memory.close()
        _cleanup_database(database)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "将默认 ai-baby-privacy-export v1 中的可见有效数据导入一个全新的 AI Baby 数据目录"
        )
    )
    parser.add_argument("source", type=Path, help="由 ai-baby-export 默认模式生成的 JSON 文件")
    parser.add_argument("--data-dir", type=Path, help="新的宝宝数据目录；绝不覆盖已有 baby.sqlite3")
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，便于脚本和 CI 使用")
    args = parser.parse_args(argv)

    try:
        result = import_privacy_export(args.source, args.data_dir or _default_data_dir())
    except (MemoryError, ValueError) as exc:
        message = str(exc)
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(safe_output(message))
        return EXIT_INVALID
    except (OSError, sqlite3.Error):
        message = "无法读取导出文件或创建目标数据库；请检查路径、磁盘和权限。"
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return EXIT_INVALID

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("隐私导入完成：" + safe_output(str(result["database"])))
        print(f"facts={result['facts']} episodes={result['episodes']}")
        print("这是一个新的可继续使用的数据库；原导出文件和任何已有宝宝均未修改。")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
