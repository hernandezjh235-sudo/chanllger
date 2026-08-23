#!/usr/bin/env python3
"""Challenger Savant refresh v3 — validated batter-vs-pitcher-hand splits.

This wrapper preserves the existing v2 batter profile, pitcher profile and official
Pitch Arsenal refreshes.  It replaces only the platoon builder because Savant's
current grouped-search CSV can return a player roster without the selected PA/K
aggregate columns.

The v3 platoon builder derives PA, SO and K% from Baseball Savant's current-season
Statcast event feed, split by the actual pitcher's throwing hand.  Refreshes are
rejected if the split coverage or aggregate PA totals are suspicious.

No app.py or projection formula is modified here.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import refresh_savant_installer_v2 as prev

base = prev.base
_PREV_VALIDATE_ALL = base.validate_all


def _statcast_event_params(start_day: date, end_day: date):
    # Deliberately omit chk_stats_* flags: type=details returns the event-level
    # Statcast CSV used to reconstruct PA/SO directly instead of depending on
    # Savant's changing grouped aggregate-column response.
    return {
        "all": "true",
        "type": "details",
        "hfGT": "R|",
        "hfSea": f"{base.SEASON}|",
        "player_type": "batter",
        "pitcher_throws": "",
        "batter_stands": "",
        "game_date_gt": start_day.isoformat(),
        "game_date_lt": end_day.isoformat(),
        "group_by": "name",
        "min_pitches": "0",
        "min_results": "0",
        "min_pas": "0",
        "min_abs": "0",
        "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
    }


def _event_split_totals() -> pd.DataFrame:
    # Regular-season filter is also enforced server-side (hfGT=R|).  Starting
    # Mar 1 safely covers the full MLB regular season in any normal schedule.
    start = date(base.SEASON, 3, 1)
    today = date.today()
    if today.year != base.SEASON:
        today = date(base.SEASON, 12, 1)

    pieces = []
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(today, chunk_start + timedelta(days=13))
        raw = base.http_csv(base.SEARCH_URL, _statcast_event_params(chunk_start, chunk_end))
        print(f"platoon event chunk {chunk_start}..{chunk_end}: rows={len(raw)}")

        batter_col = base.first_col(raw, "batter", "batter_id", "mlbam_id")
        hand_col = base.first_col(raw, "p_throws", "pitcher_throws", "pitcher_hand")
        event_col = base.first_col(raw, "events", "event")
        game_col = base.first_col(raw, "game_pk", "game_id")
        ab_col = base.first_col(raw, "at_bat_number", "ab_number", "plate_appearance_number")
        required = {
            "batter": batter_col,
            "pitcher hand": hand_col,
            "events": event_col,
            "game": game_col,
            "at-bat": ab_col,
        }
        missing = [name for name, col in required.items() if col is None]
        if missing:
            raise RuntimeError(
                f"Statcast detail response missing {missing}; columns={list(raw.columns)}"
            )

        x = pd.DataFrame({
            "mlbam_id": pd.to_numeric(raw[batter_col], errors="coerce"),
            "p_throws": raw[hand_col].astype(str).str.upper().str.strip(),
            "events": raw[event_col],
            "game_pk": raw[game_col],
            "at_bat_number": raw[ab_col],
        })
        x = x[
            x["mlbam_id"].notna()
            & x["p_throws"].isin(["R", "L"])
            & x["events"].notna()
            & x["events"].astype(str).str.strip().ne("")
        ].copy()
        if x.empty:
            chunk_start = chunk_end + timedelta(days=1)
            continue

        x["mlbam_id"] = x["mlbam_id"].astype(int)
        # Statcast places the PA result on the terminal event.  De-duplicate by
        # official game + at-bat + batter so a source-format duplication cannot
        # inflate plate appearances.
        x = x.drop_duplicates(["game_pk", "at_bat_number", "mlbam_id"], keep="last")
        event_text = x["events"].astype(str).str.lower().str.strip()
        x["is_so"] = event_text.isin(["strikeout", "strikeout_double_play"])
        agg = (
            x.groupby(["mlbam_id", "p_throws"], as_index=False)
            .agg(PA=("events", "size"), SO=("is_so", "sum"))
        )
        pieces.append(agg)
        chunk_start = chunk_end + timedelta(days=1)

    if not pieces:
        raise RuntimeError("No regular-season Statcast plate appearances returned for platoon refresh")

    totals = pd.concat(pieces, ignore_index=True)
    totals = (
        totals.groupby(["mlbam_id", "p_throws"], as_index=False)[["PA", "SO"]]
        .sum()
    )
    return totals


def _build_platoon() -> pd.DataFrame:
    totals = _event_split_totals()

    roster_raw = base.custom_leaderboard("batter")
    roster = roster_raw[["_player_id", "_player_name"]].drop_duplicates("_player_id").copy()
    roster.columns = ["mlbam_id", "player_name"]
    roster["mlbam_id"] = pd.to_numeric(roster["mlbam_id"], errors="coerce")
    roster = roster[roster["mlbam_id"].notna()].copy()
    roster["mlbam_id"] = roster["mlbam_id"].astype(int)

    r = totals[totals["p_throws"].eq("R")][["mlbam_id", "PA", "SO"]].rename(
        columns={"PA": "vs_rhp_pa", "SO": "vs_rhp_so"}
    )
    l = totals[totals["p_throws"].eq("L")][["mlbam_id", "PA", "SO"]].rename(
        columns={"PA": "vs_lhp_pa", "SO": "vs_lhp_so"}
    )
    out = roster.merge(r, on="mlbam_id", how="outer").merge(l, on="mlbam_id", how="outer")

    # Event data can contain a player that has not yet appeared in the custom
    # leaderboard.  Preserve the row but do not invent a name; validation below
    # ensures normal current-roster coverage remains strong.
    out["player_name"] = out["player_name"].fillna("")
    for c in ("vs_rhp_pa", "vs_rhp_so", "vs_lhp_pa", "vs_lhp_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out["vs_rhp_k_pct"] = out["vs_rhp_so"].div(out["vs_rhp_pa"].replace(0, pd.NA)).mul(100)
    out["vs_lhp_k_pct"] = out["vs_lhp_so"].div(out["vs_lhp_pa"].replace(0, pd.NA)).mul(100)
    out["overall_pa"] = out[["vs_rhp_pa", "vs_lhp_pa"]].sum(axis=1, min_count=1)
    out["overall_so"] = out[["vs_rhp_so", "vs_lhp_so"]].sum(axis=1, min_count=1)
    out["overall_k_pct"] = out["overall_so"].div(out["overall_pa"].replace(0, pd.NA)).mul(100)
    out["team"] = pd.NA
    out["season"] = base.SEASON
    out["source"] = "BASEBALL_SAVANT_CURRENT_SEASON_VS_HAND"
    out["source_timestamp"] = base.now_iso()
    out["refresh_status"] = "CURRENT"

    for c in ("vs_rhp_pa", "vs_rhp_so", "vs_lhp_pa", "vs_lhp_so", "overall_pa", "overall_so"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round().astype("Int64")

    return out[base.PLATOON_COLUMNS].sort_values(["player_name", "mlbam_id"]).reset_index(drop=True)


def _validate_all(platoon, batter, pitcher, mix):
    _PREV_VALIDATE_ALL(platoon, batter, pitcher, mix)

    r_pa = pd.to_numeric(platoon["vs_rhp_pa"], errors="coerce")
    l_pa = pd.to_numeric(platoon["vs_lhp_pa"], errors="coerce")
    r_k = pd.to_numeric(platoon["vs_rhp_k_pct"], errors="coerce")
    l_k = pd.to_numeric(platoon["vs_lhp_k_pct"], errors="coerce")
    overall_pa = pd.to_numeric(platoon["overall_pa"], errors="coerce")
    overall_so = pd.to_numeric(platoon["overall_so"], errors="coerce")

    r_players = int(r_pa.gt(0).sum())
    l_players = int(l_pa.gt(0).sum())
    r_k_players = int(r_k.notna().sum())
    l_k_players = int(l_k.notna().sum())
    split_pa_total = float(overall_pa.fillna(0).sum())
    split_so_total = float(overall_so.fillna(0).sum())
    profile_pa_total = float(pd.to_numeric(batter["PA"], errors="coerce").fillna(0).sum())
    pa_ratio = split_pa_total / profile_pa_total if profile_pa_total > 0 else 0.0
    league_k = split_so_total / split_pa_total if split_pa_total > 0 else 0.0

    print("platoon RHP players with PA:", r_players)
    print("platoon LHP players with PA:", l_players)
    print("platoon RHP K% populated:", r_k_players)
    print("platoon LHP K% populated:", l_k_players)
    print("platoon split PA total:", int(split_pa_total))
    print("batter profile PA total:", int(profile_pa_total))
    print("platoon/profile PA ratio:", round(pa_ratio, 4))
    print("platoon aggregate K rate:", round(league_k, 4))

    if r_players < 450:
        raise RuntimeError(f"platoon: only {r_players} batters have PA vs RHP")
    if l_players < 350:
        raise RuntimeError(f"platoon: only {l_players} batters have PA vs LHP")
    if r_k_players < 450 or l_k_players < 350:
        raise RuntimeError("platoon: K% split coverage is suspiciously incomplete")
    if not (0.90 <= pa_ratio <= 1.10):
        raise RuntimeError(f"platoon: split PA total disagrees with current batter profile (ratio={pa_ratio:.3f})")
    if not (0.15 <= league_k <= 0.35):
        raise RuntimeError(f"platoon: aggregate strikeout rate is implausible ({league_k:.3f})")


base.build_platoon = _build_platoon
base.validate_all = _validate_all

if __name__ == "__main__":
    raise SystemExit(base.main())
