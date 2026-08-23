#!/usr/bin/env python3
from pathlib import Path
import pandas as pd

paths = [
    Path('learning_data/graded_history.csv'),
    Path('learning_data/pitching_outs_loss_lab_results.csv'),
    Path('pitching_outs_loss_lab_results.csv'),
]
for p in paths:
    print('\n' + '='*88)
    print('FILE', p, 'exists=', p.exists(), 'size=', p.stat().st_size if p.exists() else 0)
    if not p.exists():
        continue
    try:
        df = pd.read_csv(p, low_memory=False)
    except Exception as e:
        print('READ ERROR', repr(e)); continue
    print('ROWS', len(df), 'COLS', len(df.columns))
    print('COLUMNS')
    for c in df.columns:
        print(' -', c)
    market_cols = [c for c in df.columns if any(k in c.lower() for k in ['market','prop','type','category'])]
    for c in market_cols[:10]:
        try:
            print('VALUE_COUNTS', c, df[c].astype(str).value_counts().head(20).to_dict())
        except Exception:
            pass
    po_cols = [c for c in df.columns if any(k in c.lower() for k in [
        'outs','pitch count','pitch_count','p/ip','p/bf','beta ip','beta bf','hook','deep start','workload','actual ip','actual outs','po active','po workload'
    ])]
    print('PO-LIKE COLS', po_cols)
    if po_cols:
        print('NONNULL COUNTS', {c:int(df[c].notna().sum()) for c in po_cols[:80]})
    # print a few rows that look like pitching outs if identifiable
    mask = pd.Series(False, index=df.index)
    for c in df.columns:
        if any(k in c.lower() for k in ['market','prop','type','category']):
            try:
                mask = mask | df[c].astype(str).str.contains('OUT', case=False, na=False)
            except Exception:
                pass
    if 'UD Line' in df.columns and any('Out' in c for c in df.columns):
        mask = mask | pd.to_numeric(df['UD Line'], errors='coerce').notna()
    sample = df.loc[mask].head(5) if mask.any() else df.head(3)
    keep = [c for c in [
        'Pitcher','Player','Name','Date','Game Date','Opponent','Matchup','Market','Prop Type','UD Line','Line',
        'Beta Projection','Beta IP','Beta BF','Beta Lean','Beta Hit %','PO Active Projection','PO Active IP','PO Active Lean','PO Active Hit %',
        'Actual Outs','Actual IP','Result','PO Result','Pitch Count Avg L3','Pitch Count Avg L5','Pitch Count Avg L10','Last Start Pitch Count','Season Avg Pitch Count',
        'Recent Hook Rate','Deep Start Rate','Pitch Efficiency P/IP','Pitch Efficiency P/BF','Workload','Workload Sample','PO Fill Sample'
    ] if c in sample.columns]
    print('SAMPLE')
    print(sample[keep].to_string(index=False) if keep else sample.head().to_string(index=False))
