#!/usr/bin/env python3
"""Runtime-only Savant manual-refresh guard for Challenger / UD2.

Network Savant work is permitted only through the explicit main-board refresh path
installed by apply_manual_refresh_state_v2.py. Passive/timed/background workers are
neutralized. Projection math, cached Savant reads, Save, grading, and other markets
are untouched.
"""
from __future__ import annotations
import argparse, py_compile, re, tempfile
from pathlib import Path

MARKER = "CHALLENGER_UD2_SAVANT_MANUAL_ONLY_V3_2026_08_28"
TAB_ANCHOR = "tab_kproj, tab_brain, tab_beta_outs, tab_first_inning_k, tab_beta_ip_debug, tab_moneyline, tab_loss_lab, tab_iq, tab_30d_learning, tab_learning_lab, tab_calibration, tab2, tab3, tab4, tab5, tab6 = st.tabs(["

BLOCK = r'''
# =============================================================================
# CHALLENGER_UD2_SAVANT_MANUAL_ONLY_V3_2026_08_28
# Runtime/network guard only. Cached Savant reads remain available on every rerun.
# Network refresh is reserved for explicit Refresh Live Board / Pull Lines.
# =============================================================================
try:
    MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = False
except Exception:
    pass

import subprocess as _manual_savant_subprocess
import sys as _manual_savant_sys


def _manual_only_savant_background_worker(*args, **kwargs):
    return {
        "status": "SKIPPED",
        "mode": "MANUAL_BOARD_REFRESH_ONLY",
        "reason": "Passive/background Savant refresh disabled",
    }

# The shared app contains a daemon Savant worker. Ordinary Streamlit reruns and
# Save actions must never use it.
if "_v2610_refresh_savant_worker" in globals():
    _v2610_refresh_savant_worker = _manual_only_savant_background_worker


def _manual_only_live_board_savant_refresh():
    """One live Savant refresh, called only by the explicit board-refresh button."""
    root = Path(__file__).resolve().parent
    result = {"mode": "CACHE_ONLY", "ok": True}
    try:
        # UD2 owns a data-only live sync wrapper. Challenger owns the validated
        # Savant installer directly. Both are invoked only from Refresh Board.
        ud_sync = root / "tools" / "sync_savant_ud20.py"
        ch_live = root / "tools" / "refresh_savant_installer_v5.py"
        if ud_sync.exists():
            cmd = [_manual_savant_sys.executable, str(ud_sync)]
            mode = "UD2_LIVE_SAVANT_ON_BOARD_REFRESH"
        elif ch_live.exists():
            cmd = [
                _manual_savant_sys.executable, str(ch_live),
                "--out", str(root / "learning_data"),
            ]
            mode = "CHALLENGER_LIVE_SAVANT_ON_BOARD_REFRESH"
        else:
            cmd = None
            mode = "SERVICE_REFRESH_ON_BOARD_REFRESH"

        if cmd is not None:
            proc = _manual_savant_subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=720,
            )
            result = {
                "mode": mode,
                "ok": proc.returncode == 0,
                "detail": (proc.stdout or proc.stderr or "")[-1200:],
            }
        else:
            svc = globals().get("_v269_savant_service")
            aux = globals().get("_v2610_savant_aux_service")
            if callable(svc):
                svc().refresh(force=True)
            if callable(aux):
                aux().refresh(force=True)
            result = {"mode": mode, "ok": True}

        # Refresh cached readers only after the explicit network/data refresh.
        for name in (
            "_v269_load_savant_platoon", "_savant_aux_bundle_cached",
            "_v2610_savant_aux_bundle", "_v2610_load_savant_aux",
        ):
            obj = globals().get(name)
            try:
                if hasattr(obj, "clear"):
                    obj.clear()
            except Exception:
                pass
    except Exception as exc:
        result = {
            "mode": "BOARD_REFRESH_SAVANT_WARNING",
            "ok": False,
            "message": str(exc),
        }
    try:
        st.session_state["manual_refresh_v2_savant"] = result
        st.session_state["savant_refresh_policy"] = "BOARD_REFRESH_ONLY"
    except Exception:
        pass
    return result

# apply_manual_refresh_state_v2 wires refresh_btn to this name. Override that
# implementation here so the explicit button gets a true live refresh while
# passive reruns remain cache-only.
if "_state_v2_refresh_savant_for_board" in globals():
    _state_v2_refresh_savant_for_board = _manual_only_live_board_savant_refresh

try:
    st.session_state.setdefault("savant_refresh_policy", "BOARD_REFRESH_ONLY")
except Exception:
    pass
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("\r\n", "\n")

    # Belt-and-suspenders: kill every known timed/health background refresh gate.
    # Explicit board refresh uses _manual_only_live_board_savant_refresh instead.
    due_pat = r'due\s*=\s*bool\(\s*unresolved\s*or\s*health\.get\("status"\)\s*not\s*in\s*\{"CURRENT"\}\s*or\s*not\s*all_aux_current\s*or\s*due_by_time\s*\)'
    text = re.sub(
        due_pat,
        'due = False  # Savant Manual Only V3: no passive/timed network refresh',
        text,
        flags=re.MULTILINE,
    )
    text = text.replace("MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = True", "MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = False")

    if TAB_ANCHOR not in text:
        raise RuntimeError("top-level tabs anchor not found; app left unchanged")
    i = text.index(TAB_ANCHOR)
    return text[:i] + BLOCK + "\n\n" + text[i:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    a = ap.parse_args()
    p = Path(a.app)
    src = p.read_text(encoding="utf-8")
    out = patch_text(src)
    if out != src:
        p.write_text(out, encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        py_compile.compile(str(p), cfile=str(Path(td) / "app.pyc"), doraise=True)
    print(f"Savant Manual Only V3 READY: {p}")

if __name__ == "__main__":
    main()
