import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { useProAnalystMap } from '../components/ProAnalystPill'
import { deriveTradeAiRating, normalizeAnalystRating, ratingLabel, ratingRank, type ManualTosRating } from '../lib/manualTosRating'
import { cioBlocksEntry, diligenceFromWatchlistItem, hasAgentMaturity, isActionable } from '../lib/watchlistDiligence'
import EntryDeskRow, { type TechGrade } from '../components/EntryDeskRow'
import EntryDeskDiligenceStrip, { type WatchlistDiligence } from '../components/EntryDeskDiligenceStrip'
import DeskAutomationBar from '../components/DeskAutomationBar'
import BrokerPromoteModal, { type BrokerPromoteSeed } from '../components/BrokerPromoteModal'

export type SourceKind = 'PROPOSAL' | 'WATCHLIST' | 'DRAFT'
type SetupState = 'READY' | 'GENERATED' | 'BROKER_OBSERVED' | 'EXCEPTION'
type SourceFilter = 'ALL' | SourceKind
type AccountFilter = 'ALL' | 'ANY' | 'schwab_taxable' | 'schwab_rollover_ira' | 'schwab_roth_ira'
type DecisionFilter = 'ALL' | 'GO' | 'WAIT' | 'OTHER'
type AnalystFilter = 'ALL' | ManualTosRating
type StatusFilter = 'ALL' | SetupState
type SortMode = 'SCORE_DESC' | 'SYMBOL_ASC' | 'SOURCE' | 'STATUS' | 'ENTRY_PRICE' | 'ANALYST'

type LocalState = Record<string, { account?: string; qty?: number; generated?: boolean }>
type ProvenanceFilter = 'CURATED' | 'ALL'
type UiPrefs = {
  source: SourceFilter; account: AccountFilter; decision: DecisionFilter; analyst: AnalystFilter
  status: StatusFilter; provenance: ProvenanceFilter; search: string; minScore: string
  hasEntry: boolean; hasRisk: boolean; hasMaturity: boolean; actionableOnly: boolean; cioBuyOnly: boolean; sort: SortMode
}
export type SetupRow = {
  id: string; source: SourceKind; raw: any; symbol: string; company?: string | null
  analyst?: string | null; analystCount?: number | null; analystUpside?: number | null
  account: string; qty: number; side: string; entryType: string; entryPrice: number | null
  stop: number | null; trail: any | null; targets: any[]; tif: string; session: string
  score?: number | string | null; decision?: string | null; reason?: string | null
  sector?: string | null; description?: string | null; sourceLabel?: string | null; origin?: string | null
  tier?: string | null; directiveId?: any; diligence?: WatchlistDiligence | null
}

type AccountSnapshot = { key: string; label: string; cash: number | null; buyingPower: number | null; accountValue: number | null }

const LS_KEY = 'tradeai.manualTosDesk.v2'
const PREF_KEY = 'tradeai.manualTosDesk.prefs.v5'
const ACCOUNTS = ['ANY', 'schwab_taxable', 'schwab_rollover_ira', 'schwab_roth_ira']
const C = { blue: '#60a5fa', green: '#22c55e', amber: '#f59e0b', red: '#ef4444', purple: '#a78bfa', dim: 'var(--text3)' }
const btn = (bg: string, fg = '#fff') => ({ fontSize: 10, fontWeight: 700, padding: '6px 10px', borderRadius: 6, border: 'none', background: bg, color: fg, cursor: 'pointer' as const })
const inputStyle = { fontSize: 10, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' } as const
const defaultPrefs: UiPrefs = {
  source: 'ALL', account: 'ALL', decision: 'ALL', analyst: 'ALL', status: 'ALL',
  provenance: 'CURATED', search: '', minScore: '', hasEntry: false, hasRisk: false,
  hasMaturity: false, actionableOnly: false, cioBuyOnly: false, sort: 'ANALYST',
}

function isCurated(r: SetupRow): boolean {
  if (r.source === 'PROPOSAL' || r.source === 'DRAFT') return true
  if (r.directiveId != null) return true
  const o = String(r.origin ?? '').toLowerCase()
  if (['operator', 'trade_ai_screener', 'portfolio', 'hermes'].includes(o)) return true
  if (['core', 'trusted'].includes(String(r.tier ?? '').toLowerCase())) return true
  return false
}

function num(v: any): number | null { const x = Number(v); return Number.isFinite(x) && x > 0 ? x : null }
function first(...vals: any[]) { return vals.find(v => v !== undefined && v !== null && v !== '') }
function str(v: any) { return v == null ? '' : String(v) }
function scoreNum(v: any) { const n = Number(v); return Number.isFinite(n) ? n : 0 }
function rawAnalyst(x: any) { return first(x.analyst_rating, x.analyst_recommendation, x.analyst_consensus, x.consensus_rating, x.recommendation, x.recommendationKey, x.rating, x.finviz_analyst, x.analyst) }
function analystColor(a: any) { const n = typeof a === 'string' ? normalizeAnalystRating(a) : deriveTradeAiRating(a).rating; return n === 'STRONG_BUY' ? '#22c55e' : n === 'BUY' ? '#84cc16' : n === 'HOLD' ? '#f59e0b' : n === 'SELL' || n === 'STRONG_SELL' ? '#ef4444' : C.dim }
function baseQty(x: any) { return Number(first(x.qty, x.shares, x.quantity?.qty, x.recommended_qty, 10)) || 10 }
function normalizedDecision(v: any): DecisionFilter { const d = String(v ?? '').toUpperCase().replace('_', '-'); if (d === 'GO') return 'GO'; if (d === 'WAIT') return 'WAIT'; return 'OTHER' }
function accountSnapshot(a: any): AccountSnapshot {
  const b = a?.balances ?? a?.currentBalances ?? a?.securitiesAccount?.currentBalances ?? {}
  const cash = num(a?.cash) ?? num(b?.cashBalance) ?? num(b?.cashAvailableForTrading)
  const buyingPower = num(a?.buying_power) ?? num(b?.buyingPower) ?? cash
  const accountValue = num(a?.account_value) ?? num(b?.liquidationValue)
  return { key: a?.account_key ?? a?.key ?? '', label: a?.account_key ?? a?.key ?? '', cash, buyingPower, accountValue }
}

function fromProposal(p: any, local: LocalState, paMap: Record<string, any>): SetupRow | null {
  const symbol = String(first(p.symbol, p.ticker, '')).toUpperCase()
  if (!symbol) return null
  const id = String(first(p.proposal_id, p.id, `proposal-${symbol}`))
  const entry = num(first(p.entry_price, p.limit_price, p.proposed_entry, p.price))
  const stop = num(first(p.stop_price, p.stop_loss, p.proposed_stop))
  const target = num(first(p.target_price, p.take_profit, p.proposed_target1, p.target1))
  const pro = paMap[symbol] ?? {}
  return {
    id, source: 'PROPOSAL', raw: p, symbol,
    company: first(p.company, p.name), analyst: first(rawAnalyst(p), pro?.rec),
    analystCount: pro?.n, analystUpside: pro?.upside,
    account: local[id]?.account ?? 'ANY', qty: local[id]?.qty ?? baseQty(p),
    side: 'BUY', entryType: 'LIMIT', entryPrice: entry, stop,
    targets: target ? [{ price: target, qty_pct: 100 }] : [], tif: 'DAY', session: 'NORMAL',
    score: first(p.score, p.signal_score), decision: first(p.decision, p.status),
    reason: first(p.thesis, p.catalyst, 'Paper proposal'),
    sector: p.sector ?? null, origin: first(p.origin, 'proposal'), tier: p.source_tier ?? null,
    directiveId: p.directive_id ?? null, trail: null,
  }
}

function fromWatchlistItem(it: any, local: LocalState, paMap: Record<string, any>, cardMap: Record<string, any>): SetupRow | null {
  const symbol = String(first(it.symbol, it.ticker, '')).toUpperCase()
  if (!symbol) return null
  const card = cardMap[symbol] ?? {}
  const pro = paMap[symbol] ?? {}
  const id = `watchlist-${symbol}`
  return {
    id, source: 'WATCHLIST', raw: it, symbol,
    company: first(it.company, it.name, card.company),
    analyst: first(rawAnalyst(it), pro?.rec, card.analyst_rating),
    analystCount: pro?.n, analystUpside: pro?.upside,
    account: local[id]?.account ?? 'ANY', qty: local[id]?.qty ?? 10,
    side: 'BUY', entryType: 'LIMIT',
    entryPrice: num(first(it.entry_limit, it.entry_price, card.price, it.latest_price)),
    stop: num(first(it.entry_stop, card.entry_stop, it.stop_loss)),
    targets: num(first(it.entry_target, card.entry_target)) ? [{ price: num(first(it.entry_target, card.entry_target)), qty_pct: 100 }] : [],
    tif: 'DAY', session: 'NORMAL',
    score: first(it.hermes_composite_score, it.score, card.score),
    decision: first(it.decision, card.decision),
    reason: first(it.catalyst_headline, it.reason, it.research_summary, 'Curated watchlist candidate'),
    sector: first(it.profile_sector, it.sector, card.sector),
    description: first(it.profile_description, card.description),
    sourceLabel: first(it.source, 'curated-watchlist'), origin: it.source ?? null,
    tier: it.source_tier ?? null, directiveId: it.directive_id ?? null, trail: null,
    diligence: diligenceFromWatchlistItem(it),
  }
}

function fromDraft(d: any, local: LocalState, paMap: Record<string, any>): SetupRow | null {
  const it = d.intent_json ?? d.intent ?? d
  const symbol = String(first(d.symbol, it.instrument?.symbol, '')).toUpperCase()
  if (!symbol) return null
  const id = String(first(d.intent_id, `draft-${symbol}`))
  const entry = it.entry ?? {}
  const pro = paMap[symbol] ?? {}
  return {
    id, source: 'DRAFT', raw: d, symbol,
    company: first(d.company, it.instrument?.name), analyst: first(rawAnalyst(d), pro?.rec),
    analystCount: pro?.n, analystUpside: pro?.upside,
    account: local[id]?.account ?? String(first(it.account_key, 'ANY')),
    qty: local[id]?.qty ?? (Number(first(it.quantity?.qty, 10)) || 10),
    side: it.direction === 'SHORT' ? 'SELL SHORT' : 'BUY',
    entryType: String(first(entry.method, 'LIMIT')).toUpperCase(),
    entryPrice: num(first(entry.limit_price, entry.stop_price)),
    stop: num(it.exit_policy?.stop?.price),
    trail: it.exit_policy?.stop?.trail ?? null,
    targets: Array.isArray(it.exit_policy?.targets) ? it.exit_policy.targets : [],
    tif: String(first(it.tif, 'DAY')), session: 'NORMAL',
    reason: it.meta?.thesis ?? 'Broker draft setup',
  }
}

function setupLine(r: SetupRow) {
  const price = r.entryPrice != null ? ` ${r.entryPrice.toFixed(2)}` : ''
  return `${r.side} ${r.qty} ${r.symbol} ${r.entryType}${price} ${r.tif}`
}
function csv(v: any) { const s = str(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
function csvText(rows: SetupRow[]) {
  const header = ['Source', 'Symbol', 'Company', 'Rating', 'Account', 'Qty', 'Entry', 'Stop', 'Targets', 'Score', 'SetupLine']
  const lines = [header.join(',')]
  rows.forEach(r => {
    const rr = deriveTradeAiRating(r)
    lines.push([r.source, r.symbol, str(r.company), ratingLabel(rr.rating), r.account, String(r.qty),
      str(r.entryPrice), str(r.stop), r.targets.map((t: any) => t.price).join('|'), str(r.score), setupLine(r)].map(csv).join(','))
  })
  return lines.join('\n') + '\n'
}
function dl(name: string, type: string, text: string) {
  const b = new Blob([text], { type }); const u = URL.createObjectURL(b)
  const a = document.createElement('a'); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(u)
}
function activityHit(r: SetupRow, activity: any[]) {
  return activity.find(a => String(a.symbol ?? '').toUpperCase() === r.symbol) ?? null
}
function rowState(r: SetupRow, local: LocalState, activity: any[]): SetupState {
  if (!r.entryPrice) return 'EXCEPTION'
  if (activityHit(r, activity)) return 'BROKER_OBSERVED'
  return local[r.id]?.generated ? 'GENERATED' : 'READY'
}

type DeskProps = { focusSymbol?: string }

export default function ManualTosDesk({ focusSymbol }: DeskProps = {}) {
  const { data: draftsR, refetch } = useApi<any>('/api/v2/broker-orders/drafts?broker=schwab', 30_000)
  const { data: activityR } = useApi<any>('/api/v2/broker-orders/activity', 30_000)
  const { data: proposalsR } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: watchlistR } = useApi<any>('/api/v2/watchlist/items?sort=hermes&full=1', 60_000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const { data: schwabR } = useApi<any>('/api/v2/schwab/accounts-live', 120_000)
  const { data: wlSummary } = useApi<any>('/api/v2/watchlist/summary', 120_000)
  const { data: execState } = useApi<any>('/api/v2/execution/current-state', 120_000)
  const { data: automationR } = useApi<any>('/api/v2/entry-desk/automation', 120_000)
  const paMap = useProAnalystMap()
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const accountRows: any[] = ((schwabR as any)?.data ?? schwabR)?.accounts ?? []
  const accountMap: Record<string, AccountSnapshot> = Object.fromEntries(
    accountRows.map(a => { const s = accountSnapshot(a); return [s.key, s] }).filter(([k]) => !!k),
  )
  const accountKeys = ['ANY', ...Object.keys(accountMap).filter(k => k && !ACCOUNTS.includes(k)), ...ACCOUNTS.filter(a => a !== 'ANY')]

  const [local, setLocal] = useState<LocalState>({})
  const [prefs, setPrefs] = useState<UiPrefs>(defaultPrefs)
  const [msg, setMsg] = useState('')
  const [techGrades, setTechGrades] = useState<Record<string, TechGrade>>({})
  const [promoteBusy, setPromoteBusy] = useState<string | null>(null)
  const [promoteSeed, setPromoteSeed] = useState<BrokerPromoteSeed | null>(null)

  useEffect(() => {
    try { setLocal(JSON.parse(localStorage.getItem(LS_KEY) || '{}')) } catch { setLocal({}) }
    try { setPrefs({ ...defaultPrefs, ...JSON.parse(localStorage.getItem(PREF_KEY) || '{}') }) } catch { setPrefs(defaultPrefs) }
  }, [])

  const saveLocal = (n: LocalState) => { setLocal(n); localStorage.setItem(LS_KEY, JSON.stringify(n)) }
  const savePrefs = (patch: Partial<UiPrefs>) => {
    const next = { ...prefs, ...patch }; setPrefs(next); localStorage.setItem(PREF_KEY, JSON.stringify(next))
  }

  const focusKey = focusSymbol?.trim().toUpperCase() || ''
  useEffect(() => {
    if (!focusKey) return
    savePrefs({ search: focusKey, source: 'WATCHLIST' })
  }, [focusKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const drill = (patch: Partial<UiPrefs>) => savePrefs({ ...defaultPrefs, ...patch })
  const setField = (id: string, patch: Partial<LocalState[string]>) => saveLocal({ ...local, [id]: { ...(local[id] ?? {}), ...patch } })

  const rows = useMemo(() => {
    const p = (((proposalsR as any)?.proposals ?? []) as any[]).map(x => fromProposal(x, local, paMap)).filter(Boolean) as SetupRow[]
    const wl = (((watchlistR as any)?.items ?? []) as any[]).map(x => fromWatchlistItem(x, local, paMap, cardMap)).filter(Boolean) as SetupRow[]
    const d = (((draftsR as any)?.drafts ?? []) as any[]).map(x => fromDraft(x, local, paMap)).filter(Boolean) as SetupRow[]
    const seen: Record<string, SetupRow> = {}
    ;[...p, ...wl, ...d].forEach(r => { const k = `${r.source}:${r.id}`; if (!seen[k]) seen[k] = r })
    // company one-liner for every source — proposals/drafts don't carry it, symbol-cards does
    return Object.values(seen).map(r => (r.description ? r : { ...r, description: cardMap[r.symbol]?.description ?? null }))
  }, [proposalsR, watchlistR, draftsR, local, paMap, cardMap])

  const activity = ((activityR as any)?.activity ?? []) as any[]
  const wrapped = rows.map(r => ({ r, state: rowState(r, local, activity), hit: activityHit(r, activity) }))
  const filtered = wrapped.filter(({ r, state }) => {
    const decision = normalizedDecision(r.decision)
    const rating = deriveTradeAiRating(r).rating
    const q = prefs.search.trim().toUpperCase()
    if (prefs.provenance === 'CURATED' && !isCurated(r)) return false
    if (prefs.source !== 'ALL' && r.source !== prefs.source) return false
    if (prefs.account !== 'ALL' && r.account !== prefs.account) return false
    if (prefs.decision !== 'ALL' && decision !== prefs.decision) return false
    if (prefs.analyst !== 'ALL' && rating !== prefs.analyst) return false
    if (prefs.status !== 'ALL' && state !== prefs.status) return false
    if (prefs.hasMaturity && !hasAgentMaturity(r.diligence)) return false
    if (prefs.actionableOnly && !isActionable(r.diligence)) return false
    if (prefs.cioBuyOnly && cioBlocksEntry(r.diligence)) return false
    if (q && !`${r.symbol} ${r.company ?? ''} ${r.reason ?? ''} ${ratingLabel(rating)}`.toUpperCase().includes(q)) return false
    if (prefs.minScore && scoreNum(r.score) < Number(prefs.minScore)) return false
    if (prefs.hasEntry && !r.entryPrice) return false
    if (prefs.hasRisk && !r.stop && r.targets.length === 0) return false
    return true
  })

  const visible = [...filtered].sort((a, b) => {
    if (prefs.sort === 'SYMBOL_ASC') return a.r.symbol.localeCompare(b.r.symbol)
    if (prefs.sort === 'SOURCE') return a.r.source.localeCompare(b.r.source) || a.r.symbol.localeCompare(b.r.symbol)
    if (prefs.sort === 'STATUS') return a.state.localeCompare(b.state) || a.r.symbol.localeCompare(b.r.symbol)
    if (prefs.sort === 'ENTRY_PRICE') return (b.r.entryPrice ?? 0) - (a.r.entryPrice ?? 0)
    if (prefs.sort === 'ANALYST') return ratingRank(deriveTradeAiRating(b.r).rating) - ratingRank(deriveTradeAiRating(a.r).rating) || scoreNum(b.r.score) - scoreNum(a.r.score)
    return scoreNum(b.r.score) - scoreNum(a.r.score)
  })

  const visibleSymsKey = visible.slice(0, 35).map(x => x.r.symbol).join(',')
  useEffect(() => {
    const syms = visibleSymsKey.split(',').filter(Boolean)
    if (!syms.length) return
    let cancelled = false
    fetch('/api/v2/entry-desk/technical-grades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: syms }),
    })
      .then(r => r.json())
      .then(res => {
        if (!cancelled && res.ok && res.grades) setTechGrades(prev => ({ ...prev, ...res.grades }))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [visibleSymsKey])

  const handlePromote = useCallback(async (r: SetupRow) => {
    const acct = r.account === 'ANY' ? 'schwab_taxable' : r.account
    const target = r.targets?.[0]?.price ? Number(r.targets[0].price) : null
    if (!r.entryPrice || !r.stop || !target) return
    setPromoteBusy(r.id)
    try {
      const res = await fetch('/api/v2/entry-desk/promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: r.symbol, account: acct, shares: r.qty,
          entry: r.entryPrice, stop: r.stop, target, source: r.source,
        }),
      }).then(x => x.json())
      if (res.ok && res.proposal_id) {
        setPromoteSeed({ proposal_id: res.proposal_id, symbol: r.symbol, account: acct })
        setMsg(`queued #${res.proposal_id} ${r.symbol}`)
      } else {
        setMsg(res.error || 'promote failed')
      }
    } catch {
      setMsg('promote failed')
    } finally {
      setPromoteBusy(null)
    }
  }, [])

  const counts = {
    total: rows.length,
    proposals: rows.filter(r => r.source === 'PROPOSAL').length,
    watchlist: rows.filter(r => r.source === 'WATCHLIST').length,
    drafts: rows.filter(r => r.source === 'DRAFT').length,
    ready: wrapped.filter(x => x.state === 'READY').length,
    generated: wrapped.filter(x => x.state === 'GENERATED').length,
    observed: wrapped.filter(x => x.state === 'BROKER_OBSERVED').length,
    exceptions: wrapped.filter(x => x.state === 'EXCEPTION').length,
  }
  const ratingCounts: Record<ManualTosRating, number> = { STRONG_BUY: 0, BUY: 0, HOLD: 0, SELL: 0, STRONG_SELL: 0, UNKNOWN: 0 }
  rows.forEach(r => { ratingCounts[deriveTradeAiRating(r).rating] += 1 })
  const curatedHidden = prefs.provenance === 'CURATED' ? rows.filter(r => !isCurated(r)).length : 0
  const watchTxt = visible.map(x => x.r.symbol).filter((s, i, a) => a.indexOf(s) === i).join('\n') + '\n'
  const kpis = [
    { label: 'Total Candidates', value: counts.total, color: 'var(--text0)', onClick: () => drill({}) },
    { label: 'Proposals', value: counts.proposals, color: C.green, onClick: () => drill({ source: 'PROPOSAL' }) },
    { label: 'Watchlist', value: counts.watchlist, color: C.blue, onClick: () => drill({ source: 'WATCHLIST' }) },
    { label: 'Drafts', value: counts.drafts, color: C.purple, onClick: () => drill({ source: 'DRAFT' }) },
    { label: 'Ready', value: counts.ready, color: C.dim, onClick: () => drill({ status: 'READY' }) },
    { label: 'Generated', value: counts.generated, color: C.blue, onClick: () => drill({ status: 'GENERATED' }) },
    { label: 'Broker Observed', value: counts.observed, color: C.green, onClick: () => drill({ status: 'BROKER_OBSERVED' }) },
    { label: 'Exceptions', value: counts.exceptions, color: C.red, onClick: () => drill({ status: 'EXCEPTION' }) },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 900 }}>Entry Desk</div>
          <div style={{ fontSize: 11, color: C.dim }}>
            Path A manual ToS · Path B via <b style={{ color: C.green }}>→ Broker queue</b> (7-stage diligence + 2FA on Proposals).
            Copy ack logs operator ticket copy without Schwab API submit.
          </div>
        </div>
        <button onClick={() => refetch()} style={btn('var(--bg2)', C.blue)}>refresh</button>
      </div>

      <DeskAutomationBar automation={(automationR as any)?.ok !== false ? automationR : null} />

      <details style={{ marginBottom: 12, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg1)' }}>
        <summary style={{ fontSize: 10, fontWeight: 800, color: C.dim, cursor: 'pointer', listStyle: 'none' }}>
          Diligence model · 2FA
          {execState?.operator_live_via_2fa_allowed != null && (
            <span style={{ marginLeft: 10, color: execState.operator_live_via_2fa_allowed ? C.green : C.amber, fontWeight: 900 }}>
              {execState.operator_live_via_2fa_allowed ? '2FA LIVE ON' : '2FA LIVE BLOCKED'}
            </span>
          )}
        </summary>
        <div style={{ marginTop: 10, fontSize: 9.5, color: 'var(--text2)', lineHeight: 1.55 }}>
          <div><b style={{ color: C.blue }}>This tab:</b> deterministic rating/R:R + watchlist agent maturity + live TECH grade (Finviz). Copy + type-ticker ack = audit trail.</div>
          <div style={{ marginTop: 6 }}><b style={{ color: C.green }}>Proposals tab:</b> Stage 2b LLM + trade plan gate + Auto route (2FA) Schwab submit.</div>
          {wlSummary?.jobs && <div style={{ marginTop: 6, fontSize: 9, color: C.dim }}>Watchlist jobs: {Object.entries(wlSummary.jobs as Record<string, number>).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>}
        </div>
      </details>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8,minmax(100px,1fr))', gap: 8, marginBottom: 12 }}>
        {kpis.map(k => (
          <button key={k.label} onClick={k.onClick} style={{ textAlign: 'left', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 9, padding: '8px 10px', cursor: 'pointer' }}>
            <div style={{ fontSize: 16, fontWeight: 900, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 8, color: C.dim, textTransform: 'uppercase' }}>{k.label}</div>
          </button>
        ))}
      </div>

      <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg1)', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontSize: 10, color: C.dim, fontWeight: 800 }}>Recommendation filter:</span>
          <button onClick={() => savePrefs({ analyst: 'ALL' })} style={{ ...btn(prefs.analyst === 'ALL' ? C.blue : 'var(--bg2)', prefs.analyst === 'ALL' ? '#0b1020' : 'var(--text2)'), border: `1px solid ${prefs.analyst === 'ALL' ? C.blue : 'var(--border)'}` }}>All · {rows.length}</button>
          {(['STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL', 'UNKNOWN'] as ManualTosRating[]).map(a => (
            <button key={a} onClick={() => savePrefs({ analyst: a })} style={{ ...btn(prefs.analyst === a ? analystColor(a) : 'var(--bg2)', prefs.analyst === a ? '#0b1020' : 'var(--text2)'), border: `1px solid ${prefs.analyst === a ? analystColor(a) : 'var(--border)'}` }}>
              {ratingLabel(a)} · {ratingCounts[a]}
            </button>
          ))}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px,1fr))', gap: 8, marginBottom: 8 }}>
          <select value={prefs.provenance} onChange={e => savePrefs({ provenance: e.target.value as ProvenanceFilter })} style={{ ...inputStyle, borderColor: prefs.provenance === 'CURATED' ? '#22c55e' : 'var(--border)' }}>
            <option value="CURATED">Curated only{curatedHidden ? ` (${curatedHidden} hidden)` : ''}</option>
            <option value="ALL">All provenance</option>
          </select>
          <select value={prefs.source} onChange={e => savePrefs({ source: e.target.value as SourceFilter })} style={inputStyle}>
            <option value="ALL">All sources</option><option value="PROPOSAL">Proposal</option><option value="WATCHLIST">Watchlist</option><option value="DRAFT">Draft</option>
          </select>
          <select value={prefs.account} onChange={e => savePrefs({ account: e.target.value as AccountFilter })} style={inputStyle}>
            <option value="ALL">All accounts</option><option value="ANY">Any Schwab</option><option value="schwab_taxable">Taxable</option>
          </select>
          <select value={prefs.status} onChange={e => savePrefs({ status: e.target.value as StatusFilter })} style={inputStyle}>
            <option value="ALL">All statuses</option><option value="READY">Ready</option><option value="GENERATED">Generated</option><option value="BROKER_OBSERVED">Broker observed</option><option value="EXCEPTION">Exception</option>
          </select>
          <input value={prefs.search} onChange={e => savePrefs({ search: e.target.value })} placeholder="Search symbol/company" style={inputStyle} />
          <input value={prefs.minScore} onChange={e => savePrefs({ minScore: e.target.value })} placeholder="Min score" type="number" style={inputStyle} />
          <select value={prefs.sort} onChange={e => savePrefs({ sort: e.target.value as SortMode })} style={inputStyle}>
            <option value="ANALYST">Recommendation strength</option><option value="SCORE_DESC">Score desc</option><option value="SYMBOL_ASC">Symbol A-Z</option>
          </select>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 10, color: C.dim, flexWrap: 'wrap' }}>
            <label><input type="checkbox" checked={prefs.hasEntry} onChange={e => savePrefs({ hasEntry: e.target.checked })} /> Has entry</label>
            <label><input type="checkbox" checked={prefs.hasRisk} onChange={e => savePrefs({ hasRisk: e.target.checked })} /> Has stop/target</label>
            <label><input type="checkbox" checked={prefs.hasMaturity} onChange={e => savePrefs({ hasMaturity: e.target.checked })} /> Agent maturity</label>
            <label><input type="checkbox" checked={prefs.actionableOnly} onChange={e => savePrefs({ actionableOnly: e.target.checked })} /> CIO actionable</label>
            <label title="Hide CIO AVOID/IGNORE — Finviz analyst STRONG BUY may still show without this filter"><input type="checkbox" checked={prefs.cioBuyOnly} onChange={e => savePrefs({ cioBuyOnly: e.target.checked })} /> CIO not AVOID</label>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button style={btn('#475569')} onClick={() => savePrefs(defaultPrefs)}>Reset Filters</button>
          <button style={btn('#334155')} onClick={() => dl('tradeai_tos_watchlist.txt', 'text/plain', watchTxt)}>download ToS watchlist</button>
          <button style={btn('#334155')} onClick={() => dl('tradeai_manual_setups.csv', 'text/csv', csvText(visible.map(x => x.r)))}>download CSV</button>
          {msg && <span style={{ fontSize: 10, color: C.green }}>{msg}</span>}
        </div>
      </div>

      {visible.length === 0 && (
        <div style={{ padding: 14, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg1)', color: C.dim, fontSize: 11 }}>
          No candidates match filters.
        </div>
      )}

      {visible.map(({ r, state, hit }) => {
        const street = num(paMap[r.symbol]?.target)
        const account = r.account === 'ANY' ? null : accountMap[r.account] ?? null
        return (
          <EntryDeskRow
            key={`${r.source}-${r.id}`}
            r={r}
            state={state}
            hit={hit}
            account={account}
            streetTarget={street}
            tech={techGrades[r.symbol]}
            accounts={accountKeys}
            accountMap={accountMap}
            onSetField={setField}
            onCopyMsg={setMsg}
            onPromote={handlePromote}
            promoteBusy={promoteBusy === r.id}
            focused={!!focusKey && r.symbol.toUpperCase() === focusKey}
          />
        )
      })}

      {promoteSeed && (
        <BrokerPromoteModal
          seed={promoteSeed}
          onClose={() => setPromoteSeed(null)}
          onPromoted={() => {
            setPromoteSeed(null)
            setMsg(`Promoted ${promoteSeed.symbol} — open Proposals for 2FA route`)
          }}
        />
      )}

      <div style={{ marginTop: 12, fontSize: 8.5, color: C.dim }}>
        APIs: entry-desk/promote · ack-copy · technical-grades · watchlist/items · paper-proposals
      </div>
    </div>
  )
}