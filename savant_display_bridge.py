from __future__ import annotations

"""Display-only Baseball Savant batter-vs-hand audit bridge.

This module is deliberately isolated from the Challenger projection engine.
It only enriches copied lineup rows with raw current-season SO/PA split data
for the Batter-by-Batter audit table.
"""

from datetime import datetime
from io import StringIO
from pathlib import Path
import math
import time
import os
import re
import unicodedata
from typing import Any, Iterable

import pandas as pd
import requests

BRIDGE_VERSION = "SAVANT_DISPLAY_BRIDGE_V8_2026_08_23"
RAW_GITHUB_TEMPLATE = (
    "https://raw.githubusercontent.com/hernandezjh235-sudo/chanllger/main/"
    "learning_data/savant_batter_platoon_{season}.csv"
)

_REQUIRED_BASE = {"mlbam_id", "player_name"}
_FRAME_CACHE = {}
_FRAME_CACHE_TTL_SECONDS = 60.0


def _num(value: Any, default=None):
    try:
        if value is None:
            return default
        text = str(value).strip()
        if text in {"", "—", "-", "nan", "NaN", "None"}:
            return default
        out = float(text.replace("%", "").replace(",", ""))
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _pid(value: Any) -> str:
    try:
        if value in (None, ""):
            return ""
        return str(int(float(value)))
    except Exception:
        return ""


def canonical_name(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("★", " ").replace("△", " ").replace("▲", " ")
    if "," in text:
        left, right = text.split(",", 1)
        if left.strip() and right.strip():
            text = f"{right.strip()} {left.strip()}"
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    ).lower()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", text)
    return " ".join(text.split())


def _token_key(value: Any) -> str:
    key = canonical_name(value)
    return " ".join(sorted(key.split())) if key else ""


def _row_name(row: dict) -> str:
    for key in (
        "Batter", "Player", "Name", "player_name", "batter_name",
        "Player Name", "Batter Name", "Hitter", "hitter_name", "full_name",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _row_pid(row: dict) -> str:
    for key in (
        "mlbam_id", "MLBAM ID", "MLBAM_ID", "player_id", "Player ID",
        "Batter ID", "batter_id", "person_id", "Person ID", "id",
    ):
        got = _pid(row.get(key))
        if got:
            return got
    return ""


def _normalize_frame(frame: pd.DataFrame, split: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    pa_col, so_col, k_col = f"vs_{split}_pa", f"vs_{split}_so", f"vs_{split}_k_pct"
    low = {str(c).strip().lower(): c for c in out.columns}
    aliases = {
        "mlbam_id": ("mlbam_id", "player_id", "batter_id", "id", "key_mlbam"),
        "player_name": ("player_name", "name", "batter_name", "last_name, first_name"),
        pa_col: (pa_col, f"{split}_pa", f"pa_vs_{split}", f"pa_{split}"),
        so_col: (so_col, f"{split}_so", f"so_vs_{split}", f"so_{split}", f"k_vs_{split}"),
        k_col: (k_col, f"{split}_k_pct", f"k_pct_vs_{split}", f"k_pct_{split}"),
    }
    for target, choices in aliases.items():
        if target in out.columns:
            continue
        for choice in choices:
            actual = low.get(choice.lower())
            if actual is not None:
                out[target] = out[actual]
                break
    return out


def _candidate_roots(app_root: Path | None = None, storage_dir: str | Path | None = None):
    roots: list[Path] = []

    def add(value):
        if value in (None, ""):
            return
        try:
            p = Path(value)
        except Exception:
            return
        candidates = (p, p / "learning_data") if p.name != "learning_data" else (p,)
        for candidate in candidates:
            key = str(candidate)
            if key not in {str(x) for x in roots}:
                roots.append(candidate)

    if app_root is not None:
        add(Path(app_root) / "learning_data")
        add(Path(app_root))
    add(Path.cwd() / "learning_data")
    add(Path.cwd() / "mlb_engine" / "learning_data")
    add(storage_dir)
    for env_name in (
        "RAILWAY_VOLUME_MOUNT_PATH", "DATA_DIR", "DATA_ROOT",
        "PERSISTENT_DATA_DIR", "STORAGE_DIR",
    ):
        add(os.getenv(env_name))
    for fixed in (
        "/app/learning_data", "/data/learning_data", "/data",
        "/workspace/learning_data",
    ):
        add(fixed)
    return roots


def _frame_timestamp(frame: pd.DataFrame) -> float:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0.0
    for col in ("source_timestamp", "refresh_timestamp", "updated_at"):
        if col in frame.columns:
            try:
                vals = pd.to_datetime(frame[col], errors="coerce", utc=True).dropna()
                if not vals.empty:
                    return float(vals.max().timestamp())
            except Exception:
                pass
    return 0.0


def load_platoon_frames(
    season: int | None = None,
    app_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    allow_network_fallback: bool = True,
):
    season = int(season or datetime.now().year)
    app_root = Path(app_root) if app_root is not None else None
    cache_key = (season, str(app_root or ""), str(storage_dir or ""), bool(allow_network_fallback))
    cached = _FRAME_CACHE.get(cache_key)
    now_mono = time.monotonic()
    if isinstance(cached, dict) and (now_mono - float(cached.get("at", 0.0) or 0.0)) < _FRAME_CACHE_TTL_SECONDS:
        return [(label, frame.copy()) for label, frame in cached.get("frames", [])]

    filenames = (
        f"savant_batter_platoon_{season}.csv",
        f"savant_batter_platoon_{season}.targeted.csv",
        f"savant_batter_platoon_{season}.last_good.csv",
    )

    frames: list[tuple[str, pd.DataFrame, float]] = []
    seen_paths: set[str] = set()
    for root in _candidate_roots(app_root=app_root, storage_dir=storage_dir):
        for filename in filenames:
            path = root / filename
            try:
                if not path.exists() or not path.is_file():
                    continue
                resolved = str(path.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                frame = pd.read_csv(path)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    frames.append((f"FILE:{resolved}", frame, _frame_timestamp(frame)))
            except Exception:
                continue

    frames.sort(key=lambda x: x[2], reverse=True)

    # Display-only network fallback. It never writes into learning_data and
    # therefore cannot alter the production Challenger projection inputs.
    newest_local_ts = max((stamp for _, _, stamp in frames), default=0.0)
    local_age_seconds = (datetime.now().timestamp() - newest_local_ts) if newest_local_ts > 0 else None
    need_network = not frames or local_age_seconds is None or local_age_seconds > 6 * 3600
    if allow_network_fallback and need_network:
        try:
            url = RAW_GITHUB_TEMPLATE.format(season=season)
            response = requests.get(
                url,
                timeout=(3.0, 8.0),
                headers={"User-Agent": "OneWayPickz-Savant-Display-Audit/1.0"},
            )
            if response.ok and response.text.strip():
                frame = pd.read_csv(StringIO(response.text))
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    frames.append(("GITHUB_CURRENT_DISPLAY_FALLBACK", frame, _frame_timestamp(frame)))
        except Exception:
            pass

    frames.sort(key=lambda x: x[2], reverse=True)
    result = [(label, frame) for label, frame, _ in frames]
    _FRAME_CACHE[cache_key] = {"at": now_mono, "frames": [(label, frame.copy()) for label, frame in result]}
    return result


def enrich_lineup_rows(
    lineup_rows: Iterable[dict],
    pitcher_hand: str,
    expected_bf: float | int | None,
    *,
    season: int | None = None,
    app_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    allow_network_fallback: bool = True,
):
    """Return copied rows enriched with raw Savant SO/PA audit fields.

    No projection fields are changed. Model K% Used remains exactly what the
    production board already calculated.
    """
    rows = [dict(x) for x in (lineup_rows or []) if isinstance(x, dict)][:9]
    hand = str(pitcher_hand or "").upper().strip()
    split = "lhp" if hand.startswith("L") else "rhp"
    pa_col, so_col, k_col = f"vs_{split}_pa", f"vs_{split}_so", f"vs_{split}_k_pct"

    frames = load_platoon_frames(
        season=season,
        app_root=app_root,
        storage_dir=storage_dir,
        allow_network_fallback=allow_network_fallback,
    )

    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    token_buckets: dict[str, list[dict]] = {}
    usable_sources: list[str] = []

    for source, raw_frame in frames:
        frame = _normalize_frame(raw_frame, split)
        if frame.empty or not (_REQUIRED_BASE | {pa_col, so_col}).issubset(frame.columns):
            continue
        usable_sources.append(source)
        for _, rec in frame.iterrows():
            pa = _num(rec.get(pa_col), None)
            so = _num(rec.get(so_col), None)
            if pa is None or pa <= 0 or so is None or so < 0:
                continue
            payload = {
                "pa": int(round(pa)),
                "so": int(round(so)),
                "k_pct": float(100.0 * float(so) / float(pa)),
                "stored_k_pct": _num(rec.get(k_col), None),
                "source": source,
                "player_name": str(rec.get("player_name") or ""),
            }
            rid = _pid(rec.get("mlbam_id"))
            rname = canonical_name(rec.get("player_name"))
            rtok = _token_key(rec.get("player_name"))
            if rid and rid not in by_id:
                by_id[rid] = payload
            if rname and rname not in by_name:
                by_name[rname] = payload
            if rtok:
                token_buckets.setdefault(rtok, []).append(payload)

    by_token = {
        key: items[0]
        for key, items in token_buckets.items()
        if len({canonical_name(x.get("player_name")) for x in items}) == 1
    }

    bf = max(0.0, _num(expected_bf, 0.0) or 0.0)
    lo = int(math.floor(bf))
    frac = bf - lo

    def counts(n):
        return [0.0 if n < slot else float(1 + (n - slot) // 9) for slot in range(1, 10)]

    ca, cb = counts(lo), counts(lo + 1)
    slot_counts = [ca[i] * (1.0 - frac) + cb[i] * frac for i in range(9)]

    matched_values = []
    weighted_pairs = []
    top, middle, bottom = [], [], []
    unmatched_names = []
    match_methods = []

    for idx, row in enumerate(rows):
        name = _row_name(row)
        pid = _row_pid(row)
        rec = by_id.get(pid) if pid else None
        method = "MLBAM_ID" if rec is not None else ""
        if rec is None and name:
            rec = by_name.get(canonical_name(name))
            method = "NAME_CANONICAL" if rec is not None else ""
        if rec is None and name:
            rec = by_token.get(_token_key(name))
            method = "NAME_TOKEN_UNIQUE" if rec is not None else ""

        if rec is None:
            row["Savant Match Status"] = "SAVANT_PLAYER_MATCH_UNCERTAIN"
            unmatched_names.append(name or f"slot {idx + 1}")
            continue

        raw_pa = int(rec["pa"])
        raw_so = int(rec["so"])
        raw_k = float(100.0 * raw_so / raw_pa)
        row["savant_raw_vs_hand_k_pct"] = round(raw_k, 3)
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
            row["model_minus_savant_pp"] = delta
            row["savant_model_delta_pp"] = delta

        matched_values.append(raw_k)
        weight = slot_counts[idx] if idx < len(slot_counts) else 1.0
        weighted_pairs.append((raw_k, weight))
        (top if idx < 3 else middle if idx < 6 else bottom).append(raw_k)
        match_methods.append(method)

    matched = len(matched_values)
    wsum = sum(w for _, w in weighted_pairs)
    audit = {
        "status": "FULL" if rows and matched == len(rows) else "PARTIAL" if matched else "UNAVAILABLE",
        "matched": matched,
        "simple_savant_lineup_k_pct": round(sum(matched_values) / matched, 3) if matched else None,
        "order_weighted_savant_k_pct": round(sum(v*w for v, w in weighted_pairs) / wsum, 3) if wsum > 0 else None,
        "top3_savant_k_pct": round(sum(top) / len(top), 3) if top else None,
        "middle3_savant_k_pct": round(sum(middle) / len(middle), 3) if middle else None,
        "bottom3_savant_k_pct": round(sum(bottom) / len(bottom), 3) if bottom else None,
        "display_bridge": BRIDGE_VERSION,
        "display_bridge_version": "V8",
        "match_methods": match_methods,
        "source_frames": len(frames),
        "usable_sources": usable_sources[:8],
        "unmatched_names": unmatched_names,
        "projection_effect_k": 0.0,
    }
    return rows, audit
