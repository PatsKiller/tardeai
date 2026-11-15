/* Wealth Portfolio analytics v0.5 — display-only selectors, no I/O or financial actions.
 * Adapter supplies canonical values; this module never derives P&L from quotes/basis.
 * One selected row population must feed cards, charts, table, detail context and CSV.
 */
const present = x => typeof x === 'number' && Number.isFinite(x);
const text = x => typeof x === 'string' ? x.trim() : '';
export const escapeHTML = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sum = values => { let total=0, correction=0; for(const v of values){const y=v-correction,t=total+y;correction=(t-total)-y;total=t;} return total; };
const sectorOf = row => row.isCash ? 'Cash & sweep' : text(row.sector) || 'Unclassified';
const palette = ['#85b7ff','#b4a2f7','#67d6ad','#e7bf78','#e598a3','#62c8d4','#b2c87a','#acbdd2'];
const cashColor = '#a1adbf';
const money = (value,currency,compact=false) => present(value) ? new Intl.NumberFormat('en-US',{style:'currency',currency,notation:compact?'compact':'standard',maximumFractionDigits:compact?1:2}).format(value) : 'Unknown';
const pct = x => present(x) ? new Intl.NumberFormat('en-US',{style:'percent',maximumFractionDigits:1}).format(x) : '—';
const signed = (v,c) => present(v) ? `${v>0?'+':''}${money(v,c,true)}` : 'Unknown';

/** Strict normalized adapter contract. Numeric strings, missing identities,
 * duplicate row identities and conflicting snapshots are rejected, not repaired.
 * sector is direct instrument classification, never inferred ETF look-through.
 */
export function validateRows(rows,snapshotId){
  if(!Array.isArray(rows)) throw new TypeError('Canonical rows must be an array');
  if(!text(snapshotId)) throw new TypeError('A canonical snapshot identity is required');
  const seen=new Set();
  for(const row of rows){
    if(!row || !text(row.rowId) || !text(row.accountId) || !text(row.securityId)) throw new TypeError('Each row requires canonical row, account and security identity');
    if(seen.has(row.rowId)) throw new TypeError('Duplicate canonical row identity');
    seen.add(row.rowId);
    if(row.snapshotId!==snapshotId) throw new TypeError('Mixed snapshot identities');
    if(!/^[A-Z]{3}$/.test(row.currency||'')) throw new TypeError('Each row requires its declared currency');
    if(typeof row.isCash!=='boolean') throw new TypeError('Cash classification must be explicit');
    for(const key of ['marketValue','unrealizedPnl']){
      if(row[key]!=null && !present(row[key])) throw new TypeError(`${key} must be finite or null`);
    }
  }
}

/** Visual totals of published row values, not broker account equity or verified profit.
 * Currency selection has no FX conversion. Negative exposures disable the pie because
 * displaying absolute/net weights as ordinary allocation would misrepresent shorts.
 */
export function derivePortfolioView(rows,scope,snapshot){
  validateRows(rows,snapshot.id);
  const account=scope.account||'',sector=scope.sector||'',query=(scope.query||'').trim().toLowerCase();
  const currencies=[...new Set(rows.map(r=>r.currency))].sort();
  const currency=scope.currency || (currencies.length===1?currencies[0]:null);
  const accountRows=rows.filter(r=>(!account||r.accountId===account)&&(!currency||r.currency===currency));
  const sectorOptions=[...new Set(accountRows.map(sectorOf))].sort();
  const selected=accountRows.filter(r=>(!sector||sectorOf(r)===sector)&&(!query||[r.symbol,r.name,r.accountName,r.accountId].some(s=>String(s||'').toLowerCase().includes(query))));
  const currencyValid=!!currency && /^[A-Z]{3}$/.test(currency) && selected.every(r=>r.currency===currency);
  const valued=selected.filter(r=>present(r.marketValue));
  const pnlRows=selected.filter(r=>!r.isCash&&present(r.unrealizedPnl));
  const nonCash=selected.filter(r=>!r.isCash);
  const total=currencyValid&&valued.length?sum(valued.map(r=>r.marketValue)):null;
  const pnl=currencyValid&&pnlRows.length?sum(pnlRows.map(r=>r.unrealizedPnl)):null;
  const cashRows=selected.filter(r=>r.isCash),knownCash=cashRows.filter(r=>present(r.marketValue));
  const cash=currencyValid&&knownCash.length?sum(knownCash.map(r=>r.marketValue)):cashRows.length===0&&currencyValid?0:null;
  const negative=valued.some(r=>r.marketValue<0);
  const allocationValid=currencyValid&&present(total)&&total>0&&!negative;
  const sectors=new Map(),holdings=new Map();
  for(const r of selected){
    const sk=sectorOf(r);if(!sectors.has(sk))sectors.set(sk,{key:sk,label:sk,value:0,known:0,count:0});
    const s=sectors.get(sk);s.count++;if(present(r.marketValue)){s.value+=r.marketValue;s.known++;}
    // A security may occur in multiple accounts. Only its chart exposure is grouped;
    // callbacks and table retain every account-specific row identity.
    const hk=r.securityId+'|'+r.currency;
    if(!holdings.has(hk))holdings.set(hk,{key:hk,label:r.symbol||r.name||r.securityId,value:0,known:0,count:0,pnl:0,pnlKnown:0,nonCash:!r.isCash,rowIds:[]});
    const h=holdings.get(hk);h.count++;h.rowIds.push(r.rowId);
    if(present(r.marketValue)){h.value+=r.marketValue;h.known++;}
    if(!r.isCash&&present(r.unrealizedPnl)){h.pnl+=r.unrealizedPnl;h.pnlKnown++;}
  }
  const sectorList=[...sectors.values()].sort((a,b)=>b.value-a.value||a.label.localeCompare(b.label)).map(s=>({...s,color:s.key==='Cash & sweep'?cashColor:palette[Math.max(0,[...new Set(rows.map(sectorOf))].sort().indexOf(s.key))%palette.length],weight:allocationValid?s.value/total:null}));
  const holdingList=[...holdings.values()].sort((a,b)=>b.value-a.value||a.label.localeCompare(b.label)).map(h=>({...h,weight:allocationValid&&h.known?h.value/total:null}));
  return {snapshot,scope:{account,sector,query:scope.query||'',currency},currencies,sectorOptions,rows:selected,total,pnl,cash,currencyValid,allocationValid,negative,sectors:sectorList,holdings:holdingList,contributions:holdingList.filter(h=>h.pnlKnown).sort((a,b)=>Math.abs(b.pnl)-Math.abs(a.pnl)),coverage:{valued:valued.length,total:selected.length,pnl:pnlRows.length,nonCash:nonCash.length,cash:knownCash.length,cashTotal:cashRows.length},securityCount:new Set(nonCash.map(r=>r.securityId)).size};
}

const opt=(value,label,selected)=>`<option value="${escapeHTML(value)}" ${value===selected?'selected':''}>${escapeHTML(label)}</option>`;
const empty=message=>`<div class="wm-pa-empty">${escapeHTML(message)}</div>`;
const coverage=v=>`${v.coverage.valued}/${v.coverage.total} position rows valued`;
function sectorChart(v){
  if(!v.rows.length)return empty('No holdings match this view. Clear a filter to continue.');
  if(!v.allocationValid)return empty(v.negative?'Signed exposures present. Net/gross allocation needs an approved definition; positions remain available below.':'Allocation unavailable: choose one currency and provide positive canonical position values.');
  let offset=0;
  const arcs=v.sectors.filter(s=>s.known&&s.value>0).map(s=>{const amount=s.weight*100,start=offset;offset+=amount;return `<circle r="42" cx="60" cy="60" pathLength="100" stroke="${s.color}" stroke-dasharray="${amount} ${100-amount}" stroke-dashoffset="${-start}"/>`;}).join('');
  return `<div class="wm-pa-sector-layout"><svg class="wm-pa-donut" viewBox="0 0 120 120" role="img" aria-label="Sector allocation, ${escapeHTML(coverage(v))}"><g transform="rotate(-90 60 60)">${arcs}</g><text x="60" y="57" class="wm-pa-donut-value">${v.securityCount}</text><text x="60" y="72" class="wm-pa-donut-label">securities</text></svg><div class="wm-pa-legend">${v.sectors.map(s=>`<button type="button" data-sector="${escapeHTML(s.key)}" aria-label="Filter sector: ${escapeHTML(s.label)}"><span class="wm-pa-dot" style="background:${s.color}"></span><span>${escapeHTML(s.label)}</span><b>${s.known?pct(s.weight):'Unknown'}</b></button>`).join('')}</div></div>`;
}
function holdingBars(v){
  if(!v.currencyValid)return empty('Select one currency. No FX values are invented.');
  const rows=v.holdings.filter(h=>h.known);
  if(!rows.length)return empty('No supported position values in this view.');
  const max=Math.max(...rows.map(h=>Math.abs(h.value)),1);
  return `<div class="wm-pa-bars">${rows.slice(0,4).map(h=>`<div class="wm-pa-bar-row"><div class="wm-pa-bar-caption"><strong>${escapeHTML(h.label)}</strong><span>${money(h.value,v.scope.currency,true)} <small>${pct(h.weight)}</small></span></div><div class="wm-pa-track"><span style="width:${Math.abs(h.value)/max*100}%;background:${h.value<0?'var(--wm-pa-red)':'var(--wm-pa-blue)'}"></span></div></div>`).join('')}</div>${rows.length>4?`<details class="wm-pa-more"><summary>All ${rows.length} valued securities</summary>${rows.slice(4).map(h=>`<p><span>${escapeHTML(h.label)}</span><b>${money(h.value,v.scope.currency,true)}</b></p>`).join('')}</details>`:''}`;
}
function pnlBars(v){
  if(!v.currencyValid)return empty('Choose one currency to compare canonical unrealized gains.');
  if(!v.contributions.length)return empty('Unrealized P&L is not supplied for the selected investments. No price-move substitute is used.');
  const rows=v.contributions,max=Math.max(...rows.map(h=>Math.abs(h.pnl)),1);
  return `<div class="wm-pa-bars">${rows.slice(0,4).map(h=>`<div class="wm-pa-bar-row"><div class="wm-pa-bar-caption"><strong>${escapeHTML(h.label)}</strong><span class="${h.pnl<0?'wm-pa-negative':'wm-pa-positive'}">${signed(h.pnl,v.scope.currency)}${h.pnlKnown<h.count?' · partial':''}</span></div><div class="wm-pa-diverge"><span class="wm-pa-zero"></span><span class="wm-pa-pnl-bar ${h.pnl<0?'wm-pa-loss':'wm-pa-gain'}" style="width:${Math.abs(h.pnl)/max*50}%"></span></div></div>`).join('')}</div><p class="wm-pa-foot">${v.coverage.pnl}/${v.coverage.nonCash} investment rows have published P&L. Unrealized, not daily or verified period profit.</p>`;
}

/** Exact design markup. No backend calls; parent owns canonical loading/error state.
 * onSelection receives rows and normalized scope for the SAME table/export selector.
 */
export function createPortfolioAnalytics(root,{rows,snapshot,scope={},onSelection=()=>{}}){
  if(!root || typeof root.addEventListener!=='function')throw new TypeError('A DOM root is required');
  let data=rows,meta=snapshot,filters={account:'',sector:'',query:'',currency:snapshot.currency||'',...scope},notice='';
  const emit=()=>{const v=derivePortfolioView(data,filters,meta);onSelection({rows:v.rows,scope:v.scope,snapshotId:meta.id,view:v});return v;};
  function draw(restoreSearch=false){
    const v=emit(),e=escapeHTML;
    const accounts=[...new Map(data.map(r=>[r.accountId,r.accountName||r.accountId])).entries()];
    root.classList.add('wm-pa');
    const warning=meta.status==='fresh'?'':`<span class="wm-pa-warning">${e(meta.status||'Unknown freshness')}${meta.reason?' · '+e(meta.reason):''}</span>`;
    root.innerHTML=`<section aria-label="Portfolio overview and filters"><header class="wm-pa-heading"><div><span class="wm-pa-eyebrow">YOUR BOOK · ONE SELECTED VIEW</span><h2>Portfolio at a glance</h2></div><span class="wm-pa-clock">${e(meta.session||'Session unknown')} · ${meta.observedAt?e(meta.observedAt):'Source time unknown'}</span></header><div class="wm-pa-filterbar"><label>Account<select data-filter="account">${opt('','All accounts',filters.account)}${accounts.map(([id,label])=>opt(id,label,filters.account)).join('')}</select></label><label>Sector<select data-filter="sector">${opt('','All sectors',filters.sector)}${v.sectorOptions.map(s=>opt(s,s,filters.sector)).join('')}</select></label>${v.currencies.length>1?`<label>Currency<select data-filter="currency">${opt('','Choose currency',filters.currency)}${v.currencies.map(c=>opt(c,c,filters.currency)).join('')}</select></label>`:''}<label class="wm-pa-search">Find a holding<input data-filter="query" type="search" value="${e(filters.query)}" placeholder="Symbol, name or account" autocomplete="off"/></label><button type="button" data-clear>Reset filters</button></div><div class="wm-pa-status" aria-live="polite">${v.rows.length} matching rows · ${v.securityCount} investment securities · ${e(coverage(v))}${warning}${notice?' · '+e(notice):''}</div><div class="wm-pa-kpis"><article><span>Selected position value${v.coverage.valued<v.coverage.total?' · partial':''}</span><strong>${v.currencyValid?money(v.total,v.scope.currency):'Unknown'}</strong><small>Published row values · includes selected cash</small></article><article><span>Unrealized gain / loss${v.coverage.pnl<v.coverage.nonCash?' · partial':''}</span><strong class="${v.pnl<0?'wm-pa-negative':v.pnl>0?'wm-pa-positive':''}">${v.currencyValid?money(v.pnl,v.scope.currency):'Unknown'}</strong><small>${v.coverage.pnl}/${v.coverage.nonCash} investment rows · not period profit</small></article><article><span>Cash in selected view${v.coverage.cash<v.coverage.cashTotal?' · partial':''}</span><strong>${v.currencyValid?money(v.cash,v.scope.currency):'Unknown'}</strong><small>${v.scope.sector&&v.scope.sector!=='Cash & sweep'?'Excluded by sector filter':'Cash & sweep only · not account equity'}</small></article><article><span>Largest valued exposure</span><strong>${e(v.holdings.find(h=>h.known)?.label||'Unknown')}</strong><small>${v.allocationValid&&v.holdings.find(h=>h.known)?pct(v.holdings.find(h=>h.known).weight)+' of known selected value':'Weight unavailable'}</small></article></div><div class="wm-pa-chartgrid"><article class="wm-pa-panel"><div class="wm-pa-panelhead"><h3>Sector allocation</h3><span>Click to filter</span></div>${sectorChart(v)}<p class="wm-pa-foot">Direct instrument classification. Funds are not constituent look-through. ${v.coverage.valued<v.coverage.total?'Percentages use known values only.':''}</p></article><article class="wm-pa-panel"><div class="wm-pa-panelhead"><h3>Largest holdings</h3><span>Selected value</span></div>${holdingBars(v)}</article><article class="wm-pa-panel"><div class="wm-pa-panelhead"><h3>Unrealized contributors</h3><span>Gain / loss</span></div>${pnlBars(v)}</article></div><p class="wm-pa-context">Charts, holding rows and export share these filters. Changing sector rebases weights to the selected slice. Account equity and historical returns are separate measures.</p></section>`;
    if(restoreSearch){const input=root.querySelector('[data-filter="query"]');input.focus();const end=input.value.length;input.setSelectionRange(end,end);}
  }
  function change(event){
    const target=event.target;if(!target?.matches('[data-filter]'))return;
    const key=target.dataset.filter;filters={...filters,[key]:target.value};notice='';
    if(key==='account'||key==='currency'){
      const available=derivePortfolioView(data,{...filters,sector:''},meta).sectorOptions;
      if(filters.sector&&!available.includes(filters.sector)){filters.sector='';notice='Sector reset because it is not present in this account/currency.';}
    }
    draw(key==='query');
  }
  function input(event){if(event.target?.dataset.filter==='query')change(event);}
  function click(event){const sector=event.target.closest('[data-sector]');if(sector&&root.contains(sector)){filters={...filters,sector:sector.dataset.sector};notice='';draw();}else if(event.target.closest('[data-clear]')){filters={account:'',sector:'',query:'',currency:meta.currency||''};notice='Filters cleared.';draw();}}
  root.addEventListener('change',change);root.addEventListener('input',input);root.addEventListener('click',click);draw();
  return {getView:()=>derivePortfolioView(data,filters,meta),setScope(next){filters={...filters,...next};notice='';draw();},setData(nextRows,nextSnapshot){validateRows(nextRows,nextSnapshot.id);data=nextRows;meta=nextSnapshot;notice='';draw();},destroy(){root.removeEventListener('change',change);root.removeEventListener('input',input);root.removeEventListener('click',click);root.replaceChildren();}};
}
