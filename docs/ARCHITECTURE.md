# Architecture — 0.3

AI Baby retains the original CLI, SQLite stores, replaceable provider boundary and 0.2 optimistic turn lifecycle. This maintenance release strengthens forgotten-request handling, migrations, correction semantics and provider cancellation; it does not train model weights. Every personality, relationship and emotion value is a **software simulation**.

## Explicit local model setup

`--local-models` and `--setup-local` are the only discovery entry points. They validate one loopback URL, then use `providers.discovery` to GET Ollama `/api/tags` or an OpenAI-compatible `/models` catalog. No memory store is opened and no context, key, generation request, installation, process launch or download is performed by discovery. Catalogs have a three-second deadline, a one-MiB body bound and at most 100 unique, locally validated model identifiers. Invalid metadata fails closed. Ordinary startup and every chat turn use the configured model directly, without discovery.

The setup wizard requires an explicit numbered selection, even with one result, and rejects entries whose service metadata declares `remote_model` or `remote_host`. It can continue directly into the existing CLI. After separate confirmation, `local_settings` exclusively creates a new `local-model-<timestamp>.json` in the data directory, with only version/provider/base URL/model fields. It never edits `.env`, overwrites an existing file or saves a key. An explicit `--local-config` reads at most eight KiB and overrides only the connection selector fields; it cannot select a remote provider. Saved files are not automatically loaded. Data-directory selection remains independent and is included in the restart instructions.

`ollama` and `local-openai` are configuration presets, not additional generation implementations. Both use `OpenAICompatibleProvider`, with the same context, validation, fallback and optimistic commit path as the existing remote presets. Changing model or provider configuration alone does not mutate SQLite; chat still causes the ordinary local state transition. There is no schema change and no model-specific identity storage.

Loopback HTTP and HTTPS use direct numeric sockets: `localhost` tries `127.0.0.1` then `::1`, without DNS. `Host` and TLS hostname/certificate validation retain the configured hostname. All proxy environment variables are bypassed and all redirects are refused. Local presets omit Authorization even if an old key remains configured; generation may send the project-scoped key only with explicit `AI_BABY_ALLOW_LOCAL_AUTH=true`. Discovery never authenticates. Legacy `openai-compatible` authentication behavior is retained. A local process can itself forward requests to the cloud, which this client cannot constrain; see the [local service trust boundary](LOCAL_LLM.md).

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

Calling `Baby.chat()` inside an existing database transaction is rejected before generation. Top-level `transaction()` / `preview()` reject nesting without rolling back the caller's unrelated work. Standalone `MemoryStore.learn()` and `episode()` use savepoints so a failed token-index write cannot leave a partially replaced fact or unindexed episode. Public backup rejects an active transaction rather than blocking its own writer indefinitely.

### Concurrent instances

Schema v3 retains the v2 monotonic `revision` row. INSERT / UPDATE / DELETE triggers on authoritative tables increment it, including direct SQL writes. The transaction rolls increments back with their data. Index-only tables and receipt bookkeeping are not independent domain state. Opening a store validates required schema fields, the revision row and required trigger presence instead of silently operating without concurrency protection.

Connections enable foreign keys and use a two-second SQLite busy timeout. The application does not change a user's journaling mode or require WAL. WAL can help readers coexist with a writer, but still allows only one writer and does not solve a write lock held over network I/O. Keeping short transactions addresses this project's current contention problem without changing existing database side-file behavior.

If another instance changes the baby during generation, finalization raises `TurnConflict`. **No part of the losing turn is saved**: no duplicate user message, lost relationship update, candidate, or orphaned learning event. The CLI explains that the user should inspect the new state and submit again. There is no automatic model re-generation on conflict, avoiding hidden requests and cost. A change to profile, journal, baby name or forgotten facts also invalidates an older context.

External services may already have received the losing turn's context. Database rollback cannot retract a sent request. This release does not promise exactly-once third-party inference.

### Idempotency and interruption

`Baby.chat(text, turn_id="caller-generated-id")` retains the last 256 successful receipts. Reusing an ID and identical input returns the stored reply without another provider call or state update. Reusing an ID for different text is rejected. The CLI creates a new ID for every intentional input; repeated text is not automatically treated as a transport retry. Receipts outside the retention window cannot be deduplicated.

`/forget` clears cached answer bodies and marks retained receipts `revoked`. A replay of a revoked ID is rejected before learning or generation, rather than resurrecting a forgotten fact. These tombstones retain IDs and input digests, not the original text, within the same 256-receipt window. They are not permanent erase requests: an evicted ID cannot be recognized, and a new intentional request can teach the same fact again.

An unexpected plugin bug, Ctrl+C, failed COMMIT or full disk does not leave a partial local turn. A crash between provider completion and commit loses that uncommitted turn; the application never claimed it was saved. This is intentional instead of leaving durable half-finished turns or unsafe automatic restart retries.

## Database versioning

`migrations.initialize()` reads `PRAGMA user_version`. Fresh empty databases receive the frozen v1 base schema and then registered v2 / v3 migrations in one transaction. Unknown nonempty unversioned databases and future versions are rejected.

For existing v1 or v2 databases:

1. Acquire `BEGIN IMMEDIATE`, re-read the version (another opener may already have migrated).
2. Create `backups/pre-v<old>-to-v3-<UTC timestamp>.sqlite3` via SQLite's backup API using a separate read-only connection. The writer reservation prevents concurrent changes while this consistent pre-migration snapshot is made. Using `backup()` on the same write transaction would deadlock, so it is deliberately not used.
3. Apply individual transactional DDL / backfill statements. Do not use `executescript()` inside migrations because it can commit implicitly.
4. Run foreign-key and required schema / revision / trigger validation, set version 3 and commit together.

Backup failure prevents migration. Migration failure rolls back both schema and data and leaves the old file and pre-migration backup available. Existing profile, facts, episodes, relationship, emotion, personality, journals and legacy `Growth` JSON are preserved. Migrating v1 adds personality defaults without rewriting legacy growth or demoting its stage. `GrowthMetrics` is refreshed from current data at the next successful turn; legacy mixed `knowledge` is not blindly treated as world knowledge.

`MIGRATIONS` is an ordered registry. Future changes must add a new migration and a frozen previous-version fixture, not edit an already released migration. Tests create actual v1 files from `tests/fixtures/v1.sql`, copied from commit `c4871b8`, and frozen v2 fixtures. Failure tests include a process exiting during migration so SQLite recovery is exercised across a real connection restart; no user database is shipped.

The new v3 migration adds `turn_receipts.revoked`, fact-associated episode / curiosity indexes, and an `(active,id)` episode index. It retires episodes and questions linked to already inactive facts. It seeds `candidate_sequence` from both existing candidate IDs and any existing sequence; already-deleted pre-upgrade IDs cannot be recovered. Released v1 / v2 migrations remain unchanged.

New databases, backups and exports use exclusive creation with POSIX mode `0600`; on Windows they inherit the directory ACL. Existing files and permissions remain unchanged. These permissions do not protect data from other programs running as the same user or an attacker controlling the data directory.

Compatibility note: the importance column uses an integer SQL default during `ALTER TABLE`, followed by an explicit `0.4` backfill. This retains NOT NULL and range checks while avoiding [older SQLite's floating-default integrity-check bug](https://sqlite.org/forum/forumpost/ee4f6fa5ab), exposed by the Linux/macOS migration CI. That released v2 fix remains unchanged; existing v2 files receive only the new v3 migration.

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
| `revision`, `turn_receipts` | Concurrency and bounded retry deduplication, including revoked IDs |

Episode retrieval ranks indexed token overlap (`sum(token_length²)`) plus `6 × importance` plus a recency bonus no larger than 1. Recency decays on a 30-day scale. Relevant old events can outrank recent irrelevant ones; results are not selected by newest IDs alone. This is lexical relevance, not semantic embeddings or human autobiographical memory.

Questions about shared history additionally remove recall boilerplate and require a matching topic of at least two characters. Common pronouns alone cannot substantiate a claimed memory. This conservative filter can miss a vague or single-character topic; the user may need to name the event more specifically.

Provider context remains bounded: 8 facts, 4 episodes, 12 recent dialogue messages (1,200 characters each), up to three pending candidate descriptions, one optional curiosity question, fixed identity and current state. Fact and episode IDs are deduplicated and capped both during assembly and serialization, including newly learned facts and event supplements. An explicit routed question keeps its answer ahead of unrelated new learning. There is no whole-database prompt. The underlying retrieval table may grow; exports deliberately include the user's full active data and are not subject to prompt limits.

## Learning proposals and trust boundary

`MemoryCandidate` validates type, subject, predicate and field lengths locally. The learner retains original explicit teaching syntax and adds anchored first-person preference, residence and friend-name statements. It does not infer gender, health conditions or identity from everyday activity.

The supported correction grammar handles explicit present preference reversals, including “我以前喜欢橘猫，现在不喜欢了”; unsupported temporal qualifiers are rejected rather than swallowed into an object. Compatible personal clauses can be split while preserving uncertainty / question scope. Multiple friends coexist. Changed single-valued world / personal facts and opposite preferences retire their old linked episodes and questions. Old rows remain for audit; ordinary corrections do not erase all recent dialogue or old journals. Explicit prose knowledge notes count as world knowledge alongside structured teaching, not as personal memories.

Residence corrections retain an existing specific place only when the new value is its normalized prefix or names a parent linked to that place in the small built-in region map. Merely naming a known parent such as Zhejiang or Hangzhou does not make an unrelated old place its child. An explicit first-person retraction or past-tense statement of the exact old residence (for example, “我不住杭州了” or “我以前住杭州”) overrides that preservation rule when the same turn also contains a supported new residence assertion. These clues use the existing assertion grammar; turns with quotation, reported-speech, hypothetical or uncertainty markers conservatively cannot authorize a residence retraction. Retractions do not delete facts on their own and are not carried into later turns. This is a bounded text heuristic, not a geocoder or a complete administrative-region database.

An uncertain phrase such as “我可能喜欢橘猫” creates only a proposal and an explicit `/confirm ID` question. `/reject ID` discards it; `/candidates` lists pending proposals. Proposals are persisted locally for restart recovery but excluded from factual recall and the confirmed-data export. They are sent only as clearly marked *unconfirmed* data when external generation is explicitly enabled. Confirmation revalidates the proposal before saving it. A durable monotonic sequence prevents a stale confirmation from targeting a newly reused ID; a newer explicit preference removes a conflicting old proposal for the same object. Unknown, quoted, hypothetical or unsupported phrases do not become facts.

There is no LLM extraction in this release. Generated text is never parsed as database instructions. The provider interface offers no database or tool handle. Third-party Python provider implementations are trusted local code, not sandboxed programs; install only code you trust. Prompt isolation alone cannot guarantee an external model's behavior.

Context labels memories as `user_taught` / `user_statement` and episodes as `user_recorded` / `software_event`. Generation receives three messages: a fixed system policy, a user-role JSON data block, and the current user input. Recent dialogue is nested inside the data block with `memory_evidence=false`; previous assistant text is labeled `previous_model_output` and is never replayed as a native assistant-role message. `Context.history` remains available to existing Python providers. The shorter, ordered policy requires model-general knowledge to be identified separately and permits remembered-experience claims only from relevant facts/episodes. Tests insert a fabricated assistant moon visit and verify that it stays outside memory evidence and does not become a durable fact. This strengthens source separation without claiming that prompt instructions can eliminate model hallucinations.

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

Current stage gates intentionally require teaching: a baby that only chats may remain newborn while its personality and relationships continue evolving. Relationship changes now diminish near the relevant boundary, preventing a few hundred repeated praise turns from maxing every field, while allowing subsequent opposite experiences to change them. Tone hints conservatively ignore supported negated, quoted, hypothetical and reported statements; they do not solve general sarcasm or language understanding.

## Journals and proactive questions

Every 20 successful turns, `/journal`, or clean `/quit`, consolidation selects at most six important new episodes and compares personality to the preceding written journal snapshot. Each selected episode receives a 120-character excerpt budget, keeping later excerpts and personality changes inside the final 1,200-character bound. Unselected details remain in episodes. Interactions without new events can still produce an entry about personality changes; an unchanged interval only advances checkpoints. Sub-threshold personality changes accumulate against the last written snapshot. Repeated `/journal` without new turns / episodes does not duplicate entries. A journal is not fed back as new growth evidence.

Curiosity can schedule one question after at least six turns, then no more than once per eight turns, only on suitable newly learned facts. Young stages ask simple examples; later stages connect to an actual earlier retrieved fact or ask a question without presupposing a past lesson. Generic offline greetings do not independently append routine questions; clarification and support can still require a question. A durable topic hash prevents re-asking. Explicit “因为…” / “回答：…” resolves the latest pending question; “不想回答” / “跳过问题” ignores it. Other replies need not resolve it and are not punished. At most three question texts remain pending; resolved topics retain minimal hashes for deduplication. This conservative handling is not unrestricted natural-language answer understanding.

## User control and provider failure modes

The English preference alias uses complete local predicates (`like`, `dislike`,
`do not like`, `don't like`). Negation of another verb is not a preference.
Before comma splitting, every part of a sentence containing an English
preference cue must match the supported simple grammar. This prevents reporting,
conditional or tag-question scope from disappearing. Qualified/uncertain objects
are conservatively rejected using word boundaries; they do not become English
candidates. Explicit teaching commands and the existing Chinese candidate flow
are preserved. This is bounded lexical validation, not general English parsing,
and it does not reinterpret or migrate earlier saved facts.

`/forget ID` marks the selected fact (active or superseded) and directly linked / normalized-content-matching episodes inactive. Matching question text is cleared, including a question associated with another fact. It also clears recent dialogue, cached answer bodies, pending candidates and journals so those secondary copies cannot revive the fact. Receipt identities become revoked tombstones, as described above. Metrics are refreshed; past developmental stage and personality do not regress. Inactive rows, input digests and previous backups remain on disk: **this is recall suppression, not secure erasure**. Other independent facts are not a semantic dependency graph, and re-teaching can intentionally save the same information again.

Emotion episodes now store only tone and simulated state. Legacy emotion episodes
embedded raw input truncated to 180 characters with the marker `用户说：`, without
fact provenance. Matching a complete long fact cannot find that partial copy.
On an explicit successful forget, all active emotion episodes bearing the marker
are conservatively retired, including unrelated excerpts. Other structured events
and state-only emotion records are preserved. This cleanup shares the existing
forget transaction, runs only after finding the ID, and requires no migration.
See [historical memory controls](MEMORY_CONTROLS.md).

`/export` writes a new human-readable JSON under `data-dir/exports/` using an explicit field allowlist and a consistent read transaction. It excludes configuration, keys, environment files, raw dialogue, unconfirmed candidates and inactive facts. All active facts, important episodes, state and journals may contain personal information. It refuses to overwrite files. `/reset` is not implemented; an independent `--data-dir` safely creates another baby.

Remote requests still require explicit provider selection and opt-in. Local presets require explicit selection but no external opt-in or key. HTTPS is required except loopback endpoints. `store=false` and no-follow-redirect behavior remain. Retry defaults to zero and is configurable to at most two retries, only for explicit HTTP 429 rejection. No retries occur for auth errors, 5xx, redirects, malformed responses, connection loss or ambiguous timeouts. Backoff is bounded to two seconds and cancelled with the caller. Discovery performs no retries.

The provider and metadata discovery share `CancellableJSONClient`: a total caller deadline, one admitted daemon transport worker per client, and a one-MiB JSON response bound. A lock covers both admission and `Thread.start()`, avoiding a concurrent check/start race. The caller polls every 50 ms. Cancellation shuts down tracked sockets to wake stalled response-header, body and TLS-handshake reads, including slow-drip responses; proxy CONNECT sockets are tracked for remote connections too. Remote name resolution / connection establishment have platform or socket-timeout limits and may not terminate immediately. A timed-out/cancelled request may finish at the service; its result is ignored, it has no database access, and no further retries are scheduled. Until that worker exits, another request on the same provider falls back with `busy`. Python cannot forcibly terminate a thread or retract a request. Streaming is deliberately deferred.

The CLI's `ProviderNotices` shows the first failure, suppresses repeated identical warnings except a short reminder every ten repeats, and announces recovery. Every turn still attempts the configured provider; SDK `Reply.warning` remains available on each failed turn. This is display coalescing, not a hidden retry or a permanent switch to mock.

Errors exposed to CLI/logs are categories, not provider bodies, user text or keys. Baseline and new tests use fake identities, temporary files and local HTTP only; real paid-model quality remains unverified.
