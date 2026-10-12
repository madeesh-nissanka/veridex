# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Offline labelled benchmark for VERIDEX fabrication/integrity signals.

Builds a deterministic, fully synthetic labelled dataset of references on
generic textbook-level engineering topics, runs the *real* detection code
(``matching.evaluate``, ``integrity.collect_integrity``,
``fabrication.score_fabrication``, ``matching.find_near_duplicates``) and
reports precision / recall / F1 per signal plus an overall
"problematic reference" classification.

No network access is used. All numbers printed are computed at run time from
the labelled cases; nothing is hard-coded.

Run::

    python benchmarks/run_benchmark.py            # human-readable markdown
    python benchmarks/run_benchmark.py --json     # machine-readable JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from veridex.fabrication import score_fabrication  # noqa: E402
from veridex.integrity import collect_integrity  # noqa: E402
from veridex.matching import evaluate, find_near_duplicates  # noqa: E402
from veridex.models import (  # noqa: E402
    AuditResult,
    ParsedReference,
    ResolvedRecord,
    Status,
    retraction_status,
)

SIGNALS = [
    "no_matching_record",
    "year_mismatch",
    "author_mismatch",
    "doi_resolves_to_different_work",
    "retracted",
    "near_duplicate",
]

_JOURNALS = [
    "Journal of Geotechnical Engineering",
    "Journal of Structural Engineering",
    "Journal of Materials in Civil Engineering",
    "International Journal of Heat and Mass Transfer",
    "Transportation Research Record",
    "Canadian Geotechnical Journal",
]

# Distinct generic textbook-level titles; no real people, venues, or projects.
# Every title is unique so that only the deliberately duplicated pair is a
# near-duplicate; curated to keep pairwise similarity below the 0.92 threshold.
_TITLES = [
    "Elastic settlement of footings on granular soil",
    "Slope stability analysis using limit equilibrium methods",
    "Bearing capacity of shallow foundations on sand",
    "Durability of reinforced concrete in chloride environments",
    "Fatigue life of asphalt pavements under cyclic loading",
    "Deflection of simply supported beams under distributed loads",
    "Steady-state heat conduction in composite walls",
    "Consolidation theory for layered soil deposits",
    "Effective stress and pore pressure in saturated soils",
    "Reinforced earth retaining walls: design considerations",
    "Thermal conductivity of porous building materials",
    "Shear strength of unsaturated soils",
    "Creep deformation of concrete under sustained load",
    "Buckling of slender steel columns",
    "Seepage analysis through earth dams",
    "Pavement rutting prediction models",
    "Bearing capacity of pile groups in cohesive soil",
    "Durability of geopolymer concrete",
    "Heat transfer through insulated building envelopes",
    "Lateral earth pressure theories",
    "Torsion of reinforced concrete beams",
    "Fatigue cracking in steel bridge details",
    "Consolidation of peat soils",
    "Settlement of embankments on soft ground",
    "Vibration isolation in foundations",
    "Liquefaction potential of saturated sands",
    "Soil compaction and relative density effects",
    "Shear modulus degradation in cyclic triaxial tests",
    "Frost heave in seasonally frozen ground",
    "Numerical modelling of groundwater flow",
    "Rock joint shear behaviour under normal stress",
    "Masonry wall out-of-plane flexural strength",
    "Prestressed concrete girder design provisions",
    "Steel connection moment-rotation behaviour",
    "Fatigue of welded tubular joints",
    "Concrete shrinkage and cracking prediction",
    "Alkali-silica reaction in concrete",
    "Chloride ingress modelling in concrete",
    "Asphalt binder rheology at low temperature",
    "Thermal bridging in building envelopes",
    "Radiant floor heating system performance",
    "Natural convection in vertical cavities",
    "Phase change materials for thermal storage",
    "Acoustic insulation of lightweight partitions",
    "Wind loading on low-rise buildings",
    "Seismic base isolation of structures",
    "Tuned mass dampers for tall buildings",
    "Damping in reinforced concrete frames",
    # Extra titles for adversarial (hard) cases.
    "Time-dependent settlement of embankments on clay",
    "Bearing capacity of ring footings on layered soil",
    "Creep rupture of prestressing steel tendons",
    "Stability of rock slopes with planar discontinuities",
    "Thermal performance of vacuum insulation panels",
    "Vibration serviceability of long-span timber floors",
    "Vibration serviceability of long-span timber floor",
]

# Title shared only by the intentional near-duplicate pair.
_DUP_TITLE = "Corrigendum to a study of shallow footing bearing assessments"


def _authors_str(seed: int) -> list[str]:
    return [f"Surname{seed}A, A.", f"Surname{seed}B, B.", f"Surname{seed}C, C."]


def _authors_rec(seed: int) -> list[dict[str, str]]:
    return [
        {"family": f"Surname{seed}A", "given": "A."},
        {"family": f"Surname{seed}B", "given": "B."},
        {"family": f"Surname{seed}C", "given": "C."},
    ]


def _correct_pair(seed: int, title: str, index: int) -> dict[str, Any]:
    journal = _JOURNALS[seed % len(_JOURNALS)]
    year = 2000 + (seed % 20)
    volume = str(10 + (seed % 40))
    pages = f"{100 + seed}-{120 + seed}"
    ref = ParsedReference(
        index=index,
        format="bib",
        title=title,
        authors=_authors_str(seed),
        year=year,
        journal=journal,
        volume=volume,
        pages=pages,
        doi=f"10.1000/bench.{seed}",
    )
    rec = ResolvedRecord(
        source="crossref",
        source_id=f"bench.{seed}",
        title=title,
        authors=_authors_rec(seed),
        year=year,
        journal=journal,
        volume=volume,
        pages=pages,
        doi=f"10.1000/bench.{seed}",
        url=f"https://example.org/works/bench.{seed}",
        source_url=f"https://api.example.org/works/{seed}",
        abstract=f"Abstract for {title.lower()}.",
    )
    return {"ref": ref, "record": rec, "labels": []}


def build_cases() -> list[dict[str, Any]]:
    """Return the deterministic labelled dataset."""
    cases: list[dict[str, Any]] = []
    index = 0

    # 1) Correct references: 15 (labels: none)
    for i in range(15):
        c = _correct_pair(seed=i, title=_TITLES[index], index=index)
        c["id"] = f"correct-{i}"
        c["category"] = "correct"
        cases.append(c)
        index += 1

    # 2) Fabricated references with no matching record: 10
    for i in range(10):
        ref = ParsedReference(
            index=index,
            format="text",
            title=_TITLES[index],
            authors=_authors_str(100 + i),
            year=2015 + (i % 5),
            journal="Journal of Fabricated Studies",
            doi=f"10.9999/fake.{i}",
        )
        cases.append({
            "id": f"fabricated-{i}",
            "category": "fabricated",
            "ref": ref,
            "record": None,
            "labels": ["no_matching_record"],
        })
        index += 1

    # 3) Corrupted year (off by >1): 6
    for i in range(6):
        c = _correct_pair(seed=200 + i, title=_TITLES[index], index=index)
        c["ref"].year = (c["record"].year or 2000) - 8
        c["id"] = f"bad-year-{i}"
        c["category"] = "corrupted_year"
        c["labels"] = ["year_mismatch"]
        cases.append(c)
        index += 1

    # 4) Corrupted author list: 5
    for i in range(5):
        c = _correct_pair(seed=300 + i, title=_TITLES[index], index=index)
        c["ref"].authors = [f"Wrongname{i}, Z."]
        c["id"] = f"bad-author-{i}"
        c["category"] = "corrupted_author"
        c["labels"] = ["author_mismatch"]
        cases.append(c)
        index += 1

    # 5) DOI resolves to a different work (title mismatch, authors/year match): 5
    for i in range(5):
        c = _correct_pair(seed=400 + i, title=_TITLES[index], index=index)
        c["record"].title = "A completely unrelated study on marine sediment transport"
        c["ref"].doi = "10.1000/wrong.target"
        c["id"] = f"wrong-doi-{i}"
        c["category"] = "doi_different_work"
        c["labels"] = ["doi_resolves_to_different_work"]
        cases.append(c)
        index += 1

    # 6) Retracted records: 5
    for i in range(5):
        c = _correct_pair(seed=500 + i, title=_TITLES[index], index=index)
        c["record"].integrity = {
            "notices": [
                {
                    "kind": "retraction",
                    "source": "crossref",
                    "url": "https://example.org/retraction/1",
                    "label": "Retracted",
                    "target": "work",
                }
            ]
        }
        c["id"] = f"retracted-{i}"
        c["category"] = "retracted"
        c["labels"] = ["retracted"]
        cases.append(c)
        index += 1

    # 7) Near-duplicate pair: 2 (identical title, different seeds/DOIs)
    for i in range(2):
        c = _correct_pair(seed=600 + i, title=_DUP_TITLE, index=index)
        c["id"] = f"near-dup-{i}"
        c["category"] = "near_duplicate"
        c["labels"] = ["near_duplicate"]
        cases.append(c)
        index += 1

    # 8) Hard negatives: genuine matches that must NOT raise the scored signals.
    hard_specs = [
        ("hard-year-offbyone", "year_off_one"),
        ("hard-author-initials", "author_initials"),
        ("hard-subtitle", "subtitle"),
        ("hard-correction", "correction"),
        ("hard-preprint", "preprint"),
    ]
    for i, (cid, kind) in enumerate(hard_specs):
        c = _correct_pair(seed=700 + i, title=_TITLES[index], index=index)
        if kind == "year_off_one":
            # One-year discrepancy is reported as an advisory, not a mismatch.
            c["ref"].year = (c["record"].year or 2000) + 1
        elif kind == "author_initials":
            # Initial-only given name for the same surname must not flag.
            c["ref"].authors = [f"{c['record'].authors[0]['family']}, J."]
        elif kind == "subtitle":
            # Same work with an added subtitle must not look like a different work.
            c["ref"].title = (c["record"].title or "") + ": a review"
        elif kind == "correction":
            # An erratum/correction notice must not be treated as a retraction.
            c["record"].integrity = {
                "notices": [
                    {
                        "kind": "correction",
                        "source": "crossref",
                        "url": "https://example.org/correction/1",
                        "label": "Correction",
                        "target": "work",
                    }
                ]
            }
        elif kind == "preprint":
            # A preprint match is still a valid match, not a fabrication signal.
            c["record"].document_type = "preprint"
            c["record"].source = "arxiv"
        c["id"] = cid
        c["category"] = "hard_negative"
        c["labels"] = []
        cases.append(c)
        index += 1

    # 9) Near-duplicate variant pair (labels: near_duplicate) - plural/singular.
    for i in range(2):
        c = _correct_pair(seed=800 + i, title=_TITLES[index], index=index)
        c["id"] = f"near-dup-variant-{i}"
        c["category"] = "near_duplicate_variant"
        c["labels"] = ["near_duplicate"]
        cases.append(c)
        index += 1

    # 10) Paraphrased genuine matches (semantic-similarity limitation).
    # Same DOI/authors/year, but the input title is a paraphrase of the real
    # title. Lexical similarity (difflib) falls below 0.6, so the stdlib
    # matcher misreads this as a DOI pointing at a different work. Labels are
    # empty: these are genuine matches and any scored signal is a false
    # positive. This quantifies the gap that optional semantic matching targets.
    paraphrase_pairs = [
        ("Elastic settlement of footings on granular soil",
         "How much shallow supports sink into sandy ground"),
        ("Steady-state heat conduction in composite walls",
         "Heat flow at equilibrium through layered building assemblies"),
        ("Buckling of slender steel columns",
         "Lateral instability of thin metal struts under compression"),
        ("Fatigue life of asphalt pavements under cyclic loading",
         "How repeated traffic loads wear out bituminous road surfaces"),
    ]
    for i, (orig, para) in enumerate(paraphrase_pairs):
        ref = ParsedReference(
            index=index,
            format="bib",
            title=para,
            authors=_authors_str(900 + i),
            year=2005 + i,
            journal=_JOURNALS[i % len(_JOURNALS)],
            volume=str(20 + i),
            pages=f"{300 + i}-{320 + i}",
            doi=f"10.1000/para.{i}",
        )
        rec = ResolvedRecord(
            source="crossref",
            source_id=f"para.{i}",
            title=orig,
            authors=_authors_rec(900 + i),
            year=2005 + i,
            journal=_JOURNALS[i % len(_JOURNALS)],
            volume=str(20 + i),
            pages=f"{300 + i}-{320 + i}",
            doi=f"10.1000/para.{i}",
            url=f"https://example.org/works/para.{i}",
            source_url=f"https://api.example.org/works/{i}",
            abstract="Abstract.",
        )
        cases.append({
            "id": f"paraphrase-{i}",
            "category": "paraphrase",
            "ref": ref,
            "record": rec,
            "labels": [],
        })
        index += 1

    return cases


def _predict(case: dict[str, Any], near_dup_indices: set[int]) -> tuple[AuditResult, set[str]]:
    ref: ParsedReference = case["ref"]
    rec: ResolvedRecord | None = case["record"]
    signals: set[str] = set()

    if rec is None:
        result = AuditResult(
            index=ref.index,
            input=ref,
            record=None,
            status=Status.NOT_FOUND,
            flags=["no_matching_record"],
        )
    else:
        ev = evaluate(ref, rec)
        result = AuditResult(
            index=ref.index,
            input=ref,
            record=rec,
            status=str(ev["status"]),
            flags=list(ev["flags"]),
            scores=dict(ev["scores"]),
        )
        result.integrity = collect_integrity([rec])
        if retraction_status(result):
            result.flags = sorted(set(result.flags + ["retracted"]))
            result.status = Status.RETRACTED

    result.fabrication = score_fabrication(ref, rec, {"flags": result.flags}, [])

    for name in (
        "no_matching_record",
        "year_mismatch",
        "author_mismatch",
        "doi_resolves_to_different_work",
    ):
        if name in result.flags:
            signals.add(name)
    if retraction_status(result):
        signals.add("retracted")
    if ref.index in near_dup_indices:
        signals.add("near_duplicate")
    return result, signals


def run_benchmark(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run the labelled benchmark and return metrics."""
    cases = build_cases() if cases is None else cases

    refs = [c["ref"] for c in cases]
    dup_pairs = find_near_duplicates(refs)
    near_dup_indices: set[int] = set()
    for p in dup_pairs:
        near_dup_indices.add(refs[p["i"]].index)
        near_dup_indices.add(refs[p["j"]].index)

    per_case: list[dict[str, Any]] = []
    for case in cases:
        result, predicted = _predict(case, near_dup_indices)
        per_case.append({
            "id": case["id"],
            "category": case["category"],
            "labels": sorted(case["labels"]),
            "predicted": sorted(predicted),
            "status": result.status,
            "fabrication_score": round(float(result.fabrication.get("score", 0.0)), 4),
        })

    # Per-signal confusion matrix
    per_signal: dict[str, dict[str, Any]] = {}
    for signal in SIGNALS:
        tp = fp = fn = tn = 0
        for case, row in zip(cases, per_case):
            truth = signal in case["labels"]
            pred = signal in row["predicted"]
            if truth and pred:
                tp += 1
            elif pred and not truth:
                fp += 1
            elif truth and not pred:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_signal[signal] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "support": tp + fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    # Overall "problematic reference" binary classification
    tp = fp = fn = tn = 0
    for case, row in zip(cases, per_case):
        truth = bool(case["labels"])
        pred = bool(row["predicted"])
        if truth and pred:
            tp += 1
        elif pred and not truth:
            fp += 1
        elif truth and not pred:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(cases) if cases else 0.0

    return {
        "tool": "veridex",
        "n_cases": len(cases),
        "n_refs": len(refs),
        "near_duplicate_pairs": len(dup_pairs),
        "overall": {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "accuracy": round(accuracy, 4),
        },
        "per_signal": per_signal,
        "per_case": per_case,
    }


def _render_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# VERIDEX synthetic benchmark",
        "",
        f"Cases: {metrics['n_cases']} | refs: {metrics['n_refs']} | "
        f"near-duplicate pairs: {metrics['near_duplicate_pairs']}",
        "",
        "## Overall: problematic-reference classification",
        "",
        "| TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |",
        "|----|----|----|----|-----------|--------|----|----------|",
    ]
    o = metrics["overall"]
    lines.append(
        f"| {o['tp']} | {o['fp']} | {o['fn']} | {o['tn']} | "
        f"{o['precision']:.3f} | {o['recall']:.3f} | {o['f1']:.3f} | {o['accuracy']:.3f} |"
    )
    lines += [
        "",
        "## Per-signal metrics",
        "",
        "| Signal | Support | TP | FP | FN | Precision | Recall | F1 |",
        "|--------|---------|----|----|----|-----------|--------|----|",
    ]
    for signal in SIGNALS:
        m = metrics["per_signal"][signal]
        lines.append(
            f"| {signal} | {m['support']} | {m['tp']} | {m['fp']} | {m['fn']} | "
            f"{m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline VERIDEX benchmark.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = parser.parse_args(argv)

    metrics = run_benchmark()
    if args.json:
        print(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        print(_render_markdown(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
