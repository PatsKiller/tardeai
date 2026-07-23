import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'

const PREF_KEY = 'portfolio.reentry.assignments.v1'
const PRIORITIES = ['HIGH', 'NORMAL', 'LOW'] as const
const TAGS = ['CORE', 'COMPOUNDING', 'DIVIDEND', 'SHORT', 'SWING'] as const
const STATES = ['READY_TO_REVIEW', 'NEAR_ENTRY', 'WAIT_FOR_PULLBACK', 'OVERSOLD_REVIEW', 'OVERBOUGHT_WAIT', 'SHORT_PLAN_REQUIRED', 'CURRENTLY_HELD', 'STALE_DATA', 'NO_CURRENT_COVERAGE'] as const
const C = { green: BB.green, red: BB.red, amber: BB.amber, blue: BB.blue, purple: BB.amberAlt, muted: BB.text3 }
const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }
const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const btn = (on = false): React.CSSProperties => ({ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${on ? C.blue : 'var(--border)'}`, background: on ? BB.blueDim : 'var(--bg2)', color: on ? C.blue : 'var(--text2)' })

type Priority = typeof PRIORITIES[number]
type State = typeof STATES[number]
type Flags = { core: boolean; compounding: boolean; dividend: boolean; short: boolean; swing: boolean }
type Assignment = { flags: Flags; priority: Priority; monitor: boolean; account: string; target_weight_pct: number | null; notes: string; updated_at: string; alert_summary?: string }
type Exit = { id: string; symbol: string; date: string; account: string; shares: number | null; exitPrice: number | null; proceeds: number | null; type: 'STOPPED' | 'SOLD' | 'UNCLASSIFIED'; reason: string; source: string; sourceStatus: string }
type Intel = { last: number | null; rsi: number | null; rsiZone: string; low: number | null; high: number | null; stop: number | null; target: number | null; distance: number | null; asOf: string | null; state: State; action: string; why: string; side: 'LONG' | 'SHORT' | 'UNAVAILABLE'; note: string }

function root(v: any): any {
  let x = v
  for (let i = 0; i < 3 && x?.data && typeof x.data === 'object'; i += 1) x = x.data
  return x ?? {}
}
function rows(v: any): any[] {
  const x = root(v)
  for (const k of ['rows', 'events', 'history', 'items', 'sells', 'transactions', 'reentry_watch', 'watch']) if (Array.isArray(x?.[k])) return x[k]
  return Array.isArray(x) ? x : []
}
function num(...xs: any[]): number | null {
  for (const x of xs) if (x !== null && x !== undefined && x !== '' && Number.isFinite(Number(x))) return Number(x)
  return null
}
function txt(...xs: any[]): string {
  for (const x of xs) if (x !== null && x !== undefined && String(x).trim()) return String(x).trim()
  return ''
}
function path(o: any, p: string): any { return p.split('.').reduce((x, k) => x?.[k], o) }
function pickNum(os: any[], ps: string[]): number | null {
  for (const o of os) for (const p of ps) { const n = num(path(o, p)); if (n !== null) return n }
  return null
}
function pickText(os: any[], ps: string[]): string | null {
  for (const o of os) for (const p of ps) { const s = txt(path(o, p)); if (s) return s }
  return null
}
function day(v: any): string {
  const s = txt(v)
  if (!s) return ''
  const d = new Date(s)
  return Number.isFinite(d.getTime()) ? d.toISOString().slice(0, 10) : s.slice(0, 10)
}
function money(v: number | null): string { return v === null ? '—' : fmt$(v, 2) }
function age(v: string | null): string {
  if (!v) return 'timestamp unavailable'
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return v.slice(0, 16)
  const h = Math.max(0, Math.round((Date.now() - t) / 36e5))
  return h < 1 ? 'current' : h < 48 ? `${h}h old` : `${Math.round(h / 24)}d old`
}
function defaults(): Assignment {
  return { flags: { core: false, compounding: false, dividend: false, short: false, swing: false }, priority: 'NORMAL', monitor: true, account: '', target_weight_pct: null, notes: '', updated_at: '' }
}
function assignment(v: any): Assignment {
  const old = txt(v?.intent).toUpperCase()
  return {
    flags: {
      core: Boolean(v?.flags?.core ?? v?.core ?? v?.is_core ?? old === 'CORE'),
      compounding: Boolean(v?.flags?.compounding ?? v?.tags?.compounding ?? v?.compounding ?? old === 'COMPOUNDING'),
      dividend: Boolean(v?.flags?.dividend ?? v?.tags?.dividend ?? v?.dividend ?? old === 'DIVIDEND'),
      short: Boolean(v?.flags?.short ?? v?.tags?.short ?? v?.short ?? old === 'SHORT'),
      swing: Boolean(v?.flags?.swing ?? v?.tags?.swing ?? v?.swing ?? old === 'SWING'),
    },
    priority: PRIORITIES.includes(v?.priority) ? v.priority : 'NORMAL',
    monitor: v?.monitor !== false,
    account: txt(v?.account),
    target_weight_pct: num(v?.target_weight_pct),
    notes: txt(v?.notes),
    updated_at: txt(v?.updated_at),
    alert_summary: txt(v?.alert_summary) || undefined,
  }
}
function labels(a: Assignment): string[] { return TAGS.filter(t => a.flags[t.toLowerCase() as keyof Flags]) }
function normalizeExit(r: any, i: number, source: string): Exit | null {
  const symbol = txt(r.symbol, r.sold_symbol, r.ticker, r.security_symbol).toUpperCase()
  if (!/^[A-Z][A-Z0-9.\-]{0,11}$/.test(symbol)) return null
  const date = day(r.sold_at ?? r.stopped_at ?? r.triggered_at ?? r.trade_date ?? r.close_date ?? r.executed_at ?? r.transaction_date ?? r.date)
  const shares = num(r.shares_sold, r.shares, r.quantity, r.qty)
  const proceeds = num(r.proceeds_usd, r.net_proceeds_usd, r.proceeds, r.amount)
  let exitPrice = num(r.sell_price, r.exit_price, r.stop_fill_price, r.price, r.avg_price, r.execution_price, r.average_price)
  if (exitPrice === null && proceeds !== null && shares !== null && Math.abs(shares) > 0) exitPrice = Math.abs(proceeds / shares)
  const meta = typeof r.metadata === 'object' ? r.metadata : {}
  const reason = txt(r.exit_reason, r.sell_reason, r.reason, r.stop_reason, r.dismiss_reason, r.description, meta?.description, r.operator_status, r.event_status, r.status)
  const kindText = `${reason} ${txt(r.order_type, r.transaction_type, r.action, r.type)} ${source}`
  const type: Exit['type'] = /stop|protective|trailing|risk exit|stop-loss/i.test(kindText) ? 'STOPPED' : /sell|sold|closed|exit/i.test(kindText) ? 'SOLD' : 'UNCLASSIFIED'
  return {
    id: txt(r.event_key, r.id, r.event_id, r.matched_event_id, r.transaction_id, `${source}:${symbol}:${date}:${proceeds ?? i}`),
    symbol, date, account: txt(r.account, r.account_key, r.account_name, r.broker_account),
    shares: shares === null ? null : Math.abs(shares), exitPrice,
    proceeds: proceeds === null ? null : Math.abs(proceeds), type,
    reason: reason || 'Exit reason not classified in source data',
    source: txt(r.source, r.source_system, r.import_source, source),
    sourceStatus: txt(r.event_status, r.completion_status, r.operator_status, r.status),
  }
}
function ekey(e: Exit): string { return `${e.id}|${e.symbol}|${e.account}|${e.date}|${e.proceeds ?? ''}` }

function families(p: any): any[] {
  if (Array.isArray(p?.families)) return p.families
  if (p?.families && typeof p.families === 'object') return Object.entries(p.families).map(([family, v]: [string, any]) => ({ family, ...(v ?? {}) }))
  if (Array.isArray(p?.family_results)) return p.family_results
  if (p?.family_results && typeof p.family_results === 'object') return Object.entries(p.family_results).map(([family, v]: [string, any]) => ({ family, ...(v ?? {}) }))
  return []
}
function derive(watch: any, card: any, advisory: any, stopRow: any, a: Assignment, held: boolean): Intel {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? stopRow?.decision_packet ?? {}
  const selected = packet?.selected_family?.mechanics ?? packet?.mechanics ?? packet?.current_mechanics ?? stopRow?.reentry_plan ?? stopRow?.mechanics ?? {}
  const shortMechanics = a.flags.short
    ? families(packet).find(x => /short|bear|breakdown/i.test(txt(x.family, x.name, x.direction, x.strategy)))?.mechanics
      ?? watch?.short_plan ?? card?.short_plan ?? stopRow?.short_plan ?? null
    : null
  const market = [stopRow ?? {}, advisory ?? {}, watch ?? {}, card ?? {}, packet ?? {}]
  const plan = a.flags.short ? [shortMechanics ?? {}] : [stopRow ?? {}, watch ?? {}, card ?? {}, packet ?? {}, selected ?? {}]
  const last = pickNum(market, ['last_price', 'price', 'current_price', 'quote_price', 'quote.last', 'quote.price', 'market.last'])
  const rsi = pickNum(market, ['rsi', 'rsi_14', 'current_rsi', 'technical.rsi', 'technicals.rsi', 'technicals.rsi_14', 'indicators.rsi'])
  let low = pickNum(plan, ['reentry_low', 'reentry_zone_low', 'entry_zone_low', 'plan_entry_low', 'entry_low', 'mechanics.entry_low', 'entry.zone_low'])
  let high = pickNum(plan, ['reentry_high', 'reentry_zone_high', 'entry_zone_high', 'plan_entry_high', 'entry_high', 'mechanics.entry_high', 'entry.zone_high'])
  const single = pickNum(plan, ['reentry_price', 'entry_limit', 'plan_entry', 'entry_price', 'mechanics.entry', 'entry.limit'])
  if (low === null) low = single
  if (high === null) high = single
  if (low !== null && high !== null && low > high) [low, high] = [high, low]
  const stop = pickNum(plan, ['reentry_stop', 'entry_stop', 'plan_stop', 'stop_price', 'mechanics.stop'])
  const target = pickNum(plan, ['reentry_target', 'entry_target', 'plan_target', 'target_price', 'mechanics.target'])
  const asOf = pickText(market, ['last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote_time', 'quote.as_of', 'technicals.as_of'])
  const t = asOf ? new Date(asOf).getTime() : NaN
  const stale = !Number.isFinite(t) || Date.now() - t > 96 * 36e5
  let distance: number | null = null
  if (last !== null && last > 0 && low !== null && high !== null) {
    distance = last > high ? ((last - high) / high) * 100 : last < low ? -((low - last) / low) * 100 : 0
  }
  const rsiZone = rsi === null ? 'UNAVAILABLE' : rsi <= 30 ? 'OVERSOLD' : rsi >= 70 ? 'OVERBOUGHT' : 'NEUTRAL'
  let state: State = 'WAIT_FOR_PULLBACK', action = 'Keep monitoring', why = 'Price and momentum have not reached review conditions.'
  if (held) { state = 'CURRENTLY_HELD'; action = 'Review as an existing holding'; why = 'The symbol is currently held, so it is no longer a clean re-entry-only candidate.' }
  else if (last === null || rsi === null) { state = 'NO_CURRENT_COVERAGE'; action = 'Build or refresh current technical coverage'; why = 'Current price and RSI are required.' }
  else if (stale) { state = 'STALE_DATA'; action = 'Refresh market and technical data'; why = `The technical packet is ${age(asOf)}.` }
  else if (a.flags.short && !shortMechanics) { state = 'SHORT_PLAN_REQUIRED'; action = 'Build and review a bearish setup'; why = 'SHORT is flagged but no same-side bearish entry mechanics exist.' }
  else if (low === null || high === null) { state = 'NO_CURRENT_COVERAGE'; action = 'Build a candidate entry zone'; why = 'Current price and RSI exist but no entry range is available.' }
  else if (a.flags.short && distance === 0 && rsi >= 60) { state = 'READY_TO_REVIEW'; action = 'Review short entry now'; why = 'Price is in the bearish zone and RSI supports a short-side review.' }
  else if (a.flags.short && distance !== null && Math.abs(distance) <= 3) { state = 'NEAR_ENTRY'; action = 'Prepare short review'; why = `Price is ${Math.abs(distance).toFixed(1)}% from the bearish zone.` }
  else if (!a.flags.short && distance === 0 && rsi <= 45) { state = 'READY_TO_REVIEW'; action = 'Review long re-entry now'; why = 'Price is in the entry zone and RSI is not extended.' }
  else if (!a.flags.short && distance !== null && distance >= 0 && distance <= 3) { state = 'NEAR_ENTRY'; action = 'Prepare a re-entry review'; why = `Price is ${distance.toFixed(1)}% above the entry zone.` }
  else if (!a.flags.short && rsi <= 30) { state = 'OVERSOLD_REVIEW'; action = 'Review for stabilization'; why = 'RSI is oversold; confirmation is still required.' }
  else if (!a.flags.short && rsi >= 70) { state = 'OVERBOUGHT_WAIT'; action = 'Wait for a pullback'; why = 'RSI is overbought and extended.' }
  return {
    last, rsi, rsiZone, low, high, stop, target, distance, asOf, state, action, why,
    side: a.flags.short ? (shortMechanics ? 'SHORT' : 'UNAVAILABLE') : 'LONG',
    note: txt(stopRow?.data_quality_state, watch?.data_quality_state, card?.data_quality_state, advisory?.note, packet?.current_validity?.state, 'cached Trade AI intelligence'),
  }
}
function stateColor(s: State): string {
  if (s === 'READY_TO_REVIEW') return C.green
  if (s === 'NEAR_ENTRY' || s === 'OVERSOLD_REVIEW') return C.amber
  if (s === 'OVERBOUGHT_WAIT' || s === 'SHORT_PLAN_REQUIRED') return C.red
  if (s === 'CURRENTLY_HELD') return C.purple
  if (s === 'WAIT_FOR_PULLBACK') return C.blue
  return C.muted
}
function Modal({ title, subtitle, close, children }: { title: string; subtitle: string; close: () => void; children: React.ReactNode }) {
  return <div role="dialog" aria-modal="true" onMouseDown={close} style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(2,6,23,.78)', display: 'grid', placeItems: 'center', padding: 18 }}>
    <div onMouseDown={e => e.stopPropagation()} style={{ ...panel, width: 'min(680px,96vw)', maxHeight: '92vh', overflowY: 'auto', padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}><div style={{ flex: 1 }}><div style={{ fontSize: 18, fontWeight: 900 }}>{title}</div><div style={{ fontSize: 10.5, color: C.muted }}>{subtitle}</div></div><button onClick={close} style={btn()}>CLOSE</button></div>
      {children}
    </div>
  </div>
}

export default function ReEntryPageV2() {
  const from = useMemo(() => { const d = new Date(); d.setUTCFullYear(d.getUTCFullYear() - 1); return d.toISOString().slice(0, 10) }, [])
  const history = useApi<any>('/api/v2/redeploy/history?days=365', 120000)
  const book = useApi<any>('/api/v2/redeploy/book?limit=1000&include_dismissed=1', 120000)
  const stopped = useApi<any>('/api/v2/stops/reentry-watch?days=365', 120000)
  const journal = useApi<any>(`/api/v2/journal/by-ticker?from=${from}`, 120000)
  const cards = useApi<any>('/api/v2/symbol-cards', 300000)
  const advisory = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120000)
  const holdings = useApi<any>('/api/v2/portfolio/holdings', 120000)
  const prefs = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(PREF_KEY)}`, 0)
  const alerts = useApi<any>('/api/v2/watch/alerts/list', 120000)
  const regimeRaw = useApi<any>('/api/v2/risk-regime/latest', 300000)
  const [assignments, setAssignments] = useState<Record<string, Assignment>>({})
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('ALL')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [exitFilter, setExitFilter] = useState('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [edit, setEdit] = useState<string | null>(null)
  const [alert, setAlert] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [loadingIntel, setLoadingIntel] = useState(false)
  const [toast, setToast] = useState('')

  useEffect(() => {
    const v = root(prefs.data)?.value
    if (!v || typeof v !== 'object' || Array.isArray(v)) return
    const next: Record<string, Assignment> = {}
    Object.entries(v).forEach(([s, a]) => { next[s.toUpperCase()] = assignment(a) })
    setAssignments(next)
  }, [prefs.data])

  const source = useMemo(() => {
    const hp = root(history.data), bp = root(book.data), sp = root(stopped.data)
    return {
      hRows: rows(history.data).length, bRows: rows(book.data).length, sRows: rows(stopped.data).length,
      jRows: Array.isArray(root(journal.data)?.tickers) ? root(journal.data).tickers.length : 0,
      expected: num(hp?.counts?.sells_found, hp?.counts?.matched),
      hErr: history.error || (hp?.ok === false ? txt(hp.error, 'ok=false') : ''),
      bErr: book.error || (bp?.ok === false ? txt(bp.error, 'ok=false') : ''),
      sErr: stopped.error || (sp?.ok === false ? txt(sp.error, 'ok=false') : ''),
    }
  }, [history.data, book.data, stopped.data, journal.data, history.error, book.error, stopped.error])

  const exits = useMemo(() => {
    const out: Exit[] = []
    const add = (rs: any[], src: string) => rs.forEach((r, i) => { const e = normalizeExit(r, i, src); if (e && (!e.date || e.date >= from)) out.push(e) })
    add(rows(history.data), 'redeploy-history'); add(rows(book.data), 'redeploy-book'); add(rows(stopped.data), 'stops-reentry-watch')
    const seen = new Set<string>()
    return out.sort((a, b) => b.date.localeCompare(a.date)).filter(e => { const k = ekey(e); if (seen.has(k)) return false; seen.add(k); return true })
  }, [history.data, book.data, stopped.data, from])

  const bySymbol = useMemo(() => {
    const map = new Map<string, Exit[]>()
    exits.forEach(e => map.set(e.symbol, [...(map.get(e.symbol) ?? []), e]))
    const jt: any[] = root(journal.data)?.tickers ?? []
    jt.forEach(t => {
      const symbol = txt(t.symbol).toUpperCase()
      if (!symbol || map.has(symbol)) return
      const e = normalizeExit({ symbol, close_date: t.last_close_date ?? t.last_trade_at ?? t.last_close, sell_price: t.last_sell_price, reason: 'Closed-trade journal fallback; transaction source did not return this symbol', status: 'journal_fallback' }, 0, 'journal-by-ticker')
      if (e && (!e.date || e.date >= from)) map.set(symbol, [e])
    })
    return Array.from(map.entries()).map(([symbol, es]) => ({ symbol, events: es.sort((a, b) => b.date.localeCompare(a.date)), latest: es.sort((a, b) => b.date.localeCompare(a.date))[0] }))
  }, [exits, journal.data, from])

  const stopMap = useMemo(() => {
    const m: Record<string, any> = {}
    rows(stopped.data).forEach(r => { const s = txt(r.symbol, r.ticker).toUpperCase(); if (s) m[s] = r })
    return m
  }, [stopped.data])

  const symbols = useMemo(() => bySymbol.map(x => x.symbol).sort(), [bySymbol])
  useEffect(() => {
    if (!symbols.length) return
    let dead = false, cursor = 0
    const ctl = new AbortController(), out: Record<string, any> = {}
    setLoadingIntel(true)
    const worker = async () => {
      while (!dead) {
        const i = cursor++; if (i >= Math.min(symbols.length, 300)) return
        const s = symbols[i]
        try {
          const r = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(s)}`, { signal: ctl.signal, cache: 'no-store' })
          const p = root(await r.json()); out[s] = (p?.items ?? [])[0] ?? null
        } catch { out[s] = null }
      }
    }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, worker)).finally(() => { if (!dead) { setWatchMap(x => ({ ...x, ...out })); setLoadingIntel(false) } })
    return () => { dead = true; ctl.abort() }
  }, [symbols.join(','), reload])

  const cardMap: Record<string, any> = root(cards.data)?.cards ?? {}
  const advMap = useMemo(() => {
    const m: Record<string, any> = {}
    for (const r of root(advisory.data)?.advisories ?? []) m[txt(r.symbol).toUpperCase()] = r
    return m
  }, [advisory.data])
  const held = useMemo(() => new Set<string>((root(holdings.data)?.holdings ?? []).filter((h: any) => Number(h.shares ?? h.quantity ?? 0) > 0).map((h: any) => txt(h.symbol).toUpperCase())), [holdings.data])
  const alertRows: any[] = root(alerts.data)?.alerts ?? root(alerts.data)?.items ?? []
  const alertCount = (s: string) => alertRows.filter(a => txt(a.symbol).toUpperCase() === s && !['disabled', 'expired', 'resolved'].includes(txt(a.status).toLowerCase())).length
  const regime = txt(root(regimeRaw.data)?.regime_label, root(regimeRaw.data)?.label, 'unknown').replace(/_/g, ' ')

  const allRows = useMemo(() => bySymbol.map(x => {
    const a = assignments[x.symbol] ?? defaults()
    const intel = derive(watchMap[x.symbol], cardMap[x.symbol], advMap[x.symbol], stopMap[x.symbol], a, held.has(x.symbol))
    const move = x.latest.exitPrice && intel.last ? ((intel.last - x.latest.exitPrice) / x.latest.exitPrice) * 100 : null
    return { ...x, a, intel, move }
  }), [bySymbol, assignments, watchMap, cardMap, advMap, stopMap, held])

  const shown = useMemo(() => {
    const priorityRank: Record<Priority, number> = { HIGH: 0, NORMAL: 1, LOW: 2 }
    return allRows.filter(x => {
      const q = search.trim().toUpperCase(), ls = labels(x.a)
      if (q && !`${x.symbol} ${x.latest.account} ${x.latest.reason} ${ls.join(' ')}`.toUpperCase().includes(q)) return false
      if (tagFilter === 'UNCLASSIFIED' && ls.length) return false
      if (tagFilter !== 'ALL' && tagFilter !== 'UNCLASSIFIED' && !ls.includes(tagFilter)) return false
      if (stateFilter !== 'ALL' && x.intel.state !== stateFilter) return false
      if (exitFilter !== 'ALL' && x.latest.type !== exitFilter) return false
      return true
    }).sort((a, b) => priorityRank[a.a.priority] - priorityRank[b.a.priority] || b.latest.date.localeCompare(a.latest.date))
  }, [allRows, search, tagFilter, stateFilter, exitFilter])

  const save = async (next: Record<string, Assignment>) => {
    setAssignments(next)
    const r = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: PREF_KEY, value: next }) })
    const p = root(await r.json().catch(() => ({})))
    if (!r.ok || p?.ok === false) throw new Error(p?.error || 'save failed')
    void prefs.refetch?.()
  }
  const refresh = () => {
    setToast('Refreshing complete exit ledger and current status…')
    ;[history, book, stopped, journal, cards, advisory, holdings, alerts, regimeRaw].forEach(x => void x.refetch?.())
    setReload(x => x + 1); window.setTimeout(() => setToast(''), 3500)
  }

  const expected = source.expected, mismatch = expected !== null && exits.length < expected
  const failed = Boolean(source.hErr || source.bErr || source.sErr)
  const coverage = mismatch || failed ? C.red : C.green
  const counts = { events: exits.length, symbols: allRows.length, monitored: allRows.filter(x => x.a.monitor).length, ready: allRows.filter(x => x.intel.state === 'READY_TO_REVIEW').length, near: allRows.filter(x => x.intel.state === 'NEAR_ENTRY').length, missing: allRows.filter(x => ['STALE_DATA', 'NO_CURRENT_COVERAGE'].includes(x.intel.state)).length }

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <div><div style={{ fontSize: 10, color: C.muted }}><Link to="/portfolio" style={{ color: C.blue, textDecoration: 'none' }}>Portfolio</Link> / Re-Entry</div><div style={{ fontSize: 24, fontWeight: 900 }}>Re-Entry Intelligence</div><div style={{ fontSize: 11, color: C.muted }}>Full trailing-year exit ledger · independent portfolio flags · current state, next action, and alerts</div><div style={{ fontSize: 10, color: /off|defensive|disrupt/i.test(regime) ? C.amber : C.muted, marginTop: 4 }}>MARKET REGIME {regime.toUpperCase()} · advisory only</div></div>
      <button onClick={refresh} style={btn()}>{loadingIntel ? 'LOADING STATUS…' : 'REFRESH ALL SOURCES'}</button>
    </div>

    <div style={{ ...panel, padding: 10, borderColor: coverage }}>
      <div style={{ fontSize: 11, fontWeight: 900, color: coverage }}>EXIT-LEDGER COVERAGE {mismatch || failed ? 'DEGRADED' : 'VERIFIED'}</div>
      <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>History {source.hRows} · Redeploy book {source.bRows} · Stopped-out watch {source.sRows} · Journal fallback {source.jRows} · Union {counts.events} events / {counts.symbols} symbols{expected !== null ? ` · source-declared sells ${expected}` : ''}</div>
      {mismatch && <div style={{ fontSize: 10, color: C.red, marginTop: 5 }}>BLOCKING WARNING: the source reports {expected} sells but the page loaded {counts.events}. Do not treat this view as complete.</div>}
      {failed && <div style={{ fontSize: 10, color: C.red, marginTop: 5 }}>{source.hErr && <div>History: {source.hErr}</div>}{source.bErr && <div>Book: {source.bErr}</div>}{source.sErr && <div>Stopped-out watch: {source.sErr}</div>}</div>}
    </div>

    <div style={{ ...panel, display: 'grid', gridTemplateColumns: 'repeat(6,minmax(100px,1fr))', gap: 1, overflow: 'hidden' }}>
      {[['Exit events', counts.events, C.blue], ['Exited symbols', counts.symbols, C.blue], ['Monitored', counts.monitored, C.purple], ['Ready now', counts.ready, C.green], ['Near entry', counts.near, C.amber], ['Missing / stale', counts.missing, C.red]].map(([l, v, color]) => <div key={String(l)} style={{ padding: '10px 12px', background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase' }}>{l}</div><div style={{ fontSize: 20, fontWeight: 900, color: String(color) }}>{v}</div></div>)}
    </div>

    <div style={{ ...panel, padding: 9, display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) repeat(3,minmax(140px,190px))', gap: 8 }}>
      <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol, account, reason, or flag…" style={input} />
      <select value={tagFilter} onChange={e => setTagFilter(e.target.value)} style={input}><option>ALL</option><option>CORE</option><option>COMPOUNDING</option><option>DIVIDEND</option><option>SHORT</option><option>SWING</option><option>UNCLASSIFIED</option></select>
      <select value={stateFilter} onChange={e => setStateFilter(e.target.value)} style={input}><option value="ALL">All current states</option>{STATES.map(s => <option key={s}>{s.replace(/_/g, ' ')}</option>)}</select>
      <select value={exitFilter} onChange={e => setExitFilter(e.target.value)} style={input}><option value="ALL">All exit types</option><option value="STOPPED">Stopped out</option><option value="SOLD">Traded out</option><option value="UNCLASSIFIED">Exit type unclassified</option></select>
    </div>

    {toast && <div style={{ fontSize: 10.5, color: C.blue }}>{toast}</div>}
    <div style={{ ...panel, overflowX: 'auto' }}><div style={{ minWidth: 1380 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '72px 120px 220px 100px 88px 112px 145px 210px 92px 132px', gap: 8, padding: '7px 10px', borderBottom: '1px solid var(--border)', fontSize: 10, color: C.muted, textTransform: 'uppercase' }}><span>Symbol</span><span>Latest exit</span><span>Current status / action</span><span>Last / exit</span><span>RSI</span><span>Pullback</span><span>Candidate entry</span><span>Portfolio flags</span><span>Alerts</span><span>Actions</span></div>
      {!shown.length ? <div style={{ padding: 24, color: C.muted, textAlign: 'center' }}>No exited positions match these filters. Check the coverage panel before concluding that no exits exist.</div> : shown.map(x => {
        const open = expanded === x.symbol, ls = labels(x.a), sc = stateColor(x.intel.state)
        return <div key={x.symbol} style={{ borderBottom: '1px solid var(--border)' }}>
          <div onClick={() => setExpanded(open ? null : x.symbol)} style={{ display: 'grid', gridTemplateColumns: '72px 120px 220px 100px 88px 112px 145px 210px 92px 132px', gap: 8, padding: '9px 10px', alignItems: 'center', cursor: 'pointer', background: open ? BB.blueDim : 'transparent' }}>
            <div><div style={{ fontSize: 13, fontWeight: 900 }}>{x.symbol}</div><div style={{ fontSize: 10, color: C.muted }}>{x.events.length} exit{x.events.length === 1 ? '' : 's'}</div></div>
            <div><div style={{ fontSize: 10, fontWeight: 850, color: x.latest.type === 'STOPPED' ? C.red : x.latest.type === 'SOLD' ? C.amber : C.muted }}>{x.latest.type}</div><div style={{ fontSize: 10, color: C.muted }}>{x.latest.date || 'date unavailable'}</div><div style={{ fontSize: 10, color: C.muted }}>{x.latest.account || 'account unavailable'}</div></div>
            <div><span style={{ fontSize: 10, fontWeight: 900, color: sc, border: `1px solid ${sc}55`, borderRadius: 3, padding: '2px 6px' }}>{x.intel.state.replace(/_/g, ' ')}</span><div style={{ fontSize: 10.5, fontWeight: 800, marginTop: 4 }}>{x.intel.action}</div><div style={{ fontSize: 10, color: C.muted }}>{x.intel.why}</div></div>
            <div><div style={{ fontSize: 11, fontWeight: 850 }}>{money(x.intel.last)}</div><div style={{ fontSize: 10, color: x.move === null ? C.muted : x.move >= 0 ? C.green : C.red }}>{x.move === null ? `exit ${money(x.latest.exitPrice)}` : `${x.move >= 0 ? '+' : ''}${x.move.toFixed(1)}% vs exit`}</div></div>
            <div><div style={{ fontSize: 14, fontWeight: 900, color: x.intel.rsiZone === 'OVERSOLD' ? C.green : x.intel.rsiZone === 'OVERBOUGHT' ? C.red : 'var(--text1)' }}>{x.intel.rsi === null ? '—' : x.intel.rsi.toFixed(1)}</div><div style={{ fontSize: 10, color: C.muted }}>{x.intel.rsiZone}</div></div>
            <div><div style={{ fontSize: 11, fontWeight: 850, color: x.intel.distance === 0 ? C.green : x.intel.distance !== null && Math.abs(x.intel.distance) <= 3 ? C.amber : 'var(--text1)' }}>{x.intel.distance === null ? '—' : x.intel.distance === 0 ? 'IN ZONE' : `${Math.abs(x.intel.distance).toFixed(1)}% ${x.intel.distance > 0 ? 'above' : 'below'}`}</div><div style={{ fontSize: 10, color: C.muted }}>{x.intel.side.toLowerCase()} · {age(x.intel.asOf)}</div></div>
            <div><div style={{ fontSize: 11, fontWeight: 850 }}>{x.intel.low === null ? '—' : x.intel.low === x.intel.high ? money(x.intel.low) : `${money(x.intel.low)}–${money(x.intel.high)}`}</div><div style={{ fontSize: 10, color: C.muted }}>stop {money(x.intel.stop)} · target {money(x.intel.target)}</div></div>
            <div><div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{ls.length ? ls.map(l => <span key={l} style={{ fontSize: 10, fontWeight: 850, color: l === 'CORE' ? C.blue : l === 'DIVIDEND' ? C.green : l === 'SHORT' ? C.red : l === 'SWING' ? C.amber : C.purple, border: '1px solid var(--border)', padding: '2px 5px', borderRadius: 3 }}>{l}</span>) : <span style={{ fontSize: 10, color: C.muted }}>UNCLASSIFIED</span>}</div><div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>{x.a.priority} · {x.a.account || 'no target account'}</div></div>
            <div><div style={{ fontSize: 12, fontWeight: 900, color: alertCount(x.symbol) ? C.amber : C.muted }}>🔔 {alertCount(x.symbol)}</div><div style={{ fontSize: 10, color: x.a.monitor ? C.green : C.muted }}>{x.a.monitor ? 'MONITORING' : 'PAUSED'}</div></div>
            <div style={{ display: 'flex', gap: 5 }} onClick={e => e.stopPropagation()}><button onClick={() => setEdit(x.symbol)} style={btn()}>FLAGS</button><button onClick={() => setAlert(x.symbol)} style={btn(alertCount(x.symbol) > 0)}>ALERTS</button></div>
          </div>
          {open && <div style={{ padding: '10px 14px 14px 90px', background: 'rgba(2,6,23,.26)', display: 'grid', gridTemplateColumns: 'minmax(360px,1fr) minmax(300px,.8fr)', gap: 22 }}>
            <div><div style={{ fontSize: 10, fontWeight: 850, color: C.muted, marginBottom: 6 }}>EXIT HISTORY — TRAILING 12 MONTHS</div>{x.events.map(e => <div key={ekey(e)} style={{ display: 'grid', gridTemplateColumns: '82px 105px 90px 90px 1fr', gap: 8, fontSize: 10, padding: '4px 0' }}><span style={{ color: C.muted }}>{e.date || '—'}</span><span style={{ color: e.type === 'STOPPED' ? C.red : e.type === 'SOLD' ? C.amber : C.muted }}>{e.type}</span><span>{money(e.exitPrice)}</span><span>{money(e.proceeds)}</span><span style={{ color: C.muted }}>{e.reason} · {e.source}{e.sourceStatus ? ` · ${e.sourceStatus}` : ''}</span></div>)}</div>
            <div><div style={{ fontSize: 10, fontWeight: 850, color: C.muted, marginBottom: 6 }}>PERSISTENT REQUIREMENTS</div><div style={{ fontSize: 10.5, lineHeight: 1.65 }}><b>Core position:</b> {x.a.flags.core ? 'YES' : 'NO'}<br/><b>Sub-flags:</b> {ls.filter(l => l !== 'CORE').join(', ') || 'none'}<br/><b>Target account:</b> {x.a.account || 'not assigned'}<br/><b>Target weight:</b> {x.a.target_weight_pct === null ? 'not assigned' : `${x.a.target_weight_pct}%`}<br/><b>Current state:</b> {x.intel.state.replace(/_/g, ' ')}<br/><b>Next action:</b> {x.intel.action}<br/><b>Why:</b> {x.intel.why}<br/><b>Current data:</b> {x.intel.note} · {age(x.intel.asOf)}<br/><b>Thesis:</b> {x.a.notes || 'No thesis saved.'}</div></div>
          </div>}
        </div>
      })}
    </div></div>

    <div style={{ fontSize: 10, color: C.muted }}>READY TO REVIEW is not an order. Coverage warnings are blocking: an incomplete ledger must never be presented as the full trailing year.</div>
    {edit && <FlagsModal symbol={edit} initial={assignments[edit] ?? defaults()} close={() => setEdit(null)} save={async v => { try { await save({ ...assignments, [edit]: v }); setToast(`${edit} flags saved`); setEdit(null) } catch (e: any) { setToast(`Save failed: ${e?.message || 'unknown error'}`) } }} />}
    {alert && (() => { const x = allRows.find(r => r.symbol === alert); return x ? <AlertModal symbol={alert} intel={x.intel} short={x.a.flags.short} close={() => setAlert(null)} armed={async summary => { const next = { ...assignments, [alert]: { ...(assignments[alert] ?? defaults()), monitor: true, alert_summary: summary, updated_at: new Date().toISOString() } }; try { await save(next) } catch {} void alerts.refetch?.(); setToast(`${alert} alerts armed`); setAlert(null) }} /> : null })()}
  </div>
}

function FlagsModal({ symbol, initial, close, save }: { symbol: string; initial: Assignment; close: () => void; save: (a: Assignment) => Promise<void> }) {
  const [v, setV] = useState(assignment(initial)), [busy, setBusy] = useState(false)
  const setFlag = (k: keyof Flags, checked: boolean) => setV(x => ({ ...x, flags: { ...x.flags, [k]: checked } }))
  const flagBox = (on: boolean, color: string): React.CSSProperties => ({ ...panel, padding: 10, borderColor: on ? color : 'var(--border)', background: on ? `${color}14` : 'var(--bg2)' })
  return <Modal title={`${symbol} · Portfolio Flags`} subtitle="CORE is independent. COMPOUNDING, DIVIDEND, SHORT, and SWING are independent sub-flags and may be combined." close={close}>
    <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>PRIMARY REQUIREMENT</div>
    <label style={flagBox(v.flags.core, C.blue)}><input type="checkbox" checked={v.flags.core} onChange={e => setFlag('core', e.target.checked)} /><b style={{ marginLeft: 8, color: v.flags.core ? C.blue : 'var(--text1)' }}>CORE POSITION</b><div style={{ fontSize: 10, color: C.muted, margin: '4px 0 0 24px' }}>Strategic long-duration holding monitored for deliberate re-entry.</div></label>
    <div style={{ fontSize: 11, fontWeight: 900, margin: '14px 0 8px' }}>INDEPENDENT SUB-FLAGS</div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {([['compounding', 'COMPOUNDING', C.purple, 'Repeated accumulation or add-on program.'], ['dividend', 'DIVIDEND', C.green, 'Income and distribution mandate.'], ['short', 'SHORT', C.red, 'Bearish re-entry requiring bearish mechanics.'], ['swing', 'SWING', C.amber, 'Bounded tactical holding period.']] as const).map(([k, l, color, note]) => <label key={k} style={flagBox(v.flags[k], color)}><input type="checkbox" checked={v.flags[k]} onChange={e => setFlag(k, e.target.checked)} /><b style={{ marginLeft: 8 }}>{l}</b><div style={{ fontSize: 10, color: C.muted, margin: '3px 0 0 24px' }}>{note}</div></label>)}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
      <label style={{ fontSize: 10, color: C.muted }}>PRIORITY<select value={v.priority} onChange={e => setV(x => ({ ...x, priority: e.target.value as Priority }))} style={{ ...input, marginTop: 4 }}>{PRIORITIES.map(p => <option key={p}>{p}</option>)}</select></label>
      <label style={{ fontSize: 10, color: C.muted }}>TARGET ACCOUNT<input value={v.account} onChange={e => setV(x => ({ ...x, account: e.target.value }))} placeholder="taxable, rollover, Roth…" style={{ ...input, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: C.muted }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={v.target_weight_pct ?? ''} onChange={e => setV(x => ({ ...x, target_weight_pct: e.target.value === '' ? null : Number(e.target.value) }))} style={{ ...input, marginTop: 4 }} /></label>
      <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, marginTop: 18 }}><input type="checkbox" checked={v.monitor} onChange={e => setV(x => ({ ...x, monitor: e.target.checked }))} />Keep in active monitor</label>
    </div>
    <label style={{ display: 'block', fontSize: 10, color: C.muted, marginTop: 14 }}>OPERATOR THESIS / WHAT MUST BE TRUE<textarea value={v.notes} onChange={e => setV(x => ({ ...x, notes: e.target.value }))} rows={5} placeholder="Why re-enter, what invalidates the thesis, and what evidence is required?" style={{ ...input, marginTop: 4, resize: 'vertical' }} /></label>
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={close} style={btn()}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); void save({ ...v, updated_at: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...btn(true), color: C.green, borderColor: C.green }}>{busy ? 'SAVING…' : 'SAVE FLAGS'}</button></div>
  </Modal>
}

function AlertModal({ symbol, intel, short, close, armed }: { symbol: string; intel: Intel; short: boolean; close: () => void; armed: (s: string) => Promise<void> }) {
  const [priceOn, setPriceOn] = useState(intel.high !== null), [priceType, setPriceType] = useState(short ? 'price_cross_above' : 'price_cross_below'), [price, setPrice] = useState(String(short ? (intel.low ?? intel.high ?? '') : (intel.high ?? intel.low ?? '')))
  const [rsiOn, setRsiOn] = useState(true), [rsiType, setRsiType] = useState(short ? 'rsi_above' : 'rsi_below'), [rsi, setRsi] = useState(short ? '65' : '40')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const arm = async () => {
    const rules = [...(priceOn ? [{ condition_type: priceType, threshold: Number(price) }] : []), ...(rsiOn ? [{ condition_type: rsiType, threshold: Number(rsi) }] : [])].filter(x => Number.isFinite(x.threshold))
    if (!rules.length) return setError('Select at least one valid alert.')
    if (short && intel.side !== 'SHORT' && priceOn) return setError('No bearish entry plan is available.')
    setBusy(true); setError('')
    try {
      for (const rule of rules) {
        const r = await fetch('/api/v2/watch/alerts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, ...rule }) })
        const p = root(await r.json().catch(() => ({}))); if (!r.ok || p?.ok === false) throw new Error(p?.error || 'alert failed')
      }
      await armed(rules.map(x => `${x.condition_type} ${x.threshold}`).join(' + '))
    } catch (e: any) { setError(e?.message || 'alert failed'); setBusy(false) }
  }
  return <Modal title={`${symbol} · Re-Entry Alerts`} subtitle="Persistent notifications only; no trade approval or submission." close={close}>
    <div style={{ ...panel, padding: 12, marginBottom: 10 }}><label><input type="checkbox" checked={priceOn} onChange={e => setPriceOn(e.target.checked)} /> <b>Price reaches candidate zone</b></label><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8, opacity: priceOn ? 1 : .45 }}><select disabled={!priceOn} value={priceType} onChange={e => setPriceType(e.target.value)} style={input}><option value="price_cross_below">Price crosses below</option><option value="price_cross_above">Price crosses above</option></select><input disabled={!priceOn} type="number" value={price} onChange={e => setPrice(e.target.value)} style={input}/></div></div>
    <div style={{ ...panel, padding: 12 }}><label><input type="checkbox" checked={rsiOn} onChange={e => setRsiOn(e.target.checked)} /> <b>RSI reaches review threshold</b></label><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8, opacity: rsiOn ? 1 : .45 }}><select disabled={!rsiOn} value={rsiType} onChange={e => setRsiType(e.target.value)} style={input}><option value="rsi_below">RSI crosses below</option><option value="rsi_above">RSI crosses above</option></select><input disabled={!rsiOn} type="number" min="0" max="100" value={rsi} onChange={e => setRsi(e.target.value)} style={input}/></div></div>
    {error && <div style={{ color: C.red, fontSize: 10.5, marginTop: 9 }}>{error}</div>}
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={close} style={btn()}>CANCEL</button><button disabled={busy} onClick={() => void arm()} style={{ ...btn(true), color: C.amber, borderColor: C.amber }}>{busy ? 'ARMING…' : 'ARM ALERTS'}</button></div>
  </Modal>
}
