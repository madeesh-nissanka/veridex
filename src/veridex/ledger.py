# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Append-only JSONL provenance ledger with a tamper-evident hash chain.

Each line is one JSON object::

    {"seq": n, "timestamp": iso, "prev_hash": hex, "data": {...}, "entry_hash": hex}

where ``entry_hash = sha256(prev_hash + canonical_json(data))`` and::

    canonical_json(data) = json.dumps(data, sort_keys=True, separators=(",", ":"))

The first line links to a genesis ``prev_hash`` of 64 zero characters, so any
edit, deletion, reorder or truncation of the file breaks the chain and is
reported by :meth:`Ledger.verify`. The hashed ``data`` payload also carries
``run_id`` and ``timestamp``, unexpected top-level line keys are rejected,
and a line ``timestamp`` that no longer matches ``data.timestamp`` is
reported, so metadata edits and added fields are tamper-evident too.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

GENESIS_HASH = "0" * 64
_HASH_ALPHABET = set("0123456789abcdef")
_TAIL_CHUNK = 65536


def canonical_json(data: Any) -> str:
    """Deterministic JSON text for hashing (sorted keys, compact separators)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def entry_digest(prev_hash: str, data: Any) -> str:
    """SHA-256 over ``prev_hash`` followed by the canonical JSON of ``data``."""
    payload = (prev_hash + canonical_json(data)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    """Current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HASH_ALPHABET


def _split_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, text)`` for non-empty lines, 1-based numbers."""
    out: list[tuple[int, str]] = []
    for number, raw in enumerate(text.split("\n"), start=1):
        if raw.strip() == "":
            continue
        out.append((number, raw))
    return out


class Ledger:
    """Append-only hash-chained ledger stored as JSONL at ``path``."""

    def __init__(self, path: "str | os.PathLike[str]") -> None:
        self.path = Path(path)

    # -- writing ---------------------------------------------------------
    def append(
        self,
        data: dict[str, Any],
        run_id: str,
        timestamp: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append one record and return the stored line object.

        ``data`` is copied and stamped with ``run_id`` and ``timestamp``
        inside the hashed payload; the caller's dict is left untouched.
        ``timestamp`` defaults to the current UTC instant.
        """
        record: dict[str, Any] = dict(data)
        record["run_id"] = run_id
        ts = timestamp if timestamp is not None else _utc_now()
        record["timestamp"] = ts

        seq, prev_hash = self._tail()
        line: dict[str, Any] = {
            "seq": seq,
            "timestamp": ts,
            "prev_hash": prev_hash,
            "data": record,
            "entry_hash": entry_digest(prev_hash, record),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, separators=(",", ":")) + "\n")
        return line

    def _tail(self) -> tuple[int, str]:
        """Return ``(next_seq, prev_hash)`` based on the current file tail.

        Only the tail of the file is read (lines are single-line compact
        JSON), so appending stays O(1) per record instead of re-reading the
        whole ledger every time.
        """
        if not self.path.exists():
            return 1, GENESIS_HASH
        entries: list[tuple[int, str]] = []
        size = self.path.stat().st_size
        if size:
            with open(self.path, "r", encoding="utf-8") as handle:
                if size > _TAIL_CHUNK:
                    handle.seek(size - _TAIL_CHUNK)
                    handle.readline()
                entries = _split_lines(handle.read())
        if not entries:
            if size > _TAIL_CHUNK:
                entries = _split_lines(self.path.read_text(encoding="utf-8"))
            if not entries:
                return 1, GENESIS_HASH
        _, last = entries[-1]
        try:
            obj = json.loads(last)
        except json.JSONDecodeError as exc:
            raise ValueError(f"cannot append: last line is not valid JSON: {exc}") from exc
        if not isinstance(obj, dict) or "seq" not in obj or "entry_hash" not in obj:
            raise ValueError("cannot append: last line is missing seq/entry_hash")
        return int(obj["seq"]) + 1, str(obj["entry_hash"])

    # -- verification ----------------------------------------------------
    def verify(self) -> dict[str, Any]:
        """Validate the whole chain and return ``{"ok", "problems"}``."""
        problems: list[dict[str, Any]] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {
                "ok": False,
                "problems": [{"line": 0, "reason": f"ledger file not found: {self.path}"}],
            }

        if text == "":
            return {"ok": True, "problems": []}

        truncated = not text.endswith("\n")
        if truncated:
            problems.append(
                {"line": text.count("\n") + 1, "reason": "truncated file: missing final newline"}
            )

        expected_prev = GENESIS_HASH
        expected_seq = 1
        for number, raw in _split_lines(text):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                problems.append({"line": number, "reason": "malformed JSON (possible truncation)"})
                continue

            if not isinstance(obj, dict):
                problems.append({"line": number, "reason": "line is not a JSON object"})
                continue

            missing = [k for k in ("seq", "timestamp", "prev_hash", "data", "entry_hash") if k not in obj]
            if missing:
                problems.append({"line": number, "reason": f"missing keys: {','.join(missing)}"})
                continue

            extra = sorted(set(obj) - {"seq", "timestamp", "prev_hash", "data", "entry_hash"})
            if extra:
                problems.append(
                    {"line": number, "reason": "unexpected top-level keys: " + ",".join(extra)}
                )
                continue

            data_value = obj.get("data")
            if (
                isinstance(data_value, dict)
                and "timestamp" in data_value
                and data_value["timestamp"] != obj.get("timestamp")
            ):
                problems.append({"line": number, "reason": "timestamp does not match data.timestamp"})

            if obj.get("seq") != expected_seq:
                problems.append(
                    {"line": number, "reason": f"sequence mismatch: expected {expected_seq}, found {obj.get('seq')!r}"}
                )

            if not _is_hash(obj.get("entry_hash")):
                problems.append({"line": number, "reason": "entry_hash is not a 64-char hex digest"})

            if obj.get("prev_hash") != expected_prev:
                problems.append(
                    {"line": number, "reason": "prev_hash does not match previous entry_hash"}
                )

            expected_digest = entry_digest(str(obj.get("prev_hash")), obj.get("data"))
            if obj.get("entry_hash") != expected_digest:
                problems.append({"line": number, "reason": "entry_hash does not match data"})

            expected_prev = str(obj.get("entry_hash"))
            expected_seq = int(obj.get("seq")) + 1 if isinstance(obj.get("seq"), int) else expected_seq + 1

        return {"ok": not problems, "problems": problems}


# -- module-level helpers ------------------------------------------------
def verify_ledger(path: "str | os.PathLike[str]") -> dict[str, Any]:
    """Verify the ledger at ``path`` (convenience wrapper)."""
    return Ledger(path).verify()


def read_records(
    path: "str | os.PathLike[str]", run_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Return record ``data`` dicts in file order, optionally filtered by run."""
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    for _, raw in _split_lines(target.read_text(encoding="utf-8")):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        data = obj.get("data")
        if not isinstance(data, dict):
            continue
        if run_id is not None and data.get("run_id") != run_id:
            continue
        records.append(data)
    return records


def latest_by_url(
    path: "str | os.PathLike[str]", run_id: Optional[str] = None
) -> dict[str, dict[str, Any]]:
    """Map ``request_url`` to the most recent record for that URL.

    Later lines win, so the result is deterministic regardless of dict order.
    """
    latest: dict[str, dict[str, Any]] = {}
    for data in read_records(path, run_id):
        url = data.get("request_url")
        if isinstance(url, str) and url:
            latest[url] = data
    return latest


def diff_ledgers(
    path: "str | os.PathLike[str]", run_a: str, run_b: str
) -> list[dict[str, Any]]:
    """Compare the latest per-URL records of two runs.

    Rows are ``{"key", "change", "old_status", "new_status", "changed_flags"}``
    with ``change`` one of ``NEW``, ``CHANGED``, ``UNCHANGED``, ``REMOVED``.
    """
    old = latest_by_url(path, run_a)
    new = latest_by_url(path, run_b)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        old_rec = old.get(key)
        new_rec = new.get(key)
        old_status = old_rec.get("status") if old_rec else None
        new_status = new_rec.get("status") if new_rec else None
        old_flags = set(old_rec.get("flags") or []) if old_rec else set()
        new_flags = set(new_rec.get("flags") or []) if new_rec else set()
        changed = sorted(old_flags ^ new_flags)
        if old_rec is None:
            change = "NEW"
        elif new_rec is None:
            change = "REMOVED"
        elif old_status == new_status and old_flags == new_flags:
            change = "UNCHANGED"
        else:
            change = "CHANGED"
        rows.append(
            {
                "key": key,
                "change": change,
                "old_status": old_status,
                "new_status": new_status,
                "changed_flags": changed,
            }
        )
    return rows


def audit_diff(result_a: dict[str, Any], result_b: dict[str, Any]) -> list[str]:
    """Field-level diff between two AuditResult-shaped dicts.

    Returns human-readable change strings in a deterministic order.
    """
    diffs: list[str] = []

    if result_a.get("status") != result_b.get("status"):
        diffs.append(f"status: {result_a.get('status')} -> {result_b.get('status')}")

    flags_a = set(result_a.get("flags") or [])
    flags_b = set(result_b.get("flags") or [])
    for flag in sorted(flags_a - flags_b):
        diffs.append(f"flag removed: {flag}")
    for flag in sorted(flags_b - flags_a):
        diffs.append(f"flag added: {flag}")

    scores_a = result_a.get("scores") or {}
    scores_b = result_b.get("scores") or {}
    for key in sorted(set(scores_a) | set(scores_b)):
        if scores_a.get(key) != scores_b.get(key):
            diffs.append(f"score {key}: {scores_a.get(key)} -> {scores_b.get(key)}")

    fab_a = (result_a.get("fabrication") or {}).get("score")
    fab_b = (result_b.get("fabrication") or {}).get("score")
    if fab_a != fab_b:
        diffs.append(f"fabrication score: {fab_a} -> {fab_b}")

    rec_a = result_a.get("record") or {}
    rec_b = result_b.get("record") or {}
    for key in ("title", "doi", "year"):
        if rec_a.get(key) != rec_b.get(key):
            diffs.append(f"record.{key}: {rec_a.get(key)} -> {rec_b.get(key)}")

    kinds_a = sorted(
        str(item.get("kind")) for item in (result_a.get("integrity") or []) if isinstance(item, dict)
    )
    kinds_b = sorted(
        str(item.get("kind")) for item in (result_b.get("integrity") or []) if isinstance(item, dict)
    )
    if kinds_a != kinds_b:
        diffs.append(f"integrity kinds: {kinds_a} -> {kinds_b}")

    evidence_a = len(result_a.get("evidence") or [])
    evidence_b = len(result_b.get("evidence") or [])
    if evidence_a != evidence_b:
        diffs.append(f"evidence count: {evidence_a} -> {evidence_b}")

    return diffs


__all__ = [
    "GENESIS_HASH",
    "Ledger",
    "audit_diff",
    "canonical_json",
    "diff_ledgers",
    "entry_digest",
    "latest_by_url",
    "read_records",
    "verify_ledger",
]
