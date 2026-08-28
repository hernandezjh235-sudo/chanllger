#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RECENCY_SHADOW_CACHE_GUARD_V3_2026_08_28"
ANCHOR = "def _chrs_render_shadow(board):"

BLOCK = r'''
# =============================================================================
# CHALLENGER_RECENCY_SHADOW_CACHE_GUARD_V3_2026_08_28
# Recency remains fully available, but its expensive K/PO/PFS audit is computed
# at most once per refreshed board generation and reused on normal widget reruns.
# No official projection/side/probability is changed.
# =============================================================================
_CHRS_BUILD_SHADOW_UNCACHED_V3 = _chrs_build_shadow


def _chrs_build_shadow(board):
    try:
        gen = str(st.session_state.get("last_refresh_time") or "NO_BOARD")
        pack = st.session_state.get("_chrs_shadow_cache_v3")
        if isinstance(pack, dict) and pack.get("generation") == gen:
            s = pack.get("shadow")
            k = pack.get("kdf")
            if isinstance(s, pd.DataFrame) and isinstance(k, pd.DataFrame):
                return s.copy(), k.copy()
    except Exception:
        gen = "NO_BOARD"

    shadow, kdf = _CHRS_BUILD_SHADOW_UNCACHED_V3(board)
    try:
        if isinstance(shadow, pd.DataFrame) and isinstance(kdf, pd.DataFrame):
            st.session_state["_chrs_shadow_cache_v3"] = {
                "generation": gen,
                "shadow": shadow.copy(),
                "kdf": kdf.copy(),
            }
    except Exception:
        pass
    return shadow, kdf
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if ANCHOR not in text or "def _chrs_build_shadow(board):" not in text:
        raise RuntimeError("Recency shadow cache anchors not found; app left unchanged")
    pos = text.index(ANCHOR)
    return text[:pos] + BLOCK + "\n\n\n" + text[pos:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8")
    updated = patch_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        py_compile.compile(str(path), cfile=str(Path(td) / "app.pyc"), doraise=True)
    print(f"Recency Cache Guard V3 READY: {path}")


if __name__ == "__main__":
    main()
