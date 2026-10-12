# VERIDEX v0.3.0 - reference validation and provenance auditing.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23274732.svg)](https://doi.org/10.5281/zenodo.23274732)

**VERIDEX** validates reference lists against public scholarly sources (Crossref, OpenAlex, DataCite, PubMed, Europe PMC, Semantic Scholar, arXiv, OpenLibrary, DOAJ) and records a tamper-evident provenance ledger. The core is stdlib-only; network access happens only through resolver adapters.

## Features

- **Input parsers**: BibTeX, RIS, CSL-JSON, EndNote XML, plain numbered/author-year lists, free text, DOCX manuscripts, and identifier-only lines (DOI/URL/PMID/arXiv/ISBN)
- **Resolver adapters**: Crossref, OpenAlex, DataCite, PubMed/Europe PMC, Semantic Scholar, arXiv, OpenLibrary (ISBN), DOAJ — per-source on/off via `--sources`
- **Matching engine**: normalized title similarity, author-list comparison (initials, transliteration, order), year/venue/volume/pages consistency, DOI-resolves-to-different-work detection, near-duplicate reference detection
- **Fabrication signals**: no matching record, DOI valid but metadata mismatched, implausible venue/volume/page combinations, impossible dates, author-set mismatch — with explainable scores
- **Integrity flags**: retractions, corrections, expressions of concern, preprint-vs-published pairing, withdrawn versions — plus an **offline** retraction/update loader (`--retraction-file`) for Retraction Watch CSV, Crossref update JSON, or JSONL
- **Citation-context check** (offline): BM25/TF-IDF comparison of citing sentence with cited record's title/abstract — clearly labeled heuristic
- **Provenance ledger**: append-only JSONL with hash chain, per-record evidence, `verify-ledger` command detects tampering, `diff` between two audits
- **Repair suggestions**: corrected BibTeX/RIS/CSL-JSON output with changed fields listed and traceable to source records; never overwrites silently
- **Reports**: Markdown, HTML (single static file), JSON, CSV, SARIF — summary counts and executive table
- **Review dashboard**: self-contained offline HTML with filter/sort, per-reference accept/reject/pending decisions, notes, and JSON/CSV decision export (stdlib-only generation)
- **Measured accuracy**: an offline labelled benchmark with real precision/recall/F1 per signal reported in [docs/benchmark.md](docs/benchmark.md)
- **Policy file** (YAML/JSON): thresholds, required-fields rules, allowed/blocked venues, fail-on conditions for CI; exit codes
- **Agent-friendliness**: subcommands (`parse`, `resolve`, `lookup`, `audit`, `repair`, `report`, `dashboard`, `verify-ledger`, `diff`, `policy`, `about`), `--json` output, Python API, SKILL.md for LLM agents, pre-commit hook config, GitHub Action example
- **Engineering**: src layout, pyproject.toml, type hints, logging, concurrency with polite rate limits, deterministic output, 471 offline unit tests, CI workflow

## Installation

```bash
pip install -e .
# or for development:
pip install -e ".[dev]"
```

Requires Python 3.10+. No required dependencies (stdlib-only core).

## Documentation

- [docs/usage.md](docs/usage.md) - CLI subcommands, flags, cache, exit codes, Python API
- [docs/architecture.md](docs/architecture.md) - module map and design decisions
- [docs/policy.md](docs/policy.md) - policy file reference for CI gates
- [docs/benchmark.md](docs/benchmark.md) - measured precision/recall/F1 per signal

## Quick Start

```bash
# Print version/about
veridex about

# Parse a bibliography (no network)
veridex parse examples/refs.bib --json

# Audit a bibliography against all sources (offline with --no-cache)
veridex audit examples/refs.bib --no-cache

# Audit with policy enforcement (exit code 1 on violation)
veridex audit examples/refs.bib --policy examples/policy.yaml --no-cache

# Audit and write reports to a directory (Markdown, HTML, JSON, CSV, SARIF)
veridex audit examples/refs.bib --out audit --format md --no-cache

# Audit with tamper-evident ledger
veridex audit examples/refs.bib --ledger run.jsonl --no-cache

# Verify ledger integrity
veridex verify-ledger run.jsonl

# Diff two runs in a ledger
veridex diff run.jsonl run-abc123 run-def456

# Validate a policy file
veridex policy examples/policy.yaml

# Suggest repairs (corrected BibTeX/RIS/CSL-JSON)
veridex repair examples/refs.bib --no-cache

# Audit and write an interactive offline HTML review dashboard
veridex dashboard examples/refs.bib --out review --no-cache

# Flag retracted works using an offline Retraction Watch CSV (no network needed for this check)
veridex audit examples/refs.bib --retraction-file retractions.csv --no-cache

# v0.1 compatible invocation (no subcommand)
veridex refs.txt --out audit --format text
```

## Subcommands

| Command | Purpose |
|---------|---------|
| `parse FILE` | Parse references only (no network). |
| `resolve FILE` | Resolve then audit references. |
| `lookup IDS_FILE` | Batch identifier lookup (DOI/URL/PMID/arXiv/ISBN per line); compact matched metadata, `--json` supported. |
| `audit FILE` | Parse + resolve + evaluate + optional policy/ledger. |
| `repair FILE [--out DIR]` | Suggest corrected fields; `--out` writes `repaired.bib`/`.ris`/`.csl.json` + `repair_log.json` (never overwrites). |
| `report FILE --out DIR` | Audit and write a report. |
| `dashboard FILE --out DIR` | Audit and write a self-contained offline HTML review dashboard (`dashboard.html`) with filter/sort, accept/reject, notes, and JSON/CSV export. |
| `verify-ledger PATH` | Verify the hash chain. |
| `diff LEDGER RUN_A RUN_B` | Diff two runs by request URL. |
| `policy PATH` | Validate a policy file. |
| `about` | Print name/version/license/copyright. |

## Global Flags

`--version`, `--json`, `--quiet`, `--verbose`, `--policy PATH`, `--sources a,b` (prefix a source with `no-` to disable, e.g. `no-arxiv`), `--cache-dir DIR`, `--no-cache`, `--workers N`, `--out DIR`, `--ledger PATH`, `--format FMT`, `--legacy-status`, `--manuscript PATH`, `--retraction-file PATH`.

## Exit Codes

- `0` clean
- `1` policy violation
- `2` usage error
- `3` internal error
- `4` ledger tamper

## JSON Output

`--json` writes a single object to stdout. `audit` returns:

```json
{
  "tool": "veridex",
  "version": "0.3.0",
  "summary": {"VERIFIED": 2, "NOT_FOUND": 1},
  "violations": [],
  "results": [
    {"index": 0, "status": "VERIFIED", "flags": [], "scores": {}}
  ]
}
```

`verify-ledger` returns `{"ok": true, "problems": []}`.

## Python API

```python
from veridex import api

# Audit references
results = api.audit_references("examples/refs.bib", ledger_path="run.jsonl")
for r in results:
    print(r.index, r.status)

# Verify ledger
report = api.verify_ledger("run.jsonl")

# Write report
api.write_report(results, "audit", fmt="md")

# Evaluate policy
violations = api.evaluate_policy(results, policy_mapping)

# Parse references
refs = api.parse_references("examples/refs.bib")
```

Set `api.TRANSPORT` to a `callable(url, timeout) -> Response` in tests to keep everything offline.

## Policy File

Example `policy.yaml`:

```yaml
fail_on:
  - RETRACTED
  - DOI_NOT_FOUND
max_fabrication_score: 0.35
max_weak_context_ratio: 0.5
min_verified_ratio: 0.5
required_fields:
  - title
  - year
allowed_venues: []
blocked_venues:
  - Predatory Reports Quarterly
```

## Offline retraction data

Pass `--retraction-file PATH` to flag retracted/corrected works without any network
access. Three formats are accepted (chosen by suffix, with content sniffing fallback):

- **Retraction Watch CSV** — e.g. a `RetractionWatch` export with an `Original Paper DOI`
  (or `Retraction DOI`) column and optional `Reason` / `RetractionDate` / `RetractionNature`
  columns.
- **Crossref update JSON** — an object with an `items` array (or a bare list) where records
  carry an `update-to` relation with a `type` of `retraction`, `withdrawal`, `correction`,
  etc.
- **JSONL** — one JSON object per line, each with a `doi` field (plus optional `kind`,
  `reason`, `date`).

```bash
# Retraction Watch CSV export
veridex audit refs.bib --retraction-file retraction_watch.csv --no-cache

# JSONL of DOIs
veridex audit refs.bib --retraction-file retracted_dois.jsonl --no-cache
```

Retraction and withdrawal notices set the entry's status to `RETRACTED` and add the
`retracted` flag; corrections and expressions of concern are attached as notices without
changing the status. The cited DOI is matched even when a source resolved a different
record DOI.

## Sources

Enable/disable sources with `--sources`:

```bash
# Use only Crossref and OpenAlex
veridex audit refs.bib --sources crossref,openalex --no-cache

# Disable arXiv
veridex audit refs.bib --sources no-arxiv --no-cache

# List available sources
veridex audit --help  # or see SKILL.md
```

Available: `crossref`, `openalex`, `datacite`, `pubmed`, `europepmc`, `semscholar`, `arxiv`, `openlibrary`, `doaj`.

## Offline Testing

All unit tests run without network access by injecting a fake transport. Run the test suite:

```bash
pytest -q
# or
python3 -m pytest tests -q
```

## Live Smoke (optional)

One real bibliographic query per registered source, generic textbook topics only:

```bash
python3 scripts/live_smoke.py
```

Exit code 0 only when every source answers 2xx. Requires internet; Semantic
Scholar may return 429 without an API key (retry after a pause).

## Benchmark

Accuracy is measured, not asserted. `benchmarks/run_benchmark.py` runs the real detection
code over a synthetic, labelled dataset of 59 references (including adversarial cases) and
reports precision/recall/F1 per signal:

```bash
python3 benchmarks/run_benchmark.py          # markdown table
python3 benchmarks/run_benchmark.py --json   # machine-readable metrics
```

Last run: overall problematic-reference **precision 0.897, recall 1.000, F1 0.946,
accuracy 0.932**. Five of six signals reach F1 = 1.000; `doi_resolves_to_different_work`
has precision 0.556 because lexical title matching cannot recognise paraphrases. Full
method, numbers and limits: [docs/benchmark.md](docs/benchmark.md).

## Limits

- The citation-context check is a heuristic (BM25/TF-IDF) and clearly labeled as such — never a verdict.
- Title matching is lexical (difflib). It misses paraphrased or cross-language titles, which can surface as a `doi_resolves_to_different_work` false positive (measured in [docs/benchmark.md](docs/benchmark.md)); an optional semantic backend is available via ``pip install veridex[semantic]`` and ``--semantic``.
- The offline benchmark is synthetic and well-separated: it is a behaviour/regression benchmark, not a field study. Absolute numbers will differ on real corpora.
- Network-dependent features require internet access and respect per-source rate limits.
- The stdlib-only core means some parsing (e.g., complex LaTeX in BibTeX) has limitations.
- Ledger entries hash `run_id` and `timestamp` inside the record payload and reject unexpected top-level line keys; a missing ledger file is a failure for `verify-ledger` (exit code 4). Entries written by pre-hardening builds still verify, but edits to their line-level `timestamp` field are not detectable.

## License

MIT License — see [LICENSE](LICENSE).

Copyright (c) 2026 Madeesh P. Nissanka

## Citation

See [CITATION.cff](CITATION.cff).