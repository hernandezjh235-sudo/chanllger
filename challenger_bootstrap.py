# -*- coding: utf-8 -*-
"""Build the Challenger app from the frozen Undefeated control source.

This bootstrap is intentionally fail-closed for projection code:
- fetch the exact frozen V1.10.1 control source used to build the validated V1.11 artifact
- normalize line endings only
- apply the exact V1.10.1 -> V1.11 post-grade patch
- verify the resulting app.py SHA256 against the validated artifact
- restore the live Savant batter-vs-hand helper and the same full pitcher-profile fallback data

Undefeated production is never modified by this script.
"""
from pathlib import Path
import base64
import gzip
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "learning_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONTROL_REPO_RAW = "https://raw.githubusercontent.com/hernandezjh235-sudo/app.py"
CONTROL_COMMIT = "ab5dd2d5cc68f64f99d76a3065f1ac1d429ea134"
PATCH_PAYLOAD = ROOT / ".github" / "challenger_v101_to_v111.patch.gz.b64"
EXPECTED_PATCH_SHA256 = "55a43463ea77fc98737fa37772816bac9d93e28aa87f11587757a4888a2be767"
EXPECTED_FINAL_APP_SHA256 = "22693e611f43edd6709e5c6aec49b86e4758c8c3e871b8a499dc4ffc546b5131"
EXPECTED_FINAL_MARKER = "UNDEFEATED_BETA_V1_11_FALSE_UNDER_GUARD_2026_08_19"
EXPECTED_PITCHER_DATA_SHA256 = "d03d4e3c87fc3bc3f3aa4cc159529c6f298ad449bc16b5e8e08dc13fb97cad68"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OneWayPickz-Challenger/1.0)",
    "Accept": "text/plain,text/csv,*/*",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(path: str, timeout=(10, 90)) -> bytes:
    url = f"{CONTROL_REPO_RAW}/{CONTROL_COMMIT}/{quote(path, safe='/()_.-')}"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def _find_sequence(lines, seq, hint):
    if not seq:
        return max(0, min(len(lines), hint))
    n = len(seq)
    lo = max(0, hint - 120)
    hi = min(len(lines) - n, hint + 120)
    for radius in range(0, 121):
        for idx in (hint + radius, hint - radius):
            if idx < lo or idx > hi:
                continue
            if lines[idx:idx+n] == seq:
                return idx
    matches = []
    for idx in range(0, len(lines) - n + 1):
        if lines[idx:idx+n] == seq:
            matches.append(idx)
            if len(matches) > 1:
                break
    if len(matches) == 1:
        return matches[0]
    return None


def _apply_unified_patch(source_text: str, patch_text: str) -> str:
    """Apply a standard unified diff with exact context matching.

    This deliberately refuses ambiguous/fuzzy edits. If the frozen control no longer
    matches the validated patch context, deployment stops instead of silently changing
    a different projection block.
    """
    source = source_text.replace("\r\n", "\n").replace("\r", "\n")
    patch = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    src = source.splitlines(keepends=True)
    plines = patch.splitlines(keepends=True)
    i = 0
    cumulative_delta = 0
    applied = 0
    while i < len(plines):
        line = plines[i]
        if not line.startswith("@@ "):
            i += 1
            continue
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            raise RuntimeError(f"Malformed patch hunk: {line.strip()}")
        old_start = int(m.group(1))
        i += 1
        old_block, new_block = [], []
        while i < len(plines) and not plines[i].startswith("@@ "):
            h = plines[i]
            if h.startswith("--- ") or h.startswith("+++ "):
                i += 1
                continue
            if h.startswith("\\ No newline"):
                i += 1
                continue
            if h.startswith(" "):
                old_block.append(h[1:])
                new_block.append(h[1:])
            elif h.startswith("-"):
                old_block.append(h[1:])
            elif h.startswith("+"):
                new_block.append(h[1:])
            else:
                raise RuntimeError(f"Unexpected patch line in hunk: {h[:80]!r}")
            i += 1
        hint = max(0, old_start - 1 + cumulative_delta)
        idx = _find_sequence(src, old_block, hint)
        if idx is None:
            raise RuntimeError(f"Challenger patch context did not match hunk starting at old line {old_start}")
        src[idx:idx + len(old_block)] = new_block
        cumulative_delta += len(new_block) - len(old_block)
        applied += 1
    if applied == 0:
        raise RuntimeError("No Challenger patch hunks were applied")
    return "".join(src)


def _build_challenger_app():
    control_bytes = _download("app.py")
    control_text = control_bytes.decode("utf-8-sig")
    normalized = control_text.replace("\r\n", "\n").replace("\r", "\n")
    print("Challenger control normalized SHA256:", _sha(normalized.encode("utf-8")))

    payload = "".join(PATCH_PAYLOAD.read_text(encoding="utf-8").split())
    patch_bytes = gzip.decompress(base64.b64decode(payload))
    if _sha(patch_bytes) != EXPECTED_PATCH_SHA256:
        raise RuntimeError("Challenger patch checksum mismatch; refusing to modify app.py")

    final_text = _apply_unified_patch(normalized, patch_bytes.decode("utf-8"))
    final_bytes = final_text.encode("utf-8")
    final_sha = _sha(final_bytes)
    if EXPECTED_FINAL_MARKER not in final_text:
        raise RuntimeError("Challenger V1.11 marker missing after patch")
    if final_sha != EXPECTED_FINAL_APP_SHA256:
        raise RuntimeError(
            f"Challenger final app checksum mismatch ({final_sha}); expected {EXPECTED_FINAL_APP_SHA256}"
        )
    (ROOT / "app.py").write_bytes(final_bytes)
    print("Challenger app verified:", EXPECTED_FINAL_MARKER, final_sha)


def _install_live_savant_helper():
    try:
        helper = _download("merge_v269_safe_update.py")
        text = helper.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        if "class SavantDataService" not in text or "SAVANT_BATTER_PLATOON_SCHEMA_V1" not in text:
            raise RuntimeError("Downloaded Savant helper failed structural validation")
        (ROOT / "merge_v269_safe_update.py").write_text(text, encoding="utf-8")
        print("Installed live Savant batter-vs-hand helper")
    except Exception as exc:
        # app.py contains a cache-only compatibility fallback, so helper failure is
        # non-fatal. We report it clearly instead of fabricating data.
        print(f"Savant helper install warning: {type(exc).__name__}: {exc}")


def _restore_full_pitcher_profile_fallback():
    """Restore the same validated full pitcher-profile CSV used by the Undefeated data bootstrap."""
    try:
        chunks = []
        for idx in range(1, 6):
            chunks.append(_download(f".github/v1102_payload/data{idx:02d}.b64").decode("utf-8"))
        packed = "".join("".join(chunks).split())
        data = gzip.decompress(base64.b64decode(packed))
        if _sha(data) != EXPECTED_PITCHER_DATA_SHA256:
            raise RuntimeError("Full pitcher-profile checksum mismatch")
        path = DATA_DIR / "savant_full_pitcher_profiles.csv"
        path.write_bytes(data)
        print(f"Installed validated full pitcher profile fallback: {path} ({len(data)} bytes)")
    except Exception as exc:
        print(f"Full pitcher-profile fallback warning: {type(exc).__name__}: {exc}")


def _restore_support_files():
    # These are support/fallback inputs only. Live/current feeds inside the app remain authoritative.
    for name in ("graded_history.csv", "Bullpen.csv", "TeamOffense.csv"):
        try:
            data = _download(f"learning_data/{name}")
            if data:
                (DATA_DIR / name).write_bytes(data)
                print(f"Installed support data: {name} ({len(data)} bytes)")
        except Exception as exc:
            print(f"Support-data warning {name}: {type(exc).__name__}: {exc}")


def _refresh_batter_platoon():
    try:
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location("merge_v269_safe_update", ROOT / "merge_v269_safe_update.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("Savant helper import spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        service = module.SavantDataService(cache_dir=DATA_DIR)
        result = service.refresh(force=False)
        safe = {
            "status": result.get("status"),
            "refresh": result.get("refresh"),
            "rows": result.get("row_count"),
            "source": result.get("source"),
            "error": result.get("error"),
        }
        print("Challenger live Savant preflight:", json.dumps(safe, default=str))
    except Exception as exc:
        print(f"Live Savant preflight warning: {type(exc).__name__}: {exc}")


def _validate_app():
    app = ROOT / "app.py"
    text = app.read_text(encoding="utf-8")
    required = (
        "UNDEFEATED_BETA_V1_11_FALSE_UNDER_GUARD_2026_08_19",
        "def _ub_v111_false_under_profile",
        "def _ub_v111_preserve_control_under_profile",
        "UB OVER Floor Survival",
        "UB Low-Line Threshold Status",
        "Savant Shadow Status",
    )
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError(f"Challenger structural validation missing: {missing}")
    subprocess.run([sys.executable, "-m", "py_compile", str(app)], cwd=ROOT, check=True)
    helper = ROOT / "merge_v269_safe_update.py"
    if helper.exists():
        subprocess.run([sys.executable, "-m", "py_compile", str(helper)], cwd=ROOT, check=True)
    print("Challenger compile + structural validation PASS")


def main():
    _build_challenger_app()
    _install_live_savant_helper()
    _restore_full_pitcher_profile_fallback()
    _restore_support_files()
    _refresh_batter_platoon()
    _validate_app()
    info = {
        "challenger_version": EXPECTED_FINAL_MARKER,
        "control_commit": CONTROL_COMMIT,
        "final_app_sha256": EXPECTED_FINAL_APP_SHA256,
        "pitcher_profile_sha256": EXPECTED_PITCHER_DATA_SHA256,
        "policy": "Undefeated production untouched; post-grade Challenger only",
    }
    (ROOT / "CHALLENGER_BUILD_INFO.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("Challenger bootstrap READY")


if __name__ == "__main__":
    main()
