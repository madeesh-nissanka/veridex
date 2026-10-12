# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Optional live smoke test. Performs ONE real bibliographic query per
registered resolver source using generic textbook topics. Requires network.
Exit code 0 only if every source returns an HTTP 2xx.

Usage: python3 scripts/live_smoke.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

from veridex import api  # noqa: F401  (registers resolver adapters)
from veridex.httpclient import HttpClient
from veridex.resolvers import build, source_names

QUERIES = {
    "crossref": {"text": "consolidation settlement of soft clay"},
    "openalex": {"search": "slope stability analysis"},
    "datacite": {"query": "concrete durability"},
    "pubmed": {"query": "beam deflection"},
    "europepmc": {"query": "heat conduction"},
    "semscholar": {"query": "bearing capacity of soils"},
    "arxiv": {"query": "heat conduction"},
    "openlibrary": {"query": "soil mechanics"},
    "doaj": {"query": "pavement fatigue"},
}


def main() -> int:
    client = HttpClient(user_agent="veridex-live-smoke/0.2", timeout=30,
                        min_interval=1.0)
    failures = 0
    for name in source_names():
        source = build(name, client)
        if source is None:
            print(f"{name:12s} SKIP (no adapter)")
            continue
        records, evidence = source.search(QUERIES[name])
        ev = evidence[0] if evidence else None
        status = getattr(ev, "http_status", 0)
        error = getattr(ev, "error", "") or ""
        ok = bool(status and 200 <= status < 300)
        mark = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{name:12s} {mark} status={status} records={len(records)} {error}")
    total = len(source_names())
    print(f"smoke: {total - failures}/{total} sources answered 2xx")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
