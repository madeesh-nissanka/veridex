# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
# VERIDEX agent skill

VERIDEX audits reference lists against public scholarly sources and records a
tamper-evident provenance ledger. The core is stdlib-only; network use happens
only through the resolver adapters.

## When to use

- Validate a bibliography (`.bib`, `.ris`, `.txt`, CSL JSON, EndNote XML, DOCX).
- Detect fabricated, mis-cited, duplicate, retracted or corrupted references.
- Produce a provenance ledger and verify it later.
- Enforce a policy (exit code 1 on violation).

## Subcommands

| Command | Purpose |
| --- | --- |
| `parse FILE` | Parse references only (no network). |
| `resolve FILE` | Resolve then audit references. |
| `lookup IDS_FILE` | Batch identifier lookup (DOI/URL/PMID/arXiv/ISBN per line); compact matched metadata, `--json` supported. |
| `audit FILE` | Parse + resolve + evaluate + optional policy/ledger. |
| `repair FILE [--out DIR]` | Suggest corrected fields; `--out` writes repaired.bib/.ris/.csl.json + repair_log.json (never overwrites). |
| `report FILE --out DIR` | Audit and write a report. |
| `dashboard FILE --out DIR` | Audit and write a self-contained offline HTML review dashboard (filter/sort, accept/reject, notes, JSON/CSV export). |
| `verify-ledger PATH` | Verify the hash chain. |
| `diff LEDGER RUN_A RUN_B` | Diff two runs by request URL. |
| `policy PATH` | Validate a policy file. |
| `about` | Print name/version/license/copyright. |

## Global flags

`--version`, `--json`, `--quiet`, `--verbose`, `--policy PATH`,
`--sources a,b` (prefix a source with `no-` to disable, e.g. `no-arxiv`),
`--cache-dir DIR`, `--no-cache`, `--workers N`, `--out DIR`, `--ledger PATH`,
`--format FMT`, `--legacy-status`, `--manuscript PATH`, `--retraction-file PATH`.

## Exit codes

- `0` clean
- `1` policy violation
- `2` usage error
- `3` internal error
- `4` ledger tamper

## JSON output

`--json` writes a single object to stdout. `audit` returns:

```json
{
  "tool": "veridex",
  "version": "0.2.0",
  "summary": {"VERIFIED": 2, "NOT_FOUND": 1},
  "violations": [],
  "results": [
    {"index": 0, "status": "VERIFIED", "flags": [], "scores": {}}
  ]
}
```

`verify-ledger` returns `{"ok": true, "problems": []}`.

## Examples

```
veridex about --json
veridex parse examples/refs.bib --json
veridex audit examples/refs.bib --policy examples/policy.yaml
veridex audit examples/refs.bib --out audit --format json --ledger run.jsonl
veridex verify-ledger run.jsonl
veridex refs.txt --out audit --format text   # v0.1 compatible
```

## Programmatic use

```python
from veridex import api

results = api.audit_references("examples/refs.bib", ledger_path="run.jsonl")
for r in results:
    print(r.index, r.status)

report = api.verify_ledger("run.jsonl")
```

Set `api.TRANSPORT` to a `callable(url, timeout) -> Response` in tests to keep
everything offline.
