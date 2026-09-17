"""Dry-run inspector for AI Baby's explicit memory parser.

This module never opens the memory database. It exposes exactly which assertion clauses
and validated candidates the deterministic parser would produce for a piece of text.
Maintainers can use it while debugging false positives/negatives or writing regression
fixtures without mutating a local profile.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Sequence

from .candidates import assertion_clauses, extract_candidates


def audit_text(text: str) -> dict[str, object]:
    """Return a JSON-serializable dry-run report for supported memory assertions."""
    clauses: list[dict[str, object]] = []
    candidate_count = 0
    for clause in assertion_clauses(text):
        candidates = extract_candidates(clause)
        candidate_count += len(candidates)
        clauses.append(
            {
                "text": clause,
                "candidates": [asdict(candidate) for candidate in candidates],
            }
        )
    return {
        "input": text,
        "candidate_count": candidate_count,
        "clauses": clauses,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_baby.memory_audit",
        description="Inspect explicit memory parsing without writing to the database.",
    )
    parser.add_argument("text", help="Text to inspect as one user turn.")
    expectation = parser.add_mutually_exclusive_group()
    expectation.add_argument(
        "--expect-memory",
        action="store_true",
        help="Exit 1 when the text produces no memory candidate.",
    )
    expectation.add_argument(
        "--expect-no-memory",
        action="store_true",
        help="Exit 1 when the text produces one or more memory candidates.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of emitting one compact line.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_text(args.text)
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    count = int(report["candidate_count"])
    if args.expect_memory and count == 0:
        return 1
    if args.expect_no_memory and count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
