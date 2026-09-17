# Inspecting and forgetting historical memories

This maintenance change preserves database schema v3 and existing save files.
It does not enable networking or change the model, growth, or personality rules.

## Find the right memory ID

`/memories` still lists the newest 20 active facts. To inspect previous versions
as well, use:

```text
/memories --all
/memories --all 125
```

The second command shows up to 20 facts with IDs **less than 125**, newest first.
Each row is labelled `有效` (active) or `已失效` (inactive). A full page prints the
command for the next page. This is an explicit local inspection command; inactive
facts are not restored to model context or exported as current knowledge.

For example, after teaching “我住在杭州” and then “我住在苏州”, the old Hangzhou
record is inactive. Ordinary correction preserves historical conversations and
journals. It is not the same as asking to forget that information.

## Forget an old or current fact

```text
/forget 12
```

The ID may refer to an active fact or an inactive, superseded version. Both now
run the same transactional cleanup: retire the selected fact and associated or
text-matching episodes/questions, clear recent conversations, pending candidates
and journals, revoke cached turn replies, and recalculate memory counts.
Unrelated active facts, the authoritative profile and attained growth stage are
preserved. Existing broad cleanup is intentional: losing the recent transcript
is preferable to silently recalling a forgotten detail from a cached copy.

A nonexistent positive ID is a no-op. Repeating an explicit forget request for an
existing inactive record runs cleanup again; it may remove secondary copies
created since the earlier request. A punctuation-only value with an empty
normalized representation no longer matches every unrelated episode/question.
Linked records are still retired.

Older emotion episodes contain a `用户说：` excerpt truncated to 180 characters,
without a link to the original fact. A long fact therefore cannot always be
found by matching its complete value. A successful `/forget` also retires **all
legacy emotion episodes containing that marker**, including unrelated excerpts.
This is conservative collateral cleanup, not semantic matching. New emotion
episodes store only the interaction tone and simulated state; unrelated
structured events and these new state-only episodes remain. Unknown IDs do not
trigger cleanup. The entire operation rolls back together if a database write
fails. No schema change or startup rewrite is required.

**This is logical forgetting, not secure erasure.** Inactive rows remain locally
inspectable. Existing backups, exports and data already sent to a model service
are not erased. A fact taught again in a new turn may be learned again. The
unchanged bounded receipt policy is not an unlimited replay-prevention guarantee.

## Input and export failure handling

Slash commands, natural-language `确认记忆 ID`, and the Python forgetting entry
point share positive signed-64-bit ID validation. Booleans, floats, negative or
zero IDs and oversized values are rejected before SQLite binding. Error messages
do not repeat the supplied input. Invalid confirmations leave candidates and
character state unchanged rather than terminating the CLI with an overflow.

Exports retain exclusive creation and owner-only POSIX permissions. Failures
while creating a text stream, writing JSON, or closing/flushing that stream now
close owned descriptors and attempt to remove the newly created incomplete file.
An existing destination or symlink is never overwritten. Filesystem permission
or hardware failures can still prevent cleanup; this is not a guarantee of
power-loss durability or forensic erasure.

## Regression evidence

Audited baseline: `e6cb8782a7a6e22b195fc651b53ab9e6210f13c0`.
The unchanged baseline passed 203 tests locally (Python 3.13.5) and in the
isolated GitHub audit (Python 3.11).

`tests/test_memory_control_boundaries.py` adds 18 cases covering superseded-fact
forgetting across restart, provider context and export; empty normalized values;
export setup/body/close failures; ID overflow/type boundaries; stable historical
pagination; and actual terminal recovery. Against the unchanged baseline the
new test file produces 15 failures and 3 passes. After the fixes, all 18 pass and
the full local suite reports **221 passed**.

The existing A–H acceptance demo and offline stress demo also passed unchanged:
three simulated upbringing styles at 1,000 turns each, plus 10,001 inserted facts,
10,001 episodes and 10,000 messages. No paid API was called. These are software
state/integrity checks, not a validation of real language-model quality or
human-like consciousness. Final cross-platform checks are recorded by the CI
run for the maintenance commit, not inferred from an earlier green badge.

`tests/test_emotion_forget_privacy.py` adds eight synthetic regression cases for
raw-input minimization, truncated legacy excerpts from active/superseded facts,
restart/retrieval/export/journal/provider-context cleanup, conservative scope,
unknown IDs and rollback. Before the excerpt fix, six fail and two pass.
