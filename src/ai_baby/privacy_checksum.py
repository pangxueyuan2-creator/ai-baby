"""Checksum sidecars for portable privacy exports."""

import hashlib
import hmac
from pathlib import Path

from .storage_files import reserve_private_file

_CHUNK_SIZE = 1024 * 1024
_MAX_MANIFEST_BYTES = 512


def checksum_manifest_path(export: Path) -> Path:
    """Return the adjacent SHA-256 sidecar path for a privacy export."""
    return export.with_name(export.name + ".sha256")


def sha256_file(path: Path) -> str:
    """Hash a file without loading the full privacy export into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum_manifest(export: Path) -> tuple[Path, str]:
    """Exclusively create an owner-private checksum sidecar for an export."""
    digest = sha256_file(export)
    manifest = checksum_manifest_path(export)
    try:
        reserve_private_file(manifest)
    except FileExistsError as exc:
        raise ValueError(
            "隐私导出 SHA-256 校验文件已存在；为避免覆盖私人数据，导出已拒绝。"
        ) from exc
    try:
        with manifest.open("w", encoding="ascii", newline="\n") as output:
            output.write(f"{digest}  {export.name}\n")
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    return manifest, digest


def _manifest_checksum(export: Path, *, required: bool) -> str | None:
    manifest = checksum_manifest_path(export)
    if not manifest.exists():
        if required:
            raise ValueError("隐私导出缺少 SHA-256 校验文件。")
        return None
    if not manifest.is_file():
        raise ValueError("隐私导出 SHA-256 校验路径不是普通文件。")
    try:
        if manifest.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("隐私导出 SHA-256 校验文件格式无效。")
        lines = manifest.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("无法读取隐私导出 SHA-256 校验文件。") from exc
    if len(lines) != 1:
        raise ValueError("隐私导出 SHA-256 校验文件格式无效。")
    expected, separator, filename = lines[0].partition("  ")
    if (
        separator != "  "
        or filename != export.name
        or len(expected) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in expected)
    ):
        raise ValueError("隐私导出 SHA-256 校验文件格式无效。")
    return expected.casefold()


def verify_checksum_manifest(
    export: Path,
    *,
    required: bool = False,
    content: bytes | None = None,
) -> str | None:
    """Verify the sidecar against supplied bytes or the file currently on disk."""
    expected = _manifest_checksum(export, required=required)
    if expected is None:
        return None
    if content is None:
        try:
            actual = sha256_file(export)
        except OSError as exc:
            raise ValueError("无法读取隐私导出文件以验证 SHA-256。") from exc
    else:
        actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError("隐私导出 SHA-256 校验失败；文件可能损坏或已被修改。")
    return actual
