"""Portable imports retain a character's age and the chronology of active memories."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ai_baby import importer, journal
from ai_baby.baby import Baby
from ai_baby.export import build_privacy_export, write_privacy_export
from ai_baby.importer import import_privacy_export, preflight_privacy_export
from ai_baby.management import forget
from ai_baby.memory import MemoryStore
from ai_baby.privacy_checksum import checksum_manifest_path

BORN = "2020-01-02 03:04:05"


def dated_export(tmp_path):
    database = tmp_path / "source" / "baby.sqlite3"
    memory = MemoryStore(database)
    try:
        baby = Baby(memory)
        baby.born("Synthetic", "other")
        baby.chat("我喜欢橘猫")
        baby.chat("我喜欢草莓")
        with memory.transaction():
            memory.db.execute("UPDATE profile SET created_at=?", (BORN,))
            memory.db.execute("UPDATE facts SET created_at='2020-02-03 04:05:06'")
            memory.db.execute("UPDATE episodes SET created_at='2020-02-04 05:06:07'")
            # IDs reflect recording order, which need not match the events' chronology.
            for summary, age in (("星空 新记录", 2), ("星空 旧记录", 100)):
                memory.episode("important", summary, 0.8)
                created = (datetime.now(timezone.utc) - timedelta(days=age)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                memory.db.execute(
                    "UPDATE episodes SET created_at=? WHERE id=(SELECT max(id) FROM episodes)",
                    (created,),
                )
    finally:
        memory.close()
    output = tmp_path / "portable.json"
    payload = write_privacy_export(database, output)
    return database, output, payload


def all_timestamps(payload):
    return [
        payload["profile"]["created_at"],
        *(fact["created_at"] for fact in payload["facts"]),
        *(episode["created_at"] for episode in payload["episodes"]),
    ]


def write_legacy_payload(output, payload):
    """Edit synthetic portable data, deliberately without a now-stale checksum."""
    checksum_manifest_path(output).unlink()
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_round_trip_retains_birth_and_memory_times_after_reopening(tmp_path):
    database, source, original = dated_export(tmp_path)
    source_bytes = source.read_bytes()
    database_bytes = database.read_bytes()
    target = tmp_path / "imported"

    import_privacy_export(source, target, require_checksum=True)

    restored = build_privacy_export(target / "baby.sqlite3")
    assert all_timestamps(restored) == all_timestamps(original)
    assert source.read_bytes() == source_bytes
    assert database.read_bytes() == database_bytes
    memory = MemoryStore(target / "baby.sqlite3")
    try:
        assert Baby(memory).memory.profile().name == "Synthetic"
        with memory.transaction():
            entry = journal.consolidate(memory, force=True)
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(BORN).replace(tzinfo=timezone.utc)
        ).days + 1
        assert f"出生第 {age} 天" in entry
    finally:
        memory.close()


def test_import_keeps_episode_recency_ranking(tmp_path):
    database, source, _ = dated_export(tmp_path)
    memory = MemoryStore(database)
    try:
        expected = [row["summary"] for row in memory.retrieve_episodes("星空")]
        assert expected == ["星空 新记录", "星空 旧记录"]
    finally:
        memory.close()

    import_privacy_export(source, tmp_path / "imported")
    memory = MemoryStore(tmp_path / "imported" / "baby.sqlite3")
    try:
        assert [row["summary"] for row in memory.retrieve_episodes("星空")] == expected
    finally:
        memory.close()


@pytest.mark.parametrize(
    "section,value",
    [
        ("profile", None),
        ("profile", True),
        ("profile", "2026-01-01"),
        ("facts", "2026-02-30 12:00:00"),
        ("facts", "2026-01-01T00:00:00+00:99"),
        ("facts", ""),
        ("episodes", "not-a-time"),
        ("episodes", "0001-01-01T00:00:00+01:00"),
    ],
)
def test_bad_timestamp_rejected_before_creating_destination(tmp_path, section, value):
    _, source, payload = dated_export(tmp_path)
    record = payload[section] if section == "profile" else payload[section][0]
    record["created_at"] = value
    write_legacy_payload(source, payload)
    original = source.read_bytes()
    target = tmp_path / "must-not-exist"

    with pytest.raises(ValueError):
        preflight_privacy_export(source)
    with pytest.raises(ValueError):
        import_privacy_export(source, target)

    assert not target.exists()
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "timestamp,normalized",
    [
        ("2020-01-02T10:20:30+08:00", "2020-01-02 02:20:30"),
        ("2020-01-02T02:20:30Z", "2020-01-02 02:20:30"),
        ("2020-01-02 02:20:30.123", "2020-01-02 02:20:30.123000"),
    ],
)
def test_supported_iso_timestamps_are_normalized_to_utc(tmp_path, timestamp, normalized):
    _, source, payload = dated_export(tmp_path)
    for record in [payload["profile"], *payload["facts"], *payload["episodes"]]:
        record["created_at"] = timestamp
    write_legacy_payload(source, payload)

    import_privacy_export(source, tmp_path / "imported")

    restored = build_privacy_export(tmp_path / "imported" / "baby.sqlite3")
    assert set(all_timestamps(restored)) == {normalized}


def test_legacy_missing_timestamps_share_one_import_time(tmp_path):
    _, source, payload = dated_export(tmp_path)
    for record in [payload["profile"], *payload["facts"], *payload["episodes"]]:
        del record["created_at"]
    write_legacy_payload(source, payload)
    before = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    assert preflight_privacy_export(source)["status"] == "ok"
    import_privacy_export(source, tmp_path / "imported")

    restored = build_privacy_export(tmp_path / "imported" / "baby.sqlite3")
    dates = set(all_timestamps(restored))
    assert len(dates) == 1
    imported_at = datetime.fromisoformat(dates.pop())
    assert before <= imported_at <= datetime.now(timezone.utc).replace(tzinfo=None)


def test_timestamp_preservation_does_not_revive_forgotten_data(tmp_path):
    database, _, _ = dated_export(tmp_path)
    memory = MemoryStore(database)
    try:
        forgotten = next(fact for fact in memory.facts() if fact.value == "草莓")
        forget(memory, forgotten.id)
    finally:
        memory.close()
    source = tmp_path / "after-forget.json"
    original = write_privacy_export(database, source)

    import_privacy_export(source, tmp_path / "imported", require_checksum=True)

    restored = build_privacy_export(tmp_path / "imported" / "baby.sqlite3")
    assert all_timestamps(restored) == all_timestamps(original)
    assert "草莓" not in json.dumps(restored, ensure_ascii=False)


def test_failure_while_restoring_timestamps_removes_only_new_database(tmp_path, monkeypatch):
    _, source, _ = dated_export(tmp_path)
    original = source.read_bytes()
    base_store = importer.MemoryStore

    class FailTimestampStore(base_store):
        def __init__(self, path):
            super().__init__(path)
            self.db.execute(
                "CREATE TRIGGER fail_timestamp BEFORE UPDATE OF created_at ON episodes "
                "BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END"
            )

    monkeypatch.setattr(importer, "MemoryStore", FailTimestampStore)
    target = tmp_path / "failed"
    with pytest.raises(sqlite3.IntegrityError, match="synthetic disk failure"):
        import_privacy_export(source, target)
    assert not (target / "baby.sqlite3").exists()
    assert source.read_bytes() == original
