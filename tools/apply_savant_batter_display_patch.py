#!/usr/bin/env python3
"""Final-card Savant batter split repair for Challenger.

This is deliberately display/enrichment-only.  The K engine's Savant authority
formula stays untouched.  The repair replaces the exact function used by the
live K cards (`_v269_savant_shadow_rows`) so the table cannot bypass the fix.

Root causes fixed:
1. The previous patch wrapped `attach_savant_shadow`, but the live card path can
   resolve that symbol through the optional import/fallback block before the
   late wrapper is executed.
2. Savant stores many names as `Last, First` while lineup rows use `First Last`.
   The old normalized-name fallback preserved token order, so a row without an
   MLBAM id could miss every hitter despite valid Savant data.

Visible raw K% is always recomputed as SO / PA against today's pitcher hand.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_SAVANT_BATTER_DISPLAY_V3_2026_08_23"
TARGET = "_v269_savant_shadow_rows"

REPLACEMENT = r'''
def _v269_savant_shadow_rows(lineup_rows, pitcher_hand, expected_bf, board_row=None):
    """Authoritative final-card Savant enrichment.

    This is the function the live Batter-by-Batter card calls immediately before
    `_kcard_lineup_html`.  It resolves MLBAM id first, then canonicalized player
    name, and calculates the visible split percentage directly from SO/PA.
    """
    rows = [dict(x) for x in (lineup_rows or []) if isinstance(x, dict)][:9]
    hand = str(pitcher_hand or "").upper()
    split = "lhp" if hand.startswith("L") else "rhp"
    pa_col = f"vs_{split}_pa"
    so_col = f"vs_{split}_so"
    k_col = f"vs_{split}_k_pct"

    def _num(value, default=None):
        try:
            if value in (None, "", "—", "-", "nan", "NaN"):
                return default
            out = float(str(value).replace("%", "").replace(",", "").strip())
            return out if math.isfinite(out) else default
        except Exception:
            return default

    def _pid(value):
        try:
            if value in (None, ""):
                return ""
            return str(int(float(value)))
        except Exception:
            return ""

    def _canon_name(value):
        try:
            text = str(value or "").strip()
            # Baseball/Savant CSVs commonly use "Last, First"; lineup feeds use
            # "First Last".  Reorder before punctuation is stripped.
            if "," in text:
                left, right = text.split(",", 1)
                if left.strip() and right.strip():
                    text = f"{right.strip()} {left.strip()}"
            text = "".join(
                ch for ch in unicodedata.normalize("NFKD", text)
                if not unicodedata.combining(ch)
            ).lower()
            text = re.sub(r"[^a-z0-9 ]+", " ", text)
            text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
            return " ".join(text.split())
        except Exception:
            return str(value or "").lower().strip()

    def _token_key(value):
        name = _canon_name(value)
        return " ".join(sorted(name.split())) if name else ""

    def _row_pid(row):
        for key in (
            "mlbam_id", "MLBAM ID", "MLBAM_ID", "player_id", "Player ID",
            "Batter ID", "batter_id", "person_id", "Person ID", "id",
        ):
            got = _pid(row.get(key))
            if got:
                return got
        return ""

    def _row_name(row):
        for key in ("Batter", "Player", "Name", "player_name", "batter_name"):
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    try:
        service = _v269_savant_service()
        # service.load() already performs current -> targeted -> LAST_GOOD
        # handling in the compatibility implementation.
        platoon = service.load() if hasattr(service, "load") else pd.DataFrame()
    except Exception:
        service = None
        platoon = pd.DataFrame()

    # Direct source fallback protects the card even if the optional helper
    # service changes or returns an incomplete frame.
    frames = []
    if isinstance(platoon, pd.DataFrame) and not platoon.empty:
        frames.append(("LIVE/CACHE", platoon.copy()))
    try:
        season = int(datetime.now().year)
    except Exception:
        season = 2026
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
            pass

    by_id, by_name, by_tokens = {}, {}, {}
    for source, frame in frames:
        required = {"mlbam_id", "player_name", pa_col, so_col}
        if not required.issubset(frame.columns):
            continue
        for _, rec in frame.iterrows():
            pa = _num(rec.get(pa_col), None)
            so = _num(rec.get(so_col), None)
            if pa is None or pa <= 0 or so is None or so < 0:
                continue
            raw_k = 100.0 * float(so) / float(pa)
            payload = {
                "pa": int(round(pa)),
                "so": int(round(so)),
                "k_pct": float(raw_k),
                "stored_k_pct": _num(rec.get(k_col), None),
                "source": source,
                "player_name": str(rec.get("player_name") or ""),
            }
            rid = _pid(rec.get("mlbam_id"))
            rname = _canon_name(rec.get("player_name"))
            rtok = _token_key(rec.get("player_name"))
            if rid and rid not in by_id:
                by_id[rid] = payload
            if rname and rname not in by_name:
                by_name[rname] = payload
            if rtok and rtok not in by_tokens:
                by_tokens[rtok] = payload

    bf = max(0.0, _num(expected_bf, 0.0) or 0.0)
    lo = int(math.floor(bf))
    frac = bf - lo
    def _counts(n):
        out = []
        for slot in range(1, 10):
            out.append(0.0 if n < slot else float(1 + (n - slot) // 9))
        return out
    ca, cb = _counts(lo), _counts(lo + 1)
    slot_counts = [ca[i] * (1.0 - frac) + cb[i] * frac for i in range(9)]

    matched_values, weighted_pairs = [], []
    top, middle, bottom = [], [], []
    match_methods = []

    for idx, row in enumerate(rows):
        pid = _row_pid(row)
        name = _row_name(row)
        rec = by_id.get(pid) if pid else None
        method = "MLBAM_ID" if rec is not None else ""
        if rec is None and name:
            rec = by_name.get(_canon_name(name))
            method = "NAME_CANONICAL" if rec is not None else ""
        if rec is None and name:
            rec = by_tokens.get(_token_key(name))
            method = "NAME_TOKEN_KEY" if rec is not None else ""

        if rec is None:
            row["Savant Match Status"] = "SAVANT_PLAYER_MATCH_UNCERTAIN"
            rows[idx] = row
            continue

        raw_pa = int(rec["pa"])
        raw_so = int(rec["so"])
        raw_k = round(100.0 * raw_so / raw_pa, 3)
        row["savant_raw_vs_hand_k_pct"] = raw_k
        row["savant_raw_vs_hand_pa"] = raw_pa
        row["savant_raw_vs_hand_so"] = raw_so
        row["Savant Match Status"] = method
        row["Savant Split Source"] = rec.get("source")
        row["Savant Raw Math"] = f"{raw_so}/{raw_pa}"

        stored = rec.get("stored_k_pct")
        if stored is not None:
            row["Savant Stored-vs-Math Delta pp"] = round(float(stored) - raw_k, 3)

        used = None
        for key in ("Used K%", "K% Used", "Raw_K_Rate", "Split K%", "Season K%"):
            value = _num(row.get(key), None)
            if value is not None:
                used = value * 100.0 if abs(value) <= 1.0 else value
                break
        if used is not None:
            delta = round(float(used) - raw_k, 3)
            # `_kcard_lineup_html` reads model_minus_savant_pp.
            row["model_minus_savant_pp"] = delta
            row["savant_model_delta_pp"] = delta

        matched_values.append(raw_k)
        weight = slot_counts[idx] if idx < len(slot_counts) else 1.0
        weighted_pairs.append((raw_k, weight))
        (top if idx < 3 else middle if idx < 6 else bottom).append(raw_k)
        match_methods.append(method)
        rows[idx] = row

    matched = len(matched_values)
    wsum = sum(w for _, w in weighted_pairs)
    audit = {
        "status": "FULL" if rows and matched == len(rows) else "PARTIAL" if matched else "UNAVAILABLE",
        "matched": matched,
        "simple_savant_lineup_k_pct": round(sum(matched_values) / matched, 3) if matched else None,
        "order_weighted_savant_k_pct": round(sum(v*w for v,w in weighted_pairs) / wsum, 3) if wsum > 0 else None,
        "top3_savant_k_pct": round(sum(top) / len(top), 3) if top else None,
        "middle3_savant_k_pct": round(sum(middle) / len(middle), 3) if middle else None,
        "bottom3_savant_k_pct": round(sum(bottom) / len(bottom), 3) if bottom else None,
        "display_bridge": "FINAL_CARD_SAVANT_SO_PA_V3",
        "match_methods": match_methods,
    }

    if isinstance(board_row, dict):
        board_row.update({
            "savant_enriched_lineup_rows": [dict(x) for x in rows],
            "savant_shadow_status": audit["status"],
            "savant_shadow_matched_hitters": matched,
            "simple_savant_lineup_k_pct": audit["simple_savant_lineup_k_pct"],
            "raw_savant_order_weighted_k_exposure": audit["order_weighted_savant_k_pct"],
            "top3_savant_k_pct": audit["top3_savant_k_pct"],
            "middle3_savant_k_pct": audit["middle3_savant_k_pct"],
            "bottom3_savant_k_pct": audit["bottom3_savant_k_pct"],
            "savant_shadow_projection_effect_k": 0.0,
            "savant_shadow_mode": "DISPLAY_ONLY_NO_PRODUCTION_EFFECT",
        })
    return rows, audit
'''.strip("\n")


def _function_nodes(text: str, name: str):
    tree = ast.parse(text)
    return [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == name and getattr(n, "col_offset", 1) == 0
    ]


def patch_text(text: str) -> tuple[str, int]:
    if MARKER in text:
        return text, 0
    nodes = _function_nodes(text, TARGET)
    if len(nodes) != 1:
        raise RuntimeError(f"Expected exactly one top-level {TARGET}, found {len(nodes)}")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno
    lines[start:end] = [REPLACEMENT + "\n"]
    out = f"# {MARKER}\n" + "".join(lines)
    ast.parse(out)
    return out, 1


def _canonical_test_name(value):
    import re, unicodedata
    text = str(value or "").strip()
    if "," in text:
        left, right = text.split(",", 1)
        if left.strip() and right.strip():
            text = f"{right.strip()} {left.strip()}"
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
    return " ".join(text.split())


def _validate_source_files():
    import pandas as pd
    active = Path("learning_data/savant_batter_platoon_2026.csv")
    fallback = Path("learning_data/savant_batter_platoon_2026.last_good.csv")
    path = active if active.exists() else fallback
    if not path.exists():
        raise RuntimeError("No Savant platoon source file found")
    frame = pd.read_csv(path)
    required = {"mlbam_id","player_name","vs_rhp_pa","vs_rhp_so","vs_rhp_k_pct","vs_lhp_pa","vs_lhp_so","vs_lhp_k_pct"}
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
        if float((calc - kp[mask]).abs().max()) > 0.15:
            raise RuntimeError(f"Savant {hand} K% disagrees with SO/PA")

    frame = frame.copy()
    frame["_canon"] = frame["player_name"].map(_canonical_test_name)
    by_name = frame.set_index("_canon", drop=False)
    checks = [
        ("Mike Trout", "rhp", 357, 94, 26.3305),
        ("Zach Neto", "rhp", 407, 132, 32.4324),
        ("Wilyer Abreu", "lhp", 164, 26, 15.8537),
        ("Shohei Ohtani", "rhp", 364, 82, 22.5275),
        ("Francisco Lindor", "lhp", 93, 12, 12.9032),
    ]
    for name, hand, exp_pa, exp_so, exp_k in checks:
        key = _canonical_test_name(name)
        if key not in by_name.index:
            raise RuntimeError(f"Canonical name match failed for {name}: {key}")
        rec = by_name.loc[key]
        if isinstance(rec, pd.DataFrame):
            rec = rec.iloc[-1]
        pa = int(round(float(rec[f"vs_{hand}_pa"])))
        so = int(round(float(rec[f"vs_{hand}_so"])))
        k = 100.0 * so / pa
        if pa != exp_pa or so != exp_so or abs(k-exp_k) > 0.06:
            raise RuntimeError(f"Known split check failed for {name}: {pa}/{so}={k:.4f}")

    # Smoke-test the exact user-visible lineups that previously showed 0/9.
    for lineup in (
        ["Jose Siri","Mike Trout","Vaughn Grissom","Zach Neto","Moisés Ballesteros","Denzer Guzman","Josh Lowe","Tyler Heineman","Adam Frazier"],
        ["Nick Sogard","Ceddanne Rafaela","Wilyer Abreu","Willson Contreras","Adley Rutschman","Caleb Durbin","Jarren Duran","Andruw Monasterio","Mickey Gasper"],
        ["Shohei Ohtani","Freddie Freeman","Andy Pages","Max Muncy","Mookie Betts","Kyle Tucker","Tommy Edman","Teoscar Hernández","Hunter Feduccia"],
    ):
        missing = [n for n in lineup if _canonical_test_name(n) not in by_name.index]
        if missing:
            raise RuntimeError(f"Known lineup canonical matches missing: {missing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    _validate_source_files()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched, count = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_savant_display_v3.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print("Savant batter display V3 CHECK PASS", {"replaced": count})
        return 0
    if patched != original:
        tmp = path.with_suffix(path.suffix + ".savant_display_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(path)
    print("Savant batter display V3 READY", {"replaced": count})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
