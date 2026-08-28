#!/usr/bin/env python3
"""Runtime/UI stability patch for the shared Challenger/UD2 Streamlit shell.

Does not alter K/PO/ML projection math. It only:
- defaults the game feed to Today instead of Today+Tomorrow;
- disables automatic official-lineup-triggered full-board recomputation (manual refresh remains);
- lazy-loads expensive secondary tab renderers;
- prevents hidden diagnostics from building PO/ML until explicitly requested;
- caches same-board PO/ML/Beta DataFrames in Streamlit session state.
"""
from __future__ import annotations
import argparse, py_compile, tempfile
from pathlib import Path

MARKER = "CHALLENGER_UD2_RUNTIME_STABILITY_V1_2026_08_28"
TAB_ANCHOR = "tab_kproj, tab_brain, tab_beta_outs, tab_first_inning_k, tab_beta_ip_debug, tab_moneyline, tab_loss_lab, tab_iq, tab_30d_learning, tab_learning_lab, tab_calibration, tab2, tab3, tab4, tab5, tab6 = st.tabs(["
DAY_OLD = 'day_mode = st.radio("Game Feed", ["Today + Tomorrow", "Today", "Tomorrow"], index=0)'
DAY_NEW = 'day_mode = st.radio("Game Feed", ["Today + Tomorrow", "Today", "Tomorrow"], index=1)'
TAB4_OLD = '''with tab4:\n\n    st.markdown('<div class="section-title-pro">Statcast + Pitch-Type</div>', unsafe_allow_html=True)'''
TAB4_NEW = '''with tab4:\n\n    st.markdown('<div class="section-title-pro">Statcast + Pitch-Type</div>', unsafe_allow_html=True)\n\n    _stability_diag_enabled = _stability_offer("diag", "Deep Statcast / Projection Diagnostics")'''

BLOCK = r'''
# =============================================================================
# CHALLENGER_UD2_RUNTIME_STABILITY_V1_2026_08_28
# UI/runtime-only stability guard. Projection formulas and official model outputs
# are not modified. Expensive hidden tab work is deferred until requested.
# =============================================================================
RUNTIME_STABILITY_VERSION = "CHALLENGER_UD2_RUNTIME_STABILITY_V1_2026_08_28"
try:
    MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = False
except Exception:
    pass

_STABILITY_BUTTONS_SHOWN = set()

def _stability_generation():
    try:
        return str(st.session_state.get("last_refresh_time") or "NO_BOARD")
    except Exception:
        return "NO_BOARD"

def _stability_offer(key, label):
    key = str(key)
    gen = _stability_generation()
    state_key = f"_runtime_stability_loaded_{key}"
    try:
        if str(st.session_state.get(state_key) or "") == gen:
            return True
    except Exception:
        return False
    if key in _STABILITY_BUTTONS_SHOWN:
        return False
    _STABILITY_BUTTONS_SHOWN.add(key)
    try:
        st.caption(f"⚙️ Stability mode: {label} is deferred so loading the main board does not run every heavy market at once.")
        if st.button(f"Load {label}", key=f"_runtime_stability_button_{key}", use_container_width=True):
            st.session_state[state_key] = gen
            return True
    except Exception:
        return False
    return False

def _stability_lazy_wrap(fn, key, label):
    if not callable(fn):
        return fn
    if getattr(fn, "_runtime_stability_lazy", False):
        return fn
    def wrapped(*args, **kwargs):
        if not _stability_offer(key, label):
            return None
        return fn(*args, **kwargs)
    wrapped.__name__ = getattr(fn, "__name__", f"stability_{key}")
    wrapped._runtime_stability_lazy = True
    wrapped._runtime_stability_original = fn
    return wrapped

def _stability_rebind(name, key, label):
    fn = globals().get(name)
    if callable(fn):
        globals()[name] = _stability_lazy_wrap(fn, key, label)

# Keep the primary K board + integrated Undefeated/UD2 output immediate.
_stability_rebind("render_sports_analysis_brain_tab", "brain", "Sports Analysis Brain")
_stability_rebind("render_beta_pitching_outs_tab", "po", "Pitching Outs")
_stability_rebind("render_first_inning_k_tab", "fi_k", "1st Inning K")
_stability_rebind("render_beta_ip_debug_tab", "ip_debug", "IP / Workload Debug")
_stability_rebind("render_moneyline_edge_tab", "moneyline", "Moneyline")
_stability_rebind("render_true_projection_loss_lab_tab", "loss_lab", "Projection Loss Lab")
for _name in (
    "render_baseball_iq_tab", "render_unified_projection_brain_panel",
    "render_lineup_transition_audit_panel", "render_projection_doctor_panel",
    "render_hand_matchup_truth_audit_panel",
):
    _stability_rebind(_name, "iq", "Baseball IQ / Projection Doctor")
_stability_rebind("render_30_day_gamelog_learning_iq", "learning30", "30-Day Learning IQ")
_stability_rebind("render_learning_lab_tab", "learning_lab", "Learning Lab")
for _name in ("render_calibration_audit_tab", "render_advanced_daily_data_hub"):
    _stability_rebind(_name, "calibration", "Calibration / Daily Data Hub")

# Same-board DataFrame memoization; a new main-board refresh changes generation.
def _stability_cache_dataframe_function(name, key_prefix, arg_key=None):
    fn = globals().get(name)
    if not callable(fn) or getattr(fn, "_runtime_stability_cached", False):
        return
    def cached(*args, **kwargs):
        gen = _stability_generation()
        extra = ""
        if callable(arg_key):
            try:
                extra = str(arg_key(args, kwargs))
            except Exception:
                extra = ""
        cache_key = f"_runtime_stability_df_{key_prefix}_{extra}"
        try:
            pack = st.session_state.get(cache_key)
            if isinstance(pack, dict) and pack.get("generation") == gen and isinstance(pack.get("df"), pd.DataFrame):
                return pack["df"].copy()
        except Exception:
            pass
        out = fn(*args, **kwargs)
        try:
            if isinstance(out, pd.DataFrame):
                st.session_state[cache_key] = {"generation": gen, "df": out.copy()}
        except Exception:
            pass
        return out
    cached.__name__ = getattr(fn, "__name__", f"cached_{name}")
    cached._runtime_stability_cached = True
    cached._runtime_stability_original = fn
    globals()[name] = cached

_stability_cache_dataframe_function("build_undefeated_beta_table", "beta")
_stability_cache_dataframe_function("ml_build_board", "ml")
_stability_cache_dataframe_function(
    "_beta_projection_rows", "beta_market",
    arg_key=lambda a, k: (a[1] if len(a) > 1 else k.get("market_kind") or k.get("market") or "OUTS"),
)
try:
    st.caption("⚡ Runtime Stability V1 active · Today is the default feed · secondary heavy tabs load on demand · automatic lineup-triggered full rebuilds are off.")
except Exception:
    pass
'''.strip()

def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    if TAB_ANCHOR not in text:
        raise RuntimeError("top-level tabs anchor not found")
    if DAY_OLD in text:
        text = text.replace(DAY_OLD, DAY_NEW, 1)
    elif DAY_NEW not in text:
        raise RuntimeError("game-feed radio anchor not found")
    idx = text.index(TAB_ANCHOR)
    text = text[:idx] + BLOCK + "\n\n" + text[idx:]
    if TAB4_OLD in text:
        text = text.replace(TAB4_OLD, TAB4_NEW, 1)
    else:
        raise RuntimeError("tab4 diagnostics anchor not found")
    old_po = 'po_df = _beta_projection_rows(board, "OUTS") if "_beta_projection_rows" in globals() else pd.DataFrame()'
    new_po = 'po_df = _beta_projection_rows(board, "OUTS") if _stability_diag_enabled and "_beta_projection_rows" in globals() else pd.DataFrame()'
    old_ml = 'ml_df = ml_build_board(board) if "ml_build_board" in globals() else pd.DataFrame()'
    new_ml = 'ml_df = ml_build_board(board) if _stability_diag_enabled and "ml_build_board" in globals() else pd.DataFrame()'
    po_count = text.count(old_po)
    ml_count = text.count(old_ml)
    if po_count < 2 or ml_count < 1:
        raise RuntimeError(f"diagnostic heavy-call anchors unexpected: PO={po_count}, ML={ml_count}")
    text = text.replace(old_po, new_po)
    text = text.replace(old_ml, new_ml)
    return text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        py_compile.compile(str(path), cfile=str(Path(td)/"app.pyc"), doraise=True)
    print(f"Runtime Stability V1 READY: {path}")

if __name__ == "__main__":
    main()
