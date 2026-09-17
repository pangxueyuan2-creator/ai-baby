-- Frozen schema v2 from a500a76; generated empty fixture, no user data.
BEGIN TRANSACTION;
CREATE TABLE candidates(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE curiosity(topic TEXT PRIMARY KEY, fact_id INTEGER REFERENCES facts(id), question TEXT NOT NULL, asked_turn INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','answered','ignored')));
CREATE TABLE episode_tokens(token TEXT NOT NULL, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE, PRIMARY KEY(token,episode_id));
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
, importance REAL NOT NULL DEFAULT 0 CHECK(importance BETWEEN 0 AND 1), active INTEGER NOT NULL DEFAULT 1, fact_id INTEGER REFERENCES facts(id));
CREATE TABLE experience(category TEXT NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(category,signature));
CREATE TABLE fact_tokens (
    token TEXT NOT NULL, fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    PRIMARY KEY(token, fact_id)
);
CREATE TABLE facts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL,
    predicate TEXT NOT NULL, value TEXT NOT NULL, normalized TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user', active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, novelty TEXT NOT NULL DEFAULT '',
    UNIQUE(kind, subject, predicate, normalized)
);
CREATE TABLE journals(id INTEGER PRIMARY KEY, through_episode INTEGER NOT NULL, through_turn INTEGER NOT NULL, summary TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(through_episode,through_turn));
CREATE TABLE messages (
    id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE profile (
    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK(gender IN ('male','female','other')),
    address TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE revision(id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL);
INSERT INTO "revision" VALUES(1,0);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "settings" VALUES('baby_name','AI 宝宝');
CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "state" VALUES('personality','{"curiosity": 70.0, "confidence": 50.0, "sociability": 50.0, "caution": 50.0, "playfulness": 50.0, "independence": 50.0, "patience": 50.0, "openness": 50.0}');
CREATE TABLE turn_receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL, answer TEXT NOT NULL, warning TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX facts_active ON facts(active, kind, predicate, id);
CREATE INDEX facts_novelty ON facts(active,kind,novelty);
CREATE INDEX episodes_rank ON episodes(active,importance,id);
CREATE TRIGGER revision_profile_insert AFTER INSERT ON profile BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_profile_update AFTER UPDATE ON profile BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_profile_delete AFTER DELETE ON profile BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_facts_insert AFTER INSERT ON facts BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_facts_update AFTER UPDATE ON facts BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_facts_delete AFTER DELETE ON facts BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_episodes_insert AFTER INSERT ON episodes BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_episodes_update AFTER UPDATE ON episodes BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_episodes_delete AFTER DELETE ON episodes BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_messages_insert AFTER INSERT ON messages BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_messages_update AFTER UPDATE ON messages BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_messages_delete AFTER DELETE ON messages BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_state_insert AFTER INSERT ON state BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_state_update AFTER UPDATE ON state BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_state_delete AFTER DELETE ON state BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_candidates_insert AFTER INSERT ON candidates BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_candidates_update AFTER UPDATE ON candidates BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_candidates_delete AFTER DELETE ON candidates BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_journals_insert AFTER INSERT ON journals BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_journals_update AFTER UPDATE ON journals BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_journals_delete AFTER DELETE ON journals BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_curiosity_insert AFTER INSERT ON curiosity BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_curiosity_update AFTER UPDATE ON curiosity BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_curiosity_delete AFTER DELETE ON curiosity BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_experience_insert AFTER INSERT ON experience BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_experience_update AFTER UPDATE ON experience BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_experience_delete AFTER DELETE ON experience BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_settings_insert AFTER INSERT ON settings BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_settings_update AFTER UPDATE ON settings BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
CREATE TRIGGER revision_settings_delete AFTER DELETE ON settings BEGIN UPDATE revision SET value=value+1 WHERE id=1; END;
COMMIT;
PRAGMA user_version=2;
