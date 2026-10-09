#!/usr/bin/env python3
"""
VERIDEX: Reference Validation and Provenance Auditing against Crossref and OpenAlex

Validates a reference list (plain text, BibTeX, or RIS) or a list of DOIs
against Crossref and OpenAlex, keeping a verification ledger for re-run auditing.
"""
import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


RUN_ID = ""
SCHOLAR_MAILTO = os.environ.get("SCHOLAR_MAILTO", "")
UA = f"veridex/0.1" + (f" (mailto:{SCHOLAR_MAILTO})" if SCHOLAR_MAILTO else "")

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+")
DOI_URL_PREFIX = "https://doi.org/"

CROSSREF_BASE = "https://api.crossref.org/works"
OPENALEX_BASE = "https://api.openalex.org/works"


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body), body


def normalize_title(title):
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def title_similarity(a, b):
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def strip_doi_prefix(doi):
    if not doi:
        return None
    if doi.startswith(DOI_URL_PREFIX):
        return doi[len(DOI_URL_PREFIX):]
    return doi


def clean_doi(doi):
    if not doi:
        return None
    doi = strip_doi_prefix(doi)
    if doi.startswith("doi:"):
        doi = doi[4:]
    doi = doi.rstrip(".,;")
    # drop trailing ")" only when it is unbalanced (a DOI such as 10.1061/(ASCE)1090-0241(2001)127:10(817) ends in ")")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;")
    return doi


def first_author_surname(authors):
    if not authors:
        return None
    name = authors[0]
    if "," in name:
        return name.split(",")[0].strip()
    parts = name.split()
    return parts[-1] if parts else None


def parse_text_line(line):
    line = line.strip()
    if not line:
        return None
    doi_match = DOI_RE.search(line)
    doi = clean_doi(doi_match.group(0)) if doi_match else None
    year_match = re.search(r"\b(19|20)\d{2}[a-z]?\b", line)
    year = int(year_match.group(0)[:4]) if year_match else None
    # Match "Surname, Initials" or "Surname" after optional [num]
    author_match = re.match(r"(?:\[?\d+\]?\s*)?([A-Z][A-Za-z\-']+(?:,\s*[A-Z]\.?(?:\s*[A-Z]\.?)?)?)", line)
    first_author = None
    if author_match:
        name = author_match.group(1)
        if "," in name:
            first_author = name.split(",")[0].strip()
        else:
            first_author = name
    title = None
    if doi_match:
        before_doi = line[:doi_match.start()]
    else:
        before_doi = line
    # title = text after "(YEAR)." up to the first full stop that is followed by a space and a capital letter
    # (periods inside tokens such as "2.1" do not end the title)
    ym = re.search(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*", before_doi)
    if ym:
        rest = before_doi[ym.end():]
        tm = re.match(r"(.+?)\.\s+(?=[A-Z\"'])", rest)
        title = (tm.group(1) if tm else rest.rstrip(". ")).strip() or None
    else:
        title_match = re.search(r"[.)]\s*([A-Z][^.]{10,}?)\.", before_doi)
        if title_match:
            title = title_match.group(1).strip()
    return {
        "raw": line,
        "doi": doi,
        "year": year,
        "first_author": first_author,
        "title": title,
    }


def parse_bibtex(path):
    text = Path(path).read_text()
    entries = re.split(r"@\w+\s*\{", text)[1:]
    out = []
    for e in entries:
        doi_match = DOI_RE.search(e)
        doi = clean_doi(doi_match.group(0)) if doi_match else None
        year_match = re.search(r"year\s*=\s*\{?(\d{4})", e)
        year = int(year_match.group(1)) if year_match else None
        author_match = re.search(r"author\s*=\s*\{([^}]+)\}", e)
        first_author = None
        if author_match:
            first = author_match.group(1).split(" and ")[0].strip()
            if "," in first:
                first_author = first.split(",")[0].strip()
            else:
                parts = first.split()
                first_author = parts[-1] if parts else None
        title_match = re.search(r"title\s*=\s*\{([^}]+)\}", e)
        title = title_match.group(1) if title_match else None
        out.append({"raw": e.strip(), "doi": doi, "year": year, "first_author": first_author, "title": title})
    return out


def parse_ris(path):
    text = Path(path).read_text()
    entries = re.split(r"\n\s*ER\s*-\s*\n", text)
    out = []
    for e in entries:
        if not e.strip():
            continue
        doi_match = DOI_RE.search(e)
        doi = clean_doi(doi_match.group(0)) if doi_match else None
        year_match = re.search(r"PY\s*-\s*(\d{4})", e)
        year = int(year_match.group(1)) if year_match else None
        author_match = re.search(r"AU\s*-\s*([^\n]+)", e)
        first_author = None
        if author_match:
            first = author_match.group(1).strip()
            if "," in first:
                first_author = first.split(",")[0].strip()
            else:
                parts = first.split()
                first_author = parts[-1] if parts else None
        title_match = re.search(r"TI\s*-\s*([^\n]+)", e)
        title = title_match.group(1).strip() if title_match else None
        out.append({"raw": e.strip(), "doi": doi, "year": year, "first_author": first_author, "title": title})
    return out


def parse_dois(path):
    text = Path(path).read_text()
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        doi = clean_doi(line)
        out.append({"raw": line, "doi": doi, "year": None, "first_author": None, "title": None})
    return out


def parse_input(path, fmt):
    if fmt == "text" or (fmt == "auto" and path.suffix.lower() not in (".bib", ".ris")):
        lines = Path(path).read_text().splitlines()
        return [parse_text_line(l) for l in lines if l.strip()]
    elif fmt == "bib" or (fmt == "auto" and path.suffix.lower() == ".bib"):
        return parse_bibtex(path)
    elif fmt == "ris" or (fmt == "auto" and path.suffix.lower() == ".ris"):
        return parse_ris(path)
    elif fmt == "dois":
        return parse_dois(path)
    else:
        return []


def crossref_by_doi(doi, sleep_between=0.1):
    url = f"{CROSSREF_BASE}/{urllib.parse.quote(doi)}"
    backoffs = [2, 4, 8]
    for backoff in [0] + backoffs:
        if backoff:
            time.sleep(backoff)
        try:
            data, body = fetch_json(url)
            msg = data["message"]
            time.sleep(sleep_between)
            return {"ok": True, "data": msg, "http_status": 200, "body": body, "url": url}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"ok": False, "error": "not_found", "http_status": 404, "body": b"", "url": url}
            if e.code in (429, 503):
                continue
            return {"ok": False, "error": f"http_{e.code}", "http_status": e.code, "body": b"", "url": url}
        except Exception as e:
            return {"ok": False, "error": f"unreachable: {e}", "http_status": 0, "body": b"", "url": url}
    return {"ok": False, "error": "crossref_unreachable", "http_status": 0, "body": b"", "url": url}


def crossref_bibliographic(raw_text, sleep_between=0.1):
    url = f"{CROSSREF_BASE}?query.bibliographic={urllib.parse.quote(raw_text)}&rows=5"
    backoffs = [2, 4, 8]
    for backoff in [0] + backoffs:
        if backoff:
            time.sleep(backoff)
        try:
            data, body = fetch_json(url)
            time.sleep(sleep_between)
            items = data["message"].get("items", [])
            return {"ok": True, "items": items, "http_status": 200, "body": body, "url": url}
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                continue
            return {"ok": False, "error": f"http_{e.code}", "http_status": e.code, "body": b"", "url": url}
        except Exception as e:
            return {"ok": False, "error": f"unreachable: {e}", "http_status": 0, "body": b"", "url": url}
    return {"ok": False, "error": "crossref_unreachable", "http_status": 0, "body": b"", "url": url}


def openalex_by_doi(doi):
    url = f"{OPENALEX_BASE}/https://doi.org/{urllib.parse.quote(doi)}"
    try:
        data, body = fetch_json(url)
        return {"ok": True, "data": data, "http_status": 200, "body": body, "url": url}
    except Exception as e:
        return {"ok": False, "error": f"unreachable: {e}", "http_status": 0, "body": b"", "url": url}


def check_retraction(msg):
    for item in msg.get("update-to", []):
        if item.get("type") in ("retraction", "withdrawal"):
            return True
    return False


def build_bibtex(msg, key):
    authors = msg.get("author", [])
    author_str = " and ".join(f"{a.get('family', '')}, {a.get('given', '')}" for a in authors if a.get("family"))
    title = (msg.get("title") or [""])[0]
    year = None
    issued = msg.get("issued", {})
    dp = issued.get("date-parts", [])
    if dp and dp[0]:
        year = dp[0][0]
    journal = (msg.get("container-title") or [""])[0]
    volume = msg.get("volume", "")
    issue = msg.get("issue", "")
    pages = msg.get("page", "")
    doi = msg.get("DOI", "")
    lines = [
        f"@{key},",
        f"  author = {{{author_str}}},",
        f"  title = {{{title}}},",
    ]
    if year:
        lines.append(f"  year = {{{year}}},")
    if journal:
        lines.append(f"  journal = {{{journal}}},")
    if volume:
        lines.append(f"  volume = {{{volume}}},")
    if issue:
        lines.append(f"  number = {{{issue}}},")
    if pages:
        lines.append(f"  pages = {{{pages}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    lines.append("}")
    return "\n".join(lines)


def make_bibtex_key(msg):
    authors = msg.get("author", [])
    first_author = authors[0].get("family", "Unknown") if authors else "Unknown"
    year = None
    issued = msg.get("issued", {})
    dp = issued.get("date-parts", [])
    if dp and dp[0]:
        year = dp[0][0]
    title = (msg.get("title") or [""])[0]
    first_word = re.sub(r"[^a-zA-Z]", "", title.split()[0]) if title else "Title"
    return f"{first_author}{year}{first_word}"


def validate_entry(entry, ledger_path):
    idx = entry.get("_index", 0)
    doi = entry.get("doi")
    raw = entry.get("raw", "")
    title = entry.get("title")
    year = entry.get("year")
    first_author = entry.get("first_author")

    def log_ledger(req_url, http_status, body, status, flags):
        sha = hashlib.sha256(body).hexdigest() if body else ""
        rec = {
            "run_id": RUN_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_index": idx,
            "request_url": req_url,
            "http_status": http_status,
            "response_sha256": sha,
            "status": status,
            "flags": flags,
        }
        with open(ledger_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    if doi:
        cr = crossref_by_doi(doi)
        log_ledger(cr["url"], cr["http_status"], cr["body"], "PENDING", [])
        if not cr["ok"]:
            if cr["error"] == "not_found":
                log_ledger(cr["url"], cr["http_status"], cr["body"], "DOI_NOT_FOUND", ["doi_not_found"])
                return "DOI_NOT_FOUND", ["doi_not_found"], {}
            log_ledger(cr["url"], cr["http_status"], cr["body"], "UNREACHABLE", ["crossref_unreachable"])
            return "UNREACHABLE", ["crossref_unreachable"], {}

        msg = cr["data"]
        flags = []

        if check_retraction(msg):
            log_ledger(cr["url"], cr["http_status"], cr["body"], "RETRACTED", ["retracted"])
            return "RETRACTED", ["retracted"], msg

        cr_title = (msg.get("title") or [""])[0]
        cr_year = None
        issued = msg.get("issued", {})
        dp = issued.get("date-parts", [])
        if dp and dp[0]:
            cr_year = dp[0][0]
        cr_authors = msg.get("author", [])
        cr_surnames = [a.get("family", "") for a in cr_authors if a.get("family")]

        doi_only = not title
        sim = title_similarity(title or "", cr_title) if title else 1.0
        year_ok = True
        year_diff = 0
        if year and cr_year:
            year_diff = abs(year - cr_year)
            if year_diff == 0:
                pass
            elif year_diff == 1:
                flags.append("year_off_by_one")
            else:
                flags.append("year_mismatch")
                year_ok = False
        author_ok = True
        if first_author:
            if first_author in cr_surnames:
                if cr_surnames and cr_surnames[0] != first_author:
                    flags.append("author_order_differs")
            else:
                flags.append("author_mismatch")
                author_ok = False

        if doi_only:
            flags.append("doi_only_resolves_no_title_to_compare")
        if sim >= 0.90 and year_ok and author_ok:
            # second opinion from OpenAlex (title only; a missing record is logged but is not a warning)
            oa = openalex_by_doi(doi)
            if oa["ok"]:
                oa_title = oa["data"].get("title") or ""
                oa_flags = [] if title_similarity(cr_title, oa_title) >= 0.85 else ["openalex_title_differs"]
                log_ledger(oa["url"], oa["http_status"], oa["body"], "OPENALEX_OK" if not oa_flags else "OPENALEX_DIFFERS", oa_flags)
                flags.extend(oa_flags)
            else:
                log_ledger(oa["url"], oa["http_status"], oa["body"], "OPENALEX_NOT_AVAILABLE", [])
            status = "VERIFIED" if not flags else "VERIFIED_WITH_WARNINGS"
            log_ledger(cr["url"], cr["http_status"], cr["body"], status, flags)
            return status, flags, msg
        else:
            mismatch_fields = []
            if sim < 0.90:
                mismatch_fields.append("title")
            if not year_ok:
                mismatch_fields.append("year")
            if not author_ok:
                mismatch_fields.append("first_author")
            log_ledger(cr["url"], cr["http_status"], cr["body"], "MISMATCH", flags + [f"mismatch_{f}" for f in mismatch_fields])
            return "MISMATCH", flags + [f"mismatch_{f}" for f in mismatch_fields], msg
    else:
        cr = crossref_bibliographic(raw)
        log_ledger(cr["url"], cr["http_status"], cr["body"], "PENDING", [])
        if not cr["ok"]:
            log_ledger(cr["url"], cr["http_status"], cr["body"], "UNREACHABLE", ["crossref_unreachable"])
            return "UNREACHABLE", ["crossref_unreachable"], {}
        items = cr.get("items", [])
        if not items:
            log_ledger(cr["url"], cr["http_status"], cr["body"], "NO_DOI_UNMATCHED", ["no_doi_unmatched"])
            return "NO_DOI_UNMATCHED", ["no_doi_unmatched"], {}
        best = items[0]
        score = best.get("score", 0)
        cr_title = (best.get("title") or [""])[0]
        sim = title_similarity(title or "", cr_title) if title else 0
        cr_year = None
        issued = best.get("issued", {})
        dp = issued.get("date-parts", [])
        if dp and dp[0]:
            cr_year = dp[0][0]
        year_ok = True
        if year and cr_year:
            year_diff = abs(year - cr_year)
            if year_diff > 1:
                year_ok = False
        if sim >= 0.90 and year_ok:
            log_ledger(cr["url"], cr["http_status"], cr["body"], "NO_DOI_MATCHED", ["no_doi_matched"])
            return "NO_DOI_MATCHED", ["no_doi_matched"], best
        else:
            log_ledger(cr["url"], cr["http_status"], cr["body"], "NO_DOI_UNMATCHED", ["no_doi_unmatched"])
            return "NO_DOI_UNMATCHED", ["no_doi_unmatched"], {}


def load_ledger(ledger_path):
    if not Path(ledger_path).exists():
        return {}
    with open(ledger_path) as f:
        lines = f.readlines()
    latest = {}
    for line in lines:
        try:
            rec = json.loads(line)
            key = rec.get("request_url", "")
            latest[key] = rec
        except:
            pass
    return latest


def compare_ledgers(old_ledger, new_ledger_path):
    new_latest = {}
    with open(new_ledger_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("run_id") != RUN_ID:
                    continue
                key = rec.get("request_url", "")
                new_latest[key] = rec
            except:
                pass
    changes = []
    for key, new_rec in new_latest.items():
        old_rec = old_ledger.get(key)
        if not old_rec:
            changes.append(("NEW", None, new_rec["status"]))
        elif old_rec["status"] != new_rec["status"]:
            changes.append(("CHANGED", old_rec["status"], new_rec["status"]))
        else:
            changes.append(("UNCHANGED", old_rec["status"], new_rec["status"]))
    return changes


def write_outputs(entries, results, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "audit.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "raw", "doi", "year", "first_author", "title", "status", "flags", "cr_title", "cr_year", "cr_first_author"])
        for i, (entry, (status, flags, msg)) in enumerate(zip(entries, results)):
            cr_title = (msg.get("title") or [""])[0] if msg else ""
            cr_year = None
            issued = msg.get("issued", {})
            dp = issued.get("date-parts", [])
            if dp and dp[0]:
                cr_year = dp[0][0]
            cr_authors = msg.get("author", [])
            cr_first = cr_authors[0].get("family", "") if cr_authors else ""
            writer.writerow([
                i, entry.get("raw", ""), entry.get("doi", "") or "",
                entry.get("year", "") or "", entry.get("first_author", "") or "",
                entry.get("title", "") or "", status, ";".join(flags),
                cr_title, cr_year or "", cr_first
            ])

    md_path = out_dir / "audit.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("| # | Raw | Status | Flags | Crossref Title | Crossref Year | Crossref First Author |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, (entry, (status, flags, msg)) in enumerate(zip(entries, results)):
            raw_disp = entry.get("raw", "").replace("|", "\\|")[:100]
            cr_title = (msg.get("title") or [""])[0] if msg else ""
            cr_year = None
            issued = msg.get("issued", {})
            dp = issued.get("date-parts", [])
            if dp and dp[0]:
                cr_year = dp[0][0]
            cr_authors = msg.get("author", [])
            cr_first = cr_authors[0].get("family", "") if cr_authors else ""
            f.write(f"| {i} | {raw_disp} | {status} | {';'.join(flags)} | {cr_title[:80]} | {cr_year or ''} | {cr_first} |\n")

    bib_path = out_dir / "verified.bib"
    with bib_path.open("w", encoding="utf-8") as f:
        for entry, (status, flags, msg) in zip(entries, results):
            if status in ("VERIFIED", "VERIFIED_WITH_WARNINGS") and msg:
                key = make_bibtex_key(msg)
                f.write(build_bibtex(msg, key) + "\n\n")

    summary = {}
    for _, (status, _, _) in enumerate(results):
        summary[status] = summary.get(status, 0) + 1
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser(description="VERIDEX: Reference validation and provenance auditing")
    ap.add_argument("references", help="Path to reference list (text, .bib, .ris, or DOIs)")
    ap.add_argument("--out", default="audit", help="Output directory")
    ap.add_argument("--format", choices=["auto", "text", "bib", "ris", "dois"], default="auto", help="Input format")
    ap.add_argument("--ledger", help="Ledger file path (default: <out>/ledger.jsonl)")
    args = ap.parse_args()

    ref_path = Path(args.references)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = Path(args.ledger) if args.ledger else out_dir / "ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    global RUN_ID
    RUN_ID = datetime.now(timezone.utc).isoformat()
    if not SCHOLAR_MAILTO:
        print("Note: SCHOLAR_MAILTO is not set; requests are sent without a contact address.", file=sys.stderr)

    old_ledger = load_ledger(ledger_path)

    entries = parse_input(ref_path, args.format)
    for i, e in enumerate(entries):
        e["_index"] = i

    results = []
    for entry in entries:
        status, flags, msg = validate_entry(entry, ledger_path)
        results.append((status, flags, msg))
        print(f"  [{entry['_index']+1}/{len(entries)}] {entry.get('doi') or 'NO_DOI'} -> {status}", file=sys.stderr)

    write_outputs(entries, results, out_dir)

    if old_ledger:
        changes = compare_ledgers(old_ledger, ledger_path)
        print("\nChanges since last audit:", file=sys.stderr)
        for change_type, old_st, new_st in changes:
            if change_type != "UNCHANGED":
                print(f"  {change_type}: {old_st} -> {new_st}", file=sys.stderr)
        unchanged = sum(1 for c in changes if c[0] == "UNCHANGED")
        print(f"  UNCHANGED: {unchanged} entries", file=sys.stderr)

    print(f"Outputs written to {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()