# Privacy export import

`ai-baby-import` turns a default `ai-baby-export` JSON document into a **new** AI Baby SQLite database.
It is a portability/bootstrap path, not a forensic database restore. For byte-preserving disaster recovery use
`ai-baby-backup` and `ai-baby-restore` instead.

## Safe workflow

```bash
ai-baby-export --data-dir ~/.ai-baby --output ./baby-portable.json --pretty
ai-baby-import ./baby-portable.json --check --require-checksum
ai-baby-import ./baby-portable.json --data-dir ./imported-baby --require-checksum
ai-baby-doctor --data-dir ./imported-baby
```

A new `ai-baby-export` also creates `baby-portable.json.sha256`. Keep the JSON and sidecar together when copying
the export. The importer verifies a sidecar automatically whenever one is present; `--require-checksum` also
rejects old or incomplete transfers where the sidecar is missing.

The importer restores the user-visible active profile, baby name, structured state, facts and episodes. It
rebuilds SQLite indexes and internal IDs using the current schema rather than copying hidden implementation
bookkeeping from the export.

Birth time (`profile.created_at`) and the creation times of active facts and episodes are
preserved. Restarting an imported character therefore retains its age in growth journals
and the recency of its memories. Timestamps accept `YYYY-MM-DD HH:MM:SS` (the SQLite UTC
format) or the same date and time with a `T` separator, optional one-to-six-digit fractional
seconds, and optional `Z` / `+HH:MM` / `-HH:MM` timezone. Explicit offsets are normalized to
UTC before storage; timestamps without an offset are treated as UTC. Invalid dates,
date-only values, nulls, and unsupported formats are rejected during preflight, before
creating a destination.

For compatibility, an older document that omits a `created_at` field still imports. Missing
fields use one shared current UTC time for that import; the original dates cannot be inferred.
This fallback applies only to absent fields, not invalid supplied values. Timestamp handling
does not restore inactive memories or raw history, and it does not change the database schema.

## Preflight / dry validation

Use `--check` before a migration, in CI, or whenever an export arrives from another machine:

```bash
ai-baby-import ./baby-portable.json --check --require-checksum --json
```

Preflight runs the same structural and semantic validation as a real import, including checksum verification
when present, format/version checks, privacy-option checks, field validation, duplicate IDs, numeric ranges and
episode-to-fact references. A successful JSON result reports the number of facts and episodes plus whether a
profile is present.

The importer reads at most 20 MiB of export bytes, verifies the checksum against those exact bytes, and parses
that same in-memory snapshot. This avoids a verify-then-reopen gap where a file could otherwise change between
integrity checking and JSON parsing.

`--check` is deliberately read-only with respect to AI Baby storage: it does not create the default
`AI_BABY_DATA_DIR`, does not create SQLite files, does not migrate an existing database, does not load provider
configuration and does not make network requests. This makes it suitable for release gates and automated
migration pipelines.

## Checksum compatibility and limits

Exports created before checksum sidecars were introduced remain accepted when `--require-checksum` is omitted.
This keeps existing portable exports usable. However, any sidecar that is present must be well formed and match
the JSON; a malformed or mismatched checksum is never ignored.

SHA-256 detects accidental corruption and untrusted modification when the expected sidecar is transferred
through a trusted channel. It is not a digital signature or proof of authorship. Do not treat a matching digest
as evidence that an export came from a particular person or machine.

## Non-destructive guarantees

- Checksum verification and the entire JSON document validation, including cross-record references, happen
  before a destination directory or database is created.
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
