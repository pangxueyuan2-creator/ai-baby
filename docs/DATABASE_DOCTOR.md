# Database doctor

`ai-baby-doctor` checks an AI Baby SQLite database without starting a model provider, opening a chat session, migrating the schema, or writing to the database.

Use it when a baby fails to start, before trusting an old backup, after copying data between machines, or as a lightweight local/CI health check.

```bash
# Default data directory: AI_BABY_DATA_DIR or ~/.ai-baby
ai-baby-doctor

# Check a specific baby directory
ai-baby-doctor --data-dir ~/.ai-baby-restored

# Check a backup or database file directly
ai-baby-doctor --database ~/.ai-baby/backups/baby-20260917T120000000000Z.sqlite3

# Slower, deeper SQLite check with machine-readable output
ai-baby-doctor --database BACKUP.sqlite3 --full --json
```

## What it checks

For the current schema, doctor verifies:

- SQLite `quick_check` by default, or `integrity_check` with `--full`;
- the `PRAGMA user_version` schema version;
- required AI Baby tables and columns;
- revision/concurrency-protection metadata;
- foreign-key references;
- non-sensitive record counts for profile, active facts, active episodes, and recent messages.

The command never prints profile values, memory text, message contents, API keys, or provider configuration.

## Read-only behavior

Doctor opens the selected database with SQLite `mode=ro`, enables `query_only`, and performs no migration or repair. In particular:

- a current healthy database is inspected in place and left unchanged;
- a supported older schema reports `upgrade_required` but is **not** migrated;
- a future/unsupported schema is rejected;
- a corrupt, empty, unversioned, missing, or structurally incomplete database is reported as unhealthy;
- a missing default/data directory is not created just by running doctor;
- unrelated model/provider environment settings are not loaded, so diagnostics do not require a model, API key, or network access.

If repair or migration is needed, preserve the original file first. For backup recovery, use the separate non-destructive `ai-baby-restore` workflow documented in [RECOVERY.md](RECOVERY.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Current database is healthy. |
| `1` | Database is missing, corrupt, unsupported, or structurally unhealthy. |
| `3` | Database is a supported older schema and requires an upgrade; doctor did not migrate it. |

Exit code `2` remains available to `argparse` for invalid command-line usage.

The `--json` form has stable top-level fields (`status`, `code`, `database`, `schema_version`, `target_schema_version`, `integrity_check`, `counts`, `message`) so scripts can gate on `status` or the exit code without scraping human-readable text.
