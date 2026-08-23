#!/usr/bin/env python3
"""Moneyline-only automatic rain/delay weather overlay for Challenger.

Adds a live Open-Meteo weather window around first pitch and exposes a
qualitative rain/delay risk without changing the canonical Phase 2.1/2.2
Moneyline winner. The overlay is deliberately support/risk-only until forward
results justify any stronger probability or side adjustment.

No K projection, BF/IP, hitter projection, grading, learning, or non-Moneyline
formula is modified.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_ML_WEATHER_DELAY_V1_2026_08_23"
BINDING = "ml_build_board = _impl_ml_build_board_21"
PUBLIC_MARKER = "# Public-path rebinding. K/Challenger and every non-Moneyline engine remain untouched."

BLOCK = r'''
# CHALLENGER_ML_WEATHER_DELAY_V1_2026_08_23
# Moneyline-only weather risk overlay. Canonical Phase 2.2 side is preserved.
ML_WEATHER_DELAY_VERSION = "ML_WEATHER_DELAY_V1_2026_08_23"


def _mlwd_num(value, default=None):
    try:
        if value is None or value == "":
            return default
        out = float(str(value).replace("%", "").replace(",", "").strip())
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _mlwd_team(value):
    try:
        return ml_canonical_abbr(value) if "ml_canonical_abbr" in globals() else str(value or "").strip().upper()
    except Exception:
        return str(value or "").strip().upper()


def _mlwd_first(mapping, keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _mlwd_game_meta(board, row):
    row = row if isinstance(row, dict) else {}
    away = _mlwd_team(_mlwd_first(row, ["Away", "Away Team", "away_team", "AwayTeam"], ""))
    home = _mlwd_team(_mlwd_first(row, ["Home", "Home Team", "home_team", "HomeTeam"], ""))

    fallback = ML_PHASE22_BALLPARKS.get(home, ("Unknown venue", "", "Unknown")) if "ML_PHASE22_BALLPARKS" in globals() else ("Unknown venue", "", "Unknown")
    venue = str(_mlwd_first(row, ["Ballpark", "Park", "Venue", "venue"], fallback[0]) or fallback[0])
    roof = str(_mlwd_first(row, ["ML Real Roof", "Roof", "Ballpark Roof", "roof"], fallback[2]) or fallback[2])
    game_time = _mlwd_first(row, ["game_time", "Game Time", "Game Date Time", "Start Time", "start_time", "Commence Time", "commence_time"], None)

    if game_time in (None, "") or venue.lower() == "unknown venue":
        for p in board or []:
            if not isinstance(p, dict):
                continue
            team = _mlwd_team(_mlwd_first(p, ["team", "Team", "pitcher_team", "Pitcher Team"], ""))
            opp = _mlwd_team(_mlwd_first(p, ["opponent", "Opponent", "opp", "Opp"], ""))
            if away and home and {team, opp} != {away, home}:
                continue
            if game_time in (None, ""):
                game_time = _mlwd_first(p, ["game_time", "Game Time", "start_time", "Start Time", "commence_time", "Commence Time"], None)
            if not venue or venue.lower() == "unknown venue":
                venue = str(_mlwd_first(p, ["venue", "Venue", "Park", "Ballpark"], fallback[0]) or fallback[0])
            if roof in ("", "Unknown"):
                roof = str(_mlwd_first(p, ["Roof", "roof"], fallback[2]) or fallback[2])
            if game_time not in (None, "") and venue and venue.lower() != "unknown venue":
                break
    return away, home, venue, roof, game_time


def _mlwd_hour_key(game_time):
    try:
        if "parse_game_hour_pt" in globals():
            key = parse_game_hour_pt(game_time)
            if key:
                return key
    except Exception:
        pass
    try:
        s = str(game_time or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if getattr(dt, "tzinfo", None) is not None and "pytz" in globals() and pytz:
            dt = dt.astimezone(pytz.timezone("America/Los_Angeles"))
        return dt.strftime("%Y-%m-%dT%H:00")
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _mlwd_forecast_window(lat, lon, start_date, end_date):
    try:
        params = {
            "latitude": float(lat),
            "longitude": float(lon),
            "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,rain,showers,weather_code,wind_speed_10m,wind_gusts_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "America/Los_Angeles",
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        if "safe_get_json" in globals():
            data = safe_get_json("https://api.open-meteo.com/v1/forecast", params=params, timeout=12) or {}
        else:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mlwd_risk(board, row):
    away, home, venue, roof, game_time = _mlwd_game_meta(board, row)
    result = {
        "source": "UNAVAILABLE",
        "tier": "UNAVAILABLE",
        "score": None,
        "peak_precip_prob": None,
        "peak_precip_mm": None,
        "peak_rain_mm": None,
        "peak_showers_mm": None,
        "wind_mph": None,
        "gust_mph": None,
        "temp_f": None,
        "humidity": None,
        "window": "",
        "venue": venue,
        "roof": roof,
        "game_time": game_time,
        "note": "Weather window unavailable",
    }

    meta = venue_weather_meta(venue) if "venue_weather_meta" in globals() else None
    if not meta:
        return result
    lat, lon, meta_indoor = meta

    roof_text = str(roof or "").upper()
    explicitly_open = "OPEN" in roof_text and "CLOSED" not in roof_text
    roof_capable = bool(meta_indoor) or any(token in roof_text for token in ["INDOOR", "CLOSED", "RETRACTABLE", "DOME"])
    roof_protected = roof_capable and not explicitly_open

    hour_key = _mlwd_hour_key(game_time)
    if not hour_key:
        if roof_protected:
            result.update({"source": "ROOF", "tier": "ROOF_PROTECTED", "score": 0.0, "note": "Roof/indoor park; delay risk protected"})
        return result

    try:
        center = datetime.fromisoformat(hour_key)
    except Exception:
        return result
    start = center - timedelta(hours=1)
    end = center + timedelta(hours=4)
    data = _mlwd_forecast_window(lat, lon, start.date().isoformat(), end.date().isoformat())
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict):
        if roof_protected:
            result.update({"source": "ROOF", "tier": "ROOF_PROTECTED", "score": 0.0, "note": "Roof/indoor park; delay risk protected"})
        return result

    times = hourly.get("time") or []
    indices = []
    parsed_times = []
    for i, raw in enumerate(times):
        try:
            dt = datetime.fromisoformat(str(raw))
        except Exception:
            continue
        if start <= dt <= end:
            indices.append(i)
            parsed_times.append(dt)
    if not indices:
        return result

    def vals(key):
        arr = hourly.get(key) or []
        out = []
        for i in indices:
            if i >= len(arr):
                continue
            v = _mlwd_num(arr[i], None)
            if v is not None:
                out.append(v)
        return out

    def nearest(key):
        arr = hourly.get(key) or []
        pairs = []
        for i, dt in zip(indices, parsed_times):
            if i >= len(arr):
                continue
            v = _mlwd_num(arr[i], None)
            if v is not None:
                pairs.append((abs((dt - center).total_seconds()), v))
        return min(pairs, key=lambda x: x[0])[1] if pairs else None

    probs = vals("precipitation_probability")
    precip = vals("precipitation")
    rain = vals("rain")
    showers = vals("showers")
    gusts = vals("wind_gusts_10m")
    wind = vals("wind_speed_10m")
    codes = vals("weather_code")

    peak_prob = max(probs) if probs else 0.0
    peak_precip = max(precip) if precip else 0.0
    peak_rain = max(rain) if rain else 0.0
    peak_showers = max(showers) if showers else 0.0
    peak_gust = max(gusts) if gusts else None
    peak_wind = max(wind) if wind else None
    thunder = any(int(round(c)) in {95, 96, 99} for c in codes)
    heavy_code = any(int(round(c)) in {65, 67, 82} for c in codes)

    # Risk index: weather uncertainty / delay concern, NOT a literal delay probability.
    score = 0.65 * float(peak_prob)
    score += min(18.0, float(max(peak_precip, peak_rain, peak_showers)) * 10.0)
    if thunder:
        score += 24.0
    elif heavy_code:
        score += 12.0
    if peak_gust is not None and peak_gust >= 30.0:
        score += min(8.0, (peak_gust - 25.0) * 0.5)
    score = max(0.0, min(100.0, score))

    if roof_protected:
        tier = "ROOF_PROTECTED"
        applied_score = 0.0
        note = f"Outside weather {peak_prob:.0f}% precip peak; roof/indoor protection"
    else:
        applied_score = score
        if score >= 75.0:
            tier = "SEVERE"
        elif score >= 55.0:
            tier = "HIGH"
        elif score >= 30.0:
            tier = "MEDIUM"
        else:
            tier = "LOW"
        note = f"{tier} rain/delay risk index · peak precip {peak_prob:.0f}%"
        if thunder:
            note += " · thunderstorm signal"

    result.update({
        "source": "OPEN_METEO_FIRST_PITCH_WINDOW",
        "tier": tier,
        "score": round(float(applied_score), 1),
        "raw_score": round(float(score), 1),
        "peak_precip_prob": round(float(peak_prob), 1),
        "peak_precip_mm": round(float(peak_precip), 2),
        "peak_rain_mm": round(float(peak_rain), 2),
        "peak_showers_mm": round(float(peak_showers), 2),
        "wind_mph": None if peak_wind is None else round(float(peak_wind), 1),
        "gust_mph": None if peak_gust is None else round(float(peak_gust), 1),
        "temp_f": nearest("temperature_2m"),
        "humidity": nearest("relative_humidity_2m"),
        "window": f"{start.strftime('%m-%d %H:%M')} to {end.strftime('%H:%M')} PT",
        "note": note,
    })
    return result


def _mlwd_append_reason(existing, reason):
    text = str(existing or "").strip()
    if not reason:
        return text
    if not text:
        return reason
    if reason.lower() in text.lower():
        return text
    return f"{text}; {reason}"


def _impl_ml_build_board_22(board):
    """Phase 2.2 + automatic rain/delay window. Side preserving."""
    df = _impl_ml_build_board_21(board)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    for ridx, rr in out.iterrows():
        row = rr.to_dict()
        wx = _mlwd_risk(board, row)
        tier = str(wx.get("tier") or "UNAVAILABLE")
        existing_summary = str(row.get("ML Weather Summary") or "").strip()
        if tier == "ROOF_PROTECTED":
            summary = wx.get("note") or "Roof/indoor weather protected"
        elif tier != "UNAVAILABLE":
            pieces = [wx.get("note")]
            if wx.get("temp_f") is not None:
                pieces.append(f"{float(wx['temp_f']):.0f}°F")
            if wx.get("wind_mph") is not None:
                pieces.append(f"wind {float(wx['wind_mph']):.0f} mph")
            if wx.get("gust_mph") is not None and float(wx.get("gust_mph") or 0) >= 20:
                pieces.append(f"gust {float(wx['gust_mph']):.0f} mph")
            summary = " · ".join([str(x) for x in pieces if x not in (None, "")])
        else:
            summary = existing_summary or "Weather unavailable"

        out.at[ridx, "ML Weather Summary"] = summary
        out.at[ridx, "ML Rain Delay Risk"] = tier
        out.at[ridx, "ML Rain Delay Risk Score"] = wx.get("score")
        out.at[ridx, "ML Weather Source"] = wx.get("source")
        out.at[ridx, "ML Weather Window"] = wx.get("window")
        out.at[ridx, "ML Weather Precip Peak %"] = wx.get("peak_precip_prob")
        out.at[ridx, "ML Weather Precip Peak MM"] = wx.get("peak_precip_mm")
        out.at[ridx, "ML Weather Gust MPH"] = wx.get("gust_mph")
        out.at[ridx, "ML Weather Roof Read"] = wx.get("roof")
        out.at[ridx, "ML Weather Version"] = ML_WEATHER_DELAY_VERSION

        # Weather is a playability warning only in V1. It never flips the canonical winner.
        if tier in {"HIGH", "SEVERE"}:
            reason = f"{tier} RAIN/DELAY RISK"
            if wx.get("peak_precip_prob") is not None:
                reason += f" ({float(wx['peak_precip_prob']):.0f}% peak precip)"
            out.at[ridx, "ML Risk Reasons"] = _mlwd_append_reason(row.get("ML Risk Reasons"), reason)
            out.at[ridx, "ML Weather Playability"] = "PASS / WAIT FOR WEATHER" if tier == "SEVERE" else "DOWNGRADE / RECHECK"
        elif tier == "MEDIUM":
            out.at[ridx, "ML Risk Reasons"] = _mlwd_append_reason(row.get("ML Risk Reasons"), "MEDIUM RAIN/DELAY WATCH")
            out.at[ridx, "ML Weather Playability"] = "WATCH"
        elif tier == "ROOF_PROTECTED":
            out.at[ridx, "ML Weather Playability"] = "ROOF PROTECTED"
        elif tier == "LOW":
            out.at[ridx, "ML Weather Playability"] = "CLEAR"
        else:
            out.at[ridx, "ML Weather Playability"] = "UNAVAILABLE"
    return out
'''.strip("\n")


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if PUBLIC_MARKER not in text:
        raise RuntimeError("Moneyline public-path marker not found; refusing fuzzy patch")
    if text.count(BINDING) != 1:
        raise RuntimeError(f"Expected exactly one active Phase 2.2 ML binding, found {text.count(BINDING)}")
    insertion = BLOCK + "\n\n"
    out = text.replace(PUBLIC_MARKER, insertion + PUBLIC_MARKER, 1)
    out = out.replace(BINDING, "ml_build_board = _impl_ml_build_board_22", 1)
    ast.parse(out)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_ml_weather.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print("ML weather delay patch CHECK PASS")
        return 0
    if patched != original:
        tmp = path.with_suffix(path.suffix + ".ml_weather_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(path)
    print("ML weather delay patch READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
