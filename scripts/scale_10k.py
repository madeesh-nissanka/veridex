# VERIDEX v0.3.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Measured scale run: 10,000 synthetic references, offline transport.

Generates a 10k-entry plain numbered list, audits it against an in-memory
fake resolver transport (no network), then reports wall time, peak RSS,
ledger size and resume behaviour. Used to verify memory-bounded batched
auditing. Stdlib only.

Usage: python3 scripts/scale_10k.py [--count N] [--batch B]
"""
from __future__ import annotations

import argparse
import resource
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "src")

from veridex import api
from veridex.httpclient import Response
from veridex.ledger import read_records

TOPICS = [
    "soil consolidation settlement",
    "slope stability analysis",
    "bearing capacity of shallow foundations",
    "concrete durability under freeze-thaw cycles",
    "pavement fatigue cracking",
    "steel beam deflection",
    "heat conduction in composite walls",
]


def fake_transport(url: str, timeout: float | None = None) -> Response:
    return Response(
        url=url, status=200, body=b'{"message": {"items": []}}', from_cache=False
    )


def build_refs(count: int) -> str:
    lines = []
    for i in range(1, count + 1):
        topic = TOPICS[i % len(TOPICS)]
        lines.append(
            f"[{i}] Author, A. B. and Carter, C. ({2000 + (i % 24)}). "
            f"{topic.title()} revisited, {i}. Journal of Generic Engineering, "
            f"{10 + (i % 40)}({1 + (i % 12)}), {1 + (i % 90)}-{2 + (i % 90)}."
        )
    return "\n".join(lines) + "\n"


def peak_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--batch", type=int, default=1000)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        refs_path = Path(tmp, "refs.txt")
        refs_path.write_text(build_refs(args.count), encoding="utf-8")
        ledger = str(Path(tmp, "ledger.jsonl"))

        api.TRANSPORT = fake_transport
        start = time.perf_counter()
        results = api.audit_references(
            str(refs_path),
            sources=["crossref"],
            ledger_path=ledger,
            batch_size=args.batch,
            cache_dir=None,
            max_workers=4,
        )
        elapsed = time.perf_counter() - start
        rss = peak_kb()
        size = Path(ledger).stat().st_size
        entries = read_records(ledger)
        lookups = sum(1 for e in entries if e.get("evidence_type") == "lookup")
        checkpoints = sum(1 for e in entries if e.get("evidence_type") == "checkpoint")
        verify = api.verify_ledger(ledger)
        statuses: dict[str, int] = {}
        for r in results:
            statuses[r.status] = statuses.get(r.status, 0) + 1

        # Resume: same input + sources must skip every checkpointed entry.
        calls = 0
        def counting(url: str, timeout: float | None = None) -> Response:
            nonlocal calls
            calls += 1
            return fake_transport(url, timeout)

        api.TRANSPORT = counting
        start2 = time.perf_counter()
        resumed = api.audit_references(
            str(refs_path),
            sources=["crossref"],
            ledger_path=ledger,
            batch_size=args.batch,
            cache_dir=None,
            max_workers=4,
            resume_from="auto",
        )
        elapsed2 = time.perf_counter() - start2

        print(f"references           {args.count}")
        print(f"batch_size           {args.batch}")
        print(f"audit time           {elapsed:.2f} s")
        print(f"peak RSS             {rss / 1024:.1f} MB")
        print(f"ledger size          {size} bytes")
        print(f"ledger entries       {len(entries)} (lookup {lookups}, checkpoint {checkpoints})")
        print(f"ledger verified      {verify['ok']}")
        print(f"status histogram     {statuses}")
        print(f"resume time          {elapsed2:.2f} s")
        print(f"resume network calls {calls}")
        print(f"resume results       {len(resumed)}")

        problems = []
        if len(results) != args.count:
            problems.append(f"expected {args.count} results, got {len(results)}")
        if not verify["ok"]:
            problems.append("ledger chain invalid")
        if calls != 0:
            problems.append(f"resume re-queried {calls} entries")
        if len(resumed) != args.count:
            problems.append(f"resume returned {len(resumed)} results")
        if [r.index for r in resumed] != sorted(r.index for r in resumed):
            problems.append("resume output not in input order")
        if [ (r.index, r.status) for r in resumed ] != [ (r.index, r.status) for r in results ]:
            problems.append("resume statuses differ from first run")
        if problems:
            for p in problems:
                print(f"FAIL: {p}")
            return 1
        print("SCALE RUN OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
