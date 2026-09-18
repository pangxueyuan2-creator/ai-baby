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

Validate the stored file without changing it:

```bash
ai-baby-backup --verify /safe/location/baby.sqlite3 --require-checksum
```

`--require-checksum` is useful in automation when a missing sidecar should be treated as an error. Without it, verification remains compatible with older `/backup` snapshots that predate checksum manifests.

## Restore preflight

Before allocating a recovery directory, `ai-baby-restore --check` can prove that a backup is restorable by copying it into disposable temporary storage, applying any supported schema migration there, validating the current schema and concurrency metadata, and running foreign-key checks:

```bash
ai-baby-restore /safe/location/baby.sqlite3 --check --require-checksum
```

For CI or recovery automation, request stable JSON:

```bash
ai-baby-restore /safe/location/baby.sqlite3 --check --require-checksum --json
```

The report includes the source schema version, target schema version, whether migration is required, and the verified checksum when a sidecar is present. `--check` does not accept `--data-dir`, does not create a recovery target, does not alter the backup, and never loads a model provider or API key. Supported older schemas are migrated only inside disposable staging so the original backup remains at its original schema version.

Restore is intentionally a separate, non-interactive command so recovery never needs a model provider, API key, or chat session:

```bash
ai-baby-restore ~/.ai-baby/backups/baby-20260917T120000000000Z.sqlite3 \
  --data-dir ~/.ai-baby-restored \
  --require-checksum
```

Omit `--require-checksum` only when intentionally restoring a legacy backup that predates sidecar manifests.

The equivalent module forms work from a source checkout:

```bash
python -m ai_baby.backup --data-dir ~/.ai-baby
python -m ai_baby.restore BACKUP.sqlite3 --check --require-checksum
python -m ai_baby.restore BACKUP.sqlite3 --data-dir ~/.ai-baby-restored --require-checksum
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

Restore and restore preflight are deliberately non-destructive:

- If an adjacent `.sha256` manifest exists, its filename and digest are validated before SQLite is opened.
- `--require-checksum` can make a missing manifest an error for both preflight and actual restore; legacy backups remain compatible when the flag is omitted.
- The backup is opened read-only and is never migrated or edited in place.
- SQLite `quick_check` runs before recovery proceeds.
- The backup is copied into disposable staging first.
- Staged data is opened through `MemoryStore`, so supported older schemas are migrated and the current schema/concurrency metadata are validated before installation.
- Foreign-key integrity is checked after staged migration.
- Invalid input is fully rejected before the requested target data directory is created.
- The final `baby.sqlite3` is created with the same exclusive private-file path used by normal backups.
- If the target data directory already contains `baby.sqlite3`, restore refuses to overwrite it; the exclusive create also closes the race if another process creates it during recovery.
- Invalid, corrupt, unsupported, checksum-mismatched, or partially written inputs leave the target without a restored database.

The JSON produced by `/export` is a readable data export and is **not** a database restore format.

## Recommended recovery flow

1. Keep the original damaged data directory unchanged.
2. Prefer the newest known-good verified `.sqlite3` backup and keep its `.sha256` file beside it.
3. Run `ai-baby-restore BACKUP.sqlite3 --check --require-checksum` so the exact restore path, including staged migration, is validated before a target is created.
4. Restore into a **new** data directory with `ai-baby-restore BACKUP.sqlite3 --data-dir NEW_DIR --require-checksum`.
5. Start AI Baby with `--data-dir` pointing to that restored directory and verify the profile and memories.
6. Only after verification should you decide whether to keep using the recovered directory.

For legacy `/backup` snapshots without sidecars, omit `--require-checksum` in steps 3 and 4. The backup and restore commands never delete or replace the original live database for you.
