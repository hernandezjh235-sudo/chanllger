# -*- coding: utf-8 -*-
"""
CHALLENGER V1.11 — ACTUAL APP.PY ENTRYPOINT

This is the real Challenger app.py tracked by GitHub.
It materializes the validated V1.11 strikeout engine into this same app.py,
verifies the false-UNDER / preserve-control guards, then executes the
materialized application in the current Streamlit process.

The separate Undefeated production repository is never modified.
"""

from pathlib import Path

import challenger_bootstrap as _challenger_bootstrap


CHALLENGER_APP_ENTRYPOINT_MARKER = "CHALLENGER_V1_11_ACTUAL_APP_PY_2026_08_19"
EXPECTED_ENGINE_MARKER = "UNDEFEATED_BETA_V1_11_FALSE_UNDER_GUARD_2026_08_19"
EXPECTED_FALSE_UNDER_FN = "def _ub_v111_false_under_profile"
EXPECTED_PRESERVE_CONTROL_FN = "def _ub_v111_preserve_control_under_profile"


def _materialize_and_run_challenger() -> None:
    app_path = Path(__file__).resolve()

    # Build the validated Challenger directly into this exact app.py path.
    _challenger_bootstrap.main()

    runtime_source = app_path.read_text(encoding="utf-8")

    # Fail closed: never run a partially built or stale Challenger.
    required = (
        EXPECTED_ENGINE_MARKER,
        EXPECTED_FALSE_UNDER_FN,
        EXPECTED_PRESERVE_CONTROL_FN,
        "UB OVER Floor Survival",
        "UB Low-Line Threshold Status",
        "Savant Shadow Status",
    )
    missing = [marker for marker in required if marker not in runtime_source]
    if missing:
        raise RuntimeError(
            "Challenger V1.11 materialization failed; required markers missing: "
            + ", ".join(missing)
        )

    # The bootstrap must have replaced this small entrypoint with the full engine.
    if CHALLENGER_APP_ENTRYPOINT_MARKER in runtime_source:
        raise RuntimeError(
            "Challenger bootstrap did not replace app.py with the validated engine."
        )

    code = compile(runtime_source, str(app_path), "exec")
    exec(code, globals(), globals())


_materialize_and_run_challenger()
