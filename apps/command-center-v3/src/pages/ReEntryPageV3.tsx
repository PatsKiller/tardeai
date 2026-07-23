import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'

const PREF_KEY = 'portfolio.reentry.assignments.v1'
const PRIORITIES = ['HIGH', 'NORMAL', 'LOW'] as const
const FLAG_LABELS = ['CORE', 'COMPOUNDING', 'DIVIDEND', 'SHORT', 'SWING'] as const
const REENTRY_STATES = [
  'READY_TO_REVIEW', 'NEAR_ENTRY', 'WAIT_FOR_PULLBACK', 'OVERSOLD_REVIEW',
  'OVERBOUGHT_WAIT', 'SHORT_PLAN_REQUIRED', 'CURRENTLY_HELD', 'STALE_DATA',
  'NO_CURRENT_COVERAGE',
] as const

const C = {
  green: BB.green, red: BB.red, amber: BB.amber, blue: BB.blue,
  purple: BB.amberAlt, muted: BB.text3,
}
const panel: React.CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
}
const field: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px',
  borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)',
  color: 'var(--text0)',
}
const button = (active = false): React.CSSProperties => ({
  fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5,
  cursor: 'pointer', border: `1px solid ${active ? C.blue : 'var(--border)'}`,
  background: active ? BB.blueDim : 'var(--bg2)', color: active ? C.blue : 'var(--text2)',
})

type Priority = typeof PRIORITIES[number]
type ReEntryState = typeof REENTRY_STATES[number]
type Flags = {
  core: boolean
  compounding: boolean
  dividend: boolean
  short: boolean
  swing: boolean
}
type Assignment = {
  flags: Flags
  priority: Priority
  monitor: boolean
  account: string
  target_weight_pct: number | null
  notes: string
  updated_at: string
  alert_summary?: string
}
type ExitEvent = {
  key: string
  symbol: string
  date: string
  account: string
  shares: number | null
  exitPrice: number | null
  proceeds: number | null
  pnl: number | null
  exitType: 'STOPPED' | 'SOLD' | 'UNCLASSIFIED'
  reason: string
  source: string
  sourceStatus: string
}
type Intel = {
  last: number | null
  rsi: number | null
  rsiZone: 'OVERSOLD' | 'NEUTRAL' | 'OVERBOUGHT' | 'UNAVAILABLE'
  entryLow: number | null
  entryHigh: number | null
  stop: number | null
  target: number | null
  distancePct: number | null
  asOf: string | null
  state: ReEntryState
  action: string
  why: string
  side: 'LONG' | 'SHORT' | 'UNAVAILABLE'
  dataNote: string
}

function unwrap(value: any): any {
  let result = value
  for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) {
    result = result.data
  }
  return result ?? {}
}
function arrayFrom(value: any, keys: string[]): any[] {
  const payload = unwrap(value)
  for (const key of keys) if (Array.isArray(payload?.[key])) return payload[key]
  return Array.isArray(payload) ? payload : []
}
function finite(...values: any[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return null
}
function text(...values: any[]): string {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const result = String(value).trim()
    if (result) return result
  }
  return ''
}
function readPath(object: any, path: string): any {
  return path.split('.').reduce((value: any, key) => value?.[key], object)
}
function numberFrom(objects: any[], paths: string[]): number | null {
  for (const object of objects) {
    for (const path of paths) {
      const number = finite(readPath(object, path))
      if (number !== null) return number
    }
  }
  return null
}
function textFrom(objects: any[], paths: string[]): string | null {
  for (const object of objects) {
    for (const path of paths) {
      const result = text(readPath(object, path))
      if (result) return result
    }
  }
  return null
}
function isoDay(value: any): string {
  const raw = text(value)
  if (!raw) return ''
  const date = new Date(raw)
  return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : raw.slice(0, 10)
}
function money(value: number | null): string {
  return value === null ? '—' : fmt$(value, 2)
}
function ageLabel(value: string | null): string {
  if (!value) return 'timestamp unavailable'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return value.slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - time) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function defaultAssignment(): Assignment {
  return {
    flags: { core: false, compounding: false, dividend: false, short: false, swing: false },
    priority: 'NORMAL', monitor: true, account: '', target_weight_pct: null,
    notes: '', updated_at: '',
  }
}
function normalizeAssignment(value: any): Assignment {
  const legacy = text(value?.intent).toUpperCase()
  return {
    flags: {
      core: Boolean(value?.flags?.core ?? value?.core ?? value?.is_core ?? legacy === 'CORE'),
      compounding: Boolean(value?.flags?.compounding ?? value?.compounding ?? legacy === 'COMPOUNDING'),
      dividend: Boolean(value?.flags?.dividend ?? value?.dividend ?? legacy === 'DIVIDEND'),
      short: Boolean(value?.flags?.short ?? value?.short ?? legacy === 'SHORT'),
      swing: Boolean(value?.flags?.swing ?? value?.swing ?? legacy === 'SWING'),
    },
    priority: PRIORITIES.includes(value?.priority) ? value.priority : 'NORMAL',
    monitor: value?.monitor !== false,
    account: text(value?.account),
    target_weight_pct: finite(value?.target_weight_pct),
    notes: text(value?.notes),
    updated_at: text(value?.updated_at),
    alert_summary: text(value?.alert_summary) || undefined,
  }
}
function flagNames(value: Assignment): string[] {
  return FLAG_LABELS.filter(label => value.flags[label.toLowerCase() as keyof Flags])
}
function identity(event: ExitEvent): string {
  const detailed = [event.symbol, event.account, event.date, event.shares, event.exitPrice, event.proceeds]
  const hasDetail = Boolean(event.date && event.account && detailed.slice(3).some(v => v !== null && v !== ''))
  return hasDetail ? detailed.join('|') : event.key
}
function normalizeExit(row: any, index: number, source: string): ExitEvent | null {
  const symbol = text(row.symbol, row.sold_symbol, row.ticker, row.security_symbol).toUpperCase()
  if (!/^[A-Z][A-Z0-9.\-]{0,11}$/.test(symbol)) return null
  const date = isoDay(
    row.sold_at ?? row.stopped_at ?? row.triggered_at ?? row.close_date ??
    row.trade_date ?? row.closed_at ?? row.executed_at ?? row.transaction_date ?? row.date,
  )
  const sharesRaw = finite(row.shares_sold, row.shares, row.quantity, row.qty)
  const shares = sharesRaw === null ? null : Math.abs(sharesRaw)
  const proceedsRaw = finite(row.proceeds_usd, row.net_proceeds_usd, row.proceeds, row.amount)
  const proceeds = proceedsRaw === null ? null : Math.abs(proceedsRaw)
  let exitPrice = finite(
    row.sell_price, row.exit_price, row.stop_fill_price, row.price,
    row.avg_price, row.execution_price, row.average_price,
  )
  if (exitPrice === null && proceeds !== null && shares !== null && shares > 0) {
    exitPrice = proceeds / shares
  }
  const metadata = typeof row.metadata === 'object' ? row.metadata : {}
  const reason = text(
    row.exit_reason, row.sell_reason, row.reason, row.stop_reason, row.dismiss_reason,
    row.strategy, row.classification, row.description, metadata?.description,
    row.operator_status, row.event_status, row.status,
  )
  const classification = `${reason} ${text(row.order_type, row.transaction_type, row.action, row.type)} ${source}`
  const exitType: ExitEvent['exitType'] = /stop|protective|trailing|risk exit|stop-loss/i.test(classification)
    ? 'STOPPED'
    : /sell|sold|closed|exit|journal/i.test(classification) ? 'SOLD' : 'UNCLASSIFIED'
  const stableKey = text(
    row.trade_key, row.event_key, row.dedupe_key, row.id, row.event_id,
    row.matched_event_id, row.transaction_id,
    `${source}:${symbol}:${date}:${shares ?? ''}:${exitPrice ?? ''}:${proceeds ?? index}`,
  )
  return {
    key: stableKey,
    symbol,
    date,
    account: text(row.account, row.account_key, row.account_name, row.broker_account),
    shares,
    exitPrice,
    proceeds,
    pnl: finite(row.pnl, row.realized_pnl, row.total_pnl),
    exitType,
    reason: reason || 'Exit reason not classified in source data',
    source: text(row.source, row.source_system, row.import_source, source),
    sourceStatus: text(row.event_status, row.completion_status, row.operator_status, row.status),
  }
}
function familyRows(packet: any): any[] {
  if (Array.isArray(packet?.families)) return packet.families
  if (packet?.families && typeof packet.families === 'object') {
    return Object.entries(packet.families).map(([family, value]: [string, any]) => ({ family, ...(value ?? {}) }))
  }
  if (Array.isArray(packet?.family_results)) return packet.family_results
  if (packet?.family_results && typeof packet.family_results === 'object') {
    return Object.entries(packet.family_results).map(([family, value]: [string, any]) => ({ family, ...(value ?? {}) }))
  }
  return []
}
function deriveIntel(
  watch: any, card: any, advisory: any, stopRow: any,
  assignment: Assignment, currentlyHeld: boolean,
): Intel {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? stopRow?.decision_packet ?? {}
  const selected = packet?.selected_family?.mechanics ?? packet?.mechanics ?? packet?.current_mechanics ?? stopRow?.reentry_plan ?? stopRow?.mechanics ?? {}
  const shortMechanics = assignment.flags.short
    ? familyRows(packet).find(row => /short|bear|breakdown/i.test(text(row.family, row.name, row.direction, row.strategy)))?.mechanics
      ?? watch?.short_plan ?? card?.short_plan ?? stopRow?.short_plan ?? null
    : null
  const marketObjects = [stopRow ?? {}, advisory ?? {}, watch ?? {}, card ?? {}, packet ?? {}]
  const planObjects = assignment.flags.short
    ? [shortMechanics ?? {}]
    : [stopRow ?? {}, watch ?? {}, card ?? {}, packet ?? {}, selected ?? {}]
  const last = numberFrom(marketObjects, [
    'last_price', 'price', 'current_price', 'quote_price', 'quote.last', 'quote.price', 'market.last',
  ])
  const rsi = numberFrom(marketObjects, [
    'rsi', 'rsi_14', 'current_rsi', 'technical.rsi', 'technicals.rsi',
    'technicals.rsi_14', 'indicators.rsi', 'indicators.rsi_14',
  ])
  let entryLow = numberFrom(planObjects, [
    'reentry_low', 'reentry_zone_low', 'entry_zone_low', 'plan_entry_low',
    'entry_low', 'mechanics.entry_low', 'entry.zone_low',
  ])
  let entryHigh = numberFrom(planObjects, [
    'reentry_high', 'reentry_zone_high', 'entry_zone_high', 'plan_entry_high',
    'entry_high', 'mechanics.entry_high', 'entry.zone_high',
  ])
  const singleEntry = numberFrom(planObjects, [
    'reentry_price', 'entry_limit', 'plan_entry', 'entry_price', 'mechanics.entry', 'entry.limit',
  ])
  if (entryLow === null) entryLow = singleEntry
  if (entryHigh === null) entryHigh = singleEntry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) {
    [entryLow, entryHigh] = [entryHigh, entryLow]
  }
  const stop = numberFrom(planObjects, [
    'reentry_stop', 'entry_stop', 'plan_stop', 'stop_price', 'mechanics.stop',
  ])
  const target = numberFrom(planObjects, [
    'reentry_target', 'entry_target', 'plan_target', 'target_price', 'mechanics.target',
  ])
  const asOf = textFrom(marketObjects, [
    'last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote_time',
    'quote.as_of', 'technicals.as_of',
  ])
  const asOfTime = asOf ? new Date(asOf).getTime() : NaN
  const stale = !Number.isFinite(asOfTime) || Date.now() - asOfTime > 96 * 36e5
  let distancePct: number | null = null
  if (last !== null && last > 0 && entryLow !== null && entryHigh !== null) {
    if (last > entryHigh) distancePct = ((last - entryHigh) / entryHigh) * 100
    else if (last < entryLow) distancePct = -((entryLow - last) / entryLow) * 100
    else distancePct = 0
  }
  const rsiZone: Intel['rsiZone'] = rsi === null
    ? 'UNAVAILABLE' : rsi <= 30 ? 'OVERSOLD' : rsi >= 70 ? 'OVERBOUGHT' : 'NEUTRAL'
  let state: ReEntryState = 'WAIT_FOR_PULLBACK'
  let action = 'Keep monitoring'
  let why = 'Price and momentum have not reached review conditions.'
  if (currentlyHeld) {
    state = 'CURRENTLY_HELD'
    action = 'Review as an existing holding'
    why = 'The symbol is currently held, so it is no longer a clean re-entry-only candidate.'
  } else if (last === null || rsi === null) {
    state = 'NO_CURRENT_COVERAGE'
    action = 'Build or refresh current technical coverage'
    why = 'Current price and RSI are required.'
  } else if (stale) {
    state = 'STALE_DATA'
    action = 'Refresh market and technical data'
    why = `The technical packet is ${ageLabel(asOf)}.`
  } else if (assignment.flags.short && !shortMechanics) {
    state = 'SHORT_PLAN_REQUIRED'
    action = 'Build and review a bearish setup'
    why = 'SHORT is flagged but no same-side bearish entry mechanics exist.'
  } else if (entryLow === null || entryHigh === null) {
    state = 'NO_CURRENT_COVERAGE'
    action = 'Build a candidate entry zone'
    why = 'Current price and RSI exist but no entry range is available.'
  } else if (assignment.flags.short && distancePct === 0 && rsi >= 60) {
    state = 'READY_TO_REVIEW'
    action = 'Review short entry now'
    why = 'Price is in the bearish zone and RSI supports a short-side review.'
  } else if (assignment.flags.short && distancePct !== null && Math.abs(distancePct) <= 3) {
    state = 'NEAR_ENTRY'
    action = 'Prepare short review'
    why = `Price is ${Math.abs(distancePct).toFixed(1)}% from the bearish zone.`
  } else if (!assignment.flags.short && distancePct === 0 && rsi <= 45) {
    state = 'READY_TO_REVIEW'
    action = 'Review long re-entry now'
    why = 'Price is in the entry zone and RSI is not extended.'
  } else if (!assignment.flags.short && distancePct !== null && distancePct >= 0 && distancePct <= 3) {
    state = 'NEAR_ENTRY'
    action = 'Prepare a re-entry review'
    why = `Price is ${distancePct.toFixed(1)}% above the entry zone.`
  } else if (!assignment.flags.short && rsi <= 30) {
    state = 'OVERSOLD_REVIEW'
    action = 'Review for stabilization'
    why = 'RSI is oversold; confirmation is still required.'
  } else if (!assignment.flags.short && rsi >= 70) {
    state = 'OVERBOUGHT_WAIT'
    action = 'Wait for a pullback'
    why = 'RSI is overbought and extended.'
  }
  return {
    last, rsi, rsiZone, entryLow, entryHigh, stop, target, distancePct, asOf,
    state, action, why,
    side: assignment.flags.short ? (shortMechanics ? 'SHORT' : 'UNAVAILABLE') : 'LONG',
    dataNote: text(
      stopRow?.data_quality_state, watch?.data_quality_state, card?.data_quality_state,
      advisory?.note, packet?.current_validity?.state, 'cached Trade AI intelligence',
    ),
  }
}
function stateColor(state: ReEntryState): string {
  if (state === 'READY_TO_REVIEW') return C.green
  if (state === 'NEAR_ENTRY' || state === 'OVERSOLD_REVIEW') return C.amber
  if (state === 'OVERBOUGHT_WAIT' || state === 'SHORT_PLAN_REQUIRED') return C.red
  if (state === 'CURRENTLY_HELD') return C.purple
  if (state === 'WAIT_FOR_PULLBACK') return C.blue
  return C.muted
}

function Modal({
  title, subtitle, onClose, children,
}: {
  title: string
  subtitle: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      role="dialog" aria-modal="true" onMouseDown={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(2,6,23,.78)', display: 'grid', placeItems: 'center', padding: 18 }}
    >
      <div
        onMouseDown={event => event.stopPropagation()}
        style={{ ...panel, width: 'min(680px,96vw)', maxHeight: '92vh', overflowY: 'auto', padding: 16 }}
      >
        <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 900 }}>{title}</div>
            <div style={{ fontSize: 10.5, color: C.muted }}>{subtitle}</div>
          </div>
          <button onClick={onClose} style={button(false)}>CLOSE</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export default function ReEntryPageV3() {
  const from = useMemo(() => {
    const date = new Date()
    date.setUTCFullYear(date.getUTCFullYear() - 1)
    return date.toISOString().slice(0, 10)
  }, [])
  const journal = useApi<any>('/api/v2/journal', 120_000)
  const byTicker = useApi<any>(`/api/v2/journal/by-ticker?from=${from}`, 120_000)
  const history = useApi<any>('/api/v2/redeploy/history?days=365', 120_000)
  const book = useApi<any>('/api/v2/redeploy/book?limit=1000&include_dismissed=1', 120_000)
  const stopped = useApi<any>('/api/v2/stops/reentry-watch?days=365', 120_000)
  const cards = useApi<any>('/api/v2/symbol-cards', 300_000)
  const advisory = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)
  const holdings = useApi<any>('/api/v2/portfolio/holdings', 120_000)
  const prefs = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(PREF_KEY)}`, 0)
  const alerts = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const regimeResponse = useApi<any>('/api/v2/risk-regime/latest', 300_000)

  const [assignments, setAssignments] = useState<Record<string, Assignment>>({})
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [flagFilter, setFlagFilter] = useState('ALL')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [exitFilter, setExitFilter] = useState('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editSymbol, setEditSymbol] = useState<string | null>(null)
  const [alertSymbol, setAlertSymbol] = useState<string | null>(null)
  const [intelReload, setIntelReload] = useState(0)
  const [intelLoading, setIntelLoading] = useState(false)
  const [toast, setToast] = useState('')

  useEffect(() => {
    const value = unwrap(prefs.data)?.value
    if (!value || typeof value !== 'object' || Array.isArray(value)) return
    const next: Record<string, Assignment> = {}
    Object.entries(value).forEach(([symbol, assignment]) => {
      next[symbol.toUpperCase()] = normalizeAssignment(assignment)
    })
    setAssignments(next)
  }, [prefs.data])

  const sourceRows = useMemo(() => {
    const journalRows = arrayFrom(journal.data, ['trades'])
      .filter(row => !isoDay(row.close_date ?? row.closed_at) || isoDay(row.close_date ?? row.closed_at) >= from)
    const historyRows = arrayFrom(history.data, ['rows'])
    const bookRows = arrayFrom(book.data, ['rows'])
    const stoppedRows = arrayFrom(stopped.data, ['rows', 'items', 'reentry_watch', 'watch'])
    return { journalRows, historyRows, bookRows, stoppedRows }
  }, [journal.data, history.data, book.data, stopped.data, from])

  const exits = useMemo(() => {
    const collected: ExitEvent[] = []
    const add = (rows: any[], source: string) => rows.forEach((row, index) => {
      const event = normalizeExit(row, index, source)
      if (event && (!event.date || event.date >= from)) collected.push(event)
    })
    add(sourceRows.journalRows, 'real-closed-trade-journal')
    add(sourceRows.historyRows, 'redeploy-history')
    add(sourceRows.bookRows, 'redeploy-book')
    add(sourceRows.stoppedRows, 'stops-reentry-watch')
    const merged = new Map<string, ExitEvent>()
    for (const event of collected.sort((a, b) => b.date.localeCompare(a.date))) {
      const key = identity(event)
      const previous = merged.get(key)
      if (!previous) {
        merged.set(key, event)
        continue
      }
      merged.set(key, {
        ...previous,
        exitType: previous.exitType === 'STOPPED' || event.exitType === 'STOPPED'
          ? 'STOPPED' : previous.exitType === 'SOLD' || event.exitType === 'SOLD' ? 'SOLD' : 'UNCLASSIFIED',
        shares: previous.shares ?? event.shares,
        exitPrice: previous.exitPrice ?? event.exitPrice,
        proceeds: previous.proceeds ?? event.proceeds,
        pnl: previous.pnl ?? event.pnl,
        reason: previous.reason === 'Exit reason not classified in source data' ? event.reason : previous.reason,
        source: Array.from(new Set(`${previous.source},${event.source}`.split(','))).join(','),
        sourceStatus: previous.sourceStatus || event.sourceStatus,
      })
    }
    return Array.from(merged.values()).sort((a, b) => b.date.localeCompare(a.date))
  }, [sourceRows, from])

  const bySymbol = useMemo(() => {
    const map = new Map<string, ExitEvent[]>()
    for (const event of exits) map.set(event.symbol, [...(map.get(event.symbol) ?? []), event])
    const tickerRows: any[] = unwrap(byTicker.data)?.tickers ?? []
    for (const ticker of tickerRows) {
      const symbol = text(ticker.symbol).toUpperCase()
      if (!symbol || map.has(symbol)) continue
      const event = normalizeExit({
        symbol,
        close_date: ticker.last_close_date ?? ticker.last_trade_at ?? ticker.last_close,
        sell_price: ticker.last_sell_price,
        reason: 'Ticker aggregate exists but no individual journal event was returned',
        status: 'aggregate_only',
      }, 0, 'journal-by-ticker-aggregate')
      if (event && (!event.date || event.date >= from)) map.set(symbol, [event])
    }
    return Array.from(map.entries()).map(([symbol, events]) => {
      const sorted = events.slice().sort((a, b) => b.date.localeCompare(a.date))
      return { symbol, events: sorted, latest: sorted[0] }
    })
  }, [exits, byTicker.data, from])

  const stopMap = useMemo(() => {
    const map: Record<string, any> = {}
    for (const row of sourceRows.stoppedRows) {
      const symbol = text(row.symbol, row.ticker).toUpperCase()
      if (symbol) map[symbol] = row
    }
    return map
  }, [sourceRows.stoppedRows])

  const symbols = useMemo(() => bySymbol.map(row => row.symbol).sort(), [bySymbol])
  const symbolKey = symbols.join(',')
  useEffect(() => {
    if (!symbols.length) return
    let cancelled = false
    let cursor = 0
    const controller = new AbortController()
    const output: Record<string, any> = {}
    setIntelLoading(true)
    const worker = async () => {
      while (!cancelled) {
        const index = cursor++
        if (index >= Math.min(symbols.length, 300)) return
        const symbol = symbols[index]
        try {
          const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, {
            signal: controller.signal, cache: 'no-store',
          })
          const payload = unwrap(await response.json())
          output[symbol] = (payload?.items ?? [])[0] ?? null
        } catch {
          output[symbol] = null
        }
      }
    }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, () => worker())).finally(() => {
      if (!cancelled) {
        setWatchMap(previous => ({ ...previous, ...output }))
        setIntelLoading(false)
      }
    })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [symbolKey, intelReload])

  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const advisoryMap = useMemo(() => {
    const map: Record<string, any> = {}
    for (const row of unwrap(advisory.data)?.advisories ?? []) {
      const symbol = text(row.symbol).toUpperCase()
      if (symbol) map[symbol] = row
    }
    return map
  }, [advisory.data])
  const heldSymbols = useMemo(() => new Set<string>(
    (unwrap(holdings.data)?.holdings ?? [])
      .filter((holding: any) => Number(holding.shares ?? holding.quantity ?? 0) > 0)
      .map((holding: any) => text(holding.symbol).toUpperCase()),
  ), [holdings.data])
  const alertRows: any[] = unwrap(alerts.data)?.alerts ?? unwrap(alerts.data)?.items ?? []
  const alertCount = (symbol: string) => alertRows.filter(alert =>
    text(alert.symbol).toUpperCase() === symbol
    && !['disabled', 'expired', 'resolved'].includes(text(alert.status).toLowerCase()),
  ).length
  const regime = text(
    unwrap(regimeResponse.data)?.regime_label,
    unwrap(regimeResponse.data)?.label,
    'unknown',
  ).replace(/_/g, ' ')

  const rows = useMemo(() => bySymbol.map(row => {
    const assignment = assignments[row.symbol] ?? defaultAssignment()
    const intel = deriveIntel(
      watchMap[row.symbol], cardMap[row.symbol], advisoryMap[row.symbol], stopMap[row.symbol],
      assignment, heldSymbols.has(row.symbol),
    )
    const moveSinceExit = row.latest.exitPrice && intel.last
      ? ((intel.last - row.latest.exitPrice) / row.latest.exitPrice) * 100 : null
    return { ...row, assignment, intel, moveSinceExit }
  }), [bySymbol, assignments, watchMap, cardMap, advisoryMap, stopMap, heldSymbols])

  const shown = useMemo(() => {
    const query = search.trim().toUpperCase()
    const priorityRank: Record<Priority, number> = { HIGH: 0, NORMAL: 1, LOW: 2 }
    return rows.filter(row => {
      const flags = flagNames(row.assignment)
      if (query && !`${row.symbol} ${row.latest.account} ${row.latest.reason} ${flags.join(' ')}`.toUpperCase().includes(query)) return false
      if (flagFilter === 'UNCLASSIFIED' && flags.length) return false
      if (flagFilter !== 'ALL' && flagFilter !== 'UNCLASSIFIED' && !flags.includes(flagFilter)) return false
      if (stateFilter !== 'ALL' && row.intel.state !== stateFilter) return false
      if (exitFilter !== 'ALL' && row.latest.exitType !== exitFilter) return false
      return true
    }).sort((a, b) => priorityRank[a.assignment.priority] - priorityRank[b.assignment.priority]
      || b.latest.date.localeCompare(a.latest.date))
  }, [rows, search, flagFilter, stateFilter, exitFilter])

  const saveAssignments = async (next: Record<string, Assignment>) => {
    setAssignments(next)
    const response = await fetch('/api/v2/ui/prefs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: PREF_KEY, value: next }),
    })
    const payload = unwrap(await response.json().catch(() => ({})))
    if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed')
    void prefs.refetch?.()
  }
  const refreshAll = () => {
    setToast('Refreshing full journal, exit sources, and current status…')
    ;[journal, byTicker, history, book, stopped, cards, advisory, holdings, alerts, regimeResponse]
      .forEach(response => void response.refetch?.())
    setIntelReload(value => value + 1)
    window.setTimeout(() => setToast(''), 3500)
  }

  const journalTrades = sourceRows.journalRows.length
  const tickerTrades = finite(unwrap(byTicker.data)?.totals?.trades) ?? 0
  const materialSells = finite(
    unwrap(history.data)?.counts?.sells_found,
    unwrap(history.data)?.counts?.matched,
  ) ?? 0
  const expectedMinimum = Math.max(journalTrades, tickerTrades, materialSells)
  const sourceErrors = [
    journal.error ? `Real journal: ${journal.error}` : unwrap(journal.data)?.ok === false ? `Real journal: ${text(unwrap(journal.data)?.error, 'ok=false')}` : '',
    byTicker.error ? `By ticker: ${byTicker.error}` : unwrap(byTicker.data)?.ok === false ? `By ticker: ${text(unwrap(byTicker.data)?.error, 'ok=false')}` : '',
    history.error ? `Redeploy history: ${history.error}` : unwrap(history.data)?.ok === false ? `Redeploy history: ${text(unwrap(history.data)?.error, 'ok=false')}` : '',
    book.error ? `Redeploy book: ${book.error}` : unwrap(book.data)?.ok === false ? `Redeploy book: ${text(unwrap(book.data)?.error, 'ok=false')}` : '',
    stopped.error ? `Stopped-out watch: ${stopped.error}` : unwrap(stopped.data)?.ok === false ? `Stopped-out watch: ${text(unwrap(stopped.data)?.error, 'ok=false')}` : '',
  ].filter(Boolean)
  const coverageMismatch = expectedMinimum > 0 && exits.length < expectedMinimum
  const coverageColor = sourceErrors.length || coverageMismatch ? C.red : C.green
  const counts = {
    events: exits.length,
    symbols: rows.length,
    monitored: rows.filter(row => row.assignment.monitor).length,
    ready: rows.filter(row => row.intel.state === 'READY_TO_REVIEW').length,
    near: rows.filter(row => row.intel.state === 'NEAR_ENTRY').length,
    missing: rows.filter(row => ['STALE_DATA', 'NO_CURRENT_COVERAGE'].includes(row.intel.state)).length,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 10, color: C.muted }}>
            <Link to="/portfolio" style={{ color: C.blue, textDecoration: 'none' }}>Portfolio</Link> / Re-Entry
          </div>
          <div style={{ fontSize: 24, fontWeight: 900 }}>Re-Entry Intelligence</div>
          <div style={{ fontSize: 11, color: C.muted }}>
            Full real closed-trade journal · stopped-out enrichment · independent portfolio flags · current action
          </div>
          <div style={{ fontSize: 10, color: /off|defensive|disrupt/i.test(regime) ? C.amber : C.muted, marginTop: 4 }}>
            MARKET REGIME {regime.toUpperCase()} · advisory only
          </div>
        </div>
        <button onClick={refreshAll} style={button(false)}>
          {intelLoading ? 'LOADING CURRENT STATUS…' : 'REFRESH ALL SOURCES'}
        </button>
      </div>

      <div style={{ ...panel, padding: 10, borderColor: coverageColor }}>
        <div style={{ fontSize: 11, fontWeight: 900, color: coverageColor }}>
          EXIT-LEDGER COVERAGE {sourceErrors.length || coverageMismatch ? 'DEGRADED' : 'VERIFIED'}
        </div>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>
          Real closed trades {journalTrades} · By-Ticker trades {tickerTrades} · Material sells {materialSells}
          {' · '}Redeploy book {sourceRows.bookRows.length} · Stopped-out records {sourceRows.stoppedRows.length}
          {' · '}Rendered union {counts.events} events / {counts.symbols} symbols
        </div>
        {coverageMismatch && (
          <div style={{ fontSize: 10, color: C.red, marginTop: 5 }}>
            BLOCKING WARNING: source counts require at least {expectedMinimum} events, but only {counts.events} rendered. Do not treat this view as complete.
          </div>
        )}
        {sourceErrors.map(error => <div key={error} style={{ fontSize: 10, color: C.red, marginTop: 4 }}>{error}</div>)}
      </div>

      <div style={{ ...panel, display: 'grid', gridTemplateColumns: 'repeat(6,minmax(100px,1fr))', gap: 1, overflow: 'hidden' }}>
        {[
          ['Exit events', counts.events, C.blue], ['Exited symbols', counts.symbols, C.blue],
          ['Monitored', counts.monitored, C.purple], ['Ready now', counts.ready, C.green],
          ['Near entry', counts.near, C.amber], ['Missing / stale', counts.missing, C.red],
        ].map(([label, value, color]) => (
          <div key={String(label)} style={{ padding: '10px 12px', background: 'var(--bg2)' }}>
            <div style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 900, color: String(color) }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ ...panel, padding: 9, display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) repeat(3,minmax(140px,190px))', gap: 8 }}>
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, account, reason, or flag…" style={field} />
        <select value={flagFilter} onChange={event => setFlagFilter(event.target.value)} style={field}>
          <option value="ALL">All portfolio flags</option>
          {FLAG_LABELS.map(flag => <option key={flag}>{flag}</option>)}
          <option value="UNCLASSIFIED">UNCLASSIFIED</option>
        </select>
        <select value={stateFilter} onChange={event => setStateFilter(event.target.value)} style={field}>
          <option value="ALL">All current states</option>
          {REENTRY_STATES.map(state => <option key={state}>{state.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={exitFilter} onChange={event => setExitFilter(event.target.value)} style={field}>
          <option value="ALL">All exit types</option>
          <option value="STOPPED">Stopped out</option>
          <option value="SOLD">Traded out</option>
          <option value="UNCLASSIFIED">Exit type unclassified</option>
        </select>
      </div>

      {toast && <div style={{ fontSize: 10.5, color: C.blue }}>{toast}</div>}

      <div style={{ ...panel, overflowX: 'auto' }}>
        <div style={{ minWidth: 1400 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '72px 122px 225px 100px 88px 112px 150px 215px 92px 132px', gap: 8, padding: '7px 10px', borderBottom: '1px solid var(--border)', fontSize: 10, color: C.muted, textTransform: 'uppercase' }}>
            <span>Symbol</span><span>Latest exit</span><span>Current status / action</span><span>Last / exit</span>
            <span>RSI</span><span>Pullback</span><span>Candidate entry</span><span>Portfolio flags</span>
            <span>Alerts</span><span>Actions</span>
          </div>
          {!shown.length ? (
            <div style={{ padding: 24, color: C.muted, textAlign: 'center' }}>
              No exited positions match these filters. Check the coverage panel before concluding that no exits exist.
            </div>
          ) : shown.map(row => {
            const open = expanded === row.symbol
            const flags = flagNames(row.assignment)
            const tone = stateColor(row.intel.state)
            return (
              <div key={row.symbol} style={{ borderBottom: '1px solid var(--border)' }}>
                <div
                  onClick={() => setExpanded(open ? null : row.symbol)}
                  style={{ display: 'grid', gridTemplateColumns: '72px 122px 225px 100px 88px 112px 150px 215px 92px 132px', gap: 8, padding: '9px 10px', alignItems: 'center', cursor: 'pointer', background: open ? BB.blueDim : 'transparent' }}
                >
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 900 }}>{row.symbol}</div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.events.length} exit{row.events.length === 1 ? '' : 's'}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 850, color: row.latest.exitType === 'STOPPED' ? C.red : row.latest.exitType === 'SOLD' ? C.amber : C.muted }}>{row.latest.exitType}</div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.latest.date || 'date unavailable'}</div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.latest.account || 'account unavailable'}</div>
                  </div>
                  <div>
                    <span style={{ fontSize: 10, fontWeight: 900, color: tone, border: `1px solid ${tone}55`, borderRadius: 3, padding: '2px 6px' }}>{row.intel.state.replace(/_/g, ' ')}</span>
                    <div style={{ fontSize: 10.5, fontWeight: 800, marginTop: 4 }}>{row.intel.action}</div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.intel.why}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 850 }}>{money(row.intel.last)}</div>
                    <div style={{ fontSize: 10, color: row.moveSinceExit === null ? C.muted : row.moveSinceExit >= 0 ? C.green : C.red }}>
                      {row.moveSinceExit === null ? `exit ${money(row.latest.exitPrice)}` : `${row.moveSinceExit >= 0 ? '+' : ''}${row.moveSinceExit.toFixed(1)}% vs exit`}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 900, color: row.intel.rsiZone === 'OVERSOLD' ? C.green : row.intel.rsiZone === 'OVERBOUGHT' ? C.red : 'var(--text1)' }}>
                      {row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)}
                    </div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.intel.rsiZone}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 850, color: row.intel.distancePct === 0 ? C.green : row.intel.distancePct !== null && Math.abs(row.intel.distancePct) <= 3 ? C.amber : 'var(--text1)' }}>
                      {row.intel.distancePct === null ? '—' : row.intel.distancePct === 0 ? 'IN ZONE' : `${Math.abs(row.intel.distancePct).toFixed(1)}% ${row.intel.distancePct > 0 ? 'above' : 'below'}`}
                    </div>
                    <div style={{ fontSize: 10, color: C.muted }}>{row.intel.side.toLowerCase()} · {ageLabel(row.intel.asOf)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 850 }}>
                      {row.intel.entryLow === null ? '—' : row.intel.entryLow === row.intel.entryHigh
                        ? money(row.intel.entryLow) : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}
                    </div>
                    <div style={{ fontSize: 10, color: C.muted }}>stop {money(row.intel.stop)} · target {money(row.intel.target)}</div>
                  </div>
                  <div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {flags.length ? flags.map(flag => (
                        <span key={flag} style={{ fontSize: 10, fontWeight: 850, color: flag === 'CORE' ? C.blue : flag === 'DIVIDEND' ? C.green : flag === 'SHORT' ? C.red : flag === 'SWING' ? C.amber : C.purple, border: '1px solid var(--border)', padding: '2px 5px', borderRadius: 3 }}>{flag}</span>
                      )) : <span style={{ fontSize: 10, color: C.muted }}>UNCLASSIFIED</span>}
                    </div>
                    <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>{row.assignment.priority} · {row.assignment.account || 'no target account'}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 900, color: alertCount(row.symbol) ? C.amber : C.muted }}>🔔 {alertCount(row.symbol)}</div>
                    <div style={{ fontSize: 10, color: row.assignment.monitor ? C.green : C.muted }}>{row.assignment.monitor ? 'MONITORING' : 'PAUSED'}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 5 }} onClick={event => event.stopPropagation()}>
                    <button onClick={() => setEditSymbol(row.symbol)} style={button(false)}>FLAGS</button>
                    <button onClick={() => setAlertSymbol(row.symbol)} style={button(alertCount(row.symbol) > 0)}>ALERTS</button>
                  </div>
                </div>
                {open && (
                  <div style={{ padding: '10px 14px 14px 90px', background: 'rgba(2,6,23,.26)', display: 'grid', gridTemplateColumns: 'minmax(420px,1fr) minmax(300px,.75fr)', gap: 22 }}>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 850, color: C.muted, marginBottom: 6 }}>EXIT HISTORY — TRAILING 12 MONTHS</div>
                      {row.events.map(event => (
                        <div key={event.key} style={{ display: 'grid', gridTemplateColumns: '82px 98px 86px 92px 92px 1fr', gap: 8, fontSize: 10, padding: '4px 0' }}>
                          <span style={{ color: C.muted }}>{event.date || '—'}</span>
                          <span style={{ color: event.exitType === 'STOPPED' ? C.red : event.exitType === 'SOLD' ? C.amber : C.muted }}>{event.exitType}</span>
                          <span>{money(event.exitPrice)}</span>
                          <span>{money(event.proceeds)}</span>
                          <span style={{ color: event.pnl === null ? C.muted : event.pnl >= 0 ? C.green : C.red }}>{money(event.pnl)}</span>
                          <span style={{ color: C.muted }}>{event.reason} · {event.source}{event.sourceStatus ? ` · ${event.sourceStatus}` : ''}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 850, color: C.muted, marginBottom: 6 }}>PERSISTENT REQUIREMENTS</div>
                      <div style={{ fontSize: 10.5, lineHeight: 1.65 }}>
                        <b>Core position:</b> {row.assignment.flags.core ? 'YES' : 'NO'}<br />
                        <b>Sub-flags:</b> {flags.filter(flag => flag !== 'CORE').join(', ') || 'none'}<br />
                        <b>Target account:</b> {row.assignment.account || 'not assigned'}<br />
                        <b>Target weight:</b> {row.assignment.target_weight_pct === null ? 'not assigned' : `${row.assignment.target_weight_pct}%`}<br />
                        <b>Current state:</b> {row.intel.state.replace(/_/g, ' ')}<br />
                        <b>Next action:</b> {row.intel.action}<br />
                        <b>Why:</b> {row.intel.why}<br />
                        <b>Current data:</b> {row.intel.dataNote} · {ageLabel(row.intel.asOf)}<br />
                        <b>Thesis:</b> {row.assignment.notes || 'No thesis saved.'}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div style={{ fontSize: 10, color: C.muted }}>
        READY TO REVIEW is not an order. A degraded coverage panel is blocking: a partial ledger must never be presented as the full trailing year.
      </div>

      {editSymbol && (
        <FlagsModal
          symbol={editSymbol}
          initial={assignments[editSymbol] ?? defaultAssignment()}
          onClose={() => setEditSymbol(null)}
          onSave={async value => {
            try {
              await saveAssignments({ ...assignments, [editSymbol]: value })
              setToast(`${editSymbol} flags saved`)
              setEditSymbol(null)
            } catch (error: any) {
              setToast(`Save failed: ${error?.message || 'unknown error'}`)
            }
          }}
        />
      )}
      {alertSymbol && (() => {
        const row = rows.find(candidate => candidate.symbol === alertSymbol)
        if (!row) return null
        return (
          <AlertModal
            symbol={alertSymbol}
            intel={row.intel}
            short={row.assignment.flags.short}
            onClose={() => setAlertSymbol(null)}
            onArmed={async summary => {
              const next = {
                ...assignments,
                [alertSymbol]: {
                  ...(assignments[alertSymbol] ?? defaultAssignment()),
                  monitor: true, alert_summary: summary, updated_at: new Date().toISOString(),
                },
              }
              try { await saveAssignments(next) } catch { /* alert remains server-persistent */ }
              void alerts.refetch?.()
              setToast(`${alertSymbol} alerts armed`)
              setAlertSymbol(null)
            }}
          />
        )
      })()}
    </div>
  )
}

function FlagsModal({
  symbol, initial, onClose, onSave,
}: {
  symbol: string
  initial: Assignment
  onClose: () => void
  onSave: (assignment: Assignment) => Promise<void>
}) {
  const [value, setValue] = useState(normalizeAssignment(initial))
  const [busy, setBusy] = useState(false)
  const setFlag = (key: keyof Flags, checked: boolean) => {
    setValue(current => ({ ...current, flags: { ...current.flags, [key]: checked } }))
  }
  const flagBox = (active: boolean, color: string): React.CSSProperties => ({
    ...panel, padding: 10, borderColor: active ? color : 'var(--border)',
    background: active ? `${color}14` : 'var(--bg2)',
  })
  return (
    <Modal
      title={`${symbol} · Portfolio Flags`}
      subtitle="CORE is independent. COMPOUNDING, DIVIDEND, SHORT, and SWING are independent sub-flags and may be combined."
      onClose={onClose}
    >
      <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>PRIMARY REQUIREMENT</div>
      <label style={flagBox(value.flags.core, C.blue)}>
        <input type="checkbox" checked={value.flags.core} onChange={event => setFlag('core', event.target.checked)} />
        <b style={{ marginLeft: 8, color: value.flags.core ? C.blue : 'var(--text1)' }}>CORE POSITION</b>
        <div style={{ fontSize: 10, color: C.muted, margin: '4px 0 0 24px' }}>Strategic long-duration holding monitored for deliberate re-entry.</div>
      </label>
      <div style={{ fontSize: 11, fontWeight: 900, margin: '14px 0 8px' }}>INDEPENDENT SUB-FLAGS</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {([
          ['compounding', 'COMPOUNDING', C.purple, 'Repeated accumulation or add-on program.'],
          ['dividend', 'DIVIDEND', C.green, 'Income and distribution mandate.'],
          ['short', 'SHORT', C.red, 'Bearish re-entry requiring bearish mechanics.'],
          ['swing', 'SWING', C.amber, 'Bounded tactical holding period.'],
        ] as const).map(([key, label, color, note]) => (
          <label key={key} style={flagBox(value.flags[key], color)}>
            <input type="checkbox" checked={value.flags[key]} onChange={event => setFlag(key, event.target.checked)} />
            <b style={{ marginLeft: 8 }}>{label}</b>
            <div style={{ fontSize: 10, color: C.muted, margin: '3px 0 0 24px' }}>{note}</div>
          </label>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
        <label style={{ fontSize: 10, color: C.muted }}>
          PRIORITY
          <select value={value.priority} onChange={event => setValue(current => ({ ...current, priority: event.target.value as Priority }))} style={{ ...field, marginTop: 4 }}>
            {PRIORITIES.map(priority => <option key={priority}>{priority}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 10, color: C.muted }}>
          TARGET ACCOUNT
          <input value={value.account} onChange={event => setValue(current => ({ ...current, account: event.target.value }))} placeholder="taxable, rollover, Roth…" style={{ ...field, marginTop: 4 }} />
        </label>
        <label style={{ fontSize: 10, color: C.muted }}>
          TARGET WEIGHT %
          <input type="number" min="0" max="100" step="0.1" value={value.target_weight_pct ?? ''} onChange={event => setValue(current => ({ ...current, target_weight_pct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} />
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, marginTop: 18 }}>
          <input type="checkbox" checked={value.monitor} onChange={event => setValue(current => ({ ...current, monitor: event.target.checked }))} />
          Keep in active monitor
        </label>
      </div>
      <label style={{ display: 'block', fontSize: 10, color: C.muted, marginTop: 14 }}>
        OPERATOR THESIS / WHAT MUST BE TRUE
        <textarea value={value.notes} onChange={event => setValue(current => ({ ...current, notes: event.target.value }))} rows={5} placeholder="Why re-enter, what invalidates the thesis, and what evidence is required?" style={{ ...field, marginTop: 4, resize: 'vertical' }} />
      </label>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
        <button onClick={onClose} style={button(false)}>CANCEL</button>
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true)
            void onSave({ ...value, updated_at: new Date().toISOString() }).finally(() => setBusy(false))
          }}
          style={{ ...button(true), color: C.green, borderColor: C.green }}
        >
          {busy ? 'SAVING…' : 'SAVE FLAGS'}
        </button>
      </div>
    </Modal>
  )
}

function AlertModal({
  symbol, intel, short, onClose, onArmed,
}: {
  symbol: string
  intel: Intel
  short: boolean
  onClose: () => void
  onArmed: (summary: string) => Promise<void>
}) {
  const [priceEnabled, setPriceEnabled] = useState(intel.entryHigh !== null)
  const [priceCondition, setPriceCondition] = useState(short ? 'price_cross_above' : 'price_cross_below')
  const [priceThreshold, setPriceThreshold] = useState(String(short ? (intel.entryLow ?? intel.entryHigh ?? '') : (intel.entryHigh ?? intel.entryLow ?? '')))
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
    if (!rules.length) {
      setError('Select at least one valid alert.')
      return
    }
    if (short && intel.side !== 'SHORT' && priceEnabled) {
      setError('No bearish entry plan is available.')
      return
    }
    setBusy(true)
    setError('')
    try {
      for (const rule of rules) {
        const response = await fetch('/api/v2/watch/alerts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol, ...rule }),
        })
        const payload = unwrap(await response.json().catch(() => ({})))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'alert failed')
      }
      await onArmed(rules.map(rule => `${rule.condition_type} ${rule.threshold}`).join(' + '))
    } catch (caught: any) {
      setError(caught?.message || 'alert failed')
      setBusy(false)
    }
  }
  return (
    <Modal title={`${symbol} · Re-Entry Alerts`} subtitle="Persistent notifications only; no trade approval or submission." onClose={onClose}>
      <div style={{ ...panel, padding: 12, marginBottom: 10 }}>
        <label><input type="checkbox" checked={priceEnabled} onChange={event => setPriceEnabled(event.target.checked)} /> <b>Price reaches candidate zone</b></label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8, opacity: priceEnabled ? 1 : .45 }}>
          <select disabled={!priceEnabled} value={priceCondition} onChange={event => setPriceCondition(event.target.value)} style={field}>
            <option value="price_cross_below">Price crosses below</option>
            <option value="price_cross_above">Price crosses above</option>
          </select>
          <input disabled={!priceEnabled} type="number" value={priceThreshold} onChange={event => setPriceThreshold(event.target.value)} style={field} />
        </div>
      </div>
      <div style={{ ...panel, padding: 12 }}>
        <label><input type="checkbox" checked={rsiEnabled} onChange={event => setRsiEnabled(event.target.checked)} /> <b>RSI reaches review threshold</b></label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8, opacity: rsiEnabled ? 1 : .45 }}>
          <select disabled={!rsiEnabled} value={rsiCondition} onChange={event => setRsiCondition(event.target.value)} style={field}>
            <option value="rsi_below">RSI crosses below</option>
            <option value="rsi_above">RSI crosses above</option>
          </select>
          <input disabled={!rsiEnabled} type="number" min="0" max="100" value={rsiThreshold} onChange={event => setRsiThreshold(event.target.value)} style={field} />
        </div>
      </div>
      {error && <div style={{ color: C.red, fontSize: 10.5, marginTop: 9 }}>{error}</div>}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
        <button onClick={onClose} style={button(false)}>CANCEL</button>
        <button disabled={busy} onClick={() => void arm()} style={{ ...button(true), color: C.amber, borderColor: C.amber }}>
          {busy ? 'ARMING…' : 'ARM ALERTS'}
        </button>
      </div>
    </Modal>
  )
}
