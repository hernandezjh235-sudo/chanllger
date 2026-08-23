#!/usr/bin/env python3
"""Challenger Savant refresh v4.

Small reliability wrapper around v3: start the event reconstruction inside the
MLB regular-season window so the first Statcast chunk is never an intentionally
empty March pre-season request. All v3 split-integrity checks remain active.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import refresh_savant_installer_v3 as v3

base = v3.base


def _event_split_totals_regular_season() -> pd.DataFrame:
    # March 20 safely precedes the MLB regular-season opening window while
    # avoiding the empty Mar 1-14 request that Savant correctly returned.
    start = date(base.SEASON, 3, 20)
    today = date.today()
    if today.year != base.SEASON:
        today = date(base.SEASON, 12, 1)

    pieces = []
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(today, chunk_start + timedelta(days=13))
        raw = base.http_csv(base.SEARCH_URL, v3._statcast_event_params(chunk_start, chunk_end))
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
        if not x.empty:
            x["mlbam_id"] = x["mlbam_id"].astype(int)
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
    return totals.groupby(["mlbam_id", "p_throws"], as_index=False)[["PA", "SO"]].sum()


v3._event_split_totals = _event_split_totals_regular_season

if __name__ == "__main__":
    raise SystemExit(base.main())
