# Backup recovery

AI Baby supports two backup paths:

- Interactive `/backup` creates the original consistent SQLite snapshot format.
- `ai-baby-backup` creates a consistent SQLite snapshot plus an adjacent SHA-256 manifest for automated verification.

The verified command does not load a model provider, API key, or chat session, and it reads the source database without migrating it:

```bash
ai-baby-backup --data-dir ~/.ai-baby
```

Choose an explicit destination when backups are managed by another tool:

```bash
ai-baby-backup --data-dir ~/.ai-baby --output /safe/location/baby.sqlite3
```

A verified backup produces two private files:

```text
baby.sqlite3
baby.sqlite3.sha256
```

Validate a backup without changing it:

```bash
ai-baby-backup --verify /safe/location/baby.sqlite3 --require-checksum
```

`--require-checksum` is useful in automation when a missing sidecar should be treated as an error. Without it, verification remains compatible with older `/backup` snapshots that predate checksum manifests.

Restore is intentionally a separate, non-interactive command so recovery never needs a model provider, API key, or chat session:

```bash
ai-baby-restore ~/.ai-baby/backups/baby-20260917T120000000000Z.sqlite3 \
  --data-dir ~/.ai-baby-restored
```

The equivalent module forms work from a source checkout:

```bash
python -m ai_baby.backup --data-dir ~/.ai-baby
python -m ai_baby.restore BACKUP.sqlite3 --data-dir ~/.ai-baby-restored
```

After a successful restore, start the recovered baby explicitly:

```bash
ai-baby --data-dir ~/.ai-baby-restored
```

## Safety properties

Verified backup creation is deliberately conservative:

- The live source is inspected through a read-only SQLite connection.
- Supported older schema versions may be backed up without being migrated in place.
- The destination is created exclusively and never overwrites an existing file.
- The copied database is checked again before the checksum sidecar is written.
- A SHA-256 sidecar is also created exclusively, so an existing manifest is never replaced.
- If verified backup creation fails, the newly created backup file is removed rather than reported as complete.

Restore is deliberately non-destructive:

- If an adjacent `.sha256` manifest exists, its filename and digest are validated before SQLite is opened.
- Legacy backups without a manifest remain restorable for backward compatibility.
- The backup is opened read-only and is never migrated or edited in place.
- SQLite `quick_check` runs before recovery proceeds.
- The backup is copied into a private staging directory first.
- Staged data is opened through `MemoryStore`, so supported older schemas are migrated and the current schema/concurrency metadata are validated before installation.
- Foreign-key integrity is checked after staged migration.
- The final `baby.sqlite3` is created with the same exclusive private-file path used by normal backups.
- If the target data directory already contains `baby.sqlite3`, restore refuses to overwrite it.
- Invalid, corrupt, unsupported, checksum-mismatched, or partially written inputs leave the target without a restored database.

The JSON produced by `/export` is a readable data export and is **not** a database restore format.

## Recommended recovery flow

1. Keep the original damaged data directory unchanged.
2. Prefer the newest known-good verified `.sqlite3` backup and keep its `.sha256` file beside it.
3. Run `ai-baby-backup --verify BACKUP.sqlite3 --require-checksum` when a verified sidecar is expected.
4. Restore into a **new** data directory.
5. Start AI Baby with `--data-dir` pointing to that restored directory and verify the profile and memories.
6. Only after verification should you decide whether to keep using the recovered directory.

The backup and restore commands never delete or replace the original live database for you.
