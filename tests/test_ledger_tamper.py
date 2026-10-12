# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tamper-detection tests for the append-only hash chain.

Every test corrupts a valid ledger in some way and asserts that
``Ledger.verify`` reports it (``ok`` is ``False`` and at least one problem
matches the expected line/reason).
"""
from __future__ import annotations

import json

import pytest

from veridex.ledger import Ledger, verify_ledger


def make_data(url, status="VERIFIED", flags=None):
    return {
        "tool_version": "0.3.0",
        "entry_index": 0,
        "source": "crossref",
        "request_url": url,
        "http_status": 200,
        "response_sha256": "a" * 64,
        "response_bytes": 512,
        "from_cache": False,
        "status": status,
        "flags": list(flags or []),
        "evidence_type": "lookup",
    }


def build(path, n=4):
    ledger = Ledger(path)
    for i in range(n):
        ledger.append(make_data(f"https://api.crossref.org/works/10.1/{i}"), "run-1")
    return ledger


def lines_of(path):
    return [json.loads(x) for x in path.read_text().split("\n") if x]


def rewrite(path, objs):
    path.write_text("".join(json.dumps(o) + "\n" for o in objs))


def reasons(result):
    return [p["reason"] for p in result["problems"]]


def test_edit_data_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path)
    objs = lines_of(path)
    objs[1]["data"]["status"] = "NOT_FOUND"
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("entry_hash" in r for r in reasons(result))


def test_edit_data_reports_the_edited_line(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path)
    objs = lines_of(path)
    objs[2]["data"]["http_status"] = 500
    rewrite(path, objs)
    result = verify_ledger(path)
    assert 3 in [p["line"] for p in result["problems"]]


def test_edit_hash_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path)
    objs = lines_of(path)
    objs[1]["entry_hash"] = "f" * 64
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("entry_hash" in r or "prev_hash" in r for r in reasons(result))


def test_edit_genesis_hash_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path)
    objs = lines_of(path)
    objs[0]["prev_hash"] = "1" * 64
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("prev_hash" in r for r in reasons(result))


def test_delete_middle_line_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    del objs[1]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("sequence" in r for r in reasons(result))


def test_delete_middle_line_breaks_prev_hash_link(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    del objs[1]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert any("prev_hash" in r for r in reasons(result))


def test_reorder_lines_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    objs[1], objs[2] = objs[2], objs[1]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("sequence" in r for r in reasons(result))


def test_swap_first_two_lines_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[0], objs[1] = objs[1], objs[0]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False


def test_wrong_prev_hash_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[2]["prev_hash"] = "0" * 64
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("prev_hash" in r for r in reasons(result))


def test_recomputed_entry_hash_with_wrong_prev_still_fails(tmp_path):
    from veridex.ledger import entry_digest

    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[2]["prev_hash"] = "2" * 64
    objs[2]["entry_hash"] = entry_digest(objs[2]["prev_hash"], objs[2]["data"])
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("prev_hash" in r for r in reasons(result))


def test_truncated_file_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    text = path.read_text()
    path.write_text(text[:-3])
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("truncat" in r or "malformed" in r for r in reasons(result))


def test_truncated_file_missing_newline_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    text = path.read_text()
    assert text.endswith("\n")
    path.write_text(text[:-1])
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("truncat" in r for r in reasons(result))


def test_garbage_bytes_are_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    text = path.read_text()
    path.write_text(text + "this is not json\n")
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("malformed JSON" in r for r in reasons(result))


def test_missing_key_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    del objs[1]["data"]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("missing keys" in r for r in reasons(result))


def test_non_hex_entry_hash_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[0]["entry_hash"] = "z" * 64
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("64-char hex" in r for r in reasons(result))


def test_duplicate_line_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs.insert(1, dict(objs[1]))
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False


def test_multiple_tampers_report_multiple_problems(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    objs[1]["data"]["status"] = "ERROR"
    objs[2]["prev_hash"] = "9" * 64
    rewrite(path, objs)
    result = verify_ledger(path)
    assert len(result["problems"]) >= 2


def test_verify_after_valid_append_remains_ok(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = build(path, 4)
    assert ledger.verify()["ok"] is True
    ledger.append(make_data("https://api.crossref.org/works/10.1/extra"), "run-1")
    assert ledger.verify()["ok"] is True


def test_append_refuses_when_tail_is_corrupt(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = build(path, 2)
    path.write_text(path.read_text() + "{broken tail\n")
    with pytest.raises(ValueError):
        ledger.append(make_data("https://api.crossref.org/works/10.1/x"), "run-1")


def test_reordered_with_renumbered_seq_still_breaks_chain(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    objs[1], objs[2] = objs[2], objs[1]
    objs[1]["seq"] = 2
    objs[2]["seq"] = 3
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("prev_hash" in r or "entry_hash" in r for r in reasons(result))


def test_tamper_reports_line_numbers(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 4)
    objs = lines_of(path)
    del objs[2]
    rewrite(path, objs)
    result = verify_ledger(path)
    assert all("line" in p for p in result["problems"])


def test_new_entries_bind_timestamp(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    line = ledger.append(make_data("https://x/1"), "run-1", timestamp="2026-02-02T02:02:02+00:00")
    assert line["data"]["timestamp"] == "2026-02-02T02:02:02+00:00"
    assert ledger.verify()["ok"] is True


def test_edit_top_level_timestamp_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[1]["timestamp"] = "2020-01-01T00:00:00+00:00"
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("timestamp does not match data.timestamp" in r for r in reasons(result))


def test_edit_data_timestamp_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    objs = lines_of(path)
    objs[1]["data"]["timestamp"] = "2020-01-01T00:00:00+00:00"
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("timestamp" in r for r in reasons(result))


def test_extra_top_level_key_is_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 2)
    objs = lines_of(path)
    objs[0]["source"] = "tampered"
    rewrite(path, objs)
    result = verify_ledger(path)
    assert result["ok"] is False
    assert any("unexpected top-level keys" in r for r in reasons(result))


def test_legacy_entry_without_data_timestamp_still_verifies(tmp_path):
    from veridex.ledger import GENESIS_HASH, entry_digest

    path = tmp_path / "l.jsonl"
    data = {"url": "https://x/1", "run_id": "run-1"}
    line = {
        "seq": 1,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "prev_hash": GENESIS_HASH,
        "data": data,
        "entry_hash": entry_digest(GENESIS_HASH, data),
    }
    rewrite(path, [line])
    assert verify_ledger(path)["ok"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
