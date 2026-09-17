# Backup recovery

AI Baby's interactive `/backup` command creates a consistent SQLite snapshot. Restore is intentionally a separate, non-interactive command so recovery never needs a model provider, API key, or chat session.

```bash
ai-baby-restore ~/.ai-baby/backups/baby-20260917T120000000000Z.sqlite3 \
  --data-dir ~/.ai-baby-restored
```

The equivalent module form works from a source checkout:

```bash
python -m ai_baby.restore BACKUP.sqlite3 --data-dir ~/.ai-baby-restored
```

After a successful restore, start the recovered baby explicitly:

```bash
ai-baby --data-dir ~/.ai-baby-restored
```

## Safety properties

Restore is deliberately non-destructive:

- The backup is opened read-only and is never migrated or edited in place.
- SQLite `quick_check` runs before recovery proceeds.
- The backup is copied into a private staging directory first.
- Staged data is opened through `MemoryStore`, so supported older schemas are migrated and the current schema/concurrency metadata are validated before installation.
- Foreign-key integrity is checked after staged migration.
- The final `baby.sqlite3` is created with the same exclusive private-file path used by normal backups.
- If the target data directory already contains `baby.sqlite3`, restore refuses to overwrite it.
- Invalid, corrupt, unsupported, or partially written inputs leave the target without a restored database.

This command restores the SQLite backup created by `/backup`. The JSON produced by `/export` is a readable data export and is **not** a database restore format.

## Recommended recovery flow

1. Keep the original damaged data directory unchanged.
2. Choose the newest known-good `.sqlite3` file under its `backups/` directory.
3. Restore into a **new** data directory.
4. Start AI Baby with `--data-dir` pointing to that restored directory and verify the profile and memories.
5. Only after verification should you decide whether to keep using the recovered directory.

The restore command never deletes or replaces the original database for you.
