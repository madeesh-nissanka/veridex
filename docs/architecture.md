# VERIDEX architecture

```
input file ──► parsing ──► resolvers ──► matching ──► signals ──► ledger ──► reports
                (7        (9 adapters   (scores,     (fabric,    (hash      (md/html/
                formats)   + http       flags,       integrity,  chain      json/csv/
                            client)     context)     context)    JSONL)     sarif +
                                                                            dashboard)
```

## Packages (src/veridex/)

| module | role |
|---|---|
| `parsing/` | BibTeX, RIS, CSL-JSON, EndNote XML, plain/author-year text, DOCX (stdlib zip+xml), ID-only lines (DOI/URL/PMID/arXiv/ISBN) |
| `ids.py` | identifier extraction and normalization shared by parsers/resolvers |
| `resolvers/` | one adapter per source (crossref, openalex, datacite, pubmed, europepmc, semscholar, arxiv, openlibrary, doaj); each maps a query to a candidate record |
| `httpclient.py` | single stdlib HTTP client: User-Agent, per-source min interval, retries with backoff, TTL cache, injectable `TRANSPORT` for offline tests |
| `matching.py` | title normalization/similarity, author-list comparison (initials, order, transliteration), year/venue/volume/pages consistency, `evaluate(semantic=...)` hook |
| `fabrication.py` | explainable 0..1 fabrication score from no-match, DOI-mismatch, impossible dates, author-set mismatch |
| `integrity.py` | retractions, corrections, expressions of concern, preprint-vs-published pairing, withdrawn versions |
| `context.py` | offline BM25/TF-IDF support check between citing sentence and matched record (heuristic, flagged for human review) |
| `retractions.py` | offline Retraction Watch CSV / Crossref update JSON/JSONL loader (`--retraction-file`) |
| `semantic.py` | optional embedding similarity (`[semantic]` extra); stdlib lexical path is the default and fallback |
| `ledger.py` | append-only JSONL hash chain: `entry_hash = sha256(prev_hash + canonical_json(data))`, genesis `0*64`; tail-chunked appends (O(1) per record) |
| `policy.py` | thresholds, required fields, allowed/blocked venues, `fail_on` conditions |
| `reports/` | markdown, single-file HTML, JSON, CSV, SARIF renderers; offline review dashboard; DOCX cross-check report |
| `repair.py` | corrected bib/ris/csl.json + repair log; refuses silent overwrite |
| `api.py` | Python API (`audit_references`, `verify_ledger`, `write_report`, `write_cross_check_report`); batching, bounded memory, resume, checkpoints |
| `cli.py` | subcommand dispatch, global flags, exit codes 0/1/2/3/4 |

## Key design decisions

- **Stdlib-only core.** Everything above runs with no third-party packages;
  only the optional semantic extra pulls a dependency, and it degrades to
  the lexical score when absent.
- **Determinism.** Sorted keys in canonical JSON, sorted report rows, fixed
  seeds in generators; re-rendering the same audit results produces
  byte-identical reports, and offline scale/benchmark runs are reproducible.
- **Tamper evidence.** Every entry hashes the previous entry; `verify`
  rejects edits, deletions, reorder, truncation, extra keys and
  line/`data.timestamp` mismatch. Exit code 4 on tamper.
- **Resume + bounded memory.** Audits run in batches (`batch_size`); each
  batch flushes evidence and a checkpoint record to the ledger, results are
  yielded per batch, so peak memory stays flat while the ledger file grows.
  `--resume` replays a ledger run without re-querying checkpointed entries
  (measured: 10k references, 7 s resume, 0 network calls).
- **Offline testability.** `api.TRANSPORT` is a single injection point; all
  400+ unit tests use a fake transport and never touch the network.
