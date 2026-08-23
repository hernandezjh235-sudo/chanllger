#!/usr/bin/env python3
import os
import math
import numpy as np
import pandas as pd
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('patch', Path('tools/apply_po_workload_v3_patch.py'))
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
core = patch.BLOCK.split("_PO_V3_BASE_ROWS =", 1)[0]

ROLE = {'label':'STARTER','explicit_short_role':False,'ip_cap':None}
SOFT = (0.0, [])

def role_context(row):
    text = ' '.join(str(v) for v in row.values()).upper()
    if 'OPENER' in text:
        return {'label':'OPENER','explicit_short_role':True,'ip_cap':3.0}
    if 'PITCH LIMIT' in text:
        return {'label':'PITCH_LIMIT','explicit_short_role':True,'ip_cap':None}
    return dict(ROLE)

def blob(row):
    return ' '.join(str(v) for v in row.values()).upper()

def soft(row):
    return row.get('_soft', SOFT)

def rng(*parts):
    return np.random.default_rng(20260823)

ns = {
    'os': os, 'math': math, 'np': np, 'pd': pd,
    'datetime': __import__('datetime').datetime,
    '_po_workload_v2_role_context': role_context,
    '_po_workload_v2_blob': blob,
    '_po_workload_v2_soft_risk': soft,
    '_sim_stable_rng': rng,
    'STORAGE_DIR': 'learning_data',
}
exec(core, ns)
profile = ns['_po_v3_profile']

# 1) Established six-inning starter: recent workload must dominate a low legacy Beta IP.
established = {
    'Pitcher':'Established Starter','UD Line':17.5,'Beta IP':4.40,'Beta Projection':13.2,'Original IP':5.80,
    'APP97 Live L5 IP Avg':6.00,'APP97 Live L5 BF Median':25.0,
    'Pitch Count Avg L3':94,'Pitch Count Avg L5':95,'Pitch Count Avg L10':93,'Season Avg Pitch Count':94,'Last Start Pitch Count':96,
    'Pitch Efficiency P/BF':3.80,'Recent Hook Rate':20,'Deep Start Rate':60,'IP Volatility Score':35,
}
a = profile(established)
assert float(a['PO V3 Final IP']) >= 5.50, a
assert float(a['PO V3 Projection']) >= 16.5, a
assert float(a['PO V3 Data Completeness %']) >= 80, a

# 2) Soft hook/damage risk may lower mean gradually, but cannot collapse a normal starter.
soft_risk = dict(established)
soft_risk['_soft'] = (1.0, ['high hook','high damage','poor efficiency'])
soft_risk['Recent Hook Rate'] = 60
soft_risk['Damage Risk Label'] = 'HIGH'
b = profile(soft_risk)
assert float(b['PO V3 Final IP']) >= 5.20, b
assert float(a['PO V3 Final IP']) - float(b['PO V3 Final IP']) <= 0.40, (a,b)

# 3) Sparse normal starter: do not accept an unexplained 1-IP collapse; mark data low and cap probability.
sparse = {'Pitcher':'Sparse Starter','UD Line':17.5,'Beta IP':0.95,'Beta Projection':2.8,'Original IP':0.95,'IP Volatility Score':70}
c = profile(sparse)
assert float(c['PO V3 Final IP']) >= ns['PO_WORKLOAD_V3_CONFIG']['normal_starter_floor_ip'], c
assert c['PO V3 Workload Confidence'] == 'LOW', c
assert float(c['PO V3 Candidate Probability %']) <= ns['PO_WORKLOAD_V3_CONFIG']['low_data_prob_cap'], c
assert c['PO V3 Candidate Tier'] == 'TRACK ONLY', c

# 4) True opener remains allowed below the starter floor.
opener = dict(sparse)
opener['Role Note'] = 'OPENER confirmed'
d = profile(opener)
assert d['PO V3 Hard Restriction'] == 'YES', d
assert float(d['PO V3 Final IP']) <= 3.0, d

# 5) Repeated low pitch counts alone are not a hard restriction without IP/BF corroboration.
uncorroborated = dict(established)
uncorroborated.pop('APP97 Live L5 IP Avg', None)
uncorroborated.pop('APP97 Live L5 BF Median', None)
uncorroborated['Pitch Count Avg L5'] = 75
uncorroborated['Last Start Pitch Count'] = 68
e = profile(uncorroborated)
assert e['PO V3 Hard Restriction'] == 'NO', e
assert e['PO V3 Restriction Type'] == 'SHORT_PC_WATCH', e

print('PO Workload V3 semantic tests PASS')
for label, row in [('established',a),('soft_risk',b),('sparse',c),('opener',d),('short_pc_watch',e)]:
    print(label, {k:row.get(k) for k in ['PO V3 Final IP','PO V3 Projection','PO V3 Candidate Lean','PO V3 Candidate Probability %','PO V3 Data Completeness %','PO V3 Restriction Type','PO V3 Candidate Tier']})
