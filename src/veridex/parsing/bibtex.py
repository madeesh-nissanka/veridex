# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""BibTeX parser with balanced-brace tokenizer."""
from __future__ import annotations

import re
from typing import Any

from veridex.models import ParsedReference
from veridex.ids import extract_identifiers, clean_doi, normalize_isbn

_FIELD_MAP = {
    "journal": "journal",
    "journaltitle": "journal",
    "volume": "volume",
    "number": "issue",
    "issue": "issue",
    "pages": "pages",
    "page": "pages",
    "publisher": "publisher",
    "url": "url",
    "doi": "doi",
    "pmid": "pmid",
    "arxiv": "arxiv_id",
    "eprint": "arxiv_id",
    "isbn": "isbn",
    "title": "title",
    "author": "authors",
    "editor": "authors",
    "year": "year",
    "date": "year",
    "booktitle": "journal",
    "series": "journal",
    "chapter": "pages",
    "edition": "edition",
    "month": "month",
    "note": "note",
    "abstract": "abstract",
    "keywords": "keywords",
    "issn": "issn",
    "isbn": "isbn",
    "howpublished": "howpublished",
    "organization": "publisher",
    "institution": "publisher",
    "school": "publisher",
    "address": "address",
    "location": "address",
}


_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


_FIELD_START_RE = re.compile(r"\n\s*[A-Za-z_][A-Za-z0-9_\-]*\s*=")

class BibtexTokenizer:
    """Tokenizes BibTeX input handling balanced braces and quotes."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.len = len(text)

    def peek(self) -> str:
        if self.pos >= self.len:
            return "\0"
        return self.text[self.pos]

    def advance(self) -> str:
        if self.pos >= self.len:
            return "\0"
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def skip_whitespace(self) -> None:
        while self.pos < self.len and self.text[self.pos].isspace():
            self.pos += 1

    def read_identifier(self) -> str:
        start = self.pos
        while self.pos < self.len:
            ch = self.text[self.pos]
            if ch.isalnum() or ch in "_-:+./":
                self.pos += 1
            else:
                break
        return self.text[start:self.pos]

    def read_braced(self) -> str:
        """Read content within balanced braces { }. On unterminated brace,
        recover by cutting at the first top-level comma and rewinding."""
        if self.pos >= self.len or self.text[self.pos] != "{":
            return ""
        start = self.pos + 1
        depth = 1
        pos = start
        first_comma = -1
        closed = False
        while pos < self.len:
            ch = self.text[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closed = True
                    break
            elif ch == "," and depth == 1 and first_comma == -1:
                first_comma = pos
            elif ch == "\n" and depth == 1:
                m = _FIELD_START_RE.match(self.text, pos)
                if m:
                    break
            pos += 1
        if closed:
            content = self.text[start:pos]
            self.pos = pos + 1
            return content
        if first_comma != -1 and first_comma < pos:
            self.pos = first_comma + 1
            return self.text[start:first_comma]
        content = self.text[start:pos]
        self.pos = pos
        return content

    def read_quoted(self) -> str:
        """Read content within double quotes."""
        if self.pos >= self.len or self.text[self.pos] != '"':
            return ""
        self.pos += 1
        start = self.pos
        while self.pos < self.len and self.text[self.pos] != '"':
            if self.text[self.pos] == "\\" and self.pos + 1 < self.len:
                self.pos += 2
            else:
                self.pos += 1
        content = self.text[start:self.pos]
        if self.pos < self.len and self.text[self.pos] == '"':
            self.pos += 1
        return content

    def read_value(self) -> str:
        """Read a field value (braced, quoted, or bare)."""
        self.skip_whitespace()
        if self.pos >= self.len:
            return ""
        ch = self.text[self.pos]
        if ch == "{":
            return self.read_braced()
        if ch == '"':
            return self.read_quoted()
        start = self.pos
        while self.pos < self.len:
            ch = self.text[self.pos]
            if ch == "}" or ch in "\n\r":
                break
            self.pos += 1
        return self.text[start:self.pos].strip().rstrip(",").strip()

    def next_token(self) -> str | None:
        """Get next significant token (@entry, identifier, =, ,, {, }, etc)."""
        self.skip_whitespace()
        if self.pos >= self.len:
            return None
        ch = self.text[self.pos]
        if ch == "@":
            self.pos += 1
            ident = self.read_identifier()
            return f"@{ident.lower()}"
        if ch in "{}(),=":
            self.pos += 1
            return ch
        if ch == "#":
            while self.pos < self.len and self.text[self.pos] != "\n":
                self.pos += 1
            return self.next_token()
        if ch == "%":
            while self.pos < self.len and self.text[self.pos] != "\n":
                self.pos += 1
            return self.next_token()
        return self.read_identifier()


def _clean_value(val: str) -> str:
    """Clean BibTeX value: remove extra braces, normalize whitespace."""
    val = val.strip()
    while val.startswith("{") and val.endswith("}") and val.count("{") == val.count("}"):
        val = val[1:-1].strip()
    val = re.sub(r"\s+", " ", val)
    return val


def _parse_authors(author_str: str) -> list[str]:
    """Split author string on ' and ', clean each name."""
    if not author_str:
        return []
    parts = re.split(r"\s+and\s+", author_str, flags=re.IGNORECASE)
    authors = []
    for part in parts:
        part = _clean_value(part)
        if part:
            authors.append(part)
    return authors


def _parse_year(year_str: str) -> int | None:
    """Extract year from various formats."""
    if not year_str:
        return None
    match = re.search(r"\b(1\d{3}|2\d{3})\b", year_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def parse_bibtex(text: str, source_file: str | None = None) -> list[ParsedReference]:
    """Parse BibTeX text into list of ParsedReference."""
    if not text or not text.strip():
        return []

    tokenizer = BibtexTokenizer(text)
    refs: list[ParsedReference] = []
    index = 0

    while True:
        token = tokenizer.next_token()
        if token is None:
            break
        if not token.startswith("@"):
            continue
        entry_type = token[1:].lower()
        if entry_type in ("string", "preamble", "comment"):
            tokenizer.skip_whitespace()
            if tokenizer.peek() == "{":
                tokenizer.read_braced()
            continue

        tokenizer.skip_whitespace()
        if tokenizer.peek() not in ("{", "("):
            continue
        tokenizer.advance()

        cite_key = ""
        tokenizer.skip_whitespace()
        if tokenizer.peek() not in (",", "}"):
            cite_key = tokenizer.read_identifier()
        tokenizer.skip_whitespace()
        if tokenizer.peek() == ",":
            tokenizer.advance()

        fields: dict[str, str] = {}
        raw_fields: dict[str, str] = {}

        while True:
            tokenizer.skip_whitespace()
            if tokenizer.peek() in ("}", ")"):
                tokenizer.advance()
                break
            if tokenizer.peek() == "\0":
                break

            field_name = tokenizer.read_identifier().lower()
            if not field_name:
                break

            tokenizer.skip_whitespace()
            if tokenizer.peek() != "=":
                continue
            tokenizer.advance()

            value = tokenizer.read_value()
            clean_val = _clean_value(value)
            raw_fields[field_name] = clean_val

            mapped = _FIELD_MAP.get(field_name)
            if mapped:
                fields[mapped] = clean_val

            tokenizer.skip_whitespace()
            if tokenizer.peek() == ",":
                tokenizer.advance()

        ref = ParsedReference(
            index=index,
            raw=text[tokenizer.pos - 100:tokenizer.pos] if tokenizer.pos > 100 else text[:tokenizer.pos],
            format="bib",
            source_file=source_file,
            raw_fields=raw_fields,
        )

        ref.title = fields.get("title")
        ref.authors = _parse_authors(fields.get("authors", ""))
        ref.year = _parse_year(fields.get("year", ""))
        ref.journal = fields.get("journal")
        ref.volume = fields.get("volume")
        ref.issue = fields.get("issue")
        ref.pages = fields.get("pages")
        ref.publisher = fields.get("publisher")
        ref.url = fields.get("url")

        ids = extract_identifiers(" ".join(filter(None, fields.values())))
        ref.doi = ids.get("doi") or (clean_doi(fields["doi"]) if fields.get("doi") else None)
        ref.pmid = ids.get("pmid") or fields.get("pmid")
        ref.arxiv_id = ids.get("arxiv_id") or fields.get("arxiv_id")
        ref.isbn = ids.get("isbn") or normalize_isbn(fields.get("isbn"))
        if not ref.url:
            ref.url = ids.get("url")

        refs.append(ref)
        index += 1

    return refs