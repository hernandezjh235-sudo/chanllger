#!/usr/bin/env python3
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app.py"
RUNTIME = ROOT / "runtime_app.py"

# app.py remains the canonical pushed source. Runtime-only patches are applied
# to a fresh copy so Railway startup can never overwrite the pushed app file.
shutil.copy2(SOURCE, RUNTIME)

PATCHES = [
    "tools/apply_savant_k_authority_patch.py",
    "tools/apply_ml_weather_delay_patch.py",
    "tools/apply_ml_environment_v2_patch.py",
    "tools/apply_po_workload_v3_patch.py",
    "tools/apply_po_single_projection_v4_patch.py",
    "tools/apply_po_data_ui_v5_patch.py",
    "tools/apply_savant_display_bridge_v8.py",
    "tools/apply_manual_refresh_state_v2.py",
    "tools/apply_savant_manual_only_v3.py",
    "tools/apply_challenger_recency_shadow_v1.py",
    "tools/apply_challenger_recency_history_feed_v2.py",
    "tools/apply_recency_cache_guard_v3.py",
    "tools/apply_recency_lazy_guard_v2.py",
    "tools/apply_opponent_k_pipeline_cleanup_v1.py",
    "tools/apply_challenger_research_ml_v3.py",
    "tools/apply_ml_card_starter_f5_v1.py",
    # IMPORTANT: runtime stability must wrap the FINAL function bindings.
    # Keeping it last prevents later PO/ML/Savant patches from bypassing
    # lazy loading, same-board caches, and hidden-heavy-tab guards.
    "tools/apply_runtime_stability_v1.py",
]

for rel in PATCHES:
    script = ROOT / rel
    if not script.exists():
        raise FileNotFoundError(f"Required runtime patch missing: {rel}")
    subprocess.run(
        [sys.executable, str(script), "--app", str(RUNTIME)],
        cwd=str(ROOT),
        check=True,
    )

py_compile.compile(str(RUNTIME), doraise=True)

# Deployment smoke checks: never launch a partially-patched runtime.
runtime_text = RUNTIME.read_text(encoding="utf-8")
required_runtime_markers = [
    "CHALLENGER_UD2_MANUAL_REFRESH_STATE_V2_1_2026_08_28",
    "CHALLENGER_RESEARCH_ML_V3_2026_09_02",
    "ml_build_board = _impl_ml_build_board_research_v3",
    "K Shadow P(<5 IP) %",
    "K Shadow P(6+ IP) %",
    "K Shadow P(7+ IP) %",
    "ML F5 Strength Score V3",
    "ML Bullpen Hold Score V3",
    "ML Full Game Strength Score V3",
    "ML V3 Canonical Side Preserved",
    "CHALLENGER_ML_CARD_STARTER_F5_V1_2026_09_02",
    "ML F5 Projected Winner V3",
    "ML F5 Win Prob V3",
    "Pitcher K%",
    "WHIP",
    "K/9",
    "CHALLENGER_UD2_RUNTIME_STABILITY_V1_2026_08_28",
]
missing = [m for m in required_runtime_markers if m not in runtime_text]
if missing:
    raise RuntimeError("Runtime integration verification failed; missing: " + ", ".join(missing))

# Streamlit source watching is disabled in production. Data/CSV changes remain
# usable when the user explicitly refreshes the board, but file writes cannot
# cause an application-source reload loop.
os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
os.environ.setdefault("STREAMLIT_SERVER_RUN_ON_SAVE", "false")
port = str(os.environ.get("PORT") or "8080")

cmd = [
    "streamlit", "run", str(RUNTIME),
    "--server.port", port,
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
    "--server.fileWatcherType", "none",
    "--server.runOnSave", "false",
]
os.execvp(cmd[0], cmd)
