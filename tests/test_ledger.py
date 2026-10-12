# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Functional tests for the append-only hash-chained provenance ledger."""
from __future__ import annotations

import hashlib
import json

import pytest

from veridex.ledger import (
    GENESIS_HASH,
    Ledger,
    audit_diff,
    canonical_json,
    diff_ledgers,
    entry_digest,
    latest_by_url,
    read_records,
    verify_ledger,
)


def make_data(url="https://api.crossref.org/works/10.1/a", status="VERIFIED", flags=None, **extra):
    data = {
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
    data.update(extra)
    return data


def build(path, n=3, run_id="run-1", url_prefix="https://api.crossref.org/works/10.1/"):
    ledger = Ledger(path)
    for i in range(n):
        ledger.append(make_data(url=f"{url_prefix}{i}", entry_index=i), run_id, timestamp=f"2026-01-0{i + 1}T00:00:00+00:00")
    return ledger


def test_genesis_hash_constant_is_64_zeros():
    assert GENESIS_HASH == "0" * 64


def test_first_append_links_to_genesis(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    line = ledger.append(make_data(), "run-1")
    assert line["prev_hash"] == GENESIS_HASH
    assert line["seq"] == 1


def test_append_returns_line_with_expected_keys(tmp_path):
    line = Ledger(tmp_path / "l.jsonl").append(make_data(), "run-1")
    assert set(line) == {"seq", "timestamp", "prev_hash", "data", "entry_hash"}


def test_seq_increments_monotonically(tmp_path):
    ledger = build(tmp_path / "l.jsonl", 4)
    seqs = [json.loads(x)["seq"] for x in (tmp_path / "l.jsonl").read_text().split("\n") if x]
    assert seqs == [1, 2, 3, 4]
    assert ledger.verify()["ok"] is True


def test_entry_hash_matches_documented_formula(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    line = ledger.append({"b": 2, "a": 1}, "run-x")
    canonical = json.dumps(line["data"], sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256((GENESIS_HASH + canonical).encode("utf-8")).hexdigest()
    assert line["entry_hash"] == expected


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"a": 1, "b": [2, 3]}) == '{"a":1,"b":[2,3]}'


def test_key_order_does_not_change_digest(tmp_path):
    ledger1 = Ledger(tmp_path / "l1.jsonl")
    ledger2 = Ledger(tmp_path / "l2.jsonl")
    first = ledger1.append({"a": 1, "b": 2}, "run-1", timestamp="2026-01-01T00:00:00+00:00")
    second = ledger2.append({"b": 2, "a": 1}, "run-1", timestamp="2026-01-01T00:00:00+00:00")
    assert first["entry_hash"] == second["entry_hash"]


def test_prev_hash_links_consecutive_lines(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    lines = [json.loads(x) for x in path.read_text().split("\n") if x]
    assert lines[1]["prev_hash"] == lines[0]["entry_hash"]
    assert lines[2]["prev_hash"] == lines[1]["entry_hash"]


def test_default_timestamp_is_utc_isoformat(tmp_path):
    line = Ledger(tmp_path / "l.jsonl").append(make_data(), "run-1")
    assert line["timestamp"].endswith("+00:00")
    assert "T" in line["timestamp"]


def test_custom_timestamp_is_used(tmp_path):
    line = Ledger(tmp_path / "l.jsonl").append(make_data(), "run-1", timestamp="2030-05-05T05:05:05+00:00")
    assert line["timestamp"] == "2030-05-05T05:05:05+00:00"


def test_append_stamps_run_id(tmp_path):
    line = Ledger(tmp_path / "l.jsonl").append(make_data(), "run-42")
    assert line["data"]["run_id"] == "run-42"


def test_append_does_not_mutate_input(tmp_path):
    payload = make_data()
    Ledger(tmp_path / "l.jsonl").append(payload, "run-1")
    assert "run_id" not in payload


def test_verify_missing_file_is_detected(tmp_path):
    result = Ledger(tmp_path / "missing.jsonl").verify()
    assert result["ok"] is False
    assert result["problems"][0]["reason"].startswith("ledger file not found")


def test_verify_empty_file_ok(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert verify_ledger(path)["ok"] is True


def test_verify_valid_chain_ok(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 5)
    result = Ledger(path).verify()
    assert result == {"ok": True, "problems": []}


def test_read_records_returns_all_in_order(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    records = read_records(path)
    assert [r["entry_index"] for r in records] == [0, 1, 2]
    assert all(r["run_id"] == "run-1" for r in records)


def test_read_records_filters_by_run_id(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1"), "run-a")
    ledger.append(make_data(url="https://x/2"), "run-b")
    assert [r["request_url"] for r in read_records(path, "run-b")] == ["https://x/2"]


def test_read_records_missing_file_is_empty(tmp_path):
    assert read_records(tmp_path / "nope.jsonl") == []


def test_latest_by_url_last_wins(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1", status="NOT_FOUND"), "run-1")
    ledger.append(make_data(url="https://x/1", status="VERIFIED"), "run-1")
    assert latest_by_url(path)["https://x/1"]["status"] == "VERIFIED"


def test_latest_by_url_filters_run(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1", status="NOT_FOUND"), "run-a")
    ledger.append(make_data(url="https://x/1", status="VERIFIED"), "run-b")
    assert latest_by_url(path, "run-a")["https://x/1"]["status"] == "NOT_FOUND"
    assert latest_by_url(path, "run-b")["https://x/1"]["status"] == "VERIFIED"


def test_diff_new_key(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1"), "a")
    ledger.append(make_data(url="https://x/2"), "b")
    rows = diff_ledgers(path, "a", "b")
    assert len(rows) == 2
    changes = {r["key"]: r["change"] for r in rows}
    assert changes["https://x/1"] == "REMOVED"
    assert changes["https://x/2"] == "NEW"


def test_diff_removed_key(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1"), "a")
    ledger.append(make_data(url="https://x/2"), "b")
    rows = diff_ledgers(path, "b", "a")
    assert len(rows) == 2
    changes = {r["key"]: r["change"] for r in rows}
    assert changes["https://x/1"] == "NEW"
    assert changes["https://x/2"] == "REMOVED"


def test_diff_unchanged_key(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1", status="VERIFIED"), "a")
    ledger.append(make_data(url="https://x/1", status="VERIFIED"), "b")
    rows = diff_ledgers(path, "a", "b")
    assert rows[0]["change"] == "UNCHANGED"
    assert rows[0]["changed_flags"] == []


def test_diff_changed_status(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1", status="NOT_FOUND"), "a")
    ledger.append(make_data(url="https://x/1", status="VERIFIED"), "b")
    rows = diff_ledgers(path, "a", "b")
    assert rows[0]["change"] == "CHANGED"
    assert rows[0]["old_status"] == "NOT_FOUND"
    assert rows[0]["new_status"] == "VERIFIED"


def test_diff_changed_flags_symmetric(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append(make_data(url="https://x/1", flags=["year_mismatch"]), "a")
    ledger.append(make_data(url="https://x/1", flags=["author_mismatch", "year_mismatch"]), "b")
    rows = diff_ledgers(path, "a", "b")
    assert rows[0]["changed_flags"] == ["author_mismatch"]


def test_diff_sorted_by_key(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    for url in ("https://x/c", "https://x/a", "https://x/b"):
        ledger.append(make_data(url=url), "a")
        ledger.append(make_data(url=url), "b")
    rows = diff_ledgers(path, "a", "b")
    assert [r["key"] for r in rows] == ["https://x/a", "https://x/b", "https://x/c"]


def test_audit_diff_status_change():
    a = {"status": "NOT_FOUND", "flags": []}
    b = {"status": "VERIFIED", "flags": []}
    assert audit_diff(a, b) == ["status: NOT_FOUND -> VERIFIED"]


def test_audit_diff_flag_added_and_removed():
    a = {"status": "VERIFIED", "flags": ["year_mismatch"]}
    b = {"status": "VERIFIED", "flags": ["author_mismatch"]}
    assert "flag removed: year_mismatch" in audit_diff(a, b)
    assert "flag added: author_mismatch" in audit_diff(a, b)


def test_audit_diff_scores_and_record():
    a = {"status": "VERIFIED", "scores": {"title": 0.9}, "record": {"title": "Old"}}
    b = {"status": "VERIFIED", "scores": {"title": 0.5}, "record": {"title": "New"}}
    diffs = audit_diff(a, b)
    assert "score title: 0.9 -> 0.5" in diffs
    assert "record.title: Old -> New" in diffs


def test_audit_diff_identical_is_empty():
    same = {"status": "VERIFIED", "flags": ["x"], "scores": {"t": 1.0}, "fabrication": {"score": 0.0}}
    assert audit_diff(same, dict(same)) == []


def test_audit_diff_fabrication_and_evidence_counts():
    a = {"status": "VERIFIED", "fabrication": {"score": 0.1}, "evidence": [{}]}
    b = {"status": "VERIFIED", "fabrication": {"score": 0.4}, "evidence": [{}, {}]}
    diffs = audit_diff(a, b)
    assert "fabrication score: 0.1 -> 0.4" in diffs
    assert "evidence count: 1 -> 2" in diffs


def test_append_creates_parent_directories(tmp_path):
    path = tmp_path / "deep" / "nested" / "l.jsonl"
    Ledger(path).append(make_data(), "run-1")
    assert path.exists()


def test_file_is_jsonl_one_object_per_line(tmp_path):
    path = tmp_path / "l.jsonl"
    build(path, 3)
    text = path.read_text()
    assert text.endswith("\n")
    for raw in text.split("\n")[:-1]:
        obj = json.loads(raw)
        assert obj["data"]["run_id"] == "run-1"


def test_entry_digest_helper_matches_ledger(tmp_path):
    line = Ledger(tmp_path / "l.jsonl").append({"k": "v"}, "run-1")
    assert entry_digest(GENESIS_HASH, line["data"]) == line["entry_hash"]


def test_data_keys_are_preserved(tmp_path):
    payload = make_data(entry_index=7, source="openalex", evidence_type="search")
    line = Ledger(tmp_path / "l.jsonl").append(payload, "run-1")
    for key in ("tool_version", "entry_index", "source", "evidence_type"):
        assert line["data"][key] == payload[key]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
