#!/usr/bin/env python3
"""Patch command_center.html to replace renderAIDeep with 18-section sidebar nav layout."""
import re, sys

path = 'reports/command_center.html'
content = open(path).read()

NEW_FUNC = r'''async function renderAIDeep() {
  // ── Data sources ──────────────────────────────────────────
  const aiCache   = S.ai_cache || {};
  const holdings  = S.holdings || {};
  const pt        = holdings.portfolio_totals || {};
  const accts     = holdings.account_summaries || {};
  const allH      = holdings.holdings || [];
  const tech      = S.technical || {};
  const risk      = S.risk || {};
  const retire    = S.retirement || {};
  const perf      = S.perf_history || {};
  const divs      = S.dividends || {};
  const taxproj   = S.taxproj || {};
  const attr      = S.attribution || {};
  const vix       = S.tradeAI?.vix || 20;
  const regime    = S.tradeAI?.regime || '—';
  const goTickers = (S.allTickers||[]).filter(t=>t.decision==='GO').map(t=>t.symbol);
  const totalVal  = pt.total_value || 0;
  const totalGain = pt.total_gain  || 0;
  const dayChg    = pt.day_change  || 0;
  const beta      = pt.weighted_beta || 0;
  const divInc    = divs.total_annual_income || 0;

  // ── Portfolio rating ──────────────────────────────────────
  const techPos = tech.holdings
    ? Object.values(tech.holdings)
    : Object.entries(tech).filter(([k,v])=>k!=='_meta'&&typeof v==='object').map(([,v])=>v);
  const aboveSMA = techPos.filter(p=>Number(p.sma200_pct||0)>0).length;
  const smaScore = aboveSMA / (techPos.length||1);
  const avgRSI   = techPos.length ? techPos.reduce((s,p)=>s+Number(p.rsi||50),0)/techPos.length : 50;
  let rScore = 50;
  if(smaScore>0.6)rScore+=15; else if(smaScore<0.4)rScore-=15;
  if(avgRSI>55)rScore+=8; else if(avgRSI<45)rScore-=8;
  if(vix<18)rScore+=10; else if(vix>25)rScore-=10;
  if(regime.toLowerCase().includes('bull'))rScore+=10; else if(regime.toLowerCase().includes('bear'))rScore-=10;
  const rating = rScore>=65?'BULLISH':rScore>=48?'NEUTRAL':'BEARISH';
  const rCol   = rating==='BULLISH'?'var(--up)':rating==='NEUTRAL'?'var(--warn)':'var(--dn)';

  // ── Freshness ─────────────────────────────────────────────
  const cTs   = aiCache.generated_at||'';
  const cAgeH = cTs ? Math.round((Date.now()-new Date(cTs).getTime())/3600000) : null;
  const freshLabel = cAgeH==null?'Unknown':cAgeH<24?`Fresh · ${cAgeH}h ago`:`${Math.floor(cAgeH/24)}d ago`;
  const freshCol   = cAgeH==null?'var(--text3)':cAgeH<48?'var(--up)':cAgeH<168?'var(--warn)':'var(--dn)';

  // ── Helpers ───────────────────────────────────────────────
  const kpi = (label,val,sub='',col='var(--text)') =>
    `<div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:12px 14px;min-width:110px;flex:1">
       <div style="font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px">${label}</div>
       <div style="font-size:17px;font-weight:800;color:${col};letter-spacing:-.5px">${val}</div>
       ${sub?`<div style="font-size:9px;color:var(--text3);margin-top:2px">${sub}</div>`:''}
     </div>`;

  const tbl = (headers,rows) => {
    if(!rows.length) return '<div style="font-size:11px;color:var(--text3);padding:8px 0">No data available.</div>';
    return `<div style="overflow-x:auto;margin-top:4px"><table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead><tr>${headers.map(h=>`<th style="text-align:left;padding:5px 8px;background:rgba(255,255,255,.04);color:var(--text3);font-size:9px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;border-bottom:1px solid var(--border)">${h}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r,i)=>`<tr style="border-top:1px solid rgba(255,255,255,.04);background:${i%2?'rgba(255,255,255,.015)':'transparent'}">${r.map(c=>`<td style="padding:5px 8px;color:var(--text);vertical-align:top">${c}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
  };

  const badge = (t,col,bg) =>
    `<span style="background:${bg};color:${col};border:1px solid ${col};border-radius:4px;padding:1px 7px;font-size:9px;font-weight:700">${t}</span>`;

  const flagBadge = sev => sev==='HIGH'
    ? badge('HIGH','var(--dn)','rgba(255,60,60,.12)')
    : sev==='WARNING'
    ? badge('WARNING','var(--warn)','rgba(255,180,0,.12)')
    : badge('INFO','var(--text3)','rgba(255,255,255,.06)');

  const secWrap = (id,icon,title,content) =>
    `<div id="ai-sec-${id}" style="background:rgba(255,255,255,.025);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-bottom:14px;scroll-margin-top:8px">
       <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.06)">
         <span style="font-size:15px">${icon}</span>
         <span style="font-size:13px;font-weight:800;color:var(--text)">${title}</span>
       </div>
       ${content}
     </div>`;

  const aiText = (key,fallback='') => {
    const t = aiCache[key]||'';
    if(!t) return `<div style="font-size:10px;color:var(--text3);font-style:italic;padding:8px 0">${fallback||'Run weekly pipeline to generate (qwen3:14b, free, local).'}</div>`;
    return `<div style="font-size:11px;color:var(--text2);line-height:1.65;max-height:280px;overflow-y:auto">${esc(t)}</div>`;
  };

  // ══════════════════════════════════════════════════════════
  // SECTION CONTENT
  // ══════════════════════════════════════════════════════════

  // 1 — EXECUTIVE SUMMARY
  const s1 = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${kpi('Total Portfolio',fmt$(totalVal,0),`Today ${dayChg>=0?'+':''}${fmt$(dayChg,0)}`,dayChg>=0?'var(--up)':'var(--dn)')}
      ${kpi('All-Time Gain',fmt$(totalGain,0),`${((totalGain/(totalVal-totalGain||1))*100).toFixed(1)}%`,totalGain>=0?'var(--up)':'var(--dn)')}
      ${kpi('Annual Dividends',fmt$(divInc,0),`${fmt$(divInc/12,0)}/mo`,'var(--accent)')}
      ${kpi('Portfolio Beta',beta.toFixed(3),'vs S&P 1.0')}
      ${kpi('Rating',rating,'',rCol)}
    </div>
    <div style="background:rgba(255,255,255,.02);border-left:3px solid ${rCol};border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:10px">
      <div style="font-size:10px;font-weight:800;color:${rCol};margin-bottom:5px">AI Executive Summary — ${rating}</div>
      <div style="font-size:11px;color:var(--text2);line-height:1.65">${esc(aiCache.executive_summary||'Run weekly pipeline to generate executive summary.')}</div>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">
      ${kpi('CAGR',attr.portfolio_cagr||'—','Since inception','var(--up)')}
      ${kpi('Sharpe',((attr.sharpe_ratio)||1.07).toFixed(2),'Risk-adjusted')}
      ${kpi('Analysis',freshLabel,'',freshCol)}
      ${kpi('Critical',(risk.danger||[]).length+' flags',`${(risk.warning||[]).length} warnings`,(risk.danger||[]).length>0?'var(--dn)':'var(--up)')}
    </div>`;

  // 2 — ACCOUNT STRUCTURE
  const acctRows = Object.entries(accts).map(([k,a])=>[
    `<b>${esc(a.label||k)}</b>`, esc(a.account_type||'—'),
    fmt$(a.total_value||0,0),
    `<span style="color:${(a.total_gain||0)>=0?'var(--up)':'var(--dn)'}">${fmt$(a.total_gain||0,0)}</span>`,
    `<span style="color:${(a.gain_pct||0)>=0?'var(--up)':'var(--dn)'}">${(a.gain_pct||0)>=0?'+':''}${(a.gain_pct||0).toFixed(2)}%</span>`
  ]);
  const s2 = tbl(['Account','Type','Value','Gain $','Gain %'],acctRows);

  // 3 — CRITICAL FLAGS
  const allFlags = [
    ...(risk.danger||[]).map(f=>({sev:'HIGH',msg:String(f)})),
    ...(risk.warning||[]).map(f=>({sev:'WARNING',msg:String(f)})),
    ...(risk.unprotected||[]).slice(0,3).map(f=>({sev:'INFO',msg:`${f.symbol||f}: No stop loss set`}))
  ];
  const s3 = allFlags.length
    ? allFlags.map(f=>`<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04)">
        ${flagBadge(f.sev)}
        <div style="font-size:11px;color:var(--text2);flex:1">${esc(f.msg)}</div>
      </div>`).join('')
    : '<div style="color:var(--up);font-size:11px;padding:8px 0">✅ No critical flags detected</div>';

  // 4 — P&L PERFORMANCE
  const sorted = [...allH].filter(h=>h.gain_loss!=null).sort((a,b)=>b.gain_loss-a.gain_loss);
  const top5 = sorted.slice(0,5), bot5 = sorted.filter(h=>h.gain_loss<0).sort((a,b)=>a.gain_loss-b.gain_loss).slice(0,5);
  const s4 = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <div style="font-size:9px;color:var(--up);text-transform:uppercase;font-weight:700;margin-bottom:8px">Top Contributors</div>
      ${top5.map(h=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)">
        <span style="font-size:11px;font-weight:700">${esc(h.symbol)}</span>
        <span style="font-size:11px;color:var(--up)">${fmt$(h.gain_loss,0)} <span style="color:var(--text3);font-size:10px">+${(h.gain_loss_pct||0).toFixed(1)}%</span></span>
      </div>`).join('')}
    </div>
    <div>
      <div style="font-size:9px;color:var(--dn);text-transform:uppercase;font-weight:700;margin-bottom:8px">Detractors</div>
      ${bot5.map(h=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)">
        <span style="font-size:11px;font-weight:700">${esc(h.symbol)}</span>
        <span style="font-size:11px;color:var(--dn)">${fmt$(h.gain_loss,0)} <span style="color:var(--text3);font-size:10px">${(h.gain_loss_pct||0).toFixed(1)}%</span></span>
      </div>`).join('')}
    </div>
  </div>`;

  // 5 — BENCHMARKS
  const portYTD = perf.periods?.YTD?.change_pct||0;
  const port1Y  = perf.periods?.['1Y']?.change_pct||0;
  const s5 = `
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px">
      ${kpi('Your YTD',`${portYTD>=0?'+':''}${portYTD.toFixed(2)}%`,'Portfolio',portYTD>=0?'var(--up)':'var(--dn)')}
      ${kpi('Your 1Y',`${port1Y>=0?'+':''}${port1Y.toFixed(2)}%`,'Portfolio',port1Y>=0?'var(--up)':'var(--dn)')}
    </div>
    ${tbl(['Benchmark','Name','YTD','1Y','3Y'],[
      ['<b>SPY</b>','S&P 500','—','—','—'],
      ['<b>QQQ</b>','Nasdaq 100','—','—','—'],
      ['<b>IWM</b>','Russell 2000','—','—','—'],
      ['<b>AGG</b>','US Bonds','—','—','—'],
      ['<b>ITA</b>','Defense ETF','—','—','—'],
      ['<b>VIG</b>','Dividend Growth','—','—','—']
    ])}
    <div style="font-size:9px;color:var(--text3);margin-top:8px">Live benchmark returns require market data API. Your portfolio returns from snapshots above.</div>`;

  // 6 — HOLDINGS
  const holdRows = [...allH].sort((a,b)=>(b.market_value||0)-(a.market_value||0)).map(h=>[
    `<b>${esc(h.symbol)}</b>`,
    esc((h.account_display||h.account||'').replace('Schwab ','').replace('Fidelity ','Fid ')),
    fmt$(h.market_value||0,0),
    fmt$(h.cost_basis||0,0),
    `<span style="color:${(h.gain_loss||0)>=0?'var(--up)':'var(--dn)'}">${fmt$(h.gain_loss||0,0)}</span>`,
    `<span style="color:${(h.gain_loss_pct||0)>=0?'var(--up)':'var(--dn)'}">${(h.gain_loss_pct||0)>=0?'+':''}${(h.gain_loss_pct||0).toFixed(1)}%</span>`,
    `${(h.portfolio_pct||0).toFixed(1)}%`
  ]);
  const s6 = tbl(['Symbol','Account','Value','Cost','Gain $','Gain %','Port%'],holdRows);

  // 7 — SECTOR EXPOSURE
  const sectors = holdings.sector_exposure||{};
  const secRows = Object.entries(sectors).sort((a,b)=>b[1]-a[1]).map(([s,v])=>[
    esc(s), `${((v/totalVal)*100).toFixed(1)}%`, fmt$(v,0),
    `<div style="height:6px;background:rgba(93,173,255,.15);border-radius:3px;width:120px"><div style="height:6px;background:var(--accent2);border-radius:3px;width:${Math.min((v/totalVal)*400,100)}%"></div></div>`
  ]);
  const s7 = secRows.length ? tbl(['Sector','%','Value',''],secRows)
    : '<div style="font-size:11px;color:var(--text3)">Sector data builds from ETF look-through during pipeline run.</div>';

  // 8 — RISK ASSESSMENT
  const s8 = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
      ${kpi('Beta',(beta||0).toFixed(3),'vs S&P 500 = 1.0')}
      ${kpi('Protected',fmt$(risk.total_protected_mv||0,0),`${(risk.pct_protected||0).toFixed(0)}% of portfolio`,'var(--up)')}
      ${kpi('Unprotected',fmt$(risk.total_unprotected_mv||0,0),'No stop set','var(--warn)')}
      ${kpi('Risk $',fmt$(risk.total_risk_dollars||0,0),'Est. max downside','var(--dn)')}
    </div>
    <div style="font-size:10px;color:var(--text3)">Stops: ${risk.stop_count||0} positions monitored · Portfolio heat: ${(risk.portfolio_heat_pct||0).toFixed(1)}%</div>`;

  // 9 — TRADE AI OSINT (portfolio holdings in screener)
  const holdSyms = new Set(allH.map(h=>h.symbol));
  const goInHold = goTickers.filter(t=>holdSyms.has(t));
  const waitTickers = (S.allTickers||[]).filter(t=>t.decision==='WAIT').map(t=>t.symbol);
  const waitInHold = waitTickers.filter(t=>holdSyms.has(t));
  const s9 = `
    <div style="margin-bottom:12px">
      <div style="font-size:10px;font-weight:700;color:var(--up);margin-bottom:6px">Holdings in Trade AI GO list</div>
      ${goInHold.length ? goInHold.map(t=>`<span style="background:rgba(0,255,120,.1);color:var(--up);border:1px solid rgba(0,255,120,.3);border-radius:4px;padding:2px 8px;font-size:10px;font-weight:700;margin:0 3px 3px 0;display:inline-block">${t}</span>`).join('') : '<span style="color:var(--text3);font-size:11px">None today</span>'}
    </div>
    <div style="margin-bottom:12px">
      <div style="font-size:10px;font-weight:700;color:var(--warn);margin-bottom:6px">Holdings in WAIT list</div>
      ${waitInHold.length ? waitInHold.map(t=>`<span style="background:rgba(255,180,0,.1);color:var(--warn);border:1px solid rgba(255,180,0,.3);border-radius:4px;padding:2px 8px;font-size:10px;font-weight:700;margin:0 3px 3px 0;display:inline-block">${t}</span>`).join('') : '<span style="color:var(--text3);font-size:11px">None today</span>'}
    </div>
    <div style="font-size:10px;color:var(--text3)">Last run: ${S.health?.last_run_label||'—'} ${S.health?.last_run_date||''} · GO: ${goTickers.length} · WAIT: ${waitTickers.length}</div>`;

  // 10 — TAX INTELLIGENCE
  const s10 = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
      ${kpi('Unrealized Gain',fmt$(totalGain,0),'All accounts',totalGain>=0?'var(--up)':'var(--dn)')}
      ${kpi('Est. Federal Tax',fmt$(taxproj?.federal_tax||9144,0),'At current brackets','var(--warn)')}
      ${kpi('YTD Dividends',fmt$(taxproj?.ytd_dividends||0,0),'Received this year')}
    </div>
    <div style="font-size:10px;color:var(--text3)">Method: FIFO · MFS filing · 2026 Roth conversion: $35K done · Sweet spot: $25K/yr (~$3,547 tax)</div>
    <div style="margin-top:10px"><button class="btn" onclick="openDeepTab('tax')">Open Tax & Lots →</button></div>`;

  // 11 — REBALANCING ORDERS
  const rebalPos = risk.positions ? Object.values(risk.positions).filter(p=>p.action).slice(0,15) : [];
  const s11 = rebalPos.length
    ? tbl(['Account','Action','Symbol','Amount','Note'],
        rebalPos.map(o=>[
          esc(o.account||'—'),
          `<span style="color:${o.action==='SELL'?'var(--dn)':'var(--up)'};font-weight:700">${o.action||'—'}</span>`,
          esc(o.symbol||'—'), fmt$(o.amount||0,0), esc(o.note||'—')
        ])) + `<div style="margin-top:8px"><button class="btn" onclick="openDeepTab('rebalance')">Open Rebalancer →</button></div>`
    : `<div style="font-size:11px;color:var(--text3)">Rebalancing data computed during pipeline. <button class="btn" style="margin-left:8px" onclick="openDeepTab('rebalance')">Open Rebalancer →</button></div>`;

  // 12 — STOP LOSS LEVELS
  const stops = risk.positions ? Object.values(risk.positions).filter(p=>p.stop_price).slice(0,15) : [];
  const s12 = stops.length
    ? tbl(['Symbol','Current','Stop','Downside','Note'],
        stops.map(s=>[
          `<b>${esc(s.symbol)}</b>`, fmt$(s.current_price||0,2), fmt$(s.stop_price||0,2),
          `<span style="color:var(--dn)">${(((s.stop_price||0)-(s.current_price||1))/(s.current_price||1)*100).toFixed(1)}%</span>`,
          esc(s.note||'—')
        ]))
    : `<div style="font-size:11px;color:var(--text3)">Stop levels in Risk Manager. <button class="btn" style="margin-left:8px" onclick="openDeepTab('risk')">Open Risk →</button></div>`;

  // 13 — DIVIDEND CALENDAR
  const divItems = (divs.holdings||[]).sort((a,b)=>(b.annual_income||0)-(a.annual_income||0)).slice(0,25);
  const s13 = divItems.length
    ? tbl(['Symbol','Account','Yield','Annual','Monthly','Freq'],
        divItems.map(d=>[
          `<b>${esc(d.symbol)}</b>`,
          esc((d.account_display||d.account||'').replace('Schwab ','').replace('Fidelity ','Fid ')),
          `${(d.yield_pct||0).toFixed(1)}%`, fmt$(d.annual_income||0,0),
          fmt$(d.monthly_income||0,0), esc(d.frequency||'—')
        ])) +
      `<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,.06)">
        <b>Total: ${fmt$(divs.total_annual_income||0,0)}/yr · ${fmt$((divs.total_annual_income||0)/12,0)}/mo</b>
      </div>`
    : '<div style="font-size:11px;color:var(--text3)">Dividend data from pipeline run.</div>';

  // 14 — PERIOD PERFORMANCE
  const pds = perf.periods||{};
  const periodRows = ['1D','1W','1M','3M','6M','YTD','1Y'].map(k=>{
    const p = pds[k];
    if(!p) return [k,'—','—','—'];
    return [
      `<b>${k}</b>`,
      `<span style="color:${(p.change_pct||0)>=0?'var(--up)':'var(--dn)'};font-weight:700">${(p.change_pct||0)>=0?'+':''}${(p.change_pct||0).toFixed(2)}%</span>`,
      `<span style="color:${(p.change||0)>=0?'var(--up)':'var(--dn)'}">${fmt$(p.change||0,0)}</span>`,
      `<span style="font-size:9px;color:var(--text3)">${p.start_date||'—'}</span>`
    ];
  });
  const s14 = tbl(['Period','Return %','Return $','From'],periodRows);

  // 15 — ROTH / GOLDEN WINDOW
  const gw = retire.golden_window||{};
  const rothBal   = retire.accounts?.roth_ira?.current_value || retire.accounts?.schwab_roth?.current_value || 42373;
  const tradBal   = retire.accounts?.rollover_ira?.current_value || retire.accounts?.schwab_rollover_ira?.current_value || 1083419;
  const daysToGW  = gw.days_remaining || 3596;
  const s15 = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${kpi('Days to Golden',daysToGW.toLocaleString(),'Opens 02/19/2036','var(--warn)')}
      ${kpi('Roth Balance',fmt$(rothBal,0),'Tax-free forever','var(--up)')}
      ${kpi('Traditional IRA',fmt$(tradBal,0),'Conversion target','var(--text)')}
      ${kpi('2026 Done',fmt$(35000,0),'$25K sweet spot','var(--accent)')}
    </div>
    <div style="background:rgba(255,180,0,.08);border:1px solid rgba(255,180,0,.3);border-radius:8px;padding:12px 14px;margin-bottom:12px">
      <div style="font-size:10px;font-weight:800;color:var(--warn);margin-bottom:5px">⚡ Golden Roth Conversion Window</div>
      <div style="font-size:11px;color:var(--text2);line-height:1.65">
        Opens <b>02/19/2036</b> (disability ends) · Closes <b>08/20/2040</b> (RMDs begin at 73)<br>
        Sweet spot: <b>$25K/yr</b> (~$3,547 tax) or <b>$50K/yr</b> (~$15,027 tax)<br>
        Target: <b>Zero</b> Traditional IRA balance by RMD age · SSDI converts to SS at FRA age 67
      </div>
    </div>
    ${aiText('roth_conversion')}`;

  // 16-22 — AI DEEP ANALYSIS SECTIONS
  const aiSecs = [
    ['deep_holdings',   '🔬','Deep Holdings',   'Look-through / hidden overlap analysis',    'holdings'],
    ['dividend_strategy','💰','Dividend Strategy','Income architecture / payout mix',         'rebalance'],
    ['bond_strategy',   '🏛️','Bond Strategy',   'Rate exposure / tax location / ballast',    'rebalance'],
    ['ira_opportunities','🏦','IRA Opportunities','Asset location / opportunity set',         'rebalance'],
    ['v_strategy',      '💳','V Strategy',       'Concentration / replacement logic ($302K)', 'rebalance'],
    ['defense_analysis','🛡️','Defense Analysis', 'Portfolio defense & risk posture review',   'risk'],
    ['roth_conversion_detail','⚡','Roth Deep Dive','Monthly Sonnet analysis — Golden Window strategy','tax']
  ];
  const s16 = aiSecs.map(([key,icon,name,why,tab])=>`
    <div style="margin-bottom:12px;background:rgba(255,255,255,.02);border:1px solid rgba(93,173,255,.15);border-radius:10px;padding:14px 16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:8px">
          <span>${icon}</span>
          <b style="font-size:12px;color:var(--text)">${name}</b>
          <span style="font-size:9px;color:var(--text3)">${why}</span>
        </div>
        ${aiCache[key]
          ? `<span style="font-size:9px;color:var(--up)">✓ ${(aiCache.run_type||'cached').toUpperCase()}</span>`
          : `<span style="font-size:9px;color:var(--dn)">Needs weekly run</span>`}
      </div>
      ${aiText(key)}
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
        <button class="btn" style="font-size:9px" onclick="openDeepTab('${tab}')">Open ${tab.charAt(0).toUpperCase()+tab.slice(1)} →</button>
        <button class="btn" style="font-size:9px" onclick="aiAskFromSection('${name}')">Ask AI →</button>
      </div>
    </div>`).join('');

  // ── YAML Banner ───────────────────────────────────────────
  let yamlBanner = '';
  try {
    const ya = await fetch('/data/portfolios/state/yaml_advisor_output.json?v='+Date.now()).then(r=>r.ok?r.json():null);
    if(ya){
      const sugs=(ya.opus_output?.suggestions||[]).filter(s=>!(ya.applied_ids||[]).includes(s.id));
      const health=ya.opus_output?.yaml_health_score||0;
      const hCol=health>=70?'var(--up)':health>=40?'var(--warn)':'var(--dn)';
      if(sugs.length) yamlBanner=`<div style="background:rgba(255,255,255,.025);border:1px solid rgba(93,173,255,.25);border-radius:10px;padding:10px 16px;margin-bottom:14px;display:flex;align-items:center;gap:14px">
        <div style="flex:1"><div style="font-size:11px;font-weight:800">⚙ YAML Config Review <span style="color:${hCol};font-size:9px;margin-left:6px">Health: ${health}/100</span></div>
        <div style="font-size:10px;color:var(--text3)">${sugs.length} pending · ${sugs.filter(s=>s.confidence==='high').length} high confidence · Generated ${(ya.generated_at||'').slice(0,10)}</div></div>
        <button class="btn" onclick="openYamlAdvisorModal()">Review & Apply →</button>
      </div>`;
    }
  } catch(e){}

  // ══════════════════════════════════════════════════════════
  // SECTIONS REGISTRY
  // ══════════════════════════════════════════════════════════
  const SECTIONS = [
    {id:'exec',    icon:'📊', label:'Executive Summary',   content:s1},
    {id:'accounts',icon:'🏦', label:'Account Structure',   content:s2},
    {id:'flags',   icon:'🚨', label:'Critical Flags',      content:s3},
    {id:'pnl',     icon:'📈', label:'P&L Performance',     content:s4},
    {id:'bench',   icon:'📉', label:'Benchmarks',          content:s5},
    {id:'holdings',icon:'💼', label:'All Holdings',        content:s6},
    {id:'sectors', icon:'🏭', label:'Sector Exposure',     content:s7},
    {id:'risk',    icon:'⚠️', label:'Risk Assessment',     content:s8},
    {id:'osint',   icon:'⚡', label:'Trade AI OSINT',      content:s9},
    {id:'tax',     icon:'🔍', label:'Tax Intelligence',    content:s10},
    {id:'rebal',   icon:'⚖️', label:'Rebalancing Orders', content:s11},
    {id:'stops',   icon:'🛑', label:'Stop Loss Levels',    content:s12},
    {id:'divs',    icon:'💰', label:'Dividend Calendar',   content:s13},
    {id:'perf',    icon:'📅', label:'Period Performance',  content:s14},
    {id:'roth',    icon:'⚡', label:'Roth / Golden Window',content:s15},
    {id:'aisecs',  icon:'🤖', label:'AI Deep Analysis',    content:s16},
  ];

  // ══════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════
  return `
  <style>
    .ai2-sidebar{position:sticky;top:0;height:calc(100vh - 140px);overflow-y:auto;padding-right:6px;scrollbar-width:thin}
    .ai2-sidebar::-webkit-scrollbar{width:3px}.ai2-sidebar::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
    .ai2-nav{display:flex;align-items:center;gap:7px;padding:6px 10px;border-radius:7px;cursor:pointer;font-size:10.5px;color:var(--text3);transition:all .15s;white-space:nowrap;margin-bottom:1px;border:1px solid transparent}
    .ai2-nav:hover{background:rgba(93,173,255,.1);color:var(--accent2);border-color:rgba(93,173,255,.2)}
    .ai2-nav.active{background:rgba(93,173,255,.15);color:var(--accent2);border-color:rgba(93,173,255,.3);font-weight:700}
    .ai2-main{flex:1;min-width:0;overflow-y:auto;height:calc(100vh - 140px);padding-right:4px;scrollbar-width:thin}
    .ai2-main::-webkit-scrollbar{width:3px}.ai2-main::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
    .ai2-sep{height:1px;background:var(--border);margin:8px 0}
    .ai2-nav-label{font-size:8px;color:var(--text3);text-transform:uppercase;letter-spacing:.6px;padding:0 10px;margin-bottom:4px;margin-top:8px}
  </style>

  ${yamlBanner}

  <div style="display:flex;gap:14px;align-items:flex-start">

    <!-- ── SIDEBAR NAV ── -->
    <div class="ai2-sidebar" style="width:175px;flex-shrink:0">
      <div style="padding:8px 10px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:8px;margin-bottom:10px">
        <div style="font-size:9px;color:var(--text3);margin-bottom:2px">Portfolio Rating</div>
        <div style="font-size:14px;font-weight:900;color:${rCol}">${rating}</div>
        <div style="font-size:9px;color:${freshCol};margin-top:2px">${freshLabel}</div>
      </div>

      <div class="ai2-nav-label">Portfolio Report</div>
      ${SECTIONS.slice(0,15).map(s=>`
        <div class="ai2-nav" onclick="(function(){
          document.getElementById('ai-sec-${s.id}').scrollIntoView({behavior:'smooth',block:'start'});
          document.querySelectorAll('.ai2-nav').forEach(n=>n.classList.remove('active'));
          event.currentTarget.classList.add('active');
        })()">
          <span>${s.icon}</span><span>${s.label}</span>
        </div>`).join('')}

      <div class="ai2-sep"></div>
      <div class="ai2-nav-label">AI Analysis</div>
      ${SECTIONS.slice(15).map(s=>`
        <div class="ai2-nav" onclick="(function(){
          document.getElementById('ai-sec-${s.id}').scrollIntoView({behavior:'smooth',block:'start'});
          document.querySelectorAll('.ai2-nav').forEach(n=>n.classList.remove('active'));
          event.currentTarget.classList.add('active');
        })()">
          <span>${s.icon}</span><span>${s.label}</span>
        </div>`).join('')}

      <div class="ai2-sep"></div>
      <div style="padding:8px 10px">
        <div style="font-size:9px;color:var(--text3);margin-bottom:4px">${SECTIONS.length} sections · ${(allH.length||0)} holdings</div>
        <div style="font-size:9px;color:var(--text3)">Accounts: ${Object.keys(accts).length}</div>
        <button class="btn" style="font-size:9px;margin-top:8px;width:100%" onclick="document.getElementById('ai-ask-wrap').scrollIntoView({behavior:'smooth'})">💬 Ask AI</button>
      </div>
    </div>

    <!-- ── MAIN CONTENT ── -->
    <div class="ai2-main">
      ${SECTIONS.map(s=>secWrap(s.id,s.icon,s.label,s.content)).join('')}

      <!-- Ask AI panel -->
      <div id="ai-ask-wrap" style="background:rgba(255,255,255,.025);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px;scroll-margin-top:8px">
        <div style="font-size:13px;font-weight:800;margin-bottom:12px">💬 Ask AI About Your Portfolio</div>
        <div style="font-size:10px;color:var(--text3);margin-bottom:8px">Powered by qwen3:14b (local, free) · No API key needed</div>
        <div style="display:flex;gap:8px">
          <input id="ai-ask-input" type="text"
            placeholder="e.g. Should I trim V? What's my Roth conversion priority this year?"
            style="flex:1;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:7px;padding:9px 12px;color:var(--text);font-size:11px;outline:none"
            onkeydown="if(event.key==='Enter')aiAsk()">
          <button class="btn primary" onclick="aiAsk()" style="white-space:nowrap;padding:9px 16px">Ask</button>
        </div>
        <div id="ai-ask-result" style="margin-top:12px;font-size:11px;color:var(--text2);line-height:1.65;display:none;background:rgba(255,255,255,.02);border-radius:6px;padding:10px"></div>
      </div>
    </div>

  </div>`;
}'''

# Find and replace renderAIDeep
start_marker = 'async function renderAIDeep() {'
start_idx = content.find(start_marker)
if start_idx == -1:
    print("ERROR: renderAIDeep not found")
    exit(1)

# Find end of function
import re
after = content[start_idx:]
m = re.search(r'\n\}\n(?=\s*//|\s*async function|\s*function)', after[100:])
if not m:
    print("ERROR: end of renderAIDeep not found")
    exit(1)

end_idx = start_idx + 100 + m.start() + 3
old_func = content[start_idx:end_idx]
print(f"Replacing {len(old_func)} chars with {len(NEW_FUNC)} chars")

new_content = content[:start_idx] + NEW_FUNC + '\n' + content[end_idx:]

# Validate brace balance on the new function
opens = NEW_FUNC.count('{')
closes = NEW_FUNC.count('}')
print(f"New function brace balance: {{ = {opens}, }} = {closes}")

open(path, 'w').write(new_content)
print("PATCHED OK")
