#!/usr/bin/env python3
"""Challenger Savant refresh v7 — complete batter-vs-hand splits.

Uses four-day Statcast detail windows, rejects Savant's 25,000-row cap, and
allows a valid header-only window when no regular-season games occurred in that
specific date range.  All v3 integrity checks remain mandatory before publish.

This changes data refresh only; app.py and projection formulas are untouched.
"""
from __future__ import annotations

import io
import time
from datetime import date, timedelta

import pandas as pd
import requests

import refresh_savant_installer_v3 as v3

base = v3.base


def _detail_csv_allow_empty(params, retries: int = 4) -> pd.DataFrame:
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(base.SEARCH_URL, params=params, headers=base.HEADERS, timeout=(10, 120))
            r.raise_for_status()
            text = str(r.text or "").strip()
            if not text or "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
                raise RuntimeError("Baseball Savant returned HTML/empty response instead of CSV")
            df = pd.read_csv(io.StringIO(text), low_memory=False)
            # A zero-row frame with the normal Statcast schema is valid for a
            # date window with no regular-season games.  Malformed CSV is not.
            if len(df.columns) < 20:
                raise RuntimeError(f"Baseball Savant returned malformed detail CSV: rows={len(df)} cols={len(df.columns)}")
            return df
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"Baseball Savant detail request failed after {retries} tries: {last}")


def _event_split_totals_four_day_allow_empty() -> pd.DataFrame:
    start = date(base.SEASON, 3, 20)
    today = date.today()
    if today.year != base.SEASON:
        today = date(base.SEASON, 12, 1)

    pieces = []
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(today, chunk_start + timedelta(days=3))
        raw = _detail_csv_allow_empty(v3._statcast_event_params(chunk_start, chunk_end))
        print(f"platoon event chunk {chunk_start}..{chunk_end}: rows={len(raw)}")

        if len(raw) == 0:
            chunk_start = chunk_end + timedelta(days=1)
            continue
        if len(raw) >= 25000:
            raise RuntimeError(
                f"Statcast detail chunk hit 25,000-row cap ({chunk_start}..{chunk_end}); refusing truncated platoon data"
            )

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
            pieces.append(
                x.groupby(["mlbam_id", "p_throws"], as_index=False)
                .agg(PA=("events", "size"), SO=("is_so", "sum"))
            )

        chunk_start = chunk_end + timedelta(days=1)

    if not pieces:
        raise RuntimeError("No regular-season Statcast plate appearances returned for platoon refresh")

    totals = pd.concat(pieces, ignore_index=True)
    return totals.groupby(["mlbam_id", "p_throws"], as_index=False)[["PA", "SO"]].sum()


v3._event_split_totals = _event_split_totals_four_day_allow_empty

if __name__ == "__main__":
    raise SystemExit(base.main())
