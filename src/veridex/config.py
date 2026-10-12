# VERIDEX v0.3.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""User configuration file support (veridex.yaml, .veridexrc, .veridexrc.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except Exception:  # pragma: no cover - yaml is optional but recommended
    yaml = None


CONFIG_FILENAMES = ("veridex.yaml", ".veridexrc", ".veridexrc.json")

# Config keys that map to CLI options
CONFIG_KEYS = {
    "sources": list[str],
    "cache_dir": str,
    "workers": int,
    "policy": str,
    "format": str,
    "ledger": str,
    "retraction_file": str,
    "semantic": bool,
    "resume": bool,
    "no_cache": bool,
    "quiet": bool,
    "verbose": bool,
    "json": bool,
    "legacy_status": bool,
}


def find_config_file(start: Optional[str] = None) -> Optional[str]:
    """Find the nearest config file walking up from start (or CWD)."""
    if start is None:
        start = os.getcwd()
    path = Path(start).resolve()
    for parent in [path] + list(path.parents):
        for name in CONFIG_FILENAMES:
            candidate = parent / name
            if candidate.is_file():
                return str(candidate)
    return None


def load_config_file(path: str) -> dict[str, Any]:
    """Load a config file (YAML or JSON)."""
    path_obj = Path(path)
    text = path_obj.read_text(encoding="utf-8")
    if path_obj.suffix == ".json":
        return json.loads(text)
    if yaml is not None:
        return yaml.safe_load(text) or {}
    # Fallback: very minimal YAML subset for simple key: value lines
    result: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip("\"'")
            # Try to infer type
            if value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
            elif value.isdigit():
                result[key] = int(value)
            else:
                result[key] = value
    return result


def load_user_config(start: Optional[str] = None) -> dict[str, Any]:
    """Load user config from the nearest config file."""
    config_path = find_config_file(start)
    if config_path:
        return load_config_file(config_path)
    return {}


def merge_config(
    cli_ctx: Any,
    user_config: dict[str, Any],
    bool_flags: set[str],
    value_flags: set[str],
) -> None:
    """Merge user config into CLI context (CLI args take precedence)."""
    for key, value in user_config.items():
        if key in bool_flags:
            # Only set if CLI didn't explicitly provide it
            if not getattr(cli_ctx, key, False):
                setattr(cli_ctx, key, bool(value))
        elif key in value_flags:
            # Only set if CLI didn't explicitly provide it
            current = getattr(cli_ctx, key, None)
            if current is None or (isinstance(current, list) and not current):
                setattr(cli_ctx, key, value)


__all__ = [
    "CONFIG_FILENAMES",
    "CONFIG_KEYS",
    "find_config_file",
    "load_config_file",
    "load_user_config",
    "merge_config",
]