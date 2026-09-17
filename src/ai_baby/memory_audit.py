"""Dry-run inspector for AI Baby's explicit memory parser.

This module never opens the memory database. It exposes exactly which assertion clauses
and validated candidates the deterministic parser would produce for a piece of text.
Maintainers can use it while debugging false positives/negatives or writing regression
fixtures without mutating a local profile.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .candidates import assertion_clauses, extract_candidates

_EXPECTATIONS = {"memory", "no-memory"}


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


def _fixture_rows(path: str) -> list[tuple[int, dict[str, object]]]:
    """Load validated JSONL fixture rows without touching persistent memory."""
    rows: list[tuple[int, dict[str, object]]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number}: each fixture must be a JSON object")
            text = payload.get("text")
            expectation = payload.get("expect")
            case_id = payload.get("id")
            if not isinstance(text, str) or not text:
                raise ValueError(f"line {line_number}: text must be a non-empty string")
            if expectation not in _EXPECTATIONS:
                raise ValueError(f"line {line_number}: expect must be 'memory' or 'no-memory'")
            if case_id is not None and (not isinstance(case_id, str) or not case_id):
                raise ValueError(f"line {line_number}: id must be a non-empty string when supplied")
            rows.append((line_number, payload))
    if not rows:
        raise ValueError("fixture file contains no cases")
    return rows


def audit_fixture_file(path: str) -> dict[str, object]:
    """Audit JSONL expectations and return a machine-readable CI summary."""
    cases: list[dict[str, object]] = []
    failed_count = 0
    for line_number, fixture in _fixture_rows(path):
        text = str(fixture["text"])
        expectation = str(fixture["expect"])
        report = audit_text(text)
        candidate_count = int(report["candidate_count"])
        matched = candidate_count > 0 if expectation == "memory" else candidate_count == 0
        failed_count += int(not matched)
        case: dict[str, object] = {
            "line": line_number,
            "expect": expectation,
            "matched": matched,
            "candidate_count": candidate_count,
            "clauses": report["clauses"],
        }
        if "id" in fixture:
            case["id"] = fixture["id"]
        cases.append(case)
    return {
        "fixture": path,
        "case_count": len(cases),
        "failed_count": failed_count,
        "cases": cases,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_baby.memory_audit",
        description="Inspect explicit memory parsing without writing to the database.",
    )
    parser.add_argument("text", nargs="?", help="Text to inspect as one user turn.")
    parser.add_argument(
        "--cases",
        metavar="PATH",
        help=("Audit JSONL cases with text and expect fields; exit 1 if any expectation fails."),
    )
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


def _print_report(report: dict[str, object], *, pretty: bool) -> None:
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cases:
        if args.text is not None or args.expect_memory or args.expect_no_memory:
            parser.print_usage(sys.stderr)
            print(
                "memory_audit: error: --cases cannot be combined with text or single-text expectations",
                file=sys.stderr,
            )
            return 2
        try:
            report = audit_fixture_file(args.cases)
        except (OSError, ValueError) as exc:
            print(f"memory_audit: error: {exc}", file=sys.stderr)
            return 2
        _print_report(report, pretty=args.pretty)
        return 1 if int(report["failed_count"]) else 0

    if args.text is None:
        parser.print_usage(sys.stderr)
        print("memory_audit: error: text or --cases PATH is required", file=sys.stderr)
        return 2

    report = audit_text(args.text)
    _print_report(report, pretty=args.pretty)
    count = int(report["candidate_count"])
    if args.expect_memory and count == 0:
        return 1
    if args.expect_no_memory and count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
