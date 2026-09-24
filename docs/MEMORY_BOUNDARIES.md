# Memory boundaries

AI Baby keeps persistent local state, but persistent memory is not the same thing as unlimited or infallible memory.

## What persists

Using the same data directory preserves the baby's profile, active facts, important episodes, relationship and character state, learning candidates, journals, curiosity items, and a bounded recent-message history.

## What does not

- The baby does not retrain model weights from conversation.
- A language model's built-in knowledge is not treated as a lived memory.
- Full raw chat history is not kept forever; recent messages are bounded.
- Forgotten or superseded facts are not returned as current knowledge, even when historical records are retained for consistency and auditability.
- Memory retrieval is selective. A stored item may not be surfaced in every reply.

## Correction beats repetition

When a single-valued fact is corrected, the newer active value replaces the older active value. Preferences and relationships may legitimately contain multiple objects, so they follow their own rules. Explicit `/forget` invalidates the selected active fact instead of pretending the historical record never existed.

## Provider boundary

The local memory layer owns identity, persistence, retrieval, correction, and growth state. The configured provider only receives selected context and produces language. Switching providers while keeping the same data directory therefore keeps the same simulated baby identity and memories.

## Privacy

The SQLite database can contain personal information supplied during conversation. It is not application-layer encrypted. Protect the operating-system account and disk, and treat backups and exports as sensitive data.
