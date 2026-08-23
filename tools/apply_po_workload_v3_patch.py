#!/usr/bin/env python3
"""Surgical Pitching Outs Workload V3 challenger patch.

The existing Pitching Outs Workload V2 stays production. V3 is an additive
shadow challenger that rebuilds expected workload from recent IP/BF/pitch-count
families BEFORE applying hook/damage/matchup risk. It also adds data-completeness
uncertainty, hard-vs-soft restriction diagnostics, calibrated probability caps,
a parallel projection-error audit, and a cleaner PO card renderer.

It does not change K projections, HRR, Batter Fantasy, Moneyline, existing PO
grading history, or Railway persistence semantics. The legacy PO grader still
runs unchanged; V3 writes a separate additive audit file.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_PO_WORKLOAD_V3_2026_08_23"
BETA_BIND_PREFIX = "_beta_projection_rows = globals().get('_impl_beta_projection_rows_07'"
RENDER_BIND_PREFIX = "render_beta_pitching_outs_tab = globals().get('_impl_render_beta_pitching_outs_tab_06'"

BLOCK = r'''
# CHALLENGER_PO_WORKLOAD_V3_2026_08_23
# Pitching-Outs-only shadow challenger. Workload V2 remains the production selector.
PO_WORKLOAD_V3_VERSION = "PO_WORKLOAD_V3_SHADOW_2026_08_23"
PO_WORKLOAD_V3_CONFIG = {
    "normal_starter_floor_ip": 4.55,
    "strong_recent_floor_min_ip": 4.75,
    "strong_recent_floor_max_ip": 5.20,
    "low_data_prob_cap": 74.0,
    "medium_data_prob_cap": 82.0,
    "good_data_prob_cap": 90.0,
    "absolute_prob_cap": 95.0,
    "boundary_outs": 1.0,
    "severe_miss_outs": 5.0,
    "extreme_miss_outs": 8.0,
}
PO_WORKLOAD_V3_AUDIT_FILE = os.path.join(
    str(globals().get("STORAGE_DIR", "learning_data")),
    "pitching_outs_projection_audit_v3.csv",
)


def _po_v3_num(row, keys, default=np.nan):
    for key in keys:
        try:
            value = row.get(key) if isinstance(row, dict) else None
        except Exception:
            value = None
        if value in (None, "", "—", "-", "nan", "NaN"):
            continue
        try:
            out = float(str(value).replace("%", "").replace(",", "").strip())
            if np.isfinite(out):
                return out
        except Exception:
            continue
    return default


def _po_v3_text(row, keys, default=""):
    for key in keys:
        try:
            value = row.get(key) if isinstance(row, dict) else None
        except Exception:
            value = None
        if value not in (None, "", "—", "-", "nan", "NaN"):
            return str(value)
    return default


def _po_v3_recent_ip(row):
    direct = [
        ("APP97 Live L5 IP Avg", "APP97_L5_IP"),
        ("L5 IP Avg", "L5_IP"),
        ("Recent IP L5", "RECENT_IP_L5"),
        ("Recent Starts IP Avg", "RECENT_START_IP"),
        ("recent_ip_l5", "HISTORY_RECENT_IP_L5"),
        ("recent_ip", "HISTORY_RECENT_IP"),
        ("AVG IP", "AVG_IP"),
    ]
    for key, source in direct:
        v = _po_v3_num(row, [key], np.nan)
        if np.isfinite(v) and 0.1 <= v <= 9.0:
            return float(v), source
    for key, source in [
        ("Recent Outs L5", "RECENT_OUTS_L5"),
        ("Recent Outs Median", "RECENT_OUTS_MEDIAN"),
        ("L5 Outs Avg", "L5_OUTS"),
    ]:
        v = _po_v3_num(row, [key], np.nan)
        if np.isfinite(v) and 1 <= v <= 27:
            return float(v) / 3.0, source
    return np.nan, "MISSING"


def _po_v3_recent_bf(row):
    for keys, source in [
        (["APP97 Live L5 BF Median"], "APP97_L5_BF"),
        (["APP97 Live L10 BF Median"], "APP97_L10_BF"),
        (["Recent BF L5", "L5 BF Avg", "BF Avg L5"], "RECENT_L5_BF"),
        (["Recent BF", "Recent BF Avg"], "RECENT_BF"),
    ]:
        v = _po_v3_num(row, keys, np.nan)
        if np.isfinite(v) and 3 <= v <= 40:
            return float(v), source
    return np.nan, "MISSING"


def _po_v3_pc_inputs(row):
    families = {
        "L3": _po_v3_num(row, ["Pitch Count Avg L3", "PO Fill Pitch Count L3", "pitch_count_avg_l3"], np.nan),
        "L5": _po_v3_num(row, ["Pitch Count Avg L5", "PO Fill Pitch Count L5", "pitch_count_avg_l5"], np.nan),
        "L10": _po_v3_num(row, ["Pitch Count Avg L10", "PO Fill Pitch Count L10"], np.nan),
        "SEASON": _po_v3_num(row, ["Season Avg Pitch Count", "PO Fill Season Pitch Count Avg"], np.nan),
        "LAST": _po_v3_num(row, ["Last Start Pitch Count", "PO Fill Last Pitch Count"], np.nan),
        "MAX": _po_v3_num(row, ["Max Pitch Count L10", "PO Fill Max Pitch Count L10"], np.nan),
    }
    return {k: v for k, v in families.items() if np.isfinite(v) and 20 <= v <= 130}


def _po_v3_pc_baseline(row):
    vals = _po_v3_pc_inputs(row)
    weights = {"L3": 1.15, "L5": 1.25, "L10": 1.00, "SEASON": 0.85, "LAST": 0.55, "MAX": 0.25}
    if not vals:
        return np.nan, "MISSING"
    num = sum(float(v) * weights[k] for k, v in vals.items())
    den = sum(weights[k] for k in vals)
    return float(num / den), "+".join(vals.keys())


def _po_v3_capacity_ip(row, pc):
    if not np.isfinite(pc):
        return np.nan, "MISSING"
    pbf = _po_v3_num(row, ["Pitch Efficiency P/BF", "PO Fill P/BF", "P/BF"], np.nan)
    if np.isfinite(pbf) and pbf > 0:
        return float(np.clip((pc / max(pbf, 3.15)) / 4.25, 2.0, 8.0)), "PC/PBF"
    ppi = _po_v3_num(row, ["Pitch Efficiency P/IP", "PO Fill P/IP", "P/IP"], np.nan)
    if np.isfinite(ppi) and ppi > 0:
        return float(np.clip(pc / max(ppi, 12.5), 2.0, 8.0)), "PC/PIP"
    return float(np.clip(pc / 16.8, 2.0, 8.0)), "PC/DEFAULT_EFF"


def _po_v3_restriction(row, recent_ip, recent_bf):
    role = _po_workload_v2_role_context(row) if "_po_workload_v2_role_context" in globals() else {"label": "STARTER", "explicit_short_role": False, "ip_cap": None}
    blob = ""
    try:
        blob = _po_workload_v2_blob(row) if "_po_workload_v2_blob" in globals() else " ".join(str(v) for v in row.values()).upper()
    except Exception:
        blob = ""
    explicit_terms = [
        "RETURN FROM IL", "INJURY_RETURN", "REHAB", "BUILD UP", "RAMP",
        "PITCH LIMIT", "PITCH_LIMIT", "OPENER", "OPENING PITCHER", "BULK",
        "TANDEM", "PIGGYBACK", "NON_TRADITIONAL_ROLE", "ROLE_CHANGE",
    ]
    reasons = [x for x in explicit_terms if x in blob]
    hard = bool(role.get("explicit_short_role")) or bool(reasons)
    confidence = 95.0 if hard else 0.0
    rtype = str(role.get("label") or "STARTER") if hard else "NONE"

    pcs = _po_v3_pc_inputs(row)
    l5 = pcs.get("L5")
    last = pcs.get("LAST")
    corroborated_short = (
        l5 is not None and last is not None and l5 <= 78 and last <= 70
        and ((np.isfinite(recent_ip) and recent_ip <= 4.50) or (np.isfinite(recent_bf) and recent_bf <= 19.0))
    )
    if not hard and corroborated_short:
        hard = True
        confidence = 84.0
        rtype = "VERIFIED_SHORT_WORKLOAD"
        reasons.append("SHORT_PC+RECENT_IP/BF")
    elif not hard and l5 is not None and last is not None and l5 <= 78 and last <= 70:
        # Pitch count alone is evidence, but not enough to become a hard restriction.
        confidence = 55.0
        rtype = "SHORT_PC_WATCH"
        reasons.append("SHORT_PC_UNCORROBORATED")
    return hard, rtype, confidence, reasons, role


def _po_v3_completeness(row, recent_ip, recent_bf, pc, role):
    score = 0.0
    missing = []
    if np.isfinite(recent_ip): score += 25.0
    else: missing.append("recent IP")
    if np.isfinite(recent_bf): score += 20.0
    else: missing.append("recent BF")
    if np.isfinite(pc): score += 25.0
    else: missing.append("recent pitch count")
    ppi = _po_v3_num(row, ["Pitch Efficiency P/IP", "PO Fill P/IP", "P/IP"], np.nan)
    pbf = _po_v3_num(row, ["Pitch Efficiency P/BF", "PO Fill P/BF", "P/BF"], np.nan)
    if np.isfinite(ppi) or np.isfinite(pbf): score += 10.0
    else: missing.append("pitch efficiency")
    if role and str(role.get("label") or "").strip(): score += 10.0
    else: missing.append("role")
    hook = _po_v3_num(row, ["Recent Hook Rate", "PO Fill Hook Rate"], np.nan)
    deep = _po_v3_num(row, ["Deep Start Rate", "PO Fill Deep Start Rate"], np.nan)
    if np.isfinite(hook) or np.isfinite(deep): score += 10.0
    else: missing.append("manager leash")
    label = "HIGH" if score >= 80 else "GOOD" if score >= 65 else "LIMITED" if score >= 45 else "LOW"
    return float(score), label, missing


def _po_v3_candidate_probability(row, projection, line, side, completeness, hard_conf):
    if not np.isfinite(projection) or not np.isfinite(line) or side not in {"OVER", "UNDER"}:
        return np.nan, np.nan, np.nan, ""
    vol = _po_v3_num(row, ["IP Volatility Score"], 50.0)
    vol = 50.0 if not np.isfinite(vol) else float(vol)
    sd = 2.25 + max(0.0, min(80.0, vol)) / 34.0
    if completeness < 45: sd += 0.90
    elif completeness < 65: sd += 0.50
    elif completeness < 80: sd += 0.20
    hook = _po_v3_num(row, ["Recent Hook Rate", "PO Fill Hook Rate"], np.nan)
    if np.isfinite(hook) and hook >= 50: sd += 0.35
    damage_score = _po_v3_num(row, ["Damage Risk Score", "PO Fill Damage Score", "run_damage_score"], np.nan)
    damage_label = _po_v3_text(row, ["Damage Risk Label", "PO Fill Damage Label", "run_damage_risk_level"], "").upper()
    if "HIGH" in damage_label or (np.isfinite(damage_score) and damage_score >= 65): sd += 0.35
    elif "MED" in damage_label or (np.isfinite(damage_score) and damage_score >= 45): sd += 0.15
    sd = float(np.clip(sd, 2.0, 6.2))
    try:
        rng = _sim_stable_rng("PO_V3", _po_v3_text(row, ["Pitcher"], ""), round(float(projection), 3), round(sd, 3), PO_WORKLOAD_V3_VERSION)
    except Exception:
        rng = np.random.default_rng(20260823)
    samples = np.rint(rng.normal(float(projection), sd, 12000)).astype(int)
    samples = np.clip(samples, 0, 27)
    over = float(np.mean(samples > float(line)) * 100.0)
    under = float(np.mean(samples < float(line)) * 100.0)
    p = over if side == "OVER" else under
    cap = float(PO_WORKLOAD_V3_CONFIG["absolute_prob_cap"])
    if hard_conf < 85:
        if completeness < 45: cap = min(cap, PO_WORKLOAD_V3_CONFIG["low_data_prob_cap"])
        elif completeness < 65: cap = min(cap, PO_WORKLOAD_V3_CONFIG["medium_data_prob_cap"])
        elif completeness < 80: cap = min(cap, PO_WORKLOAD_V3_CONFIG["good_data_prob_cap"])
    p = min(float(p), float(cap))
    return round(p, 1), round(over, 1), round(under, 1), round(sd, 2)


def _po_v3_profile(row):
    row = dict(row or {})
    line = _po_v3_num(row, ["UD Line", "Line", "Outs Line"], np.nan)
    beta_ip = _po_v3_num(row, ["Beta IP"], np.nan)
    beta_proj = _po_v3_num(row, ["Beta Projection", "Projection", "Projected Outs"], np.nan)
    if not np.isfinite(beta_ip) and np.isfinite(beta_proj): beta_ip = beta_proj / 3.0
    original_ip = _po_v3_num(row, ["Original IP"], np.nan)
    recent_ip, recent_ip_source = _po_v3_recent_ip(row)
    recent_bf, recent_bf_source = _po_v3_recent_bf(row)
    pc, pc_source = _po_v3_pc_baseline(row)
    capacity_ip, capacity_source = _po_v3_capacity_ip(row, pc)
    hard, restriction_type, restriction_conf, hard_reasons, role = _po_v3_restriction(row, recent_ip, recent_bf)
    completeness, confidence_label, missing = _po_v3_completeness(row, recent_ip, recent_bf, pc, role)

    components = []
    if np.isfinite(recent_ip): components.append((recent_ip, 0.40, "recent IP"))
    if np.isfinite(recent_bf): components.append((recent_bf / 4.25, 0.22, "recent BF"))
    if np.isfinite(capacity_ip): components.append((capacity_ip, 0.18, "pitch capacity"))
    if np.isfinite(original_ip): components.append((original_ip, 0.12, "original IP"))
    if np.isfinite(beta_ip): components.append((beta_ip, 0.08, "legacy Beta IP"))
    if not components:
        return {
            "PO V3 Version": PO_WORKLOAD_V3_VERSION,
            "PO V3 Status": "UNAVAILABLE",
            "PO V3 Workload Reason": "No workload inputs available",
            "PO V3 Data Completeness %": round(completeness, 1),
            "PO V3 Workload Confidence": confidence_label,
            "PO V3 Missing Inputs": ", ".join(missing),
        }
    wsum = sum(w for _, w, _ in components)
    pre_ip = sum(v * w for v, w, _ in components) / wsum
    base_ip = float(pre_ip)

    soft_score, soft_reasons = _po_workload_v2_soft_risk(row) if "_po_workload_v2_soft_risk" in globals() else (0.0, [])
    soft_penalty = min(max(0.0, float(soft_score)) * 0.26, 0.30)
    support_boost = 0.0
    deep = _po_v3_num(row, ["Deep Start Rate", "PO Fill Deep Start Rate"], np.nan)
    if np.isfinite(deep) and deep >= 55 and (not np.isfinite(pc) or pc >= 84): support_boost += 0.12
    if np.isfinite(pc) and pc >= 92: support_boost += 0.08

    final_ip = base_ip - soft_penalty + support_boost
    reason_bits = ["baseline=" + "+".join(name for _, _, name in components)]
    if hard:
        reason_bits.append("HARD=" + restriction_type)
        role_cap = role.get("ip_cap") if isinstance(role, dict) else None
        try: role_cap = float(role_cap)
        except Exception: role_cap = np.nan
        if np.isfinite(role_cap):
            final_ip = min(final_ip, role_cap)
        elif np.isfinite(capacity_ip):
            final_ip = min(final_ip - 0.15, capacity_ip + 0.10)
        else:
            final_ip -= 0.30
    else:
        # Soft matchup/hook/damage risk can lower the mean gradually, but it cannot
        # turn a normal established starter into a 1-3 IP projection by itself.
        starter_floor = float(PO_WORKLOAD_V3_CONFIG["normal_starter_floor_ip"])
        if np.isfinite(recent_ip) and completeness >= 60 and recent_ip >= 5.25:
            recent_floor = min(float(PO_WORKLOAD_V3_CONFIG["strong_recent_floor_max_ip"]), recent_ip - 0.60)
            starter_floor = max(starter_floor, float(PO_WORKLOAD_V3_CONFIG["strong_recent_floor_min_ip"]), recent_floor)
            reason_bits.append(f"recent-workload floor {starter_floor:.2f} IP")
        elif np.isfinite(recent_ip) and completeness >= 60 and recent_ip >= 4.90:
            starter_floor = max(starter_floor, min(4.75, recent_ip - 0.30))
        if final_ip < starter_floor:
            final_ip = starter_floor
            reason_bits.append(f"normal-starter floor {starter_floor:.2f} IP")

    final_ip = float(np.clip(final_ip, 0.1, 8.2))
    projection = round(final_ip * 3.0, 1)
    edge = projection - line if np.isfinite(line) else np.nan
    side = "OVER" if np.isfinite(edge) and edge > 0 else "UNDER" if np.isfinite(edge) and edge < 0 else "PASS"
    prob, over_prob, under_prob, sd = _po_v3_candidate_probability(row, projection, line, side, completeness, restriction_conf)

    abs_edge = abs(edge) if np.isfinite(edge) else 0.0
    if side not in {"OVER", "UNDER"}:
        tier = "PASS"
    elif completeness < 45 and restriction_conf < 85:
        tier = "TRACK ONLY"
    elif abs_edge >= 3.0 and np.isfinite(prob) and prob >= 60 and completeness >= 65:
        tier = "V3 OFFICIAL CANDIDATE"
    elif abs_edge >= 1.75 and np.isfinite(prob) and prob >= 57 and completeness >= 55:
        tier = "V3 PLAYABLE CANDIDATE"
    else:
        tier = "V3 TRACK"

    if soft_reasons:
        reason_bits.append("soft risk=" + ", ".join(soft_reasons[:4]))
    if np.isfinite(pc): reason_bits.append(f"PC {pc:.0f}")
    if np.isfinite(recent_ip): reason_bits.append(f"recent IP {recent_ip:.2f}")
    if np.isfinite(recent_bf): reason_bits.append(f"recent BF {recent_bf:.1f}")
    if missing: reason_bits.append("missing=" + ", ".join(missing))

    return {
        "PO V3 Version": PO_WORKLOAD_V3_VERSION,
        "PO V3 Status": "SHADOW_ONLY",
        "PO V3 Recent IP Baseline": round(recent_ip, 2) if np.isfinite(recent_ip) else "",
        "PO V3 Recent IP Source": recent_ip_source,
        "PO V3 Recent BF Baseline": round(recent_bf, 1) if np.isfinite(recent_bf) else "",
        "PO V3 Recent BF Source": recent_bf_source,
        "PO V3 Recent PC Baseline": round(pc, 1) if np.isfinite(pc) else "",
        "PO V3 Recent PC Source": pc_source,
        "PO V3 Capacity IP": round(capacity_ip, 2) if np.isfinite(capacity_ip) else "",
        "PO V3 Capacity Source": capacity_source,
        "PO V3 Data Completeness %": round(completeness, 1),
        "PO V3 Workload Confidence": confidence_label,
        "PO V3 Missing Inputs": ", ".join(missing),
        "PO V3 Restriction Type": restriction_type,
        "PO V3 Restriction Confidence %": round(restriction_conf, 1),
        "PO V3 Hard Restriction": "YES" if hard else "NO",
        "PO V3 Restriction Reasons": ", ".join(hard_reasons),
        "PO V3 Pre-Risk IP": round(pre_ip, 2),
        "PO V3 Soft Risk Score": round(float(soft_score), 2),
        "PO V3 Soft Adjustment IP": round(-soft_penalty + support_boost, 2),
        "PO V3 Final IP": round(final_ip, 2),
        "PO V3 Projection": projection,
        "PO V3 Candidate Lean": side,
        "PO V3 Candidate Edge": round(edge, 2) if np.isfinite(edge) else "",
        "PO V3 Candidate Probability %": prob if np.isfinite(_po_v3_num({"p": prob}, ["p"], np.nan)) else "",
        "PO V3 Over %": over_prob if np.isfinite(_po_v3_num({"p": over_prob}, ["p"], np.nan)) else "",
        "PO V3 Under %": under_prob if np.isfinite(_po_v3_num({"p": under_prob}, ["p"], np.nan)) else "",
        "PO V3 SD Outs": sd,
        "PO V3 Candidate Tier": tier,
        "PO V3 Total Workload Adjustment Outs": round((final_ip - pre_ip) * 3.0, 2),
        "PO V3 Workload Reason": "; ".join(reason_bits),
    }


_PO_V3_BASE_ROWS = globals().get('_impl_beta_projection_rows_07', globals().get('_impl_beta_projection_rows_06', globals().get('_impl_beta_projection_rows_05', globals().get('_impl_beta_projection_rows_04', globals().get('_impl_beta_projection_rows_03', globals().get('_impl_beta_projection_rows_02', globals().get('_impl_beta_projection_rows_01', None)))))))


def _impl_beta_projection_rows_po_v3(board, market):
    if _PO_V3_BASE_ROWS is None:
        return pd.DataFrame()
    df = _PO_V3_BASE_ROWS(board, market)
    if not isinstance(df, pd.DataFrame) or df.empty or str(market or '').upper() != 'OUTS':
        return df
    rows = []
    for _, rr in df.iterrows():
        row = rr.to_dict()
        try:
            row.update(_po_v3_profile(row))
        except Exception as exc:
            row["PO V3 Version"] = PO_WORKLOAD_V3_VERSION
            row["PO V3 Status"] = "ERROR"
            row["PO V3 Workload Reason"] = f"V3 profile error: {str(exc)[:140]}"
        rows.append(row)
    return pd.DataFrame(rows)


def _po_v3_side_result(side, actual, line):
    side = str(side or '').upper()
    if not np.isfinite(actual) or not np.isfinite(line) or side not in {'OVER','UNDER'}:
        return 'NO_ACTION'
    if actual == line: return 'PUSH'
    win = actual > line if side == 'OVER' else actual < line
    return 'WIN' if win else 'LOSS'


def _po_v3_outcome_class(side_result, abs_error, actual, line):
    cfg = PO_WORKLOAD_V3_CONFIG
    if side_result == 'LOSS' and np.isfinite(actual) and np.isfinite(line) and abs(actual-line) <= cfg['boundary_outs']:
        return 'BOUNDARY_LOSS'
    if side_result == 'WIN' and np.isfinite(abs_error) and abs_error >= cfg['severe_miss_outs']:
        return 'CORRECT_SIDE_BAD_PROJECTION'
    if np.isfinite(abs_error) and abs_error >= cfg['extreme_miss_outs']:
        return 'EXTREME_PROJECTION_MISS'
    if np.isfinite(abs_error) and abs_error >= cfg['severe_miss_outs']:
        return 'SEVERE_PROJECTION_MISS'
    if side_result == 'LOSS': return 'NORMAL_MISS'
    if side_result == 'WIN': return 'CORRECT_SIDE_GOOD_PROJECTION'
    return side_result


def _po_v3_append_audit(po_df, actuals_df):
    if not isinstance(po_df, pd.DataFrame) or po_df.empty or not isinstance(actuals_df, pd.DataFrame) or actuals_df.empty:
        return 0
    actual_map = {}
    for _, rr in actuals_df.iterrows():
        name = _tpl_norm_name(rr.get('Pitcher') or rr.get('Player') or rr.get('Name')) if '_tpl_norm_name' in globals() else str(rr.get('Pitcher') or '').lower().strip()
        if name: actual_map[name] = rr.to_dict()
    audit = []
    for _, rr in po_df.iterrows():
        row = rr.to_dict()
        # Ensure V3 exists even if grader receives a saved row from before the public V3 wrapper.
        if not row.get('PO V3 Version'):
            try: row.update(_po_v3_profile(row))
            except Exception: pass
        name = _tpl_norm_name(row.get('Pitcher')) if '_tpl_norm_name' in globals() else str(row.get('Pitcher') or '').lower().strip()
        actual_row = actual_map.get(name)
        if not actual_row: continue
        actual = _tpl_num(actual_row.get('Actual Outs'), None) if '_tpl_num' in globals() else None
        if actual is None and '_tpl_ip_to_outs' in globals():
            actual = _tpl_ip_to_outs(actual_row.get('Actual IP') or actual_row.get('IP'))
        try: actual = float(actual)
        except Exception: continue
        line = _po_v3_num(row, ['UD Line','Line'], np.nan)
        if not np.isfinite(line): continue
        v2_proj = _po_v3_num(row, ['PO Active Projection','PO Workload V2 Projection','Beta Projection'], np.nan)
        v2_side = _po_v3_text(row, ['PO Active Lean','PO Workload V2 Lean','Beta Lean'], '')
        v2_prob = _po_v3_num(row, ['PO Active Hit %','PO Sim Current Side Prob %','PO Workload V2 Hit %'], np.nan)
        v3_proj = _po_v3_num(row, ['PO V3 Projection'], np.nan)
        v3_side = _po_v3_text(row, ['PO V3 Candidate Lean'], '')
        v3_prob = _po_v3_num(row, ['PO V3 Candidate Probability %'], np.nan)
        v2_abs = abs(actual-v2_proj) if np.isfinite(v2_proj) else np.nan
        v3_abs = abs(actual-v3_proj) if np.isfinite(v3_proj) else np.nan
        v2_result = _po_v3_side_result(v2_side, actual, line)
        v3_result = _po_v3_side_result(v3_side, actual, line)
        date = _po_v3_text(row, ['Date','Game Date','game_date','date'], datetime.now().date().isoformat())
        audit.append({
            'Date': date,
            'Pitcher': row.get('Pitcher',''),
            'Opponent': _po_v3_text(row, ['Opponent','opponent','Matchup'], ''),
            'Line': line,
            'Production Side': v2_side,
            'Production Projection Outs': v2_proj if np.isfinite(v2_proj) else '',
            'Production Projection IP': round(v2_proj/3.0,2) if np.isfinite(v2_proj) else '',
            'Production Probability %': v2_prob if np.isfinite(v2_prob) else '',
            'Production Status': row.get('PO Official Tier',''),
            'Production Side Result': v2_result,
            'Production Abs Projection Error': round(v2_abs,2) if np.isfinite(v2_abs) else '',
            'Production Signed Error': round(actual-v2_proj,2) if np.isfinite(v2_proj) else '',
            'V3 Side': v3_side,
            'V3 Projection Outs': v3_proj if np.isfinite(v3_proj) else '',
            'V3 Projection IP': round(v3_proj/3.0,2) if np.isfinite(v3_proj) else '',
            'V3 Probability %': v3_prob if np.isfinite(v3_prob) else '',
            'V3 Candidate Tier': row.get('PO V3 Candidate Tier',''),
            'V3 Side Result': v3_result,
            'V3 Abs Projection Error': round(v3_abs,2) if np.isfinite(v3_abs) else '',
            'V3 Signed Error': round(actual-v3_proj,2) if np.isfinite(v3_proj) else '',
            'V3 Outcome Class': _po_v3_outcome_class(v3_result, v3_abs, actual, line),
            'Actual Outs': actual,
            'Actual IP': actual_row.get('Actual IP') or actual_row.get('IP') or '',
            'Distance Actual From Line': round(actual-line,2),
            'Recent IP Baseline': row.get('PO V3 Recent IP Baseline',''),
            'Recent BF Baseline': row.get('PO V3 Recent BF Baseline',''),
            'Recent Pitch Count Baseline': row.get('PO V3 Recent PC Baseline',''),
            'Workload Data Completeness %': row.get('PO V3 Data Completeness %',''),
            'Workload Confidence': row.get('PO V3 Workload Confidence',''),
            'Restriction Type': row.get('PO V3 Restriction Type',''),
            'Restriction Confidence %': row.get('PO V3 Restriction Confidence %',''),
            'Pre-Cal Projection': row.get('Pre-PO Calibration Projection', row.get('Beta Projection','')),
            'V3 Pre-Risk IP': row.get('PO V3 Pre-Risk IP',''),
            'V3 Final Projection': row.get('PO V3 Projection',''),
            'V3 Total Workload Adjustment Outs': row.get('PO V3 Total Workload Adjustment Outs',''),
            'V3 Workload Reason': row.get('PO V3 Workload Reason',''),
            'V3 Version': PO_WORKLOAD_V3_VERSION,
            'Graded At': datetime.now().isoformat(timespec='seconds'),
        })
    if not audit: return 0
    new = pd.DataFrame(audit)
    try:
        os.makedirs(os.path.dirname(PO_WORKLOAD_V3_AUDIT_FILE) or '.', exist_ok=True)
        if os.path.exists(PO_WORKLOAD_V3_AUDIT_FILE):
            old = pd.read_csv(PO_WORKLOAD_V3_AUDIT_FILE, low_memory=False)
            out = pd.concat([old,new], ignore_index=True, sort=False)
        else:
            out = new
        keys = [c for c in ['Date','Pitcher','Line','V3 Version'] if c in out.columns]
        if keys: out = out.drop_duplicates(subset=keys, keep='last')
        out.to_csv(PO_WORKLOAD_V3_AUDIT_FILE, index=False)
    except Exception:
        return 0
    return len(new)


_po_v3_legacy_grade_pitching_outs_loss_lab = grade_pitching_outs_loss_lab

def grade_pitching_outs_loss_lab(po_df, actuals_df):
    result = _po_v3_legacy_grade_pitching_outs_loss_lab(po_df, actuals_df)
    try:
        n = _po_v3_append_audit(po_df, actuals_df)
        if isinstance(result, dict):
            result = dict(result)
            result['projection_audit_v3_rows'] = n
            result['projection_audit_v3_path'] = PO_WORKLOAD_V3_AUDIT_FILE
    except Exception:
        pass
    return result


def _po_v3_calibration_summary():
    try:
        if not os.path.exists(PO_WORKLOAD_V3_AUDIT_FILE): return pd.DataFrame()
        df = pd.read_csv(PO_WORKLOAD_V3_AUDIT_FILE, low_memory=False)
        if df.empty: return pd.DataFrame()
        p = pd.to_numeric(df.get('V3 Probability %'), errors='coerce')
        bins = [55,60,65,70,75,80,85,90,95,101]
        labels = ['55-59.9','60-64.9','65-69.9','70-74.9','75-79.9','80-84.9','85-89.9','90-94.9','95%+']
        df = df.assign(_bucket=pd.cut(p, bins=bins, labels=labels, right=False))
        df = df[df['_bucket'].notna()].copy()
        if df.empty: return pd.DataFrame()
        df['_win'] = df['V3 Side Result'].astype(str).eq('WIN').astype(int)
        df['_loss'] = df['V3 Side Result'].astype(str).eq('LOSS').astype(int)
        df['_abs'] = pd.to_numeric(df['V3 Abs Projection Error'], errors='coerce')
        df['_signed'] = pd.to_numeric(df['V3 Signed Error'], errors='coerce')
        out = df.groupby('_bucket', observed=False).agg(
            Plays=('V3 Side Result','count'), Wins=('_win','sum'), Losses=('_loss','sum'),
            Avg_Projection_Error=('_abs','mean'), Avg_Signed_Error=('_signed','mean')
        ).reset_index().rename(columns={'_bucket':'Probability Bucket'})
        out['Win %'] = np.where(out['Wins']+out['Losses']>0, 100*out['Wins']/(out['Wins']+out['Losses']), np.nan)
        out['Avg Projection Error'] = out['Avg_Projection_Error'].round(2)
        out['Avg Signed Error'] = out['Avg_Signed_Error'].round(2)
        return out[['Probability Bucket','Plays','Wins','Losses','Win %','Avg Projection Error','Avg Signed Error']]
    except Exception:
        return pd.DataFrame()


_po_v3_legacy_card_renderer = _po_render_player_cards

def _po_render_player_cards(df, board=None, limit=None):
    """Cleaner PO cards. Production V2 remains primary; V3 is clearly labeled shadow."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty: return 0
    show = df.head(int(limit)) if limit else df
    cards = []
    for _, rr in show.iterrows():
        try:
            row = rr.to_dict()
            pitcher = _po_v3_text(row, ['Pitcher'], 'Pitcher')
            matchup = _po_v3_text(row, ['Matchup'], '')
            away, home = _po_card_matchup_teams(matchup) if '_po_card_matchup_teams' in globals() else ('','')
            logo_team = away or home
            if board and '_kcard_board_lookup' in globals() and '_kcard_pitcher_team' in globals():
                try:
                    lookup = _kcard_board_lookup(board)
                    key = _tpl_norm_name(pitcher) if '_tpl_norm_name' in globals() else pitcher.lower().strip()
                    p = lookup.get(key,{})
                    logo_team = _kcard_pitcher_team(row,p) or logo_team
                except Exception: pass
            logo_url = _po_card_team_logo(logo_team) if '_po_card_team_logo' in globals() else ''
            logo_html = f"<img class='pov3-logo' src='{html.escape(logo_url)}'/>" if logo_url else f"<div class='pov3-logo pov3-fallback'>{html.escape((logo_team or 'MLB')[:3])}</div>"
            line = _po_v3_num(row,['UD Line'],np.nan)
            active_proj = _po_v3_num(row,['PO Active Projection','PO Workload V2 Projection'],np.nan)
            active_ip = _po_v3_num(row,['PO Active IP','PO Workload V2 IP'],np.nan)
            active_side = _po_v3_text(row,['PO Active Lean'],'TRACK').upper()
            active_prob = _po_v3_num(row,['PO Active Hit %','PO Sim Current Side Prob %'],np.nan)
            tier = _po_v3_text(row,['PO Official Tier'],'TRACK')
            v3_proj = _po_v3_num(row,['PO V3 Projection'],np.nan)
            v3_ip = _po_v3_num(row,['PO V3 Final IP'],np.nan)
            v3_side = _po_v3_text(row,['PO V3 Candidate Lean'],'—')
            v3_prob = _po_v3_num(row,['PO V3 Candidate Probability %'],np.nan)
            v3_tier = _po_v3_text(row,['PO V3 Candidate Tier'],'SHADOW')
            data = _po_v3_num(row,['PO V3 Data Completeness %'],np.nan)
            conf = _po_v3_text(row,['PO V3 Workload Confidence'],'—')
            rip = _po_v3_num(row,['PO V3 Recent IP Baseline'],np.nan)
            rbf = _po_v3_num(row,['PO V3 Recent BF Baseline'],np.nan)
            rpc = _po_v3_num(row,['PO V3 Recent PC Baseline'],np.nan)
            restriction = _po_v3_text(row,['PO V3 Restriction Type'],'NONE')
            rconf = _po_v3_num(row,['PO V3 Restriction Confidence %'],np.nan)
            hook = _po_v3_num(row,['Recent Hook Rate','PO Fill Hook Rate'],np.nan)
            damage = _po_v3_text(row,['Damage Risk Label','PO Fill Damage Label','run_damage_risk_level'],'—')
            reason = _po_v3_text(row,['PO V3 Workload Reason'],'')
            missing = _po_v3_text(row,['PO V3 Missing Inputs'],'')
            cls = 'over' if 'OVER' in active_side else 'under' if 'UNDER' in active_side else 'track'
            def f(v,d=1): return '—' if not np.isfinite(v) else f'{v:.{d}f}'
            cards.append(f"""
            <article class='pov3-card {cls}'>
              <div class='pov3-head'><div class='pov3-id'>{logo_html}<div><h3>{html.escape(pitcher)}</h3><p>{html.escape(matchup)}</p></div></div><span class='pov3-tier'>{html.escape(tier)}</span></div>
              <div class='pov3-compare'>
                <div class='pov3-primary'><span>PRODUCTION V2</span><strong>{f(active_proj)}</strong><b>{html.escape(active_side)} {f(line)}</b><small>{f(active_ip,2)} IP · {f(active_prob)}%</small></div>
                <div class='pov3-shadow'><span>CHALLENGER V3 · SHADOW</span><strong>{f(v3_proj)}</strong><b>{html.escape(v3_side)} {f(line)}</b><small>{f(v3_ip,2)} IP · {f(v3_prob)}% · {html.escape(v3_tier)}</small></div>
              </div>
              <div class='pov3-grid'>
                <div><span>RECENT IP</span><b>{f(rip,2)}</b></div><div><span>RECENT BF</span><b>{f(rbf)}</b></div><div><span>RECENT PC</span><b>{f(rpc)}</b></div>
                <div><span>DATA</span><b>{f(data,0)}%</b><small>{html.escape(conf)}</small></div><div><span>HOOK</span><b>{f(hook,0)}%</b></div><div><span>DAMAGE</span><b>{html.escape(damage)}</b></div>
              </div>
              <div class='pov3-context'><b>Role / restriction:</b> {html.escape(restriction)}{(' · '+f(rconf,0)+'% confidence') if np.isfinite(rconf) and rconf>0 else ''}</div>
              <div class='pov3-note'><b>V3 workload:</b> {html.escape(reason or 'No extra workload note')}</div>
              {f"<div class='pov3-warning'><b>Missing workload data:</b> {html.escape(missing)}</div>" if missing else ''}
            </article>""")
        except Exception as exc:
            cards.append(f"<article class='pov3-card track'><h3>Pitching Outs row</h3><p>{html.escape(str(exc)[:160])}</p></article>")
    css = r"""
    <style>
    .pov3-wrap{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:8px 0 18px}
    .pov3-card{background:linear-gradient(145deg,#0b1321,#07101c);border:1px solid #26364b;border-radius:17px;padding:15px;color:#eef5ff;box-shadow:0 10px 26px rgba(0,0,0,.23)}
    .pov3-card.over{border-top:3px solid #2ed8ff}.pov3-card.under{border-top:3px solid #ffe06a}.pov3-card.track{border-top:3px solid #ff6b75}
    .pov3-head,.pov3-id{display:flex;align-items:center}.pov3-head{justify-content:space-between;gap:10px;margin-bottom:10px}.pov3-id{gap:10px;min-width:0}
    .pov3-logo{width:40px;height:40px;object-fit:contain;border-radius:50%;background:#111b2a;border:1px solid #2c3c52;padding:4px}.pov3-fallback{display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:900}
    .pov3-head h3{margin:0;font-size:17px}.pov3-head p{margin:3px 0 0;color:#98a8bd;font-size:10px}.pov3-tier{font-size:9px;font-weight:900;border:1px solid #51647d;border-radius:999px;padding:5px 8px;white-space:nowrap}
    .pov3-compare{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pov3-primary,.pov3-shadow{background:#0d1827;border:1px solid #22344d;border-radius:13px;padding:11px}.pov3-shadow{border-color:#21586b}
    .pov3-compare span,.pov3-grid span{display:block;color:#8fa1b9;font-size:8px;font-weight:900;letter-spacing:.07em}.pov3-compare strong{display:block;color:#47d9ff;font-size:27px;line-height:1;margin:6px 0}.pov3-shadow strong{color:#9cecff}.pov3-compare b{font-size:11px}.pov3-compare small{display:block;color:#a8b4c3;font-size:9px;margin-top:4px}
    .pov3-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}.pov3-grid>div{background:#0a1421;border:1px solid #1e2f45;border-radius:10px;padding:8px;min-height:49px}.pov3-grid b{display:block;font-size:13px;margin-top:4px}.pov3-grid small{font-size:8px;color:#9fb0c4}
    .pov3-context,.pov3-note,.pov3-warning{font-size:9.5px;line-height:1.35;color:#aeb9c7;border-top:1px solid #1d2b3e;padding-top:8px;margin-top:8px}.pov3-context b,.pov3-note b{color:#eff5ff}.pov3-warning{color:#ffd28a}
    @media(max-width:900px){.pov3-wrap{grid-template-columns:1fr}}@media(max-width:520px){.pov3-card{padding:11px}.pov3-compare strong{font-size:24px}.pov3-grid{gap:5px}.pov3-grid>div{padding:7px}}
    </style>"""
    full = css + "<div class='pov3-wrap'>" + ''.join(cards) + "</div>"
    full = "\n".join(line.lstrip() for line in full.splitlines()).strip()
    st.html(full) if hasattr(st,'html') else st.markdown(full, unsafe_allow_html=True)
    return len(cards)


_po_v3_legacy_render_po = _impl_render_beta_pitching_outs_tab_06

def _impl_render_beta_pitching_outs_tab_po_v3(board):
    _po_v3_legacy_render_po(board)
    summary = _po_v3_calibration_summary()
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        with st.expander('Pitching Outs V3 — forward calibration / projection accuracy', expanded=False):
            st.caption('V3 is shadow-only. Side accuracy and projection accuracy are tracked separately; production V2 is not replaced from this table automatically.')
            st.dataframe(summary, use_container_width=True, hide_index=True)
            try:
                audit = pd.read_csv(PO_WORKLOAD_V3_AUDIT_FILE, low_memory=False)
                if not audit.empty:
                    a = pd.to_numeric(audit['V3 Abs Projection Error'], errors='coerce')
                    s = pd.to_numeric(audit['V3 Signed Error'], errors='coerce')
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric('V3 MAE', '—' if a.dropna().empty else f'{a.mean():.2f} outs')
                    c2.metric('V3 RMSE', '—' if a.dropna().empty else f'{np.sqrt(np.nanmean(np.square(a))):.2f}')
                    c3.metric('V3 Signed Bias', '—' if s.dropna().empty else f'{s.mean():+.2f}')
                    c4.metric('5+ Out Misses', int((a>=PO_WORKLOAD_V3_CONFIG['severe_miss_outs']).sum()))
            except Exception:
                pass
'''.strip("\n")


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    lines = text.splitlines(keepends=True)
    beta_hits = [i for i,l in enumerate(lines) if l.startswith(BETA_BIND_PREFIX)]
    render_hits = [i for i,l in enumerate(lines) if l.startswith(RENDER_BIND_PREFIX)]
    if len(beta_hits) != 1:
        raise RuntimeError(f"Expected one public beta row binding, found {len(beta_hits)}")
    if len(render_hits) != 1:
        raise RuntimeError(f"Expected one public PO render binding, found {len(render_hits)}")
    insert_at = min(beta_hits[0], render_hits[0])
    lines.insert(insert_at, BLOCK + "\n\n")
    out = ''.join(lines)
    # Recompute by text replacement after insertion.
    beta_line = next(l for l in out.splitlines() if l.startswith(BETA_BIND_PREFIX))
    render_line = next(l for l in out.splitlines() if l.startswith(RENDER_BIND_PREFIX))
    out = out.replace(beta_line, "_beta_projection_rows = _impl_beta_projection_rows_po_v3", 1)
    out = out.replace(render_line, "render_beta_pitching_outs_tab = _impl_render_beta_pitching_outs_tab_po_v3", 1)
    ast.parse(out)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', default='app.py')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding='utf-8-sig')
    patched = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / 'app_po_v3.py'
        probe.write_text(patched, encoding='utf-8')
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print('PO Workload V3 patch CHECK PASS')
        return 0
    if patched != original:
        tmp = path.with_suffix(path.suffix + '.po_v3_tmp')
        tmp.write_text(patched, encoding='utf-8')
        tmp.replace(path)
    print('PO Workload V3 patch READY')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
