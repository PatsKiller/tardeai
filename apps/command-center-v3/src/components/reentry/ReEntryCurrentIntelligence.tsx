import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'
import { HelpTip } from './ReEntryHelpGuide'
import { LevelLines, useLevels } from '../../lib/supportResistance'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  EXIT_CACHE_KEY,
  MANDATE_KEY,
  RESISTANCE_KEY,
  SHARED_CONTEXT_KEY,
  REENTRY_FLAGS,
  classificationLabel,
  classificationState,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  rowPrice,
  rowShares,
  text,
  unwrap,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'

type IntelState = 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT FOR PULLBACK' | 'OVERSOLD REVIEW' | 'OVERBOUGHT WAIT' | 'CURRENTLY HELD' | 'STALE DATA' | 'NO CURRENT COVERAGE'
type Summary = { symbol: string; rows: ExitEvidenceRow[]; latest: ExitEvidenceRow; shares: number | null; avgExit: number | null; proceeds: number }
type Intel = {
  last: number | null
  rsi: number | null
  rsiZone: 'OVERSOLD' | 'NEUTRAL' | 'OVERBOUGHT' | 'UNAVAILABLE'
  entryLow: number | null
  entryHigh: number | null
  stop: number | null
  target: number | null
  distancePct: number | null
  state: IntelState
  action: string
  why: string
  trend: string
  asOf: string | null
}
type Resistance = { state: string; resistance: number | null; distance_pct: number | null; hold_days: number | null; reason: string; as_of: string | null; source: string }

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

function useJson(url: string, refreshMs = 120_000) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let dead = false
    const controller = new AbortController()
    setLoading(true); setError('')
    fetch(url, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || String(response.status))
        if (!dead) setData(payload?.data && typeof payload.data === 'object' ? payload.data : payload)
      })
      .catch(value => { if (!dead && value?.name !== 'AbortError') setError(String(value?.message || value)) })
      .finally(() => { if (!dead) setLoading(false) })
    const timer = refreshMs > 0 ? window.setTimeout(() => setTick(value => value + 1), refreshMs) : 0
    return () => { dead = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [url, tick, refreshMs])
  return { data, error, loading, refetch: () => setTick(value => value + 1) }
}
function path(value: any, key: string): any { return key.split('.').reduce((result: any, part) => result?.[part], value) }
function numberFrom(objects: any[], paths: string[]): number | null { for (const object of objects) for (const key of paths) { const value = finite(path(object, key)); if (value !== null) return value } return null }
function textFrom(objects: any[], paths: string[]): string | null { for (const object of objects) for (const key of paths) { const value = text(path(object, key)); if (value) return value } return null }
function money(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function age(value: string | null): string { if (!value) return 'timestamp unavailable'; const time = new Date(value).getTime(); if (!Number.isFinite(time)) return value.slice(0, 16); const hours = Math.max(0, Math.round((Date.now() - time) / 36e5)); return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old` }
function stateColor(state: IntelState): string { if (state === 'READY TO REVIEW') return BB.green; if (state === 'NEAR ENTRY' || state === 'OVERSOLD REVIEW') return BB.amber; if (state === 'OVERBOUGHT WAIT') return BB.red; if (state === 'WAIT FOR PULLBACK') return BB.blue; if (state === 'CURRENTLY HELD') return BB.amberAlt; return BB.text3 }
function classificationTone(state: string): string { return state === 'CLASSIFIED' ? BB.green : state === 'AUTO-TAGGED' ? BB.amber : BB.text3 }
function classify(symbols: string[]) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbols } })); window.setTimeout(() => document.getElementById('reentry-exit-summary')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50) }

function deriveIntel(watch: any, card: any, mandate: ReEntryMandate, held: boolean, level?: any): Intel {
  // An exited symbol is usually status='removed' in watchlist_items, so the per-symbol
  // watch lookup returns nothing and price/RSI arrive null — the desk then reported
  // "NO CURRENT COVERAGE" for names whose closes were in ticker_prices all along. The
  // level cache computes both from that same closed-session series, so it backstops the
  // watch row rather than replacing it: live enrichment still wins when present.
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.current_mechanics ?? packet?.mechanics ?? watch?.reentry_plan ?? card?.reentry_plan ?? {}
  const objects = [watch ?? {}, card ?? {}, packet ?? {}, mechanics ?? {}, level ?? {}]
  const last = numberFrom(objects, ['last_price', 'price', 'current_price', 'quote_price', 'quote.last', 'market.last', 'current_close'])
  const rsi = numberFrom(objects, ['rsi', 'rsi_14', 'current_rsi', 'technical.rsi', 'technicals.rsi', 'indicators.rsi'])
  let entryLow = numberFrom(objects, ['reentry_low', 'reentry_zone_low', 'entry_zone_low', 'entry_low', 'mechanics.entry_low', 'selected_family.mechanics.entry_low'])
  let entryHigh = numberFrom(objects, ['reentry_high', 'reentry_zone_high', 'entry_zone_high', 'entry_high', 'mechanics.entry_high', 'selected_family.mechanics.entry_high'])
  const entry = numberFrom(objects, ['reentry_price', 'entry_limit', 'entry_price', 'mechanics.entry', 'selected_family.mechanics.entry'])
  if (entryLow === null) entryLow = entry
  if (entryHigh === null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]
  const stop = numberFrom(objects, ['reentry_stop', 'entry_stop', 'stop_price', 'mechanics.stop', 'selected_family.mechanics.stop'])
  const target = numberFrom(objects, ['reentry_target', 'entry_target', 'target_price', 'mechanics.target', 'selected_family.mechanics.target'])
  const asOf = textFrom(objects, ['last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote_time', 'technicals.as_of', 'decision_packet_at', 'rsi_as_of'])
  const trend = textFrom(objects, ['trend_direction', 'trend_state', 'technicals.trend', 'technical.trend', 'selected_family.mechanics.trend'])?.replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE'
  let distancePct: number | null = null
  if (last !== null && entryLow !== null && entryHigh !== null && entryLow > 0 && entryHigh > 0) distancePct = last > entryHigh ? ((last - entryHigh) / entryHigh) * 100 : last < entryLow ? -((entryLow - last) / entryLow) * 100 : 0
  const rsiZone: Intel['rsiZone'] = rsi === null ? 'UNAVAILABLE' : rsi <= 30 ? 'OVERSOLD' : rsi >= 70 ? 'OVERBOUGHT' : 'NEUTRAL'
  const stale = !asOf || !Number.isFinite(new Date(asOf).getTime()) || Date.now() - new Date(asOf).getTime() > 96 * 36e5
  const isShort = Boolean(mandate.flags.short)
  let state: IntelState = 'WAIT FOR PULLBACK'; let action = 'Keep monitoring'; let why = 'Price and momentum have not reached review conditions.'
  if (held) { state = 'CURRENTLY HELD'; action = 'Review as an existing holding'; why = 'The symbol is currently held, so it is not a clean re-entry-only candidate.' }
  else if (last === null || rsi === null) { state = 'NO CURRENT COVERAGE'; action = 'Refresh technical coverage'; why = 'Current price and RSI are required.' }
  else if (stale) { state = 'STALE DATA'; action = 'Refresh market and technical data'; why = `The current packet is ${age(asOf)}.` }
  else if (entryLow === null || entryHigh === null) { state = 'NO CURRENT COVERAGE'; action = 'Build a candidate entry zone'; why = 'Price and RSI exist, but no validated entry range is available.' }
  else if (!isShort && distancePct === 0 && rsi <= 45) { state = 'READY TO REVIEW'; action = 'Review long re-entry now'; why = 'Price is in the entry zone and RSI is not extended.' }
  else if (!isShort && distancePct !== null && distancePct >= 0 && distancePct <= 3) { state = 'NEAR ENTRY'; action = 'Prepare a re-entry review'; why = `Price is ${distancePct.toFixed(1)}% above the entry zone.` }
  else if (!isShort && rsi <= 30) { state = 'OVERSOLD REVIEW'; action = 'Review for stabilization'; why = 'RSI is oversold; confirmation is still required.' }
  else if (!isShort && rsi >= 70) { state = 'OVERBOUGHT WAIT'; action = 'Wait for a pullback'; why = 'RSI is overbought and extended.' }
  else if (isShort && distancePct === 0 && rsi >= 60) { state = 'READY TO REVIEW'; action = 'Review short entry now'; why = 'Price is in the short-side entry zone and RSI supports review.' }
  return { last, rsi, rsiZone, entryLow, entryHigh, stop, target, distancePct, state, action, why, trend, asOf }
}

function parseResistanceText(value: string): number | null {
  const match = value.match(/resistance\s+\$?([0-9]+(?:\.[0-9]+)?)/i)
  return match ? Number(match[1]) : null
}
function resistanceFor(symbol: string, cached: any, shared: any, watch: any, card: any, last: number | null): Resistance {
  const primary = cached ?? shared?.resistance
  if (primary && String(primary.state || '').toUpperCase() !== 'UNAVAILABLE') return {
    state: String(primary.state || 'UNAVAILABLE').toUpperCase(), resistance: finite(primary.resistance), distance_pct: finite(primary.distance_pct), hold_days: finite(primary.hold_days), reason: text(primary.reason, primary.method, 'Closed-session resistance cache.'), as_of: text(primary.as_of) || null, source: 'CLOSED-SESSION CACHE',
  }
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const triggerText = text(packet?.primary_action?.trigger, packet?.action_policy?.trigger, packet?.selected_family?.mechanics?.trigger, watch?.trigger, watch?.action_trigger)
  const level = finite(watch?.resistance, watch?.resistance_level, card?.resistance, packet?.selected_family?.mechanics?.resistance, parseResistanceText(triggerText))
  if (level !== null && last !== null && level > 0) {
    const distance = ((last - level) / level) * 100
    return { state: Math.abs(distance) <= 0.5 ? 'TESTING' : distance > 0 ? 'ABOVE' : 'BELOW', resistance: level, distance_pct: distance, hold_days: null, reason: `Watch decision-packet fallback${triggerText ? `: ${triggerText}` : ''}. Completed-session hold count waits for the resistance cache.`, as_of: text(watch?.decision_packet_at, watch?.last_enriched_at) || null, source: 'WATCH FALLBACK' }
  }
  return { state: 'UNAVAILABLE', resistance: null, distance_pct: null, hold_days: null, reason: `${symbol}: no valid closed-session resistance row and no parsable Watch resistance trigger. Refresh Watch inputs/evaluator.`, as_of: null, source: 'MISSING EVIDENCE' }
}

export default function ReEntryCurrentIntelligence() {
  const cache = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const history = useJson('/api/v2/redeploy/history?days=365', 120_000)
  const cards = useJson('/api/v2/symbol-cards', 300_000)
  const holdings = useJson('/api/v2/portfolio/holdings', 120_000)
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const alerts = useJson('/api/v2/watch/alerts/list', 120_000)
  const regime = useJson('/api/v2/risk-regime/latest', 300_000)
  const resistancePref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(RESISTANCE_KEY)}`, 120_000)
  const sharedPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(SHARED_CONTEXT_KEY)}`, 120_000)
  const analyst = useJson('/api/v2/pro-analyst/pills?map=1', 300_000)
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [classificationFilter, setClassificationFilter] = useState('ALL')
  const [queueFilter, setQueueFilter] = useState<'ACTIVE' | 'SUPPRESSED' | 'ALL'>('ACTIVE')
  const levels = useLevels()
  const [loadingIntel, setLoadingIntel] = useState(false)
  const [reload, setReload] = useState(0)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const cachePayload = prefValue(cache.data)
  const cacheRows: ExitEvidenceRow[] = Array.isArray(cachePayload?.rows) ? cachePayload.rows : []
  const fallbackRows: ExitEvidenceRow[] = unwrap(history.data)?.rows ?? []
  const sourceRows = cacheRows.length ? cacheRows : fallbackRows
  const mandates: Record<string, ReEntryMandate> = prefMap(mandatesPref.data) as Record<string, ReEntryMandate>
  const events: Record<string, ReEntryEvent> = prefMap(eventsPref.data) as Record<string, ReEntryEvent>
  const dispositions: Record<string, ReEntryDisposition> = prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>
  const sharedMap: Record<string, any> = prefValue(sharedPref.data)?.symbols ?? {}

  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of sourceRows) { const symbol = String(row.symbol || '').toUpperCase(); if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), { ...row, symbol }]) }
    return [...groups.entries()].map(([symbol, rows]) => {
      const sorted = rows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let shares = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of sorted) { const amount = rowShares(row); const price = rowPrice(row); const rowProceeds = finite(row.proceeds_usd); if (amount !== null) { known = true; shares += amount; if (price !== null) weighted += amount * price } if (rowProceeds !== null) proceeds += Math.abs(rowProceeds) }
      return { symbol, rows: sorted, latest: sorted[0], shares: known ? shares : null, avgExit: shares > 0 && weighted > 0 ? weighted / shares : null, proceeds } satisfies Summary
    })
  }, [sourceRows])

  const symbols = useMemo(() => summaries.map(summary => summary.symbol).slice(0, 300), [summaries])
  useEffect(() => {
    if (!symbols.length) return
    let dead = false; let cursor = 0
    const controller = new AbortController(); const output: Record<string, any> = {}; setLoadingIntel(true)
    const worker = async () => { while (!dead) { const index = cursor++; if (index >= symbols.length) return; const symbol = symbols[index]; try { const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal: controller.signal }); const payload = unwrap(await response.json()); output[symbol] = (payload?.items ?? [])[0] ?? null } catch { output[symbol] = null } } }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, () => worker())).finally(() => { if (!dead) { setWatchMap(previous => ({ ...previous, ...output })); setLoadingIntel(false) } })
    return () => { dead = true; controller.abort() }
  }, [symbols.join('|'), reload])

  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const held = new Set<string>((unwrap(holdings.data)?.holdings ?? []).filter((row: any) => Number(row.shares ?? row.quantity ?? 0) > 0).map((row: any) => String(row.symbol || '').toUpperCase()))
  const alertRows: any[] = unwrap(alerts.data)?.alerts ?? unwrap(alerts.data)?.items ?? []
  const resistanceMap: Record<string, any> = prefValue(resistancePref.data)?.symbols ?? {}
  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}

  const rows = useMemo(() => summaries.map(summary => {
    const mandate = normalizedMandate(mandates[summary.symbol])
    const watch = watchMap[summary.symbol]
    const card = cardMap[summary.symbol]
    const intel = deriveIntel(watch, card, mandate, held.has(summary.symbol), resistanceMap[summary.symbol])
    const move = summary.avgExit !== null && intel.last !== null && summary.avgExit > 0 ? ((intel.last - summary.avgExit) / summary.avgExit) * 100 : null
    const alertsCount = alertRows.filter(row => String(row.symbol || '').toUpperCase() === summary.symbol && !['disabled', 'expired', 'resolved'].includes(String(row.status || '').toLowerCase())).length
    const classified = classificationState(mandate, summary.rows, events, dispositions, sharedMap[summary.symbol])
    const resistance = resistanceFor(summary.symbol, resistanceMap[summary.symbol], sharedMap[summary.symbol], watch, card, intel.last)
    // Suppressed = every exit for the symbol is operator-suppressed. Source history is
    // never deleted; the symbol just leaves the default re-entry queue.
    const suppressed = summary.rows.length > 0 && summary.rows.every(row => normalizedDisposition(dispositions[row.event_key]).state === 'suppressed')
    return { ...summary, mandate, intel, move, alertsCount, resistance, analyst: analystMap[summary.symbol] ?? null, shared: sharedMap[summary.symbol] ?? null, classified, suppressed }
  }), [summaries, mandatesPref.data, eventsPref.data, dispositionsPref.data, watchMap, cards.data, holdings.data, alerts.data, resistancePref.data, analyst.data, sharedPref.data])

  const shown = rows.filter(row => {
    if (queueFilter === 'ACTIVE' && row.suppressed) return false
    if (queueFilter === 'SUPPRESSED' && !row.suppressed) return false
    if (search.trim() && !`${row.symbol} ${row.intel.state} ${row.intel.action} ${row.classified} ${row.shared?.journal_annotation ?? ''}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    if (stateFilter !== 'ALL' && row.intel.state !== stateFilter) return false
    if (classificationFilter !== 'ALL' && row.classified !== classificationFilter) return false
    return true
  }).sort((a, b) => {
    const priority: Record<string, number> = { HIGH: 0, NORMAL: 1, LOW: 2 }
    return (priority[String(a.mandate.priority || 'NORMAL')] ?? 1) - (priority[String(b.mandate.priority || 'NORMAL')] ?? 1) || String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || ''))
  })

  const selectedSymbols = shown.filter(row => selected[row.symbol]).map(row => row.symbol)
  const counts = {
    symbols: rows.length,
    classified: rows.filter(row => row.classified === 'CLASSIFIED').length,
    ready: rows.filter(row => row.intel.state === 'READY TO REVIEW').length,
    near: rows.filter(row => row.intel.state === 'NEAR ENTRY').length,
    stale: rows.filter(row => ['STALE DATA', 'NO CURRENT COVERAGE'].includes(row.intel.state)).length,
  }
  const regimeLabel = text(unwrap(regime.data)?.regime_label, unwrap(regime.data)?.label, 'unknown').replace(/_/g, ' ').toUpperCase()
  const kpis = [
    { label: 'EXITED SYMBOLS', value: counts.symbols, color: BB.blue, tip: 'All symbols in the trailing exit universe. Click to clear status and classification filters.', action: () => { setStateFilter('ALL'); setClassificationFilter('ALL') }, active: stateFilter === 'ALL' && classificationFilter === 'ALL' },
    { label: 'CLASSIFIED', value: counts.classified, color: BB.green, tip: 'Operator-saved mandate/event/disposition. Click to show only green CLASSIFIED rows.', action: () => setClassificationFilter(value => value === 'CLASSIFIED' ? 'ALL' : 'CLASSIFIED'), active: classificationFilter === 'CLASSIFIED' },
    { label: 'READY NOW', value: counts.ready, color: BB.green, tip: 'Price is in the current entry zone and momentum is not extended. Advisory review only; click to filter.', action: () => setStateFilter(value => value === 'READY TO REVIEW' ? 'ALL' : 'READY TO REVIEW'), active: stateFilter === 'READY TO REVIEW' },
    { label: 'NEAR ENTRY', value: counts.near, color: BB.amber, tip: 'Price is within 3% above the current entry zone. Click to filter these candidates.', action: () => setStateFilter(value => value === 'NEAR ENTRY' ? 'ALL' : 'NEAR ENTRY'), active: stateFilter === 'NEAR ENTRY' },
    { label: 'MISSING / STALE', value: counts.stale, color: BB.red, tip: 'Current price/RSI/entry evidence is missing or older than the validity window. Click to isolate data work.', action: () => setStateFilter(value => value === 'STALE DATA' ? 'ALL' : 'STALE DATA'), active: stateFilter === 'STALE DATA' },
  ]

  return <div style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 18, fontWeight: 900 }}>CURRENT RE-ENTRY INTELLIGENCE <HelpTip text="Every row now expands. KPI headers filter. Checkboxes support bulk classification. Tooltips explain the current symbol-specific evidence." /></div><div style={{ fontSize: 10.5, color: BB.text3 }}>Market regime {regimeLabel} · Watch, Journal, analyst, resistance and Re-Entry evidence share one operator context · advisory only</div></div><button onClick={() => { cache.refetch(); history.refetch(); cards.refetch(); holdings.refetch(); alerts.refetch(); regime.refetch(); resistancePref.refetch(); analyst.refetch(); sharedPref.refetch(); setReload(value => value + 1) }} style={{ ...button(false), marginLeft: 'auto' }}>{loadingIntel ? 'LOADING CURRENT STATUS…' : 'REFRESH ALL SOURCES'}</button></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(120px,1fr))', gap: 7, marginTop: 9 }}>{kpis.map(kpi => <button key={kpi.label} onClick={kpi.action} title={kpi.tip} style={{ ...panel, background: kpi.active ? `${kpi.color}18` : 'var(--bg2)', padding: 9, textAlign: 'left', cursor: 'pointer', color: 'var(--text0)', outline: kpi.active ? `1px solid ${kpi.color}` : 'none' }}><span style={{ color: BB.text3, fontSize: 10 }}>{kpi.label} ⓘ</span><br /><b style={{ fontSize: 20, color: kpi.color }}>{kpi.value}</b></button>)}</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(200px,1fr) 210px 180px 210px auto auto auto', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, state, classification or annotation…" style={field} /><select value={stateFilter} onChange={event => setStateFilter(event.target.value)} title="Filter by current Re-Entry state" style={field}><option value="ALL">ALL CURRENT STATES</option>{['READY TO REVIEW', 'NEAR ENTRY', 'WAIT FOR PULLBACK', 'OVERSOLD REVIEW', 'OVERBOUGHT WAIT', 'CURRENTLY HELD', 'STALE DATA', 'NO CURRENT COVERAGE'].map(state => <option key={state}>{state}</option>)}</select><select value={classificationFilter} onChange={event => setClassificationFilter(event.target.value)} title="Green operator-saved, amber auto-tagged or gray unclassified" style={field}><option value="ALL">ALL CLASSIFICATIONS</option><option>CLASSIFIED</option><option>AUTO-TAGGED</option><option>UNCLASSIFIED</option></select><select value={queueFilter} onChange={event => setQueueFilter(event.target.value as typeof queueFilter)} title="Suppressed symbols are ones you chose not to track. Set this per symbol in CLASSIFY → QUEUE DISPOSITION → SUPPRESS. Broker history is never deleted." style={field}><option value="ACTIVE">ACTIVE · HIDE SUPPRESSED</option><option value="SUPPRESSED">SUPPRESSED ONLY</option><option value="ALL">ALL · INCLUDE SUPPRESSED</option></select><button onClick={() => setSelected(Object.fromEntries(shown.map(row => [row.symbol, true])))} title={`Select all ${shown.length} currently filtered symbols`} style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelected({})} style={button(false)}>CLEAR</button><button disabled={!selectedSymbols.length} onClick={() => classify(selectedSymbols)} title="Open one multi-symbol classification modal" style={{ ...button(Boolean(selectedSymbols.length)), opacity: selectedSymbols.length ? 1 : .5, color: selectedSymbols.length ? BB.green : BB.text3, borderColor: selectedSymbols.length ? BB.green : 'var(--border)' }}>EDIT SELECTED {selectedSymbols.length}</button></div>
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1590 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 175px 240px 115px 85px 115px 155px 190px 190px 160px 70px', gap: 8, padding: '7px 9px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol / classification</span><span>Current status / action</span><span>Last / avg exit</span><span>RSI</span><span>Pullback</span><span>Candidate entry</span><span>Resistance</span><span>Portfolio flags</span><span>Analyst</span><span>Alerts</span></div>{shown.map(row => {
      const tone = stateColor(row.intel.state)
      const classTone = classificationTone(row.classified)
      const flags = REENTRY_FLAGS.filter(flag => row.mandate.flags[flag]).map(flag => flag.toUpperCase())
      const resistanceTone = row.resistance.state === 'ABOVE' ? BB.green : row.resistance.state === 'BELOW' ? BB.red : row.resistance.state === 'TESTING' ? BB.amber : BB.text3
      const rec = text(row.analyst?.rec, row.analyst?.recommendation).replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE'
      const open = Boolean(expanded[row.symbol])
      const event = normalizedEvent(row.latest, events[row.latest.event_key])
      return <div key={row.symbol}><div onClick={() => setExpanded(value => ({ ...value, [row.symbol]: !open }))} title={`${row.symbol}: ${row.intel.state}. ${row.intel.why} Click to ${open ? 'collapse' : 'expand'} full evidence.`} style={{ display: 'grid', gridTemplateColumns: '28px 175px 240px 115px 85px 115px 155px 190px 190px 160px 70px', gap: 8, padding: '9px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: open ? BB.blueDim : 'transparent' }}><input type="checkbox" checked={Boolean(selected[row.symbol])} onClick={event => event.stopPropagation()} onChange={event => setSelected(value => ({ ...value, [row.symbol]: event.target.checked }))} title={`Select ${row.symbol} for bulk classification`} /><div><div style={{ display: 'flex', alignItems: 'center', gap: 5 }}><b style={{ fontSize: 14 }}>{row.symbol}</b><span style={{ color: classTone, border: `1px solid ${classTone}88`, background: `${classTone}18`, borderRadius: 4, padding: '2px 5px', fontSize: 10, fontWeight: 900 }}>{classificationLabel(row.classified)}</span><span style={{ color: BB.text3 }}>{open ? '▾' : '▸'}</span></div><div style={{ color: BB.text3 }}>{row.rows.length} exits · {row.shares === null ? 'shares unavailable' : `${row.shares.toLocaleString()} sh`}</div><button onClick={event => { event.stopPropagation(); classify([row.symbol]) }} title={`${row.symbol}: edit mandate, multi-select strategy flags, exit reason and queue state`} style={{ ...button(row.classified === 'CLASSIFIED'), padding: '3px 7px', marginTop: 5, color: classTone, borderColor: classTone }}>{row.classified === 'CLASSIFIED' ? 'EDIT CLASSIFICATION' : 'CLASSIFY'}</button></div><div title={`${row.symbol}: ${row.intel.why}`}><span style={{ color: tone, border: `1px solid ${tone}`, borderRadius: 4, padding: '2px 6px', fontSize: 10, fontWeight: 900 }}>{row.intel.state}</span><div style={{ fontWeight: 850, marginTop: 4 }}>{row.intel.action}</div><div style={{ color: BB.text3 }}>{row.intel.why}</div></div><div title={`${row.symbol}: current ${money(row.intel.last)}, share-weighted average exit ${money(row.avgExit)}`}><b>{money(row.intel.last)}</b><br /><span style={{ color: row.move === null ? BB.text3 : row.move >= 0 ? BB.green : BB.red }}>{row.move === null ? `avg exit ${money(row.avgExit)}` : `${row.move >= 0 ? '+' : ''}${row.move.toFixed(1)}% vs avg exit`}</span></div><div title={`${row.symbol}: RSI ${row.intel.rsi === null ? 'unavailable' : row.intel.rsi.toFixed(1)}; ${row.intel.rsiZone}`}><b style={{ fontSize: 14, color: row.intel.rsiZone === 'OVERSOLD' ? BB.green : row.intel.rsiZone === 'OVERBOUGHT' ? BB.red : 'var(--text1)' }}>{row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)}</b><br /><span style={{ color: BB.text3 }}>{row.intel.rsiZone}</span></div><div title={`${row.symbol}: distance from the validated entry zone; negative means below the zone`}><b style={{ color: row.intel.distancePct === 0 ? BB.green : row.intel.distancePct !== null && Math.abs(row.intel.distancePct) <= 3 ? BB.amber : 'var(--text1)' }}>{row.intel.distancePct === null ? '—' : row.intel.distancePct === 0 ? 'IN ZONE' : `${Math.abs(row.intel.distancePct).toFixed(1)}% ${row.intel.distancePct > 0 ? 'above' : 'below'}`}</b><br /><span style={{ color: BB.text3 }}>{row.intel.trend} · {age(row.intel.asOf)}</span></div><div title={`${row.symbol}: current Watch/decision-packet entry mechanics`}><b>{row.intel.entryLow === null ? '—' : row.intel.entryLow === row.intel.entryHigh ? money(row.intel.entryLow) : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}</b><br /><span style={{ color: BB.text3 }}>stop {money(row.intel.stop)} · target {money(row.intel.target)}</span></div><div title={`${row.symbol}: ${row.resistance.reason} Source ${row.resistance.source}.`}><b style={{ color: resistanceTone }}>{row.resistance.state} · {row.resistance.distance_pct == null ? '—' : `${row.resistance.distance_pct >= 0 ? '+' : ''}${Number(row.resistance.distance_pct).toFixed(1)}%`}</b><br /><span style={{ color: BB.text3 }}>resistance {money(row.resistance.resistance)} · held {row.resistance.hold_days ?? '—'} closes</span><br /><span style={{ color: row.resistance.state === 'UNAVAILABLE' ? BB.red : BB.text3 }}>{row.resistance.source}</span><LevelLines symbol={row.symbol} row={levels[row.symbol]} /></div><div title={`${row.symbol}: persistent operator mandate and independent multi-select strategy flags`}><b>{row.mandate.mandate.toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{flags.join(' · ') || 'NO FLAGS'} · {row.mandate.targetAccount || 'no target account'}</span></div><div title={`${row.symbol}: current professional consensus; this cannot override technical, regime, resistance or account gates`}><b>{rec}</b><br /><span style={{ color: BB.text3 }}>{row.analyst?.n ?? '—'} analysts · target {row.analyst?.target == null ? '—' : money(Number(row.analyst.target))}{row.analyst?.upside == null ? '' : ` · ${Number(row.analyst.upside) >= 0 ? '+' : ''}${Number(row.analyst.upside).toFixed(1)}%`}</span></div><div title={`${row.symbol}: ${row.alertsCount} active Watch/Re-Entry alerts`}><b style={{ color: row.alertsCount ? BB.amber : BB.text3 }}>🔔 {row.alertsCount}</b></div></div>
      {open && <div style={{ padding: '10px 14px 14px 42px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1.1fr .9fr', gap: 18 }}><div><div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>EXIT HISTORY — TRAILING 12 MONTHS</div>{row.rows.map(exit => { const classifiedEvent = normalizedEvent(exit, events[exit.event_key]); return <div key={exit.event_key} style={{ display: 'grid', gridTemplateColumns: '90px 120px 90px 90px 100px 1fr', gap: 7, fontSize: 10, padding: '4px 0', borderBottom: '1px solid var(--border)' }}><span>{exit.trade_date ?? '—'}</span><span>{exit.account ?? '—'}</span><span>{rowShares(exit) === null ? '—' : `${rowShares(exit)?.toLocaleString()} sh`}</span><span>{money(rowPrice(exit))}</span><span>{money(finite(exit.proceeds_usd))}</span><span><b style={{ color: classifiedEvent.updatedAt ? BB.green : BB.amber }}>{classifiedEvent.updatedAt ? 'SAVED' : 'AUTO'} · {classifiedEvent.eventType.replace(/_/g, ' ').toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{classifiedEvent.reason}</span></span></div>})}</div><div><div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>SHARED WATCH / JOURNAL CONTEXT</div><div style={{ fontSize: 10.5, lineHeight: 1.55 }}><b>Classification:</b> <span style={{ color: classTone }}>{classificationLabel(row.classified)}</span><br /><b>Latest event:</b> {event.eventType.replace(/_/g, ' ').toUpperCase()} — {event.reason}<br /><b>Resistance:</b> {row.resistance.state} at {money(row.resistance.resistance)} — {row.resistance.reason}<br /><b>Watch:</b> {row.shared?.watch?.recommendation ?? 'unavailable'} · {row.shared?.watch?.sector ?? 'sector unavailable'} · {row.shared?.watch?.regime ?? 'regime unavailable'}<br /><b>Earnings:</b> {row.shared?.watch?.earnings_date ?? 'not in shared evidence'}<br /><b>Catalyst:</b> {row.shared?.watch?.catalyst ?? 'not in shared evidence'}<br /><b>Journal annotation:</b> {row.shared?.journal_annotation ?? 'Shared cache has not been refreshed yet.'}<br /><b>Thesis:</b> {row.mandate.thesis || 'No operator thesis saved.'}</div><div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>{(row.shared?.annotations ?? []).slice(0, 10).map((item: any, index: number) => <span key={`${item.label}-${index}`} title={`${item.detail ?? ''}${item.source ? ` · source ${item.source}` : ''}`} style={{ color: BB.blue, border: `1px solid ${BB.blue}66`, borderRadius: 4, padding: '3px 6px', fontSize: 10, cursor: 'help' }}>{item.label}</span>)}</div></div></div>}</div>
    })}</div></div>
    {(cache.error || sharedPref.error || resistancePref.error) && <div style={{ color: BB.red, fontSize: 10, marginTop: 6 }}>Data warning: {[cache.error, sharedPref.error, resistancePref.error].filter(Boolean).join(' · ')}</div>}
    {!shown.length && <div style={{ padding: 14, color: BB.text3 }}>No symbols match the current filters.</div>}
  </div>
}
