"""Tests for the read-only memory parser audit utility."""

import json

from ai_baby.memory_audit import audit_fixture_file, audit_text, main


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


def test_batch_fixture_file_checks_positive_and_negative_cases(tmp_path, capsys):
    cases = tmp_path / "memory-cases.jsonl"
    cases.write_text(
        "\n".join(
            [
                json.dumps({"id": "like", "text": "I like tea.", "expect": "memory"}),
                json.dumps(
                    {
                        "id": "qualified",
                        "text": "Maybe I live in Paris.",
                        "expect": "no-memory",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert main(["--cases", str(cases)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["case_count"] == 2
    assert payload["failed_count"] == 0
    assert [case["id"] for case in payload["cases"]] == ["like", "qualified"]
    assert all(case["matched"] for case in payload["cases"])


def test_batch_fixture_failure_returns_one_and_reports_mismatch(tmp_path, capsys):
    cases = tmp_path / "memory-cases.jsonl"
    cases.write_text(
        json.dumps({"id": "false-negative", "text": "I like tea.", "expect": "no-memory"}),
        encoding="utf-8",
    )

    assert main(["--cases", str(cases)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["failed_count"] == 1
    assert payload["cases"][0]["matched"] is False
    assert payload["cases"][0]["candidate_count"] == 1


def test_batch_fixture_audit_does_not_touch_database(tmp_path, baby):
    cases = tmp_path / "memory-cases.jsonl"
    cases.write_text(
        json.dumps({"text": "I dislike broccoli.", "expect": "memory"}),
        encoding="utf-8",
    )
    before = baby.memory.db.execute("SELECT count(*) FROM facts").fetchone()[0]

    report = audit_fixture_file(str(cases))

    after = baby.memory.db.execute("SELECT count(*) FROM facts").fetchone()[0]
    assert before == after
    assert report["failed_count"] == 0


def test_batch_fixture_validation_returns_usage_error(tmp_path, capsys):
    cases = tmp_path / "memory-cases.jsonl"
    cases.write_text('{"text":"I like tea.","expect":"sometimes"}\n', encoding="utf-8")

    assert main(["--cases", str(cases)]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "line 1" in output.err
    assert "expect must be 'memory' or 'no-memory'" in output.err


def test_batch_mode_rejects_single_text_expectation_flags(tmp_path, capsys):
    cases = tmp_path / "memory-cases.jsonl"
    cases.write_text(
        json.dumps({"text": "I like tea.", "expect": "memory"}), encoding="utf-8"
    )

    assert main(["--cases", str(cases), "--expect-memory"]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "cannot be combined" in output.err
