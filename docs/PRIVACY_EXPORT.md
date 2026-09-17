# Privacy export

`ai-baby-export` creates a versioned JSON export of the user-visible data stored in an AI Baby SQLite database. It is designed for inspection, data portability work, support, and privacy review without opening the database through the normal chat/provider stack.

## Default behavior

```bash
ai-baby-export --data-dir ~/.ai-baby --output ~/baby-export.json --pretty
```

The command opens `baby.sqlite3` read-only, validates the current database with the same health checks used by `ai-baby-doctor`, and then exports:

- the authoritative profile;
- the baby name and structured persistent state;
- active learned facts;
- active episodic memories.

The output format is currently `ai-baby-privacy-export` version `1`. Rows are emitted in stable ID/key order and JSON keys are sorted, making exports practical to inspect or diff.

## Sensitive data is opt-in

Raw chat history is deliberately excluded by default. Include it only when you actually need it:

```bash
ai-baby-export \
  --data-dir ~/.ai-baby \
  --output ~/baby-export-with-history.json \
  --include-history
```

`--include-history` adds raw `messages` plus journal summaries, both of which may contain sensitive conversation text.

Superseded or explicitly deactivated facts and episodes are also excluded by default. `--include-inactive` opts them back in. This matters because an old value may contain information the user no longer wants treated as current.

## Internal tables intentionally omitted

The export is not a byte-for-byte backup and is not accepted by `ai-baby-restore`. Use `ai-baby-backup` for disaster recovery.

The privacy export intentionally leaves out implementation data such as token indexes, optimistic-concurrency revisions, replay receipts, candidate staging records, curiosity bookkeeping, and experience signatures. The JSON document records the omitted internal table names so consumers do not mistake it for a complete database image.

## Safety guarantees

- The SQLite source is opened with `mode=ro` and `PRAGMA query_only=ON`.
- The current schema must pass integrity, schema, and foreign-key checks before export.
- Databases requiring migration are rejected instead of being modified by the exporter.
- The exporter does not import provider configuration, call a model, or access the network.
- The output is created with exclusive-create semantics and never overwrites an existing file.
- On POSIX systems the new export is created owner-only (`0600`); on Windows it inherits the directory ACL.
- A failed export removes only the newly reserved incomplete output file.

For a recoverable backup use `ai-baby-backup`; for a read-only database diagnosis use `ai-baby-doctor`.
