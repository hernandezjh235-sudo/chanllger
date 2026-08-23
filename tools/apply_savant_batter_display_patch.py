#!/usr/bin/env python3
"""Display-only/diagnostic bridge for batter-by-batter Savant K splits.

Purpose
-------
* Keep the K engine's existing Savant-authority patch intact.
* Ensure the Batter-by-Batter table displays the real current-season Baseball
  Savant vs-pitcher-hand PA, SO and K% whenever that split exists.
* Resolve hitters by MLBAM id first and normalized player name second.
* Recompute displayed K% directly as SO / PA so the visible percentage always
  agrees with the visible sample.
* Fall back player-by-player through current, targeted and LAST_GOOD Savant
  caches instead of showing dashes merely because one cache/match path missed.

This patch does not modify BF/IP, pitcher workload, side protection, grading,
Moneyline, Pitching Outs, HRR or Batter Fantasy formulas.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_SAVANT_BATTER_DISPLAY_V2_2026_08_23"
ANCHOR = "_beta_projection_rows = globals().get('_impl_beta_projection_rows_07'"

BLOCK = r'''
# CHALLENGER_SAVANT_BATTER_DISPLAY_V2_2026_08_23
# Batter-table bridge: visible Savant raw K% is always SO/PA from the same
# current-season vs-hand data family used by the K engine.


def _sbd_num(value, default=None):
    try:
        if value in (None, "", "—", "-", "nan", "NaN"):
            return default
        out = float(str(value).replace("%", "").replace(",", "").strip())
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _sbd_id(value):
    try:
        if value in (None, ""):
            return ""
        return str(int(float(value)))
    except Exception:
        return ""


def _sbd_norm_name(value):
    try:
        raw = "".join(
            ch for ch in unicodedata.normalize("NFKD", str(value or ""))
            if not unicodedata.combining(ch)
        ).lower()
        raw = re.sub(r"[^a-z0-9 ]+", " ", raw)
        raw = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", raw)
        return " ".join(raw.split())
    except Exception:
        return str(value or "").lower().strip()


def _sbd_player_id(row):
    if not isinstance(row, dict):
        return ""
    for key in (
        "mlbam_id", "MLBAM ID", "MLBAM_ID", "player_id", "Player ID",
        "Batter ID", "batter_id", "person_id", "Person ID", "id",
    ):
        pid = _sbd_id(row.get(key))
        if pid:
            return pid
    return ""


def _sbd_player_name(row):
    if not isinstance(row, dict):
        return ""
    for key in ("Batter", "Player", "Name", "player_name", "batter_name"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _sbd_frame_candidates(platoon_frame):
    frames = []
    if isinstance(platoon_frame, pd.DataFrame) and not platoon_frame.empty:
        frames.append(("LIVE/CACHE", platoon_frame.copy()))
    season = int(datetime.now().year)
    for label, path in (
        ("CURRENT", Path("learning_data") / f"savant_batter_platoon_{season}.csv"),
        ("TARGETED", Path("learning_data") / f"savant_batter_platoon_{season}.targeted.csv"),
        ("LAST_GOOD", Path("learning_data") / f"savant_batter_platoon_{season}.last_good.csv"),
    ):
        try:
            if path.exists():
                frame = pd.read_csv(path)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    frames.append((label, frame))
        except Exception:
            continue
    return frames


def _sbd_lookup_maps(platoon_frame, pitcher_hand):
    hand = str(pitcher_hand or "").upper()
    split = "lhp" if hand.startswith("L") else "rhp"
    pa_col = f"vs_{split}_pa"
    so_col = f"vs_{split}_so"
    k_col = f"vs_{split}_k_pct"
    by_id, by_name = {}, {}

    for source, frame in _sbd_frame_candidates(platoon_frame):
        required = {"mlbam_id", "player_name", pa_col, so_col}
        if not required.issubset(frame.columns):
            continue
        for _, rec in frame.iterrows():
            pa = _sbd_num(rec.get(pa_col), None)
            so = _sbd_num(rec.get(so_col), None)
            if pa is None or pa <= 0 or so is None or so < 0:
                continue
            # Visible raw percentage is derived from the visible official sample.
            calc_k = 100.0 * float(so) / float(pa)
            stored_k = _sbd_num(rec.get(k_col), None)
            payload = {
                "pa": int(round(pa)),
                "so": int(round(so)),
                "k_pct": float(calc_k),
                "stored_k_pct": stored_k,
                "source": source,
            }
            pid = _sbd_id(rec.get("mlbam_id"))
            name = _sbd_norm_name(rec.get("player_name"))
            # First valid match wins: passed live/cache, then CURRENT, TARGETED,
            # then LAST_GOOD.  This lets LAST_GOOD fill individual holes without
            # overriding a valid current split.
            if pid and pid not in by_id:
                by_id[pid] = payload
            if name and name not in by_name:
                by_name[name] = payload
    return by_id, by_name


def _sbd_slot_counts(expected_bf, slots=9):
    bf = max(0.0, _sbd_num(expected_bf, 0.0) or 0.0)
    lo = int(math.floor(bf))
    frac = bf - lo
    def counts(n):
        out = []
        for slot in range(1, slots + 1):
            if n < slot:
                out.append(0.0)
            else:
                out.append(float(1 + (n - slot) // slots))
        return out
    a, b = counts(lo), counts(lo + 1)
    return [a[i] * (1.0 - frac) + b[i] * frac for i in range(slots)]


_legacy_attach_savant_shadow_for_display = attach_savant_shadow


def attach_savant_shadow(lineup_rows, pitcher_hand, platoon_frame, expected_bf):
    """Enrich the visible batter table with authoritative Savant split samples."""
    try:
        enriched, audit = _legacy_attach_savant_shadow_for_display(
            lineup_rows, pitcher_hand, platoon_frame, expected_bf
        )
    except Exception:
        enriched = [dict(x) for x in (lineup_rows or []) if isinstance(x, dict)][:9]
        audit = {}

    rows = [dict(x) for x in (enriched or []) if isinstance(x, dict)][:9]
    original = [dict(x) for x in (lineup_rows or []) if isinstance(x, dict)][:9]
    by_id, by_name = _sbd_lookup_maps(platoon_frame, pitcher_hand)

    matched_values = []
    weighted_pairs = []
    top, middle, bottom = [], [], []
    slot_counts = _sbd_slot_counts(expected_bf, 9)
    match_methods = []

    for idx, row in enumerate(rows):
        src = original[idx] if idx < len(original) else row
        pid = _sbd_player_id(row) or _sbd_player_id(src)
        name = _sbd_player_name(row) or _sbd_player_name(src)
        rec = by_id.get(pid) if pid else None
        method = "MLBAM_ID" if rec is not None else ""
        if rec is None and name:
            rec = by_name.get(_sbd_norm_name(name))
            method = "NORMALIZED_NAME" if rec is not None else ""

        if rec is not None:
            raw_k = round(float(rec["k_pct"]), 3)
            raw_pa = int(rec["pa"])
            raw_so = int(rec["so"])
            row["savant_raw_vs_hand_k_pct"] = raw_k
            row["savant_raw_vs_hand_pa"] = raw_pa
            row["savant_raw_vs_hand_so"] = raw_so
            row["Savant Match Status"] = method
            row["Savant Split Source"] = rec.get("source")
            row["Savant Raw Math"] = f"{raw_so}/{raw_pa}"

            # Keep a visible integrity diagnostic if a stored percentage ever
            # differs from SO/PA after a future refresh.  The table still uses
            # the official SO/PA calculation.
            stored = rec.get("stored_k_pct")
            if stored is not None:
                row["Savant Stored-vs-Math Delta pp"] = round(float(stored) - raw_k, 3)

            used = None
            for key in ("Used K%", "K% Used", "Raw_K_Rate", "Split K%", "Season K%"):
                v = _sbd_num(row.get(key), None)
                if v is not None:
                    used = v * 100.0 if abs(v) <= 1.0 else v
                    break
            if used is not None:
                row["savant_model_delta_pp"] = round(float(used) - raw_k, 3)

            matched_values.append(raw_k)
            weight = slot_counts[idx] if idx < len(slot_counts) else 1.0
            weighted_pairs.append((raw_k, weight))
            (top if idx < 3 else middle if idx < 6 else bottom).append(raw_k)
            match_methods.append(method)
        else:
            # A dash now means there truly was no usable Savant PA/SO split in
            # live/current/targeted/LAST_GOOD, not merely a failed card match.
            row["Savant Match Status"] = "SAVANT_TRUE_SPLIT_UNAVAILABLE"
        rows[idx] = row

    audit = dict(audit or {})
    matched = len(matched_values)
    audit["matched"] = matched
    audit["status"] = "FULL" if matched == len(rows) and rows else "PARTIAL" if matched else "UNAVAILABLE"
    audit["simple_savant_lineup_k_pct"] = round(sum(matched_values) / matched, 3) if matched else None
    wsum = sum(w for _, w in weighted_pairs)
    audit["order_weighted_savant_k_pct"] = (
        round(sum(v * w for v, w in weighted_pairs) / wsum, 3) if wsum > 0 else None
    )
    audit["top3_savant_k_pct"] = round(sum(top) / len(top), 3) if top else None
    audit["middle3_savant_k_pct"] = round(sum(middle) / len(middle), 3) if middle else None
    audit["bottom3_savant_k_pct"] = round(sum(bottom) / len(bottom), 3) if bottom else None
    audit["display_bridge"] = "SAVANT_PA_SO_AUTHORITATIVE_V2"
    audit["match_methods"] = match_methods
    return rows, audit
'''.strip("\n")


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if text.count(ANCHOR) != 1:
        raise RuntimeError(f"Expected exactly one batter-display anchor, found {text.count(ANCHOR)}")
    out = text.replace(ANCHOR, BLOCK + "\n\n" + ANCHOR, 1)
    ast.parse(out)
    return out


def _validate_source_files():
    season = 2026
    active = Path("learning_data") / f"savant_batter_platoon_{season}.csv"
    fallback = Path("learning_data") / f"savant_batter_platoon_{season}.last_good.csv"
    path = active if active.exists() else fallback
    if not path.exists():
        raise RuntimeError("No Savant platoon source file found")
    import pandas as pd
    frame = pd.read_csv(path)
    required = {
        "mlbam_id", "player_name",
        "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct",
        "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct",
    }
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError("Savant platoon source schema incomplete")
    for hand in ("rhp", "lhp"):
        pa = pd.to_numeric(frame[f"vs_{hand}_pa"], errors="coerce")
        so = pd.to_numeric(frame[f"vs_{hand}_so"], errors="coerce")
        kp = pd.to_numeric(frame[f"vs_{hand}_k_pct"], errors="coerce")
        mask = (pa > 0) & so.notna() & kp.notna()
        if int(mask.sum()) < 600:
            raise RuntimeError(f"Insufficient Savant {hand} coverage: {int(mask.sum())}")
        calc = 100.0 * so[mask] / pa[mask]
        max_err = float((calc - kp[mask]).abs().max())
        if max_err > 0.15:
            raise RuntimeError(f"Savant {hand} stored K% disagrees with SO/PA: max {max_err:.3f}pp")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    _validate_source_files()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_savant_display.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print("Savant batter display V2 CHECK PASS")
        return 0
    if patched != original:
        tmp = path.with_suffix(path.suffix + ".savant_display_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(path)
    print("Savant batter display V2 READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
