#!/usr/bin/env python3
from __future__ import annotations

"""Replace only the final-card Savant audit function with the V8 bridge wrapper.

Fail-closed: projection-critical functions are fingerprinted before/after and the
patched app must compile. No projection function is intentionally modified.
"""

import argparse
import ast
import hashlib
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_SAVANT_DISPLAY_BRIDGE_V8_2026_08_23"
TARGET = "_v269_savant_shadow_rows"
CRITICAL = (
    "get_batter_k_rate_vs_pitcher_hand",
    "blend_batter_k_inputs",
    "build_mlb_projected_lineup_rows",
    "build_copy_paste_k_slate",
    "kproj_decision",
)

WRAPPER = r'''
def _v269_savant_shadow_rows(lineup_rows, pitcher_hand, expected_bf, board_row=None):
    """Display-only V8 Savant bridge. Zero production projection effect."""
    from savant_display_bridge import enrich_lineup_rows

    enriched, audit = enrich_lineup_rows(
        lineup_rows,
        pitcher_hand,
        expected_bf,
        season=int(datetime.now().year),
        app_root=Path(__file__).resolve().parent,
        storage_dir=globals().get("STORAGE_DIR"),
        allow_network_fallback=True,
    )
    if isinstance(board_row, dict):
        board_row.update({
            "savant_enriched_lineup_rows": [dict(x) for x in enriched],
            "savant_shadow_status": audit.get("status"),
            "savant_shadow_matched_hitters": int(audit.get("matched", 0) or 0),
            "simple_savant_lineup_k_pct": audit.get("simple_savant_lineup_k_pct"),
            "raw_savant_order_weighted_k_exposure": audit.get("order_weighted_savant_k_pct"),
            "top3_savant_k_pct": audit.get("top3_savant_k_pct"),
            "middle3_savant_k_pct": audit.get("middle3_savant_k_pct"),
            "bottom3_savant_k_pct": audit.get("bottom3_savant_k_pct"),
            "savant_shadow_projection_effect_k": 0.0,
            "savant_shadow_mode": "DISPLAY_ONLY_NO_PRODUCTION_EFFECT_V8",
            "savant_display_bridge_version": audit.get("display_bridge"),
            "savant_display_sources": audit.get("usable_sources"),
            "savant_display_unmatched_names": audit.get("unmatched_names"),
        })
    return enriched, audit
'''.strip("\n") + "\n"


def top_level_functions(text: str):
    tree = ast.parse(text)
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def function_text(text: str, node):
    lines = text.splitlines(keepends=True)
    return "".join(lines[node.lineno - 1:node.end_lineno])


def sha(text: str):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patch_text(text: str):
    funcs = top_level_functions(text)
    if TARGET not in funcs:
        raise RuntimeError(f"Missing target function: {TARGET}")

    before_critical = {
        name: sha(function_text(text, funcs[name]))
        for name in CRITICAL if name in funcs
    }

    node = funcs[TARGET]
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [WRAPPER]
    out = "".join(lines)
    if MARKER not in out:
        out = f"# {MARKER}\n" + out

    ast.parse(out)
    after = top_level_functions(out)
    after_critical = {
        name: sha(function_text(out, after[name]))
        for name in before_critical
    }
    changed = [name for name in before_critical if before_critical[name] != after_critical.get(name)]
    if changed:
        raise RuntimeError(f"Projection-critical function changed unexpectedly: {changed}")

    return out, {
        "critical_functions_checked": sorted(before_critical),
        "critical_functions_changed": changed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    args = parser.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched, audit = patch_text(original)

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)

    tmp = path.with_suffix(path.suffix + ".savant_display_v8_tmp")
    tmp.write_text(patched, encoding="utf-8")
    tmp.replace(path)
    print("Savant display bridge V8 READY", audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
