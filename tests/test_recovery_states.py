"""Recovery must reject unreadable character states, even with a matching checksum."""

import json
import sqlite3
import traceback
from contextlib import closing
from pathlib import Path

import pytest

from ai_baby import restore as restore_module
from ai_baby.baby import Baby
from ai_baby.backup import (
    backup_database,
    verify_backup,
    verify_checksum_manifest,
    write_checksum_manifest,
)
from ai_baby.doctor import diagnose_database
from ai_baby.memory import MemoryError, MemoryStore
from ai_baby.models import (
    Emotion,
    Growth,
    GrowthMetrics,
    PersonalityState,
    Profile,
    Relationship,
    record,
)
from ai_baby.recovery_audit import audit_recovery_readiness
from ai_baby.restore import check_restore_backup, restore_backup

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "private-state-canary-do-not-print"
STATE_CLASSES = {
    "growth": Growth,
    "growth_metrics": GrowthMetrics,
    "relationship": Relationship,
    "emotion": Emotion,
    "personality": PersonalityState,
}


@pytest.mark.parametrize(
    "key,serialized",
    [
        pytest.param("growth", '{"' + PRIVATE + '":', id="malformed-json"),
        pytest.param("growth", "[" * 2000 + "0" + "]" * 2000, id="excessive-json-nesting"),
        pytest.param("growth", "{}", id="missing-fields"),
        pytest.param(
            "growth", json.dumps({**record(Growth()), PRIVATE: "extra"}), id="extra-field"
        ),
        pytest.param("relationship", "[]", id="non-object"),
        pytest.param("growth", json.dumps(record(Growth(stage=PRIVATE))), id="invalid-stage"),
        pytest.param(
            "growth", json.dumps(record(Growth(interactions=PRIVATE))), id="numeric-string"
        ),
        pytest.param("growth", json.dumps(record(Growth(interactions=True))), id="boolean"),
        pytest.param(
            "growth_metrics", json.dumps(record(GrowthMetrics(active_seconds=-1))), id="negative"
        ),
        pytest.param(
            "growth_metrics",
            json.dumps(record(GrowthMetrics(relationship_depth=float("nan")))),
            id="nan",
        ),
        pytest.param(
            "relationship", json.dumps(record(Relationship(trust=float("inf")))), id="infinity"
        ),
        pytest.param(
            "relationship", json.dumps(record(Relationship(trust=100.01))), id="relationship-range"
        ),
        pytest.param(
            "personality",
            json.dumps(record(PersonalityState(curiosity=100.01))),
            id="personality-range",
        ),
        pytest.param("emotion", json.dumps(record(Emotion(label=PRIVATE))), id="emotion-label"),
        pytest.param("emotion", json.dumps(record(Emotion(intensity=1.01))), id="emotion-range"),
    ],
)
def test_doctor_rejects_the_same_invalid_state_as_chat_without_writing(store, key, serialized):
    store.db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, serialized))
    before = store.path.read_bytes()

    with pytest.raises(MemoryError) as error:
        store.load_state(key, STATE_CLASSES[key])
    assert PRIVATE not in "".join(traceback.format_exception(error.value))

    report = diagnose_database(store.path)

    assert report["status"] == "error"
    assert report["code"] == "state_invalid"
    assert report["counts"] is None
    assert PRIVATE not in json.dumps(report)
    assert store.path.read_bytes() == before
    assert (
        store.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()[0] == serialized
    )


def test_verified_backup_creation_rejects_invalid_state_before_allocating_output(store, tmp_path):
    store.db.execute("INSERT INTO state VALUES('growth','{}')")
    before = store.path.read_bytes()
    destination = tmp_path / "new-backup-directory" / "backup.sqlite3"

    with pytest.raises(MemoryError):
        backup_database(store.path, destination)

    assert not destination.parent.exists()
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("operation", ["verify", "check", "restore"])
def test_matching_checksum_does_not_make_invalid_state_restorable(store, tmp_path, operation):
    store.save_state("growth", Growth(stage=PRIVATE))
    backup = tmp_path / "bad-state.sqlite3"
    store.backup(backup)
    manifest, digest = write_checksum_manifest(backup)
    assert verify_checksum_manifest(backup, required=True) == digest
    before, manifest_before = backup.read_bytes(), manifest.read_bytes()
    destination = tmp_path / "must-not-create"

    with pytest.raises(MemoryError) as error:
        if operation == "verify":
            verify_backup(backup, require_checksum=True)
        elif operation == "check":
            check_restore_backup(backup, require_checksum=True)
        else:
            restore_backup(backup, destination, require_checksum=True)

    assert PRIVATE not in "".join(traceback.format_exception(error.value))
    assert not destination.exists()
    assert backup.read_bytes() == before
    assert manifest.read_bytes() == manifest_before


@pytest.mark.parametrize("operation", ["check", "restore"])
def test_invalid_v2_state_is_rejected_after_staged_migration_and_stage_is_closed(
    tmp_path, monkeypatch, operation
):
    backup = tmp_path / "v2.sqlite3"
    with closing(sqlite3.connect(backup)) as db:
        db.executescript((ROOT / "tests/fixtures/v2.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO state VALUES('growth','{}')")
        db.commit()
    before = backup.read_bytes()
    assert diagnose_database(backup)["status"] == "upgrade_required"
    opened = []

    class ObservedStore(MemoryStore):
        def __init__(self, path):
            super().__init__(path)
            opened.append((self, self.db.execute("PRAGMA user_version").fetchone()[0]))

    monkeypatch.setattr(restore_module, "MemoryStore", ObservedStore)
    destination = tmp_path / "must-not-create"
    with pytest.raises(MemoryError):
        if operation == "check":
            check_restore_backup(backup)
        else:
            restore_backup(backup, destination)

    assert len(opened) == 1 and opened[0][1] == 3
    assert opened[0][0].connection is None
    assert not destination.exists()
    assert backup.read_bytes() == before
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("present", [False, True], ids=["missing-defaults", "persisted-states"])
def test_valid_or_missing_states_and_unknown_extension_survive_recovery(store, tmp_path, present):
    profile = Profile.create("Fixture", "female")
    store.save_profile(profile)
    store.db.execute("DELETE FROM state")
    store.db.execute("INSERT INTO state VALUES('future_extension','opaque non-JSON value')")
    expected = {
        "growth": Growth(interactions=4, stage="baby"),
        "growth_metrics": GrowthMetrics(world_knowledge=2),
        "relationship": Relationship(trust=45),
        "emotion": Emotion(label="happy", intensity=0.7),
        "personality": PersonalityState(curiosity=75),
    }
    if present:
        for key, value in expected.items():
            store.save_state(key, value)
    before = store.path.read_bytes()
    rows = [tuple(row) for row in store.db.execute("SELECT * FROM state ORDER BY key")]
    assert diagnose_database(store.path)["status"] == "ok"
    backup = tmp_path / "valid-backup.sqlite3"
    backup_database(store.path, backup)
    assert verify_backup(backup, require_checksum=True)["status"] == "ok"
    assert check_restore_backup(backup, require_checksum=True)["status"] == "ok"
    target = restore_backup(backup, tmp_path / "restored", require_checksum=True)
    assert store.path.read_bytes() == before

    restored = MemoryStore(target)
    try:
        assert restored.profile() == profile
        for key, cls in STATE_CLASSES.items():
            assert restored.load_state(key, cls) == (expected[key] if present else cls())
        assert [
            tuple(row) for row in restored.db.execute("SELECT * FROM state ORDER BY key")
        ] == rows
        assert Baby(restored).chat("你好").text
    finally:
        restored.close()


def test_existing_numeric_state_compatibility_is_not_tightened(store):
    # The existing decoder accepts finite nonnegative numeric counts and no upper score bound.
    store.save_state("growth", Growth(interactions=2.5, score=150))
    store.save_state("growth_metrics", GrowthMetrics(world_knowledge=1.5, relationship_depth=2))

    assert store.load_state("growth", Growth) == Growth(interactions=2.5, score=150)
    assert store.load_state("growth_metrics", GrowthMetrics) == GrowthMetrics(
        world_knowledge=1.5, relationship_depth=2
    )
    assert diagnose_database(store.path)["status"] == "ok"


def test_recovery_audit_refuses_bad_live_state_and_checksummed_backup(store, tmp_path):
    store.db.execute("INSERT INTO state VALUES('growth','{}')")
    backup = tmp_path / "backups" / "invalid.sqlite3"
    store.backup(backup)
    write_checksum_manifest(backup)

    report = audit_recovery_readiness(tmp_path, require_checksum=True)

    assert report["status"] == "error"
    assert report["current_database"]["code"] == "state_invalid"
    assert report["backup_summary"]["recoverable"] == 0
    assert report["backup_summary"]["invalid"] == 1
