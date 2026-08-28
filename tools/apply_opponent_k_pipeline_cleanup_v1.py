#!/usr/bin/env python3
"""Challenger opponent-K pipeline cleanup.

1) APP97 uses season vs-hand + current lineup, not recent team windows a second time.
   Recent team form remains upstream in Matchup Intel.
2) K cards display true lineup exposure when available.
3) L5/L10 labels explicitly say DAYS and include pitcher hand.

Surgical scope: K opponent-environment pipeline/card labels only. No BF/IP,
pitcher skill, probability/distribution, grading, save/refresh, Savant refresh,
Pitching Outs, FS, or Moneyline logic is touched.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_OPP_K_PIPELINE_CLEANUP_V1_2026_08_28"
TARGET_FN = "_app97_recent_hand_profile"

CARD_OLD = '''            opp_k = _kclean_fmt(_kclean_pick(row, ["Opponent K% vs Pitcher Hand", "APP97 Opponent K Environment", "APP88 Batter Lineup K%"], ""), 1)\n\n            hand_window = "LHP" if str(hand).upper().startswith("L") else "RHP"\n\n            opp_l10 = _kclean_fmt(_kclean_pick(row, [f"Opp L10 K% vs {hand_window} Official", "Team K% L10 vs Hand"], ""), 1)\n\n            opp_l5 = _kclean_fmt(_kclean_pick(row, [f"Opp L5 K% vs {hand_window} Official", "Team K% L5 vs Hand"], ""), 1)\n'''

CARD_NEW = '''            # True current-lineup exposure for the public card. Do not label the\n            # season/team split as lineup exposure.\n            opp_k = _kclean_fmt(_kclean_pick(row, [\n                "Lineup Exposure K%", "lineup_exposure_k_pct",\n                "UB Lineup Exposure K%", "APP88 Batter Lineup K%", "Lineup K%",\n                "Opponent K% vs Pitcher Hand", "APP97 Opponent K Environment"\n            ], ""), 1)\n\n            hand_window = "LHP" if str(hand).upper().startswith("L") else "RHP"\n\n            opp_season = _kclean_fmt(_kclean_pick(row, [\n                "Team K% Season vs Hand", f"Opp K% vs {hand_window} Official",\n                "Opponent K% vs Pitcher Hand"\n            ], ""), 1)\n\n            opp_l10 = _kclean_fmt(_kclean_pick(row, [f"Opp L10 K% vs {hand_window} Official", "Team K% L10 vs Hand"], ""), 1)\n\n            opp_l5 = _kclean_fmt(_kclean_pick(row, [f"Opp L5 K% vs {hand_window} Official", "Team K% L5 vs Hand"], ""), 1)\n'''

LINES_OLD = '''            if opp_k != "—": _opp_lines.append(f"Exposure {opp_k}%")\n\n            if opp_l10 != "—": _opp_lines.append(f"L10 {opp_l10}%")\n\n            if opp_l5 != "—": _opp_lines.append(f"L5 {opp_l5}%")\n'''

LINES_NEW = '''            if opp_k != "—": _opp_lines.append(f"Lineup Exposure {opp_k}%")\n\n            if opp_season != "—": _opp_lines.append(f"Season vs {hand_window} {opp_season}%")\n\n            if opp_l10 != "—": _opp_lines.append(f"Last 10 Days vs {hand_window} {opp_l10}%")\n\n            if opp_l5 != "—": _opp_lines.append(f"Last 5 Days vs {hand_window} {opp_l5}%")\n'''


def _replace_top_level_function(text: str) -> str:
    tree = ast.parse(text)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == TARGET_FN and getattr(n, 'col_offset', 1) == 0]
    if len(nodes) != 1:
        raise RuntimeError(f"Expected exactly one {TARGET_FN}, found {len(nodes)}")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno
    original = ''.join(lines[start:end])
    legacy = original.replace(f"def {TARGET_FN}(", f"def _legacy{TARGET_FN}(", 1).rstrip('\r\n')
    wrapper = r'''
def _app97_recent_hand_profile(row):
    """APP97 opponent baseline without duplicate recent-team-K influence.

    Matchup Intel already owns the PA-shrunk L3/L5/L10/L15/L30 recency family.
    APP97 therefore uses the stable season vs-hand team baseline and blends it
    with the current lineup once. Legacy recent blend is retained only as audit
    detail and as a fail-safe fallback if the season split is missing.
    """
    legacy_env, split_suspect, legacy_detail = _legacy_app97_recent_hand_profile(row)
    season_hand = _app97_pct(row.get("Team K% Season vs Hand"), None)
    if season_hand is None:
        season_hand = _app97_pct(row.get("Opponent K% vs Pitcher Hand"), None)
    if season_hand is None:
        return legacy_env, split_suspect, f"FALLBACK legacy recent blend; {legacy_detail}"
    detail = (
        f"season_vs_hand_only {season_hand:.1f}; recent team form applied once upstream "
        f"in Matchup Intel; legacy APP97 recent blend audit={legacy_env:.1f}"
        if legacy_env is not None else
        f"season_vs_hand_only {season_hand:.1f}; recent team form applied once upstream in Matchup Intel"
    )
    return season_hand, split_suspect, detail
'''.lstrip('\n')
    lines[start:end] = [legacy + '\n\n' + wrapper + '\n']
    return ''.join(lines)


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    out = _replace_top_level_function(text)
    if CARD_OLD not in out:
        raise RuntimeError("K card opponent-K source block not found; app left unchanged")
    out = out.replace(CARD_OLD, CARD_NEW, 1)
    if LINES_OLD not in out:
        raise RuntimeError("K card opponent-K label block not found; app left unchanged")
    out = out.replace(LINES_OLD, LINES_NEW, 1)
    out = f"# {MARKER}\n" + out
    ast.parse(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', default='app.py')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding='utf-8-sig')
    updated = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / 'app.py'
        probe.write_text(updated, encoding='utf-8')
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print(f"{MARKER}: CHECK PASS")
        return
    if updated != original:
        path.write_text(updated, encoding='utf-8')
    print(f"{MARKER}: {'applied' if updated != original else 'already applied'}")

if __name__ == '__main__':
    main()
