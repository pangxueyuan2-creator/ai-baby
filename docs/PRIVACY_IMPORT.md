# Privacy export import

`ai-baby-import` turns a default `ai-baby-export` JSON document into a **new** AI Baby SQLite database.
It is a portability/bootstrap path, not a forensic database restore. For byte-preserving disaster recovery use
`ai-baby-backup` and `ai-baby-restore` instead.

## Safe workflow

```bash
ai-baby-export --data-dir ~/.ai-baby --output ./baby-portable.json --pretty
ai-baby-import ./baby-portable.json --check
ai-baby-import ./baby-portable.json --data-dir ./imported-baby
ai-baby-doctor --data-dir ./imported-baby
```

The importer restores the user-visible active profile, baby name, structured state, facts and episodes. It
rebuilds SQLite indexes and internal IDs using the current schema rather than copying hidden implementation
bookkeeping from the export.

## Preflight / dry validation

Use `--check` before a migration, in CI, or whenever an export arrives from another machine:

```bash
ai-baby-import ./baby-portable.json --check --json
```

Preflight runs the same structural and semantic validation as a real import, including format/version checks,
privacy-option checks, field validation, duplicate IDs, numeric ranges and episode-to-fact references. A
successful JSON result reports the number of facts and episodes plus whether a profile is present.

`--check` is deliberately read-only with respect to AI Baby storage: it does not create the default
`AI_BABY_DATA_DIR`, does not create SQLite files, does not migrate an existing database, does not load provider
configuration and does not make network requests. This makes it suitable for release gates and automated
migration pipelines.

## Non-destructive guarantees

- The entire JSON document, including cross-record references, is parsed and validated before a destination
  directory or database is created.
- `--data-dir` must not already contain `baby.sqlite3`; existing babies are never overwritten.
- If database reconstruction fails, the newly-created database plus SQLite WAL/SHM files are removed.
- The completed database is checked with the same read-only doctor used elsewhere in the project.
- The command does not load LLM/provider configuration, make network requests, or require an API key.
- On POSIX systems the new SQLite file is owner-only (`0600`) through the normal storage creation path.

## Why history and inactive records are refused

Version 1 intentionally accepts only the **default** privacy export, where both
`include_history=false` and `include_inactive=false`.

Raw chat history can contain highly sensitive text, while inactive facts/episodes can include information the
user explicitly replaced or retired. Importing those records into a fresh live baby would require additional
semantics for replay, revision, forgetting and retired-memory identity. Rather than silently guessing, the
importer rejects such exports. Re-run `ai-baby-export` without `--include-history` or `--include-inactive` to
create a portable import document.

## Compatibility

The importer requires `format="ai-baby-privacy-export"` and `format_version=1`. A future incompatible export
version is rejected instead of being partially imported. This keeps data migration explicit and testable.
