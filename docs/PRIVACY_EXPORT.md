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

Every newly written export is paired with an adjacent SHA-256 sidecar such as `baby-export.json.sha256`. The sidecar is created with the same exclusive-create and owner-private behavior as the JSON file. Move or copy the JSON and its `.sha256` file together when transferring an export between machines.

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

## Integrity and portability

`ai-baby-import` automatically verifies the adjacent `.sha256` file when one is present, before parsing the JSON or creating a destination database. For CI or cross-machine migrations, require a checksum explicitly:

```bash
ai-baby-import ./baby-export.json --check --require-checksum
```

Exports produced before checksum sidecars were introduced remain accepted by default for backward compatibility. `--require-checksum` turns a missing sidecar into an error. A mismatched or malformed sidecar is always rejected when present.

The checksum protects against accidental corruption or modification in transit; it is not a digital signature and does not prove who created the export. Treat privacy exports as sensitive local data even when the checksum verifies.

## Safety guarantees

- The SQLite source is opened with `mode=ro` and `PRAGMA query_only=ON`.
- The current schema must pass integrity, schema, and foreign-key checks before export.
- Databases requiring migration are rejected instead of being modified by the exporter.
- The exporter does not import provider configuration, call a model, or access the network.
- The JSON and checksum sidecar use exclusive-create semantics and never overwrite existing files.
- On POSIX systems both new files are created owner-only (`0600`); on Windows they inherit the directory ACL.
- If checksum creation fails, the newly-created JSON is removed while any pre-existing sidecar is left untouched.

For a recoverable backup use `ai-baby-backup`; for a read-only database diagnosis use `ai-baby-doctor`.
