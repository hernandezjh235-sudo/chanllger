#!/usr/bin/env python3
"""Add a read-only Challenger K recency/process regression + best-market shadow panel.

Safety contract:
- Does NOT modify Challenger K projection math, side selection, confidence, BF/IP,
  opponent K logic, probability/distribution logic, or official grading fields.
- Does NOT modify Pitching Outs / Pitcher FS projections.
- It only wraps the existing K renderer and computes a separate diagnostic DataFrame.
"""
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RECENCY_SHADOW_V1_2026_08_28"
ANCHORS = (
    "tab_kproj, tab_brain, tab_beta_outs",
    "tab_kproj, tab_brain",
)

BLOCK = r'''
# ===========================================================================
# CHALLENGER_RECENCY_SHADOW_V1_2026_08_28
# Read-only research layer. Challenger K production/control stays frozen.
# Purpose: detect results-vs-process recency traps (buy-low rebound / sell-high
# suppression) and compare which *available lined* pitcher market best expresses
# the same pregame pitcher thesis. This layer never changes an official pick.
# ===========================================================================
CHALLENGER_RECENCY_SHADOW_VERSION = "CHALLENGER_RECENCY_SHADOW_V1_2026_08_28"


def _chrs_num(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, str):
            s = v.strip().replace("%", "").replace(",", "")
            if not s or s.lower() in {"nan", "none", "—", "-"}:
                return default
            v = s
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _chrs_rate(v, default=None):
    x = _chrs_num(v, default)
    if x is None:
        return None
    if abs(x) > 1.5:
        x /= 100.0
    return float(x)


def _chrs_text(row, keys, default=""):
    row = row if isinstance(row, dict) else {}
    for k in keys:
        try:
            v = row.get(k)
            if v not in (None, "", "—", "-", "nan", "NaN"):
                return str(v)
        except Exception:
            pass
    return default


def _chrs_first_num(row, keys, default=None, rate=False):
    row = row if isinstance(row, dict) else {}
    for k in keys:
        if k not in row:
            continue
        x = _chrs_rate(row.get(k), None) if rate else _chrs_num(row.get(k), None)
        if x is not None:
            return x
    return default


def _chrs_series_mean(v):
    """Parse a scalar/list/simple comma list. Never fetches postgame data."""
    if isinstance(v, (list, tuple, np.ndarray, pd.Series)):
        z = [_chrs_num(x, None) for x in list(v)]
        z = [x for x in z if x is not None]
        return float(np.mean(z)) if z else None
    if isinstance(v, str) and any(ch in v for ch in "[],|"):
        s = v.strip().strip("[]()")
        for sep in ("|", ","):
            if sep in s:
                z = [_chrs_num(x.strip(), None) for x in s.split(sep)]
                z = [x for x in z if x is not None]
                if z:
                    return float(np.mean(z))
    return _chrs_num(v, None)


def _chrs_first_mean(row, keys, default=None):
    row = row if isinstance(row, dict) else {}
    for k in keys:
        if k in row:
            x = _chrs_series_mean(row.get(k))
            if x is not None:
                return x
    return default


def _chrs_side(row):
    s = _chrs_text(row, [
        "Line-Aware Smart Decision", "Decision", "Final Decision",
        "Canonical Decision", "Pick", "Side"
    ], "").upper()
    if "UNDER" in s:
        return "UNDER"
    if "OVER" in s:
        return "OVER"
    return "PASS"


def _chrs_name_key(v):
    try:
        if "_tpl_norm_name" in globals():
            return _tpl_norm_name(v)
    except Exception:
        pass
    return " ".join(str(v or "").lower().replace(".", " ").replace("-", " ").split())


def _chrs_process_profile(r):
    """Pregame process trend only. Positive = K process improving; negative = fading."""
    votes = []
    reasons = []

    def trend_vote(label, short, long, threshold):
        if short is None or long is None:
            return
        d = short - long
        if d >= threshold:
            votes.append(1.0); reasons.append(f"{label} +{d*100:.1f}pp")
        elif d <= -threshold:
            votes.append(-1.0); reasons.append(f"{label} {d*100:.1f}pp")

    kbf3 = _chrs_first_num(r, ["UB L3 Pooled K/BF", "L3 K/BF", "Recent L3 K/BF"], None, True)
    kbf10 = _chrs_first_num(r, ["UB L10 Pooled K/BF", "L10 K/BF", "Pitcher K/BF", "Model K/BF", "K/BF"], None, True)
    w3 = _chrs_first_num(r, ["UB Recent Whiff L3", "L3_Whiff_pct", "L3 Whiff%", "Recent Whiff%"], None, True)
    w10 = _chrs_first_num(r, ["UB Recent Whiff L10", "L10_Whiff_pct", "L10 Whiff%", "APP100 Whiff%", "Official Savant Whiff%", "Statcast Whiff%"], None, True)
    c3 = _chrs_first_num(r, ["UB Recent CSW L3", "L3_CSW_pct", "L3 CSW%", "Recent CSW%"], None, True)
    c10 = _chrs_first_num(r, ["UB Recent CSW L10", "L10_CSW_pct", "L10 CSW%", "APP100 CSW%", "Official Savant CSW%", "Statcast CSW%"], None, True)
    s3 = _chrs_first_num(r, ["UB Recent SwStr L3", "L3_swinging_strike_pct", "L3 SwStr%"], None, True)
    s10 = _chrs_first_num(r, ["UB Recent SwStr L10", "L10_swinging_strike_pct", "L10 SwStr%"], None, True)

    trend_vote("K/BF", kbf3, kbf10, 0.015)
    trend_vote("Whiff", w3, w10, 0.015)
    trend_vote("CSW", c3, c10, 0.012)
    trend_vote("SwStr", s3, s10, 0.010)

    velo_delta = _chrs_first_num(r, ["Velocity Delta", "velocity_delta", "velocity_trend_mph"], None)
    if velo_delta is None:
        v3 = _chrs_first_num(r, ["L3_fastball_velocity"], None)
        v10 = _chrs_first_num(r, ["L10_fastball_velocity"], None)
        if v3 is not None and v10 is not None:
            velo_delta = v3 - v10
    if velo_delta is not None:
        if velo_delta >= 0.5:
            votes.append(1.0); reasons.append(f"velo +{velo_delta:.1f} mph")
        elif velo_delta <= -0.5:
            votes.append(-1.0); reasons.append(f"velo {velo_delta:.1f} mph")

    whiff_now = w3 if w3 is not None else w10
    csw_now = c3 if c3 is not None else c10
    if whiff_now is not None:
        if whiff_now >= 0.285:
            votes.append(0.5); reasons.append(f"Whiff healthy {whiff_now*100:.1f}%")
        elif whiff_now <= 0.205:
            votes.append(-0.5); reasons.append(f"Whiff weak {whiff_now*100:.1f}%")
    if csw_now is not None:
        if csw_now >= 0.295:
            votes.append(0.5); reasons.append(f"CSW healthy {csw_now*100:.1f}%")
        elif csw_now <= 0.245:
            votes.append(-0.5); reasons.append(f"CSW weak {csw_now*100:.1f}%")

    score = float(sum(votes)) if votes else 0.0
    return {
        "score": score,
        "evidence": len(votes),
        "reasons": reasons,
        "kbf3": kbf3, "kbf10": kbf10,
        "whiff3": w3, "whiff10": w10,
        "csw3": c3, "csw10": c10,
        "swstr3": s3, "swstr10": s10,
        "velo_delta": velo_delta,
    }


def _chrs_workload_profile(r):
    ip5 = _chrs_first_num(r, ["APP97 Live L5 IP Avg", "Live L5 IP Avg", "Recent IP L5", "L5 IP Avg", "UB Live L5 IP"], None)
    bf5 = _chrs_first_num(r, ["APP97 Live L5 BF Median", "APP100 L5 BF", "Live L5 BF Median", "L5 BF Median", "Recent BF L5", "UB Live L5 BF"], None)
    pc5 = _chrs_first_num(r, ["APP97 Live L5 Pitch Median", "APP100 L5 Pitch Median", "Live L5 Pitch Median", "Pitch Count Avg L5", "L5 Pitch Median", "UB Live L5 Pitch"], None)
    pc3 = _chrs_first_num(r, ["Pitch Count Avg L3", "L3 Pitch Count", "UB L3 Pitch Count"], None)
    pc10 = _chrs_first_num(r, ["Pitch Count Avg L10", "UB L10 Pitch Count"], None)
    bf_proj = _chrs_first_num(r, ["APP100 Projected BF", "APP97 Reconciled Expected BF", "Exp BF", "Expected BF"], None)
    ip_proj = _chrs_first_num(r, ["IP Floor", "Projected IP", "Proj IP", "Expected IP"], None)
    trend = 0.0
    notes = []
    if pc3 is not None and pc10 is not None:
        d = pc3 - pc10
        if d >= 5:
            trend += 1.0; notes.append(f"PC L3 +{d:.0f}")
        elif d <= -5:
            trend -= 1.0; notes.append(f"PC L3 {d:.0f}")
    if ip5 is not None and ip_proj is not None:
        d = ip_proj - ip5
        if d >= 0.45:
            trend += 0.5; notes.append(f"projected IP +{d:.1f} vs L5")
        elif d <= -0.45:
            trend -= 0.5; notes.append(f"projected IP {d:.1f} vs L5")
    return {"ip5": ip5, "bf5": bf5, "pc5": pc5, "bf_proj": bf_proj, "ip_proj": ip_proj,
            "trend": trend, "notes": notes}


def _chrs_shadow_row(r):
    r = r if isinstance(r, dict) else {}
    name = _chrs_text(r, ["Pitcher", "pitcher", "Player"], "")
    matchup = _chrs_text(r, ["Matchup", "matchup"], "")
    line = _chrs_first_num(r, ["UD/Line", "Underdog Line", "Line", "Current Line"], None)
    proj = _chrs_first_num(r, [
        "APP97 True K Projection", "Line-Aware Smart Final K Projection",
        "K PROJ", "Official K PROJ", "Final K Projection", "Proj SO", "K Projection"
    ], None)
    side = _chrs_side(r)

    l3 = _chrs_first_mean(r, ["Atlas L3 Avg K", "Trend L3 Avg 2.2", "L3 K Avg", "Recent L3 Ks"], None)
    l5 = _chrs_first_mean(r, ["L5 K Avg", "Atlas L5 Avg K", "Trend L5 Avg 2.2", "Recent L5 Ks"], None)
    l10 = _chrs_first_mean(r, ["Atlas L10 Avg K", "APP97 Live L10 K Avg", "L10 K Avg", "Trend L10 Avg"], None)
    if l5 is None:
        rkbf = _chrs_first_num(r, ["UB L5 Pooled K/BF", "Recent K/BF", "L5 K/BF"], None, True)
        rbf = _chrs_first_num(r, ["APP97 Live L5 BF Median", "APP100 L5 BF", "L5 BF Median", "Recent BF L5", "UB Live L5 BF"], None)
        if rkbf is not None and rbf is not None:
            l5 = rkbf * rbf

    process = _chrs_process_profile(r)
    work = _chrs_workload_profile(r)
    result_gap = (l5 - proj) if l5 is not None and proj is not None else None
    line_gap = (l5 - line) if l5 is not None and line is not None else None
    pscore = process["score"]
    wscore = work["trend"]

    state = "INSUFFICIENT RECENCY DATA"
    if result_gap is not None:
        if result_gap <= -1.0:
            if pscore >= 1.0:
                state = "STRONG REBOUND" if result_gap <= -1.5 and pscore >= 2.0 else "REBOUND WATCH"
            elif pscore <= -1.0:
                state = "TRUE DOWNTREND RISK"
            else:
                state = "RESULT SLUMP / PROCESS MIXED"
        elif result_gap >= 1.0:
            if pscore <= -1.0:
                state = "STRONG SUPPRESSION" if result_gap >= 1.5 and pscore <= -2.0 else "SUPPRESSION WATCH"
            elif pscore >= 1.0:
                state = "TRUE SURGE SUPPORT"
            else:
                state = "RESULT SURGE / PROCESS MIXED"
        else:
            state = "NEUTRAL"

    opposed = (result_gap is not None and ((result_gap < 0 and pscore > 0) or (result_gap > 0 and pscore < 0)))
    trap_score = 0.0
    if result_gap is not None:
        trap_score = min(45.0, abs(result_gap) * 18.0)
        trap_score += min(30.0, abs(pscore) * 8.0)
        if opposed:
            trap_score += 18.0
        if (result_gap < 0 and wscore > 0) or (result_gap > 0 and wscore < 0):
            trap_score += 7.0
    trap_score = round(float(max(0.0, min(100.0, trap_score))), 1)

    market_read = "NO RECENCY EDGE"
    if line_gap is not None and proj is not None and line is not None:
        if line_gap <= -1.0 and proj > line and pscore >= 1.0:
            market_read = "BUY-LOW K OVER CANDIDATE"
        elif line_gap >= 1.0 and proj < line and pscore <= -1.0:
            market_read = "SELL-HIGH K UNDER CANDIDATE"
        elif side == "OVER" and result_gap is not None and result_gap < -1.0 and pscore >= 1.0:
            market_read = "RECENT RESULTS FADE OVER"
        elif side == "UNDER" and result_gap is not None and result_gap > 1.0 and pscore <= -1.0:
            market_read = "RECENT RESULTS FADE UNDER"

    reasons = []
    if result_gap is not None:
        reasons.append(f"L5-vs-model {result_gap:+.2f} K")
    if process["reasons"]:
        reasons.extend(process["reasons"][:4])
    if work["notes"]:
        reasons.extend(work["notes"][:2])
    if not reasons:
        reasons.append("insufficient pregame result/process split")

    return {
        "Pitcher": name,
        "Matchup": matchup,
        "K Line": line,
        "Challenger K Proj": None if proj is None else round(proj, 2),
        "Challenger Side": side,
        "L3 K Avg": None if l3 is None else round(l3, 2),
        "L5 K Avg": None if l5 is None else round(l5, 2),
        "L10 K Avg": None if l10 is None else round(l10, 2),
        "L5 vs Model": None if result_gap is None else round(result_gap, 2),
        "Process Score": round(pscore, 1),
        "Workload Trend": round(wscore, 1),
        "Recency State": state,
        "Recency Trap Score": trap_score,
        "K Market Read": market_read,
        "L5 IP": None if work["ip5"] is None else round(work["ip5"], 2),
        "L5 BF": None if work["bf5"] is None else round(work["bf5"], 1),
        "L5 Pitches": None if work["pc5"] is None else round(work["pc5"], 0),
        "Shadow Reason": " | ".join(reasons),
        "Shadow Version": CHALLENGER_RECENCY_SHADOW_VERSION,
    }


def _chrs_market_indexes(board):
    """Read other already-existing model outputs without modifying them."""
    po_idx, fs_idx = {}, {}
    try:
        fn = globals().get("_beta_projection_rows")
        po = fn(board, "OUTS") if callable(fn) else pd.DataFrame()
        if isinstance(po, pd.DataFrame) and not po.empty:
            for _, rr in po.iterrows():
                x = rr.to_dict(); k = _chrs_name_key(_chrs_text(x, ["Pitcher", "Player"], ""))
                if k: po_idx[k] = x
    except Exception:
        pass
    try:
        fn = globals().get("build_pitcher_fs_board")
        fs = fn(board) if callable(fn) else pd.DataFrame()
        if isinstance(fs, pd.DataFrame) and not fs.empty:
            for _, rr in fs.iterrows():
                x = rr.to_dict(); k = _chrs_name_key(_chrs_text(x, ["Pitcher", "Player"], ""))
                if k: fs_idx[k] = x
    except Exception:
        pass
    return po_idx, fs_idx


def _chrs_candidate(label, proj, line, side="", prob=None, scale=1.0, note=""):
    if proj is None or line is None:
        return None
    raw = proj - line
    side2 = str(side or "").upper()
    if side2 not in {"OVER", "UNDER"}:
        side2 = "OVER" if raw > 0 else "UNDER" if raw < 0 else "PASS"
    edge = raw if side2 == "OVER" else -raw if side2 == "UNDER" else 0.0
    if edge <= 0:
        return None
    p = _chrs_num(prob, None)
    if p is not None and p <= 1.0:
        p *= 100.0
    strength = (p - 50.0) if p is not None else (edge / max(scale, 0.1)) * 10.0
    return {"market": label, "side": side2, "line": line, "proj": proj, "edge": edge,
            "prob": p, "strength": float(strength), "note": note}


def _chrs_add_best_market(shadow, kdf, board):
    if not isinstance(shadow, pd.DataFrame) or shadow.empty:
        return shadow
    po_idx, fs_idx = _chrs_market_indexes(board)
    k_idx = {}
    try:
        for _, rr in kdf.iterrows():
            x = rr.to_dict(); k = _chrs_name_key(_chrs_text(x, ["Pitcher", "Player"], ""))
            if k: k_idx[k] = x
    except Exception:
        pass

    bests, details = [], []
    for _, sr in shadow.iterrows():
        key = _chrs_name_key(sr.get("Pitcher"))
        kr = k_idx.get(key, {})
        candidates = []
        kp = _chrs_num(sr.get("Challenger K Proj"), None); kl = _chrs_num(sr.get("K Line"), None)
        kprob = _chrs_first_num(kr, ["K Sim Current Side Prob %", "Selected Side Probability %", "Win Probability %", "Confidence %"], None)
        kc = _chrs_candidate("K", kp, kl, sr.get("Challenger Side"), kprob, 1.35, sr.get("K Market Read", ""))
        if kc: candidates.append(kc)

        pr = po_idx.get(key, {})
        pp = _chrs_first_num(pr, ["PO Final Projection", "PO Active Projection", "Beta Projection", "Projection"], None)
        pl = _chrs_first_num(pr, ["UD Line", "UD/Line", "Line"], None)
        ps = _chrs_text(pr, ["PO Final Side", "PO Active Lean", "Beta Pick", "Pick", "Side"], "")
        pprob = _chrs_first_num(pr, ["PO Final Probability %", "PO Active Hit %", "Beta Hit %", "Hit %"], None)
        pc = _chrs_candidate("PITCHING OUTS", pp, pl, ps, pprob, 2.25, "existing PO model")
        if pc: candidates.append(pc)

        fr = fs_idx.get(key, {})
        fp = _chrs_first_num(fr, ["FS Projection", "Pitcher FS Projection", "Projection"], None)
        fl = _chrs_first_num(fr, ["Pitcher FS Line", "FS Line", "UD Line", "UD/Line", "Line"], None)
        fs = _chrs_text(fr, ["FS Side", "Pick", "Side", "Decision"], "")
        fprob = _chrs_first_num(fr, ["Confidence %", "Win Probability %", "Hit %"], None)
        fc = _chrs_candidate("PITCHER FS", fp, fl, fs, fprob, 7.0, "only when a real FS line exists")
        if fc: candidates.append(fc)

        read = str(sr.get("K Market Read") or "")
        for c in candidates:
            if c["market"] == "K" and (("OVER" in read and c["side"] == "OVER") or ("UNDER" in read and c["side"] == "UNDER")):
                c["strength"] += min(6.0, _chrs_num(sr.get("Recency Trap Score"), 0.0) / 16.0)
        if candidates:
            b = max(candidates, key=lambda x: x["strength"])
            bests.append(f"{b['market']} {b['side']} {b['line']:.1f}")
            probtxt = f" · {b['prob']:.0f}%" if b.get("prob") is not None else ""
            details.append(f"proj {b['proj']:.2f} · edge {b['edge']:.2f}{probtxt}")
        else:
            bests.append("NO LINED MARKET EDGE")
            details.append("PFS is excluded when no real line is available")
    out = shadow.copy()
    out["Best Market Candidate"] = bests
    out["Best Market Detail"] = details
    return out


def _chrs_build_shadow(board):
    fn = globals().get("build_kproj_table")
    df = fn(board) if callable(fn) else pd.DataFrame()
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(), df
    try:
        dedupe = globals().get("_owp_one_final_row_per_pitcher")
        if callable(dedupe):
            df = dedupe(df.copy())
    except Exception:
        pass
    rows = []
    for _, rr in df.iterrows():
        try:
            rows.append(_chrs_shadow_row(rr.to_dict()))
        except Exception:
            continue
    out = pd.DataFrame(rows)
    if not out.empty:
        out = _chrs_add_best_market(out, df, board)
        out = out.sort_values(["Recency Trap Score", "Pitcher"], ascending=[False, True], kind="stable")
    return out, df


def _chrs_render_shadow(board):
    try:
        shadow, _ = _chrs_build_shadow(board)
        if not isinstance(shadow, pd.DataFrame) or shadow.empty:
            return
        try:
            st.session_state["challenger_recency_shadow_v1"] = shadow.copy()
        except Exception:
            pass
        with st.expander("🧠 RECENCY TRAP / BEST PROP — SHADOW", expanded=False):
            st.caption(
                "Research only. Challenger's official K projection, side, probability, BF/IP and grading are unchanged. "
                "The detector looks for recent box-score results moving opposite underlying K process/workload. "
                "Best Market only compares props that already have a real line; it does not invent a Pitcher FS line."
            )
            top = shadow[shadow["Recency Trap Score"].fillna(0) >= 45].copy()
            if not top.empty:
                st.markdown("**Highest recency/process disagreements**")
                show = [c for c in [
                    "Pitcher", "Matchup", "K Line", "Challenger K Proj", "Challenger Side",
                    "L5 K Avg", "L5 vs Model", "Process Score", "Workload Trend",
                    "Recency State", "Recency Trap Score", "K Market Read",
                    "Best Market Candidate", "Best Market Detail", "Shadow Reason"
                ] if c in top.columns]
                st.dataframe(top[show], use_container_width=True, hide_index=True)
            else:
                st.info("No strong recency/process disagreement is present on this slate.")
            with st.expander("Full shadow audit", expanded=False):
                st.dataframe(shadow, use_container_width=True, hide_index=True)
            try:
                csv = shadow.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download Recency Shadow CSV", csv,
                    file_name=f"challenger_recency_shadow_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv", key="challenger_recency_shadow_v1_download"
                )
            except Exception:
                pass
    except Exception as e:
        st.info(f"Recency Trap shadow unavailable: {e}")


_CH_RECENCY_PREV_RENDER_K = render_kproj_tab


def _impl_render_kproj_tab_ch_recency_shadow_v1(board):
    if callable(_CH_RECENCY_PREV_RENDER_K):
        _CH_RECENCY_PREV_RENDER_K(board)
    _chrs_render_shadow(board)


# Public renderer rebind only. No K builder/projection function is rebound.
render_kproj_tab = _impl_render_kproj_tab_ch_recency_shadow_v1
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    anchor = next((a for a in ANCHORS if a in text), None)
    if not anchor:
        raise RuntimeError("Could not find the top-level K tab anchor; app left unchanged")
    i = text.index(anchor)
    if "render_kproj_tab =" not in text[:i]:
        raise RuntimeError("render_kproj_tab binding not found before tabs; app left unchanged")
    return text[:i] + BLOCK + "\n\n\n" + text[i:]


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
        try: tmp.unlink()
        except Exception: pass
    path.write_text(updated, encoding="utf-8")
    print(f"{MARKER}: applied safely to {path}")


if __name__ == "__main__":
    main()
