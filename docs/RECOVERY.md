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

For the current schema, verified backup creation and verification also check that the five known character states can be decoded by normal chat. A matching checksum does not make malformed state JSON or invalid state values usable. Supported older schemas still report `upgrade_required` without being modified by backup verification; use restore preflight to validate their state after staged migration.

## Restore preflight

Before allocating a recovery directory, `ai-baby-restore --check` checks whether a backup passes the recovery requirements by copying it into disposable temporary storage, applying any supported schema migration there, validating the current schema and concurrency metadata, and checking foreign keys and known character states:

```bash
ai-baby-restore /safe/location/baby.sqlite3 --check --require-checksum
```

For CI or recovery automation, request stable JSON:

```bash
ai-baby-restore /safe/location/baby.sqlite3 --check --require-checksum --json
```

The report includes the source schema version, target schema version, whether migration is required, and the verified checksum when a sidecar is present. `--check` does not accept `--data-dir`, does not create a recovery target, does not alter the backup, and never loads a model provider or API key. Supported older schemas are migrated only inside disposable staging so the original backup remains at its original schema version.

State validation covers `growth`, `growth_metrics`, `relationship`, `emotion`, and `personality` with the same fields, types, finite numeric values, stages, and ranges accepted by normal chat. Missing known state rows retain their default behavior, and unknown extension keys are preserved without interpretation. Existing invalid state records are rejected rather than reset; the error never includes their stored values. This check does not claim to validate every possible application-level relationship in a database.

## Recovery-readiness audit

Use `ai-baby-recovery-audit` to check the live database and **every** `.sqlite3` backup in one pass. Each discovered backup goes through the same disposable staged migration, current-schema validation, foreign-key checks, and character-state validation as `ai-baby-restore --check`; the audit never migrates or edits the source backups.

```bash
ai-baby-recovery-audit --data-dir ~/.ai-baby
```

For a strict disaster-recovery policy, require every backup to have a matching checksum sidecar:

```bash
ai-baby-recovery-audit --data-dir ~/.ai-baby --require-checksum
```

A valid backup set can still be operationally weak if it has only one copy or the newest recovery point is old. Add explicit recovery-readiness objectives when that matters:

```bash
ai-baby-recovery-audit --data-dir ~/.ai-baby \
  --require-checksum \
  --min-recoverable-backups 2 \
  --max-backup-age-hours 24
```

`--min-recoverable-backups` requires at least that many backups to pass the full restore preflight. `--max-backup-age-hours` requires at least one recoverable backup whose filesystem modification time is no older than the configured window. A future-dated file is treated as age zero rather than producing a negative age. These gates are intentionally opt-in except for the existing default requirement of one recoverable backup.

Stable machine-readable output is available for CI and scheduled recovery drills:

```bash
ai-baby-recovery-audit --data-dir ~/.ai-baby --require-checksum --json
```

The audit reports the current database status, checked/recoverable/invalid backup counts, per-backup schema migration requirements, and orphan `.sha256` manifests. When recovery objectives are configured, JSON also includes the requested minimum copy count, maximum backup age, fresh recoverable count, policy violations, and per-backup age/freshness for successfully validated backups. It deliberately omits the absolute live database path and does not load provider configuration, API keys, or a chat session.

A nonzero exit means recovery is not fully ready: no backups were found, the current database is unhealthy, at least one backup is not restorable, an orphan checksum manifest exists, or a configured copy-count/freshness objective is not met. Integrity failures remain failures even if enough other backups satisfy the minimum count; the policy gates do not hide damaged recovery artifacts.

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
python -m ai_baby.recovery_audit --data-dir ~/.ai-baby --require-checksum
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
- Known character states are decoded after staged migration; malformed states fail even when SQLite integrity and SHA-256 checks pass. Validation cursors and the staged store are closed on failure so temporary files can be removed on Windows as well as POSIX.
- Invalid input is fully rejected before the requested target data directory is created.
- The final `baby.sqlite3` is created with the same exclusive private-file path used by normal backups.
- If the target data directory already contains `baby.sqlite3`, restore refuses to overwrite it; the exclusive create also closes the race if another process creates it during recovery.
- Invalid, corrupt, unsupported, checksum-mismatched, or partially written inputs leave the target without a restored database.

Recovery-readiness audit inherits those preflight guarantees for every discovered backup. It writes only disposable temporary staging data managed by the operating system, never creates a recovery target, never alters a backup or checksum sidecar, and treats orphan manifests as a failed recovery set rather than silently ignoring them. Copy-count and freshness objectives only inspect validated results and file metadata; they do not delete, rotate, or rewrite backup files.

The JSON produced by `/export` is a readable data export and is **not** a database restore format.

## Recommended recovery flow

1. Keep the original damaged data directory unchanged.
2. Run `ai-baby-recovery-audit --data-dir DATA_DIR --require-checksum --min-recoverable-backups 2 --max-backup-age-hours 24` regularly (adjust the copy count and age window to your own recovery objective) so broken, insufficient, or stale backup sets are found before an incident.
3. Prefer the newest known-good verified `.sqlite3` backup and keep its `.sha256` file beside it.
4. Run `ai-baby-restore BACKUP.sqlite3 --check --require-checksum` so the exact restore path, including staged migration, is validated before a target is created.
5. Restore into a **new** data directory with `ai-baby-restore BACKUP.sqlite3 --data-dir NEW_DIR --require-checksum`.
6. Start AI Baby with `--data-dir` pointing to that restored directory and verify the profile and memories.
7. Only after verification should you decide whether to keep using the recovered directory.

For legacy `/backup` snapshots without sidecars, omit `--require-checksum` in steps 2, 4, and 5. The backup, audit, and restore commands never delete or replace the original live database for you.
