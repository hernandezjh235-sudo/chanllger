#!/usr/bin/env python3
"""
Challenger live Baseball Savant installer refresh.

Creates/updates exactly these 10 files in learning_data/:
- savant_batter_platoon_2026.csv
- savant_batter_platoon_2026.last_good.csv
- savant_refresh_manifest.json
- savant_batter_profiles.csv
- savant_batter_profiles.last_good.csv
- savant_pitcher_stats.csv
- savant_pitcher_stats.last_good.csv
- pitch_mix_matchups.csv
- pitch_mix_matchups.last_good.csv
- savant_aux_refresh_manifest.json

Safety:
- App/model code is never touched.
- New data is written to temporary files first.
- Required schema/row-count sanity checks must pass before active/LAST_GOOD replacement.
- Network/schema failure exits nonzero and leaves prior validated files unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

SEASON = max(2026, datetime.now(timezone.utc).year)
SOURCE = "BASEBALL_SAVANT_CURRENT_SEASON"
CUSTOM_URL = "https://baseballsavant.mlb.com/leaderboard/custom"
SEARCH_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OneWayPickz-Challenger-Savant/1.0)",
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://baseballsavant.mlb.com/",
}

PROFILE_COLUMNS = [
    "player_id", "player_name", "season", "PA", "SO", "K%", "BB%",
    "Whiff%", "Swing%", "xwOBA", "xBA", "xSLG", "Hard-Hit%", "Barrel%",
    "average_swing_speed", "fast_swing_rate", "swords",
    "squared_up_contact", "wOBA", "source", "source_timestamp",
    "schema_version", "refresh_status",
]

PLATOON_COLUMNS = [
    "mlbam_id", "player_name", "team", "season",
    "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct",
    "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct",
    "overall_pa", "overall_so", "overall_k_pct",
    "source", "source_timestamp", "refresh_status",
]

MIX_COLUMNS = [
    "player_id", "player_name", "season", "PA", "SO", "K%", "BB%",
    "Whiff%", "Swing%", "xwOBA", "xBA", "xSLG", "Hard-Hit%", "Barrel%",
    "average_swing_speed", "fast_swing_rate", "swords",
    "squared_up_contact", "pitch_type", "pitch_name", "pitch_usage",
    "Pitches", "PutAway%", "BA", "SLG", "wOBA", "run_value_per_100",
    "source", "source_timestamp", "schema_version", "refresh_status",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_num(v: Any):
    try:
        if v is None:
            return None
        s = str(v).strip().replace("%", "").replace(",", "")
        if s == "" or s.lower() in {"nan", "none", "null", "—", "-"}:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def as_pct(v: Any):
    x = as_num(v)
    if x is None:
        return None
    return x * 100.0 if abs(x) <= 1.0 else x


def norm_col(v: Any) -> str:
    return (
        str(v or "").strip().lower()
        .replace("%", "percent")
        .replace("/", "_per_")
        .replace("-", "_")
        .replace(" ", "_")
        .replace(".", "")
        .replace("(", "")
        .replace(")", "")
    )


def first_col(df: pd.DataFrame, *candidates: str):
    cmap = {norm_col(c): c for c in df.columns}
    for c in candidates:
        hit = cmap.get(norm_col(c))
        if hit is not None:
            return hit
    return None


def ser(df: pd.DataFrame, *candidates: str, default=None) -> pd.Series:
    c = first_col(df, *candidates)
    if c is None:
        return pd.Series([default] * len(df), index=df.index)
    return df[c]


def http_csv(url: str, params: dict[str, Any] | None = None, retries: int = 4) -> pd.DataFrame:
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=(10, 120))
            r.raise_for_status()
            text = str(r.text or "").strip()
            if not text or "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
                raise RuntimeError("Baseball Savant returned HTML/empty response instead of CSV")
            df = pd.read_csv(io.StringIO(text), low_memory=False)
            if df.empty or len(df.columns) < 3:
                raise RuntimeError(f"Baseball Savant returned unusable CSV: rows={len(df)} cols={len(df.columns)}")
            return df
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"Baseball Savant request failed after {retries} tries: {last}")


def custom_leaderboard(kind: str) -> pd.DataFrame:
    selections = ",".join([
        "pa", "k_percent", "bb_percent", "woba", "xwoba", "xba", "xslg",
        "sweet_spot_percent", "barrel_batted_rate", "hard_hit_percent",
        "avg_best_speed", "whiff_percent", "swing_percent",
    ])
    frames = []
    for min_filter in ("q", "0"):
        params = {
            "year": SEASON,
            "type": kind,
            "filter": "",
            "min": min_filter,
            "selections": selections,
            "chart": "false",
            "x": "pa",
            "y": "pa",
            "r": "no",
            "chartType": "beeswarm",
            "sort": "xwoba",
            "sortDir": "asc",
            "csv": "true",
        }
        try:
            df = http_csv(CUSTOM_URL, params)
            df = df.copy()
            df["_min_filter"] = min_filter
            frames.append(df)
        except Exception as exc:
            print(f"custom leaderboard {kind}/{min_filter} warning: {exc}", file=sys.stderr)

    if not frames:
        raise RuntimeError(f"No usable Baseball Savant custom leaderboard response for {kind}")

    out = pd.concat(frames, ignore_index=True, sort=False)
    idc = first_col(out, "player_id", "entity_id", "mlb_id", "batter", "pitcher")
    namec = first_col(out, "player_name", "last_name, first_name", "name", "entity_name")
    if idc is None or namec is None:
        raise RuntimeError(f"Custom {kind} leaderboard missing player id/name columns: {list(out.columns)}")

    out["_player_id"] = pd.to_numeric(out[idc], errors="coerce")
    out["_player_name"] = out[namec].astype(str).str.strip()
    out = out[out["_player_id"].notna() & out["_player_name"].ne("")].copy()
    out["_player_id"] = out["_player_id"].astype(int)
    rank = out["_min_filter"].map({"q": 0, "0": 1}).fillna(2)
    out["_min_rank"] = rank
    out = out.sort_values("_min_rank").drop_duplicates("_player_id", keep="first")
    return out.reset_index(drop=True)


def build_profile(kind: str, schema_version: str) -> pd.DataFrame:
    raw = custom_leaderboard(kind)
    ts = now_iso()
    pa = pd.to_numeric(ser(raw, "pa", "bf"), errors="coerce")
    kp = ser(raw, "k_percent", "k%").map(as_pct)
    so_raw = pd.to_numeric(ser(raw, "so", "strikeouts"), errors="coerce")
    so = so_raw.where(so_raw.notna(), (pa * pd.to_numeric(kp, errors="coerce") / 100.0).round())

    out = pd.DataFrame({
        "player_id": raw["_player_id"].astype(int),
        "player_name": raw["_player_name"],
        "season": SEASON,
        "PA": pa,
        "SO": so,
        "K%": kp,
        "BB%": ser(raw, "bb_percent", "bb%").map(as_pct),
        "Whiff%": ser(raw, "whiff_percent", "swing_miss_percent", "whiff%").map(as_pct),
        "Swing%": ser(raw, "swing_percent", "swing%").map(as_pct),
        "xwOBA": pd.to_numeric(ser(raw, "xwoba", "est_woba"), errors="coerce"),
        "xBA": pd.to_numeric(ser(raw, "xba", "est_ba"), errors="coerce"),
        "xSLG": pd.to_numeric(ser(raw, "xslg", "est_slg"), errors="coerce"),
        "Hard-Hit%": ser(raw, "hard_hit_percent", "hardhit_percent").map(as_pct),
        "Barrel%": ser(raw, "barrel_batted_rate", "barrels_per_bbe_percent", "barrel_percent").map(as_pct),
        "average_swing_speed": pd.to_numeric(ser(raw, "avg_best_speed", "bat_speed", "average_swing_speed"), errors="coerce"),
        "fast_swing_rate": ser(raw, "fast_swing_rate", "fast_swing_percent").map(as_pct),
        "swords": pd.to_numeric(ser(raw, "swords"), errors="coerce"),
        "squared_up_contact": ser(raw, "squared_up_contact", "squared_up_percent").map(as_pct),
        "wOBA": pd.to_numeric(ser(raw, "woba"), errors="coerce"),
        "source": SOURCE,
        "source_timestamp": ts,
        "schema_version": schema_version,
        "refresh_status": "CURRENT",
    })
    out = out[out["PA"].notna()].drop_duplicates("player_id", keep="first").copy()
    out["SO"] = pd.to_numeric(out["SO"], errors="coerce").round().astype("Int64")
    return out[PROFILE_COLUMNS].sort_values(["player_name", "player_id"]).reset_index(drop=True)


def search_params(player_type: str, group_by: str, pitcher_throws: str = "") -> dict[str, Any]:
    return {
        "all": "true",
        "type": "details",
        "hfGT": "R|",
        "hfSea": f"{SEASON}|",
        "player_type": player_type,
        "pitcher_throws": pitcher_throws,
        "batter_stands": "",
        "group_by": group_by,
        "min_pitches": "0",
        "min_results": "0",
        "min_pas": "0",
        "sort_col": "pitches",
        "sort_order": "desc",
        "chk_stats_pa": "on",
        "chk_stats_so": "on",
        "chk_stats_strikeouts": "on",
        "chk_stats_k_percent": "on",
        "chk_stats_bb_percent": "on",
        "chk_stats_ba": "on",
        "chk_stats_slg": "on",
        "chk_stats_woba": "on",
        "chk_stats_xba": "on",
        "chk_stats_xslg": "on",
        "chk_stats_xwoba": "on",
        "chk_stats_swing_miss_percent": "on",
        "chk_stats_swing_percent": "on",
        "chk_stats_hardhit_percent": "on",
        "chk_stats_barrels_per_bbe_percent": "on",
        "chk_stats_sweetspot_speed_mph": "on",
        "chk_stats_bat_speed": "on",
        "chk_stats_fast_swing_rate": "on",
        "chk_stats_swords": "on",
        "chk_stats_squared_up_contact": "on",
        "chk_stats_pitch_percent": "on",
        "chk_stats_delev_pitcher_run_value_per_100": "on",
    }


def player_id_from(df: pd.DataFrame, player_type: str) -> pd.Series:
    return pd.to_numeric(ser(df, "player_id", "entity_id", "mlbam_id", "batter" if player_type == "batter" else "pitcher"), errors="coerce")


def player_name_from(df: pd.DataFrame) -> pd.Series:
    return ser(df, "player_name", "last_name, first_name", "name", "entity_name").astype(str).str.strip()


def build_platoon() -> pd.DataFrame:
    def one_side(hand: str, prefix: str) -> pd.DataFrame:
        raw = http_csv(SEARCH_URL, search_params("batter", "name", pitcher_throws=hand))
        pid = player_id_from(raw, "batter")
        name = player_name_from(raw)
        pa = pd.to_numeric(ser(raw, "pa"), errors="coerce")
        kp = ser(raw, "k_percent", "k%").map(as_pct)
        so_raw = pd.to_numeric(ser(raw, "so", "strikeouts"), errors="coerce")
        so = so_raw.where(so_raw.notna(), (pa * pd.to_numeric(kp, errors="coerce") / 100.0).round())
        out = pd.DataFrame({"mlbam_id": pid, "player_name": name, f"{prefix}_pa": pa, f"{prefix}_so": so})
        out = out[out["mlbam_id"].notna() & out["player_name"].ne("")].copy()
        out["mlbam_id"] = out["mlbam_id"].astype(int)
        return out.drop_duplicates("mlbam_id", keep="first")

    vs_r = one_side("R", "vs_rhp")
    vs_l = one_side("L", "vs_lhp")
    out = vs_r.merge(vs_l, on="mlbam_id", how="outer", suffixes=("_r", "_l"))
    out["player_name"] = out["player_name_r"].where(out["player_name_r"].notna(), out["player_name_l"])
    for c in ("vs_rhp_pa", "vs_rhp_so", "vs_lhp_pa", "vs_lhp_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["vs_rhp_k_pct"] = out["vs_rhp_so"].div(out["vs_rhp_pa"].replace(0, pd.NA)).mul(100)
    out["vs_lhp_k_pct"] = out["vs_lhp_so"].div(out["vs_lhp_pa"].replace(0, pd.NA)).mul(100)
    out["overall_pa"] = out["vs_rhp_pa"] + out["vs_lhp_pa"]
    out["overall_so"] = out["vs_rhp_so"] + out["vs_lhp_so"]
    out["overall_k_pct"] = out["overall_so"].div(out["overall_pa"].replace(0, pd.NA)).mul(100)
    out["team"] = pd.NA
    out["season"] = SEASON
    out["source"] = SOURCE
    out["source_timestamp"] = now_iso()
    out["refresh_status"] = "CURRENT"
    for c in ("vs_rhp_so", "vs_lhp_so", "overall_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round().astype("Int64")
    return out[PLATOON_COLUMNS].sort_values(["player_name", "mlbam_id"]).reset_index(drop=True)


def build_pitch_mix(pitcher_profile: pd.DataFrame) -> pd.DataFrame:
    raw = http_csv(SEARCH_URL, search_params("pitcher", "pitch-type"))
    ts = now_iso()
    pid = player_id_from(raw, "pitcher")
    pname = player_name_from(raw)
    ptype = ser(raw, "pitch_type", "pitch_type_code", "pitch_code").astype(str).str.strip()
    pitches = pd.to_numeric(ser(raw, "pitches", "pitch_count", "n"), errors="coerce")
    usage = ser(raw, "pitch_percent", "pitch_usage", "pitch_usage_percent").map(as_pct)
    tmp = pd.DataFrame({"pid": pid, "pitches": pitches})
    totals = tmp.groupby("pid", dropna=False)["pitches"].transform("sum")
    derived_usage = pitches.div(totals.replace(0, pd.NA)).mul(100)
    usage = pd.to_numeric(usage, errors="coerce").where(pd.to_numeric(usage, errors="coerce").notna(), derived_usage)
    pa = pd.to_numeric(ser(raw, "pa"), errors="coerce")
    kp = ser(raw, "k_percent", "k%").map(as_pct)
    so_raw = pd.to_numeric(ser(raw, "so", "strikeouts"), errors="coerce")
    so = so_raw.where(so_raw.notna(), (pa * pd.to_numeric(kp, errors="coerce") / 100.0).round())

    out = pd.DataFrame({
        "player_id": pid,
        "player_name": pname,
        "season": SEASON,
        "PA": pa,
        "SO": so,
        "K%": kp,
        "BB%": ser(raw, "bb_percent", "bb%").map(as_pct),
        "Whiff%": ser(raw, "swing_miss_percent", "whiff_percent", "whiff%").map(as_pct),
        "Swing%": ser(raw, "swing_percent", "swing%").map(as_pct),
        "xwOBA": pd.to_numeric(ser(raw, "xwoba", "est_woba"), errors="coerce"),
        "xBA": pd.to_numeric(ser(raw, "xba", "est_ba"), errors="coerce"),
        "xSLG": pd.to_numeric(ser(raw, "xslg", "est_slg"), errors="coerce"),
        "Hard-Hit%": ser(raw, "hardhit_percent", "hard_hit_percent").map(as_pct),
        "Barrel%": ser(raw, "barrels_per_bbe_percent", "barrel_batted_rate", "barrel_percent").map(as_pct),
        "average_swing_speed": pd.to_numeric(ser(raw, "bat_speed", "sweetspot_speed_mph", "avg_best_speed", "average_swing_speed"), errors="coerce"),
        "fast_swing_rate": ser(raw, "fast_swing_rate", "fast_swing_percent").map(as_pct),
        "swords": pd.to_numeric(ser(raw, "swords"), errors="coerce"),
        "squared_up_contact": ser(raw, "squared_up_contact", "squared_up_percent").map(as_pct),
        "pitch_type": ptype,
        "pitch_name": ser(raw, "pitch_name"),
        "pitch_usage": usage,
        "Pitches": pitches,
        "PutAway%": ser(raw, "put_away", "put_away_percent", "putaway_percent").map(as_pct),
        "BA": pd.to_numeric(ser(raw, "ba"), errors="coerce"),
        "SLG": pd.to_numeric(ser(raw, "slg"), errors="coerce"),
        "wOBA": pd.to_numeric(ser(raw, "woba"), errors="coerce"),
        "run_value_per_100": pd.to_numeric(ser(raw, "delev_pitcher_run_value_per_100", "run_value_per_100"), errors="coerce"),
        "source": SOURCE,
        "source_timestamp": ts,
        "schema_version": "SAVANT_ARSENAL_SCHEMA_V1",
        "refresh_status": "CURRENT",
    })
    out = out[out["player_id"].notna() & out["player_name"].ne("") & out["pitch_type"].ne("")].copy()
    out["player_id"] = out["player_id"].astype(int)
    prof = pitcher_profile.drop_duplicates("player_id").set_index("player_id")
    for c in ["PA", "SO", "K%", "BB%", "Whiff%", "Swing%", "xwOBA", "xBA", "xSLG", "Hard-Hit%", "Barrel%", "average_swing_speed", "fast_swing_rate", "swords", "squared_up_contact", "wOBA"]:
        if c in prof.columns:
            fill = out["player_id"].map(prof[c])
            out[c] = out[c].where(out[c].notna(), fill)
    out["SO"] = pd.to_numeric(out["SO"], errors="coerce").round().astype("Int64")
    out = out.drop_duplicates(["player_id", "pitch_type"], keep="first")
    return out[MIX_COLUMNS].sort_values(["player_name", "Pitches"], ascending=[True, False]).reset_index(drop=True)


def validate_schema(df: pd.DataFrame, required: set[str], name: str, min_rows: int) -> None:
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"{name}: missing required columns {sorted(missing)}")
    if len(df) < min_rows:
        raise RuntimeError(f"{name}: only {len(df)} rows; minimum safe count is {min_rows}")
    if df.empty:
        raise RuntimeError(f"{name}: empty output")


def validate_all(platoon: pd.DataFrame, batter: pd.DataFrame, pitcher: pd.DataFrame, mix: pd.DataFrame) -> None:
    validate_schema(platoon, {"mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct", "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"}, "platoon", 500)
    validate_schema(batter, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "batter_profiles", 500)
    validate_schema(pitcher, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "pitcher_stats", 650)
    validate_schema(mix, {"player_id", "player_name", "season", "pitch_type", "pitch_usage", "Pitches"}, "pitch_mix", 2500)
    if platoon["mlbam_id"].nunique() < 500:
        raise RuntimeError("platoon: too few unique MLBAM ids")
    if batter["player_id"].nunique() < 500:
        raise RuntimeError("batter_profiles: too few unique player ids")
    if pitcher["player_id"].nunique() < 650:
        raise RuntimeError("pitcher_stats: too few unique player ids")
    if mix["player_id"].nunique() < 500 or mix["pitch_type"].nunique() < 6:
        raise RuntimeError("pitch_mix: suspicious player/pitch-type coverage")
    if pd.to_numeric(mix["pitch_usage"], errors="coerce").notna().mean() < 0.80:
        raise RuntimeError("pitch_mix: pitch_usage coverage below 80%")
    for df, name in ((platoon, "platoon"), (batter, "batter"), (pitcher, "pitcher"), (mix, "mix")):
        seasons = set(pd.to_numeric(df["season"], errors="coerce").dropna().astype(int).tolist())
        if SEASON not in seasons:
            raise RuntimeError(f"{name}: target season {SEASON} missing")


def safe_replace_dataframe(df: pd.DataFrame, active: Path, last_good: Path) -> None:
    active.parent.mkdir(parents=True, exist_ok=True)
    tmp = active.with_name(active.name + ".new")
    df.to_csv(tmp, index=False)
    if tmp.stat().st_size < 100:
        raise RuntimeError(f"temporary output unexpectedly small: {tmp}")
    os.replace(tmp, active)
    shutil.copy2(active, last_good)


def write_json_atomic(path: Path, obj: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def query_signature(label: str) -> str:
    return hashlib.sha256(f"{label}|season={SEASON}|baseballsavant|v2".encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="learning_data", help="Destination directory; default learning_data")
    args = ap.parse_args()
    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    print(f"Challenger Savant refresh start: {started}")
    print(f"Season: {SEASON}")
    print(f"Destination: {outdir}")

    platoon = build_platoon()
    print("platoon rows:", len(platoon))
    batter = build_profile("batter", "SAVANT_BATTER_PROFILE_SCHEMA_V1")
    print("batter profile rows:", len(batter))
    pitcher = build_profile("pitcher", "SAVANT_PITCHER_SCHEMA_V1")
    print("pitcher profile rows:", len(pitcher))
    mix = build_pitch_mix(pitcher)
    print("pitch mix rows:", len(mix))
    validate_all(platoon, batter, pitcher, mix)
    print("All Savant schema/coverage checks passed.")

    safe_replace_dataframe(platoon, outdir / f"savant_batter_platoon_{SEASON}.csv", outdir / f"savant_batter_platoon_{SEASON}.last_good.csv")
    safe_replace_dataframe(batter, outdir / "savant_batter_profiles.csv", outdir / "savant_batter_profiles.last_good.csv")
    safe_replace_dataframe(pitcher, outdir / "savant_pitcher_stats.csv", outdir / "savant_pitcher_stats.last_good.csv")
    safe_replace_dataframe(mix, outdir / "pitch_mix_matchups.csv", outdir / "pitch_mix_matchups.last_good.csv")

    done = now_iso()
    write_json_atomic(outdir / "savant_refresh_manifest.json", {
        "active_path": f"learning_data/savant_batter_platoon_{SEASON}.csv",
        "dataset": f"savant_batter_platoon_{SEASON}.csv",
        "error": "",
        "last_good_path": f"learning_data/savant_batter_platoon_{SEASON}.last_good.csv",
        "last_success_at": done,
        "query_signature": query_signature("savant_batter_platoon"),
        "refresh_completed_at": done,
        "refresh_started_at": started,
        "row_count": int(len(platoon)),
        "schema_version": "SAVANT_BATTER_PLATOON_SCHEMA_V1",
        "season": SEASON,
        "status": "SUCCESS",
    })
    write_json_atomic(outdir / "savant_aux_refresh_manifest.json", {
        "datasets": {
            "batter_profiles": {"error": "", "row_count": int(len(batter)), "status": "SUCCESS"},
            "pitch_mix_matchups": {"error": "", "row_count": int(len(mix)), "status": "SUCCESS"},
            "pitcher_stats": {"error": "", "row_count": int(len(pitcher)), "status": "SUCCESS"},
        },
        "last_success_at": done,
        "refresh_completed_at": done,
        "refresh_started_at": started,
        "schema_version": "SAVANT_AUX_MANIFEST_SCHEMA_V1",
        "season": SEASON,
        "status": "SUCCESS",
    })
    print("SUCCESS — published 10 validated Challenger installer files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
