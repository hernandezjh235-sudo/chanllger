#!/usr/bin/env python3
"""PO-only V4: live MLB workload fill + one public Pitching Outs projection."""
import argparse, ast, py_compile, tempfile
from pathlib import Path
MARKER='CHALLENGER_PO_SINGLE_V4_2026_08_26'
BETA='_beta_projection_rows = _impl_beta_projection_rows_po_v3'
RENDER='render_beta_pitching_outs_tab = _impl_render_beta_pitching_outs_tab_po_v3'
BLOCK=r'''
# CHALLENGER_PO_SINGLE_V4_2026_08_26
PO_SINGLE_V4_VERSION='PO_SINGLE_V4_2026_08_26'
PO_V4_API='https://statsapi.mlb.com/api/v1'

def _po4_f(v,d=np.nan):
    try:
        x=float(v); return x if np.isfinite(x) else d
    except Exception:return d

def _po4_missing(v):
    return v is None or str(v).strip() in {'','—','-','nan','NaN','None'}

def _po4_fill(r,k,v):
    if _po4_missing(r.get(k)) and np.isfinite(_po4_f(v)):r[k]=v

def _po4_outs(ip):
    try:
        s=str(ip); a,b=(s.split('.',1)+['0'])[:2]; return int(float(a))*3+(int(b[:1]) if b[:1] in {'0','1','2'} else 0)
    except Exception:return np.nan

def _po4_ip(outs):
    x=_po4_f(outs)
    return (int(round(x))//3)+(int(round(x))%3)/3 if np.isfinite(x) else np.nan

try:_po4_cache=st.cache_data(ttl=21600,show_spinner=False)
except Exception:_po4_cache=lambda f:f

@_po4_cache
def _po4_pid(name):
    try:
        q=requests.get(f'{PO_V4_API}/people/search',params={'names':str(name)},timeout=4,headers={'User-Agent':'Challenger-PO/4'} )
        ps=(q.json() or {}).get('people',[]) if q.ok else []
        if not ps:return None
        n=str(name).lower().replace('.','').strip()
        exact=[p for p in ps if str(p.get('fullName','')).lower().replace('.','').strip()==n]
        return int((exact or ps)[0]['id'])
    except Exception:return None

@_po4_cache
def _po4_log(pid,season):
    try:
        q=requests.get(f'{PO_V4_API}/people/{int(pid)}/stats',params={'stats':'gameLog','group':'pitching','season':int(season)},timeout=5,headers={'User-Agent':'Challenger-PO/4'})
        if not q.ok:return []
        return [s for b in (q.json() or {}).get('stats',[]) for s in b.get('splits',[])]
    except Exception:return []

def _po4_live(name):
    pid=_po4_pid(name)
    if not pid:return {'ok':False}
    season=getattr(datetime.now(),'year',2026)
    ss=_po4_log(pid,season) or _po4_log(pid,season-1)
    a=[]
    for s in ss:
        z=s.get('stat',{}); o=_po4_outs(z.get('inningsPitched')); gs=_po4_f(z.get('gamesStarted'),0)
        if not (gs>=1 or _po4_f(o,0)>=9):continue
        pc=_po4_f(z.get('numberOfPitches')); pc=pc if np.isfinite(pc) else _po4_f(z.get('pitchesThrown'))
        a.append({'d':str(s.get('date','')),'o':o,'bf':_po4_f(z.get('battersFaced')),'pc':pc})
    if not a:return {'ok':False}
    a=sorted(a,key=lambda x:x['d']); l3=a[-3:]; l5=a[-5:]; l10=a[-10:]
    def avg(xs,k):
        v=[x[k] for x in xs if np.isfinite(_po4_f(x[k]))]; return float(np.mean(v)) if v else np.nan
    def med(xs,k):
        v=[x[k] for x in xs if np.isfinite(_po4_f(x[k]))]; return float(np.median(v)) if v else np.nan
    def rate(fn):
        v=[x['o'] for x in l10 if np.isfinite(_po4_f(x['o']))]; return 100*sum(fn(x) for x in v)/len(v) if v else np.nan
    tpc=sum(x['pc'] for x in l10 if np.isfinite(_po4_f(x['pc']))); tout=sum(x['o'] for x in l10 if np.isfinite(_po4_f(x['pc'])) and np.isfinite(_po4_f(x['o']))); tbf=sum(x['bf'] for x in l10 if np.isfinite(_po4_f(x['pc'])) and np.isfinite(_po4_f(x['bf'])))
    last=a[-1]; pcs=[x['pc'] for x in l10 if np.isfinite(_po4_f(x['pc']))]
    return {'ok':True,'n':len(l10),'ip5':_po4_ip(avg(l5,'o')),'bf5':avg(l5,'bf'),'bfm5':med(l5,'bf'),'bfm10':med(l10,'bf'),'pc3':avg(l3,'pc'),'pc5':avg(l5,'pc'),'pc10':avg(l10,'pc'),'pcs':avg(a,'pc'),'pclast':last['pc'],'pcmax':max(pcs) if pcs else np.nan,'ppi':tpc/(tout/3) if tout else np.nan,'pbf':tpc/tbf if tbf else np.nan,'deep':rate(lambda x:x>=18),'seven':rate(lambda x:x>=21),'early':rate(lambda x:x<15),'lastip':_po4_ip(last['o']),'lastd':last['d']}

def _po4_enrich(r):
    r=dict(r); name=_po_v3_text(r,['Pitcher'],''); x=_po4_live(name); r['PO V4 Live']='YES' if x.get('ok') else 'NO'
    if not x.get('ok'):return r
    for k,v in [('APP97 Live L5 IP Avg',x['ip5']),('Recent IP L5',x['ip5']),('APP97 Live L5 BF Median',x['bfm5']),('APP97 Live L10 BF Median',x['bfm10']),('Recent BF L5',x['bf5']),('Pitch Count Avg L3',x['pc3']),('Pitch Count Avg L5',x['pc5']),('Pitch Count Avg L10',x['pc10']),('Season Avg Pitch Count',x['pcs']),('Last Start Pitch Count',x['pclast']),('Max Pitch Count L10',x['pcmax']),('Pitch Efficiency P/IP',x['ppi']),('Pitch Efficiency P/BF',x['pbf']),('Deep Start Rate',x['deep']),('Recent Hook Rate',x['early'])]:_po4_fill(r,k,v)
    r.update({'PO V4 L5 IP':x['ip5'],'PO V4 L5 BF':x['bf5'],'PO V4 L5 PC':x['pc5'],'PO V4 P/IP':x['ppi'],'PO V4 6+ IP %':x['deep'],'PO V4 7+ IP %':x['seven'],'PO V4 Early Exit %':x['early'],'PO V4 Recent Starts':x['n'],'PO V4 Last Start IP':x['lastip'],'PO V4 Last Start PC':x['pclast'],'PO V4 Last Start Date':x['lastd']})
    return r

def _po4_final(r):
    line=_po_v3_num(r,['UD Line','Line'],np.nan); v2=_po_v3_num(r,['PO Active Projection','PO Workload V2 Projection','Beta Projection'],np.nan); v3=_po_v3_num(r,['PO V3 Projection'],np.nan); data=_po_v3_num(r,['PO V3 Data Completeness %'],0); rc=_po_v3_num(r,['PO V3 Restriction Confidence %'],0); live=_po_v3_text(r,['PO V4 Live'],'NO')=='YES'
    if np.isfinite(v2) and np.isfinite(v3):
        w=.65 if data>=80 else .55 if data>=65 else .4 if data>=50 else .2
        if not live:w=min(w,.35)
        p=round(v2*(1-w)+v3*w,1); src=f'V2/V3 workload ensemble · {int(w*100)}% live-workload weight'
    elif np.isfinite(v3):p,src=v3,'Workload projection'
    else:p,src=v2,'Production fallback'
    e=p-line if np.isfinite(p) and np.isfinite(line) else np.nan; side='OVER' if np.isfinite(e) and e>0 else 'UNDER' if np.isfinite(e) and e<0 else 'PASS'
    s2='OVER' if np.isfinite(v2) and v2>line else 'UNDER' if np.isfinite(v2) and v2<line else 'PASS'; s3='OVER' if np.isfinite(v3) and v3>line else 'UNDER' if np.isfinite(v3) and v3<line else 'PASS'; conflict=s2 in {'OVER','UNDER'} and s3 in {'OVER','UNDER'} and s2!=s3
    prob,ov,un,sd=_po_v3_candidate_probability(r,p,line,side,data,rc) if np.isfinite(p) else (np.nan,)*4
    if np.isfinite(_po4_f(prob)) and conflict:prob=min(prob-2,60)
    ae=abs(e) if np.isfinite(e) else 0
    tier='TRACK ONLY PO' if data<45 or conflict else 'OFFICIAL PO' if ae>=3 and prob>=62 and data>=65 else 'PLAYABLE PO' if ae>=1.75 and prob>=57 and data>=55 else 'LEAN / TRACK PO'
    return {'PO Final Projection':p,'PO Final IP':round(p/3,2) if np.isfinite(p) else '','PO Final Side':side,'PO Final Edge':round(e,2) if np.isfinite(e) else '','PO Final Probability %':round(prob,1) if np.isfinite(_po4_f(prob)) else '','PO Final Tier':tier,'PO Final Conflict':'YES' if conflict else 'NO','PO Final Source':src}

_PO4_BASE=_impl_beta_projection_rows_po_v3
def _impl_beta_projection_rows_po_v4(board,market):
    df=_PO4_BASE(board,market)
    if not isinstance(df,pd.DataFrame) or df.empty or str(market).upper()!='OUTS':return df
    out=[]
    for _,z in df.iterrows():
        r=z.to_dict()
        try:r=_po4_enrich(r); r.update(_po_v3_profile(r)); r.update(_po4_final(r))
        except Exception as e:r['PO Final Tier']='TRACK ONLY PO';r['PO V4 Error']=str(e)[:120]
        out.append(r)
    return pd.DataFrame(out)

def _po4_txt(v,d=1,s=''):
    x=_po4_f(v);return '—' if not np.isfinite(x) else f'{x:.{d}f}{s}'

def _po_render_player_cards(df,board=None,limit=None):
    if not isinstance(df,pd.DataFrame) or df.empty:return 0
    cards=[]
    for _,z in (df.head(int(limit)) if limit else df).iterrows():
        r=z.to_dict(); name=_po_v3_text(r,['Pitcher'],'Pitcher'); matchup=_po_v3_text(r,['Matchup'],''); away,home=_po_card_matchup_teams(matchup) if '_po_card_matchup_teams' in globals() else ('',''); tm=away or home
        try:
            if board and '_kcard_board_lookup' in globals():
                p=_kcard_board_lookup(board).get(_tpl_norm_name(name),{});tm=_kcard_pitcher_team(r,p) or tm
        except Exception:pass
        u=_po_card_team_logo(tm) if '_po_card_team_logo' in globals() else ''; logo=f"<img class='po4logo' src='{html.escape(u)}'/>" if u else f"<div class='po4logo'>{html.escape((tm or 'MLB')[:3])}</div>"
        line=_po_v3_num(r,['UD Line'],np.nan);p=_po_v3_num(r,['PO Final Projection'],np.nan);ip=_po_v3_num(r,['PO Final IP'],np.nan);side=_po_v3_text(r,['PO Final Side'],'PASS');prob=_po_v3_num(r,['PO Final Probability %'],np.nan);edge=_po_v3_num(r,['PO Final Edge'],np.nan);tier=_po_v3_text(r,['PO Final Tier'],'TRACK ONLY PO');data=_po_v3_num(r,['PO V3 Data Completeness %'],np.nan); live=_po_v3_text(r,['PO V4 Live'],'NO')=='YES';conflict=_po_v3_text(r,['PO Final Conflict'],'NO')=='YES'
        cls='over' if side=='OVER' else 'under' if side=='UNDER' else 'track'; sync='LIVE MLB WORKLOAD' if live else 'FALLBACK DATA'; alert="<div class='po4alert'>⚠ Internal workload models disagree — Track Only.</div>" if conflict else ''
        cards.append(f"""<article class='po4 {cls}'><header><div class='po4id'>{logo}<div><h3>{html.escape(name)}</h3><small>{html.escape(matchup)}</small></div></div><em>{html.escape(tier)}</em></header><section class='po4hero'><div><span>PROJECTED OUTS</span><strong>{_po4_txt(p)}</strong><b>{html.escape(side)} {_po4_txt(line)}</b><small>{_po4_txt(ip,2)} IP · {_po4_txt(prob)}%</small></div><aside><span>EDGE</span><b>{_po4_txt(edge)}</b></aside><aside><span>DATA</span><b>{_po4_txt(data,0,'%')}</b></aside></section><div class='po4sync'>{sync}</div><section class='po4grid'><div><span>L5 IP</span><b>{_po4_txt(_po_v3_num(r,['PO V4 L5 IP','PO V3 Recent IP Baseline'],np.nan),2)}</b></div><div><span>L5 BF</span><b>{_po4_txt(_po_v3_num(r,['PO V4 L5 BF','PO V3 Recent BF Baseline'],np.nan))}</b></div><div><span>L5 PITCHES</span><b>{_po4_txt(_po_v3_num(r,['PO V4 L5 PC','PO V3 Recent PC Baseline'],np.nan),0)}</b></div><div><span>P / IP</span><b>{_po4_txt(_po_v3_num(r,['PO V4 P/IP','Pitch Efficiency P/IP'],np.nan))}</b></div><div><span>6+ IP</span><b>{_po4_txt(_po_v3_num(r,['PO V4 6+ IP %','Deep Start Rate'],np.nan),0,'%')}</b></div><div><span>EARLY EXIT</span><b>{_po4_txt(_po_v3_num(r,['PO V4 Early Exit %','Recent Hook Rate'],np.nan),0,'%')}</b></div></section><footer><b>Last start:</b> {_po4_txt(_po_v3_num(r,['PO V4 Last Start IP'],np.nan),2)} IP · {_po4_txt(_po_v3_num(r,['PO V4 Last Start PC'],np.nan),0)} pitches &nbsp; <b>Engine:</b> {html.escape(_po_v3_text(r,['PO Final Source'],''))}</footer>{alert}</article>""")
    css="""<style>.po4wrap{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.po4{background:radial-gradient(circle at 10% 0,rgba(255,35,139,.18),transparent 35%),linear-gradient(145deg,#160b27,#091426);border:1px solid #533566;border-radius:19px;padding:14px;color:#f7f7ff}.po4.over{border-top:3px solid #37e5a5}.po4.under{border-top:3px solid #ffd653}.po4.track{border-top:3px solid #8997ad}.po4 header,.po4id{display:flex;align-items:center}.po4 header{justify-content:space-between}.po4id{gap:9px}.po4logo{width:40px;height:40px;object-fit:contain;border-radius:50%;background:#11182a;padding:4px}.po4 h3{margin:0;font-size:17px}.po4 small{color:#aab3c5}.po4 em{font-style:normal;font-size:9px;font-weight:900;color:#ffdc7b;border:1px solid #9c6c2c;border-radius:999px;padding:5px 8px}.po4hero{display:grid;grid-template-columns:1.6fr .7fr .7fr;gap:7px;margin-top:10px}.po4hero>div,.po4hero aside,.po4grid>div{background:#0a1021cc;border:1px solid #3a2e50;border-radius:12px;padding:9px}.po4 span{display:block;color:#9ba5bc;font-size:8px;font-weight:900;letter-spacing:.08em}.po4hero strong{display:block;font-size:32px;color:#ff3b9a;margin:5px 0}.po4hero aside b{display:block;font-size:20px;margin-top:9px}.po4sync{margin-top:7px;padding:6px 8px;border:1px solid #2a715d;border-radius:9px;color:#65e8ba;font-size:8px;font-weight:900}.po4grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:7px}.po4grid b{display:block;margin-top:3px}.po4 footer{margin-top:8px;border-top:1px solid #352b48;padding-top:7px;color:#aab3c5;font-size:9px}.po4alert{margin-top:7px;padding:6px 8px;border:1px solid #8a6528;border-radius:8px;color:#ffd47d;font-size:9px}@media(max-width:900px){.po4wrap{grid-template-columns:1fr}}</style>"""
    h=css+"<div class='po4wrap'>"+''.join(cards)+"</div>";st.html(h) if hasattr(st,'html') else st.markdown(h,unsafe_allow_html=True);return len(cards)

def _impl_render_beta_pitching_outs_tab_po_v4(board):
    _po_v3_legacy_render_po(board)
    s=_po_v3_calibration_summary()
    if isinstance(s,pd.DataFrame) and not s.empty:
        with st.expander('Pitching Outs — projection accuracy audit',expanded=False):st.caption('V2/V3 stay internal for audit; cards show one final projection.');st.dataframe(s,use_container_width=True,hide_index=True)
'''.strip()

def patch_text(t):
    if MARKER in t:return t
    if t.count(BETA)!=1 or t.count(RENDER)!=1:raise RuntimeError('Apply PO Workload V3 before PO V4')
    i=min(t.index(BETA),t.index(RENDER));t=t[:i]+BLOCK+'\n\n'+t[i:];t=t.replace(BETA,'_beta_projection_rows = _impl_beta_projection_rows_po_v4',1).replace(RENDER,'render_beta_pitching_outs_tab = _impl_render_beta_pitching_outs_tab_po_v4',1);ast.parse(t);return t

def main():
    a=argparse.ArgumentParser();a.add_argument('--app',default='app.py');a.add_argument('--check-only',action='store_true');x=a.parse_args();p=Path(x.app);o=p.read_text(encoding='utf-8-sig');n=patch_text(o)
    with tempfile.TemporaryDirectory() as d:q=Path(d)/'x.py';q.write_text(n);py_compile.compile(str(q),doraise=True)
    if not x.check_only and n!=o:p.write_text(n)
    print('PO Single Projection V4 CHECK PASS' if x.check_only else 'PO Single Projection V4 READY')
if __name__=='__main__':raise SystemExit(main())
