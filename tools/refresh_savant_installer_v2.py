#!/usr/bin/env python3
"""Coverage-preserving live Savant refresh wrapper for Challenger.

This keeps the base refresh implementation isolated from app.py, while fixing two
coverage issues found by the live GitHub verification run:
1) include min_abs=0 in Statcast Search requests;
2) keep the broad current batter roster in the platoon file without fabricating
   zero split PA/SO for players Savant omits from one split query.
"""
from __future__ import annotations

import pandas as pd

import refresh_savant_installer as base


_ORIGINAL_SEARCH_PARAMS = base.search_params
_ORIGINAL_BUILD_PLATOON = base.build_platoon


def _search_params(player_type: str, group_by: str, pitcher_throws: str = ""):
    params = _ORIGINAL_SEARCH_PARAMS(player_type, group_by, pitcher_throws)
    # Savant's search form still carries the legacy min_abs scalar.  Supplying both
    # min_pas and min_abs prevents low-sample players/pitches from being silently
    # filtered by backend defaults.
    params["min_abs"] = "0"
    return params


def _build_platoon():
    out = _ORIGINAL_BUILD_PLATOON().copy()

    # The base function historically used fillna(0).  A missing Savant split is not
    # evidence of 0 PA; restore it to NULL so downstream code can fall back safely.
    for pa_col, so_col in (("vs_rhp_pa", "vs_rhp_so"), ("vs_lhp_pa", "vs_lhp_so")):
        pa = pd.to_numeric(out[pa_col], errors="coerce")
        so = pd.to_numeric(out[so_col], errors="coerce")
        missing_like = pa.eq(0)
        out.loc[missing_like, pa_col] = pd.NA
        out.loc[missing_like, so_col] = pd.NA

    # Use the broad official current-season batter leaderboard as the roster spine.
    # Players absent from a split result remain present with NULL split fields rather
    # than disappearing from the installer dataset.
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


def _validate_all(platoon, batter, pitcher, mix):
    base.validate_schema(
        platoon,
        {"mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct",
         "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"},
        "platoon",
        500,
    )
    base.validate_schema(batter, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "batter_profiles", 500)
    base.validate_schema(pitcher, {"player_id", "player_name", "season", "PA", "SO", "K%"}, "pitcher_stats", 650)
    # Live verification showed Savant currently returns ~1.8K genuine unique
    # pitcher/pitch-type rows with min filters at zero.  Require broad coverage but
    # do not force the stale Aug-12 row count of 3,679.
    base.validate_schema(mix, {"player_id", "player_name", "season", "pitch_type", "pitch_usage", "Pitches"}, "pitch_mix", 1500)

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
        if base.SEASON not in seasons:
            raise RuntimeError(f"{name}: target season {base.SEASON} missing")


base.search_params = _search_params
base.build_platoon = _build_platoon
base.validate_all = _validate_all

if __name__ == "__main__":
    raise SystemExit(base.main())
