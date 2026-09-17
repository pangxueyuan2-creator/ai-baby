"""Generate a privacy-safe diagnostic bundle for bug reports and support."""

import argparse
import hashlib
import json
import os
import platform
import sqlite3
from pathlib import Path
from typing import Any

from . import __version__
from .doctor import diagnose_database
from .models import safe_output
from .storage_files import reserve_private_file

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_UPGRADE_REQUIRED = 3
FORMAT_NAME = "ai-baby-support-bundle"
FORMAT_VERSION = 1


def _default_data_dir() -> Path:
    """Match the app default without loading provider configuration."""
    return Path(os.environ.get("AI_BABY_DATA_DIR", str(Path.home() / ".ai-baby"))).expanduser()


def _public_database_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove filesystem paths and free-form text from doctor output."""
    return {
        "status": report["status"],
        "code": report["code"],
        "schema_version": report["schema_version"],
        "target_schema_version": report["target_schema_version"],
        "integrity_check": report["integrity_check"],
        "counts": report["counts"],
    }


def build_support_bundle(database: Path, *, full: bool = False) -> dict[str, Any]:
    """Build diagnostics without reading user content or mutating the database."""
    report = diagnose_database(database, full=full)
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "database": _public_database_report(report),
        "privacy": {
            "content_included": False,
            "paths_included": False,
            "provider_configuration_included": False,
        },
    }


def _checksum_path(output: Path) -> Path:
    return output.with_name(output.name + ".sha256")


def _write_checksum(output: Path) -> tuple[Path, str]:
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = _checksum_path(output)
    try:
        reserve_private_file(manifest)
    except FileExistsError as exc:
        raise ValueError("支持包校验文件已存在；为避免覆盖已有文件，操作已拒绝。") from exc
    try:
        with manifest.open("w", encoding="ascii", newline="\n") as stream:
            stream.write(f"{digest}  {output.name}\n")
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    return manifest, digest


def write_support_bundle(
    database: Path,
    output: Path,
    *,
    full: bool = False,
    pretty: bool = True,
) -> dict[str, Any]:
    """Exclusively create a private support JSON plus checksum sidecar."""
    output = output.expanduser()
    payload = build_support_bundle(database.expanduser(), full=full)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        reserve_private_file(output)
    except FileExistsError as exc:
        raise ValueError("支持包目标已存在；为避免覆盖已有文件，操作已拒绝。") from exc

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
        manifest, digest = _write_checksum(output)
    except BaseException:
        output.unlink(missing_ok=True)
        raise

    payload["artifact"] = {
        "output": str(output),
        "checksum_manifest": str(manifest),
        "sha256": digest,
    }
    return payload


def _exit_code(status: str) -> int:
    if status == "ok":
        return EXIT_OK
    if status == "upgrade_required":
        return EXIT_UPGRADE_REQUIRED
    return EXIT_UNHEALTHY


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "生成不含聊天、记忆正文、资料值、绝对数据库路径或 Provider 配置的诊断支持包"
        )
    )
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--data-dir", type=Path, help="宝宝数据目录；检查其中 baby.sqlite3")
    location.add_argument("--database", type=Path, help="直接检查指定 AI Baby SQLite 文件")
    parser.add_argument("--output", type=Path, required=True, help="新 JSON 文件路径；绝不覆盖已有文件")
    parser.add_argument(
        "--full",
        action="store_true",
        help="使用较慢的 SQLite integrity_check；默认使用 quick_check",
    )
    parser.add_argument("--compact", action="store_true", help="输出紧凑 JSON 文件")
    parser.add_argument("--json", action="store_true", help="CLI 状态输出稳定 JSON")
    args = parser.parse_args(argv)

    database = args.database or (args.data_dir or _default_data_dir()) / "baby.sqlite3"
    try:
        payload = write_support_bundle(
            database,
            args.output,
            full=args.full,
            pretty=not args.compact,
        )
    except ValueError as exc:
        message = str(exc)
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(safe_output(message))
        return EXIT_UNHEALTHY
    except (OSError, sqlite3.Error):
        message = "无法创建支持包；请检查输出路径、磁盘和权限。"
        if args.json:
            print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return EXIT_UNHEALTHY

    database_report = payload["database"]
    result = {
        "status": database_report["status"],
        "code": database_report["code"],
        "output": payload["artifact"]["output"],
        "checksum_manifest": payload["artifact"]["checksum_manifest"],
        "sha256": payload["artifact"]["sha256"],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("支持包已生成：" + safe_output(result["output"]))
        print("数据库状态：" + str(result["status"]) + " / " + str(result["code"]))
        print("SHA-256：" + str(result["sha256"]))
        print("内容保护：不包含聊天、记忆正文、资料值、绝对数据库路径或 Provider 配置。")
    return _exit_code(str(database_report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
