"""Tests for the read-only memory parser audit utility."""

import json

from ai_baby.memory_audit import audit_text, main


def test_audit_reports_validated_candidates_without_database(baby):
    before = baby.memory.db.execute("SELECT count(*) FROM facts").fetchone()[0]

    report = audit_text("I like tea.")

    after = baby.memory.db.execute("SELECT count(*) FROM facts").fetchone()[0]
    assert before == after
    assert report["candidate_count"] == 1
    assert report["clauses"] == [
        {
            "text": "I like tea",
            "candidates": [
                {
                    "kind": "preference",
                    "subject": "用户",
                    "predicate": "likes",
                    "value": "tea",
                    "ambiguous": False,
                }
            ],
        }
    ]


def test_audit_exposes_abstention_for_qualified_english_assertion():
    report = audit_text("Maybe I live in Paris.")

    assert report["candidate_count"] == 0
    assert report["clauses"] == []


def test_cli_expect_memory_success(capsys):
    assert main(["I dislike broccoli.", "--expect-memory"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 1
    assert payload["clauses"][0]["candidates"][0]["predicate"] == "dislikes"


def test_cli_expect_memory_fails_when_parser_abstains(capsys):
    assert main(["Maybe I like broccoli.", "--expect-memory"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 0


def test_cli_expect_no_memory_detects_false_positive_candidate(capsys):
    assert main(["I like broccoli.", "--expect-no-memory"]) == 1
    capsys.readouterr()


def test_cli_expect_no_memory_passes_for_question(capsys):
    assert main(["What do I like?", "--expect-no-memory"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_count"] == 0
