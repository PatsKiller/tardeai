import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

const PREF_KEY = 'portfolio.reentry.assignments.v1'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'
const MUTED = 'var(--text3)'

const INTENTS = ['UNASSIGNED', 'CORE', 'COMPOUNDING', 'DIVIDEND', 'SHORT', 'SWING'] as const
const PRIORITIES = ['HIGH', 'NORMAL', 'LOW'] as const
const STATUSES = ['READY_FOR_REVIEW', 'NEAR_ZONE', 'OVERSOLD_REVIEW', 'WATCH', 'OVERBOUGHT_WAIT', 'STALE', 'NEEDS_DATA'] as const

type Intent = typeof INTENTS[number]
type Priority = typeof PRIORITIES[number]
type ReEntryStatus = typeof STATUSES[number]

type Assignment = {
  intent: Intent
  priority: Priority
  monitor: boolean
  account: string
  target_weight_pct: number | null
  notes: string
  updated_at: string
  alert_summary?: string
}

type ExitEvent = {
  id: string
  symbol: string
  date: string
  account: string
  shares: number | null
  sellPrice: number | null
  proceeds: number | null
  reason: string
  exitType: 'STOPPED' | 'SOLD'
  source: string
  raw: any
}

type Intel = {
  symbol: string
  last: number | null
  rsi: number | null
  rsiZone: 'OVERSOLD' | 'OVERBOUGHT' | 'NEUTRAL' | 'UNAVAILABLE'
  entryLow: number | null
  entryHigh: number | null
  stop: number | null
  target: number | null
  distancePct: number | null
  asOf: string | null
  stale: boolean
  status: ReEntryStatus
  dataNote: string
}

const panel: React.CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
}
const button = (active = false): React.CSSProperties => ({
  fontSize: 10.5, fontWeight: 750, padding: '5px 10px', borderRadius: 5, cursor: 'pointer',
  border: `1px solid ${active ? BLUE : 'var(--border)'}`,
  background: active ? 'rgba(96,165,250,.14)' : 'var(--bg2)', color: active ? BLUE : 'var(--text2)',
})
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5,
  border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)',
}

function root(v: any): any {
  return v?.data ?? v ?? {}
}
function finite(...values: any[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const n = Number(value)
    if (Number.isFinite(n)) return n
  }
  return null
}
function text(...values: any[]): string {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const s = String(value).trim()
    if (s) return s
  }
  return ''
}
function firstRows(v: any): any[] {
  const r = root(v)
  for (const key of ['history', 'events', 'items', 'rows', 'sells', 'transactions']) {
    if (Array.isArray(r?.[key])) return r[key]
  }
  return Array.isArray(r) ? r : []
}
function isoDay(value: any): string {
  const s = text(value)
  if (!s) return ''
  const d = new Date(s)
  return Number.isFinite(d.getTime()) ? d.toISOString().slice(0, 10) : s.slice(0, 10)
}
function normalizeExit(row: any, i: number): ExitEvent | null {
  const symbol = text(row.symbol, row.sold_symbol, row.ticker, row.security_symbol).toUpperCase()
  if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol)) return null
  const date = isoDay(row.sold_at ?? row.close_date ?? row.trade_date ?? row.executed_at ?? row.transaction_date ?? row.date)
  const reason = text(row.exit_reason, row.sell_reason, row.reason, row.notes, row.strategy, row.description)
  const stopped = /stop|protective|trailing|risk exit/i.test(reason)
  return {
    id: text(row.id, row.event_id, row.transaction_id, `${symbol}-${date}-${i}`),
    symbol,
    date,
    account: text(row.account, row.account_key, row.account_name, row.broker_account),
    shares: finite(row.shares, row.quantity, row.qty),
    sellPrice: finite(row.sell_price, row.price, row.avg_price, row.execution_price, row.average_price),
    proceeds: finite(row.proceeds_usd, row.net_proceeds, row.proceeds, row.amount),
    reason: reason || 'Operator sale / exit reason not classified',
    exitType: stopped ? 'STOPPED' : 'SOLD',
    source: text(row.source, row.source_system, 'trade history'),
    raw: row,
  }
}
function getPath(obj: any, path: string): any {
  return path.split('.').reduce((v: any, key) => v?.[key], obj)
}
function pickPath(objects: any[], paths: string[]): number | null {
  for (const obj of objects) {
    for (const path of paths) {
      const n = finite(getPath(obj, path))
      if (n !== null) return n
    }
  }
  return null
}
function pickText(objects: any[], paths: string[]): string | null {
  for (const obj of objects) {
    for (const path of paths) {
      const s = text(getPath(obj, path))
      if (s) return s
    }
  }
  return null
}
function money(v: number | null): string {
  return v === null ? '—' : fmt$(v, 2)
}
function ageLabel(value: string | null): string {
  if (!value) return 'timestamp unavailable'
  const ms = new Date(value).getTime()
  if (!Number.isFinite(ms)) return value.slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - ms) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function statusColor(status: ReEntryStatus): string {
  if (status === 'READY_FOR_REVIEW') return GREEN
  if (status === 'NEAR_ZONE' || status === 'OVERSOLD_REVIEW') return AMBER
  if (status === 'OVERBOUGHT_WAIT') return RED
  if (status === 'WATCH') return BLUE
  return MUTED
}
function intentColor(intent: Intent): string {
  if (intent === 'CORE') return BLUE
  if (intent === 'COMPOUNDING') return PURPLE
  if (intent === 'DIVIDEND') return GREEN
  if (intent === 'SHORT') return RED
  if (intent === 'SWING') return AMBER
  return MUTED
}
function defaultAssignment(): Assignment {
  return { intent: 'UNASSIGNED', priority: 'NORMAL', monitor: true, account: '', target_weight_pct: null, notes: '', updated_at: '' }
}

function deriveIntel(symbol: string, watch: any, card: any, advisory: any, assignment: Assignment): Intel {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.mechanics ?? packet?.current_mechanics ?? {}
  const objects = [advisory ?? {}, watch ?? {}, card ?? {}, packet ?? {}, mechanics ?? {}]
  const rsi = pickPath(objects, ['rsi', 'rsi_14', 'current_rsi', 'technicals.rsi', 'technicals.rsi_14', 'indicators.rsi', 'indicators.rsi_14'])
  const last = pickPath(objects, ['last_price', 'price', 'current_price', 'quote.last', 'quote.price', 'market.last'])
  let entryLow = pickPath(objects, ['entry_zone_low', 'plan_entry_low', 'entry_low', 'mechanics.entry_low', 'entry.zone_low', 'entry.min'])
  let entryHigh = pickPath(objects, ['entry_zone_high', 'plan_entry_high', 'entry_high', 'mechanics.entry_high', 'entry.zone_high', 'entry.max'])
  const entry = pickPath(objects, ['entry_limit', 'plan_entry', 'entry_price', 'mechanics.entry', 'entry.limit', 'selected_entry'])
  if (entryLow === null && entry !== null) entryLow = entry
  if (entryHigh === null && entry !== null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]
  const stop = pickPath(objects, ['entry_stop', 'plan_stop', 'stop_price', 'mechanics.stop', 'entry.stop'])
  const target = pickPath(objects, ['entry_target', 'plan_target', 'target_price', 'mechanics.target', 'entry.target'])
  const asOf = pickText(objects, ['last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote.as_of', 'technicals.as_of'])
  const asOfMs = asOf ? new Date(asOf).getTime() : NaN
  const stale = !Number.isFinite(asOfMs) || Date.now() - asOfMs > 96 * 36e5
  let distancePct: number | null = null
  if (last !== null && last > 0 && entryLow !== null && entryHigh !== null) {
    if (last > entryHigh) distancePct = ((last - entryHigh) / last) * 100
    else if (last < entryLow) distancePct = -((entryLow - last) / last) * 100
    else distancePct = 0
  }
  const rsiZone: Intel['rsiZone'] = rsi === null ? 'UNAVAILABLE' : rsi <= 30 ? 'OVERSOLD' : rsi >= 70 ? 'OVERBOUGHT' : 'NEUTRAL'
  let status: ReEntryStatus = 'WATCH'
  const isShort = assignment.intent === 'SHORT'
  if (last === null || rsi === null || entryLow === null || entryHigh === null) status = 'NEEDS_DATA'
  else if (stale) status = 'STALE'
  else if (isShort) {
    if (distancePct !== null && distancePct <= 0 && rsi >= 65) status = 'READY_FOR_REVIEW'
    else if (rsi >= 70) status = 'OVERSOLD_REVIEW'
    else if (distancePct !== null && Math.abs(distancePct) <= 3) status = 'NEAR_ZONE'
    else status = 'WATCH'
  } else {
    if (distancePct === 0 && rsi <= 45) status = 'READY_FOR_REVIEW'
    else if (distancePct !== null && distancePct >= 0 && distancePct <= 3 && rsi <= 58) status = 'NEAR_ZONE'
    else if (rsi <= 30) status = 'OVERSOLD_REVIEW'
    else if (rsi >= 70) status = 'OVERBOUGHT_WAIT'
    else status = 'WATCH'
  }
  return {
    symbol, last, rsi, rsiZone, entryLow, entryHigh, stop, target, distancePct, asOf, stale, status,
    dataNote: text(watch?.data_quality_state, card?.data_quality_state, advisory?.note, packet?.current_validity?.state, 'cached Trade AI intelligence'),
  }
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(2,6,23,.78)', display: 'grid', placeItems: 'center', padding: 18 }} onMouseDown={onClose}>
      <div onMouseDown={e => e.stopPropagation()} style={{ ...panel, width: 'min(620px, 96vw)', maxHeight: '92vh', overflowY: 'auto', padding: 16, boxShadow: '0 20px 60px rgba(0,0,0,.55)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 900 }}>{title}</div>
            {subtitle && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 3 }}>{subtitle}</div>}
          </div>
          <button onClick={onClose} style={button(false)}>CLOSE</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export default function ReEntryPage() {
  const from = useMemo(() => {
    const d = new Date(); d.setUTCFullYear(d.getUTCFullYear() - 1); return d.toISOString().slice(0, 10)
  }, [])
  const { data: historyRaw, loading: historyLoading, error: historyError, refetch: refetchHistory } = useApi<any>('/api/v2/redeploy/history?days=365', 120_000)
  const { data: journalRaw, refetch: refetchJournal } = useApi<any>(`/api/v2/journal/by-ticker?from=${from}`, 120_000)
  const { data: cardsRaw, refetch: refetchCards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const { data: advisoryRaw, refetch: refetchAdvisory } = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)
  const { data: prefRaw, refetch: refetchPrefs } = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(PREF_KEY)}`, 0)
  const { data: alertsRaw, refetch: refetchAlerts } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const { data: regimeRaw, refetch: refetchRegime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)

  const [assignments, setAssignments] = useState<Record<string, Assignment>>({})
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [intelLoading, setIntelLoading] = useState(false)
  const [intelReload, setIntelReload] = useState(0)
  const [search, setSearch] = useState('')
  const [intentFilter, setIntentFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [exitFilter, setExitFilter] = useState('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editSymbol, setEditSymbol] = useState<string | null>(null)
  const [alertSymbol, setAlertSymbol] = useState<string | null>(null)
  const [toast, setToast] = useState('')

  useEffect(() => {
    const value = root(prefRaw)?.value
    if (value && typeof value === 'object' && !Array.isArray(value)) setAssignments(value)
  }, [prefRaw])

  const exits = useMemo(() => {
    const rows = firstRows(historyRaw)
      .map(normalizeExit)
      .filter((v): v is ExitEvent => !!v)
      .filter(e => !e.date || e.date >= from)
    return rows.sort((a, b) => b.date.localeCompare(a.date))
  }, [historyRaw, from])

  const bySymbol = useMemo(() => {
    const map = new Map<string, ExitEvent[]>()
    for (const event of exits) {
      const list = map.get(event.symbol) ?? []
      list.push(event); map.set(event.symbol, list)
    }
    const journalTickers: any[] = root(journalRaw)?.tickers ?? []
    for (const ticker of journalTickers) {
      const symbol = text(ticker.symbol).toUpperCase()
      if (!symbol || map.has(symbol)) continue
      const fallback = normalizeExit({
        symbol,
        close_date: ticker.last_close ?? ticker.last_close_date ?? ticker.last_trade_at,
        sell_price: ticker.last_sell_price,
        reason: 'Closed trade history',
      }, 0)
      if (fallback) map.set(symbol, [fallback])
    }
    return Array.from(map.entries()).map(([symbol, events]) => ({
      symbol,
      events: events.slice().sort((a, b) => b.date.localeCompare(a.date)),
      latest: events.slice().sort((a, b) => b.date.localeCompare(a.date))[0],
      journal: journalTickers.find(t => text(t.symbol).toUpperCase() === symbol) ?? null,
    }))
  }, [exits, journalRaw])

  const symbolKey = useMemo(() => bySymbol.map(r => r.symbol).sort().join(','), [bySymbol])
  useEffect(() => {
    const symbols = symbolKey ? symbolKey.split(',').filter(Boolean).slice(0, 150) : []
    if (!symbols.length) return
    let cancelled = false
    const controller = new AbortController()
    setIntelLoading(true)
    const out: Record<string, any> = {}
    let cursor = 0
    const worker = async () => {
      while (!cancelled) {
        const idx = cursor++
        if (idx >= symbols.length) return
        const symbol = symbols[idx]
        try {
          const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { signal: controller.signal })
          const payload = root(await response.json())
          out[symbol] = (payload?.items ?? [])[0] ?? null
          if (!cancelled && idx % 8 === 0) setWatchMap(prev => ({ ...prev, ...out }))
        } catch { out[symbol] = null }
      }
    }
    void Promise.all(Array.from({ length: Math.min(6, symbols.length) }, worker)).finally(() => {
      if (!cancelled) { setWatchMap(prev => ({ ...prev, ...out })); setIntelLoading(false) }
    })
    return () => { cancelled = true; controller.abort() }
  }, [symbolKey, intelReload])

  const cards: Record<string, any> = root(cardsRaw)?.cards ?? {}
  const advisories: Record<string, any> = useMemo(() => {
    const map: Record<string, any> = {}
    for (const row of root(advisoryRaw)?.advisories ?? []) map[text(row.symbol).toUpperCase()] = row
    return map
  }, [advisoryRaw])
  const alertRows: any[] = root(alertsRaw)?.alerts ?? root(alertsRaw)?.items ?? []
  const alertCount = (symbol: string) => alertRows.filter(a => text(a.symbol).toUpperCase() === symbol && !['disabled', 'expired', 'resolved'].includes(text(a.status).toLowerCase())).length
  const regime = text(root(regimeRaw)?.regime_label, root(regimeRaw)?.label, 'unknown').replace(/_/g, ' ')

  const rows = useMemo(() => bySymbol.map(row => {
    const assignment = assignments[row.symbol] ?? defaultAssignment()
    const intel = deriveIntel(row.symbol, watchMap[row.symbol], cards[row.symbol], advisories[row.symbol], assignment)
    const moveSinceExit = row.latest?.sellPrice && intel.last ? ((intel.last - row.latest.sellPrice) / row.latest.sellPrice) * 100 : null
    return { ...row, assignment, intel, moveSinceExit }
  }), [bySymbol, assignments, watchMap, cards, advisories])

  const shown = useMemo(() => {
    const q = search.trim().toUpperCase()
    const rank: Record<ReEntryStatus, number> = { READY_FOR_REVIEW: 0, NEAR_ZONE: 1, OVERSOLD_REVIEW: 2, WATCH: 3, OVERBOUGHT_WAIT: 4, STALE: 5, NEEDS_DATA: 6 }
    const priority: Record<Priority, number> = { HIGH: 0, NORMAL: 1, LOW: 2 }
    return rows.filter(row => {
      if (q && !`${row.symbol} ${row.latest.account} ${row.latest.reason}`.toUpperCase().includes(q)) return false
      if (intentFilter !== 'ALL' && row.assignment.intent !== intentFilter) return false
      if (statusFilter !== 'ALL' && row.intel.status !== statusFilter) return false
      if (exitFilter !== 'ALL' && row.latest.exitType !== exitFilter) return false
      return true
    }).sort((a, b) => priority[a.assignment.priority] - priority[b.assignment.priority]
      || rank[a.intel.status] - rank[b.intel.status]
      || b.latest.date.localeCompare(a.latest.date))
  }, [rows, search, intentFilter, statusFilter, exitFilter])

  const saveAssignments = async (next: Record<string, Assignment>) => {
    setAssignments(next)
    const response = await fetch('/api/v2/ui/prefs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: PREF_KEY, value: next }),
    })
    const payload = root(await response.json().catch(() => ({})))
    if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed')
    void refetchPrefs?.()
  }

  const refreshAll = () => {
    setToast('Refreshing sale ledger and cached intelligence…')
    void refetchHistory?.(); void refetchJournal?.(); void refetchCards?.(); void refetchAdvisory?.(); void refetchAlerts?.(); void refetchRegime?.()
    setIntelReload(v => v + 1)
    window.setTimeout(() => setToast(''), 3500)
  }

  const counts = {
    monitored: rows.filter(r => r.assignment.monitor).length,
    ready: rows.filter(r => r.intel.status === 'READY_FOR_REVIEW').length,
    near: rows.filter(r => r.intel.status === 'NEAR_ZONE').length,
    oversold: rows.filter(r => r.intel.rsiZone === 'OVERSOLD').length,
    stale: rows.filter(r => ['STALE', 'NEEDS_DATA'].includes(r.intel.status)).length,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 10, color: MUTED, marginBottom: 4 }}><Link to="/portfolio" style={{ color: BLUE, textDecoration: 'none' }}>Portfolio</Link> / Re-Entry</div>
          <div style={{ fontSize: 24, fontWeight: 900 }}>Re-Entry Intelligence</div>
          <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>
            Last 12 months of exited positions · deterministic pullback review · persistent classifications · advisory alerts
          </div>
          <div style={{ fontSize: 9.5, color: /off|defensive|disrupt/i.test(regime) ? AMBER : MUTED, marginTop: 5 }}>
            MARKET REGIME {regime.toUpperCase()} · cached technicals show their age · no order or broker authority
          </div>
        </div>
        <button onClick={refreshAll} style={button(false)}>{intelLoading ? 'LOADING TECHNICALS…' : 'REFRESH CACHED INTELLIGENCE'}</button>
      </div>

      <div style={{ ...panel, display: 'grid', gridTemplateColumns: 'repeat(5, minmax(100px, 1fr))', gap: 1, overflow: 'hidden' }}>
        {[
          ['Exited symbols', rows.length, BLUE], ['Monitored', counts.monitored, PURPLE], ['Ready for review', counts.ready, GREEN],
          ['Near pullback', counts.near, AMBER], ['Oversold / stale', `${counts.oversold} / ${counts.stale}`, RED],
        ].map(([label, value, color]) => (
          <div key={String(label)} style={{ padding: '10px 12px', background: 'var(--bg2)' }}>
            <div style={{ fontSize: 8.5, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 900, color: String(color), marginTop: 2 }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ ...panel, padding: 9, display: 'grid', gridTemplateColumns: 'minmax(180px, 1fr) repeat(3, minmax(130px, 180px))', gap: 8 }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol, account, exit reason…" style={input} />
        <select value={intentFilter} onChange={e => setIntentFilter(e.target.value)} style={input}>
          <option value="ALL">All position types</option>{INTENTS.map(v => <option key={v}>{v}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={input}>
          <option value="ALL">All re-entry states</option>{STATUSES.map(v => <option key={v}>{v.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={exitFilter} onChange={e => setExitFilter(e.target.value)} style={input}>
          <option value="ALL">Stopped + sold</option><option value="STOPPED">Stopped out</option><option value="SOLD">Traded out</option>
        </select>
      </div>

      {toast && <div style={{ fontSize: 10.5, color: BLUE }}>{toast}</div>}
      {historyLoading && !historyRaw && <div style={{ ...panel, padding: 24, color: MUTED }}>Loading the last year of exits…</div>}
      {historyError && !historyRaw && <div style={{ ...panel, padding: 24, color: RED }}>Exit history unavailable: {historyError}</div>}

      <div style={{ ...panel, overflowX: 'auto' }}>
        <div style={{ minWidth: 1180 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '70px 112px 105px 90px 92px 118px 150px 138px 76px 122px', gap: 8, padding: '7px 10px', borderBottom: '1px solid var(--border)', fontSize: 8.5, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            <span>Symbol</span><span>Latest exit</span><span>Classification</span><span>Last / exit</span><span>RSI</span><span>Pullback distance</span><span>Candidate entry</span><span>State</span><span>Alerts</span><span>Actions</span>
          </div>
          {shown.length === 0 ? (
            <div style={{ padding: 24, color: MUTED, textAlign: 'center' }}>No exited positions match these filters.</div>
          ) : shown.map(row => {
            const c = statusColor(row.intel.status)
            const ic = intentColor(row.assignment.intent)
            const open = expanded === row.symbol
            return (
              <div key={row.symbol} style={{ borderBottom: '1px solid var(--border)' }}>
                <div onClick={() => setExpanded(open ? null : row.symbol)} style={{ display: 'grid', gridTemplateColumns: '70px 112px 105px 90px 92px 118px 150px 138px 76px 122px', gap: 8, padding: '9px 10px', alignItems: 'center', cursor: 'pointer', background: open ? 'rgba(96,165,250,.05)' : 'transparent' }}>
                  <div><div style={{ fontSize: 13, fontWeight: 900 }}>{row.symbol}</div><div style={{ fontSize: 8.5, color: MUTED }}>{row.events.length} exit{row.events.length === 1 ? '' : 's'}</div></div>
                  <div><div style={{ fontSize: 10, fontWeight: 800, color: row.latest.exitType === 'STOPPED' ? RED : AMBER }}>{row.latest.exitType}</div><div style={{ fontSize: 9, color: MUTED }}>{row.latest.date || 'date —'}</div></div>
                  <div><span style={{ fontSize: 9, fontWeight: 850, color: ic, border: `1px solid ${ic}55`, padding: '2px 6px', borderRadius: 3 }}>{row.assignment.intent}</span><div style={{ fontSize: 8, color: MUTED, marginTop: 3 }}>{row.assignment.priority}</div></div>
                  <div><div style={{ fontSize: 11, fontWeight: 800 }}>{money(row.intel.last)}</div><div style={{ fontSize: 9, color: row.moveSinceExit === null ? MUTED : row.moveSinceExit >= 0 ? GREEN : RED }}>{row.moveSinceExit === null ? 'exit —' : `${row.moveSinceExit >= 0 ? '+' : ''}${row.moveSinceExit.toFixed(1)}% vs exit`}</div></div>
                  <div><div style={{ fontSize: 14, fontWeight: 900, color: row.intel.rsiZone === 'OVERSOLD' ? GREEN : row.intel.rsiZone === 'OVERBOUGHT' ? RED : 'var(--text1)' }}>{row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)}</div><div style={{ fontSize: 8.5, color: MUTED }}>{row.intel.rsiZone}</div></div>
                  <div><div style={{ fontSize: 11, fontWeight: 850, color: row.intel.distancePct === 0 ? GREEN : row.intel.distancePct !== null && row.intel.distancePct <= 3 ? AMBER : 'var(--text1)' }}>{row.intel.distancePct === null ? '—' : row.intel.distancePct === 0 ? 'IN ZONE' : `${Math.abs(row.intel.distancePct).toFixed(1)}% ${row.intel.distancePct > 0 ? 'above' : 'below'}`}</div><div style={{ fontSize: 8.5, color: MUTED }}>to candidate zone</div></div>
                  <div><div style={{ fontSize: 11, fontWeight: 800 }}>{row.intel.entryLow === null ? '—' : row.intel.entryLow === row.intel.entryHigh ? money(row.intel.entryLow) : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}</div><div style={{ fontSize: 8.5, color: MUTED }}>stop {money(row.intel.stop)} · target {money(row.intel.target)}</div></div>
                  <div><span style={{ fontSize: 9, fontWeight: 900, color: c, border: `1px solid ${c}55`, borderRadius: 3, padding: '2px 6px' }}>{row.intel.status.replace(/_/g, ' ')}</span><div style={{ fontSize: 8, color: MUTED, marginTop: 3 }}>{ageLabel(row.intel.asOf)}</div></div>
                  <div><div style={{ fontSize: 12, fontWeight: 900, color: alertCount(row.symbol) ? AMBER : MUTED }}>🔔 {alertCount(row.symbol)}</div><div style={{ fontSize: 8, color: row.assignment.monitor ? GREEN : MUTED }}>{row.assignment.monitor ? 'MONITOR' : 'PAUSED'}</div></div>
                  <div style={{ display: 'flex', gap: 5 }} onClick={e => e.stopPropagation()}><button onClick={() => setEditSymbol(row.symbol)} style={button(false)}>ASSIGN</button><button onClick={() => setAlertSymbol(row.symbol)} style={button(alertCount(row.symbol) > 0)}>ALERT</button></div>
                </div>
                {open && (
                  <div style={{ padding: '9px 12px 12px 90px', background: 'rgba(2,6,23,.26)', display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(240px, .7fr)', gap: 18 }}>
                    <div>
                      <div style={{ fontSize: 9, fontWeight: 850, color: MUTED, letterSpacing: '.06em', marginBottom: 5 }}>EXIT HISTORY — 12 MONTHS</div>
                      {row.events.map(event => <div key={event.id} style={{ display: 'grid', gridTemplateColumns: '82px 70px 85px 1fr', gap: 8, fontSize: 10, padding: '3px 0' }}><span style={{ color: MUTED }}>{event.date}</span><span style={{ color: event.exitType === 'STOPPED' ? RED : AMBER }}>{event.exitType}</span><span>{money(event.sellPrice)}</span><span style={{ color: MUTED }}>{event.reason}</span></div>)}
                    </div>
                    <div>
                      <div style={{ fontSize: 9, fontWeight: 850, color: MUTED, letterSpacing: '.06em', marginBottom: 5 }}>RE-ENTRY REVIEW</div>
                      <div style={{ fontSize: 10, lineHeight: 1.55, color: 'var(--text2)' }}>
                        <b>Classification:</b> {row.assignment.intent} · {row.assignment.priority}<br />
                        <b>Data:</b> {row.intel.dataNote} · {ageLabel(row.intel.asOf)}<br />
                        <b>Notes:</b> {row.assignment.notes || 'No operator thesis saved.'}<br />
                        <b>Guardrail:</b> state is advisory; review fresh market, event, risk, and account facts before any proposal.
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div style={{ fontSize: 9.5, color: MUTED, lineHeight: 1.5 }}>
        READY FOR REVIEW is not a buy order. It requires current cached RSI, an active candidate entry zone, and price/RSI agreement. Alerts are independent Watch rules and may notify before the combined re-entry state is ready. No broker call, proposal, approval, or 2FA is created here.
      </div>

      {editSymbol && (() => {
        const base = assignments[editSymbol] ?? defaultAssignment()
        return <AssignmentModal key={editSymbol} symbol={editSymbol} initial={base} onClose={() => setEditSymbol(null)} onSave={async value => {
          try { await saveAssignments({ ...assignments, [editSymbol]: value }); setToast(`${editSymbol} classification saved persistently`); setEditSymbol(null) }
          catch (e: any) { setToast(`Save failed: ${e?.message || 'unknown error'}`) }
        }} />
      })()}

      {alertSymbol && (() => {
        const row = rows.find(r => r.symbol === alertSymbol)
        return row ? <AlertModal key={alertSymbol} symbol={alertSymbol} intel={row.intel} intent={row.assignment.intent} onClose={() => setAlertSymbol(null)} onArmed={async summary => {
          const now = new Date().toISOString()
          const next = { ...assignments, [alertSymbol]: { ...(assignments[alertSymbol] ?? defaultAssignment()), monitor: true, alert_summary: summary, updated_at: now } }
          try { await saveAssignments(next) } catch { /* alert itself is already server-persistent */ }
          void refetchAlerts?.(); setToast(`${alertSymbol} alerts armed — ${summary}`); setAlertSymbol(null)
        }} /> : null
      })()}
    </div>
  )
}

function AssignmentModal({ symbol, initial, onClose, onSave }: { symbol: string; initial: Assignment; onClose: () => void; onSave: (value: Assignment) => Promise<void> }) {
  const [value, setValue] = useState<Assignment>({ ...initial })
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<Assignment>) => setValue(v => ({ ...v, ...patch }))
  return <Modal title={`${symbol} · Classification`} subtitle="One persistent modal covers core, compounding, dividend, short, and swing intent. Material changes are operator-entered; no model assigns them automatically." onClose={onClose}>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      <label style={{ fontSize: 10, color: MUTED }}>POSITION TYPE<select value={value.intent} onChange={e => set({ intent: e.target.value as Intent })} style={{ ...input, marginTop: 4 }}>{INTENTS.map(v => <option key={v}>{v}</option>)}</select></label>
      <label style={{ fontSize: 10, color: MUTED }}>PRIORITY<select value={value.priority} onChange={e => set({ priority: e.target.value as Priority })} style={{ ...input, marginTop: 4 }}>{PRIORITIES.map(v => <option key={v}>{v}</option>)}</select></label>
      <label style={{ fontSize: 10, color: MUTED }}>TARGET ACCOUNT<input value={value.account} onChange={e => set({ account: e.target.value })} placeholder="optional account" style={{ ...input, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: MUTED }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={value.target_weight_pct ?? ''} onChange={e => set({ target_weight_pct: e.target.value === '' ? null : Number(e.target.value) })} placeholder="optional" style={{ ...input, marginTop: 4 }} /></label>
    </div>
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '14px 0', fontSize: 11 }}><input type="checkbox" checked={value.monitor} onChange={e => set({ monitor: e.target.checked })} /> Keep this symbol in the active re-entry monitor</label>
    <label style={{ fontSize: 10, color: MUTED }}>OPERATOR THESIS / WHAT MUST BE TRUE<textarea value={value.notes} onChange={e => set({ notes: e.target.value })} rows={5} placeholder="Why re-enter, what would invalidate the thesis, and what evidence is required?" style={{ ...input, marginTop: 4, resize: 'vertical' }} /></label>
    <div style={{ marginTop: 10, padding: 9, border: '1px solid var(--border)', borderRadius: 5, fontSize: 9.5, color: MUTED }}>
      CORE = strategic long-duration holding · COMPOUNDING = repeated/add-on accumulation plan · DIVIDEND = income mandate · SHORT = bearish re-entry review · SWING = bounded tactical holding period.
    </div>
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); void onSave({ ...value, updated_at: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...button(true), color: GREEN, borderColor: GREEN }}>{busy ? 'SAVING…' : 'SAVE CLASSIFICATION'}</button></div>
  </Modal>
}

function AlertModal({ symbol, intel, intent, onClose, onArmed }: { symbol: string; intel: Intel; intent: Intent; onClose: () => void; onArmed: (summary: string) => Promise<void> }) {
  const short = intent === 'SHORT'
  const [priceEnabled, setPriceEnabled] = useState(intel.entryHigh !== null)
  const [priceCondition, setPriceCondition] = useState(short ? 'price_cross_above' : 'price_cross_below')
  const [priceThreshold, setPriceThreshold] = useState(String(short ? (intel.entryLow ?? intel.entryHigh ?? intel.last ?? '') : (intel.entryHigh ?? intel.entryLow ?? intel.last ?? '')))
  const [rsiEnabled, setRsiEnabled] = useState(true)
  const [rsiCondition, setRsiCondition] = useState(short ? 'rsi_above' : 'rsi_below')
  const [rsiThreshold, setRsiThreshold] = useState(short ? '65' : '40')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const arm = async () => {
    const rules = [
      ...(priceEnabled ? [{ condition_type: priceCondition, threshold: Number(priceThreshold) }] : []),
      ...(rsiEnabled ? [{ condition_type: rsiCondition, threshold: Number(rsiThreshold) }] : []),
    ].filter(rule => Number.isFinite(rule.threshold))
    if (!rules.length) { setError('Select at least one valid alert rule.'); return }
    setBusy(true); setError('')
    try {
      for (const rule of rules) {
        const response = await fetch('/api/v2/watch/alerts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, ...rule }) })
        const payload = root(await response.json().catch(() => ({})))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `${rule.condition_type} failed`)
      }
      await onArmed(rules.map(r => `${r.condition_type} ${r.threshold}`).join(' + '))
    } catch (e: any) { setError(e?.message || 'Alert request failed'); setBusy(false) }
  }
  return <Modal title={`${symbol} · Re-Entry Alerts`} subtitle="Uses the existing server-side Watch alert evaluator. Rules are persistent, deduped by that service, and delivered through its configured sinks." onClose={onClose}>
    <div style={{ ...panel, padding: 12, marginBottom: 12 }}>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, fontWeight: 800 }}><input type="checkbox" checked={priceEnabled} onChange={e => setPriceEnabled(e.target.checked)} /> Price reaches candidate re-entry zone</label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 9, opacity: priceEnabled ? 1 : .45 }}>
        <select disabled={!priceEnabled} value={priceCondition} onChange={e => setPriceCondition(e.target.value)} style={input}><option value="price_cross_below">Price crosses below</option><option value="price_cross_above">Price crosses above</option></select>
        <input disabled={!priceEnabled} type="number" step="0.01" value={priceThreshold} onChange={e => setPriceThreshold(e.target.value)} style={input} />
      </div>
    </div>
    <div style={{ ...panel, padding: 12 }}>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, fontWeight: 800 }}><input type="checkbox" checked={rsiEnabled} onChange={e => setRsiEnabled(e.target.checked)} /> RSI reaches review threshold</label>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 9, opacity: rsiEnabled ? 1 : .45 }}>
        <select disabled={!rsiEnabled} value={rsiCondition} onChange={e => setRsiCondition(e.target.value)} style={input}><option value="rsi_below">RSI crosses below</option><option value="rsi_above">RSI crosses above</option></select>
        <input disabled={!rsiEnabled} type="number" min="0" max="100" step="1" value={rsiThreshold} onChange={e => setRsiThreshold(e.target.value)} style={input} />
      </div>
    </div>
    <div style={{ fontSize: 9.5, color: MUTED, lineHeight: 1.5, marginTop: 10 }}>
      The two rules notify independently. A notification is not a combined re-entry approval: the page still requires fresh data, entry-zone proximity, RSI context, and operator review. For shorts, defaults invert to resistance/overbought conditions.
    </div>
    {error && <div style={{ color: RED, fontSize: 10.5, marginTop: 9 }}>{error}</div>}
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy} onClick={() => void arm()} style={{ ...button(true), color: AMBER, borderColor: AMBER }}>{busy ? 'ARMING…' : 'ARM ALERTS'}</button></div>
  </Modal>
}
