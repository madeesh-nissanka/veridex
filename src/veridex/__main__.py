# VERIDEX v0.2.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""``python -m veridex`` entry point."""
from __future__ import annotations

import sys

from veridex.cli import main

if __name__ == "__main__":
    sys.exit(main())
