# Safe Delivery governance

AI Baby uses two complementary repository-safety layers.

## GuardSpec preflight

`.github/workflows/guardspec.yml` pins a reviewed GuardSpec commit and validates the repository's agent instructions on pull requests and pushes to `main`. It checks instruction hygiene and proves that the root `AGENTS.md` applies to a representative runtime target.

GuardSpec is read-only: it does not execute instructions, model output, or repository commands described inside instruction files.

## PatchWitness policy bootstrap

`.patchwitness.toml` defines the intended post-change evidence policy:

- ordinary source/docs changes are allowed within a bounded file/line budget;
- generated/private runtime data, build outputs, and PatchWitness evidence are denied;
- workflows and the policy file itself are protected control-plane paths;
- dependency changes require separate review rather than being silently accepted;
- tests, Ruff lint/format, and package build are required checks.

The policy is committed before enabling a PatchWitness PR gate on purpose. PatchWitness loads policy from an immutable trusted base revision; a workflow introduced in the same pull request as its first policy file would otherwise have to trust candidate-controlled policy. After this bootstrap lands on `main`, a later pull request can enable the pinned PatchWitness Action with `policy-ref` set to the pull request's trusted base SHA.

Until that follow-up lands, the presence of `.patchwitness.toml` **does not mean PatchWitness is already an enforced CI gate**. Existing CI plus the GuardSpec workflow remain the active hosted checks.

## Non-goals

These governance files do not grant autonomous merge authority, do not replace human review where review is required, do not weaken existing CI, and do not make hashes or passing tests proof of authorship or security approval.
