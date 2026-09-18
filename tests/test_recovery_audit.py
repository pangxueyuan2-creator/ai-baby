"""Recovery-readiness audit exercises only temporary fictional databases."""

import json

from ai_baby.backup import backup_open_store
from ai_baby.recovery_audit import EXIT_NOT_READY, EXIT_OK, audit_recovery_readiness, main


def _verified_backup(store, tmp_path, name="baby-verified.sqlite3"):
    destination = tmp_path / "backups" / name
    backup_open_store(store, destination)
    return destination


def test_recovery_audit_proves_verified_backup_is_restorable(store, tmp_path):
    backup = _verified_backup(store, tmp_path)
    before = backup.read_bytes()

    report = audit_recovery_readiness(tmp_path, require_checksum=True)

    assert report["status"] == "ok"
    assert report["backup_summary"] == {
        "checked": 1,
        "recoverable": 1,
        "invalid": 0,
        "orphan_manifests": 0,
    }
    assert report["backups"] == [
        {
            "name": backup.name,
            "status": "ok",
            "checksum_present": True,
            "source_schema_version": 3,
            "target_schema_version": 3,
            "migration_required": False,
        }
    ]
    assert backup.read_bytes() == before


def test_recovery_audit_detects_tampered_backup_before_restore(store, tmp_path):
    backup = _verified_backup(store, tmp_path)
    with backup.open("ab") as stream:
        stream.write(b"tampered")

    report = audit_recovery_readiness(tmp_path, require_checksum=True)

    assert report["status"] == "error"
    assert report["backup_summary"]["invalid"] == 1
    assert report["backups"][0]["status"] == "error"
    assert "SHA-256" in report["backups"][0]["message"]


def test_recovery_audit_can_flag_legacy_backup_only_under_strict_policy(store, tmp_path):
    backup = tmp_path / "backups" / "legacy.sqlite3"
    store.backup(backup)

    compatible = audit_recovery_readiness(tmp_path)
    strict = audit_recovery_readiness(tmp_path, require_checksum=True)

    assert compatible["status"] == "ok"
    assert compatible["backups"][0]["checksum_present"] is False
    assert strict["status"] == "error"
    assert strict["backups"][0]["status"] == "error"
    assert "SHA-256" in strict["backups"][0]["message"]


def test_recovery_audit_reports_missing_backups_and_orphan_manifests(store, tmp_path):
    empty = audit_recovery_readiness(tmp_path)
    assert empty["status"] == "no_backups"
    assert empty["backup_summary"]["checked"] == 0

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "orphan.sqlite3.sha256").write_text("deadbeef\n", encoding="ascii")
    orphaned = audit_recovery_readiness(tmp_path)
    assert orphaned["status"] == "error"
    assert orphaned["orphan_manifests"] == ["orphan.sqlite3.sha256"]


def test_recovery_audit_json_cli_is_provider_independent(store, tmp_path, monkeypatch, capsys):
    _verified_backup(store, tmp_path)
    monkeypatch.setenv("AI_BABY_PROVIDER", "definitely-not-a-provider")
    monkeypatch.setenv("AI_BABY_API_KEY", "must-not-be-read")

    code = main(["--data-dir", str(tmp_path), "--require-checksum", "--json"])

    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["backup_summary"]["recoverable"] == 1
    assert "must-not-be-read" not in json.dumps(payload, ensure_ascii=False)


def test_recovery_audit_cli_returns_not_ready_without_backup(store, tmp_path, capsys):
    code = main(["--data-dir", str(tmp_path), "--json"])

    assert code == EXIT_NOT_READY
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "no_backups"
