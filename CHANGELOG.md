# Changelog

All notable changes to VERIDEX are documented here.

## [0.3.0] - 2026-10-12

### Added
- **Offline HTML review dashboard** (`veridex dashboard FILE --out DIR`): a single self-contained `dashboard.html` (stdlib-only generation) with status/decision/search/score filtering, sortable columns, per-reference accept/reject/pending decisions, notes, browser-local storage, and JSON/CSV decision export
- **Measured-accuracy benchmark** (`benchmarks/run_benchmark.py`): synthetic labelled dataset with real per-signal precision/recall/F1, adversarial hard negatives, and a documented paraphrase limitation; results in `docs/benchmark.md`
- **Offline retraction data** (`--retraction-file PATH`): load Retraction Watch CSV, Crossref update JSON, or JSONL to flag retracted/withdrawn/corrected works without network access
- **Optional semantic similarity** (`--semantic`, `pip install veridex[semantic]`): local embedding model (sentence-transformers) for title matching; stdlib TF-IDF/BM25 fallback; semantic scores only increase confidence
- **Zotero CSL round-trip**: parse CSL-JSON, audit, repair, emit CSL-JSON; verified with tests
- **Pre-commit hook + GitHub Action verified**: `.pre-commit-config.yaml` and `ci/github-actions-ci.yml` both run and pass locally
- **DOCX cross-check report** (`veridex cross-check REFS --manuscript DOCX --out DIR`): aligns in-text citations with reference list, emits Markdown/HTML
- **10k-reference scale test + resumable audit**: bounded memory batch processing, `--resume` from ledger checkpoint, O(n^2) ledger append fixed, measured 10k refs: 8.82s audit, 50.8MB RSS, 7.21s resume with 0 network calls
- **Wheel build verified + docs site**: `pip wheel --no-build-isolation` produces installable wheel; docs/usage.md, docs/architecture.md, docs/policy.md, docs/benchmark.md
- **SARIF 2.1.0 schema validation + GitHub Code Scanning upload**: hand-written stdlib validator with 6 adversarial mutation tests; fixed `driver.version` and `informationUri` defects; `upload-sarif` CI step added
- **Batch identifier lookup subcommand** (`veridex lookup ids.txt`): resolve DOI/URL/PMID/arXiv/ISBN lines without full audit; JSON/text output
- **User config file** (`veridex.yaml`, `.veridexrc`, `.veridexrc.json`): defaults for sources, workers, cache_dir, etc.; parent directory walk; CLI args take precedence

### Fixed
- `--format all` now writes JSON, Markdown, HTML, CSV and SARIF reports (it was rejected as an unsupported format).
- A reference field missing on one side (journal, volume, pages) is no longer reported as a mismatch; only values present on both sides that differ are flagged. Correct references without a journal in the input now come back `VERIFIED` instead of `VERIFIED_WITH_WARNINGS`.
- Regression tests added for both, found by running the real CLI against live Crossref/OpenAlex data.

## [0.2.0] - 2026-10-11

### Added
- **Input parsers**: BibTeX, RIS, CSL-JSON, EndNote XML, plain text (numbered/author-year/free text), DOCX manuscript extraction, identifier-only lines (DOI/URL/PMID/arXiv/ISBN)
- **Resolver adapters** (9 sources): Crossref, OpenAlex, DataCite, PubMed/Europe PMC, Semantic Scholar, arXiv, OpenLibrary (ISBN), DOAJ
- **Matching engine**: normalized title similarity, author-list comparison (initials, transliteration, order), year/venue/volume/pages consistency, DOI-resolves-to-different-work detection, near-duplicate detection
- **Fabrication signals** with explainable scores: no matching record, DOI metadata mismatch, implausible venue/volume/page, impossible dates, author mismatch
- **Integrity flags**: retractions, corrections, expressions of concern (Crossref/Retraction Watch fields), preprint-vs-published pairing, withdrawn versions
- **Citation-context check** (offline): BM25/TF-IDF comparison of citing sentence with cited record title/abstract, labeled heuristic
- **Provenance ledger**: append-only JSONL with hash chain, per-record evidence, `verify-ledger` command, `diff` between audits
- **Repair suggestions**: corrected BibTeX/RIS/CSL-JSON with change traceability, never overwrites silently
- **Reports**: Markdown, HTML (single static file), JSON, CSV, SARIF with summary and executive table
- **Policy file** (YAML/JSON): thresholds, required fields, allowed/blocked venues, fail-on conditions, exit codes
- **Agent-friendliness**: subcommands (parse, resolve, audit, repair, report, verify-ledger, diff, policy, about), `--json`, Python API, SKILL.md, pre-commit hooks, GitHub Action
- **Engineering**: src layout, pyproject.toml, type hints, logging, polite concurrency, deterministic output, 378 offline tests, CI workflow

### Hardened
- Ledger records now bind `timestamp` (and `run_id`) inside the hashed payload, so edits to per-record timestamps are tamper-evident; `verify-ledger` also rejects unexpected top-level line keys and reports a missing ledger file as a failure (exit 4)
- Legacy ledgers from earlier builds still verify (their data payloads simply lack the bound timestamp)
- `repair FILE --out DIR` now writes the actual repaired outputs (`repaired.bib`, `repaired.ris`, `repaired.csl.json`, `repair_log.json`) instead of an empty report; existing files are never overwritten (suffixed instead) and `--json` includes the written paths

### Changed
- v0.1 CLI flags work as aliases where practical: `veridex refs.txt --out audit --format text` still runs audit

### Fixed
- `--version` and `--about` now both print name, version, license and copyright line
- All 378 unit tests pass offline (no network in tests)

## [0.1.1] - 2026 (baseline)

### Added
- Single-script stdlib-only reference validator
- Crossref and OpenAlex validation
- Audit table output
- Provenance ledger (UNCHANGED/NEW/CHANGED)
- Verified .bib output
- MIT License