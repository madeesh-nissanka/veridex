# VERIDEX usage guide

Install (core is stdlib-only, Python 3.10+):

```bash
pip install .                    # from a checkout
pip install ".[semantic]"        # optional local embedding similarity extra
```

Every subcommand accepts the global flags shown by `veridex --help`:
`--json`, `--quiet`, `--verbose`, `--policy PATH`, `--sources a,b|no-x`,
`--cache-dir DIR`, `--no-cache`, `--workers N`, `--out DIR`, `--ledger PATH`,
`--format FMT`, `--manuscript PATH`, `--retraction-file PATH`, `--semantic`,
`--resume`.

## Quick start

```bash
veridex audit refs.bib --out audit_out            # full audit + md/html/json/csv/sarif reports
veridex audit manuscript.docx --format all --json     # DOCX input, machine-readable summary
veridex audit refs.txt --ledger ledger.jsonl --resume   # skip entries already checkpointed
veridex dashboard refs.bib --out review.html      # offline review page (accept/reject/export)
```

The legacy v0.1 form still works: `veridex FILE [--out DIR] [--format FMT]`.

## Subcommands

| command | what it does |
|---|---|
| `parse FILE` | read any supported input and print normalized references (`--json`) |
| `resolve FILE` | resolve then audit references (v0.1 compatibility alias of `audit`) |
| `lookup IDS_FILE` | batch identifier lookup: one DOI/URL/PMID/arXiv-ID/ISBN per line, compact matched metadata out (`--json` for machines) |
| `audit FILE` | full pipeline: parse, resolve, match, score, ledger, reports |
| `repair FILE [--out DIR]` | corrected BibTeX/RIS/CSL-JSON + `repair_log.json`, each change traceable to a source record; input files are never modified |
| `report FILE --out DIR` | run the audit and write only the selected report (`--format md|html|json|csv|sarif`) |
| `dashboard FILE --out review.html` | self-contained offline HTML review dashboard |
| `cross-check MANUSCRIPT` | in-text citations vs reference list cross-check (DOCX/plain text) |
| `verify-ledger LEDGER` | validate the append-only hash chain (tamper check) |
| `diff LEDGER RUN_A RUN_B` | ledger diff between two runs: NEW / CHANGED / UNCHANGED / REMOVED |
| `policy FILE` | evaluate the audit against a policy file (see [policy.md](policy.md)) |

The `sarif` report format is SARIF 2.1.0 and can be uploaded straight into
GitHub code scanning (`github/codeql-action/upload-sarif`); see the
`Upload SARIF` step in `ci/github-actions-ci.yml`. Conformance is checked by
`tests/test_sarif_schema.py` (offline structural validator).

## Resolvers

Adapters: Crossref, OpenAlex, DataCite, PubMed, Europe PMC, Semantic Scholar,
arXiv, OpenLibrary, DOAJ. Enable a subset per run:

```bash
veridex audit refs.bib --sources crossref,openalex
veridex audit refs.bib --sources no-semscholar   # everything except one
```

Responses can be cached on disk per run (`--cache-dir DIR`; opt-in, off by
default — `--no-cache` is kept as a v0.1 compatibility alias). Requests are
retried politely and rate-limited per source. All HTTP traffic uses one
stdlib client with per-source limits.

## Retractions

By default retractions are detected from Crossref/OpenAlex update fields.
For offline corpora point at an open Retraction Watch CSV or Crossref update
JSON (`--retraction-file`); matched citations are flagged `RETRACTED` with the
retraction DOI as evidence.

## Exit codes

| code | meaning |
|---|---|
| 0 | OK |
| 1 | policy violation (`fail_on` conditions met) |
| 2 | usage / input error |
| 3 | internal error |
| 4 | tampered or unverifiable ledger |

## Python API

```python
from veridex import api
results = api.audit_references("refs.bib", sources=["crossref"], ledger_path="ledger.jsonl")
rows = api.lookup_references("ids.txt", sources=["crossref"])  # compact per-line lookup
summary = api.verify_ledger("ledger.jsonl")   # {"ok": bool, "problems": [...]}
```

See `SKILL.md` for an agent-oriented summary of the CLI contract.
