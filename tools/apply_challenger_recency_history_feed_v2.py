#!/usr/bin/env python3
"""Expose Challenger's already-fetched MLB L3/L5 K averages to Recency Shadow.

Display/research only. No projection math, side, confidence, BF/IP, probability,
grading, save/refresh behavior, Savant behavior, or other market is changed.
This patch makes no network requests: APP97 already fetched l3/l5/l10 in one
pregame MLB game-log profile; we only expose l3/l5 columns and let the shadow
read them.
"""
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RECENCY_HISTORY_FEED_V3_2026_08_28"

APP97_L10 = '            "APP97 Live L10 K Avg": l10_k,'
APP97_K_BLOCK = '''            "APP97 Live L3 K Avg": live.get("l3_k_avg"),\n\n            "APP97 Live L5 K Avg": live.get("l5_k_avg"),\n\n            "APP97 Live L10 K Avg": l10_k,'''

L3_OLD = '    l3 = _chrs_first_mean(r, ["Atlas L3 Avg K", "Trend L3 Avg 2.2", "L3 K Avg", "Recent L3 Ks"], None)'
L3_NEW = '    l3 = _chrs_first_mean(r, ["APP97 Live L3 K Avg", "Atlas L3 Avg K", "Trend L3 Avg 2.2", "L3 K Avg", "Recent L3 Ks"], None)'
L5_OLD = '    l5 = _chrs_first_mean(r, ["L5 K Avg", "Atlas L5 Avg K", "Trend L5 Avg 2.2", "Recent L5 Ks"], None)'
L5_NEW = '    l5 = _chrs_first_mean(r, ["APP97 Live L5 K Avg", "L5 K Avg", "Atlas L5 Avg K", "Trend L5 Avg 2.2", "Recent L5 Ks"], None)'


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if "def _chrs_shadow_row" not in text:
        raise RuntimeError("Recency Shadow V1 not found; app left unchanged")

    # APP97 already builds l3_k_avg/l5_k_avg/l10_k_avg from its single MLB
    # gameLog fetch. Expose the two values that were previously omitted.
    if '"APP97 Live L3 K Avg"' not in text:
        if APP97_L10 not in text:
            raise RuntimeError("APP97 live-K output anchor not found; app left unchanged")
        text = text.replace(APP97_L10, APP97_K_BLOCK, 1)

    # Let the shadow consume those already-fetched values before any older
    # fallback columns. L10 already did this in Recency Shadow V1.
    if L3_NEW not in text:
        if L3_OLD not in text:
            raise RuntimeError("Recency Shadow L3 anchor not found; app left unchanged")
        text = text.replace(L3_OLD, L3_NEW, 1)
    if L5_NEW not in text:
        if L5_OLD not in text:
            raise RuntimeError("Recency Shadow L5 anchor not found; app left unchanged")
        text = text.replace(L5_OLD, L5_NEW, 1)

    # Marker comment makes startup idempotent inside a single runtime image.
    marker_comment = f"# {MARKER}\n"
    pos = text.find("def _chrs_shadow_row")
    text = text[:pos] + marker_comment + text[pos:]
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8")
    updated = patch_text(original)
    if updated == original:
        print(f"{MARKER}: already applied")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as tf:
        tf.write(updated)
        tmp = Path(tf.name)
    try:
        py_compile.compile(str(tmp), doraise=True)
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    path.write_text(updated, encoding="utf-8")
    print(f"{MARKER}: applied safely to {path}")


if __name__ == "__main__":
    main()
