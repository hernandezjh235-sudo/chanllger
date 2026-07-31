MASTER PO — FINAL PITCHING OUTS CARD RENDER FIX
===================================================

FILE
master_PO_PO_CARDS_RENDER_FINAL.py

ROOT CAUSE
The generated player-card HTML was being sent through Markdown. Because the
generated HTML contained indentation, Streamlit/Markdown could interpret it as
a code block and display the raw <div> markup instead of rendering the cards.

FINAL FIX
- Build the exact same PO card HTML.
- Strip leading indentation from every generated HTML line.
- Prefer st.html(full_html) when the deployed Streamlit version supports it.
- Fall back to st.markdown(..., unsafe_allow_html=True) only when st.html is unavailable.
- No iframe/components renderer is used.
- Existing PO card data, styling, and IP-needed-to-win thresholds remain intact.

MODEL SAFETY
- K projection math: UNCHANGED
- Pitching Outs projection math: UNCHANGED
- BF/workload math: UNCHANGED
- Hybrid/OG-shadow logic: UNCHANGED
- Expected lineup/order logic: UNCHANGED
- Line/edge math: UNCHANGED
- Calibration/learning/grading: UNCHANGED
- Only changed function: _po_render_player_cards

VALIDATION
- Python compile: PASSED
- Only UI renderer changed: PASSED
- No functions added: PASSED
- No functions removed: PASSED
- Direct st.html preferred: PASSED
- Markdown fallback preserved: PASSED
- HTML indentation stripped: PASSED
- IP-needed logic preserved: PASSED
- PO data fields preserved: PASSED
- Single build_kproj_table: PASSED
- No duplicate module-level functions: PASSED

FUNCTION DIFF
- Changed functions: ['_po_render_player_cards']
- Added functions: []
- Removed functions: []

SOURCE
- Lines: 52,128
- Size: 2.37 MB
- Duplicate module-level functions: 0
