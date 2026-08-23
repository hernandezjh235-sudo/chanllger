#!/usr/bin/env python3
"""Final-card Savant batter split repair V4 for Challenger.

Display/enrichment only: this patch does not change the K projection formula or
the production K-side decision. It repairs the final Batter-by-Batter card
bridge so Baseball Savant split data is actually attached to the nine lineup
rows and every visible raw K% is recomputed from SO / PA vs today's pitcher hand.

V4 fixes two failure modes seen on the live cards:
- the injected function depended on globals (notably ``unicodedata``), so a
  missing import could silently make all name matches fail and show SAVANT 0/9;
- deploy validation hard-coded old PA/SO totals, so a normal daily Savant refresh
  could fail validation even though the refreshed data was correct.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_SAVANT_BATTER_DISPLAY_V4_2026_08_23"
TARGET = "_v269_savant_shadow_rows"

REPLACEMENT = r"""
def _v269_savant_shadow_rows(lineup_rows, pitcher_hand, expected_bf, board_row=None):
    \"\"\"Authoritative final-card Savant enrichment; no projection-side effect.\"\"\"
    import math as _math
    import re as _re
    import unicodedata as _unicodedata
    from datetime import datetime as _datetime
    from pathlib import Path as _Path
    import pandas as _pd

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
            return out if _math.isfinite(out) else default
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
        text = str(value or "").strip()
        if "," in text:
            left, right = text.split(",", 1)
            if left.strip() and right.strip():
                text = f"{right.strip()} {left.strip()}"
        text = "".join(
            ch for ch in _unicodedata.normalize("NFKD", text)
            if not _unicodedata.combining(ch)
        ).lower()
        text = _re.sub(r"[^a-z0-9 ]+", " ", text)
        text = _re.sub(r"\\b(jr|sr|ii|iii|iv)\\b", " ", text)
        return " ".join(text.split())

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
        for key in (
            "Batter", "Player", "Name", "player_name", "batter_name",
            "batter", "player", "name",
        ):
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    frames = []
    try:
        service = _v269_savant_service()
        platoon = service.load() if hasattr(service, "load") else _pd.DataFrame()
        if isinstance(platoon, _pd.DataFrame) and not platoon.empty:
            frames.append(("LIVE/CACHE", platoon.copy()))
    except Exception:
        pass

    try:
        season = int(_datetime.now().year)
    except Exception:
        season = 2026
    try:
        if isinstance(board_row, dict):
            board_season = _num(
                board_row.get("season", board_row.get("Season", board_row.get("slate_season"))),
                None,
            )
            if board_season is not None and 2000 <= int(board_season) <= 2100:
                season = int(board_season)
    except Exception:
        pass

    for label, path in (
        ("CURRENT", _Path("learning_data") / f"savant_batter_platoon_{season}.csv"),
        ("TARGETED", _Path("learning_data") / f"savant_batter_platoon_{season}.targeted.csv"),
        ("LAST_GOOD", _Path("learning_data") / f"savant_batter_platoon_{season}.last_good.csv"),
    ):
        try:
            if path.exists():
                frame = _pd.read_csv(path)
                if isinstance(frame, _pd.DataFrame) and not frame.empty:
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
            if pa is None or pa <= 0 or so is None or so < 0 or so > pa:
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
    lo = int(_math.floor(bf))
    frac = bf - lo

    def _counts(n):
        return [
            0.0 if n < slot else float(1 + (n - slot) // 9)
            for slot in range(1, 10)
        ]

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
            row["Savant Split Source"] = None
            row["savant_raw_vs_hand_k_pct"] = None
            row["savant_raw_vs_hand_pa"] = None
            row["savant_raw_vs_hand_so"] = None
            row["model_minus_savant_pp"] = None
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
        for key in (
            "Used K%", "K% Used", "Raw_K_Rate", "Split K%", "Season K%",
            "used_k_pct", "model_k_pct_used",
        ):
            value = _num(row.get(key), None)
            if value is not None:
                used = value * 100.0 if abs(value) <= 1.0 else value
                break

        if used is not None:
            delta = round(float(used) - raw_k, 3)
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
        "status": (
            "FULL" if rows and matched == len(rows)
            else "PARTIAL" if matched
            else "UNAVAILABLE"
        ),
        "matched": matched,
        "simple_savant_lineup_k_pct": (
            round(sum(matched_values) / matched, 3) if matched else None
        ),
        "order_weighted_savant_k_pct": (
            round(sum(v * w for v, w in weighted_pairs) / wsum, 3)
            if wsum > 0 else None
        ),
        "top3_savant_k_pct": round(sum(top) / len(top), 3) if top else None,
        "middle3_savant_k_pct": round(sum(middle) / len(middle), 3) if middle else None,
        "bottom3_savant_k_pct": round(sum(bottom) / len(bottom), 3) if bottom else None,
        "display_bridge": "FINAL_CARD_SAVANT_SO_PA_V4",
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
            "savant_display_bridge": "FINAL_CARD_SAVANT_SO_PA_V4",
        })

    return rows, audit
""".strip("\n")


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
    import re
    import unicodedata

    text = str(value or "").strip()
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


def _load_validation_frame():
    import pandas as pd

    candidates = (
        Path("learning_data/savant_batter_platoon_2026.csv"),
        Path("learning_data/savant_batter_platoon_2026.targeted.csv"),
        Path("learning_data/savant_batter_platoon_2026.last_good.csv"),
    )
    for path in candidates:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        required = {
            "mlbam_id", "player_name",
            "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct",
            "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct",
        }
        if isinstance(frame, pd.DataFrame) and not frame.empty and required.issubset(frame.columns):
            return path, frame
    raise RuntimeError("No valid Savant batter platoon source file found")


def _validate_source_files():
    import pandas as pd

    path, frame = _load_validation_frame()
    coverage = {}

    for hand in ("rhp", "lhp"):
        pa = pd.to_numeric(frame[f"vs_{hand}_pa"], errors="coerce")
        so = pd.to_numeric(frame[f"vs_{hand}_so"], errors="coerce")
        kp = pd.to_numeric(frame[f"vs_{hand}_k_pct"], errors="coerce")
        mask = (pa > 0) & (so >= 0) & (so <= pa) & kp.notna()
        coverage[hand] = int(mask.sum())
        if coverage[hand] < 550:
            raise RuntimeError(
                f"Insufficient Savant {hand} coverage in {path}: {coverage[hand]}"
            )

        calc = 100.0 * so[mask] / pa[mask]
        max_err = float((calc - kp[mask]).abs().max())
        if max_err > 0.15:
            raise RuntimeError(
                f"Savant {hand} K% disagrees with SO/PA; max delta={max_err:.4f} pp"
            )

    canon = frame.copy()
    canon["_canon"] = canon["player_name"].map(_canonical_test_name)
    by_name = canon.set_index("_canon", drop=False)

    known_lineups = (
        ("Jose Siri", "Mike Trout", "Vaughn Grissom", "Zach Neto",
         "Moisés Ballesteros", "Denzer Guzman", "Josh Lowe",
         "Tyler Heineman", "Adam Frazier"),
        ("Nick Sogard", "Ceddanne Rafaela", "Wilyer Abreu", "Willson Contreras",
         "Adley Rutschman", "Caleb Durbin", "Jarren Duran",
         "Andruw Monasterio", "Mickey Gasper"),
        ("Shohei Ohtani", "Freddie Freeman", "Andy Pages", "Max Muncy",
         "Mookie Betts", "Kyle Tucker", "Tommy Edman",
         "Teoscar Hernández", "Hunter Feduccia"),
    )

    missing = []
    for lineup in known_lineups:
        for name in lineup:
            if _canonical_test_name(name) not in by_name.index:
                missing.append(name)
    if missing:
        raise RuntimeError(f"Known lineup canonical matches missing: {sorted(set(missing))}")

    return path, frame, coverage


def _validate_replacement_runtime():
    """Execute the injected function itself so missing imports cannot slip by."""
    _, frame, _ = _validate_source_files()

    class _Service:
        def load(self):
            return frame

    ns = {"_v269_savant_service": lambda: _Service()}
    exec(REPLACEMENT, ns)
    fn = ns[TARGET]

    lineup = [
        {"Batter": "Jose Siri", "Used K%": 34.5},
        {"Batter": "Mike Trout", "Used K%": 27.0},
        {"Batter": "Vaughn Grissom", "Used K%": 23.8},
        {"Batter": "Zach Neto", "Used K%": 27.0},
        {"Batter": "Moisés Ballesteros", "Used K%": 20.8},
        {"Batter": "Denzer Guzman", "Used K%": 24.4},
        {"Batter": "Josh Lowe", "Used K%": 33.1},
        {"Batter": "Tyler Heineman", "Used K%": 10.5},
        {"Batter": "Adam Frazier", "Used K%": 19.0},
    ]

    rows, audit = fn(lineup, "RHP", 21.4, {})
    if audit.get("matched") != 9 or audit.get("status") != "FULL":
        raise RuntimeError(f"Runtime final-card match failed: {audit}")

    for row in rows:
        pa = row.get("savant_raw_vs_hand_pa")
        so = row.get("savant_raw_vs_hand_so")
        raw = row.get("savant_raw_vs_hand_k_pct")
        if not pa or so is None or raw is None:
            raise RuntimeError(f"Runtime row missing Savant values: {row}")

        calc = round(100.0 * float(so) / float(pa), 3)
        if abs(float(raw) - calc) > 0.001:
            raise RuntimeError(f"Runtime raw K% math failed: {row}")

        if row.get("model_minus_savant_pp") is None:
            raise RuntimeError(f"Runtime delta missing despite Used K%: {row}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    path, _, coverage = _validate_source_files()
    _validate_replacement_runtime()

    app_path = Path(args.app)
    original = app_path.read_text(encoding="utf-8-sig")
    patched, count = patch_text(original)

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_savant_display_v4.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)

    if args.check_only:
        print(
            "Savant batter display V4 CHECK PASS",
            {
                "replaced": count,
                "source": str(path),
                "rhp_rows": coverage["rhp"],
                "lhp_rows": coverage["lhp"],
            },
        )
        return 0

    if patched != original:
        tmp = app_path.with_suffix(app_path.suffix + ".savant_display_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(app_path)

    print(
        "Savant batter display V4 READY",
        {
            "replaced": count,
            "source": str(path),
            "rhp_rows": coverage["rhp"],
            "lhp_rows": coverage["lhp"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
