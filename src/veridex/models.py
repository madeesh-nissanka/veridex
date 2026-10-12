# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Shared data models for VERIDEX. Core is stdlib-only, type-hinted."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

TOOL_NAME = "veridex"
TOOL_VERSION = "0.3.0"


class Status:
    """Result statuses. Values are stable public strings."""

    VERIFIED = "VERIFIED"
    VERIFIED_WITH_WARNINGS = "VERIFIED_WITH_WARNINGS"
    MISMATCH = "MISMATCH"
    DOI_NOT_FOUND = "DOI_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    NO_DOI_MATCHED = "NO_DOI_MATCHED"
    NO_DOI_UNMATCHED = "NO_DOI_UNMATCHED"
    UNREACHABLE = "UNREACHABLE"
    AMBIGUOUS = "AMBIGUOUS"
    RETRACTED = "RETRACTED"
    ERROR = "ERROR"


ALL_STATUSES = (
    Status.VERIFIED, Status.VERIFIED_WITH_WARNINGS, Status.MISMATCH,
    Status.DOI_NOT_FOUND, Status.NOT_FOUND, Status.NO_DOI_MATCHED,
    Status.NO_DOI_UNMATCHED, Status.UNREACHABLE, Status.AMBIGUOUS,
    Status.RETRACTED, Status.ERROR,
)

# v0.1.x compatibility: legacy name -> v0.2 name
LEGACY_STATUS_MAP = {
    "VERIFIED": "VERIFIED",
    "VERIFIED_WITH_WARNINGS": "VERIFIED_WITH_WARNINGS",
    "MISMATCH": "MISMATCH",
    "DOI_NOT_FOUND": "DOI_NOT_FOUND",
    "NO_DOI_MATCHED": "NO_DOI_MATCHED",
    "NO_DOI_UNMATCHED": "NOT_FOUND",
    "UNREACHABLE": "UNREACHABLE",
    "RETRACTED": "RETRACTED",
}


@dataclass
class ParsedReference:
    """One reference as parsed from the input file/text."""

    index: int = 0
    raw: str = ""
    format: str = "text"
    doi: Optional[str] = None
    pmid: Optional[str] = None
    arxiv_id: Optional[str] = None
    isbn: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    raw_fields: dict[str, str] = field(default_factory=dict)
    source_file: Optional[str] = None

    def identifier(self) -> Optional[str]:
        """First machine identifier present (doi > pmid > arxiv > isbn > url)."""
        for key in ("doi", "pmid", "arxiv_id", "isbn", "url"):
            value = getattr(self, key)
            if value:
                return str(value)
        return None

    def has_identity(self) -> bool:
        return self.identifier() is not None or bool(self.title)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedRecord:
    """One candidate record returned by a source adapter (normalized)."""

    source: str = ""
    source_id: str = ""
    title: Optional[str] = None
    authors: list[dict[str, str]] = field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    arxiv_id: Optional[str] = None
    isbn: Optional[str] = None
    document_type: Optional[str] = None
    language: Optional[str] = None
    abstract: Optional[str] = None
    integrity: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None
    raw_sha256: Optional[str] = None
    raw_size: int = 0

    def surnames(self) -> list[str]:
        return [a.get("family", "") for a in self.authors if a.get("family")]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    """One network/cache interaction, hashed for the ledger."""

    source: str = ""
    request_url: str = ""
    http_status: int = 0
    response_sha256: str = ""
    response_bytes: int = 0
    timestamp: str = ""
    ok: bool = False
    error: Optional[str] = None
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditResult:
    """Outcome of auditing one parsed reference."""

    index: int = 0
    input: Optional[ParsedReference] = None
    record: Optional[ResolvedRecord] = None
    candidates: list[ResolvedRecord] = field(default_factory=list)
    status: str = Status.ERROR
    flags: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    fabrication: dict[str, Any] = field(default_factory=dict)
    integrity: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    repairs: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def retraction_status(result: AuditResult) -> bool:
    """True if any integrity entry marks the chosen record as retracted/withdrawn."""
    for item in result.integrity:
        if item.get("kind") in ("retraction", "withdrawal") and item.get("target", "work") == "work":
            return True
    return False
