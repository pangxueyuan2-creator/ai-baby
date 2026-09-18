# Memory parser audit fixtures

AI Baby can inspect its deterministic memory parser without opening or mutating the SQLite memory database.

For one user turn:

```bash
python -m ai_baby.memory_audit "I like tea." --expect-memory
python -m ai_baby.memory_audit "Maybe I live in Paris." --expect-no-memory
python -m ai_baby.memory_audit "Who is my friend" --expect-no-memory
```

For regression suites, put one JSON object on each non-empty line of a JSONL file:

```jsonl
{"id":"simple-like","text":"I like tea.","expect":"memory"}
{"id":"qualified-residence","text":"Maybe I live in Paris.","expect":"no-memory"}
```

Then run:

```bash
python -m ai_baby.memory_audit --cases tests/fixtures/memory-cases.jsonl
```

Each case requires a non-empty `text` string and an `expect` value of either `memory` or `no-memory`. `id` is optional but useful in CI output. Blank lines are ignored.

The command emits a JSON summary containing every case, the parser clauses, candidate counts, and whether the expectation matched. Exit codes are:

- `0`: every expectation matched.
- `1`: at least one fixture expectation failed.
- `2`: the fixture file could not be read or is invalid, or batch mode was combined with single-text arguments.

Use `--pretty` for human-readable output. Batch mode intentionally cannot be combined with `--expect-memory`, `--expect-no-memory`, or a positional text argument because every fixture carries its own expectation.

This is a parser regression harness, not a second persistence path: it imports only the deterministic candidate parser and never opens the memory database.

English relation questions beginning with `who`, `what`, or `which` are not assertions,
even without a question mark. Relation grammar keywords use ASCII case-insensitive
matching; Unicode names remain supported, but Unicode lookalikes in a keyword are
declined rather than normalized into a relation. This conservative boundary applies
before period-separated clauses can become facts. Parser fixes do not rewrite old
memories; inspect `/memories --all` and explicitly `/forget ID` for an earlier mistaken
relation.
