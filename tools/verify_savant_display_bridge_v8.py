#!/usr/bin/env python3
from __future__ import annotations

"""Functional runtime verification for the Savant display bridge.

Unlike the old marker-only verifier, this actually reads the current platoon CSV,
resolves real hitters, verifies SO/PA math, and confirms Model K% values are not
mutated by enrichment.
"""

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tools" else Path.cwd()
sys.path.insert(0, str(ROOT))

from savant_display_bridge import BRIDGE_VERSION, enrich_lineup_rows

CHECK_NAMES = [
    "Drew Gilbert", "Rafael Devers", "Victor Bericoto", "Bryce Eldridge",
    "Osleivis Basabe", "Jung Hoo Lee", "Turner Hill", "Drew Cavanaugh",
    "Christian Koss",
]


def main():
    app_path = ROOT / "app.py"
    text = app_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    targets = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_v269_savant_shadow_rows"]
    if len(targets) != 1:
        raise RuntimeError(f"Expected exactly one top-level Savant shadow function, found {len(targets)}")
    fn_text = "\n".join(text.splitlines()[targets[0].lineno - 1:targets[0].end_lineno])
    if "savant_display_bridge" not in fn_text or "DISPLAY_ONLY_NO_PRODUCTION_EFFECT_V8" not in fn_text:
        raise RuntimeError("V8 display wrapper is not active in app.py")

    rows = [
        {
            "Batter": name,
            "Hand": "L" if name in {"Drew Gilbert", "Rafael Devers", "Bryce Eldridge", "Jung Hoo Lee", "Turner Hill", "Drew Cavanaugh"} else "R",
            "Used K%": 10.0 + idx,
            "Order": idx + 1,
        }
        for idx, name in enumerate(CHECK_NAMES)
    ]
    before_used = [row["Used K%"] for row in rows]
    enriched, audit = enrich_lineup_rows(
        rows,
        "RHP",
        23.0,
        app_root=ROOT,
        storage_dir=ROOT / "mlb_engine",
        allow_network_fallback=True,
    )
    if audit.get("matched") != 9:
        raise RuntimeError(
            f"Functional Savant match failed: {audit.get('matched')}/9; "
            f"unmatched={audit.get('unmatched_names')} sources={audit.get('usable_sources')}"
        )
    after_used = [row.get("Used K%") for row in enriched]
    if before_used != after_used:
        raise RuntimeError("Display bridge mutated Model K% Used")

    for row in enriched:
        pa = row.get("savant_raw_vs_hand_pa")
        so = row.get("savant_raw_vs_hand_so")
        pct = row.get("savant_raw_vs_hand_k_pct")
        if not pa or so is None or pct is None:
            raise RuntimeError(f"Missing Savant audit fields for {row.get('Batter')}")
        expected = 100.0 * float(so) / float(pa)
        if abs(float(pct) - expected) > 0.01:
            raise RuntimeError(f"SO/PA math mismatch for {row.get('Batter')}: {pct} vs {expected}")

    print(
        f"Savant display functional verification PASS: {audit.get('matched')}/9; "
        f"bridge={BRIDGE_VERSION}; production Model K% unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
