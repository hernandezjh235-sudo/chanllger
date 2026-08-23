#!/usr/bin/env python3
"""Hotfix wrapper for the final-card Savant batter display patch.

V4 had one escaped triple-quote sequence inside its injected function. Because
REPLACEMENT is a raw string, those backslashes survived and exec(REPLACEMENT)
raised SyntaxError before the card bridge could be installed. This wrapper
repairs that exact injected docstring in memory, then runs the original V4
validation + patch flow unchanged.

Display/enrichment only. It does not change the K projection formula or side.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("apply_savant_batter_display_patch.py")
spec = importlib.util.spec_from_file_location("_challenger_savant_display_v4", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BAD = r'\"\"\"Authoritative final-card Savant enrichment; no projection-side effect.\"\"\"'
GOOD = '"""Authoritative final-card Savant enrichment; no projection-side effect."""'
if BAD not in mod.REPLACEMENT:
    raise RuntimeError("Expected V4 escaped injected docstring was not found")
mod.REPLACEMENT = mod.REPLACEMENT.replace(BAD, GOOD, 1)
if BAD in mod.REPLACEMENT:
    raise RuntimeError("V5 Savant display quote repair did not fully apply")

mod.MARKER = "CHALLENGER_SAVANT_BATTER_DISPLAY_V5_2026_08_23"

if __name__ == "__main__":
    raise SystemExit(mod.main())
