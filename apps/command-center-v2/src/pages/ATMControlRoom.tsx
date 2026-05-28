// ATMControlRoom.tsx.REPLACEMENT_V1_8
// Designed by ChatGPT Chief Architect.
// Fix: distinguish actionable broker/journal-confirmed open trades from ATM DB open records.
// Target: apps/command-center-v2/src/pages/ATMControlRoom.tsx


import React, { useEffect, useMemo, useState } from 'react';
import ReconciliationHealthPanel from '../components/ReconciliationHealthPanel';
import ProposalHygienePanel from '../components/ProposalHygienePanel';
import LifecycleTracePanel from '../components/LifecycleTracePanel';
import StopProofPanel from '../components/StopProofPanel';
import ExecutionTimingPanel from '../components/ExecutionTimingPanel';
import StopTrailingControlPanel from '../components/StopTrailingControlPanel';
import JournalLearningWorkspace from '../components/JournalLearningWorkspace';
import LLMBacktestingReviewPanel from '../components/LLMBacktestingReviewPanel';
import UnifiedTradeInspector from '../components/UnifiedTradeInspector';
import StopChangeAuditPanel from '../components/StopChangeAuditPanel';
import ProposalDedupPanel from '../components/ProposalDedupPanel';


type R = Record<string, any>;
type Tone = 'healthy' | 'warning' | 'danger' | 'neutral';
type Tab = 'overview' | 'records' | 'lifecycle' | 'risk' | 'actions' | 'raw';


type Inspector = {
  open: boolean;
  title: string;
  subtitle?: string;
  tone?: Tone;
  source?: string;
  description?: string;
  records?: R[];
  selected?: R | null;
  lifecycle?: R[];
  risks?: R[];
  safeActions?: string[];
  blockedActions?: string[];
  raw?: any;
  tab?: Tab;
};


const emptyInspector: Inspector = { open: false, title: '', tab: 'overview', records: [], lifecycle: [], risks: [], safeActions: [], blockedActions: [] };


const API = {
  lifecycle: '/api/v2/atm/lifecycle',
  overdue: '/api/v2/atm/overdue-decisions',
  manualClose: '/api/v2/atm/manual-close-review',
  reconciliation: '/api/v2/atm/close-reconciliation',
  closePreview: '/api/v2/atm/close-preview',
  journalCandidates: [
    '/api/v2/trade-journal',
    '/api/v2/journal/automated',
    '/api/v2/automated-journal',
    '/api/v2/paper-trades/journal',
  ],
};


async function getJson(url: string) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}
async function firstOk(urls: string[]) {
  const errors: string[] = [];
  for (const u of urls) {
    try { return { url: u, data: await getJson(u) }; }
    catch (e: any) { errors.push(`${u}: ${e.message || e}`); }
  }
  return { url: 'unavailable', data: null, errors };
}
function arr(...xs: any[]): R[] { for (const x of xs) if (Array.isArray(x)) return x; return []; }
function num(v: any) { const x = Number(v); return Number.isFinite(x) ? x : null; }
function money(v: any) { const x = num(v); return x === null ? '—' : `$${x.toFixed(2)}`; }
function fmt(v: any) { if (v === null || v === undefined || v === '') return '—'; if (typeof v === 'object') return JSON.stringify(v); return String(v); }
function tone(v: any): Tone { const s = String(v ?? '').toLowerCase(); if (s.includes('missing') || s.includes('overdue') || s.includes('fail') || s.includes('disabled') || s.includes('mismatch')) return 'danger'; if (s.includes('unknown') || s.includes('pending') || s.includes('stale') || s.includes('warn')) return 'warning'; if (s.includes('ok') || s.includes('pass') || s.includes('healthy') || s.includes('reviewed') || s.includes('open')) return 'healthy'; return 'neutral'; }
function sym(r: R) { return String(r.symbol || r.ticker || '').toUpperCase(); }
function normStrategy(s: any) { return String(s || '').replace(/\s+/g, '_').toLowerCase(); }
function positionKey(r: R) { return `${sym(r)}|${normStrategy(r.strategy_id || r.strategy)}|${num(r.entry_price ?? r.entry) ?? ''}|${num(r.shares ?? r.qty ?? r.quantity) ?? ''}`; }
function lower(v: any) { return String(v ?? '').toLowerCase(); }
function label(k: string) { return k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()); }
function keyOf(r: R) { return [r.paper_trade_id, r.trade_id, r.id, r.symbol, r.strategy_id || r.strategy].filter(Boolean).join('|').toUpperCase(); }


function normalizeJournalOpen(raw: any): R[] {
  const rows = arr(raw?.open_trades, raw?.open_positions, raw?.openPositions, raw?.open, raw?.alpaca_paper?.open_positions, raw?.journal?.open_positions, raw?.data?.open_positions, raw?.data?.open_trades, raw?.positions);
  return rows.map((r) => ({
    ...r,
    symbol: sym(r),
    strategy_id: r.strategy_id || r.strategy || r.strategy_name,
    strategy_family: r.strategy_family || r.family,
    paper_trade_id: r.paper_trade_id || r.trade_id || r.id,
    account: r.account || r.broker || 'ALPACA_PAPER',
    entry_price: r.entry_price ?? r.entry,
    current_price: r.current_price ?? r.now ?? r.mark_price,
    shares: r.shares ?? r.qty ?? r.quantity,
    db_stop: r.db_stop ?? r.stop_loss ?? r.stop,
    target: r.target_price ?? r.target,
    unrealized_pnl: r.unrealized_pnl ?? r.pnl,
    r_multiple: r.r_multiple ?? r.r,
    source_confirmed_open: true,
    actionability: 'actionable_open_trade',
    actionability_reason: 'Present in Trade Journal / broker-confirmed open positions source.',
  })).filter((r) => sym(r));
}
function normalizeAtmOpen(raw: any): R[] {
  const rows = arr(raw?.open_positions, raw?.open_position_records, raw?.positions, raw?.lifecycle_items);
  return rows.map((r) => ({
    ...r,
    symbol: sym(r),
    strategy_id: r.strategy_id || r.strategy,
    paper_trade_id: r.paper_trade_id || r.trade_id || r.id,
    entry_price: r.entry_price ?? r.entry,
    shares: r.shares ?? r.qty ?? r.quantity,
    db_stop: r.db_stop ?? r.stop_loss ?? r.stop,
    actionability: 'atm_db_open_record',
  })).filter((r) => sym(r));
}
function isClosedLike(r: R) {
  const text = lower([r.status, r.exit_reason, r.reason, r.verdict, r.actionability_reason, r.lifecycle_status].join(' '));
  return text.includes('closed') || text.includes('stop_hit') || text.includes('stop hit') || text.includes('target_hit') || text.includes('target hit') || text.includes('manual stale close') || text.includes('broker close') || text.includes('cancel') || text.includes('orphan') || text.includes('duplicate');
}
function reconcilePositions(journalOpen: R[], atmOpen: R[]) {
  const journalKeys = new Set(journalOpen.map(positionKey));
  const journalSymbols = new Set(journalOpen.map(sym));
  const dbRecords = atmOpen.map((r) => {
    const exact = journalKeys.has(positionKey(r));
    const symbolOnly = journalSymbols.has(sym(r));
    const closed = isClosedLike(r);
    let classification = 'unmatched_db_record';
    let reason = 'ATM DB open record is not present in broker/journal-confirmed open positions.';
    if (exact) { classification = 'confirmed_actionable'; reason = 'Matches actionable open trade by symbol/strategy/entry/shares.'; }
    else if (closed) { classification = 'closed_or_ghost_record'; reason = 'Record looks closed, stopped, target-hit, canceled, duplicate, or orphaned.'; }
    else if (symbolOnly) { classification = 'symbol_match_only'; reason = 'Same symbol exists in actionable trades, but strategy/entry/shares do not match exactly.'; }
    return { ...r, reconciliation_classification: classification, reconciliation_reason: reason, actionable: exact };
  });
  return { actionable: journalOpen, dbRecords, gaps: dbRecords.filter((r) => !r.actionable) };
}


function Badge({ children, t = 'neutral' }: { children: React.ReactNode; t?: Tone }) { return <span className={`atm-badge atm-${t}`}>{children}</span>; }
function Card({ label, value, t, onClick }: { label: string; value: any; t?: Tone; onClick: () => void }) { return <button className={`atm-cardMetric atm-${t || 'neutral'}`} onClick={onClick}><strong>{value ?? '—'}</strong><span>{label} ↗</span></button>; }
function Table({ rows, cols, onRow }: { rows: R[]; cols: Array<{ k: string; h: string; r?: (row: R) => React.ReactNode }>; onRow?: (r: R) => void }) { return <div className="atm-tableWrap"><table className="atm-table"><thead><tr>{cols.map((c) => <th key={c.k}>{c.h}</th>)}</tr></thead><tbody>{rows.length === 0 && <tr><td className="empty" colSpan={cols.length}>No records.</td></tr>}{rows.map((row, i) => <tr key={keyOf(row) || i} className={onRow ? 'clickable' : ''} onClick={() => onRow?.(row)}>{cols.map((c) => <td key={c.k}>{c.r ? c.r(row) : fmt(row[c.k])}</td>)}</tr>)}</tbody></table></div>; }
function GateChips({ row, onGate }: { row: R; onGate: (g: R) => void }) { const source = row.gates || row.gate_summary || row.gate_audit || {}; const gates = Array.isArray(source) ? source : (typeof source === 'object' && source ? Object.entries(source).map(([k, v]: any) => ({ name: label(k), status: typeof v === 'object' ? (v.status || v.result || 'unknown') : (v ? 'pass' : 'fail'), reason: typeof v === 'object' ? (v.reason || v.message) : '' })) : []); const fallback = ['Strategy', 'Classifier', 'Max Conc.', 'Stop', 'Premarket'].map((name) => ({ name, status: 'unknown', reason: 'Gate detail not supplied by API.' })); return <div className="gateGrid">{(gates.length ? gates : fallback).map((g) => <button key={g.name} className={`gate gate-${tone(g.status)}`} onClick={(e) => { e.stopPropagation(); onGate(g); }}><span>{g.name}</span><b>{String(g.status).toUpperCase()}</b></button>)}</div>; }
function RecordTable({ records, onPick }: { records: R[]; onPick?: (r: R) => void }) { const keys = Array.from(new Set(records.flatMap((r) => Object.keys(r)))).slice(0, 10); return <Table rows={records} cols={keys.map((k) => ({ k, h: label(k) }))} onRow={onPick} />; }
function RecordCard({ r }: { r: R }) { return <div className="recordGrid">{Object.entries(r).slice(0, 28).map(([k, v]) => <div key={k}><b>{label(k)}</b><span>{fmt(v)}</span></div>)}</div>; }
function InspectorPanel({ s, set }: { s: Inspector; set: (x: Inspector) => void }) { if (!s.open) return null; const tab = s.tab || 'overview'; const tabs: Tab[] = ['overview', 'records', 'lifecycle', 'risk', 'actions', 'raw']; return <aside className="inspector"><header><div><p className="crumb">ATM Control Room → Drill Down</p><h2>{s.title}</h2><p>{s.subtitle}</p></div><button onClick={() => set(emptyInspector)}>×</button></header><div className="meta"><Badge t={s.tone || 'neutral'}>{s.tone || 'neutral'}</Badge><span>{s.source || 'source unavailable'}</span><span>{(s.records || []).length} records</span></div><nav>{tabs.map((t) => <button key={t} className={tab === t ? 'active' : ''} onClick={() => set({ ...s, tab: t })}>{t === 'risk' ? 'Risk / Gates' : label(t)}</button>)}</nav><main>{tab === 'overview' && <><h3>What this means</h3><p>{s.description || 'No explanation supplied.'}</p>{s.selected && <RecordCard r={s.selected} />}</>}{tab === 'records' && <RecordTable records={s.records || []} onPick={(r) => set({ ...s, selected: r, tab: 'overview' })} />}{tab === 'lifecycle' && <RecordTable records={s.lifecycle || []} />}{tab === 'risk' && <RecordTable records={s.risks || []} />}{tab === 'actions' && <div className="two"><div><h3>Safe Actions</h3>{(s.safeActions || []).map((x) => <p className="safe" key={x}>{x}</p>)}</div><div><h3>Blocked Actions</h3>{(s.blockedActions || []).map((x) => <p className="blocked" key={x}>{x}</p>)}</div></div>}{tab === 'raw' && <pre>{JSON.stringify(s.raw ?? s.records, null, 2)}</pre>}</main></aside>; }


export default function ATMControlRoom() {
  const [life, setLife] = useState<R>({}); const [journal, setJournal] = useState<R | null>(null); const [journalSource, setJournalSource] = useState('unavailable'); const [overdue, setOverdue] = useState<R>({}); const [manual, setManual] = useState<R>({}); const [recon, setRecon] = useState<R>({}); const [loading, setLoading] = useState(false); const [err, setErr] = useState<string | null>(null); const [inspector, setInspector] = useState<Inspector>(emptyInspector);
  const [lifecycleQuery, setLifecycleQuery] = useState<{symbol?: string; paperTradeId?: number} | null>(null);
  function unwrap(v: any) { return v?.data || v || {}; }
  async function refresh() { setLoading(true); setErr(null); try { const [l, j, o, m, c] = await Promise.allSettled([getJson(API.lifecycle), firstOk(API.journalCandidates), getJson(API.overdue), getJson(API.manualClose), getJson(API.reconciliation)]); if (l.status === 'fulfilled') setLife(unwrap(l.value)); else throw l.reason; if (j.status === 'fulfilled') { const jd = j.value.data; setJournal(jd?.data || jd); setJournalSource(j.value.url); } if (o.status === 'fulfilled') setOverdue(unwrap(o.value)); if (m.status === 'fulfilled') setManual(unwrap(m.value)); if (c.status === 'fulfilled') setRecon(unwrap(c.value)); } catch (e: any) { setErr(e.message || String(e)); } finally { setLoading(false); } }
  useEffect(() => { refresh(); }, []);
  const summary = life.summary || {}; const journalOpen = normalizeJournalOpen(journal); const atmOpen = normalizeAtmOpen(life); const { actionable, dbRecords, gaps } = useMemo(() => reconcilePositions(journalOpen, atmOpen), [JSON.stringify(journalOpen), JSON.stringify(atmOpen)]); const events = arr(life.lifecycle_event_records, life.lifecycle_events, life.events_24h); const proposals = arr(life.proposals, life.proposal_records, life.recent_proposals); const staleProposals = arr(life.stale_proposal_records, proposals.filter((p: R) => p.stale_reason || p.classification || Number(p.age_hours) > 48)); const overdueRows = arr(overdue.all_overdue, overdue.reviewed, life.time_stop_overdue_records, dbRecords.filter((p: R) => String(p.time_stop_status || '').includes('overdue'))); const closeRows = arr(recon.items, recon.close_reconciliation_records, life.close_reconciliation_records);
  function eventsFor(records: R[]) { const keys = new Set(records.flatMap((r) => [r.lifecycle_id, r.paper_trade_id, r.proposal_id, sym(r)].filter(Boolean).map(String))); return events.filter((e: R) => [e.lifecycle_id, e.paper_trade_id, e.proposal_id, sym(e)].some((v) => keys.has(String(v)))); }
  function risksFor(records: R[]) { return records.flatMap((r) => [r.risk_summary, r.stop_summary, r.time_stop_summary, r.gate_summary, r.broker_stop_proof, r.reconciliation_reason].filter(Boolean).map((x: any) => typeof x === 'object' ? x : { detail: x })); }
  function open(title: string, records: R[], description: string, t?: Tone, source = 'computed') { setInspector({ open: true, title, subtitle: `${records.length} records`, tone: t || tone(title), source, description, records, lifecycle: eventsFor(records), risks: risksFor(records), safeActions: safeActions(title), blockedActions: blockedActions(title), raw: { summary, records }, tab: 'records' }); }
  function openRow(title: string, row: R, records = [row]) { setInspector({ open: true, title, subtitle: row.symbol || row.paper_trade_id || row.proposal_id, tone: tone(row.reconciliation_classification || row.status || row.time_stop_status), source: row.source || 'row', description: row.actionability_reason || row.reconciliation_reason || 'Selected row drill-down.', records, selected: row, lifecycle: eventsFor([row]), risks: risksFor([row]), safeActions: safeActions(title), blockedActions: blockedActions(title), raw: row, tab: 'overview' }); }
  async function preview(row: R) { const id = row.paper_trade_id || row.trade_id || row.id; const raw = await getJson(`${API.closePreview}?paper_trade_id=${encodeURIComponent(String(id))}`); const p = raw?.data || raw || {}; setInspector({ open: true, title: `${row.symbol || p.symbol} Paper Close Preview`, subtitle: `Paper trade #${id}`, tone: p.can_submit_paper_close ? 'warning' : 'danger', source: API.closePreview, description: 'Paper-only close preview. No order is placed by opening this preview.', records: [p], selected: p, lifecycle: eventsFor([row]), risks: arr(p.safety_gates, p.gates), safeActions: ['Review close estimate', 'Confirm paper-only safeguards', 'Return to reconciliation workflow'], blockedActions: ['Live close', 'Automatic close', 'Stop cancellation without explicit workflow'], raw: p, tab: 'overview' }); }
  return <div className="atm"><style>{css}</style><header className="head"><div><h1>ATM Control Room</h1><p>Actionable trades are broker/journal-confirmed. DB records are separated for audit and reconciliation.</p></div><button onClick={refresh}>Refresh</button></header>{loading && <div className="banner">Loading…</div>}{err && <div className="banner danger">{err}</div>}
    <section className="metrics"><Card label="Signals Today" value={summary.signals_today ?? 0} onClick={() => open('Signals Today', arr(life.signals, life.signals_today_records), 'Signals generated today.')} /><Card label="Proposals" value={summary.proposals_today ?? proposals.length} onClick={() => open('Proposals', proposals, 'Proposal records and statuses.')} /><Card label="Actionable Open Trades" value={actionable.length} t="healthy" onClick={() => open('Actionable Open Trades', actionable, 'Broker/journal-confirmed open trades. This is the active trade-action set.', 'healthy', journalSource)} /><Card label="ATM DB Open Records" value={dbRecords.length} t="warning" onClick={() => open('ATM DB Open Records', dbRecords, 'ATM lifecycle/DB rows that appear open. These are audit records until matched to broker/journal open trades.', 'warning', API.lifecycle)} /><Card label="Reconciliation Gaps" value={gaps.length} t={gaps.length ? 'danger' : 'healthy'} onClick={() => open('Position Reconciliation Gaps', gaps, 'ATM DB records that do not match the actionable broker/journal open trade set. These are data-quality items, not trade actions.', gaps.length ? 'danger' : 'healthy')} /><Card label="Time-Stop Overdue" value={summary.time_stop_overdue ?? overdueRows.length} t={(summary.time_stop_overdue ?? overdueRows.length) ? 'danger' : 'healthy'} onClick={() => open('Time-Stop Overdue', overdueRows, 'Positions past strategy time-stop window.')} /><Card label="Missing Stops" value={summary.stop_missing_count ?? 0} t={(summary.stop_missing_count ?? 0) ? 'danger' : 'healthy'} onClick={() => open('Missing Stops', arr(life.missing_stop_records), 'Missing DB or broker stop proof records.')} /><Card label="Stale Proposals" value={summary.stale_proposals ?? staleProposals.length} t={(summary.stale_proposals ?? staleProposals.length) ? 'warning' : 'healthy'} onClick={() => open('Stale Proposals', staleProposals, 'Stale proposal records with classification and reason kept.')} /><Card label="Classifier Gate" value={summary.classifier_gate_disabled ? 'OFF' : 'ON'} t={summary.classifier_gate_disabled ? 'danger' : 'healthy'} onClick={() => open('Classifier Gate', [summary], 'Classifier burn-in / graduation gate state.')} /><Card label="Events 24h" value={summary.lifecycle_events_24h ?? events.length} onClick={() => open('Lifecycle Events 24h', events, 'Lifecycle events in the last 24 hours.')} /></section>
    <ReconciliationHealthPanel />
    <section className="notice"><h2>Position Source Reconciliation</h2><p>Trade Journal open positions and ATM DB open records do not always mean the same thing. Active trade actions use <b>Actionable Open Trades</b>. ATM DB mismatches are shown as reconciliation gaps.</p><div className="triple"><div><b>{actionable.length}</b><span>Actionable broker/journal-confirmed trades</span></div><div><b>{dbRecords.length}</b><span>ATM DB open records</span></div><div><b>{gaps.length}</b><span>Reconciliation gaps</span></div></div></section>
    <section className="panel"><h2>Actionable Open Trades ({actionable.length})</h2><p>These are the only rows treated as currently actionable for trade review and close-preview workflow.</p><Table rows={actionable} cols={[{k:'symbol',h:'Symbol'},{k:'strategy_id',h:'Strategy'},{k:'shares',h:'Shares'},{k:'entry_price',h:'Entry',r:(x)=>money(x.entry_price)},{k:'current_price',h:'Current',r:(x)=>money(x.current_price)},{k:'unrealized_pnl',h:'P&L',r:(x)=>money(x.unrealized_pnl)},{k:'r_multiple',h:'R'},{k:'db_stop',h:'Stop',r:(x)=>money(x.db_stop)},{k:'target',h:'Target',r:(x)=>money(x.target)},{k:'action',h:'Action',r:(x)=><button onClick={(e)=>{e.stopPropagation(); openRow(`${x.symbol} actionable trade`, x, actionable);}}>Drill Down</button>}]} onRow={(r)=>openRow(`${r.symbol} actionable trade`, r, actionable)} /></section>
    <section className="panel danger"><h2>Position Reconciliation Gaps ({gaps.length})</h2><p>These records explain why ATM DB open records do not add up to actionable open trades.</p><Table rows={gaps} cols={[{k:'symbol',h:'Symbol'},{k:'paper_trade_id',h:'#'},{k:'strategy_id',h:'Strategy'},{k:'entry_price',h:'Entry',r:(x)=>money(x.entry_price)},{k:'shares',h:'Shares'},{k:'reconciliation_classification',h:'Classification',r:(x)=><Badge t={tone(x.reconciliation_classification)}>{x.reconciliation_classification}</Badge>},{k:'reconciliation_reason',h:'Reason'}]} onRow={(r)=>openRow(`${r.symbol} reconciliation gap`, r, gaps)} /></section>
    <section className="panel"><h2>Close Reconciliation</h2><p>External-close decisions are tracked here. Preview is available only for rows with a valid paper_trade_id.</p><Table rows={closeRows} cols={[{k:'symbol',h:'Symbol'},{k:'paper_trade_id',h:'#'},{k:'strategy_id',h:'Strategy'},{k:'status',h:'Status',r:(x)=><Badge t={tone(x.reconciliation_state || x.status)}>{x.reconciliation_state || x.status || 'unknown'}</Badge>},{k:'action',h:'Actions',r:(x)=><div className="rowActions"><button onClick={(e)=>{e.stopPropagation(); openRow(`${x.symbol} close reconciliation`, x, closeRows);}}>View</button><button onClick={(e)=>{e.stopPropagation(); preview(x);}}>Close Preview</button></div>}]} onRow={(r)=>openRow(`${r.symbol} close reconciliation`, r, closeRows)} /></section>
    <section className="panel"><h2>ATM DB Open Records ({dbRecords.length})</h2><p>Audit-only database lifecycle view. Do not treat every row here as an actionable broker-open position.</p><Table rows={dbRecords} cols={[{k:'symbol',h:'Symbol'},{k:'paper_trade_id',h:'#'},{k:'strategy_id',h:'Strategy'},{k:'strategy_family',h:'Family'},{k:'days_held',h:'Days'},{k:'entry_price',h:'Entry',r:(x)=>money(x.entry_price)},{k:'db_stop',h:'DB Stop',r:(x)=>money(x.db_stop)},{k:'time_stop_status',h:'Time-Stop',r:(x)=><Badge t={tone(x.time_stop_status)}>{x.time_stop_status || 'unknown'}</Badge>},{k:'gates',h:'Gates',r:(x)=><GateChips row={x} onGate={(g)=>openRow(`Gate: ${g.name}`, g)} />},{k:'account',h:'Account'}]} onRow={(r)=>openRow(`${r.symbol} DB open record`, r, dbRecords)} /></section>
    <ProposalHygienePanel fallbackRecords={proposals} onOpenProposal={(proposal: any, all: any) => openRow(`${proposal.symbol || proposal.proposal_id} proposal hygiene`, proposal, all)} />
    <StopTrailingControlPanel />
    <StopChangeAuditPanel />
    <StopProofPanel />
    <ExecutionTimingPanel />
    <JournalLearningWorkspace compact />
    <LLMBacktestingReviewPanel compact />
    <LifecycleTracePanel />
    <ProposalDedupPanel />
    <InspectorPanel s={inspector} set={setInspector} />
    {lifecycleQuery && <UnifiedTradeInspector symbol={lifecycleQuery.symbol} paperTradeId={lifecycleQuery.paperTradeId} onClose={() => setLifecycleQuery(null)} />}
    </div>;
}
function safeActions(title: string) { const out = ['Open records', 'Inspect raw data']; if (title.toLowerCase().includes('actionable')) out.push('Review stop', 'Prepare paper close preview', 'Open journal'); if (title.toLowerCase().includes('gap')) out.push('Review reconciliation reason', 'Fix DB state after confirmation'); return out; }
function blockedActions(title: string) { return ['Live order placement', 'Automatic close', 'Automatic stop cancellation/replacement', 'Changing ATM mode']; }
const css = `.atm{padding:28px 32px;background:#070b12;color:#e8eef8;min-height:100vh;font-family:Inter,system-ui}.head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid #263244;padding-bottom:18px}.head h1{font-size:32px;margin:0}.head p,.panel p,.notice p{color:#9fb0c4}.head button,.rowActions button,.panel button,.inspector button{background:#162033;color:#dbeafe;border:1px solid #334155;border-radius:8px;padding:8px 12px;cursor:pointer}.banner{margin:12px 0;padding:12px;border:1px solid #3b82f6;border-radius:10px;background:#0b2447}.banner.danger{border-color:#ef4444;background:#2b1115}.metrics{display:grid;grid-template-columns:repeat(10,minmax(120px,1fr));gap:10px;margin:22px 0}.atm-cardMetric{background:#0d1320;border:1px solid #263244;border-radius:15px;color:#dbeafe;text-align:left;padding:14px;min-height:92px}.atm-cardMetric:hover,.clickable:hover{border-color:#60a5fa;background:#101a2b}.atm-cardMetric strong{display:block;font-size:30px}.atm-cardMetric span{color:#9fb0c4;font-size:12px}.atm-danger strong{color:#fb7185}.atm-warning strong{color:#fbbf24}.atm-healthy strong{color:#4ade80}.notice,.panel{border:1px solid #263244;border-radius:18px;background:#0b1019;margin:18px 0;padding:18px}.panel.danger{border-color:#7f1d1d}.triple{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.triple div{border:1px solid #263244;border-radius:14px;padding:14px;background:#0d1320}.triple b{display:block;font-size:28px}.triple span{color:#9fb0c4}.atm-tableWrap{overflow:auto}.atm-table{width:100%;border-collapse:collapse;font-size:13px}.atm-table th{text-align:left;color:#9fb0c4;border-bottom:1px solid #263244;padding:9px}.atm-table td{border-bottom:1px solid #1f2937;padding:9px;vertical-align:top}.empty{text-align:center;color:#94a3b8}.atm-badge{display:inline-flex;border-radius:999px;padding:3px 8px;font-size:11px;text-transform:uppercase;border:1px solid #334155}.atm-badge.atm-healthy{color:#4ade80;border-color:#166534}.atm-badge.atm-warning{color:#fbbf24;border-color:#92400e}.atm-badge.atm-danger{color:#fb7185;border-color:#7f1d1d}.gateGrid{display:flex;flex-wrap:wrap;gap:4px}.gate{border:1px solid #92400e;background:#111827;color:#dbeafe;border-radius:8px;padding:4px 7px;font-size:10px}.gate b{display:block}.rowActions{display:flex;gap:6px}.inspector{position:fixed;top:0;right:0;height:100vh;width:min(940px,54vw);background:#0b1020;border-left:1px solid #334155;box-shadow:-20px 0 60px rgba(0,0,0,.5);z-index:50;display:flex;flex-direction:column}.inspector header{display:flex;justify-content:space-between;gap:20px;padding:22px;border-bottom:1px solid #263244}.inspector header h2{margin:4px 0;font-size:28px}.crumb{color:#60a5fa;margin:0}.meta{display:flex;gap:10px;align-items:center;padding:10px 22px;border-bottom:1px solid #263244;color:#9fb0c4}.inspector nav{display:flex;gap:8px;padding:14px 22px;border-bottom:1px solid #263244}.inspector nav button.active{background:#2563eb;border-color:#60a5fa}.inspector main{padding:18px 22px;overflow:auto}.recordGrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.recordGrid div{background:#0d1320;border:1px solid #263244;border-radius:10px;padding:10px}.recordGrid b{display:block;color:#9fb0c4;font-size:11px}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.safe{color:#4ade80}.blocked{color:#fb7185}pre{white-space:pre-wrap;background:#020617;border:1px solid #263244;border-radius:14px;padding:14px}@media(max-width:1300px){.metrics{grid-template-columns:repeat(2,1fr)}.inspector{width:96vw}}`;