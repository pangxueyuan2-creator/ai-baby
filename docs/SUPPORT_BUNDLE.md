# Privacy-safe support bundle

`ai-baby-support` creates a small diagnostic JSON file that can be attached to a bug report without exporting the baby's private content.

It reports the AI Baby version, Python/runtime platform, database health code, schema version, integrity-check mode, and non-sensitive record counts. It intentionally excludes chat text, fact and episode contents, profile values, the absolute database path, Provider/API configuration, URLs, and API keys.

## Create a bundle

```sh
ai-baby-support --output support.json
```

For a non-default data directory:

```sh
ai-baby-support --data-dir ./data/second-baby --output support.json
```

You can also inspect a specific database file with `--database PATH`. The command is read-only with respect to the database and uses the same `quick_check` / schema / foreign-key validation as `ai-baby-doctor`. Add `--full` to use SQLite `integrity_check`.

The output file and adjacent `support.json.sha256` are created with exclusive-create semantics: existing files are never overwritten. On POSIX systems they are created owner-only (`0600`). The checksum is useful for detecting accidental corruption when a bundle is copied or uploaded.

## Exit codes

- `0`: database is healthy and the bundle was created.
- `3`: the database is a supported older schema that needs a normal AI Baby upgrade; the bundle was still created.
- `1`: the database is missing, unreadable, corrupt, unsupported, or the bundle could not be created.

A non-zero database-health exit still leaves the successfully created support bundle in place, because that bundle is most useful precisely when diagnosis fails.

For scripts and CI, add `--json` to make the command status machine-readable. Use `--compact` if the on-disk support bundle should not be pretty-printed.
