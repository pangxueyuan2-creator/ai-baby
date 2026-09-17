
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK(gender IN ('male','female','other')),
    address TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL,
    predicate TEXT NOT NULL, value TEXT NOT NULL, normalized TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user', active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, subject, predicate, normalized)
);
CREATE TABLE IF NOT EXISTS fact_tokens (
    token TEXT NOT NULL, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    PRIMARY KEY(token, fact_id)
);
CREATE INDEX IF NOT EXISTS facts_active ON facts(active, kind, predicate, id);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
