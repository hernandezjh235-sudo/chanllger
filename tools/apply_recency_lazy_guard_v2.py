#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "CHALLENGER_RECENCY_SHADOW_LAZY_GUARD_V2_2026_08_28"

OLD = '''def _impl_render_kproj_tab_ch_recency_shadow_v1(board):
    if callable(_CH_RECENCY_PREV_RENDER_K):
        _CH_RECENCY_PREV_RENDER_K(board)
    _chrs_render_shadow(board)
'''

NEW = '''# CHALLENGER_RECENCY_SHADOW_LAZY_GUARD_V2_2026_08_28
# Preserve the complete Recency Trap / Best Prop feature, but do not rebuild
# K + Pitching Outs + Pitcher FS during every normal K-board render. The heavy
# audit is opt-in for the current board generation only.
def _impl_render_kproj_tab_ch_recency_shadow_v1(board):
    if callable(_CH_RECENCY_PREV_RENDER_K):
        _CH_RECENCY_PREV_RENDER_K(board)

    try:
        _chrs_gen = str(st.session_state.get("last_refresh_time") or "NO_BOARD")
        _chrs_loaded_gen = str(st.session_state.get("_chrs_lazy_loaded_generation") or "")
        _chrs_loaded = (_chrs_loaded_gen == _chrs_gen)
    except Exception:
        _chrs_gen, _chrs_loaded = "NO_BOARD", False

    if not _chrs_loaded:
        st.caption(
            "🧠 Recency Trap / Best Prop is preserved in stability mode and is deferred "
            "until requested so it cannot duplicate-build every pitcher market while the main board loads."
        )
        if st.button(
            "Load Recency Trap / Best Prop",
            key="challenger_recency_shadow_lazy_v2_load",
            use_container_width=True,
        ):
            try:
                st.session_state["_chrs_lazy_loaded_generation"] = _chrs_gen
            except Exception:
                pass
            _chrs_loaded = True

    if _chrs_loaded:
        _chrs_render_shadow(board)
'''


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if OLD not in text:
        raise RuntimeError("Recency shadow wrapper anchor not found; app left unchanged")
    return text.replace(OLD, NEW, 1)


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
    print(f"Recency Lazy Guard V2 READY: {path}")


if __name__ == "__main__":
    main()
