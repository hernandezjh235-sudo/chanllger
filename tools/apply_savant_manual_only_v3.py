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

def _manual_only_savant_background_worker(*args, **kwargs):
    return {
        "status": "SKIPPED",
        "mode": "MANUAL_BOARD_REFRESH_ONLY",
        "reason": "Passive/background Savant refresh disabled",
    }

# The large shared app has a daemon worker that can otherwise refresh Savant on
# ordinary Streamlit reruns. Rebinding the worker leaves cached data reads intact
# and does not affect _state_v2_refresh_savant_for_board().
if "_v2610_refresh_savant_worker" in globals():
    _v2610_refresh_savant_worker = _manual_only_savant_background_worker

try:
    st.session_state.setdefault("savant_refresh_policy", "BOARD_REFRESH_ONLY")
except Exception:
    pass
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("\r\n", "\n")

    # Belt-and-suspenders: kill all known timed/health-driven background refresh
    # gates before rebinding the worker. Explicit board refresh uses a separate path.
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
