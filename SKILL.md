---
name: veridex
description: Validate a reference list or DOIs against Crossref and OpenAlex, keeping a verification ledger for re-run auditing.
---

# VERIDEX: Reference Validation and Provenance Auditing

VERIDEX takes a reference list (plain text one-per-line, BibTeX .bib, or RIS .ris) or a list of DOIs and checks every entry against Crossref (primary) and OpenAlex (second opinion). It keeps a verification ledger so that re-runs show what changed.

## When to use
- Before submitting a manuscript to verify all references.
- Auditing a bibliography for mismatches, retractions, or missing DOIs.
- You need an auditable trail of every verification decision.

## Workflow
1. Run VERIDEX on your reference list before submission.
2. Treat MISMATCH and NO_DOI_UNMATCHED as your decision: never silently fix.
3. Never "correct" a reference from memory; use the Crossref metadata shown in the audit.
4. Note the Crossref author-order trap: order sometimes differs from the printed paper; the printed paper wins. Check the PDF where one exists.

## Command-line interface
```bash
python3 scripts/veridex.py references.txt --out audit/ [--format auto|text|bib|ris|dois] [--ledger audit/ledger.jsonl]
```

## Input formats
- **text**: One reference per line, e.g. "[3] Wilkinson, M.D. et al. (2016). Title. Journal. doi:10.1038/sdata.2016.18"
- **bib**: BibTeX .bib file
- **ris**: RIS .ris file
- **dois**: One DOI per line
- **auto**: Detect from file extension (.bib, .ris) or content

## Per-entry statuses
- VERIFIED: DOI resolves, title similarity >= 0.90, first-author surname present, year within 1.
- VERIFIED_WITH_WARNINGS: author_order_differs, year_off_by_one, doi_case_or_formatting_fixed.
- MISMATCH: DOI resolves but title < 0.90 or first author absent or year off by >1 (exact field listed).
- DOI_NOT_FOUND: Crossref 404.
- NO_DOI_MATCHED: Found via bibliographic search.
- NO_DOI_UNMATCHED: Cannot be verified; reported honestly, not guessed.
- RETRACTED: Crossref update-to retraction/withdrawal.
- UNREACHABLE: Crossref unreachable after backoff.

## Outputs
- `audit.csv`: Full verification table.
- `audit.md`: Human-readable table with corrected fields shown next to original for MISMATCH entries.
- `verified.bib`: BibTeX of VERIFIED and VERIFIED_WITH_WARNINGS entries (keys: firstauthorYEARfirstwordoftitle).
- `ledger.jsonl`: One JSON line per lookup: timestamp, entry index, request URL, HTTP status, response SHA256, status, flags.
- `summary.json`: Counts per status.

## Ledger and re-runs
On a re-run, the ledger is compared and a "changes since last audit" section is printed (NEW, UNCHANGED, CHANGED with old and new status).

## Design decisions
- Google Scholar is not used (no API, scraping breaks terms). Crossref and OpenAlex only.
- Crossref query.bibliographic returns items with a score; match only if title similarity >= 0.90 AND year within 1.
- DOI regex: `10.\d{4,9}/[-._;()/:A-Za-z0-9]+`, strip trailing punctuation and period.
- User-Agent includes SCHOLAR_MAILTO when set.

## Limitations
- Crossref bibliographic search may return false positives; the 0.90/year threshold reduces this.
- Author order in Crossref may differ from the printed paper; flagged as warning only.
- Paywalled records cannot be fully verified beyond metadata.
- RIS parsing is minimal; complex RIS files may need pre-processing.