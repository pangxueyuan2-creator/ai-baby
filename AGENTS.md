# Agent instructions

## Project mission
AI Baby is a local-first AI character simulator whose identity, memory, growth state, and recovery data belong to the local application. Language generation is replaceable; persisted user data and deterministic safety boundaries are authoritative.

## Read first
Before changing behavior, read the documents relevant to the touched surface:
- `README.md` for the public product contract.
- `docs/ARCHITECTURE.md` for turn flow, persistence, and provider boundaries.
- `SECURITY.md` for data/network safety expectations.
- `docs/LOCAL_LLM.md` for loopback model setup and transport constraints.
- `docs/RECOVERY.md`, `docs/PRIVACY_EXPORT.md`, and `docs/PRIVACY_IMPORT.md` for portability and disaster-recovery invariants.

## Setup
Use Python 3.11 or newer in a clean environment:

```bash
python -m pip install -e ".[dev]"
```

Tests must not require paid APIs, real model credentials, or a live external model service.

## Required checks
Run the complete local quality set before opening or updating a pull request:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
```

Do not weaken, skip, delete, or bypass a failing check to make a change appear green.

## Data and privacy invariants
- Never commit a real `baby.sqlite3`, backup, export, support bundle, API key, provider secret, raw user transcript, or other private runtime data.
- Keep the default privacy export narrower than a full database dump; raw chat history and inactive/superseded memories must remain explicit opt-ins.
- Keep support diagnostics content-minimized and free of chat text, memory values, profile values, provider credentials, endpoints, and absolute private paths.
- Recovery, import, export, doctor, support, and audit tools must not silently overwrite an existing user database or output file.
- Schema changes require forward migration coverage from supported historical fixtures plus corruption/failure-path tests; never rewrite a source backup in place.
- Treat checksum files as integrity signals only, not signatures or proof of authorship.

## Provider and network invariants
- Offline and storage-maintenance commands must not load unrelated provider credentials or make network requests.
- Local-model presets remain loopback-only unless the user explicitly configures a remote provider through the existing remote-provider path.
- Do not forward project API keys to local discovery by default, follow redirects during local discovery, disable TLS verification, or inherit unsafe proxy behavior into loopback transport.
- Model output is untrusted text. Do not give it shell, filesystem, Git, package-manager, or tool authority.

## Change discipline
- Prefer small, coherent behavior changes with regression tests over broad rewrites.
- Preserve current command-line compatibility unless the change is intentionally versioned and documented.
- Do not add runtime dependencies unless they provide clear user value that cannot reasonably be implemented with the standard library.
- Do not force-push, rewrite history, delete protections, or push directly to the default branch.
- Do not weaken GitHub Actions, review expectations, data-loss protections, or security checks as a shortcut.

## Current product priorities
1. Memory correctness and conservative parsing: avoid learning questions, speculation, quoted claims, or unsupported language as facts.
2. A natural local-first companion experience without pretending the software has biological consciousness or requiring exclusive attachment.
3. Safe local-LLM interoperability without coupling identity or memory to one model vendor.
4. Inspectable privacy, backup, restore, and recovery workflows that fail closed before mutating user state.
5. Reproducible cross-platform packaging and tests on Linux, macOS, and Windows.

## Definition of done
A change is complete only when:
1. user-visible behavior and safety boundaries are explicit;
2. normal, regression, and meaningful failure paths are tested;
3. the exact pull-request head passes the required checks;
4. package/wheel behavior is verified when command-line entry points or packaging change;
5. no private data, credentials, or destructive fallback is introduced;
6. documentation is updated when the public contract materially changes.

## Agent workflow
1. Inspect live open PRs/issues and the current `main` head before selecting work.
2. Read the relevant architecture/security/data documents before editing.
3. Create a descriptive branch from current `main`.
4. Implement one bounded change and add tests for the bug, feature, or safety boundary.
5. Run the required checks and fix failures without weakening them.
6. Keep commits and PR text truthful about what was actually verified.
7. Merge only when the exact head is green and there is no unresolved blocker or required review.
