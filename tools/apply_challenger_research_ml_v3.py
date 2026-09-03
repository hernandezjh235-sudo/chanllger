#!/usr/bin/env python3
"""Challenger research + Moneyline V3 runtime overlay.

Safety contract:
- Never changes Challenger K projection, K side, K confidence, BF/IP core,
  opponent K%, lineup weighting, or K distribution logic.
- Adds SHADOW workload/start-shape diagnostics to loaded board rows.
- Adds Moneyline-only F5/full-game/bullpen-hold/collapse research fields and a
  capped research probability. Canonical ML side is preserved.
- Hardens persisted live-board saves by storing the shadow-annotated board.

Designed to run late in tools/launch_stable.py against runtime_app.py.
"""
from __future__ import annotations

import argparse
import ast
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RESEARCH_ML_V3_2026_09_02"
ML_BINDING = "ml_build_board = _impl_ml_build_board_23"

BLOCK = r'''
# =============================================================================
# CHALLENGER_RESEARCH_ML_V3_2026_09_02
# K side = SHADOW ONLY. Moneyline side = support/research overlay only.
# Protected Challenger K core is never modified by this block.
# =============================================================================
import math as _crml_math

CRML_V3_VERSION = "CHALLENGER_RESEARCH_ML_V3_2026_09_02"


def _crml_num(v, default=None):
    try:
        if v is None or v == "":
            return default
        x = float(str(v).replace("%", "").replace(",", "").strip())
        return x if _crml_math.isfinite(x) else default
    except Exception:
        return default


def _crml_clamp(x, lo=0.0, hi=100.0):
    try:
        return max(float(lo), min(float(hi), float(x)))
    except Exception:
        return float(lo)


def _crml_first(row, keys, default=None):
    if not isinstance(row, dict):
        return default
    for k in keys:
        if row.get(k) not in (None, ""):
            return row.get(k)
    norm = {"".join(ch for ch in str(k).lower() if ch.isalnum()): k for k in row.keys()}
    for k in keys:
        nk = "".join(ch for ch in str(k).lower() if ch.isalnum())
        real = norm.get(nk)
        if real is not None and row.get(real) not in (None, ""):
            return row.get(real)
    return default


def _crml_pct_tail(threshold, mean, sigma):
    try:
        z = (float(threshold) - float(mean)) / max(0.15, float(sigma))
        cdf = 0.5 * (1.0 + _crml_math.erf(z / _crml_math.sqrt(2.0)))
        return _crml_clamp(100.0 * cdf)
    except Exception:
        return 50.0


def _crml_kshape_one(row):
    """Return research-only start-shape diagnostics from already-projected inputs."""
    r = dict(row or {})
    ip = _crml_num(_crml_first(r, [
        "IP", "Projected IP", "Proj IP", "IP Projection", "Expected IP",
        "Challenger IP", "CHALLENGER IP", "Starter IP Projection"
    ]), None)
    kproj = _crml_num(_crml_first(r, [
        "Projected K", "Proj K", "K Projection", "Projection", "Strikeout Projection",
        "Challenger K", "CHALLENGER K"
    ]), None)
    if ip is None or ip <= 0:
        return r

    bb = _crml_num(_crml_first(r, ["BB%", "Pitcher BB%", "Walk %", "Walk%"]), None)
    hr9 = _crml_num(_crml_first(r, ["HR/9", "Pitcher HR/9", "HR9"]), None)
    hard = _crml_num(_crml_first(r, ["HardHit%", "Hard Hit %", "Pitcher HardHit%"]), None)
    barrel = _crml_num(_crml_first(r, ["Barrel%", "Barrel %", "Pitcher Barrel%"]), None)
    pbf = _crml_num(_crml_first(r, ["Pitches/BF", "P/BF", "Pitches per BF", "Pitches/Batter"]), None)

    collapse = 14.0
    if bb is not None:
        collapse += _crml_clamp((bb - 7.5) * 1.8, -5.0, 20.0)
    if hr9 is not None:
        collapse += _crml_clamp((hr9 - 0.9) * 12.0, -4.0, 16.0)
    if hard is not None:
        collapse += _crml_clamp((hard - 35.0) * 0.55, -5.0, 15.0)
    if barrel is not None:
        collapse += _crml_clamp((barrel - 7.0) * 1.25, -4.0, 14.0)
    if pbf is not None:
        collapse += _crml_clamp((pbf - 3.85) * 18.0, -5.0, 18.0)
    if ip < 5.0:
        collapse += (5.0 - ip) * 7.0
    collapse = _crml_clamp(collapse, 5.0, 78.0)

    sigma = _crml_clamp(0.58 + collapse / 100.0 * 0.70, 0.55, 1.15)
    p25 = max(1.0, ip - 0.674 * sigma)
    p75 = min(9.0, ip + 0.674 * sigma)
    p_lt5 = _crml_pct_tail(5.0, ip, sigma)
    p6 = 100.0 - _crml_pct_tail(6.0, ip, sigma)
    p7 = 100.0 - _crml_pct_tail(7.0, ip, sigma)
    deep = _crml_clamp(0.68 * p6 + 0.32 * p7)

    r["K Research Version"] = CRML_V3_VERSION
    r["K Shadow IP P25"] = round(p25, 2)
    r["K Shadow IP P50"] = round(ip, 2)
    r["K Shadow IP P75"] = round(p75, 2)
    r["K Shadow P(<5 IP) %"] = round(p_lt5, 1)
    r["K Shadow P(6+ IP) %"] = round(p6, 1)
    r["K Shadow P(7+ IP) %"] = round(p7, 1)
    r["K Shadow Early Exit Risk %"] = round(p_lt5, 1)
    r["K Shadow Deep Start Score"] = round(deep, 1)
    r["K Shadow Starter Collapse Risk %"] = round(collapse, 1)

    if kproj is not None and ip > 0.1:
        kip = kproj / ip
        r["K Shadow Opportunity K P25"] = round(max(0.0, kip * p25), 2)
        r["K Shadow Opportunity K P50"] = round(max(0.0, kproj), 2)
        r["K Shadow Opportunity K P75"] = round(max(0.0, kip * p75), 2)
    return r


def _crml_annotate_board(board):
    if not isinstance(board, (list, tuple)):
        return board
    return [_crml_kshape_one(x) if isinstance(x, dict) else x for x in board]


try:
    if callable(globals().get("_state_v2_save_board")) and not getattr(_state_v2_save_board, "_crml_v3", False):
        _crml_old_state_save = _state_v2_save_board
        def _crml_state_save(picks):
            return _crml_old_state_save(_crml_annotate_board(picks))
        _crml_state_save._crml_v3 = True
        _state_v2_save_board = _crml_state_save
except Exception:
    pass

try:
    if st.session_state.get("loaded_picks"):
        st.session_state.loaded_picks = _crml_annotate_board(st.session_state.loaded_picks)
except Exception:
    pass


def _crml_ml_prob(row):
    return _crml_num(_crml_first(row, [
        "ML Environment Adjusted Win Prob %", "ML Support Adjusted Win Prob %",
        "ML Card Best Play Prob %", "Canonical Win Probability", "ML Win Prob %", "Win Probability"
    ]), None)


def _crml_ml_quality(row):
    return _crml_num(_crml_first(row, ["ML Data Quality Score", "ML Data Quality", "Data Quality"]), 75.0) or 75.0


def _crml_ml_fatigue(row):
    raw = _crml_num(_crml_first(row, [
        "ML Bullpen Fatigue %", "Bullpen Fatigue %", "Bullpen Fatigue", "Pen Fatigue",
        "Bullpen Workload %", "Bullpen Workload"
    ]), None)
    if raw is None:
        return 50.0
    if 0 <= raw <= 1.0:
        raw *= 100.0
    return _crml_clamp(raw)


def _crml_ml_late_offense(row):
    offense = _crml_num(row.get("ML Offense Vs Hand Edge"), 0.0) or 0.0
    contact = _crml_num(row.get("ML Contact Quality Edge"), 0.0) or 0.0
    run_share = _crml_num(row.get("ML Team Scoring Share %"), 50.0) or 50.0
    return _crml_clamp(50.0 + offense * 2.0 + contact * 1.0 + (run_share - 50.0) * 1.2)


def _crml_ml_overlay_row(row):
    r = dict(row or {})
    starter_edge = _crml_num(r.get("ML Starter Edge"), 0.0) or 0.0
    bullpen_edge = _crml_num(r.get("ML Bullpen Edge"), 0.0) or 0.0
    offense_edge = _crml_num(r.get("ML Offense Vs Hand Edge"), 0.0) or 0.0
    contact_edge = _crml_num(r.get("ML Contact Quality Edge"), 0.0) or 0.0
    env = _crml_num(r.get("ML Environment Score V2"), 50.0) or 50.0
    blowout = _crml_num(r.get("ML Blowout Score"), 50.0) or 50.0
    fatigue = _crml_ml_fatigue(r)
    late_off = _crml_ml_late_offense(r)

    f5 = _crml_clamp(50.0 + 3.0 * starter_edge + 1.6 * offense_edge + 0.8 * contact_edge)
    bullpen_hold = _crml_clamp(50.0 + 3.2 * bullpen_edge - 0.22 * (fatigue - 50.0))

    explicit_collapse = _crml_num(_crml_first(r, [
        "ML Starter Collapse Risk %", "Starter Collapse Risk %", "K Shadow Starter Collapse Risk %"
    ]), None)
    if explicit_collapse is None:
        explicit_collapse = _crml_clamp(25.0 - 4.2 * starter_edge + max(0.0, blowout - 70.0) * 0.18, 6.0, 72.0)
    collapse = explicit_collapse

    full = _crml_clamp(
        0.44 * f5 + 0.22 * bullpen_hold + 0.14 * late_off +
        0.12 * env + 0.08 * blowout - 0.10 * max(0.0, collapse - 35.0)
    )
    f5_to_full = full - f5
    quality = _crml_ml_quality(r)
    base_prob = _crml_ml_prob(r)
    support = (full - 50.0) * 0.16
    if bullpen_hold < 42.0:
        support -= min(1.5, (42.0 - bullpen_hold) * 0.07)
    if collapse > 55.0:
        support -= min(1.5, (collapse - 55.0) * 0.07)
    if quality < 60.0:
        support *= 0.35
    support = max(-4.0, min(4.0, support))
    research_prob = None if base_prob is None else _crml_clamp(base_prob + support, 1.0, 99.0)

    if quality < 55:
        action = "LOW DATA / PASS"
    elif full >= 68 and bullpen_hold >= 55 and collapse <= 45:
        action = "STRONG FULL-GAME SUPPORT"
    elif full >= 59 and collapse <= 55:
        action = "SUPPORTED"
    elif full <= 43 or bullpen_hold <= 38 or collapse >= 65:
        action = "CONFLICT / PASS"
    else:
        action = "NEUTRAL / TRACK"

    r["ML V3 Version"] = CRML_V3_VERSION
    r["ML F5 Strength Score V3"] = round(f5, 1)
    r["ML Bullpen Hold Score V3"] = round(bullpen_hold, 1)
    r["ML Bullpen Fatigue Score V3"] = round(fatigue, 1)
    r["ML Late Offense Score V3"] = round(late_off, 1)
    r["ML Starter Collapse Risk V3 %"] = round(collapse, 1)
    r["ML Full Game Strength Score V3"] = round(full, 1)
    r["ML F5→Full Delta V3"] = round(f5_to_full, 1)
    r["ML V3 Probability Adjustment"] = round(support, 2)
    r["ML V3 Research Win Prob %"] = None if research_prob is None else round(research_prob, 1)
    r["ML V3 Action"] = action
    r["ML V3 Canonical Side Preserved"] = True
    return r


_crml_ml_v2_build = _impl_ml_build_board_23

def _impl_ml_build_board_research_v3(board):
    df = _crml_ml_v2_build(board)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    try:
        rows = [_crml_ml_overlay_row(rr.to_dict()) for _, rr in df.iterrows()]
        return pd.DataFrame(rows, index=df.index)
    except Exception:
        return df

ml_build_board = _impl_ml_build_board_research_v3
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if ML_BINDING not in text:
        raise RuntimeError("Moneyline V2 public binding not found; apply ML environment V2 first")
    text = text.replace(ML_BINDING, BLOCK, 1)
    ast.parse(text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8")
    try:
        patched = patch_text(original)
        with tempfile.TemporaryDirectory() as td:
            probe = Path(td) / "runtime_probe.py"
            probe.write_text(patched, encoding="utf-8")
            py_compile.compile(str(probe), doraise=True)
        if patched != original:
            path.write_text(patched, encoding="utf-8")
        print(f"Research/ML V3 READY: {path}")
    except Exception as exc:
        print(f"Research/ML V3 SKIPPED safely: {exc}")


if __name__ == "__main__":
    main()
