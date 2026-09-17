# Architecture — 0.2

AI Baby retains the 0.1 CLI, SQLite stores and replaceable provider boundary. This release changes turn consistency and adds small, separate domain modules; it does not train model weights. Every personality, relationship and emotion value is a **software simulation**.

## One turn: preview, generate, compare-and-commit

```text
input
  -> clean_text / local validation / optional caller turn_id
  -> short BEGIN IMMEDIATE
       read committed receipt or capture revision
       identify learning candidates
       apply provisional learning and local state changes
       retrieve bounded facts + relevant episodes
       build context (stage + individual personality + optional question)
     ROLLBACK every provisional write
  -> provider.generate(context)       NO SQLite transaction or lock held
       optional explicit external opt-in
       recoverable failure -> MockProvider
       Ctrl+C -> stop, no durable partial turn
  -> short BEGIN IMMEDIATE
       recheck receipt
       compare current revision with captured revision
       deterministic replay of local transition
       persist both messages + state + optional journal + receipt
     COMMIT
  -> display the committed reply
```

`Baby._advance()` implements the **same local transition** for preview and final commit. Preview uses the existing normalized store and SQL queries, rather than copying the entire database into memory or maintaining a second state engine. Its writes are always rolled back, including generated IDs, candidates, personality and revision changes. The context is detached data; no SQLite connection is passed to the provider.

This deliberately trades two short local transitions per turn for a simple consistency contract. Network latency, backoff and provider deadlines never extend a SQLite write transaction. SQL, validation and retrieval remain inside the short local phase. Huge databases can still make local phases slower; keyword indexes and bounded result sets limit work, but this is not a distributed high-throughput service.

### Concurrent instances

Schema v2 maintains a monotonic `revision` row. INSERT / UPDATE / DELETE triggers on authoritative tables increment it, including direct SQL writes. The transaction rolls increments back with their data. Index-only tables and receipt bookkeeping are not independent domain state.

If another instance changes the baby during generation, finalization raises `TurnConflict`. **No part of the losing turn is saved**: no duplicate user message, lost relationship update, candidate, or orphaned learning event. The CLI explains that the user should inspect the new state and submit again. There is no automatic model re-generation on conflict, avoiding hidden requests and cost. A change to profile, journal, baby name or forgotten facts also invalidates an older context.

External services may already have received the losing turn's context. Database rollback cannot retract a sent request. This release does not promise exactly-once third-party inference.

### Idempotency and interruption

`Baby.chat(text, turn_id="caller-generated-id")` retains the last 256 successful receipts. Reusing an ID and identical input returns the stored reply without another provider call or state update. Reusing an ID for different text is rejected. The CLI creates a new ID for every intentional input; repeated text is not automatically treated as a transport retry. Receipts outside the retention window cannot be deduplicated.

An unexpected plugin bug, Ctrl+C, failed COMMIT or full disk does not leave a partial local turn. A crash between provider completion and commit loses that uncommitted turn; the application never claimed it was saved. This is intentional instead of leaving durable half-finished turns or unsafe automatic restart retries.

## Database versioning

`migrations.initialize()` reads `PRAGMA user_version`. Fresh empty databases receive the frozen v1 base schema and then the v2 migration in one transaction. Unknown nonempty unversioned databases and future versions are rejected.

For existing v1 databases:

1. Acquire `BEGIN IMMEDIATE`, re-read the version (another opener may already have migrated).
2. Create `backups/pre-v1-to-v2-<UTC timestamp>.sqlite3` via SQLite's backup API using a separate read-only connection. The writer reservation prevents concurrent changes while this consistent pre-migration snapshot is made. Using `backup()` on the same write transaction would deadlock, so it is deliberately not used.
3. Apply individual transactional DDL / backfill statements. Do not use `executescript()` inside migrations because it can commit implicitly.
4. Run foreign-key validation, set version 2 and commit together.

Backup failure prevents migration. Migration failure rolls back both schema and data and leaves the v1 file and pre-migration backup available. Existing `profile`, facts, episodes, relationship, emotion and legacy `Growth` JSON are preserved. New personality defaults are added without rewriting the legacy growth state or demoting its stage. `GrowthMetrics` is initialized from current data at the next successful turn; legacy mixed `knowledge` is not blindly treated as world knowledge.

`MIGRATIONS` is an ordered registry. Future changes must add a new migration and a frozen previous-version fixture, not edit an already released migration. Tests create actual v1 files from `tests/fixtures/v1.sql`, copied from commit `c4871b8`; no user database is shipped.

## Memory and retrieval

The existing layers remain separate. Additional v2 tables:

| Table / field | Purpose |
| --- | --- |
| `episodes.importance`, `active`, `fact_id` | Importance, recall eligibility, fact provenance |
| `episode_tokens` | Chinese character / bigram and Latin token index |
| `facts.novelty` | Digit / punctuation normalized novelty key |
| `state.personality` | Eight individual simulated traits |
| `state.growth_metrics` | Separated growth dimensions |
| `candidates` | At most three unconfirmed proposals; not factual memory |
| `journals` | Deterministic interval summaries with turn / episode cursors |
| `curiosity` | At most three pending questions and compact asked-topic history |
| `experience` | Unique category / signature pairs for diversity accounting |
| `settings` | Baby name and local journal / curiosity cursors |
| `revision`, `turn_receipts` | Concurrency and bounded retry deduplication |

Episode retrieval ranks indexed token overlap (`sum(token_length²)`) plus `6 × importance` plus a recency bonus no larger than 1. Recency decays on a 30-day scale. Relevant old events can outrank recent irrelevant ones; results are not selected by newest IDs alone. This is lexical relevance, not semantic embeddings or human autobiographical memory.

Provider context remains bounded: 8 facts, 4 episodes, 12 recent dialogue messages (1,200 characters each), up to three pending candidate descriptions, one optional curiosity question, fixed identity and current state. There is no whole-database prompt. The underlying retrieval table may grow; exports deliberately include the user's full active data and are not subject to prompt limits.

## Learning proposals and trust boundary

`MemoryCandidate` validates type, subject, predicate and field lengths locally. The learner retains original explicit teaching syntax and adds anchored first-person preference, residence and friend-name statements. It does not infer gender, health conditions or identity from everyday activity.

An uncertain phrase such as “我可能喜欢橘猫” creates only a proposal and an explicit `/confirm ID` question. `/reject ID` discards it; `/candidates` lists pending proposals. Proposals are persisted locally for restart recovery but excluded from factual recall and the confirmed-data export. They are sent only as clearly marked *unconfirmed* data when external generation is explicitly enabled. Confirmation revalidates the proposal before saving it. Unknown, quoted, hypothetical or unsupported phrases do not become facts.

There is no LLM extraction in this release. Generated text is never parsed as database instructions. The provider interface offers no database or tool handle. Third-party Python provider implementations are trusted local code, not sandboxed programs; install only code you trust. Prompt isolation alone cannot guarantee an external model's behavior.

## Development stage versus personality

`Growth.stage` describes developmental complexity and retains newborn / baby / child / growing / mature. `growth.TRAITS` now supplies only the stage's expression guidance. `PersonalityState` describes differences between two babies at the same stage:

| Trait | Simulated meaning |
| --- | --- |
| curiosity | Interest in exploring or asking about new material |
| confidence | Willingness to attempt an answer |
| sociability | Tendency to engage socially |
| caution | Preference for checking and slowing down |
| playfulness | Preference for lighthearted interaction |
| independence | Readiness to connect knowledge without constant prompting |
| patience | Preference for sustained, gradual interaction |
| openness | Receptiveness to new topics and perspectives |

All values are 0–100, initially 50 except curiosity 70. Each change is bounded by 0.20 and decreases near a boundary. Encouragement, exploration, play, explicit caution and hostility have small distinct effects. Stage and personality are both supplied to the provider. The offline provider uses selected traits for response style; it remains a finite response system, not a general language model.

Growth metrics separate world knowledge, personal memories, episodes, relationship depth, interaction diversity, active seconds, important events and knowledge diversity. World-knowledge novelty and category breadth gate advancement. Duplicate facts produce no new learning episodes; digit / punctuation variants share a novelty key; per-dimension saturation limits reward. Arbitrary semantically meaningless but lexically varied assertions can still evade this heuristic. There is no truth detector or claim of spam-proof intelligence.

## Journals and proactive questions

Every 20 successful turns, `/journal`, or clean `/quit`, consolidation selects at most six important new episodes and compares personality to the preceding journal snapshot. It writes a bounded 1,200-character deterministic software-state entry. Interactions without new events can still produce an entry about personality changes. Repeated `/journal` without new turns / episodes does not duplicate entries. A journal is not fed back as new growth evidence.

Curiosity can schedule one question after at least six turns, then no more than once per eight turns, only on suitable newly learned facts. Young stages ask simple examples; later stages ask about connections and changed perspectives. A durable topic hash prevents re-asking. Explicit “因为…” / “回答：…” resolves the latest pending question; “不想回答” / “跳过问题” ignores it. Other replies need not resolve it and are not punished. At most three question texts remain pending; resolved topics retain minimal hashes for deduplication. This conservative handling is not unrestricted natural-language answer understanding.

## User control and provider failure modes

`/forget ID` marks a fact and directly linked / matching episodes inactive. It also clears recent dialogue, cached replies, pending candidates and journals so those secondary copies cannot revive the fact. This intentionally conservative cleanup is explained before use in help and README. Metrics are refreshed; past developmental stage and personality do not regress. Inactive rows and previous backups remain on disk: **this is recall suppression, not secure erasure**.

`/export` writes a new human-readable JSON under `data-dir/exports/` using an explicit field allowlist and a consistent read transaction. It excludes configuration, keys, environment files, raw dialogue, unconfirmed candidates and inactive facts. All active facts, important episodes, state and journals may contain personal information. It refuses to overwrite files. `/reset` is not implemented; an independent `--data-dir` safely creates another baby.

External requests still require explicit provider selection and opt-in. HTTPS is required except loopback endpoints; loopback services may omit Authorization entirely or use a user-provided dummy key. `store=false` and no-follow-redirect behavior remain. Retry defaults to zero and is configurable to at most two retries, only for explicit HTTP 429 rejection. No retries occur for auth errors, 5xx, redirects, malformed responses, connection loss or ambiguous timeouts. Backoff is bounded to two seconds and cancelled with the caller.

The provider has a total caller deadline and a single daemon transport worker. The caller polls every 50 ms, making Ctrl+C responsive even when the underlying platform socket call blocks. A timed-out/cancelled request may finish at the service; its result is ignored, it has no database access, and no further retries are scheduled. Until that worker exits, another request on the same provider falls back with a `busy` classification. This bounds worker accumulation. Socket-level timeouts still apply, but Python cannot forcibly terminate a thread or retract a request. Streaming is deliberately deferred.

Errors exposed to CLI/logs are categories, not provider bodies, user text or keys. Baseline and new tests use fake identities, temporary files and local HTTP only; real paid-model quality remains unverified.
