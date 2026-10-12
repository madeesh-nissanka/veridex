# VERIDEX benchmark: measured accuracy of fabrication & integrity signals

This page reports **real, reproducible** precision/recall/F1 for the reference-integrity
signals that VERIDEX computes offline. All numbers below are produced by running the
checked-in benchmark; none are estimated or hand-written.

## How to reproduce

```bash
python3 benchmarks/run_benchmark.py          # markdown (same table as below)
python3 benchmarks/run_benchmark.py --json   # machine-readable metrics
```

The benchmark is fully offline (no network) and deterministic: two runs on the same
machine produce byte-identical JSON.

## Method

`benchmarks/run_benchmark.py` builds a **synthetic, labelled dataset** of 59 references on
generic textbook-level engineering topics (soil mechanics, structures, pavements, heat
transfer, building physics). Every case supplies

- an input reference (`ParsedReference`),
- a candidate resolved record (`ResolvedRecord`) or `None`,
- the ground-truth set of signals that *should* fire.

The runner then executes the **real detection code** — `matching.evaluate`,
`integrity.collect_integrity`, `matching.find_near_duplicates`, and
`fabrication.score_fabrication` — and compares the predicted signal set against the
labels. It reports per-signal TP/FP/FN/TN, precision, recall and F1, plus an overall
"problematic reference" (any signal present) classification.

### Labelled categories

| Category | Count | Expected signals |
|----------|------:|------------------|
| `correct` (matching title/author/year/venue/volume/pages) | 15 | none |
| `fabricated` (no matching record) | 10 | `no_matching_record` |
| `corrupted_year` (off by > 1) | 6 | `year_mismatch` |
| `corrupted_author` (wrong first author) | 5 | `author_mismatch` |
| `doi_different_work` (DOI + unrelated title) | 5 | `doi_resolves_to_different_work` |
| `retracted` (retraction notice on the record) | 5 | `retracted` |
| `near_duplicate` (identical title pair) | 2 | `near_duplicate` |
| `hard_negative` (year off-by-one, initials-only author, added subtitle, erratum notice, preprint match) | 5 | none |
| `near_duplicate` variant (plural/singular pair) | 2 | `near_duplicate` |
| `paraphrase` (same DOI/author/year, paraphrased title) | 4 | none |

The `hard_negative` and `paraphrase` categories are **adversarial**: they are genuine
matches that must *not* raise a scored signal, so they are the cases that actually test
precision.

## Results (last run)

Cases: 59 — near-duplicate pairs found by the detector: 2.

### Overall: "problematic reference" classification

| TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|----|----|----|----|-----------|--------|----|----------|
| 35 | 4 | 0 | 20 | 0.897 | 1.000 | 0.946 | 0.932 |

### Per-signal metrics

| Signal | Support | TP | FP | FN | Precision | Recall | F1 |
|--------|--------:|----|----|----|-----------|--------|----|
| `no_matching_record` | 10 | 10 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `year_mismatch` | 6 | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `author_mismatch` | 5 | 5 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `doi_resolves_to_different_work` | 5 | 5 | 4 | 0 | 0.556 | 1.000 | 0.714 |
| `retracted` | 5 | 5 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `near_duplicate` | 4 | 4 | 0 | 0 | 1.000 | 1.000 | 1.000 |

## Interpretation

- **Recall is 1.000 for every signal.** In this dataset VERIDEX never misses a fabricated,
  mis-cited, retracted or duplicated reference.
- **Five of six signals have F1 = 1.000**, including all five adversarial `hard_negative`
  cases (off-by-one year stays an advisory, initials-only authors match, an added subtitle
  still matches, an erratum is not treated as a retraction, and a preprint match is not a
  fabrication).
- **`doi_resolves_to_different_work` has precision 0.556.** All four false positives are the
  `paraphrase` cases: the input title is a genuine paraphrase of the real title but lexical
  similarity (`difflib`) falls below the 0.6 threshold, so the DOI looks like it points at a
  different work. This is the precise limitation that an optional semantic-similarity
  backend (see README "Limits") is intended to reduce; the stdlib path is the default and
  fallback.

## Honest limits of this benchmark

- The dataset is **synthetic and intentionally well-separated**; it is a regression and
  behaviour benchmark, not a field study. Absolute numbers will differ on real corpora.
- Labels encode the maintainers' intended semantics for each signal; reasonable people may
  label borderline cases differently.
- The `paraphrase` category deliberately measures a known lexical-matching weakness; it is
  reported rather than hidden.
- Metrics cover the offline signal pipeline. Network resolution quality (which record a
  source returns) is out of scope here and is exercised separately by the live smoke test.

## Regression use

`tests/test_benchmark.py` runs the benchmark inside the offline unit-test suite. It asserts
metric identities, determinism, full F1 on the cleanly-separable signals, and that the
paraphrase limitation is present — so a change that silently worsens matching quality fails
CI.
