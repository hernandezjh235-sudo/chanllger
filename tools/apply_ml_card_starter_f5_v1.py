#!/usr/bin/env python3
"""Moneyline card starter-stat + First-5 display patch.

UI/data-only overlay. It does not change Challenger K projection math, side,
confidence, BF/IP core, opponent K%, or canonical Moneyline side.

Adds:
- starter K%, ERA, WHIP, K/9 and projected IP metadata to ML rows/cards;
- explicit projected First-5 winner + F5 probability;
- compact F5 label inside the existing canonical-best-play card area when the
  current HTML renderer exposes the expected text;
- safe fallback First-5/starter summary panel if HTML injection is unavailable.
"""
from __future__ import annotations

import argparse
import ast
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_ML_CARD_STARTER_F5_V1_2026_09_02"
TAB_ANCHOR = "tab_kproj, tab_brain, tab_beta_outs, tab_first_inning_k, tab_beta_ip_debug, tab_moneyline, tab_loss_lab, tab_iq, tab_30d_learning, tab_learning_lab, tab_calibration, tab2, tab3, tab4, tab5, tab6 = st.tabs(["

BLOCK = r'''
# =============================================================================
# CHALLENGER_ML_CARD_STARTER_F5_V1_2026_09_02
# UI/data overlay only. Protected K core + canonical ML side remain untouched.
# =============================================================================
import html as _mcsf_html
import re as _mcsf_re

ML_CARD_STARTER_F5_VERSION = "CHALLENGER_ML_CARD_STARTER_F5_V1_2026_09_02"


def _mcsf_num(v, default=None):
    try:
        if v is None or v == "":
            return default
        x = float(str(v).replace("%", "").replace(",", "").strip())
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _mcsf_first(row, keys, default=None):
    if not isinstance(row, dict):
        return default
    for k in keys:
        if row.get(k) not in (None, ""):
            return row.get(k)
    norm = {"".join(c for c in str(k).lower() if c.isalnum()): k for k in row}
    for k in keys:
        nk = "".join(c for c in str(k).lower() if c.isalnum())
        real = norm.get(nk)
        if real is not None and row.get(real) not in (None, ""):
            return row.get(real)
    return default


def _mcsf_name(row):
    return str(_mcsf_first(row, ["Pitcher", "Player", "Name", "Starter", "Pitcher Name"], "") or "").strip()


def _mcsf_fmt(v, digits=2, suffix=""):
    x = _mcsf_num(v, None)
    return "—" if x is None else f"{x:.{digits}f}{suffix}"


def _mcsf_pitcher_profile(row):
    return {
        "name": _mcsf_name(row),
        "k_pct": _mcsf_num(_mcsf_first(row, ["Pitcher K%", "K%", "K %", "SO%", "Strikeout %", "Strikeout%"]), None),
        "era": _mcsf_num(_mcsf_first(row, ["ERA", "Pitcher ERA", "Season ERA"]), None),
        "whip": _mcsf_num(_mcsf_first(row, ["WHIP", "Pitcher WHIP", "Season WHIP"]), None),
        "k9": _mcsf_num(_mcsf_first(row, ["K/9", "K9", "Pitcher K/9", "SO/9"]), None),
        "ip": _mcsf_num(_mcsf_first(row, ["IP", "Projected IP", "Proj IP", "IP Projection", "Expected IP", "Challenger IP", "PO Final IP"]), None),
    }


def _mcsf_profile_text(p):
    if not isinstance(p, dict):
        return "K% — · ERA — · WHIP — · K/9 — · IP —"
    return (
        f"K% {_mcsf_fmt(p.get('k_pct'),1,'%')} · ERA {_mcsf_fmt(p.get('era'),2)} · "
        f"WHIP {_mcsf_fmt(p.get('whip'),2)} · K/9 {_mcsf_fmt(p.get('k9'),1)} · "
        f"Proj IP {_mcsf_fmt(p.get('ip'),2)}"
    )


def _mcsf_norm_name(x):
    return _mcsf_re.sub(r"[^a-z0-9]", "", str(x or "").lower())


def _mcsf_board_profiles(board):
    out = {}
    for rr in (board or []):
        if not isinstance(rr, dict):
            continue
        p = _mcsf_pitcher_profile(rr)
        key = _mcsf_norm_name(p.get("name"))
        if not key:
            continue
        old = out.get(key, {})
        # Prefer the row carrying more actual starter statistics.
        score = sum(p.get(k) is not None for k in ("k_pct","era","whip","k9","ip"))
        old_score = sum(old.get(k) is not None for k in ("k_pct","era","whip","k9","ip")) if old else -1
        if score >= old_score:
            out[key] = p
    return out


def _mcsf_matchup_teams(row):
    away = str(_mcsf_first(row, ["Away Team", "Away", "ML Away Team", "Away Abbr"], "") or "").strip().upper()
    home = str(_mcsf_first(row, ["Home Team", "Home", "ML Home Team", "Home Abbr"], "") or "").strip().upper()
    if away and home:
        return away, home
    m = str(_mcsf_first(row, ["Matchup", "Game", "ML Matchup"], "") or "").upper()
    mt = _mcsf_re.search(r"\b([A-Z]{2,3})\s*@\s*([A-Z]{2,3})\b", m)
    return (mt.group(1), mt.group(2)) if mt else (away, home)


def _mcsf_pick(row):
    raw = str(_mcsf_first(row, ["ML Card Best Play", "Canonical Winner", "ML Canonical Winner", "ML Pick", "Pick", "Winner"], "") or "").upper()
    raw = raw.replace(" MONEYLINE", "").replace(" ML", "").strip()
    return raw.split()[0] if raw else ""


def _mcsf_f5_fields(row):
    r = dict(row or {})
    away, home = _mcsf_matchup_teams(r)
    pick = _mcsf_pick(r)
    f5 = _mcsf_num(_mcsf_first(r, ["ML F5 Strength Score V3", "ML F5 Strength", "F5 Strength Score"]), None)
    if f5 is None:
        # Conservative fallback from starter/offense family edges; this is a display
        # projection only and does not alter full-game canonical ML.
        se = _mcsf_num(r.get("ML Starter Edge"), 0.0) or 0.0
        oe = _mcsf_num(r.get("ML Offense Vs Hand Edge"), 0.0) or 0.0
        ce = _mcsf_num(r.get("ML Contact Quality Edge"), 0.0) or 0.0
        f5 = max(1.0, min(99.0, 50.0 + 3.0*se + 1.6*oe + 0.8*ce))
    winner = pick
    prob = f5
    other = home if pick == away else away if pick == home else ""
    if f5 < 50.0 and other:
        winner, prob = other, 100.0 - f5
    if not winner:
        winner = "TOSS-UP"
        prob = max(f5, 100.0-f5)
    r["ML Card UI Version"] = ML_CARD_STARTER_F5_VERSION
    r["ML F5 Projected Winner V3"] = winner
    r["ML F5 Win Prob V3"] = round(prob, 1)
    r["ML F5 Pick Display V3"] = f"{winner} F5 · {prob:.1f}%"
    return r


# Add explicit F5 winner fields to the final ML dataframe.
try:
    if callable(globals().get("ml_build_board")) and not getattr(ml_build_board, "_mcsf_v1", False):
        _mcsf_old_ml_build = ml_build_board
        def _mcsf_ml_build(board):
            df = _mcsf_old_ml_build(board)
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return df
            rows = [_mcsf_f5_fields(rr.to_dict()) for _, rr in df.iterrows()]
            return pd.DataFrame(rows, index=df.index)
        _mcsf_ml_build._mcsf_v1 = True
        ml_build_board = _mcsf_ml_build
except Exception:
    pass


def _mcsf_inject_pitcher_stats(card_html, profiles):
    text = str(card_html)
    for p in profiles.values():
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        candidates = [name, _mcsf_html.escape(name)]
        for shown in candidates:
            if shown not in text:
                continue
            stats = _mcsf_html.escape(_mcsf_profile_text(p))
            addon = (
                f"{shown}<div style='font-size:10px;line-height:1.25;color:#9fb3cf;"
                f"margin-top:2px;font-weight:600'>{stats}</div>"
            )
            text = text.replace(shown, addon, 1)
            break
    return text


def _mcsf_inject_f5(card_html, f5_display):
    text = str(card_html)
    if not f5_display:
        return text
    f5 = _mcsf_html.escape(str(f5_display))
    badge = (
        "<span style='display:inline-block;margin-right:8px;padding:3px 7px;"
        "border:1px solid #3b82f6;border-radius:999px;color:#8ec5ff;"
        "font-size:10px;font-weight:800;letter-spacing:.06em'>"
        f"1–5: {f5}</span>"
    )
    for needle in ("CANONICAL BEST PLAY", "Canonical Best Play", "canonical best play"):
        if needle in text:
            return text.replace(needle, badge + needle, 1)
    return text


def _mcsf_render_fallback(df, profiles):
    try:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return
        with st.expander("⚾ First-5 + Starter Profiles", expanded=False):
            for _, rr in df.iterrows():
                r = rr.to_dict()
                matchup = str(_mcsf_first(r, ["Matchup", "ML Matchup", "Game"], "ML Game"))
                f5 = str(r.get("ML F5 Pick Display V3") or "F5 unavailable")
                st.markdown(f"**{matchup} — 1–5: {f5}**")
    except Exception:
        pass


# Wrap the current ML renderer. During its HTML output, inject starter profiles
# beside the existing pitcher names and F5 winner into the canonical card area.
try:
    if callable(globals().get("render_moneyline_edge_tab")) and not getattr(render_moneyline_edge_tab, "_mcsf_v1", False):
        _mcsf_old_render_ml = render_moneyline_edge_tab
        def _mcsf_render_ml(board, *args, **kwargs):
            profiles = _mcsf_board_profiles(board)
            try:
                mldf = ml_build_board(board) if callable(globals().get("ml_build_board")) else pd.DataFrame()
            except Exception:
                mldf = pd.DataFrame()
            f5_queue = []
            if isinstance(mldf, pd.DataFrame) and not mldf.empty:
                f5_queue = [str(x or "") for x in mldf.get("ML F5 Pick Display V3", pd.Series(dtype=object)).tolist()]

            original_markdown = st.markdown
            card_index = {"n": 0}
            def _patched_markdown(body, *margs, **mkwargs):
                b = body
                try:
                    if isinstance(body, str) and ("CANONICAL" in body.upper() and "BEST PLAY" in body.upper()):
                        b = _mcsf_inject_pitcher_stats(body, profiles)
                        i = card_index["n"]
                        f5 = f5_queue[i] if i < len(f5_queue) else ""
                        b = _mcsf_inject_f5(b, f5)
                        card_index["n"] = i + 1
                except Exception:
                    b = body
                return original_markdown(b, *margs, **mkwargs)
            try:
                st.markdown = _patched_markdown
                result = _mcsf_old_render_ml(board, *args, **kwargs)
            finally:
                st.markdown = original_markdown
            # If the card HTML signature changed, keep the information accessible.
            if card_index["n"] == 0:
                _mcsf_render_fallback(mldf, profiles)
            return result
        _mcsf_render_ml._mcsf_v1 = True
        render_moneyline_edge_tab = _mcsf_render_ml
except Exception:
    pass
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if TAB_ANCHOR not in text:
        raise RuntimeError("top-level tabs anchor not found")
    idx = text.index(TAB_ANCHOR)
    out = text[:idx] + BLOCK + "\n\n" + text[idx:]
    ast.parse(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    p = Path(args.app)
    original = p.read_text(encoding="utf-8")
    patched = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "runtime_probe.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)
    if patched != original:
        p.write_text(patched, encoding="utf-8")
    print(f"ML starter/F5 card V1 READY: {p}")


if __name__ == "__main__":
    main()
