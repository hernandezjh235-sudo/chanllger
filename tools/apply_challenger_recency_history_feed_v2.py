#!/usr/bin/env python3
"""Fill Challenger Recency Shadow L3/L5/L10 Ks from existing local game logs.

This patch is display/research only. It does not change Challenger projections,
side, confidence, BF/IP, probabilities, grading, Savant refresh behavior, or any
other market. It never makes a network request.
"""
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RECENCY_HISTORY_FEED_V2_2026_08_28"

HELPER = r'''
# CHALLENGER_RECENCY_HISTORY_FEED_V2_2026_08_28
# Local/pregame game-log fallback for the read-only Recency Trap shadow.
def _chrs_log_k_avgs(name):
    vals = []
    try:
        fn = globals().get("_tpl_k_values_from_logs")
        if callable(fn):
            raw = fn(name) or []
            for v in raw:
                try:
                    x = float(v)
                    if np.isfinite(x):
                        vals.append(x)
                except Exception:
                    pass
    except Exception:
        vals = []
    vals = vals[:10]  # helper already returns newest -> oldest
    out = {}
    for n in (3, 5, 10):
        use = vals[:n]
        if use:
            out[n] = float(np.mean(use))
    return out
'''.strip()

OLD = '''    l3 = _chrs_first_mean(r, ["Atlas L3 Avg K", "Trend L3 Avg 2.2", "L3 K Avg", "Recent L3 Ks"], None)\n    l5 = _chrs_first_mean(r, ["L5 K Avg", "Atlas L5 Avg K", "Trend L5 Avg 2.2", "Recent L5 Ks"], None)\n    l10 = _chrs_first_mean(r, ["Atlas L10 Avg K", "APP97 Live L10 K Avg", "L10 K Avg", "Trend L10 Avg"], None)\n'''

NEW = OLD + '''    # If table columns are absent, use the app's existing local pitcher game log.\n    # This is the same pregame history source already used elsewhere in Challenger.\n    _log_k = _chrs_log_k_avgs(name)\n    if l3 is None:\n        l3 = _log_k.get(3)\n    if l5 is None:\n        l5 = _log_k.get(5)\n    if l10 is None:\n        l10 = _log_k.get(10)\n'''


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if "def _chrs_shadow_row" not in text:
        raise RuntimeError("Recency Shadow V1 was not found; app left unchanged")
    if OLD not in text:
        raise RuntimeError("Recency Shadow recent-K block was not found; app left unchanged")
    anchor = "def _chrs_shadow_row(r):"
    pos = text.find(anchor)
    text = text[:pos] + HELPER + "\n\n\n" + text[pos:]
    text = text.replace(OLD, NEW, 1)
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
