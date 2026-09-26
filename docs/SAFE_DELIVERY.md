# Safe Delivery governance

AI Baby uses complementary repository-safety layers before and after a proposed change.

## GuardSpec preflight

`.github/workflows/guardspec.yml` pins a reviewed GuardSpec commit and validates the repository's agent instructions on pull requests and pushes to `main`. It checks instruction hygiene and proves that the root `AGENTS.md` applies to a representative runtime target.

GuardSpec is read-only: it does not execute instructions, model output, or repository commands described inside instruction files.

## PatchWitness trusted-base gate

`.patchwitness.toml` defines the post-change evidence policy:

- ordinary source/docs changes are allowed within a bounded file/line budget;
- generated/private runtime data, build outputs, and PatchWitness evidence are denied;
- workflows and the policy file itself are protected control-plane paths;
- dependency changes require separate review rather than being silently accepted;
- tests, Ruff lint/format, and package build are required checks.

`.github/workflows/patchwitness.yml` installs PatchWitness from the reviewed, immutable commit `b1a99dfe01e6010f9e989981e79d1fde45bb6cb9`. For every pull request it uses the event's immutable base SHA for both `--base` and `--policy-ref`, so the candidate branch cannot weaken its own policy. Checkout credentials are not persisted, the workflow has only `contents: read`, and PatchWitness executes required checks in clean-room mode before publishing a Markdown/GitHub report.

PatchWitness is pinned independently from AI Baby. Updating that pin is a control-plane change and is therefore subject to the same protected-path handling as any other workflow modification.

## Bootstrap boundary

The policy landed on trusted `main` before the workflow was introduced. That ordering is intentional: the first gate must have an authoritative base policy to read.

The pull request that first adds `.github/workflows/patchwitness.yml` itself modifies a path protected by the already-trusted base policy. A correct PatchWitness run is therefore expected to emit `PW003` for that bootstrap change. Do not suppress, special-case, or reinterpret that finding as a pass. The bootstrap PR requires explicit review/acceptance of the control-plane change before merge; ordinary later pull requests are expected to pass the gate without protected-path findings.

## Non-goals

These governance files do not grant autonomous merge authority, do not replace human review where review is required, do not weaken existing CI, and do not make hashes or passing tests proof of authorship or security approval.
