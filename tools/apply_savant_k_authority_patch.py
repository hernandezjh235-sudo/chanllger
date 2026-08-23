#!/usr/bin/env python3
"""Surgical Challenger batter-K authority patch.

Purpose
-------
1) Make the validated current-season Baseball Savant vs-pitcher-hand file the
   authoritative upstream batter split used by the K engine when available.
2) Preserve the existing Challenger batter-K blend, but prevent recent-form
   inputs from moving a large-sample handedness split an implausibly large
   distance. Small samples remain free to shrink toward broader talent/recent
   information.

This does NOT alter pitcher workload, BF/IP, K distribution, Challenger/Undefeated
side protection, grading, learning, Moneyline, or any non-batter-K formula.

The patch is applied to the Railway checkout immediately before Streamlit starts.
It is idempotent and fail-closed: if the expected functions are not found or the
patched file does not compile, app.py is left unchanged.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import py_compile
import tempfile

MARKER = "CHALLENGER_SAVANT_K_AUTHORITY_V1_2026_08_23"
TARGET_FUNCTIONS = (
    "get_batter_k_rate_vs_pitcher_hand",
    "blend_batter_k_inputs",
)


def _function_nodes(text: str, name: str):
    tree = ast.parse(text)
    return [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == name
        and getattr(n, "col_offset", 1) == 0
    ]


def _savant_wrapper() -> str:
    return r'''
@st.cache_data(ttl=600, show_spinner=False)
def get_batter_k_rate_vs_pitcher_hand(player_id, pitcher_hand):
    """Current-season batter K% vs pitcher hand, Savant-first.

    The validated Savant installer is the authoritative split source. The
    legacy MLB Stats API implementation remains the fallback when a player is
    genuinely absent from the current/LAST_GOOD Savant data.
    """
    if not player_id or pitcher_hand not in ["R", "L"]:
        return None, None, None, "No pitcher hand"

    try:
        pid = str(int(float(player_id)))
    except Exception:
        return _legacy_get_batter_k_rate_vs_pitcher_hand(player_id, pitcher_hand)

    season = int(datetime.now().year)
    hand_key = "rhp" if pitcher_hand == "R" else "lhp"
    pa_col = f"vs_{hand_key}_pa"
    so_col = f"vs_{hand_key}_so"
    k_col = f"vs_{hand_key}_k_pct"

    try:
        global _CHALLENGER_SAVANT_K_TABLE_CACHE
        cache = globals().get("_CHALLENGER_SAVANT_K_TABLE_CACHE")
        cache_key = (season,)
        if not isinstance(cache, dict) or cache.get("key") != cache_key:
            active = Path("learning_data") / f"savant_batter_platoon_{season}.csv"
            last_good = Path("learning_data") / f"savant_batter_platoon_{season}.last_good.csv"
            source_path = active if active.exists() else last_good
            frame = pd.read_csv(source_path) if source_path.exists() else pd.DataFrame()
            if not frame.empty and "mlbam_id" in frame.columns:
                ids = pd.to_numeric(frame["mlbam_id"], errors="coerce")
                frame = frame.assign(_challenger_pid=ids).dropna(subset=["_challenger_pid"])
                frame["_challenger_pid"] = frame["_challenger_pid"].astype(int).astype(str)
                frame = frame.drop_duplicates("_challenger_pid", keep="last").set_index("_challenger_pid", drop=False)
            cache = {"key": cache_key, "frame": frame, "path": str(source_path)}
            _CHALLENGER_SAVANT_K_TABLE_CACHE = cache

        frame = cache.get("frame") if isinstance(cache, dict) else None
        if isinstance(frame, pd.DataFrame) and not frame.empty and pid in frame.index:
            rec = frame.loc[pid]
            if isinstance(rec, pd.DataFrame):
                rec = rec.iloc[-1]

            def _num(value):
                try:
                    out = float(value)
                    return out if out == out else None
                except Exception:
                    return None

            pa = _num(rec.get(pa_col))
            so = _num(rec.get(so_col))
            kpct = _num(rec.get(k_col))
            if pa is not None and pa > 0 and kpct is not None:
                rate = kpct / 100.0 if abs(kpct) > 1.0 else kpct
                rate = max(0.0, min(1.0, float(rate)))
                return rate, int(round(so or 0.0)), int(round(pa)), f"Baseball Savant current-season vs {pitcher_hand}HP"
    except Exception:
        pass

    return _legacy_get_batter_k_rate_vs_pitcher_hand(player_id, pitcher_hand)
'''.strip("\n")


def _blend_wrapper() -> str:
    return r'''
def blend_batter_k_inputs(season_k, split_k=None, season_pa=None, split_pa=None, rolling14=None, rolling30=None):
    """Preserve Challenger blend with large-sample Savant authority.

    The legacy blend remains the baseline. When the current vs-hand split has a
    meaningful sample, cap how far overlapping recent/season windows may pull
    the model away from that observed split. This avoids double-counting recent
    PA while still allowing small-sample shrinkage.
    """
    blended, source = _legacy_blend_batter_k_inputs(
        season_k,
        split_k=split_k,
        season_pa=season_pa,
        split_pa=split_pa,
        rolling14=rolling14,
        rolling30=rolling30,
    )
    try:
        if split_k is None or split_pa is None:
            return blended, source
        split = float(split_k)
        pa = float(split_pa)
        if abs(split) > 1.0:
            split /= 100.0
        if blended is None:
            return split, "Baseball Savant vs-hand split"
        value = float(blended)
        if abs(value) > 1.0:
            value /= 100.0

        # Large samples get progressively stronger authority. These are caps,
        # not hard replacements: recent/season information can still move the
        # expected K rate, just not by an outsized amount.
        if pa >= 300:
            cap = 0.025
        elif pa >= 200:
            cap = 0.030
        elif pa >= 100:
            cap = 0.040
        elif pa >= 50:
            cap = 0.050
        else:
            return value, f"{source}; Savant small-sample shrinkage ({int(pa)} PA)"

        guarded = max(split - cap, min(split + cap, value))
        guarded = max(0.02, min(0.60, guarded))
        if abs(guarded - value) > 1e-9:
            return guarded, f"{source}; Savant authority {int(pa)} PA (cap ±{cap*100:.1f}pp)"
        return value, f"{source}; Savant authority {int(pa)} PA"
    except Exception:
        return blended, source
'''.strip("\n")


def _replace_all(text: str, name: str, wrapper: str) -> tuple[str, int]:
    nodes = _function_nodes(text, name)
    if not nodes:
        raise RuntimeError(f"Expected top-level function not found: {name}")

    lines = text.splitlines(keepends=True)
    count = 0
    # Replace from bottom to top so AST line numbers remain valid.
    for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
        start = node.lineno - 1
        end = node.end_lineno
        original = "".join(lines[start:end])
        needle = f"def {name}("
        if needle not in original:
            raise RuntimeError(f"Could not locate definition token for {name} at line {node.lineno}")
        legacy = original.replace(needle, f"def _legacy_{name}(", 1).rstrip("\r\n")
        replacement = legacy + "\n\n" + wrapper + "\n"
        lines[start:end] = [replacement]
        count += 1
    return "".join(lines), count


def patch_text(text: str) -> tuple[str, dict]:
    if MARKER in text:
        return text, {"already_patched": True, "get_split": 0, "blend": 0}

    out, n_get = _replace_all(text, "get_batter_k_rate_vs_pitcher_hand", _savant_wrapper())
    out, n_blend = _replace_all(out, "blend_batter_k_inputs", _blend_wrapper())
    header = f"# {MARKER}\n"
    out = header + out
    ast.parse(out)
    return out, {"already_patched": False, "get_split": n_get, "blend": n_blend}


def _synthetic_checks():
    # Expected authority behavior for examples observed on the current slate.
    def guard(raw_pct, pa, legacy_pct):
        raw = raw_pct / 100.0
        value = legacy_pct / 100.0
        if pa >= 300:
            cap = .025
        elif pa >= 200:
            cap = .030
        elif pa >= 100:
            cap = .040
        elif pa >= 50:
            cap = .050
        else:
            return legacy_pct
        return max(raw - cap, min(raw + cap, value)) * 100.0

    cases = {
        "Neto": (32.4, 407, 27.0, 29.9),
        "Josh Lowe": (27.7, 220, 33.1, 30.7),
        "Rutschman": (12.6, 111, 20.9, 16.6),
        "Lane Thomas": (23.3, 150, 31.2, 27.3),
        "Gasper small sample unchanged": (36.8, 19, 10.9, 10.9),
    }
    for name, (raw, pa, legacy, expected) in cases.items():
        got = round(guard(raw, pa, legacy), 1)
        if got != round(expected, 1):
            raise RuntimeError(f"Synthetic authority check failed for {name}: got {got}, expected {expected}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="app.py")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    patched, stats = patch_text(original)
    _synthetic_checks()

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app_patched.py"
        probe.write_text(patched, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)

    if args.check_only:
        print("Savant K authority patch CHECK PASS", stats)
        return 0

    if patched != original:
        tmp = path.with_suffix(path.suffix + ".savant_k_tmp")
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(path)
    print("Savant K authority patch READY", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
