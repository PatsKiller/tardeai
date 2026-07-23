import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'
import { HelpTip } from './ReEntryHelpGuide'

const EXIT_CACHE_KEY = 'portfolio.reentry.exit-universe.v1'
const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const RESISTANCE_KEY = 'portfolio.reentry.resistance.v1'

type IntelState = 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT FOR PULLBACK' | 'OVERSOLD REVIEW' | 'OVERBOUGHT WAIT' | 'CURRENTLY HELD' | 'STALE DATA' | 'NO CURRENT COVERAGE'
type ExitRow = { event_key: string; symbol: string; trade_date?: string | null; quantity?: number | null; price?: number | null; proceeds_usd?: number | null; account?: string | null }
type Mandate = { mandate?: string; flags?: Record<string, boolean>; targetAccount?: string; targetWeightPct?: number | null; priority?: string; thesis?: string }
type Summary = { symbol: string; rows: ExitRow[]; latest: ExitRow; shares: number | null; avgExit: number | null }
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
function unwrap(value: any): any { let result = value; for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function prefValue(value: any): any { const payload = unwrap(value); return payload?.value ?? payload }
function prefMap(value: any): Record<string, any> { const payload = prefValue(value); return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {} }
function finite(...values: any[]): number | null { for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value); return null }
function text(...values: any[]): string { for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim(); return '' }
function path(value: any, key: string): any { return key.split('.').reduce((result: any, part) => result?.[part], value) }
function numberFrom(objects: any[], paths: string[]): number | null { for (const object of objects) for (const key of paths) { const value = finite(path(object, key)); if (value !== null) return value } return null }
function textFrom(objects: any[], paths: string[]): string | null { for (const object of objects) for (const key of paths) { const value = text(path(object, key)); if (value) return value } return null }
function money(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function rowShares(row: ExitRow): number | null { const value = finite(row.quantity); return value === null ? null : Math.abs(value) }
function rowPrice(row: ExitRow): number | null { const direct = finite(row.price); if (direct !== null) return direct; const shares = rowShares(row); const proceeds = finite(row.proceeds_usd); return shares && proceeds !== null ? Math.abs(proceeds) / shares : null }
function age(value: string | null): string { if (!value) return 'timestamp unavailable'; const time = new Date(value).getTime(); if (!Number.isFinite(time)) return value.slice(0, 16); const hours = Math.max(0, Math.round((Date.now() - time) / 36e5)); return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old` }
function classify(symbol: string) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbol } })); window.setTimeout(() => document.getElementById('reentry-exit-summary')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50) }
function stateColor(state: IntelState): string { if (state === 'READY TO REVIEW') return BB.green; if (state === 'NEAR ENTRY' || state === 'OVERSOLD REVIEW') return BB.amber; if (state === 'OVERBOUGHT WAIT') return BB.red; if (state === 'WAIT FOR PULLBACK') return BB.blue; if (state === 'CURRENTLY HELD') return BB.amberAlt; return BB.text3 }

function deriveIntel(watch: any, card: any, mandate: Mandate, held: boolean): Intel {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.current_mechanics ?? packet?.mechanics ?? watch?.reentry_plan ?? card?.reentry_plan ?? {}
  const objects = [watch ?? {}, card ?? {}, packet ?? {}, mechanics ?? {}]
  const last = numberFrom(objects, ['last_price', 'price', 'current_price', 'quote_price', 'quote.last', 'market.last'])
  const rsi = numberFrom(objects, ['rsi', 'rsi_14', 'current_rsi', 'technical.rsi', 'technicals.rsi', 'indicators.rsi'])
  let entryLow = numberFrom(objects, ['reentry_low', 'reentry_zone_low', 'entry_zone_low', 'entry_low', 'mechanics.entry_low'])
  let entryHigh = numberFrom(objects, ['reentry_high', 'reentry_zone_high', 'entry_zone_high', 'entry_high', 'mechanics.entry_high'])
  const entry = numberFrom(objects, ['reentry_price', 'entry_limit', 'entry_price', 'mechanics.entry'])
  if (entryLow === null) entryLow = entry
  if (entryHigh === null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]
  const stop = numberFrom(objects, ['reentry_stop', 'entry_stop', 'stop_price', 'mechanics.stop'])
  const target = numberFrom(objects, ['reentry_target', 'entry_target', 'target_price', 'mechanics.target'])
  const asOf = textFrom(objects, ['last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote_time', 'technicals.as_of'])
  const trend = textFrom(objects, ['trend_direction', 'trend_state', 'technicals.trend', 'technical.trend'])?.replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE'
  let distancePct: number | null = null
  if (last !== null && entryLow !== null && entryHigh !== null && entryLow > 0 && entryHigh > 0) distancePct = last > entryHigh ? ((last - entryHigh) / entryHigh) * 100 : last < entryLow ? -((entryLow - last) / entryLow) * 100 : 0
  const rsiZone: Intel['rsiZone'] = rsi === null ? 'UNAVAILABLE' : rsi <= 30 ? 'OVERSOLD' : rsi >= 70 ? 'OVERBOUGHT' : 'NEUTRAL'
  const stale = !asOf || !Number.isFinite(new Date(asOf).getTime()) || Date.now() - new Date(asOf).getTime() > 96 * 36e5
  const isShort = Boolean(mandate?.flags?.short)
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

export default function ReEntryCurrentIntelligence() {
  const cache = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const history = useJson('/api/v2/redeploy/history?days=365', 120_000)
  const cards = useJson('/api/v2/symbol-cards', 300_000)
  const holdings = useJson('/api/v2/portfolio/holdings', 120_000)
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const alerts = useJson('/api/v2/watch/alerts/list', 120_000)
  const regime = useJson('/api/v2/risk-regime/latest', 300_000)
  const resistancePref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(RESISTANCE_KEY)}`, 120_000)
  const analyst = useJson('/api/v2/pro-analyst/pills?map=1', 300_000)
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [loadingIntel, setLoadingIntel] = useState(false)
  const [reload, setReload] = useState(0)
  const cachePayload = prefValue(cache.data)
  const cacheRows: ExitRow[] = Array.isArray(cachePayload?.rows) ? cachePayload.rows : []
  const fallbackRows: ExitRow[] = unwrap(history.data)?.rows ?? []
  const sourceRows = cacheRows.length ? cacheRows : fallbackRows
  const summaries = useMemo(() => {
    const groups = new Map<string, ExitRow[]>()
    for (const row of sourceRows) { const symbol = String(row.symbol || '').toUpperCase(); if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), { ...row, symbol }]) }
    return [...groups.entries()].map(([symbol, rows]) => {
      const sorted = rows.slice().sort((a, b) => String(b.trade_date || '').localeCompare(String(a.trade_date || '')))
      let shares = 0; let weighted = 0; let known = false
      for (const row of sorted) { const rowQty = rowShares(row); const price = rowPrice(row); if (rowQty !== null) { known = true; shares += rowQty; if (price !== null) weighted += rowQty * price } }
      return { symbol, rows: sorted, latest: sorted[0], shares: known ? shares : null, avgExit: shares > 0 && weighted > 0 ? weighted / shares : null } satisfies Summary
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
  const mandates = prefMap(mandatesPref.data)
  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const held = new Set<string>((unwrap(holdings.data)?.holdings ?? []).filter((row: any) => Number(row.shares ?? row.quantity ?? 0) > 0).map((row: any) => String(row.symbol || '').toUpperCase()))
  const alertRows: any[] = unwrap(alerts.data)?.alerts ?? unwrap(alerts.data)?.items ?? []
  const resistanceMap: Record<string, any> = prefValue(resistancePref.data)?.symbols ?? {}
  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}
  const rows = useMemo(() => summaries.map(summary => {
    const mandate = mandates[summary.symbol] ?? {}
    const intel = deriveIntel(watchMap[summary.symbol], cardMap[summary.symbol], mandate, held.has(summary.symbol))
    const move = summary.avgExit !== null && intel.last !== null && summary.avgExit > 0 ? ((intel.last - summary.avgExit) / summary.avgExit) * 100 : null
    const alertsCount = alertRows.filter(row => String(row.symbol || '').toUpperCase() === summary.symbol && !['disabled', 'expired', 'resolved'].includes(String(row.status || '').toLowerCase())).length
    return { ...summary, mandate, intel, move, alertsCount, resistance: resistanceMap[summary.symbol] ?? null, analyst: analystMap[summary.symbol] ?? null }
  }), [summaries, mandatesPref.data, watchMap, cards.data, holdings.data, alerts.data, resistancePref.data, analyst.data])
  const shown = rows.filter(row => (!search.trim() || `${row.symbol} ${row.intel.state} ${row.intel.action}`.toUpperCase().includes(search.trim().toUpperCase())) && (stateFilter === 'ALL' || row.intel.state === stateFilter)).sort((a, b) => {
    const priority: Record<string, number> = { HIGH: 0, NORMAL: 1, LOW: 2 }
    return (priority[String(a.mandate.priority || 'NORMAL')] ?? 1) - (priority[String(b.mandate.priority || 'NORMAL')] ?? 1) || String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || ''))
  })
  const regimeLabel = text(unwrap(regime.data)?.regime_label, unwrap(regime.data)?.label, 'unknown').replace(/_/g, ' ').toUpperCase()
  const counts = { ready: rows.filter(row => row.intel.state === 'READY TO REVIEW').length, near: rows.filter(row => row.intel.state === 'NEAR ENTRY').length, stale: rows.filter(row => ['STALE DATA', 'NO CURRENT COVERAGE'].includes(row.intel.state)).length }
  return <div style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 18, fontWeight: 900 }}>CURRENT RE-ENTRY INTELLIGENCE <HelpTip text="Restored actionable view: current status, last versus average exit, RSI, pullback distance, candidate entry, resistance, analyst consensus and alerts." /></div><div style={{ fontSize: 10.5, color: BB.text3 }}>Current status and next action are back on the first screen · market regime {regimeLabel} · advisory only</div></div><button onClick={() => { cache.refetch(); history.refetch(); cards.refetch(); holdings.refetch(); alerts.refetch(); regime.refetch(); resistancePref.refetch(); analyst.refetch(); setReload(value => value + 1) }} style={{ ...button(false), marginLeft: 'auto' }}>{loadingIntel ? 'LOADING CURRENT STATUS…' : 'REFRESH ALL SOURCES'}</button></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(120px,1fr))', gap: 7, marginTop: 9 }}><div style={{ ...panel, background: 'var(--bg2)', padding: 9 }}><span style={{ color: BB.text3, fontSize: 10 }}>EXITED SYMBOLS</span><br /><b style={{ fontSize: 20 }}>{rows.length}</b></div><div style={{ ...panel, background: 'var(--bg2)', padding: 9 }}><span style={{ color: BB.text3, fontSize: 10 }}>READY NOW</span><br /><b style={{ fontSize: 20, color: BB.green }}>{counts.ready}</b></div><div style={{ ...panel, background: 'var(--bg2)', padding: 9 }}><span style={{ color: BB.text3, fontSize: 10 }}>NEAR ENTRY</span><br /><b style={{ fontSize: 20, color: BB.amber }}>{counts.near}</b></div><div style={{ ...panel, background: 'var(--bg2)', padding: 9 }}><span style={{ color: BB.text3, fontSize: 10 }}>MISSING / STALE</span><br /><b style={{ fontSize: 20, color: BB.red }}>{counts.stale}</b></div></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,1fr) 230px', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol or current action…" style={field} /><select value={stateFilter} onChange={event => setStateFilter(event.target.value)} style={field}><option value="ALL">ALL CURRENT STATES</option>{['READY TO REVIEW', 'NEAR ENTRY', 'WAIT FOR PULLBACK', 'OVERSOLD REVIEW', 'OVERBOUGHT WAIT', 'CURRENTLY HELD', 'STALE DATA', 'NO CURRENT COVERAGE'].map(state => <option key={state}>{state}</option>)}</select></div>
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1490 }}><div style={{ display: 'grid', gridTemplateColumns: '150px 240px 115px 85px 115px 155px 170px 190px 160px 80px', gap: 8, padding: '7px 9px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol / classify</span><span>Current status / action</span><span>Last / avg exit</span><span>RSI</span><span>Pullback</span><span>Candidate entry</span><span>Resistance</span><span>Portfolio flags</span><span>Analyst</span><span>Alerts</span></div>{shown.map(row => {
      const tone = stateColor(row.intel.state)
      const flags = Object.entries(row.mandate.flags ?? {}).filter(([, active]) => active).map(([flag]) => flag.toUpperCase())
      const resistanceTone = row.resistance?.state === 'ABOVE' ? BB.green : row.resistance?.state === 'BELOW' ? BB.red : row.resistance?.state === 'TESTING' ? BB.amber : BB.text3
      const rec = text(row.analyst?.rec, row.analyst?.recommendation).replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE'
      return <div key={row.symbol} style={{ display: 'grid', gridTemplateColumns: '150px 240px 115px 85px 115px 155px 170px 190px 160px 80px', gap: 8, padding: '9px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}><div><b style={{ fontSize: 14 }}>{row.symbol}</b><div style={{ color: BB.text3 }}>{row.rows.length} exits · {row.shares === null ? 'shares unavailable' : `${row.shares.toLocaleString()} sh`}</div><button onClick={() => classify(row.symbol)} style={{ ...button(true), padding: '3px 7px', marginTop: 5 }}>CLASSIFY</button></div><div><span style={{ color: tone, border: `1px solid ${tone}`, borderRadius: 4, padding: '2px 6px', fontSize: 10, fontWeight: 900 }}>{row.intel.state}</span><div style={{ fontWeight: 850, marginTop: 4 }}>{row.intel.action}</div><div style={{ color: BB.text3 }}>{row.intel.why}</div></div><div><b>{money(row.intel.last)}</b><br /><span style={{ color: row.move === null ? BB.text3 : row.move >= 0 ? BB.green : BB.red }}>{row.move === null ? `avg exit ${money(row.avgExit)}` : `${row.move >= 0 ? '+' : ''}${row.move.toFixed(1)}% vs avg exit`}</span></div><div><b style={{ fontSize: 14, color: row.intel.rsiZone === 'OVERSOLD' ? BB.green : row.intel.rsiZone === 'OVERBOUGHT' ? BB.red : 'var(--text1)' }}>{row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)}</b><br /><span style={{ color: BB.text3 }}>{row.intel.rsiZone}</span></div><div><b style={{ color: row.intel.distancePct === 0 ? BB.green : row.intel.distancePct !== null && Math.abs(row.intel.distancePct) <= 3 ? BB.amber : 'var(--text1)' }}>{row.intel.distancePct === null ? '—' : row.intel.distancePct === 0 ? 'IN ZONE' : `${Math.abs(row.intel.distancePct).toFixed(1)}% ${row.intel.distancePct > 0 ? 'above' : 'below'}`}</b><br /><span style={{ color: BB.text3 }}>{row.intel.trend} · {age(row.intel.asOf)}</span></div><div><b>{row.intel.entryLow === null ? '—' : row.intel.entryLow === row.intel.entryHigh ? money(row.intel.entryLow) : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}</b><br /><span style={{ color: BB.text3 }}>stop {money(row.intel.stop)} · target {money(row.intel.target)}</span></div><div><b style={{ color: resistanceTone }}>{row.resistance?.state ?? 'UNAVAILABLE'} · {row.resistance?.distance_pct == null ? '—' : `${row.resistance.distance_pct >= 0 ? '+' : ''}${Number(row.resistance.distance_pct).toFixed(1)}%`}</b><br /><span style={{ color: BB.text3 }}>resistance {money(finite(row.resistance?.resistance))} · held {row.resistance?.hold_days ?? '—'} closes</span></div><div><b>{String(row.mandate.mandate || 'unclassified').toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{flags.join(' · ') || 'NO FLAGS'} · {row.mandate.targetAccount || 'no target account'}</span></div><div><b>{rec}</b><br /><span style={{ color: BB.text3 }}>{row.analyst?.n ?? '—'} analysts · target {row.analyst?.target == null ? '—' : money(Number(row.analyst.target))}{row.analyst?.upside == null ? '' : ` · ${Number(row.analyst.upside) >= 0 ? '+' : ''}${Number(row.analyst.upside).toFixed(1)}%`}</span></div><div><b style={{ color: row.alertsCount ? BB.amber : BB.text3 }}>🔔 {row.alertsCount}</b></div></div>
    })}</div></div>
    {!shown.length && <div style={{ padding: 14, color: BB.text3 }}>No symbols match the current filters.</div>}
  </div>
}
