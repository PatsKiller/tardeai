import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'

type SourceKind = 'PROPOSAL' | 'WATCHLIST' | 'DRAFT'
type SetupState = 'READY' | 'GENERATED' | 'BROKER_OBSERVED'
type DeskFilter = 'ALL' | SourceKind | SetupState

type LocalState = Record<string, { account?: string; qty?: number; generated?: boolean }>

type SetupRow = {
  id: string
  source: SourceKind
  raw: any
  symbol: string
  account: string
  qty: number
  side: string
  entryType: string
  entryPrice: number | null
  stop: number | null
  trail: any | null
  targets: any[]
  tif: string
  session: string
  score?: number | string | null
  decision?: string | null
  reason?: string | null
  sector?: string | null
  sourceLabel?: string | null
}

const LS_KEY = 'tradeai.manualTosDesk.v1'
const ACCOUNTS = ['ANY', 'schwab_taxable', 'schwab_rollover_ira', 'schwab_roth_ira']
const C = { blue: '#60a5fa', green: '#22c55e', amber: '#f59e0b', red: '#ef4444', purple: '#a78bfa', dim: 'var(--text3)' }
const mono = { fontFamily: 'JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace' as const }
const btn = (bg: string, fg = '#fff') => ({ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 5, border: 'none', background: bg, color: fg, cursor: 'pointer' as const })

function num(v: any): number | null { const x = Number(v); return Number.isFinite(x) && x > 0 ? x : null }
function first(...vals: any[]) { return vals.find(v => v !== undefined && v !== null && v !== '') }
function acct(a: string) { return !a || a === 'ANY' ? 'ANY SCHWAB' : a.replace('schwab_', '').replace(/_/g, ' ').toUpperCase() }
function baseQty(x: any) { return Number(first(x.qty, x.shares, x.quantity?.qty, x.recommended_qty, x.position_size_shares, 10)) || 10 }

function fromProposal(p: any, local: LocalState): SetupRow | null {
  const symbol = String(first(p.symbol, p.ticker, p.instrument?.symbol, '')).toUpperCase()
  if (!symbol) return null
  const id = String(first(p.proposal_id, p.id, `proposal-${symbol}-${p.created_at ?? ''}`))
  const entry = num(first(p.entry_price, p.limit_price, p.suggested_entry, p.price, p.current_price))
  const stop = num(first(p.stop_price, p.stop_loss, p.initial_stop))
  const target = num(first(p.target_price, p.take_profit, p.target1, p.target))
  return {
    id, source: 'PROPOSAL', raw: p, symbol,
    account: local[id]?.account ?? 'ANY', qty: local[id]?.qty ?? baseQty(p),
    side: String(first(p.direction, p.side, 'BUY')).toUpperCase().includes('SHORT') ? 'SELL SHORT' : 'BUY',
    entryType: String(first(p.entry_type, p.order_type, 'LIMIT')).toUpperCase(), entryPrice: entry,
    stop, trail: null, targets: target ? [{ price: target, qty_pct: 100 }] : [], tif: 'DAY', session: 'NORMAL',
    score: first(p.score, p.final_score, p.rating_score), decision: first(p.decision, p.status),
    reason: first(p.thesis, p.catalyst, p.reason, p.strategy_name, 'Paper proposal promoted to manual ToS setup'),
    sector: p.sector ?? null, sourceLabel: 'paper proposal'
  }
}

function fromWatch(x: any, local: LocalState): SetupRow | null {
  const symbol = String(first(x.symbol, x.ticker, '')).toUpperCase()
  if (!symbol) return null
  const id = `watch-${symbol}-${first(x.source, 'tradeai')}`
  const price = num(first(x.price, x.last, x.current_price))
  return {
    id, source: 'WATCHLIST', raw: x, symbol,
    account: local[id]?.account ?? 'ANY', qty: local[id]?.qty ?? 10,
    side: 'BUY', entryType: 'LIMIT', entryPrice: price,
    stop: null, trail: null, targets: [], tif: 'DAY', session: 'NORMAL',
    score: x.score ?? null, decision: x.decision ?? null,
    reason: first(x.catalyst, x.reason, x.sector, 'Trade AI scanner/watchlist candidate'),
    sector: x.sector ?? null, sourceLabel: x.source ?? null
  }
}

function fromDraft(d: any, local: LocalState): SetupRow | null {
  const it = d.intent_json ?? d.intent ?? d
  const symbol = String(first(d.symbol, it.instrument?.symbol, '')).toUpperCase()
  if (!symbol) return null
  const id = String(first(d.intent_id, it.intent_id, `draft-${symbol}-${it.entry?.limit_price ?? ''}`))
  const entry = it.entry ?? {}
  return {
    id, source: 'DRAFT', raw: d, symbol,
    account: local[id]?.account ?? String(first(it.account_key, d.account_key, 'ANY')),
    qty: local[id]?.qty ?? Number(first(it.quantity?.qty, d.qty, 10)) || 10,
    side: it.direction === 'SHORT' ? 'SELL SHORT' : 'BUY',
    entryType: String(first(entry.method, 'LIMIT')), entryPrice: num(first(entry.limit_price, entry.stop_price)),
    stop: num(it.exit_policy?.stop?.price), trail: it.exit_policy?.stop?.trail ?? null,
    targets: Array.isArray(it.exit_policy?.targets) ? it.exit_policy.targets : [],
    tif: String(first(it.tif, 'DAY')), session: String(first(it.session, 'NORMAL')),
    reason: it.meta?.thesis ?? 'Broker draft setup', sourceLabel: 'draft'
  }
}

function line(r: SetupRow) {
  const price = r.entryPrice != null ? ` ${r.entryPrice.toFixed(2)}` : ''
  const exits = [
    r.stop != null ? `STOP ${r.stop.toFixed(2)}` : null,
    r.trail ? `TRAIL ${r.trail.offset}${r.trail.type === 'PERCENT' ? '%' : r.trail.type === 'VALUE' ? '$' : ' ticks'} ${r.trail.basis ?? 'LAST'}` : null,
    ...r.targets.map((t: any, i: number) => `TARGET${i + 1} ${Number(t.price).toFixed(2)}${t.qty_pct && t.qty_pct !== 100 ? ` ${t.qty_pct}%` : ''}`)
  ].filter(Boolean).join(' | ')
  return `${r.side} ${r.qty} ${r.symbol} ${r.entryType}${price} ${r.tif}${exits ? ` | ${exits}` : ''}`
}

function csv(v: any) { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
function csvText(rows: SetupRow[]) {
  const out = [['Source','Symbol','Account','Side','Qty','EntryType','EntryPrice','Stop','Targets','TIF','Decision','Score','Sector','Reason','SetupLine']]
  rows.forEach(r => out.push([r.source, r.symbol, r.account, r.side, String(r.qty), r.entryType, r.entryPrice ?? '', r.stop ?? '', r.targets.map((t: any) => t.price).join('|'), r.tif, r.decision ?? '', r.score ?? '', r.sector ?? '', r.reason ?? '', line(r)]))
  return out.map(r => r.map(csv).join(',')).join('\n') + '\n'
}

function copyText(text: string, setMsg: (s: string) => void) {
  const done = () => { setMsg('copied'); setTimeout(() => setMsg(''), 1200) }
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
  else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done() }
}
function dl(name: string, type: string, text: string) { const b = new Blob([text], { type }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(u) }

function activityHit(r: SetupRow, activity: any[]) {
  const exactAcct = r.account && r.account !== 'ANY'
  return activity.find(a => {
    const sym = String(a.symbol ?? '').toUpperCase() === r.symbol
    const ac = !exactAcct || String(a.account_key ?? '') === r.account
    const aq = first(a.quantity, a.qty, a.filled_qty, a.shares)
    const q = aq == null || Number(aq) === r.qty || !r.qty
    return sym && ac && q
  }) ?? null
}
function rowState(r: SetupRow, local: LocalState, activity: any[]): SetupState {
  if (activityHit(r, activity)) return 'BROKER_OBSERVED'
  return local[r.id]?.generated ? 'GENERATED' : 'READY'
}
function payload(r: SetupRow, state: SetupState, hit: any) {
  return { mode: 'MANUAL_TOS', source: r.source, source_id: r.id, account: r.account, symbol: r.symbol, side: r.side, qty: r.qty, entry_type: r.entryType, entry_price: r.entryPrice, stop: r.stop, targets: r.targets, tif: r.tif, score: r.score, decision: r.decision, reason: r.reason, broker_observed: !!hit, observed: hit ? { account_key: hit.account_key, kind: hit.kind, status: hit.status, captured_at: hit.captured_at } : null, setup_line: line(r) }
}

export default function ManualTosDesk() {
  const { data: draftsR, refetch } = useApi<any>('/api/v2/broker-orders/drafts?broker=schwab', 30_000)
  const { data: activityR } = useApi<any>('/api/v2/broker-orders/activity', 30_000)
  const { data: reconR } = useApi<any>('/api/v2/broker-orders/shadow-recon', 60_000)
  const { data: proposalsR } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: tradeAiR } = useApi<any>('/api/v2/trade-ai', 60_000)
  const [local, setLocal] = useState<LocalState>({})
  const [filter, setFilter] = useState<DeskFilter>('ALL')
  const [msg, setMsg] = useState('')
  useEffect(() => { try { setLocal(JSON.parse(localStorage.getItem(LS_KEY) || '{}')) } catch { setLocal({}) } }, [])
  const save = (n: LocalState) => { setLocal(n); localStorage.setItem(LS_KEY, JSON.stringify(n)) }

  const rows = useMemo(() => {
    const p = (((proposalsR as any)?.proposals ?? []) as any[]).map(x => fromProposal(x, local)).filter(Boolean) as SetupRow[]
    const w = (((tradeAiR as any)?.tickers ?? []) as any[]).filter(x => ['GO','WAIT'].includes(String(x.decision ?? '').toUpperCase()) || Number(x.score ?? 0) >= 30).map(x => fromWatch(x, local)).filter(Boolean) as SetupRow[]
    const d = (((draftsR as any)?.drafts ?? []) as any[]).map(x => fromDraft(x, local)).filter(Boolean) as SetupRow[]
    const seen: Record<string, SetupRow> = {}
    ;[...p, ...w, ...d].forEach(r => { const k = `${r.source}:${r.id}`; if (!seen[k]) seen[k] = r })
    return Object.values(seen)
  }, [proposalsR, tradeAiR, draftsR, local])

  const activity = ((activityR as any)?.activity ?? []) as any[]
  const wrapped = rows.map(r => ({ r, state: rowState(r, local, activity), hit: activityHit(r, activity) }))
  const visible = filter === 'ALL' ? wrapped : wrapped.filter(x => x.r.source === filter || x.state === filter)
  const lastRun = (reconR as any)?.runs?.[0]
  const watchTxt = visible.map(x => x.r.symbol).filter((s, i, a) => a.indexOf(s) === i).join('\n') + '\n'
  const setField = (id: string, patch: Partial<LocalState[string]>) => save({ ...local, [id]: { ...(local[id] ?? {}), ...patch } })

  return <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
      <div><div style={{ fontSize: 20, fontWeight: 800 }}>Manual ToS Desk</div><div style={{ fontSize: 11, color: C.dim }}>Proposal, watchlist, and broker-draft setup bridge. Schwab activity is read-only confirmation.</div></div>
      <button onClick={() => refetch()} style={btn('var(--bg2)', C.blue)}>refresh</button>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,minmax(105px,1fr))', gap: 8, marginBottom: 12 }}>{(['ALL','PROPOSAL','WATCHLIST','DRAFT','READY','GENERATED','BROKER_OBSERVED'] as const).map(f => { const count = f === 'ALL' ? wrapped.length : wrapped.filter(x => x.r.source === f || x.state === f).length; return <button key={f} onClick={() => setFilter(f)} style={{ ...btn(filter === f ? C.blue : 'var(--bg2)'), padding: '8px 10px' }}>{f.replace('BROKER_OBSERVED','LINKED')} · {count}</button> })}</div>
    <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg1)', marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}><span style={{ fontSize: 11, color: C.dim }}>Visible exports:</span><button style={btn('#1d4ed8')} onClick={() => copyText(watchTxt, setMsg)}>copy symbols</button><button style={btn('#334155')} onClick={() => dl('tradeai_tos_watchlist.txt', 'text/plain', watchTxt)}>watchlist .txt</button><button style={btn('#334155')} onClick={() => dl('tradeai_manual_setups.csv', 'text/csv', csvText(visible.map(x => x.r)))}>setup CSV</button>{msg && <span style={{ fontSize: 10, color: C.green }}>{msg}</span>}</div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}><div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg1)' }}><b>Lifecycle</b><div style={{ fontSize: 10, color: C.dim, marginTop: 4 }}>Candidate to generated setup to broker activity observed. No local button creates truth.</div></div><div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg1)' }}><b>Read-only recon</b><div style={{ fontSize: 10, color: C.dim, marginTop: 4 }}>{lastRun ? `Last run #${lastRun.id} · orders ${lastRun.orders_seen} · matched ${lastRun.matched} · mismatched ${lastRun.mismatched} · ${lastRun.status}` : 'No recon run yet'}</div></div></div>
    {visible.map(({ r, state, hit }) => <div key={`${r.source}-${r.id}`} style={{ border: `1px solid ${state === 'BROKER_OBSERVED' ? C.green : 'var(--border)'}`, borderRadius: 9, background: 'var(--bg1)', padding: 12, marginBottom: 10 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><span style={{ fontSize: 9, color: r.source === 'PROPOSAL' ? C.green : r.source === 'WATCHLIST' ? C.blue : C.purple, fontWeight: 900 }}>{r.source}</span><span style={{ fontSize: 14, fontWeight: 900, ...mono }}>{line(r)}</span><span style={{ fontSize: 9, color: state === 'BROKER_OBSERVED' ? C.green : state === 'GENERATED' ? C.blue : C.dim, background: 'rgba(96,165,250,.12)', padding: '2px 7px', borderRadius: 4 }}>{state === 'BROKER_OBSERVED' ? 'AUTO-LINKED' : state}</span>{r.decision && <span style={{ fontSize: 9, color: C.amber }}>{r.decision}</span>}{r.score != null && <span style={{ fontSize: 9, color: C.blue }}>score {r.score}</span>}<span style={{ flex: 1 }} />
      <select value={r.account} onChange={e => setField(r.id, { account: e.target.value })} style={{ fontSize: 10, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }}>{ACCOUNTS.map(a => <option key={a} value={a}>{acct(a)}</option>)}</select>
      <input value={r.qty} onChange={e => setField(r.id, { qty: Number(e.target.value) || 1 })} style={{ width: 48, fontSize: 10, padding: '5px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
      <button onClick={() => { setField(r.id, { generated: true }); copyText(line(r), setMsg) }} style={btn('#1d4ed8')}>copy setup</button><button onClick={() => dl(`tradeai_${r.symbol}.json`, 'application/json', JSON.stringify(payload(r, state, hit), null, 2) + '\n')} style={btn('#334155')}>JSON</button><button onClick={() => dl(`tradeai_${r.symbol}.html`, 'text/html', `<pre>${line(r)}\n\n${JSON.stringify(payload(r, state, hit), null, 2)}</pre>`)} style={btn('#334155')}>HTML</button></div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7 }}>{r.stop != null && <span style={{ fontSize: 9, color: C.red }}>stop {r.stop.toFixed(2)}</span>}{r.targets.map((t: any, i: number) => <span key={i} style={{ fontSize: 9, color: C.green }}>target {i + 1}: {Number(t.price).toFixed(2)}</span>)}{r.sector && <span style={{ fontSize: 9, color: C.dim }}>{r.sector}</span>}{r.reason && <span style={{ fontSize: 9, color: C.dim }}>{String(r.reason).slice(0, 150)}</span>}</div>
      {hit ? <div style={{ marginTop: 7, fontSize: 10, color: C.green }}>Matched by read-only activity: {String(hit.captured_at ?? '').slice(0, 16)} · {acct(hit.account_key)} · {hit.kind} · {hit.status}</div> : <div style={{ marginTop: 7, fontSize: 10, color: C.dim }}>No matching Schwab activity observed yet.</div>}
    </div>)}
    <div style={{ marginTop: 12, fontSize: 8.5, color: C.dim }}>Sources: paper proposals, Trade AI scanner/watchlist, broker drafts, read-only broker activity.</div>
  </div>
}
