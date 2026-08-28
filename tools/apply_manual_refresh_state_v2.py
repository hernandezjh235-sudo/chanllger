#!/usr/bin/env python3
from __future__ import annotations
import argparse, py_compile, re, tempfile
from pathlib import Path

MARKER = "CHALLENGER_UD2_MANUAL_REFRESH_STATE_V2_2026_08_28"
STATE_ANCHOR = "dates = target_dates(day_mode)"

BLOCK = r'''
# =============================================================================
# CHALLENGER_UD2_MANUAL_REFRESH_STATE_V2_2026_08_28
# Runtime/state only. Projection math is untouched.
# Savant network work is tied to explicit board refresh, never Save/passive reruns.
# =============================================================================
try:
    MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = False
except Exception:
    pass

import pickle as _state_v2_pickle
import subprocess as _state_v2_subprocess
import sys as _state_v2_sys
import time as _state_v2_time


def _state_v2_cache_path():
    candidates = []
    try:
        mount = str(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
        if mount:
            candidates.append(Path(mount) / "mlb_live_board_state_v2.pkl")
    except Exception:
        pass
    candidates += [Path("/data/mlb_live_board_state_v2.pkl"), Path(__file__).resolve().parent / "learning_data" / ".mlb_live_board_state_v2.pkl"]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            probe = p.parent / ".board_state_probe"
            probe.write_bytes(b"1")
            probe.unlink(missing_ok=True)
            return p
        except Exception:
            pass
    return Path(__file__).resolve().parent / ".mlb_live_board_state_v2.pkl"


def _state_v2_save_board(picks):
    try:
        if not isinstance(picks, (list, tuple)) or not picks:
            return False
        p = _state_v2_cache_path()
        tmp = p.with_suffix(p.suffix + ".tmp")
        payload = {"saved_epoch": _state_v2_time.time(), "last_refresh_time": st.session_state.get("last_refresh_time"), "board": list(picks)}
        with tmp.open("wb") as fh:
            _state_v2_pickle.dump(payload, fh, protocol=_state_v2_pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _state_v2_restore_board(target_dates_value=None):
    try:
        p = _state_v2_cache_path()
        if not p.exists():
            return [], None
        with p.open("rb") as fh:
            payload = _state_v2_pickle.load(fh)
        if not isinstance(payload, dict):
            return [], None
        age = _state_v2_time.time() - float(payload.get("saved_epoch") or 0.0)
        if age < 0 or age > 129600:
            return [], None
        board = payload.get("board")
        if not isinstance(board, list) or not board:
            return [], None
        wanted = {str(x)[:10] for x in (target_dates_value or []) if str(x).strip()}
        board_dates = set()
        for row in board:
            if isinstance(row, dict):
                raw = row.get("Slate Date") or row.get("slate_date") or row.get("Game Date") or row.get("Date")
                if raw not in (None, ""):
                    board_dates.add(str(raw)[:10])
        if wanted and board_dates and wanted.isdisjoint(board_dates):
            return [], None
        return board, payload.get("last_refresh_time")
    except Exception:
        return [], None


def _state_v2_refresh_savant_for_board():
    result = {"mode": "CACHE_ONLY", "ok": True}
    try:
        ud_sync = Path(__file__).resolve().parent / "tools" / "sync_savant_ud20.py"
        if ud_sync.exists():
            proc = _state_v2_subprocess.run([_state_v2_sys.executable, str(ud_sync)], cwd=str(Path(__file__).resolve().parent), capture_output=True, text=True, timeout=180)
            result = {"mode": "UD20_SYNC_ON_BOARD_REFRESH", "ok": proc.returncode == 0}
        else:
            svc = globals().get("_v269_savant_service")
            aux = globals().get("_v2610_savant_aux_service")
            if callable(svc):
                try: svc().refresh(force=False)
                except Exception: pass
            if callable(aux):
                try: aux().refresh(force=False)
                except Exception: pass
            result = {"mode": "CHALLENGER_SAVANT_ON_BOARD_REFRESH", "ok": True}
        for name in ("_v269_load_savant_platoon", "_savant_aux_bundle_cached"):
            obj = globals().get(name)
            try:
                if hasattr(obj, "clear"):
                    obj.clear()
            except Exception:
                pass
    except Exception as exc:
        result = {"mode": "BOARD_REFRESH_SAVANT_WARNING", "ok": False, "message": str(exc)}
    try:
        st.session_state["manual_refresh_v2_savant"] = result
    except Exception:
        pass
    return result
'''.strip()


def _sub_once(pattern, repl, text, label):
    new, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"{label} anchor not found")
    return new


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("\r\n", "\n")
    if STATE_ANCHOR not in text:
        raise RuntimeError("state anchor not found")
    text = text.replace(STATE_ANCHOR, BLOCK + "\n\n" + STATE_ANCHOR, 1)

    init_pat = r'if "loaded_picks" not in st\.session_state:\s+st\.session_state\.loaded_picks = \[\]\s+if "last_refresh_time" not in st\.session_state:\s+st\.session_state\.last_refresh_time = None'
    init_repl = '''if "loaded_picks" not in st.session_state:\n    st.session_state.loaded_picks = []\nif "last_refresh_time" not in st.session_state:\n    st.session_state.last_refresh_time = None\nif not st.session_state.get("loaded_picks"):\n    if st.session_state.pop("_manual_refresh_v2_skip_restore_once", False):\n        _restored_board_v2, _restored_refresh_v2 = [], None\n    else:\n        _restored_board_v2, _restored_refresh_v2 = _state_v2_restore_board(dates)\n    if _restored_board_v2:\n        st.session_state.loaded_picks = _restored_board_v2\n        if _restored_refresh_v2 and not st.session_state.get("last_refresh_time"):\n            st.session_state.last_refresh_time = _restored_refresh_v2'''
    text = _sub_once(init_pat, init_repl, text, "loaded_picks init")

    clear_pat = r'(if st\.button\("🧹 Clear Streamlit Cache \+ Reload Live Lines", use_container_width=True\):\s+st\.cache_data\.clear\(\)\s+st\.session_state\.loaded_picks = \[\]\s+st\.session_state\.last_refresh_time = None)'
    text, _ = re.subn(clear_pat, r'\1\n        st.session_state["_manual_refresh_v2_skip_restore_once"] = True', text, count=1, flags=re.MULTILINE)

    due_pat = r'due\s*=\s*bool\(\s*unresolved\s*or\s*health\.get\("status"\)\s*not\s*in\s*\{"CURRENT"\}\s*or\s*not\s*all_aux_current\s*or\s*due_by_time\s*\)'
    text, due_count = re.subn(due_pat, 'due = False  # Manual Refresh V2: no passive/background Savant refresh', text, count=1, flags=re.MULTILINE)
    if due_count == 0:
        text = text.replace('"v112_savant_refresh_minutes": 30,', '"v112_savant_refresh_minutes": 52560000,', 1)

    refresh_pat = r'if refresh_btn:\s+all_rows = \[\]'
    text = _sub_once(refresh_pat, 'if refresh_btn:\n    _state_v2_refresh_savant_for_board()\n    all_rows = []', text, "refresh")

    seq_pat = r'st\.session_state\.loaded_picks = projections\s+st\.session_state\.last_refresh_time = now_iso\(\)'
    text = _sub_once(seq_pat, 'st.session_state.loaded_picks = projections\n    st.session_state.last_refresh_time = now_iso()\n    _state_v2_save_board(st.session_state.loaded_picks)', text, "successful refresh state")

    save_pat = r'if save_btn:\s+if not st\.session_state\.get\("loaded_picks"\):\s+st\.warning\("Refresh the live board first, inspect the lines, then save the official before-game snapshot\."\)\s+else:\s+added = save_many_once\(st\.session_state\.loaded_picks\)'
    save_repl = '''if save_btn:\n    if not st.session_state.get("loaded_picks"):\n        st.warning("Refresh the live board first, inspect the lines, then save the official before-game snapshot.")\n    else:\n        _state_v2_save_board(st.session_state.loaded_picks)\n        added = save_many_once(st.session_state.loaded_picks)'''
    text = _sub_once(save_pat, save_repl, text, "official save")

    text = text.replace("MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = True", "MERGE_V254_ENABLE_AUTO_LINEUP_REFRESH = False")
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
        py_compile.compile(str(path), cfile=str(Path(td) / "app.pyc"), doraise=True)
    print(f"Manual Refresh / Board State V2 READY: {path}")

if __name__ == "__main__":
    main()
