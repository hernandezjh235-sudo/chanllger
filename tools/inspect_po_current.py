#!/usr/bin/env python3
from pathlib import Path
import ast

PATH = Path('app.py')
text = PATH.read_text(encoding='utf-8-sig')
lines = text.splitlines()
want = {
    '_po_workload_v2_role_context',
    '_po_workload_v2_hard_restriction',
    '_po_workload_v2_expected_pitch_count',
    '_po_workload_v2_capacity_ip',
    '_po_workload_v2_soft_risk',
    '_po_workload_v2_support',
    '_po_workload_v2_active_selector',
    '_simulate_po_row',
    '_po_render_player_cards',
    '_impl_render_beta_pitching_outs_tab_06',
    'grade_pitching_outs_loss_lab',
    'build_po_loss_lab_summary',
}

tree = ast.parse(text)
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in want:
        print('\n' + '='*80)
        print(f'FUNCTION {node.name} lines {node.lineno}-{node.end_lineno}')
        print('='*80)
        print('\n'.join(lines[node.lineno-1:node.end_lineno]))

for marker in [
    'PO_WORKLOAD_V2_ACTIVE_FOR_SELECTOR',
    'render_beta_pitching_outs_tab =',
    'PO_DATA_FILL_VERSION',
    'TRUE_PROB_SIM_VERSION',
]:
    print('\n' + '='*80)
    print('MARKER', marker)
    print('='*80)
    for i, line in enumerate(lines, 1):
        if marker in line:
            lo=max(1,i-8); hi=min(len(lines),i+12)
            print('\n'.join(f'{j}: {lines[j-1]}' for j in range(lo,hi+1)))
