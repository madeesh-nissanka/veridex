# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Policy loading, validation and evaluation. Stdlib only.

The policy format is a small YAML subset (indentation maps, ``- item`` lists,
``[a, b]`` inline lists, quoted scalars, ints/floats/bools/null and ``#``
comments) or plain JSON. Anchors, aliases, multi-document streams and block
scalars are intentionally unsupported.
"""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from veridex.models import ALL_STATUSES, ParsedReference, Status

DEFAULT_POLICY: dict[str, Any] = {
    "fail_on": [],
    "max_fabrication_score": 1.0,
    "max_weak_context_ratio": 1.0,
    "min_verified_ratio": 0.0,
    "required_fields": [],
    "allowed_venues": [],
    "blocked_venues": [],
}

_KNOWN_KEYS = set(DEFAULT_POLICY)
_RATIO_KEYS = ("max_fabrication_score", "max_weak_context_ratio", "min_verified_ratio")
_STATUS_SET = set(ALL_STATUSES)
_VALID_FIELDS = {f.name for f in fields(ParsedReference)}
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_QUOTED_RE = re.compile(r"^(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')$")


# --------------------------------------------------------------------------
# Mini YAML subset parser
# --------------------------------------------------------------------------
def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment, ignoring ``#`` inside quotes."""
    out: list[str] = []
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out)


def _split_inline(text: str) -> list[str]:
    """Split a comma-separated inline list, honouring quotes and nesting."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == "[":
            depth += 1
            cur.append(ch)
        elif ch == "]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail or parts:
        parts.append(tail)
    return parts


def _unquote(text: str) -> str:
    quote = text[0]
    body = text[1:-1]
    if quote == '"':
        body = body.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    else:
        body = body.replace("''", "'")
    return body


def _scalar(text: str) -> Any:
    """Parse one scalar / inline-list token."""
    text = text.strip()
    if text == "":
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if inner == "":
            return []
        return [_scalar(part) for part in _split_inline(inner)]
    if len(text) >= 2 and _QUOTED_RE.match(text):
        return _unquote(text)
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~", "none"):
        return None
    if _INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            pass
    if _FLOAT_RE.match(text) and ("." in text or "e" in lowered):
        try:
            return float(text)
        except ValueError:
            pass
    return text


class _Lines:
    """Tokenised, comment-stripped input lines."""

    def __init__(self, text: str) -> None:
        self.lines: list[tuple[int, str]] = []
        normalised = text.replace("\r\n", "\n").replace("\r", "\n")
        for raw in normalised.split("\n"):
            stripped = _strip_comment(raw)
            if stripped.strip() == "":
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            self.lines.append((indent, stripped.strip()))
        self.pos = 0

    def peek(self) -> tuple[int, str] | None:
        return self.lines[self.pos] if self.pos < len(self.lines) else None


def _as_mapping_item(text: str) -> tuple[str, str] | None:
    """Return ``(key, rest)`` when ``text`` looks like ``key: value``."""
    key, sep, rest = text.partition(":")
    if not sep:
        return None
    if rest != "" and not rest.startswith(" "):
        return None
    key_norm = key.strip()
    if _KEY_RE.match(key_norm) or _QUOTED_RE.match(key_norm):
        return key_norm, rest.strip()
    return None


class _Parser:
    def __init__(self, data: _Lines) -> None:
        self.data = data

    def parse(self) -> Any:
        if not self.data.lines:
            return {}
        return self._block(self.data.lines[0][0])

    def _block(self, indent: int) -> Any:
        nxt = self.data.peek()
        if nxt is None:
            return None
        content = nxt[1]
        if content == "-" or content.startswith("- "):
            return self._list(indent)
        return self._map(indent)

    def _map(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            nxt = self.data.peek()
            if nxt is None:
                break
            line_indent, content = nxt
            if line_indent != indent:
                break
            if content == "-" or content.startswith("- "):
                break
            pair = _as_mapping_item(content)
            if pair is None:
                self.data.pos += 1
                continue
            key, rest = pair
            if _QUOTED_RE.match(key):
                key = _unquote(key)
            self.data.pos += 1
            if rest == "":
                following = self.data.peek()
                if following is not None and following[0] > indent:
                    result[key] = self._block(following[0])
                else:
                    result[key] = None
            else:
                result[key] = _scalar(rest)
        return result

    def _list(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while True:
            nxt = self.data.peek()
            if nxt is None:
                break
            line_indent, content = nxt
            if line_indent != indent:
                break
            if not (content == "-" or content.startswith("- ")):
                break
            item_text = content[1:].strip()
            self.data.pos += 1

            pair = _as_mapping_item(item_text) if item_text else None
            if pair is not None:
                key, rest = pair
                if _QUOTED_RE.match(key):
                    key = _unquote(key)
                item: dict[str, Any] = {}
                if rest == "":
                    following = self.data.peek()
                    if following is not None and following[0] > indent:
                        item[key] = self._block(following[0])
                    else:
                        item[key] = None
                else:
                    item[key] = _scalar(rest)
                following = self.data.peek()
                if (
                    following is not None
                    and following[0] > indent
                    and not following[1].startswith("-")
                ):
                    extra = self._map(following[0])
                    item.update(extra)
                result.append(item)
            elif item_text == "":
                following = self.data.peek()
                if following is not None and following[0] > indent:
                    result.append(self._block(following[0]))
                else:
                    result.append(None)
            else:
                result.append(_scalar(item_text))
        return result


def parse_yaml(text: str) -> Any:
    """Parse the supported YAML subset into Python data structures."""
    if text is None:
        return None
    return _Parser(_Lines(text)).parse()


# --------------------------------------------------------------------------
# Loading / validation
# --------------------------------------------------------------------------
def load_policy(path_or_text: "str | os.PathLike[str]") -> dict[str, Any]:
    """Load a policy from a filesystem path or from a JSON/YAML string.

    Existing files are read; anything else is treated as inline text. JSON is
    tried first, then the YAML subset. Returns ``DEFAULT_POLICY`` copy when the
    input is empty. Raises ``ValueError`` when the result is not a mapping.
    """
    text: str
    if isinstance(path_or_text, (str, os.PathLike)):
        candidate = os.fspath(path_or_text)
        if candidate and os.path.exists(candidate):
            text = Path(candidate).read_text(encoding="utf-8")
        else:
            text = str(candidate)
    else:
        raise TypeError("policy source must be a path or a string")

    if text.strip() == "":
        return copy.deepcopy(DEFAULT_POLICY)

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = parse_yaml(text)
    else:
        data = parse_yaml(text)

    if data is None:
        return copy.deepcopy(DEFAULT_POLICY)
    if not isinstance(data, dict):
        raise ValueError("policy root must be a mapping")
    return data


def validate_policy(data: Any) -> list[str]:
    """Return a list of human-readable policy problems (empty when valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["policy root must be a mapping"]

    for key in sorted(data):
        if key not in _KNOWN_KEYS:
            errors.append(f"unknown policy key: {key}")

    fail_on = data.get("fail_on", [])
    if not isinstance(fail_on, list):
        errors.append("fail_on must be a list of status strings")
    else:
        for item in fail_on:
            if not isinstance(item, str):
                errors.append(f"fail_on entry is not a string: {item!r}")
            elif item not in _STATUS_SET:
                errors.append(f"unknown status in fail_on: {item}")

    for key in _RATIO_KEYS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{key} must be a number between 0 and 1")
        elif not 0.0 <= float(value) <= 1.0:
            errors.append(f"{key} must be between 0 and 1")

    required = data.get("required_fields", [])
    if not isinstance(required, list):
        errors.append("required_fields must be a list of field names")
    else:
        for item in required:
            if not isinstance(item, str):
                errors.append(f"required_fields entry is not a string: {item!r}")
            elif item not in _VALID_FIELDS:
                errors.append(f"unknown reference field in required_fields: {item}")

    for key in ("allowed_venues", "blocked_venues"):
        value = data.get(key, [])
        if not isinstance(value, list):
            errors.append(f"{key} must be a list of venue strings")
        else:
            for item in value:
                if not isinstance(item, str):
                    errors.append(f"{key} entry is not a string: {item!r}")

    return errors


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return {}  # pragma: no cover - defensive


def _fabrication_score(result: dict[str, Any]) -> float:
    fabric = result.get("fabrication") or {}
    if isinstance(fabric, dict):
        value = fabric.get("score")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _input_dict(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("input")
    return value if isinstance(value, dict) else {}


def _record_dict(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("record")
    return value if isinstance(value, dict) else {}


def _venue_of(record: dict[str, Any]) -> str:
    for key in ("journal", "container_title", "publisher"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def _make_violation(code: str, message: str, index: int | None = None,
                    status: str | None = None, field: str | None = None,
                    value: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "index": index,
        "status": status,
        "field": field,
        "value": value,
    }


def evaluate_policy(results: list[Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate ``results`` against ``policy`` and return violations.

    The returned list is deterministically ordered by ``(code, index, field)``.
    """
    policy = policy or {}
    dicts = [_as_dict(r) for r in results]
    violations: list[dict[str, Any]] = []

    fail_on = {s for s in policy.get("fail_on", []) if isinstance(s, str)}
    for result in dicts:
        status = result.get("status")
        if status in fail_on:
            violations.append(
                _make_violation(
                    "fail_on",
                    f"entry {result.get('index')} status {status} is in fail_on",
                    index=result.get("index"),
                    status=status,
                )
            )

    max_fabrication = policy.get("max_fabrication_score")
    if isinstance(max_fabrication, (int, float)) and not isinstance(max_fabrication, bool):
        for result in dicts:
            score = _fabrication_score(result)
            if score > float(max_fabrication) + 1e-9:
                violations.append(
                    _make_violation(
                        "max_fabrication_score",
                        f"entry {result.get('index')} fabrication score {score:.4f} "
                        f"exceeds {max_fabrication}",
                        index=result.get("index"),
                        status=result.get("status"),
                        value=score,
                    )
                )

    max_weak = policy.get("max_weak_context_ratio")
    if isinstance(max_weak, (int, float)) and not isinstance(max_weak, bool):
        weak = 0
        total = 0
        for result in dicts:
            context = result.get("context")
            entries = context if isinstance(context, list) else ([context] if context else [])
            for entry in entries:
                if isinstance(entry, dict):
                    total += 1
                    if str(entry.get("label", "")).upper() == "WEAK":
                        weak += 1
        ratio = (weak / total) if total else 0.0
        if ratio > float(max_weak) + 1e-9:
            violations.append(
                _make_violation(
                    "max_weak_context_ratio",
                    f"weak context ratio {ratio:.4f} exceeds {max_weak}",
                    value=ratio,
                )
            )

    required = [f for f in policy.get("required_fields", []) if isinstance(f, str)]
    if required:
        for result in dicts:
            source = _input_dict(result)
            for field in required:
                if _is_empty(source.get(field)):
                    violations.append(
                        _make_violation(
                            "missing_required_field",
                            f"entry {result.get('index')} is missing required field '{field}'",
                            index=result.get("index"),
                            field=field,
                        )
                    )

    allowed = [v.casefold() for v in policy.get("allowed_venues", []) if isinstance(v, str)]
    blocked = [v.casefold() for v in policy.get("blocked_venues", []) if isinstance(v, str)]
    for result in dicts:
        record = _record_dict(result)
        venue = _venue_of(record)
        if not venue:
            continue
        folded = venue.casefold()
        if allowed and folded not in allowed:
            violations.append(
                _make_violation(
                    "venue_not_allowed",
                    f"entry {result.get('index')} venue '{venue}' is not allowed",
                    index=result.get("index"),
                    field="journal",
                    value=venue,
                )
            )
        if blocked and folded in blocked:
            violations.append(
                _make_violation(
                    "venue_blocked",
                    f"entry {result.get('index')} venue '{venue}' is blocked",
                    index=result.get("index"),
                    field="journal",
                    value=venue,
                )
            )

    min_verified = policy.get("min_verified_ratio")
    if isinstance(min_verified, (int, float)) and not isinstance(min_verified, bool):
        total = len(dicts)
        verified = sum(
            1
            for r in dicts
            if r.get("status") in (Status.VERIFIED, Status.VERIFIED_WITH_WARNINGS)
        )
        ratio = (verified / total) if total else 0.0
        if ratio < float(min_verified) - 1e-9:
            violations.append(
                _make_violation(
                    "min_verified_ratio",
                    f"verified ratio {ratio:.4f} is below {min_verified}",
                    value=ratio,
                )
            )

    violations.sort(
        key=lambda v: (str(v.get("code")), v.get("index") if v.get("index") is not None else -1,
                       str(v.get("field") or ""))
    )
    return violations


__all__ = [
    "DEFAULT_POLICY",
    "load_policy",
    "parse_yaml",
    "validate_policy",
    "evaluate_policy",
]
