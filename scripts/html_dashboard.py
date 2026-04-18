"""html_dashboard.py — Trade AI v12 HTML Dashboard generator (v3 design)."""
from __future__ import annotations
import html as html_lib, json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

def _e(s) -> str: return html_lib.escape(str(s or ""))
def _sign(v: float) -> str: return f"+{v:.2f}" if v >= 0 else f"{v:.2f}"
def _pct_color(v: float) -> str: return "#0F9D58" if v > 0 else ("#DB4437" if v < 0 else "#9A9AB0")
def _js(obj) -> str: return json.dumps(obj, default=str, ensure_ascii=False)

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d1a;color:#e0e0f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;line-height:1.5}
.top-nav{background:#12122a;border-bottom:2px solid #1A73E8;padding:8px 16px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:999;gap:12px;flex-wrap:wrap}
.brand{font-size:17px;font-weight:800;color:#fff}.brand span{color:#1A73E8}
.run-meta{font-size:10px;color:#9A9AB0;margin-top:1px}
.nav-pills{display:flex;gap:5px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:4px;padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;border:1.5px solid #2a2a4e;color:#ccc;cursor:pointer;transition:all .15s;background:none;white-space:nowrap}
.pill:hover{background:#1A73E8;color:#fff;border-color:#1A73E8}
.pill.tos-pill{border-color:#F4B400;color:#F4B400}
.pill.tos-pill:hover{background:#F4B400;color:#1e1e35}
.session-banner{display:flex;align-items:center;gap:10px;padding:6px 16px;font-size:12px;font-weight:600;border-bottom:1px solid #2a2a4e}
.sentiment-bar{display:flex;align-items:center;gap:12px;padding:7px 16px;border-bottom:1px solid #2a2a4e;flex-wrap:wrap}
.sent-badge{border-radius:20px;padding:4px 14px;font-size:12px;font-weight:800}
.sent-bull{background:#0d3a22;color:#0F9D58;border:1px solid #0F9D58}
.sent-bear{background:#3a0d0d;color:#DB4437;border:1px solid #DB4437}
.sent-neut{background:#1e1e35;color:#9A9AB0;border:1px solid #3a3a5e}
.sent-detail{font-size:11px;color:#9A9AB0}
.stats-bar{display:flex;gap:8px;flex-wrap:wrap;padding:10px 12px}
.stat{background:#12122a;border-radius:8px;padding:8px 14px;text-align:center;min-width:76px;border:1px solid #2a2a4e;cursor:pointer;transition:all .15s}
.stat:hover,.stat.active{border-color:#1A73E8;background:#1e1e35}
.stat.go-chip:hover,.stat.go-chip.active{border-color:#0F9D58}
.stat.top-chip{border-color:#1A73E8}
.stat-val{font-size:19px;font-weight:800}
.stat-lbl{font-size:9px;color:#9A9AB0;text-transform:uppercase;margin-top:1px}
.section{background:#12122a;border-radius:10px;padding:14px;margin:0 10px 10px}
.section-hdr{font-size:11px;font-weight:700;color:#1A73E8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.badge{background:#1e1e35;border-radius:10px;padding:1px 8px;font-size:10px;font-weight:400;text-transform:none;color:#ccc}
.collapse-btn{cursor:pointer;color:#9A9AB0;font-size:10px;margin-left:auto;padding:2px 8px;border:1px solid #2a2a4e;border-radius:10px;white-space:nowrap}
.tos-box{background:#0d1a2a;border:2px solid #1A73E8;border-radius:10px;padding:14px;margin:0 10px 10px}
.tos-title{font-size:13px;font-weight:800;color:#1A73E8;margin-bottom:10px}
.tos-row{display:flex;gap:8px;align-items:flex-end;margin-bottom:10px;flex-wrap:wrap}
.tos-grp{flex:1;min-width:200px}
.tos-lbl{font-size:9px;color:#9A9AB0;font-weight:700;text-transform:uppercase;margin-bottom:3px}
.tos-input{width:100%;background:#1e1e35;font-family:monospace;font-size:12px;font-weight:700;border:1.5px solid #3a3a5e;border-radius:6px;padding:6px 9px;cursor:text}
.tos-input.go-color{color:#0F9D58}.tos-input.all-color{color:#F4B400}
.copybtn{padding:7px 14px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;border:none;white-space:nowrap}
.copybtn.go{background:#0F9D58;color:#fff}.copybtn.all{background:#F4B400;color:#1e1e35}
.copybtn:hover{opacity:.85}
.tos-steps{background:#0d0d1a;border-radius:8px;padding:10px;font-size:10px;color:#9A9AB0;line-height:1.9}
.tos-steps b{color:#ccc}.tos-steps code{background:#1e1e35;padding:1px 5px;border-radius:3px;color:#1A73E8}
.heatmap-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:6px}
@media(max-width:700px){.heatmap-grid{grid-template-columns:repeat(3,1fr)}}
.tile{border-radius:8px;padding:9px 5px;text-align:center;cursor:pointer;transition:transform .15s}
.tile:hover{transform:scale(1.06)}
.t-flat{background:#252540;color:#9A9AB0}.t-sup{background:#0d6e3f;color:#fff}
.t-up{background:#1a9e5c;color:#fff}.t-dn{background:#c0392b;color:#fff}.t-sdn{background:#7b0d0d;color:#fff}
.t-sym{font-weight:800;font-size:12px}.t-pct{font-size:11px;margin:1px 0;font-weight:600}.t-name{font-size:9px;opacity:.8;margin-top:1px}
.delta-item{border-radius:6px;padding:7px 12px;margin-bottom:4px;cursor:pointer}
.delta-item .delta-detail{display:none;margin-top:6px;font-size:11px;color:#9A9AB0;border-top:1px solid rgba(255,255,255,.08);padding-top:6px}
.delta-item.open .delta-detail{display:block}
.d-arrow{float:right;color:#9A9AB0;font-size:10px;margin-top:1px}
.d-up{background:#0d2a1a;border-left:3px solid #0F9D58}.d-dn{background:#2a0d0d;border-left:3px solid #DB4437}
.d-cat{background:#1a150d;border-left:3px solid #F4B400}.d-crit{background:#0d0d2a;border-left:3px solid #1A73E8}
.d-new{background:#0d2a0d;border-left:3px solid #34a853}.d-fade{background:#1a1a1a;border-left:3px solid #9A9AB0}
.ticker-tbl{width:100%;border-collapse:collapse;font-size:12px}
.ticker-tbl th{color:#9A9AB0;text-align:left;padding:5px 8px;border-bottom:1px solid #2a2a4e;font-size:9px;text-transform:uppercase;cursor:pointer;white-space:nowrap;font-weight:600}
.ticker-tbl th:hover{color:#fff}
.ticker-tbl td{padding:5px 8px;border-bottom:1px solid #1a1a2e;vertical-align:middle}
.ticker-tbl tr.data-row{cursor:pointer;transition:background .1s}
.ticker-tbl tr.data-row:hover{background:#1e1e35}
.ticker-tbl tr.expanded td{background:#1a1a30}
.dec-go{color:#0F9D58;font-weight:800}.dec-wait{color:#F4B400;font-weight:800}.dec-avoid{color:#DB4437}
.up{color:#0F9D58}.dn{color:#DB4437}.nt{color:#9A9AB0}
.sym-link{color:#fff;font-weight:800;font-size:13px}
.sym-link:hover{color:#1A73E8;text-decoration:underline}
.fv-btn{background:#1A73E8;color:#fff;border:none;border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700;cursor:pointer}
.fv-btn:hover{background:#1557b0}
.sbar-wrap{background:#252540;border-radius:2px;height:4px;width:70px;display:inline-block;vertical-align:middle;margin-left:4px}
.sbar-fill{height:4px;border-radius:2px;background:linear-gradient(90deg,#1A73E8,#0F9D58)}
.crit-dots{display:inline-flex;gap:2px;vertical-align:middle}
.crit-dot{width:5px;height:10px;border-radius:2px}
.detail-row{display:none}.detail-row td{padding:0}
.detail-inner{background:#161630;border-radius:8px;margin:3px 6px 6px;padding:12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.dg{background:#1e1e35;border-radius:6px;padding:9px 11px}
.dg-lbl{font-size:9px;color:#9A9AB0;text-transform:uppercase;font-weight:700;margin-bottom:5px}
.pm-row{display:flex;align-items:center;gap:4px;margin-bottom:2px}
.pm-name{font-size:9px;color:#9A9AB0;width:68px;flex-shrink:0}
.pm-wrap{flex:1;background:#252540;border-radius:2px;height:5px}
.pm-bar{height:5px;border-radius:2px}
.pm-pts{font-size:9px;color:#9A9AB0;width:24px;text-align:right;flex-shrink:0}
.crit-wrap{display:flex;flex-wrap:wrap;gap:3px}
.crit{font-size:10px;border-radius:10px;padding:2px 7px}
.crit.met{background:#0d3a22;color:#0F9D58}.crit.unmet{background:#1e1e35;color:#9A9AB0}
.chart-container img{width:100%;border-radius:4px;display:block;max-width:300px}
.chart-fallback{padding:16px;color:#9A9AB0;font-size:11px;text-align:center}
.cat-item{border-bottom:1px solid #1a1a2e;padding:6px 0;cursor:pointer}
.cat-item:last-child{border-bottom:none}
.cat-time{font-size:9px;color:#9A9AB0;margin-bottom:1px}
.cat-title-text{font-size:11px;font-weight:500;line-height:1.4}
.cat-summary{font-size:10px;color:#a0a0c0;font-style:italic;margin-top:3px;display:none;padding-left:8px;border-left:2px solid #3a3a5e}
.cat-item.open .cat-summary{display:block}
.tag-hi{color:#DB4437;font-weight:700}.tag-med{color:#F4B400;font-weight:700}.tag-low{color:#9A9AB0}
.social-chip{background:#1e1e35;border-radius:6px;padding:3px 8px;font-size:10px;margin-right:4px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 10px 10px}
@media(max-width:900px){.two-col{grid-template-columns:1fr}}
.cal-table,.opt-table{width:100%;border-collapse:collapse;font-size:11px}
.cal-table th,.opt-table th{color:#9A9AB0;padding:4px 6px;border-bottom:1px solid #2a2a4e;text-align:left;font-size:9px;text-transform:uppercase}
.cal-table td,.opt-table td{padding:4px 6px;border-bottom:1px solid #1a1a2e}
.tape-sym{font-weight:700;color:#1A73E8;margin-top:10px;margin-bottom:3px;font-size:12px}
.tape-row{font-size:11px;margin-left:8px;margin-bottom:3px;color:#ccc}
.tape-row a{color:inherit}.tape-row a:hover{color:#1A73E8}
footer{text-align:center;color:#9A9AB0;font-size:10px;padding:14px;border-top:1px solid #1e1e35;margin-top:10px}
.exec-strip{background:#0a1628;border-bottom:2px solid #1A73E8;padding:6px 16px;display:flex;align-items:center;gap:20px;flex-wrap:wrap;font-size:11px}
.exec-item{display:flex;flex-direction:column;gap:1px;min-width:70px}
.exec-label{font-size:9px;color:#9A9AB0;text-transform:uppercase;letter-spacing:.4px}
.exec-value{font-size:13px;font-weight:800;color:#e0e0f0}
.exec-value.warn{color:#F4B400}.exec-value.danger{color:#DB4437}.exec-value.ok{color:#0F9D58}
.regime-banner{background:#1a1500;border-left:4px solid #F4B400;border-radius:6px;padding:10px 16px;margin:6px 10px;font-size:11px;line-height:1.6}
.regime-title{font-weight:800;color:#F4B400;font-size:12px;margin-bottom:4px}
.regime-body{color:#ccc}
.sf-btn{background:#1e1e35;border:1px solid #2a2a4e;border-radius:10px;padding:2px 10px;font-size:10px;color:#ccc;cursor:pointer}
.sf-btn.active{background:#1A73E8;color:#fff;border-color:#1A73E8}
"""

JS = """
var TICKERS={tickers};
var DELTAS={deltas};
var SECTORS={sectors};
var PC={{catalyst:"#DB4437",rvol:"#F4B400",pa:"#1A73E8",float:"#9c27b0",price:"#00bcd4",sector:"#0F9D58"}};
var PM={{catalyst:15,rvol:12,pa:10,float:8,price:5,sector:5}};
var PL={{catalyst:"Catalyst",rvol:"RVOL",pa:"Price Act.",float:"Float",price:"Px Range",sector:"Sector"}};
var cf='all';
function init(){{buildHeatmap();buildDeltas();buildTable(TICKERS,true);buildCatTape();}}
var sfMode=true;
function toggleScoreFilter(){{
  sfMode=!sfMode;
  var btn=document.getElementById('sf-btn');
  btn.textContent=sfMode?'Score ≥15 Active (click for all)':'Showing All (click for ≥15)';
  btn.className=sfMode?'sf-btn active':'sf-btn';
  buildTable(TICKERS,sfMode);
}}
function buildHeatmap(){{
  var g=document.getElementById('heatmap-grid');
  var s=SECTORS.slice().sort(function(a,b){{return b.pct-a.pct}});
  document.getElementById('leaders-txt').textContent=s.slice(0,3).map(function(x){{return x.sym+" "+(x.pct>=0?"+":"")+x.pct.toFixed(2)+"%"}}).join(" · ")||"—";
  document.getElementById('laggards-txt').textContent=s.slice(-3).map(function(x){{return x.sym+" "+x.pct.toFixed(2)+"%"}}).join(" · ")||"—";
  g.innerHTML=SECTORS.map(function(s){{
    return '<div class="tile '+s.tier+'" onclick="window.open(\\'https://elite.finviz.com/quote.ashx?t='+s.sym+'\\',\\'_blank\\')" title="'+s.name+'">'+
      '<div class="t-sym">'+s.sym+'</div><div class="t-pct">'+(s.pct>=0?"+":"")+s.pct.toFixed(2)+'%</div><div class="t-name">'+s.name+'</div></div>';
  }}).join('');
}}
function buildDeltas(){{
  var el=document.getElementById('delta-body');
  el.innerHTML=DELTAS.map(function(d,i){{
    return '<div class="delta-item '+d.type+'" onclick="tgD('+i+',this)">'+
      (d.detail?'<span class="d-arrow" id="da'+i+'">▼</span>':'')+d.icon+' '+d.text+
      (d.detail?'<div class="delta-detail" id="dd'+i+'">'+d.detail+'</div>':'')+
    '</div>';
  }}).join('');
}}
function tgD(i,el){{
  var dd=document.getElementById('dd'+i);
  if(!dd)return;
  el.classList.toggle('open');
  document.getElementById('da'+i).textContent=el.classList.contains('open')?'▲':'▼';
}}
function buildTable(tickers,scoreFilter){{
  var tb=document.getElementById('tbl-body');
  tb.innerHTML='';
  var n=0;
  tickers.forEach(function(t){{
    var show=(cf==='all'||cf===t.dec||(cf==='catalyst'&&t.catalyst_count>0))&&(!scoreFilter||t.score>=15);
    if(!show)return;n++;
    var dc='dec-'+(t.dec==='GO'?'go':t.dec==='WAIT'?'wait':'avoid');
    var cc=t.chg>0?'up':t.chg<0?'dn':'nt',gc=t.gap>0?'up':t.gap<0?'dn':'nt';
    var sp=Math.round(t.score/55*100);
    var dots='<div class="crit-dots">';
    for(var j=0;j<t.criteria_total;j++)dots+='<div class="crit-dot" style="background:'+(j<t.criteria_met?'#0F9D58':'#2a2a4e')+'"></div>';
    dots+='</div><span class="nt" style="font-size:10px">'+t.criteria_met+'/'+t.criteria_total+'</span>';
    var sl=(t.social&&t.social.sentiment_label)||'—';
    var sc=sl.includes('Bull')?'up':sl.includes('Bear')?'dn':'nt';
    var stc=(t.social&&t.social.stocktwits&&t.social.stocktwits.count)||0;
    var soc='<span class="'+sc+'" style="font-size:11px">'+sl+'</span>'+(stc?'<span class="nt" style="font-size:10px"> '+stc+'</span>':'');
    var cath=t.top_cat?
      '<span class="'+(t.catalyst_tier==='high_impact'?'tag-hi':t.catalyst_tier==='medium_impact'?'tag-med':'tag-low')+'">'+(t.catalyst_tier==='high_impact'?'🔥':t.catalyst_tier==='medium_impact'?'⚡':'📰')+'</span> '+
      (t.top_cat.title||'').substring(0,40)+((t.top_cat.title||'').length>40?'…':''):'—';
    var fu='https://elite.finviz.com/quote.ashx?t='+t.sym;
    tb.innerHTML+=
      '<tr class="data-row" onclick="tgR(\\''+t.sym+'\\',this)" id="row-'+t.sym+'">'+
      '<td><a class="sym-link" href="'+fu+'" target="_blank" onclick="event.stopPropagation()">'+t.sym+'</a></td>'+
      '<td><span style="font-weight:700">'+t.score+'</span><div class="sbar-wrap"><div class="sbar-fill" style="width:'+sp+'%"></div></div></td>'+
      '<td class="'+dc+'">'+t.dec+'</td>'+
      '<td class="'+(t.rvol>=5?'up':'nt')+'">'+t.rvol.toFixed(1)+'x</td>'+
      '<td>$'+t.price.toFixed(2)+'</td>'+
      '<td class="'+cc+'">'+(t.chg>=0?'+':'')+t.chg.toFixed(1)+'%</td>'+
      '<td class="'+gc+'">'+(t.gap>=0?'+':'')+t.gap.toFixed(1)+'%</td>'+
      '<td class="'+(t.float_m<10?'up':'nt')+'">'+t.float_m.toFixed(1)+'M</td>'+
      '<td>'+t.country+'</td>'+
      '<td style="font-size:11px;color:#9A9AB0">'+t.sector+'</td>'+
      '<td>'+dots+'</td>'+
      '<td>'+soc+'</td>'+
      '<td style="font-size:11px;max-width:180px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">'+cath+'</td>'+
      '<td><a href="'+fu+'" target="_blank" onclick="event.stopPropagation()"><button class="fv-btn">FV</button></a></td>'+
      '</tr>'+
      '<tr class="detail-row" id="dr-'+t.sym+'"><td colspan="14">'+buildDet(t)+'</td></tr>';
  }});
  document.getElementById('setups-count').textContent=n+' tickers';
}}
function buildDet(t){{
  var fu='https://elite.finviz.com/quote.ashx?t='+t.sym;
  var cu='https://elite.finviz.com/chart.ashx?t='+t.sym+'&ty=c&ta=1&p=d&s=m';
  var ph='<div class="dg"><div class="dg-lbl">Pillars</div>';
  ['catalyst','rvol','pa','float','price','sector'].forEach(function(k){{
    var pts=t.pillars[k]||0,max=PM[k],pct=max>0?Math.round(pts/max*100):0;
    ph+='<div class="pm-row"><span class="pm-name">'+PL[k]+'</span><div class="pm-wrap"><div class="pm-bar" style="width:'+pct+'%;background:'+PC[k]+'"></div></div><span class="pm-pts">'+pts+'/'+max+'</span></div>';
  }});ph+='</div>';
  var clab={{has_catalyst:'Catalyst',has_high_impact:'High Impact',has_fresh_catalyst:'Fresh <12h',rvol_3:'RVOL≥3x',rvol_5:'RVOL≥5x',float_50:'Float≤50M',price_ok:'Price OK',gap_5:'Gap≥5%',chg_10:'Chg≥10%'}};
  var ch='<div class="dg"><div class="dg-lbl">Criteria</div><div class="crit-wrap">';
  Object.keys(clab).forEach(function(k){{var m=t.criteria[k];ch+='<span class="crit '+(m?'met':'unmet')+'">'+(m?'✅':'⬜')+' '+clab[k]+'</span>';}});ch+='</div></div>';
  var chart='<div class="dg"><div class="dg-lbl">Daily Chart (login to Finviz Elite)</div>'+
    '<div class="chart-container"><a href="'+fu+'" target="_blank">'+
    '<img src="'+cu+'" alt="'+t.sym+'" onerror="this.parentElement.parentElement.innerHTML=\\'<div class=chart-fallback><a href='+fu+' target=_blank style=color:#1A73E8>Open '+t.sym+' on Finviz Elite →</a></div>\\">'+
    '</a></div></div>';
  var cath='<div class="dg" style="grid-column:span 2;min-width:200px"><div class="dg-lbl">Catalysts (click headline for summary)</div>';
  if(t.cats&&t.cats.length){{
    t.cats.slice(0,5).forEach(function(c){{
      var tc=c.tier==='high_impact'?'tag-hi':c.tier==='medium_impact'?'tag-med':'tag-low';
      var te=c.tier==='high_impact'?'🔥':c.tier==='medium_impact'?'⚡':'📰';
      cath+='<div class="cat-item" onclick="this.classList.toggle(\\'open\\')">'+
        '<div class="cat-time"><span class="'+tc+'">'+te+' '+c.tier.replace('_impact',' impact')+'</span> · '+c.age.toFixed(1)+'h · '+c.source+'</div>'+
        '<div class="cat-title-text">'+(c.url?'<a href="'+c.url+'" target="_blank" onclick="event.stopPropagation()" style="color:inherit">'+c.title+'</a>':c.title)+'</div>'+
        (c.summary?'<div class="cat-summary">💡 '+c.summary+'</div>':'')+
      '</div>';
    }});
  }}else{{cath+='<div style="color:#9A9AB0;font-size:11px">No catalysts found</div>';}}
  cath+='</div>';
  var soc=t.social||{{}},st=soc.stocktwits||{{}},rd=soc.reddit||{{}},sl=soc.sentiment_label||'Neutral';
  var sc=sl.includes('Bull')?'up':sl.includes('Bear')?'dn':'nt';
  var sh='<div class="dg"><div class="dg-lbl">Social Sentiment</div>'+
    '<div style="font-size:14px;font-weight:800" class="'+sc+'">'+sl+'</div>'+
    '<div style="margin-top:6px"><span class="social-chip">💬 '+((st.count)||0)+'</span>'+
    '<span class="social-chip '+(st.bullish_pct>=60?'up':st.bullish_pct<=40?'dn':'nt')+'">'+((st.bullish_pct)||50)+'% bull</span>'+
    (rd.count?'<span class="social-chip">📱 Reddit: '+rd.count+'</span>':'')+
    '</div><a href="https://stocktwits.com/symbol/'+t.sym+'" target="_blank" style="font-size:10px;color:#1A73E8;display:block;margin-top:5px">StockTwits →</a></div>';
  var mk='<div class="dg"><div class="dg-lbl">Market Data</div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;font-size:11px">'+
    '<span class="nt">Price</span><span>$'+t.price.toFixed(2)+'</span>'+
    '<span class="nt">Chg</span><span class="'+(t.chg>=0?'up':'dn')+'">'+(t.chg>=0?'+':'')+t.chg.toFixed(1)+'%</span>'+
    '<span class="nt">Gap</span><span class="'+(t.gap>=0?'up':'dn')+'">'+(t.gap>=0?'+':'')+t.gap.toFixed(1)+'%</span>'+
    '<span class="nt">RVOL</span><span>'+t.rvol.toFixed(1)+'x</span>'+
    '<span class="nt">Float</span><span class="'+(t.float_m<10?'up':'nt')+'">'+t.float_m.toFixed(1)+'M</span>'+
    '<span class="nt">Volume</span><span>'+t.vol.toLocaleString()+'</span></div></div>';
  var lk='<div class="dg"><div class="dg-lbl">Links</div>'+
    '<div style="display:flex;flex-direction:column;gap:5px">'+
    '<a href="'+fu+'" target="_blank" style="background:#1A73E8;color:#fff;border-radius:6px;padding:6px;font-size:11px;font-weight:700;text-align:center;display:block">📊 Finviz Elite Chart</a>'+
    '<a href="https://elite.finviz.com/news.ashx?t='+t.sym+'" target="_blank" style="background:#252540;color:#ccc;border-radius:6px;padding:5px;font-size:11px;text-align:center;display:block">📰 Finviz News</a>'+
    '<a href="https://stocktwits.com/symbol/'+t.sym+'" target="_blank" style="background:#252540;color:#ccc;border-radius:6px;padding:5px;font-size:11px;text-align:center;display:block">💬 StockTwits</a>'+
    '</div></div>';
  return '<div class="detail-inner">'+ph+ch+chart+cath+sh+mk+lk+'</div>';
}}
function tgR(sym,row){{
  var dr=document.getElementById('dr-'+sym);
  var open=dr.style.display==='table-row';
  document.querySelectorAll('.detail-row').forEach(function(r){{r.style.display='none'}});
  document.querySelectorAll('.data-row').forEach(function(r){{r.classList.remove('expanded')}});
  if(!open){{dr.style.display='table-row';row.classList.add('expanded');}}
}}
function buildCatTape(){{
  var el=document.getElementById('cat-body');
  el.innerHTML=TICKERS.filter(function(t){{return t.cats&&t.cats.length>0}}).map(function(t){{
    var rows=t.cats.map(function(c){{
      var tc=c.tier==='high_impact'?'tag-hi':c.tier==='medium_impact'?'tag-med':'tag-low';
      var te=c.tier==='high_impact'?'🔥':c.tier==='medium_impact'?'⚡':'📰';
      return '<div class="tape-row"><span class="'+tc+'">'+te+' ['+c.tier.replace('_impact','').toUpperCase()+' · '+c.age.toFixed(1)+'h · '+c.source+']</span> '+
        (c.url?'<a href="'+c.url+'" target="_blank">'+c.title+'</a>':c.title)+
        (c.summary?'<div style="font-size:10px;color:#9A9AB0;margin-left:14px;font-style:italic">💡 '+c.summary+'</div>':'')+
      '</div>';
    }}).join('');
    return '<div class="tape-sym">'+t.country+' '+t.sym+' · '+t.co+'</div>'+rows;
  }}).join('');
}}
function filterBy(f){{
  cf=f;
  var lbl={{all:'All',GO:'GO Only',WAIT:'WAIT Only',AVOID:'Avoid Only',catalyst:'Has Catalyst'}};
  document.getElementById('filter-lbl').textContent='Showing: '+lbl[f];
  document.querySelectorAll('.stat').forEach(function(s){{s.classList.remove('active')}});
  var m={{all:'s-all',GO:'s-go',WAIT:'s-wait',AVOID:'s-av'}};
  if(m[f])document.getElementById(m[f]).classList.add('active');
  buildTable(TICKERS,sfMode);
  jumpTo('setups');
}}
function srt(k){{
  TICKERS.sort(function(a,b){{var av=a[k]||0,bv=b[k]||0;return typeof av==='string'?av.localeCompare(bv):bv-av}});
  buildTable(TICKERS,sfMode);
}}
function tog(id,btn){{
  var el=document.getElementById(id),h=el.style.display==='none';
  el.style.display=h?'':'none';btn.textContent=h?'▲ hide':'▼ show';
}}
function jumpTo(id){{var el=document.getElementById(id);if(el)el.scrollIntoView({{behavior:'smooth',block:'start'}});}}
function doCopy(id,btn){{
  var el=document.getElementById(id),txt=el.value.trim(),orig=btn.textContent;
  if(!txt||txt.startsWith('—')){{btn.textContent='Nothing to copy';setTimeout(function(){{btn.textContent=orig}},1500);return}}
  el.select();el.setSelectionRange(0,99999);
  var ok=false;try{{ok=document.execCommand('copy')}}catch(e){{}}
  if(!ok&&navigator.clipboard)navigator.clipboard.writeText(txt).catch(function(){{}});
  btn.textContent='✅ Copied!';setTimeout(function(){{btn.textContent=orig}},2000);
}}
init();
"""

def _ticker_to_js(t):
    pb  = t.get("pillar_breakdown", {})
    top = t.get("top_catalyst") or {}
    soc = t.get("social") or {}
    st  = soc.get("stocktwits") or {}
    rd  = soc.get("reddit") or {}
    cr  = t.get("criteria", {})
    cats = []
    for c in t.get("catalysts", [])[:5]:
        cats.append({"title": str(c.get("title",""))[:200], "source": str(c.get("source","")),
                     "age": round(float(c.get("hours_old") or 0), 1),
                     "tier": str(c.get("impact_tier","low_impact")),
                     "url": str(c.get("url","")), "summary": str(c.get("llm_summary",""))})
    return {
        "sym": str(t.get("symbol","")), "co": str(t.get("company","")),
        "country": "🇺🇸", "sector": str(t.get("sector","")),
        "score": int(t.get("score",0)), "grade": str(t.get("grade","D")),
        "dec": str(t.get("decision","AVOID")),
        "rvol": round(float(t.get("relative_volume") or 0), 1),
        "price": round(float(t.get("price") or 0), 2),
        "chg": round(float(t.get("change_percent") or 0), 1),
        "gap": round(float(t.get("gap_percent") or 0), 1),
        "float_m": round(float(t.get("float_m") or 0), 1),
        "vol": int(t.get("volume") or 0),
        "criteria_met": int(t.get("criteria_met") or 0),
        "criteria_total": int(t.get("criteria_total") or 9),
        "catalyst_count": int(t.get("catalyst_count") or 0),
        "catalyst_tier": str(t.get("catalyst_tier","none")),
        "criteria": {
            "has_catalyst": bool(cr.get("has_catalyst")),
            "has_high_impact": bool(cr.get("has_high_impact")),
            "has_fresh_catalyst": bool(cr.get("has_fresh_catalyst")),
            "rvol_3": bool(cr.get("rvol_above_3")), "rvol_5": bool(cr.get("rvol_above_5")),
            "float_50": bool(cr.get("float_under_50m")), "price_ok": bool(cr.get("price_in_range")),
            "gap_5": bool(cr.get("gap_above_5pct")), "chg_10": bool(cr.get("change_above_10pct")),
        },
        "pillars": {
            "catalyst": int(pb.get("catalyst",0)), "rvol": int(pb.get("relative_volume",0)),
            "pa": int(pb.get("price_action",0)), "float": int(pb.get("float",0)),
            "price": int(pb.get("price_range",0)), "sector": int(pb.get("sector_momentum",0)),
        },
        "top_cat": {"title": str(top.get("title",""))[:150], "source": str(top.get("source","")),
                    "age": round(float(top.get("hours_old") or 0), 1),
                    "tier": str(top.get("impact_tier","low_impact")), "url": str(top.get("url",""))} if top.get("title") else None,
        "cats": cats,
        "ollama_flag": str(t.get("ollama_flag","") or ""),
        "ollama_risk": str(t.get("ollama_risk","") or "")[:100],
        "ollama_summary": str(t.get("ollama_summary","") or "")[:100],
        "ollama_preplan": str(t.get("ollama_preplan","") or "")[:300],
        "catalyst_type": str(t.get("catalyst_type","") or ""),
        "social": {"sentiment_label": str(soc.get("sentiment_label","Neutral")),
                   "stocktwits": {"count": int(st.get("count",0)), "bullish_pct": int(st.get("bullish_pct",50))},
                   "reddit": {"count": int(rd.get("count",0))}},
    }

def _delta_to_js(evt):
    etype = evt.get("event","")
    sym   = evt.get("symbol","")
    m = {"NEW_TICKER":("d-new","🆕"),"GRADE_UP":("d-up","📈"),"GRADE_DOWN":("d-dn","📉"),
         "NEW_CATALYST":("d-cat","🔥"),"RVOL_THRESHOLD_CROSS":("d-rvol","🚀"),
         "NEW_CRITERIA_MET":("d-crit","✅"),"TICKER_FADED":("d-fade","👻")}
    if etype not in m: return None
    css, icon = m[etype]
    if etype == "GRADE_UP":
        d = evt.get("score_delta",0)
        text = f"<b>{_e(sym)}</b> — {evt.get('prev_score')} → {evt.get('score')} ({d:+d})"
        detail = f"Grade: {_e(evt.get('prev_grade','?'))} → {_e(evt.get('grade','?'))}"
    elif etype == "NEW_CATALYST":
        titles = evt.get("titles") or []
        text = f"<b>{_e(sym)}</b> — {evt.get('count',0)} new catalyst(s): {_e((titles[0] if titles else '')[:80])}"
        detail = "<br>".join(_e(tt) for tt in titles[:5])
    elif etype == "NEW_CRITERIA_MET":
        crits = ", ".join(evt.get("new_criteria",[]))
        text = f"<b>{_e(sym)}</b> — New criteria: {_e(crits)}"
        detail = f"Total: {evt.get('total_met','?')}/9"
    elif etype == "NEW_TICKER":
        text = f"<b>{_e(sym)}</b> — First seen · Score {evt.get('score')} · {_e(evt.get('decision',''))}"
        detail = ""
    elif etype == "TICKER_FADED":
        text = f"<b>{_e(sym)}</b> — Dropped out (was score {evt.get('last_score',0)})"
        detail = ""
    elif etype == "RVOL_THRESHOLD_CROSS":
        text = f"<b>{_e(sym)}</b> — RVOL crossed {evt.get('threshold')}x"
        detail = ""
    else:
        text = f"<b>{_e(sym)}</b> — {_e(etype)}"
        detail = ""
    return {"type": css, "icon": icon, "text": text, "detail": detail}

def _sector_to_js(s):
    pct = round(float(s.get("change_percent") or 0), 2)
    tm = {"strong-up":"t-sup","up":"t-up","flat":"t-flat","down":"t-dn","strong-down":"t-sdn"}
    return {"sym": str(s.get("symbol","")), "name": str(s.get("name","")),
            "pct": pct, "tier": tm.get(str(s.get("color_tier","flat")),"t-flat")}


def generate_html_dashboard(
    scored_tickers, market_snapshot, delta, calendar,
    options_flow, options_summary, output_dir, run_label, date_str,
    trade_plans=None, halt_data=None,
    institutional: bool = False,
    portfolio_totals: dict = None,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"dashboard_{date_str}_{run_label}.html"
    inst_path = output_dir / f"dashboard_{date_str}_{run_label}_institutional.html"

    if trade_plans:
        for t in scored_tickers:
            if not t.get("trade_plan"): t["trade_plan"] = trade_plans.get(t.get("symbol",""))

    tickers_js = [_ticker_to_js(t) for t in scored_tickers]
    deltas_js  = [d for d in (_delta_to_js(e) for e in delta.get("events",[])) if d]
    sectors_js = [_sector_to_js(s) for s in market_snapshot.get("sectors",[])]

    go_list   = [t for t in scored_tickers if t.get("decision")=="GO"]
    wait_list = [t for t in scored_tickers if t.get("decision")=="WAIT"]
    go_syms   = " ".join(t["symbol"] for t in go_list[:20])
    all_syms  = " ".join(t["symbol"] for t in (go_list+wait_list)[:30])
    top_sym   = scored_tickers[0]["symbol"] if scored_tickers else "—"
    top_score = scored_tickers[0]["score"]  if scored_tickers else 0
    with_cat  = sum(1 for t in scored_tickers if (t.get("catalyst_count") or 0) > 0)

    indices   = market_snapshot.get("indices",{})
    vix       = market_snapshot.get("vix",{})
    breadth   = market_snapshot.get("breadth_label","Neutral")
    session   = market_snapshot.get("session") or {}
    spy_pct   = indices.get("SPY",{}).get("change_percent",0) or 0
    qqq_pct   = indices.get("QQQ",{}).get("change_percent",0) or 0
    vix_val   = vix.get("price",0) or 0
    sess_lbl  = session.get("session_label","—")
    sess_emj  = session.get("session_emoji","🔴")
    sess_desc = session.get("description","")
    sess_id   = session.get("session","closed")
    sess_bg   = {"pre_market":"#1a1500","market_hours":"#0d1a0d","after_hours":"#0d0d2a","closed":"#1a1a1a"}.get(sess_id,"#1a1a1a")
    sent_cls  = "sent-bull" if breadth=="Bullish" else ("sent-bear" if breadth=="Bearish" else "sent-neut")
    sent_txt  = f"{'🟢' if breadth=='Bullish' else '🔴' if breadth=='Bearish' else '🟡'} {breadth}"
    ts = datetime.now().strftime("%H:%M:%S ET")

    # ── Institutional exec strip (built AFTER go_list and market vars defined) ──
    _go_count  = len(go_list)
    _port      = portfolio_totals or {}
    _port_val  = _port.get("total_value", 0) or 0
    _port_day  = _port.get("day_change", 0) or 0
    _day_sign  = "+" if _port_day >= 0 else ""
    _day_col   = "ok" if _port_day >= 0 else "danger"
    _vix_col   = "warn" if vix_val > 20 else "ok"
    _go_col    = "ok" if _go_count > 0 else "warn"
    exec_strip_html = (
        "<div class='exec-strip'>"
        f"<div class='exec-item'><span class='exec-label'>VIX</span>"
        f"<span class='exec-value {_vix_col}'>{vix_val:.1f}</span></div>"
        f"<div class='exec-item'><span class='exec-label'>Breadth</span>"
        f"<span class='exec-value'>{ breadth}</span></div>"
        f"<div class='exec-item'><span class='exec-label'>Scanned</span>"
        f"<span class='exec-value'>{len(scored_tickers)}</span></div>"
        f"<div class='exec-item'><span class='exec-label'>GO Tier</span>"
        f"<span class='exec-value {_go_col}'>{_go_count}</span></div>"
        + (f"<div class='exec-item'><span class='exec-label'>Portfolio</span>"
           f"<span class='exec-value {_day_col}'>{_day_sign}{_port.get('day_change_pct', 0) or 0:.2f}%</span></div>"
           if _port_val > 0 else "")
        + f"<div style='margin-left:auto;font-size:9px;color:#9A9AB0'>Run {_e(run_label)} &middot; {_e(date_str)} &middot; {ts}</div>"
        "</div>"
    )

    # ── Regime statement (zero-GO days only) ───────────────────────────────
    regime_html = ""
    if _go_count == 0:
        _secs = sorted(market_snapshot.get("sectors", []),
                       key=lambda s: float(s.get("change_percent") or 0), reverse=True)
        _leaders  = " &middot; ".join(
            f"{_e(s.get('symbol',''))} {float(s.get('change_percent',0)):+.1f}%"
            for s in _secs[:3])
        _laggards = " &middot; ".join(
            f"{_e(s.get('symbol',''))} {float(s.get('change_percent',0)):+.1f}%"
            for s in _secs[-2:])
        _vix_desc = ("elevated fear" if vix_val > 25
                     else "moderate caution" if vix_val > 18
                     else "low fear")
        regime_html = (
            "<div class='regime-banner'>"
            f"<div class='regime-title'>&#x1f4ca; Market Regime &mdash; Quiet Consolidation &middot; 0 GO Setups</div>"
            f"<div class='regime-body'>"
            f"{len(scored_tickers)} tickers scanned &middot; VIX {vix_val:.1f} ({_vix_desc}) &middot; Breadth: {_e(breadth)}"
            f"<br>Leaders: {_leaders} &nbsp;|&nbsp; Laggards: {_laggards}"
            f"<br>No high-conviction scalp setups this run. Watch for catalyst rotation or VIX compression."
            f"</div></div>"
        )



    # Calendar
    hi_events = (calendar.get("high_impact_events") or [])[:6]
    earnings  = (calendar.get("earnings") or [])[:8]
    wl_earn   = calendar.get("watchlist_earnings") or []
    cal_rows  = ""
    for e in hi_events:
        ic = "#DB4437" if "HIGH" in e.get("impact","") else "#F4B400"
        cal_rows += f"<tr><td class='nt'>{_e(str(e.get('date',''))[-8:])}</td><td><span style='color:{ic};font-weight:700;font-size:10px'>{_e(e.get('impact',''))}</span></td><td>{_e(str(e.get('event',''))[:50])}</td><td class='nt'>{_e(str(e.get('forecast','—')))}</td><td class='nt'>{_e(str(e.get('previous','—')))}</td></tr>"
    earn_chips = ""
    for e in earnings[:6]:
        sym = _e(e.get("symbol",""))
        tt  = "BMO" if e.get("time","")=="bmo" else "AMC"
        hl  = " style='border-color:#F4B400'" if e.get("symbol") in wl_earn else ""
        earn_chips += f"<span style='background:#1e1e35;border:1px solid #3a3a5e{hl};border-radius:10px;padding:3px 9px;font-size:11px;margin:2px'>{sym} <small class='nt'>{tt}</small></span>"

    # Options
    all_opts = sorted([item for items in options_flow.values() for item in items], key=lambda x: x.get("premium_est",0), reverse=True)
    opt_rows = ""
    for item in all_opts[:8]:
        dc = "#0F9D58" if item.get("direction")=="bullish" else ("#DB4437" if item.get("direction")=="bearish" else "#9A9AB0")
        sw = '<span style="background:#DB4437;color:#fff;border-radius:3px;padding:1px 4px;font-size:9px;font-weight:700">SWEEP</span>' if item.get("is_sweep") else ""
        vol_str = f"{item.get('volume',0):,}"
        opt_rows += (f"<tr><td style='font-weight:700'>{_e(str(item.get('ticker',''))[:8])}</td>"
                     f"<td style='color:{dc}'>{_e(item.get('contract_type',''))}</td>"
                     f"<td>${_e(item.get('strike',''))}</td>"
                     f"<td class='nt'>{_e(item.get('expiry',''))}</td>"
                     f"<td>{_e(vol_str)}</td>"
                     f"<td style='font-weight:700'>{_e(item.get('premium_display',''))}</td>"
                     f"<td style='color:{dc}'>{_e(str(item.get('direction','')).upper())}</td>"
                     f"<td>{sw}</td></tr>")


    js = JS.format(tickers=_js(tickers_js), deltas=_js(deltas_js), sectors=_js(sectors_js))
    tst = f"trade_ai_{run_label}.tst"

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade AI v12 · {_e(run_label)} · {_e(date_str)}</title>
<style>{CSS}</style></head><body>
<div class="top-nav"><div><div class="brand">Trade AI <span>v12</span></div>
<div class="run-meta">Run {_e(run_label)} · {_e(date_str)} · {ts}</div></div>
<div class="nav-pills">
<span class="pill tos-pill" onclick="jumpTo('tos')">🎯 TOS</span>
<span class="pill" onclick="jumpTo('market')">📊 Market</span>
<span class="pill" onclick="jumpTo('delta')">📡 Changes</span>
<span class="pill" onclick="jumpTo('setups')">🃏 Setups</span>
<span class="pill" onclick="jumpTo('catalysts')">📰 Catalysts</span>
</div></div>
<div class="session-banner" style="background:{sess_bg}"><span>{sess_emj}</span>
<span style="font-weight:700">{_e(sess_lbl)}</span>
<span style="color:#9A9AB0;font-size:11px">{_e(sess_desc)}</span></div>
<div class="sentiment-bar"><span class="sent-badge {sent_cls}">{sent_txt}</span>
<div class="sent-detail">SPY <b>{_sign(spy_pct)}%</b> · QQQ <b>{_sign(qqq_pct)}%</b> · VIX <b>{vix_val:.1f}</b> · {len(go_list)} GO · {_e(sess_lbl)}</div></div>
{exec_strip_html}
{regime_html}
<div class="stats-bar">
<div class="stat" onclick="filterBy('all')" id="s-all"><div class="stat-val">{len(scored_tickers)}</div><div class="stat-lbl">Scanned</div></div>
<div class="stat go-chip" onclick="filterBy('GO')" id="s-go"><div class="stat-val up">{len(go_list)}</div><div class="stat-lbl">GO Tier</div></div>
<div class="stat" onclick="filterBy('WAIT')" id="s-wait"><div class="stat-val" style="color:#F4B400">{len(wait_list)}</div><div class="stat-lbl">WAIT</div></div>
<div class="stat" onclick="filterBy('AVOID')" id="s-av"><div class="stat-val nt">{len(scored_tickers)-len(go_list)-len(wait_list)}</div><div class="stat-lbl">Avoid</div></div>
<div class="stat" onclick="jumpTo('delta')"><div class="stat-val">{len(delta.get('events',[]))}</div><div class="stat-lbl">Δ Events</div></div>
<div class="stat top-chip"><div class="stat-val" style="color:#1A73E8">{_e(top_sym)}</div><div class="stat-lbl">Top ({top_score})</div></div>
<div class="stat" onclick="filterBy('catalyst')"><div class="stat-val" style="color:#F4B400">{with_cat}</div><div class="stat-lbl">Catalysts</div></div>
<div class="stat"><div class="stat-val nt">{vix_val:.1f}</div><div class="stat-lbl">VIX</div></div>
</div>
<div style="padding:0 12px 6px;font-size:11px;color:#9A9AB0">
<span id="filter-lbl" style="background:#1A73E8;color:#fff;border-radius:10px;padding:2px 8px;font-size:10px">Showing: All</span>
&nbsp; Click stats to filter · Click row to expand · FV opens Finviz Elite</div>
<div class="tos-box" id="tos"><div class="tos-title">🎯 ThinkorSwim Export</div>
<div class="tos-row"><div class="tos-grp"><div class="tos-lbl">GO-Tier Symbols</div>
<input type="text" class="tos-input go-color" id="go-syms" readonly value="{_e(go_syms)}" placeholder="— no GO tickers —"></div>
<button class="copybtn go" onclick="doCopy('go-syms',this)">Copy GO</button></div>
<div class="tos-row"><div class="tos-grp"><div class="tos-lbl">All Qualified (GO + WAIT)</div>
<input type="text" class="tos-input all-color" id="all-syms" readonly value="{_e(all_syms)}" placeholder="— no qualified tickers —"></div>
<button class="copybtn all" onclick="doCopy('all-syms',this)">📋 Copy All</button></div>
<div class="tos-steps"><b>Import .tst:</b> TOS → Watchlists → Gear ⚙ → <b>Import Watchlist</b> → <code>reports\\{_e(date_str)}\\{_e(run_label)}\\{_e(tst)}</code><br>
<b>Paste:</b> Click <b>Copy All</b> → TOS → New Watchlist → Paste
{f'<br><span style="color:#F4B400">⚠ Earnings on watchlist: {", ".join(_e(s) for s in wl_earn)}</span>' if wl_earn else ""}</div></div>
<div class="section" id="market">
<div class="section-hdr">📊 Sector Heatmap <span class="badge">{sess_emj} {_e(sess_lbl)}</span>
<span class="collapse-btn" onclick="tog('heatmap-body',this)">▲ hide</span></div>
<div id="heatmap-body"><div class="heatmap-grid" id="heatmap-grid"></div>
<div style="font-size:11px;color:#9A9AB0;display:flex;gap:16px;flex-wrap:wrap;margin-top:4px">
<span>▲ Leaders: <span style="color:#0F9D58" id="leaders-txt">—</span></span>
<span>▼ Laggards: <span style="color:#DB4437" id="laggards-txt">—</span></span></div></div></div>
<div class="two-col">
<div class="section" style="margin:0"><div class="section-hdr">📅 Economic Calendar
<span class="badge">{len(hi_events)} high-impact</span>
<span class="collapse-btn" onclick="tog('cal-body',this)">▲ hide</span></div>
<div id="cal-body"><table class="cal-table"><thead><tr><th>Time</th><th>Impact</th><th>Event</th><th>Fcst</th><th>Prior</th></tr></thead>
<tbody>{cal_rows or '<tr><td colspan="5" class="nt" style="padding:8px">No high-impact events today</td></tr>'}</tbody></table>
<div style="margin-top:8px;font-size:11px;color:#9A9AB0;font-weight:700">Earnings Today/Tomorrow</div>
<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:5px">
{earn_chips or '<span class="nt" style="font-size:11px">None scheduled</span>'}</div></div></div>
<div class="section" style="margin:0"><div class="section-hdr">⚡ Options Flow
<span class="badge">{options_summary.get('total_sweeps',0)} sweeps · {options_summary.get('bullish_count',0)}🟢/{options_summary.get('bearish_count',0)}🔴</span>
<span class="collapse-btn" onclick="tog('opt-body',this)">▲ hide</span></div>
<div id="opt-body"><table class="opt-table"><thead><tr><th>Ticker</th><th>Type</th><th>Strike</th><th>Expiry</th><th>Vol</th><th>Premium</th><th>Dir</th><th></th></tr></thead>
<tbody>{opt_rows or '<tr><td colspan="8" class="nt" style="padding:8px">No unusual flow detected</td></tr>'}</tbody></table></div></div></div>
<div class="section" id="delta"><div class="section-hdr">📡 What Changed
<span class="badge">{len(delta.get('events',[]))} events · click to expand</span>
<span class="collapse-btn" onclick="tog('delta-body',this)">▲ hide</span></div>
<div id="delta-body"></div></div>
<div style="padding:4px 12px 2px;display:flex;align-items:center;gap:8px"><button class="sf-btn active" id="sf-btn" onclick="toggleScoreFilter()">Score ≥15 Active (click for all)</button></div>
<div class="section" id="setups"><div class="section-hdr">🃏 Setups
<span class="badge" id="setups-count">{len(scored_tickers)} tickers</span>
<span class="collapse-btn" onclick="tog('setups-body',this)">▲ hide</span></div>
<div id="setups-body" style="overflow-x:auto"><table class="ticker-tbl">
<thead><tr>
<th onclick="srt('sym')">Symbol ↕</th><th onclick="srt('score')">Score ↕</th>
<th onclick="srt('dec')">Decision ↕</th><th onclick="srt('rvol')">RVOL ↕</th>
<th onclick="srt('price')">Price ↕</th><th onclick="srt('chg')">Chg% ↕</th>
<th onclick="srt('gap')">Gap% ↕</th><th onclick="srt('float_m')">Float ↕</th>
<th>Country</th><th>Sector</th><th>Criteria</th><th>Social</th><th>Catalyst</th><th>Chart</th>
</tr></thead><tbody id="tbl-body"></tbody></table></div></div>
<div class="section" id="catalysts"><div class="section-hdr">📰 Catalyst Tape
<span class="collapse-btn" onclick="tog('cat-body',this)">▲ hide</span></div>
<div id="cat-body"></div></div>
<footer>Trade AI v12 · Run {_e(run_label)} · {_e(date_str)} · {len(scored_tickers)} tickers · Auto-refresh 60s · {ts}</footer>
<script>{js}</script></body></html>"""

    html_path.write_text(page, encoding="utf-8")
    if institutional:
        inst_path.write_text(page, encoding="utf-8")
    return str(html_path)
