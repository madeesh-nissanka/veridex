# VERIDEX: Reference Validation and Provenance Auditing

VERIDEX validates a reference list (plain text, BibTeX, or RIS) or a list of DOIs against Crossref and OpenAlex, keeping a verification ledger for re-run auditing. It is designed for use by LLM agents and researchers preparing manuscripts.

## Abstract

VERIDEX automates reference verification: every entry in a bibliography is checked against the Crossref metadata registry (primary) and OpenAlex (second opinion). It parses multiple input formats, extracts DOIs or uses bibliographic search for entries without DOIs, and assigns a clear validation status. A verification ledger records every API call, enabling re-run auditing to show what changed.

## Install

```bash
# No dependencies beyond Python 3.10+ standard library
git clone https://github.com/madeesh-nissanka/veridex.git
cd veridex
```

## Usage

```bash
# Validate a plain text reference list
python3 scripts/veridex.py references.txt --out audit/

# Validate a BibTeX file
python3 scripts/veridex.py refs.bib --out audit/ --format bib

# Validate a RIS file
python3 scripts/veridex.py refs.ris --out audit/ --format ris

# Validate a list of DOIs (one per line)
python3 scripts/veridex.py dois.txt --out audit/ --format dois

# Specify a custom ledger path
python3 scripts/veridex.py references.txt --out audit/ --ledger audit/custom_ledger.jsonl
```

### Options

- `references`: Path to reference list (required positional argument)
- `--out`: Output directory (default: `audit/`)
- `--format`: Input format: `auto` (default), `text`, `bib`, `ris`, `dois`
- `--ledger`: Ledger file path (default: `<out>/ledger.jsonl`)

### Environment

- `SCHOLAR_MAILTO`: Email for polite pool contact with Crossref and OpenAlex. If unset, requests are sent without a mailto parameter and a one-line note is printed. Example: `export SCHOLAR_MAILTO=you@example.org`

## Outputs

All files are written to the `--out` directory:

- `audit.csv`: Full verification table with all fields.
- `audit.md`: Human-readable markdown table showing original and Crossref metadata side by side for MISMATCH entries.
- `verified.bib`: BibTeX entries for VERIFIED and VERIFIED_WITH_WARNINGS records (citation keys: firstauthorYEARfirstwordoftitle).
- `ledger.jsonl`: One JSON line per API lookup: timestamp, entry index, request URL, HTTP status, response SHA256, status, flags.
- `summary.json`: Counts per validation status.

## Validation Statuses

| Status | Meaning |
|--------|---------|
| VERIFIED | DOI resolves, title similarity ≥ 0.90, first-author surname present, year within ±1. |
| VERIFIED_WITH_WARNINGS | As above but with minor flags (author_order_differs, year_off_by_one, doi_case_or_formatting_fixed). |
| MISMATCH | DOI resolves but title similarity < 0.90, or first author absent, or year off by >1 (specific field listed). |
| DOI_NOT_FOUND | Crossref returns HTTP 404 for the DOI. |
| NO_DOI_MATCHED | No DOI in entry, but Crossref bibliographic search found a match (title ≥ 0.90, year within 1). |
| NO_DOI_UNMATCHED | No DOI and bibliographic search found no match; cannot be verified. |
| RETRACTED | Crossref update-to indicates retraction or withdrawal. |
| UNREACHABLE | Crossref unreachable after exponential backoff (2, 4, 8 s). |

## Ledger and Re-runs

Every API call is appended to `ledger.jsonl` with a timestamp, request URL, HTTP status, response hash, and assigned status. On a re-run, VERIDEX loads the previous ledger and prints a "changes since last audit" section showing NEW, UNCHANGED, or CHANGED (with old and new status) for each entry.

```bash
# First run
python3 scripts/veridex.py references.txt --out audit/

# Second run (shows changes)
python3 scripts/veridex.py references.txt --out audit/
```

## Design Decisions

- **Google Scholar is not used.** No public API exists and scraping violates its terms of service. Crossref and OpenAlex are used instead.
- **Crossref bibliographic search** returns items with a score; a candidate is treated as a match only if title similarity ≥ 0.90 AND year within 1.
- **DOI regex**: `10.\d{4,9}/[-._;()/:A-Za-z0-9]+`, trailing punctuation and period stripped.
- **Crossref author order** sometimes differs from the printed paper. An author-order difference is flagged as a WARNING only; the printed paper wins. Check the PDF where one exists.
- **User-Agent** includes SCHOLAR_MAILTO when set.

## Limitations

- Crossref bibliographic search may return false positives; the 0.90/year threshold reduces this.
- Author order in Crossref may differ from the printed paper; flagged as warning only.
- Paywalled records cannot be fully verified beyond metadata.
- RIS parsing is minimal; complex RIS files may need pre-processing.
- The OpenAlex second opinion compares titles only; a DOI missing from OpenAlex is written to the ledger but is not raised as a warning.
- The tool validates metadata only; it does not assess scientific quality.

## Validation

Unit tests (run with `python3 -m unittest tests/test_veridex.py -v`):

- DOI regex and cleanup.
- Parsers for text, BibTeX, and RIS samples.
- Title normalization and similarity.
- Status assignment on hand-made Crossref-like dicts (retraction, author_order_differs, author_mismatch, year_off_by_one, year_mismatch).
- Ledger append and diff logic.

Example run (real output saved in `examples/run_sample/`):

```bash
SCHOLAR_MAILTO=you@example.org python3 scripts/veridex.py tests/fixtures/sample_refs.txt --out examples/run_sample --format text
```

Produced 15 entries from a sample list of well-known papers plus deliberate errors: 9 VERIFIED, 1 VERIFIED_WITH_WARNINGS (a DOI-only line), 2 MISMATCH (one changed year, one misspelled author), 1 DOI_NOT_FOUND (an invented DOI) and 2 NO_DOI_UNMATCHED (a book and a non-existent paper without DOIs). Every verified DOI was also looked up in OpenAlex.

A second run with the same input reported every lookup as UNCHANGED against the first run (the ledger keeps both runs, one `run_id` each).

## How to Cite

See `CITATION.cff`. A BibTeX entry is also generated by `cffconvert` if needed.

## Licence

MIT. See `LICENSE`.