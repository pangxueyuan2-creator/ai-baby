"""Preserve revoked request identities and retire superseded recall evidence."""

import sqlite3


def upgrade(db: sqlite3.Connection) -> None:
    """Run under the migration owner's transaction; v1/v2 migrations remain frozen."""
    db.execute(
        "ALTER TABLE turn_receipts ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0 "
        "CHECK(revoked IN (0,1))"
    )
    db.execute("CREATE INDEX episodes_fact ON episodes(fact_id,active)")
    db.execute("CREATE INDEX episodes_active_id ON episodes(active,id)")
    db.execute("CREATE INDEX curiosity_fact ON curiosity(fact_id,status)")
    maximum = db.execute("SELECT coalesce(max(id),0) FROM candidates").fetchone()[0]
    previous = db.execute("SELECT value FROM settings WHERE key='candidate_sequence'").fetchone()
    sequence = max(maximum, int(previous[0]) if previous else 0)
    db.execute("INSERT OR REPLACE INTO settings VALUES('candidate_sequence',?)", (str(sequence),))
    db.execute(
        "UPDATE episodes SET active=0 WHERE active=1 AND fact_id IN "
        "(SELECT id FROM facts WHERE active=0)"
    )
    db.execute(
        "UPDATE curiosity SET status='ignored',question='' WHERE fact_id IN "
        "(SELECT id FROM facts WHERE active=0)"
    )
