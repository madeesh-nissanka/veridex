# VERIDEX v0.3.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""VERIDEX: validate reference lists against public scholarly sources with
tamper-evident provenance. Stdlib-only core."""

from veridex.models import TOOL_NAME, TOOL_VERSION as __version__

ABOUT = (
    "veridex 0.3.0 - reference validation and provenance auditing\n"
    "Copyright (c) 2026 Madeesh P. Nissanka\n"
    "License: MIT\n"
)


def about() -> str:
    """Version/license/copyright blurb for --about/--version."""
    return ABOUT


__all__ = ["TOOL_NAME", "__version__", "about", "ABOUT"]
