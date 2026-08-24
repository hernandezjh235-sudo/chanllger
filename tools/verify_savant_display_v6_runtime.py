#!/usr/bin/env python3
"""Fail-closed runtime guard for Challenger Savant final-card display V6.

This script is read-only. It does not modify projections or app.py. It simply
verifies that the deployed app still contains the V6 final-card Savant bridge
and that an older V4/V5 display patch has not replaced it during startup.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path("app.py")
TARGET = "_v269_savant_shadow_rows"
REQUIRED_MARKER = "CHALLENGER_SAVANT_BATTER_DISPLAY_V6_2026_08_23"
REQUIRED_TOKENS = (
    "FINAL_CARD_SAVANT_SO_PA_V6",
    "app_root = Path(__file__).resolve().parent",
    "data_roots = []",
    "savant_batter_platoon_{season}.csv",
    "Savant Raw Math",
)


def main() -> int:
    text = APP.read_text(encoding="utf-8")
    if REQUIRED_MARKER not in text:
        raise RuntimeError("Savant display V6 marker missing from app.py")

    tree = ast.parse(text)
    nodes = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == TARGET
    ]
    if len(nodes) != 1:
        raise RuntimeError(f"Expected one top-level {TARGET}, found {len(nodes)}")

    node = nodes[0]
    lines = text.splitlines()
    fn = "\n".join(lines[node.lineno - 1:node.end_lineno])
    missing = [token for token in REQUIRED_TOKENS if token not in fn]
    if missing:
        raise RuntimeError(f"Savant display V6 runtime guard failed; missing {missing}")

    if "FINAL_CARD_SAVANT_SO_PA_V4" in fn or "FINAL_CARD_SAVANT_SO_PA_V5" in fn:
        raise RuntimeError("Older Savant display bridge replaced V6 during startup")

    print("Savant final-card display V6 runtime guard PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
