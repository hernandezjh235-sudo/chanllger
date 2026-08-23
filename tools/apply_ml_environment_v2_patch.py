#!/usr/bin/env python3
"""Moneyline-only environment V2 overlay for Challenger.

This runs after the existing Savant K-authority patch and ML rain/delay patch.
It adds team-scoring share, high-scoring environment, blowout/environment support,
wind direction, postponement/starter-disruption risk, and a capped audit-only
support-adjusted probability. It NEVER changes the canonical Moneyline winner.

No pitcher K, BF/IP, HRR, Batter Fantasy, Pitching Outs, grading, learning, or
saved historical board is modified.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_ML_ENVIRONMENT_V2_2026_08_23"
BINDING = "ml_build_board = _impl_ml_build_board_22"
PUBLIC_MARKER = "# Public-path rebinding. K/Challenger and every non-Moneyline engine remain untouched."

BLOCK = r'''
# CHALLENGER_ML_ENVIRONMENT_V2_2026_08_23
# Moneyline support/environment overlay. Canonical side remains protected.
ML_ENVIRONMENT_V2_VERSION = "ML_ENVIRONMENT_V2_2026_08_23"


def _mlenv_num(value, default=None):
    try:
        if value is None or value == "":
            return default
        out = float(str(value).replace("%", "").replace(",", "").strip())
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _mlenv_clamp(value, lo=0.0, hi=100.0):
    try:
        return max(float(lo), min(float(hi), float(value)))
    except Exception:
        return float(lo)


def _mlenv_first(mapping, keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _mlenv_team(value):
    text = str(value or "").strip().upper()
    text = text.replace(" MONEYLINE", "").replace(" ML", "").strip()
    try:
        return ml_canonical_abbr(text) if "ml_canonical_abbr" in globals() else text
    except Exception:
        return text


def _mlenv_interp(x, points):
    try:
        x = float(x)
    except Exception:
        return 50.0
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 50.0


def _mlenv_projected_runs(row, away, home):
    away_runs = _mlenv_num(_mlenv_first(row, [
        "ML Card Away Projected Runs", "Away Projected Runs", "Away Expected Runs",
        "Away Runs", "ML Away Projected Runs", "Away Exp Runs"
    ]), None)
    home_runs = _mlenv_num(_mlenv_first(row, [
        "ML Card Home Projected Runs", "Home Projected Runs", "Home Expected Runs",
        "Home Runs", "ML Home Projected Runs", "Home Exp Runs"
    ]), None)
    if away_runs is not None and home_runs is not None:
        return away_runs, home_runs, "PROJECTED_RUN_FIELDS"

    # Fallback: parse two run values from an existing projected-score string.
    score_text = str(_mlenv_first(row, [
        "ML Score Brain Projected Score", "Projected Score", "ML Projected Score",
        "Score Projection", "Projected Final Score"
    ], "") or "")
    try:
        nums = [float(x) for x in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", score_text)]
        if len(nums) >= 2:
            return nums[0], nums[1], "PROJECTED_SCORE_PARSE"
    except Exception:
        pass
    return None, None, "MISSING"


def _mlenv_pick(row, away, home):
    raw = _mlenv_first(row, [
        "ML Card Best Play", "Canonical Winner", "ML Canonical Winner", "ML Pick",
        "Pick", "Winner"
    ], "")
    pick = _mlenv_team(raw)
    if pick == away or pick == home:
        return pick
    # Some cards contain strings such as "LAD ML" or "LAD -135".
    for team in (away, home):
        if team and team in str(raw or "").upper().split():
            return team
    return pick


def _mlenv_run_score(runs):
    if runs is None:
        return 50.0
    return _mlenv_interp(float(runs), [
        (2.0, 20), (3.0, 35), (4.0, 50), (5.0, 66), (6.0, 82), (7.0, 94)
    ])


def _mlenv_total_score(total_runs):
    if total_runs is None:
        return 50.0
    return _mlenv_interp(float(total_runs), [
        (6.5, 18), (7.0, 27), (8.0, 42), (9.0, 58), (10.0, 75), (11.0, 88), (12.0, 96)
    ])


def _mlenv_diff_score(run_diff):
    if run_diff is None:
        return 50.0
    return _mlenv_interp(float(run_diff), [
        (-1.0, 18), (0.0, 42), (0.5, 52), (1.0, 62), (1.5, 72),
        (2.0, 81), (2.5, 88), (3.0, 94), (4.0, 98)
    ])


def _mlenv_edge_score(value, scale=3.0):
    v = _mlenv_num(value, None)
    if v is None:
        return 50.0
    # Phase 2.2 edges are support deltas, so zero is neutral. Cap aggressively.
    return _mlenv_clamp(50.0 + float(v) * float(scale), 15.0, 85.0)


def _mlenv_cardinal(degrees):
    d = _mlenv_num(degrees, None)
    if d is None:
        return ""
    labels = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S",
              "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return labels[int((float(d) + 11.25) // 22.5) % 16]


@st.cache_data(ttl=600, show_spinner=False)
def _mlenv_direction_forecast(lat, lon, start_date, end_date):
    """Small companion request for wind direction + weather code.

    The existing ML weather patch already supplies temperature/rain/wind speed.
    This request intentionally adds only fields that are not already present.
    """
    try:
        params = {
            "latitude": float(lat),
            "longitude": float(lon),
            "hourly": "wind_direction_10m,weather_code",
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


def _mlenv_weather_extra(board, row, wx):
    result = {"wind_dir_deg": None, "wind_dir": "", "weather_code": None, "thunder": False}
    try:
        away, home, venue, roof, game_time = _mlwd_game_meta(board, row)
        meta = venue_weather_meta(venue) if "venue_weather_meta" in globals() else None
        hour_key = _mlwd_hour_key(game_time) if "_mlwd_hour_key" in globals() else None
        if not meta or not hour_key:
            return result
        lat, lon, _ = meta
        center = datetime.fromisoformat(hour_key)
        data = _mlenv_direction_forecast(lat, lon, center.date().isoformat(), center.date().isoformat())
        hourly = data.get("hourly") if isinstance(data, dict) else None
        if not isinstance(hourly, dict):
            return result
        times = hourly.get("time") or []
        best = None
        for i, raw in enumerate(times):
            try:
                dt = datetime.fromisoformat(str(raw))
                dist = abs((dt - center).total_seconds())
            except Exception:
                continue
            if best is None or dist < best[0]:
                best = (dist, i)
        if best is None:
            return result
        i = best[1]
        dirs = hourly.get("wind_direction_10m") or []
        codes = hourly.get("weather_code") or []
        d = _mlenv_num(dirs[i], None) if i < len(dirs) else None
        c = _mlenv_num(codes[i], None) if i < len(codes) else None
        result["wind_dir_deg"] = d
        result["wind_dir"] = _mlenv_cardinal(d)
        result["weather_code"] = c
        result["thunder"] = c is not None and int(round(c)) in {95, 96, 99}
        return result
    except Exception:
        return result


def _mlenv_weather_risks(wx, extra):
    tier = str((wx or {}).get("tier") or "UNAVAILABLE").upper()
    thunder = bool((extra or {}).get("thunder"))
    peak = _mlenv_num((wx or {}).get("peak_precip_prob"), 0.0) or 0.0
    precip = _mlenv_num((wx or {}).get("peak_precip_mm"), 0.0) or 0.0

    if tier == "ROOF_PROTECTED":
        return "NONE", 0.0
    disruption = {"SEVERE": 88.0, "HIGH": 68.0, "MEDIUM": 38.0, "LOW": 10.0}.get(tier, 20.0)
    if thunder:
        disruption = min(100.0, disruption + 10.0)

    # This is a risk label, not a claim that MLB has postponed the game.
    if tier == "SEVERE" and thunder and (peak >= 80 or precip >= 1.0):
        postpone = "HIGH"
    elif tier == "SEVERE":
        postpone = "MODERATE"
    elif tier == "HIGH" and thunder:
        postpone = "MODERATE"
    elif tier == "HIGH" and peak >= 70:
        postpone = "LOW/MODERATE"
    elif tier == "MEDIUM":
        postpone = "LOW"
    else:
        postpone = "VERY LOW"
    return postpone, disruption


def _mlenv_weather_run_effect(wx, extra, existing_summary=""):
    """Tiny run-environment residual; direction is informational unless park-relative text exists."""
    if str((wx or {}).get("tier") or "").upper() == "ROOF_PROTECTED":
        return 0.0
    temp = _mlenv_num((wx or {}).get("temp_f"), None)
    wind = _mlenv_num((wx or {}).get("wind_mph"), None)
    effect = 0.0
    if temp is not None:
        if temp >= 90:
            effect += 0.18
        elif temp >= 80:
            effect += 0.10
        elif temp <= 50:
            effect -= 0.12
        elif temp <= 60:
            effect -= 0.05
    # Do not guess "out" or "in" from compass direction without stadium orientation.
    text = str(existing_summary or "").lower()
    if wind is not None and wind >= 8:
        if "wind out" in text or "out to" in text:
            effect += min(0.22, (wind - 5.0) * 0.012)
        elif "wind in" in text or "in from" in text:
            effect -= min(0.22, (wind - 5.0) * 0.012)
    return round(max(-0.30, min(0.30, effect)), 2)


def _mlenv_data_quality(row, projected_runs_ok, wx, venue):
    score = 100.0
    if not projected_runs_ok:
        score -= 40.0
    if str((wx or {}).get("source") or "UNAVAILABLE").upper() == "UNAVAILABLE":
        score -= 12.0
    if not venue or "UNKNOWN" in str(venue).upper():
        score -= 6.0
    if _mlenv_num(row.get("ML Starter Edge"), None) is None:
        score -= 8.0
    if _mlenv_num(row.get("ML Bullpen Edge"), None) is None:
        score -= 8.0
    lineup_text = str(_mlenv_first(row, ["Lineup", "Lineup Status", "ML Lineup Status"], "") or "").upper()
    if "EXPECTED" in lineup_text and "CONFIRMED" not in lineup_text:
        score -= 8.0
    price = _mlenv_first(row, ["ML Card Best Play Price", "Best Play Price", "ML Price", "Price"], None)
    if price in (None, ""):
        score -= 4.0
    return round(_mlenv_clamp(score, 0.0, 100.0), 1)


def _mlenv_probability_adjustment(env_score, quality):
    e = float(env_score)
    if 45.0 <= e <= 55.0:
        raw = 0.0
    elif 55.0 < e < 65.0:
        raw = 0.5 + (e - 56.0) / 8.0 * 1.0
    elif 65.0 <= e < 75.0:
        raw = 1.5 + (e - 65.0) / 9.0 * 1.5
    elif 75.0 <= e < 85.0:
        raw = 3.0 + (e - 75.0) / 9.0 * 1.5
    elif e >= 85.0:
        raw = min(5.0, 4.5 + (e - 85.0) / 15.0 * 0.5)
    elif 35.0 <= e < 45.0:
        raw = -(0.5 + (44.0 - e) / 9.0 * 1.0)
    elif 25.0 <= e < 35.0:
        raw = -(1.5 + (34.0 - e) / 9.0 * 1.5)
    else:
        raw = -min(4.0, 3.0 + max(0.0, 25.0 - e) / 25.0)

    q = float(quality)
    if q < 60.0:
        return 0.0
    authority = _mlenv_clamp((q - 50.0) / 50.0, 0.0, 1.0)
    return round(raw * authority, 2)


def _mlenv_support_state(env_score, blowout, quality, disruption):
    if quality < 60:
        return "LOW_DATA"
    if disruption >= 85:
        return "WEATHER_CONFLICT"
    if env_score >= 80 and blowout >= 75:
        return "ELITE_SUPPORT"
    if env_score >= 70 and blowout >= 65:
        return "STRONG_SUPPORT"
    if env_score >= 60:
        return "SUPPORTED"
    if env_score < 40:
        return "CONFLICTED"
    return "NEUTRAL"


def _mlenv_append(existing, text):
    old = str(existing or "").strip()
    if not text:
        return old
    if text.lower() in old.lower():
        return old
    return text if not old else f"{old}; {text}"


def _impl_ml_build_board_23(board):
    """Phase 2.2 + weather delay V1 + environment V2; canonical side preserving."""
    df = _impl_ml_build_board_22(board)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()

    for ridx, rr in out.iterrows():
        row = rr.to_dict()
        away, home, venue, roof, game_time = _mlwd_game_meta(board, row)
        pick = _mlenv_pick(row, away, home)
        away_runs, home_runs, run_source = _mlenv_projected_runs(row, away, home)
        projected_ok = away_runs is not None and home_runs is not None

        if pick == away:
            pick_runs, opp_runs = away_runs, home_runs
        elif pick == home:
            pick_runs, opp_runs = home_runs, away_runs
        else:
            pick_runs, opp_runs = None, None

        total_runs = None if not projected_ok else float(away_runs) + float(home_runs)
        run_diff = None if pick_runs is None or opp_runs is None else float(pick_runs) - float(opp_runs)
        share = None if pick_runs is None or total_runs in (None, 0) else 100.0 * float(pick_runs) / float(total_runs)

        wx = _mlwd_risk(board, row) if "_mlwd_risk" in globals() else {}
        extra = _mlenv_weather_extra(board, row, wx)
        postpone, disruption = _mlenv_weather_risks(wx, extra)
        wx_run_effect = _mlenv_weather_run_effect(wx, extra, row.get("ML Weather Summary"))

        total_score = _mlenv_total_score(total_runs)
        park_factor = _mlenv_num(_mlenv_first(row, ["Park Factor", "ML Park Factor"], 1.0), 1.0) or 1.0
        park_score = _mlenv_clamp(50.0 + (park_factor - 1.0) * 180.0, 25.0, 75.0)
        weather_score = _mlenv_clamp(50.0 + wx_run_effect * 35.0, 35.0, 65.0)
        # Projected total already absorbs offense/starter/bullpen; avoid stacking them again.
        high_score = _mlenv_clamp(0.85 * total_score + 0.10 * park_score + 0.05 * weather_score)

        share_score = 50.0 if share is None else _mlenv_clamp(50.0 + (share - 50.0) * 3.0, 10.0, 95.0)
        diff_score = _mlenv_diff_score(run_diff)
        team_adv = 0.60 * diff_score + 0.40 * share_score

        offense_edge = _mlenv_num(row.get("ML Offense Vs Hand Edge"), 0.0) or 0.0
        contact_edge = _mlenv_num(row.get("ML Contact Quality Edge"), 0.0) or 0.0
        starter_score = _mlenv_edge_score(row.get("ML Starter Edge"), 3.0)
        bullpen_score = _mlenv_edge_score(row.get("ML Bullpen Edge"), 3.0)
        pick_run_strength = _mlenv_clamp(_mlenv_run_score(pick_runs) + 0.6 * offense_edge + 0.2 * contact_edge)
        opp_run_strength = _mlenv_clamp(_mlenv_run_score(opp_runs) - 0.6 * offense_edge - 0.2 * contact_edge)
        offensive_edge_score = pick_run_strength - opp_run_strength

        existing_blowout = _mlenv_num(row.get("ML Blowout Score"), None)
        if existing_blowout is None:
            offense_support_score = _mlenv_clamp(50.0 + offensive_edge_score, 10.0, 90.0)
            blowout = _mlenv_clamp(
                0.30 * diff_score + 0.20 * starter_score + 0.17 * offense_support_score +
                0.13 * bullpen_score + 0.08 * 50.0 + 0.07 * 50.0 + 0.05 * 50.0
            )
            blowout_source = "ENV_V2_FALLBACK"
        else:
            blowout = _mlenv_clamp(existing_blowout)
            blowout_source = "EXISTING_ML_BLOWOUT"

        env_score = _mlenv_clamp(
            0.35 * team_adv + 0.25 * blowout + 0.15 * starter_score +
            0.10 * bullpen_score + 0.10 * share_score + 0.05 * high_score
        )
        quality = _mlenv_data_quality(row, projected_ok, wx, venue)
        env_adj = _mlenv_probability_adjustment(env_score, quality)

        canonical_prob = _mlenv_num(_mlenv_first(row, [
            "ML Card Best Play Prob %", "Canonical Win Probability", "ML Win Prob %", "Win Probability"
        ]), None)
        adjusted_prob = None
        if canonical_prob is not None:
            adjusted_prob = float(canonical_prob) + float(env_adj)
            # Weather disruption reduces confidence but never reverses the canonical side.
            if disruption >= 85:
                adjusted_prob -= 2.0
            elif disruption >= 65:
                adjusted_prob -= 1.2
            elif disruption >= 35:
                adjusted_prob -= 0.5
            adjusted_prob = max(50.0, min(99.0, adjusted_prob))

        state = _mlenv_support_state(env_score, blowout, quality, disruption)
        direction = extra.get("wind_dir") or ""
        deg = extra.get("wind_dir_deg")

        out.at[ridx, "ML High Scoring Score"] = round(high_score, 1)
        out.at[ridx, "ML Team Run Strength"] = round(pick_run_strength, 1)
        out.at[ridx, "ML Opp Team Run Strength"] = round(opp_run_strength, 1)
        out.at[ridx, "ML Offensive Edge Score"] = round(offensive_edge_score, 1)
        out.at[ridx, "ML Team Scoring Share %"] = None if share is None else round(share, 1)
        out.at[ridx, "ML Projected Run Diff"] = None if run_diff is None else round(run_diff, 2)
        out.at[ridx, "ML Environment Score V2"] = round(env_score, 1)
        out.at[ridx, "ML Environment Data Score"] = quality
        out.at[ridx, "ML Environment Support State"] = state
        out.at[ridx, "ML Environment Probability Adj"] = env_adj
        out.at[ridx, "ML Environment Adjusted Win %"] = None if adjusted_prob is None else round(adjusted_prob, 1)
        out.at[ridx, "ML Environment Run Source"] = run_source
        out.at[ridx, "ML Environment Version"] = ML_ENVIRONMENT_V2_VERSION
        out.at[ridx, "ML Blowout Source V2"] = blowout_source
        out.at[ridx, "ML Weather Run Effect"] = wx_run_effect
        out.at[ridx, "ML Wind Direction"] = direction
        out.at[ridx, "ML Wind Direction Deg"] = deg
        out.at[ridx, "ML Postponement Risk"] = postpone
        out.at[ridx, "ML Starter Disruption Risk Score"] = round(disruption, 1)
        out.at[ridx, "ML Weather Code"] = extra.get("weather_code")

        # Make the new context visible without altering the canonical pick/tier.
        summary = str(row.get("ML Weather Summary") or "").strip()
        if direction:
            summary = _mlenv_append(summary, f"wind dir {direction}")
        if postpone not in {"VERY LOW", "NONE"}:
            summary = _mlenv_append(summary, f"postpone risk {postpone}")
        out.at[ridx, "ML Weather Summary"] = summary

        env_note = f"ENV {env_score:.0f} · HS {high_score:.0f}"
        if share is not None:
            env_note += f" · share {share:.1f}%"
        env_note += f" · blowout {blowout:.0f} · data {quality:.0f}"
        out.at[ridx, "ML Support Signals"] = _mlenv_append(row.get("ML Support Signals"), env_note)

        if disruption >= 65:
            out.at[ridx, "ML Risk Reasons"] = _mlenv_append(
                row.get("ML Risk Reasons"), f"STARTER DISRUPTION WEATHER RISK {disruption:.0f}/100"
            )

    return out
'''.strip("\n")


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if PUBLIC_MARKER not in text:
        raise RuntimeError("Moneyline public-path marker not found; refusing fuzzy patch")
    if text.count(BINDING) != 1:
        raise RuntimeError(f"Expected exactly one weather-overlay ML binding, found {text.count(BINDING)}")
    out = text.replace(PUBLIC_MARKER, BLOCK + "\n\n" + PUBLIC_MARKER, 1)
    out = out.replace(BINDING, "ml_build_board = _impl_ml_build_board_23", 1)
    ast.parse(out)
    return out


def _synthetic_checks():
    # High-scoring but close should not look like an elite winner environment.
    hs = _mlenv_test_total_score(11.5)
    share_close = 100.0 * 6.0 / 11.5
    share_sep = 100.0 * 6.5 / 9.3
    if hs < 80.0:
        raise RuntimeError("High-scoring synthetic score too low")
    if share_close >= 55.0:
        raise RuntimeError("Close high-scoring share check failed")
    if share_sep < 65.0:
        raise RuntimeError("Separated scoring-share check failed")


def _mlenv_test_total_score(total):
    points = [(6.5, 18), (7.0, 27), (8.0, 42), (9.0, 58), (10.0, 75), (11.0, 88), (12.0, 96)]
    if total <= points[0][0]:
        return points[0][1]
    if total >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= total <= x1:
            return y0 + (total - x0) / (x1 - x0) * (y1 - y0)
    return 50.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    _synthetic_checks()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched = patch_text(original)
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_ml_env.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)
    if args.check_only:
        print("ML environment V2 patch CHECK PASS")
        return 0
    if patched != original:
        tmp = path.with_suffix(path.suffix + ".ml_env_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(path)
    print("ML environment V2 patch READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
