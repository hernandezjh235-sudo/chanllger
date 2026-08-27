#!/usr/bin/env python3
"""PO-only V5: repository workload fallback + one public elite PO card."""
import argparse, ast, py_compile, tempfile
from pathlib import Path
MARKER='CHALLENGER_PO_DATA_UI_V5_2026_08_26'
BETA='_beta_projection_rows = _impl_beta_projection_rows_po_v4'
RENDER='render_beta_pitching_outs_tab = _impl_render_beta_pitching_outs_tab_po_v4'
BLOCK=r'''
# CHALLENGER_PO_DATA_UI_V5_2026_08_26
PO_V5_VERSION='PO_DATA_UI_V5_2026_08_26'
PO_V5_HISTORY='Pitch (3) (1) (1).csv'

def _po5_n(v,d=np.nan):
    try:
        x=float(v);return x if np.isfinite(x) else d
    except Exception:return d

def _po5_norm(v):
    try:return _tpl_norm_name(v)
    except Exception:return ' '.join(str(v or '').lower().replace('.',' ').replace('-',' ').split())

try:_po5_cache=st.cache_data(ttl=21600,show_spinner=False)
except Exception:_po5_cache=lambda f:f

@_po5_cache
def _po5_hist():
    paths=[]
    try:
        s=str(globals().get('STORAGE_DIR','') or '').strip()
        if s:paths.append(os.path.join(s,PO_V5_HISTORY))
    except Exception:pass
    paths += [os.path.join('learning_data',PO_V5_HISTORY),PO_V5_HISTORY]
    for p in paths:
        try:
            if not os.path.exists(p):continue
            d=pd.read_csv(p,low_memory=False)
            if d.empty or 'Pitcher' not in d.columns:continue
            d=d.copy();d['_n']=d['Pitcher'].map(_po5_norm);d['_d']=pd.to_datetime(d.get('Date'),errors='coerce')
            for c in ['IP','BF','Pitch Count']:d[c]=pd.to_numeric(d.get(c),errors='coerce')
            return d
        except Exception:pass
    return pd.DataFrame()

def _po5_local(name):
    d=_po5_hist();k=_po5_norm(name)
    if d.empty or not k:return {'ok':False}
    x=d[d['_n']==k].copy()
    if x.empty:return {'ok':False}
    start=(x['IP']>=3)|(x['BF']>=12)|(x['Pitch Count']>=45)
    if start.any():x=x[start]
    if x.empty:return {'ok':False}
    x=x.sort_values('_d');l3=x.tail(3);l5=x.tail(5);l10=x.tail(10)
    def a(f,c):
        z=pd.to_numeric(f[c],errors='coerce').dropna();return float(z.mean()) if len(z) else np.nan
    def m(f,c):
        z=pd.to_numeric(f[c],errors='coerce').dropna();return float(z.median()) if len(z) else np.nan
    ip=pd.to_numeric(l10['IP'],errors='coerce');bf=pd.to_numeric(l10['BF'],errors='coerce');pc=pd.to_numeric(l10['Pitch Count'],errors='coerce')
    q=(ip.notna()&pc.notna()&(ip>0));q2=(bf.notna()&pc.notna()&(bf>0));last=x.iloc[-1];dt=last.get('_d');age=np.nan
    try:
        if pd.notna(dt):age=max(0,(pd.Timestamp.now().normalize()-pd.Timestamp(dt).normalize()).days)
    except Exception:pass
    return {'ok':True,'ip5':a(l5,'IP'),'bf5':a(l5,'BF'),'bfm5':m(l5,'BF'),'bfm10':m(l10,'BF'),'pc3':a(l3,'Pitch Count'),'pc5':a(l5,'Pitch Count'),'pc10':a(l10,'Pitch Count'),'pcs':a(x,'Pitch Count'),'pclast':_po5_n(last.get('Pitch Count')),'pcmax':float(pc.max()) if pc.notna().any() else np.nan,'ppi':float(pc[q].sum()/ip[q].sum()) if q.any() else np.nan,'pbf':float(pc[q2].sum()/bf[q2].sum()) if q2.any() else np.nan,'deep':float((ip.dropna()>=6).mean()*100) if ip.notna().any() else np.nan,'early':float((ip.dropna()<5).mean()*100) if ip.notna().any() else np.nan,'lastip':_po5_n(last.get('IP')),'lastd':'' if pd.isna(dt) else pd.Timestamp(dt).date().isoformat(),'age':age}

def _po5_enrich(r):
    r=dict(r);live=_po_v3_text(r,['PO V4 Live'],'NO').upper()=='YES';h=_po5_local(_po_v3_text(r,['Pitcher'],''));used=False
    if h.get('ok'):
        pairs=[('APP97 Live L5 IP Avg','ip5'),('Recent IP L5','ip5'),('APP97 Live L5 BF Median','bfm5'),('APP97 Live L10 BF Median','bfm10'),('Recent BF L5','bf5'),('Pitch Count Avg L3','pc3'),('Pitch Count Avg L5','pc5'),('Pitch Count Avg L10','pc10'),('Season Avg Pitch Count','pcs'),('Last Start Pitch Count','pclast'),('Max Pitch Count L10','pcmax'),('Pitch Efficiency P/IP','ppi'),('Pitch Efficiency P/BF','pbf'),('Deep Start Rate','deep'),('Recent Hook Rate','early')]
        for k,z in pairs:
            if _po4_missing(r.get(k)) and np.isfinite(_po5_n(h.get(z))):r[k]=h[z];used=True
    age=_po5_n(h.get('age')) if h.get('ok') else np.nan;stale=h.get('ok') and np.isfinite(age) and age>14
    r['PO V5 Workload Source']='LIVE MLB'+(' + LOCAL FILL' if used else '') if live else ('LOCAL GAME LOG' if h.get('ok') else 'FALLBACK MODEL')
    r['PO V5 Data State']='LIVE' if live else 'HISTORICAL' if stale else 'LOCAL CURRENT' if h.get('ok') else 'LIMITED'
    r['PO V5 Local Age Days']=round(age,0) if np.isfinite(age) else ''
    r['PO V5 Local Last Start Date']=h.get('lastd','') if h.get('ok') else ''
    r['PO V5 Local Last Start IP']=h.get('lastip','') if h.get('ok') else ''
    return r

_PO5_BASE=_impl_beta_projection_rows_po_v4
def _impl_beta_projection_rows_po_v5(board,market):
    d=_PO5_BASE(board,market)
    if not isinstance(d,pd.DataFrame) or d.empty or str(market or '').upper()!='OUTS':return d
    out=[]
    for _,z in d.iterrows():
        r=z.to_dict()
        try:
            r=_po5_enrich(r);r.update(_po_v3_profile(r));state=r.get('PO V5 Data State')
            if state=='HISTORICAL':
                r['PO V3 Data Completeness %']=min(_po5_n(r.get('PO V3 Data Completeness %'),60),60);r['PO V3 Workload Confidence']='LIMITED · STALE HISTORY'
            r.update(_po4_final(r));r['PO V5 Version']=PO_V5_VERSION
        except Exception as e:r['PO Final Tier']='TRACK ONLY PO';r['PO V5 Error']=str(e)[:120]
        out.append(r)
    return pd.DataFrame(out)

def _po5_t(v,d=1,s=''):
    x=_po5_n(v);return '—' if not np.isfinite(x) else f'{x:.{d}f}{s}'

def _po_render_player_cards(df,board=None,limit=None):
    if not isinstance(df,pd.DataFrame) or df.empty:return 0
    cards=[]
    for _,z in (df.head(int(limit)) if limit else df).iterrows():
        r=z.to_dict();name=_po_v3_text(r,['Pitcher'],'Pitcher');match=_po_v3_text(r,['Matchup'],'');away,home=_po_card_matchup_teams(match) if '_po_card_matchup_teams' in globals() else ('','');tm=away or home
        try:
            if board and '_kcard_board_lookup' in globals():p=_kcard_board_lookup(board).get(_tpl_norm_name(name),{});tm=_kcard_pitcher_team(r,p) or tm
        except Exception:pass
        u=_po_card_team_logo(tm) if '_po_card_team_logo' in globals() else '';logo=f"<img class='po5logo' src='{html.escape(u)}'/>" if u else f"<div class='po5logo'>{html.escape((tm or 'MLB')[:3])}</div>"
        line=_po_v3_num(r,['UD Line','Line'],np.nan);proj=_po_v3_num(r,['PO Final Projection'],np.nan);ip=_po_v3_num(r,['PO Final IP'],np.nan);side=_po_v3_text(r,['PO Final Side'],'PASS').upper();prob=_po_v3_num(r,['PO Final Probability %'],np.nan);edge=_po_v3_num(r,['PO Final Edge'],np.nan);tier=_po_v3_text(r,['PO Final Tier'],'TRACK ONLY PO');data=_po_v3_num(r,['PO V3 Data Completeness %'],np.nan);state=_po_v3_text(r,['PO V5 Data State'],'LIMITED');source=_po_v3_text(r,['PO V5 Workload Source'],'FALLBACK MODEL');conflict=_po_v3_text(r,['PO Final Conflict'],'NO')=='YES'
        l5ip=_po_v3_num(r,['PO V4 L5 IP','PO V3 Recent IP Baseline','Recent IP L5'],np.nan);l5bf=_po_v3_num(r,['PO V4 L5 BF','PO V3 Recent BF Baseline','Recent BF L5'],np.nan);l5pc=_po_v3_num(r,['PO V4 L5 PC','PO V3 Recent PC Baseline','Pitch Count Avg L5'],np.nan);ppi=_po_v3_num(r,['PO V4 P/IP','Pitch Efficiency P/IP'],np.nan);deep=_po_v3_num(r,['PO V4 6+ IP %','Deep Start Rate'],np.nan);early=_po_v3_num(r,['PO V4 Early Exit %','Recent Hook Rate'],np.nan);lastip=_po_v3_num(r,['PO V4 Last Start IP','PO V5 Local Last Start IP'],np.nan);lastpc=_po_v3_num(r,['PO V4 Last Start PC','Last Start Pitch Count'],np.nan);lastd=_po_v3_text(r,['PO V4 Last Start Date','PO V5 Local Last Start Date'],'')
        cls='over' if side=='OVER' else 'under' if side=='UNDER' else 'track';sc='live' if state=='LIVE' else 'hist' if state=='HISTORICAL' else 'current' if state=='LOCAL CURRENT' else 'limited';agree='Internal workload disagreement · final public side only.' if conflict else 'Workload models aligned.'
        cards.append(f"""<article class='po5 {cls}'><header><div class='id'>{logo}<div><h3>{html.escape(name)}</h3><small>{html.escape(match)}</small></div></div><div class='badges'><em class='{sc}'>{html.escape(state)}</em><em>{html.escape(tier)}</em></div></header><section class='hero'><div><span>FINAL PROJECTED OUTS</span><strong>{_po5_t(proj)}</strong><b>{html.escape(side)} {_po5_t(line)}</b><small>{_po5_t(ip,2)} expected IP · {_po5_t(prob)}% probability</small></div><aside><span>EDGE</span><b>{_po5_t(edge)}</b></aside><aside><span>DATA</span><b>{_po5_t(data,0,'%')}</b><small>{html.escape(source)}</small></aside></section><div class='grid'><div><span>L5 IP</span><b>{_po5_t(l5ip,2)}</b></div><div><span>L5 BF</span><b>{_po5_t(l5bf)}</b></div><div><span>L5 PITCHES</span><b>{_po5_t(l5pc,0)}</b></div><div><span>P / IP</span><b>{_po5_t(ppi)}</b></div><div><span>6+ IP</span><b>{_po5_t(deep,0,'%')}</b></div><div><span>EARLY EXIT</span><b>{_po5_t(early,0,'%')}</b></div></div><footer><b>Last start:</b> {_po5_t(lastip,2)} IP · {_po5_t(lastpc,0)} pitches{(' · '+html.escape(lastd)) if lastd else ''}<i>{html.escape(agree)}</i></footer></article>""")
    css="""<style>.po5wrap{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.po5{background:radial-gradient(circle at 8% 0,rgba(255,42,145,.22),transparent 34%),radial-gradient(circle at 100% 20%,rgba(42,190,255,.14),transparent 30%),linear-gradient(145deg,#140a24,#081321);border:1px solid #4b3561;border-radius:20px;padding:15px;color:#f7f8ff;box-shadow:0 14px 32px rgba(0,0,0,.28)}.po5.over{border-top:3px solid #43e6ac}.po5.under{border-top:3px solid #ffd85e}.po5.track{border-top:3px solid #91a0b6}.po5 header,.po5 .id,.po5 .badges{display:flex;align-items:center}.po5 header{justify-content:space-between;gap:8px}.po5 .id{gap:9px}.po5logo{width:43px;height:43px;object-fit:contain;border-radius:50%;background:#0d1727;padding:5px}.po5 h3{margin:0;font-size:18px}.po5 small{color:#a4aec0}.po5 .badges{gap:4px;flex-wrap:wrap;justify-content:flex-end}.po5 em{font-style:normal;font-size:8px;font-weight:900;border:1px solid #6d597d;border-radius:999px;padding:5px 7px}.po5 em.live{color:#66ebba;border-color:#2b7b61}.po5 em.hist{color:#ffd06d;border-color:#806027}.po5 em.current{color:#79ddff;border-color:#2b6d88}.hero{display:grid;grid-template-columns:1.65fr .65fr .8fr;gap:7px;margin-top:11px}.hero>div,.hero aside,.grid>div{background:#091423d9;border:1px solid #372c4a;border-radius:13px;padding:10px}.po5 span{display:block;color:#929db0;font-size:8px;font-weight:900;letter-spacing:.08em}.hero strong{display:block;font-size:34px;line-height:1;color:#ff49a3;margin:7px 0 5px}.hero aside b{display:block;font-size:19px;margin-top:10px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}.grid b{display:block;margin-top:4px}.po5 footer{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:8px;padding-top:8px;border-top:1px solid #30273f;color:#aab4c4;font-size:9px}.po5 footer i{font-style:normal;color:#d5bcff}@media(max-width:900px){.po5wrap{grid-template-columns:1fr}}</style>"""
    h=css+"<div class='po5wrap'>"+''.join(cards)+"</div>";st.html(h) if hasattr(st,'html') else st.markdown(h,unsafe_allow_html=True);return len(cards)

def _impl_render_beta_pitching_outs_tab_po_v5(board):
    _po_v3_legacy_render_po(board)
    s=_po_v3_calibration_summary()
    if isinstance(s,pd.DataFrame) and not s.empty:
        with st.expander('Pitching Outs — internal projection audit',expanded=False):st.caption('Cards show one final projection and one final side. Internal V2/V3 stay hidden here for calibration.');st.dataframe(s,use_container_width=True,hide_index=True)
'''.strip()

def patch_text(t):
    if MARKER in t:return t
    if t.count(BETA)!=1 or t.count(RENDER)!=1:raise RuntimeError('Apply PO V3 and PO V4 before PO V5')
    i=min(t.index(BETA),t.index(RENDER));t=t[:i]+BLOCK+'\n\n'+t[i:];t=t.replace(BETA,'_beta_projection_rows = _impl_beta_projection_rows_po_v5',1).replace(RENDER,'render_beta_pitching_outs_tab = _impl_render_beta_pitching_outs_tab_po_v5',1);ast.parse(t);return t

def main():
    a=argparse.ArgumentParser();a.add_argument('--app',default='app.py');a.add_argument('--check-only',action='store_true');x=a.parse_args();p=Path(x.app);o=p.read_text(encoding='utf-8-sig');n=patch_text(o)
    with tempfile.TemporaryDirectory() as d:q=Path(d)/'x.py';q.write_text(n,encoding='utf-8');py_compile.compile(str(q),doraise=True)
    if x.check_only:print('PO Data/UI V5 CHECK PASS');return 0
    if n!=o:tmp=p.with_suffix(p.suffix+'.po_v5_tmp');tmp.write_text(n,encoding='utf-8');tmp.replace(p)
    print('PO Data/UI V5 READY');return 0
if __name__=='__main__':raise SystemExit(main())
