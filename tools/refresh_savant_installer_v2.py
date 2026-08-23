#!/usr/bin/env python3
"""Coverage-preserving live Savant refresh wrapper for Challenger.

The base refresh stays isolated from app.py. This wrapper:
- includes min_abs=0 in Statcast Search requests;
- preserves a broad current batter roster for platoon data;
- uses Baseball Savant's official Pitch Arsenal Stats feed for pitch usage/outcomes.
"""
from __future__ import annotations

import pandas as pd

import refresh_savant_installer as base


_ORIGINAL_SEARCH_PARAMS = base.search_params
_ORIGINAL_BUILD_PLATOON = base.build_platoon
ARSENAL_URL = "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"

PITCH_NAME_TO_CODE = {
    "4-seam fastball": "FF", "four-seam fastball": "FF", "four seam fastball": "FF",
    "sinker": "SI", "cutter": "FC", "changeup": "CH", "change": "CH",
    "split-finger": "FS", "splitter": "FS", "forkball": "FO",
    "curveball": "CU", "curve": "CU", "knuckle curve": "KC",
    "slider": "SL", "sweeper": "ST", "slurve": "SV", "knuckleball": "KN",
    "eephus": "EP", "fastball": "FA", "pitchout": "PO",
}


def _search_params(player_type: str, group_by: str, pitcher_throws: str = ""):
    params = _ORIGINAL_SEARCH_PARAMS(player_type, group_by, pitcher_throws)
    params["min_abs"] = "0"
    return params


def _build_platoon():
    out = _ORIGINAL_BUILD_PLATOON().copy()

    # A player omitted from one handedness query is missing data, not 0 PA.
    for pa_col, so_col in (("vs_rhp_pa", "vs_rhp_so"), ("vs_lhp_pa", "vs_lhp_so")):
        pa = pd.to_numeric(out[pa_col], errors="coerce")
        missing_like = pa.eq(0)
        out.loc[missing_like, pa_col] = pd.NA
        out.loc[missing_like, so_col] = pd.NA

    # Broad current-season batter roster spine keeps low-sample players present.
    roster_raw = base.custom_leaderboard("batter")
    roster = roster_raw[["_player_id", "_player_name"]].drop_duplicates("_player_id").copy()
    roster.columns = ["mlbam_id", "_profile_name"]
    roster["mlbam_id"] = pd.to_numeric(roster["mlbam_id"], errors="coerce")
    roster = roster[roster["mlbam_id"].notna()].copy()
    roster["mlbam_id"] = roster["mlbam_id"].astype(int)

    out["mlbam_id"] = pd.to_numeric(out["mlbam_id"], errors="coerce").astype("Int64")
    out = roster.merge(out, on="mlbam_id", how="outer")
    out["player_name"] = out["player_name"].where(out["player_name"].notna(), out["_profile_name"])
    out = out.drop(columns=["_profile_name"])

    for c in ("vs_rhp_pa", "vs_rhp_so", "vs_lhp_pa", "vs_lhp_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["vs_rhp_k_pct"] = out["vs_rhp_so"].div(out["vs_rhp_pa"].replace(0, pd.NA)).mul(100)
    out["vs_lhp_k_pct"] = out["vs_lhp_so"].div(out["vs_lhp_pa"].replace(0, pd.NA)).mul(100)
    out["overall_pa"] = out[["vs_rhp_pa", "vs_lhp_pa"]].sum(axis=1, min_count=1)
    out["overall_so"] = out[["vs_rhp_so", "vs_lhp_so"]].sum(axis=1, min_count=1)
    out["overall_k_pct"] = out["overall_so"].div(out["overall_pa"].replace(0, pd.NA)).mul(100)
    out["team"] = pd.NA
    out["season"] = base.SEASON
    out["source"] = base.SOURCE
    out["source_timestamp"] = base.now_iso()
    out["refresh_status"] = "CURRENT"
    for c in ("vs_rhp_so", "vs_lhp_so", "overall_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round().astype("Int64")
    return out[base.PLATOON_COLUMNS].sort_values(["player_name", "mlbam_id"]).reset_index(drop=True)


def _pitch_code(value):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if len(text) <= 3 and text.upper() == text:
        return text
    return PITCH_NAME_TO_CODE.get(text.lower(), text)


def _build_pitch_mix(pitcher_profile: pd.DataFrame) -> pd.DataFrame:
    params = {
        "type": "pitcher",
        "year": base.SEASON,
        "team": "",
        "pitchType": "",
        "min": "1",
        "minPitches": "1",
        "sort": "6",
        "sortDir": "desc",
        "csv": "true",
    }
    raw = base.http_csv(ARSENAL_URL, params)
    print("pitch arsenal raw rows:", len(raw))
    print("pitch arsenal columns:", list(raw.columns))

    pid = pd.to_numeric(base.ser(raw, "player_id", "entity_id", "pitcher", "pitcher_id"), errors="coerce")
    pname = base.ser(raw, "player_name", "last_name, first_name", "name", "entity_name").astype(str).str.strip()

    raw_pitch_type = base.ser(raw, "pitch_type", "pitch_type_code", "pitch_code")
    pitch_name = base.ser(raw, "pitch_name", "pitch", "pitch_type_name")
    if raw_pitch_type.isna().all() or raw_pitch_type.astype(str).str.strip().isin(["", "nan", "None"]).all():
        ptype = pitch_name.map(_pitch_code)
    else:
        ptype = raw_pitch_type.map(_pitch_code)

    pitches = pd.to_numeric(base.ser(raw, "pitches", "pitch_count", "number_of_pitches"), errors="coerce")
    usage = base.ser(raw, "pitch_usage", "pitch_percent", "%", "usage", "usage_percent").map(base.as_pct)
    # The official arsenal table exposes both Pitches and usage %. If the percentage
    # column name changes, recompute exact per-pitcher usage from Pitches.
    tmp = pd.DataFrame({"pid": pid, "pitches": pitches})
    totals = tmp.groupby("pid", dropna=False)["pitches"].transform("sum")
    derived_usage = pitches.div(totals.replace(0, pd.NA)).mul(100)
    usage_num = pd.to_numeric(usage, errors="coerce")
    usage = usage_num.where(usage_num.notna(), derived_usage)

    pa = pd.to_numeric(base.ser(raw, "pa", "plate_appearances"), errors="coerce")
    kp = base.ser(raw, "k_percent", "k%", "strikeout_percent").map(base.as_pct)
    so_raw = pd.to_numeric(base.ser(raw, "so", "strikeouts"), errors="coerce")
    so = so_raw.where(so_raw.notna(), (pa * pd.to_numeric(kp, errors="coerce") / 100.0).round())

    out = pd.DataFrame({
        "player_id": pid,
        "player_name": pname,
        "season": base.SEASON,
        "PA": pa,
        "SO": so,
        "K%": kp,
        "BB%": base.ser(raw, "bb_percent", "bb%").map(base.as_pct),
        "Whiff%": base.ser(raw, "whiff_percent", "whiff%", "swing_miss_percent").map(base.as_pct),
        "Swing%": base.ser(raw, "swing_percent", "swing%").map(base.as_pct),
        "xwOBA": pd.to_numeric(base.ser(raw, "xwoba", "est_woba"), errors="coerce"),
        "xBA": pd.to_numeric(base.ser(raw, "xba", "est_ba"), errors="coerce"),
        "xSLG": pd.to_numeric(base.ser(raw, "xslg", "est_slg"), errors="coerce"),
        "Hard-Hit%": base.ser(raw, "hard_hit_percent", "hardhit_percent", "hard_hit%").map(base.as_pct),
        "Barrel%": base.ser(raw, "barrel_batted_rate", "barrel_percent", "barrel%").map(base.as_pct),
        "average_swing_speed": pd.to_numeric(base.ser(raw, "avg_best_speed", "bat_speed", "average_swing_speed"), errors="coerce"),
        "fast_swing_rate": base.ser(raw, "fast_swing_rate", "fast_swing_percent").map(base.as_pct),
        "swords": pd.to_numeric(base.ser(raw, "swords"), errors="coerce"),
        "squared_up_contact": base.ser(raw, "squared_up_contact", "squared_up_percent").map(base.as_pct),
        "pitch_type": ptype,
        "pitch_name": pitch_name,
        "pitch_usage": usage,
        "Pitches": pitches,
        "PutAway%": base.ser(raw, "put_away", "put_away_percent", "putaway_percent", "put_away%").map(base.as_pct),
        "BA": pd.to_numeric(base.ser(raw, "ba"), errors="coerce"),
        "SLG": pd.to_numeric(base.ser(raw, "slg"), errors="coerce"),
        "wOBA": pd.to_numeric(base.ser(raw, "woba"), errors="coerce"),
        "run_value_per_100": pd.to_numeric(base.ser(raw, "run_value_per_100", "rv_per_100", "rv/100"), errors="coerce"),
        "source": "BASEBALL_SAVANT_PITCH_ARSENAL_CURRENT_SEASON",
        "source_timestamp": base.now_iso(),
        "schema_version": "SAVANT_ARSENAL_SCHEMA_V1",
        "refresh_status": "CURRENT",
    })
    out = out[out["player_id"].notna() & out["player_name"].ne("") & out["pitch_type"].astype(str).str.strip().ne("")].copy()
    out["player_id"] = out["player_id"].astype(int)

    # Season profile backfills metrics that the pitch-specific table intentionally
    # does not publish, while keeping pitch-specific arsenal outcomes authoritative.
    prof = pitcher_profile.drop_duplicates("player_id").set_index("player_id")
    for c in ["PA", "SO", "K%", "BB%", "Whiff%", "Swing%", "xwOBA", "xBA", "xSLG",
              "Hard-Hit%", "Barrel%", "average_swing_speed", "fast_swing_rate",
              "swords", "squared_up_contact", "wOBA"]:
        if c in prof.columns:
            fill = out["player_id"].map(prof[c])
            out[c] = out[c].where(out[c].notna(), fill)

    out["SO"] = pd.to_numeric(out["SO"], errors="coerce").round().astype("Int64")
    out = out.drop_duplicates(["player_id", "pitch_type"], keep="first")
    return out[base.MIX_COLUMNS].sort_values(["player_name", "Pitches"], ascending=[True, False]).reset_index(drop=True)


def _validate_all(platoon, batter, pitcher, mix):
    base.validate_schema(
        platoon,
        {"mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct",
         "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"},
        "platoon", 500,
    )
    base.validate_schema(batter, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "batter_profiles", 500)
    base.validate_schema(pitcher, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "pitcher_stats", 650)
    base.validate_schema(mix, {"player_id", "player_name", "season", "pitch_type", "pitch_usage", "Pitches"}, "pitch_mix", 1500)

    mix_pitchers = int(mix["player_id"].nunique())
    mix_types = int(mix["pitch_type"].nunique())
    usage_coverage = float(pd.to_numeric(mix["pitch_usage"], errors="coerce").notna().mean())
    pitches_coverage = float(pd.to_numeric(mix["Pitches"], errors="coerce").notna().mean())
    print("pitch mix unique pitchers:", mix_pitchers)
    print("pitch mix unique pitch types:", mix_types)
    print("pitch usage coverage:", round(usage_coverage, 4))
    print("pitch count coverage:", round(pitches_coverage, 4))

    if platoon["mlbam_id"].nunique() < 500:
        raise RuntimeError("platoon: too few unique MLBAM ids")
    if batter["player_id"].nunique() < 500:
        raise RuntimeError("batter_profiles: too few unique player ids")
    if pitcher["player_id"].nunique() < 650:
        raise RuntimeError("pitcher_stats: too few unique player ids")
    if mix_pitchers < 300 or mix_types < 6:
        raise RuntimeError("pitch_mix: suspicious player/pitch-type coverage")
    if usage_coverage < 0.95:
        raise RuntimeError("pitch_mix: pitch_usage coverage below 95%")
    if pitches_coverage < 0.95:
        raise RuntimeError("pitch_mix: Pitches coverage below 95%")
    for df, name in ((platoon, "platoon"), (batter, "batter"), (pitcher, "pitcher"), (mix, "mix")):
        seasons = set(pd.to_numeric(df["season"], errors="coerce").dropna().astype(int).tolist())
        if base.SEASON not in seasons:
            raise RuntimeError(f"{name}: target season {base.SEASON} missing")


base.search_params = _search_params
base.build_platoon = _build_platoon
base.build_pitch_mix = _build_pitch_mix
base.validate_all = _validate_all

if __name__ == "__main__":
    raise SystemExit(base.main())
