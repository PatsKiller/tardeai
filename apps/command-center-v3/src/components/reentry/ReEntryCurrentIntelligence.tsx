import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  MANDATE_KEY,
  RESISTANCE_KEY,
  REENTRY_FLAGS,
  classificationLabel,
  classificationState,
  finite,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  rowPrice,
  rowShares,
  text,
  type ExitEvidenceField,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'
import { HelpTip } from './ReEntryHelpGuide'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 11.5, padding: '7px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

type Summary = { symbol: string; rows: ExitEvidenceRow[]; latest: ExitEvidenceRow; shares: number | null; avgExit: number | null; proceeds: number; eventGapCount: number; derivedCount: number }
type IntelState = 'READY TO REVIEW' | 'NEAR ENTRY' | 'WAIT' | 'CURRENTLY HELD' | 'STALE' | 'MISSING PLAN' | 'MISSING MARKET'
type Intel = { price: number | null; asOf: string; rsi: number | null; trend: string; entryLow: number | null; entryHigh: number | null; stop: number | null; target: number | null; distancePct: number | null; state: IntelState; action: string; reason: string }
type Resistance = { state: string; level: number | null; distancePct: number | null; holdDays: number | null; source: string; reason: string }

function unwrap(value: any): any { let result = value; for (let i = 0; i < 4 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function path(value: any, key: string): any { return key.split('.').reduce((result: any, part) => result?.[part], value) }
function numberFrom(objects: any[], paths: string[]): number | null { for (const object of objects) for (const key of paths) { const value = finite(path(object, key)); if (value !== null) return value } return null }
function textFrom(objects: any[], paths: string[]): string { for (const object of objects) for (const key of paths) { const value = text(path(object, key)); if (value) return value } return '' }
function money(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function age(value: string): string { if (!value) return 'as-of unavailable'; const time = new Date(value).getTime(); if (!Number.isFinite(time)) return value.slice(0, 16); const hours = Math.max(0, Math.round((Date.now() - time) / 36e5)); return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old` }
function classify(symbols: string[]) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbols } })) }
function openWatch(symbol: string) { window.location.href = `/v3/watch?symbol=${encodeURIComponent(symbol)}&review=1` }

function deriveIntel(watch: any, card: any, held: boolean): Intel {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.current_mechanics ?? packet?.mechanics ?? watch?.reentry_plan ?? card?.reentry_plan ?? {}
  const objects = [watch ?? {}, card ?? {}, packet ?? {}, mechanics ?? {}, packet?.technical_state ?? {}, packet?.current_input_snapshot ?? {}]
  const price = numberFrom(objects, ['price', 'last_price', 'price_live', 'current_price', 'quote.last'])
  const asOf = textFrom(objects, ['price_as_of', 'last_enriched_at', 'computed_at', 'decision_packet_at', 'as_of'])
  const rsi = numberFrom(objects, ['rsi', 'rsi_14', 'technical.rsi', 'technicals.rsi', 'current_rsi'])
  const trend = textFrom(objects, ['trend_state', 'trend_direction', 'overall_direction', 'technical_state.overall_direction', 'technicals.trend']).replace(/_/g, ' ').toUpperCase() || 'UNAVAILABLE'
  let entryLow = numberFrom(objects, ['entry_zone_low', 'reentry_zone_low', 'entry_low', 'mechanics.entry_low', 'selected_family.mechanics.entry_low'])
  let entryHigh = numberFrom(objects, ['entry_zone_high', 'reentry_zone_high', 'entry_high', 'mechanics.entry_high', 'selected_family.mechanics.entry_high'])
  const entry = numberFrom(objects, ['entry_limit', 'reentry_price', 'entry_price', 'mechanics.entry', 'selected_family.mechanics.entry'])
  if (entryLow === null) entryLow = entry
  if (entryHigh === null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]
  const stop = numberFrom(objects, ['entry_stop', 'reentry_stop', 'stop_price', 'mechanics.stop', 'selected_family.mechanics.stop'])
  const target = numberFrom(objects, ['entry_target', 'reentry_target', 'target_price', 'mechanics.target', 'selected_family.mechanics.target'])
  const stale = !asOf || !Number.isFinite(new Date(asOf).getTime()) || Date.now() - new Date(asOf).getTime() > 96 * 36e5
  let distancePct: number | null = null
  if (price !== null && entryLow !== null && entryHigh !== null && entryLow > 0 && entryHigh > 0) distancePct = price > entryHigh ? ((price - entryHigh) / entryHigh) * 100 : price < entryLow ? -((entryLow - price) / entryLow) * 100 : 0
  let state: IntelState = 'WAIT'; let action = 'Keep monitoring'; let reason = 'Current price has not reached the validated entry conditions.'
  if (held) { state = 'CURRENTLY HELD'; action = 'Manage as an existing holding'; reason = 'This symbol is currently held and is not a clean re-entry-only candidate.' }
  else if (price === null || rsi === null) { state = 'MISSING MARKET'; action = 'Refresh market evidence'; reason = 'Current price and RSI are required before a re-entry review.' }
  else if (stale) { state = 'STALE'; action = 'Refresh inputs'; reason = `The market/technical evidence is ${age(asOf)}.` }
  else if (entryLow === null || entryHigh === null) { state = 'MISSING PLAN'; action = 'Build a candidate entry zone'; reason = 'Market evidence exists, but no current validated entry range is available.' }
  else if (distancePct === 0 && rsi <= 45) { state = 'READY TO REVIEW'; action = 'Review re-entry now'; reason = 'Price is inside the entry zone and momentum is not extended.' }
  else if (distancePct !== null && distancePct >= 0 && distancePct <= 3) { state = 'NEAR ENTRY'; action = 'Prepare the review'; reason = `Price is ${distancePct.toFixed(1)}% above the entry zone.` }
  return { price, asOf, rsi, trend, entryLow, entryHigh, stop, target, distancePct, state, action, reason }
}

function resistanceFor(cached: any, watch: any, card: any, price: number | null): Resistance {
  if (cached && String(cached.state || '').toUpperCase() !== 'UNAVAILABLE') return { state: String(cached.state || 'UNAVAILABLE').toUpperCase(), level: finite(cached.resistance), distancePct: finite(cached.distance_pct), holdDays: finite(cached.hold_days), source: 'CLOSED-SESSION CACHE', reason: text(cached.reason, cached.method, 'Closed-session resistance evidence.') }
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const trigger = text(packet?.horizons?.tactical?.trigger, packet?.horizons?.swing?.trigger, packet?.selected_family?.mechanics?.trigger, watch?.trigger)
  const match = trigger.match(/resistance\s+\$?([0-9]+(?:\.[0-9]+)?)/i)
  const level = finite(watch?.resistance, watch?.resistance_level, card?.resistance, packet?.selected_family?.mechanics?.resistance, match?.[1])
  if (level !== null && price !== null && level > 0) { const distancePct = ((price - level) / level) * 100; return { state: Math.abs(distancePct) <= .5 ? 'TESTING' : distancePct > 0 ? 'ABOVE' : 'BELOW', level, distancePct, holdDays: null, source: 'WATCH FALLBACK', reason: trigger || 'Decision-packet resistance fallback.' } }
  return { state: 'UNAVAILABLE', level: null, distancePct: null, holdDays: null, source: 'MISSING', reason: 'No valid resistance cache row or parsable Watch trigger.' }
}

function stateTone(state: IntelState): string { if (state === 'READY TO REVIEW') return BB.green; if (state === 'NEAR ENTRY') return BB.amber; if (state === 'MISSING MARKET' || state === 'MISSING PLAN' || state === 'STALE') return BB.red; if (state === 'CURRENTLY HELD') return BB.amber; return BB.blue }
function sourceFor(row: ExitEvidenceRow, fieldName: ExitEvidenceField): string { return row.field_sources?.[fieldName] || row.import_source || 'source unavailable' }

export default function ReEntryCurrentIntelligence() {
  const evidence = useReEntryExitEvidence(365)
  const cards = useApi<any>('/api/v2/symbol-cards', 300_000)
  const holdings = useApi<any>('/api/v2/portfolio/holdings', 120_000)
  const mandatesPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const alerts = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const regime = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const resistancePref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(RESISTANCE_KEY)}`, 120_000)
  const analyst = useApi<any>('/api/v2/pro-analyst/pills?map=1', 300_000)
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [classificationFilter, setClassificationFilter] = useState('ALL')
  const [gapOnly, setGapOnly] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [watchReload, setWatchReload] = useState(0)

  const mandates: Record<string, ReEntryMandate> = prefMap(mandatesPref.data) as Record<string, ReEntryMandate>
  const events: Record<string, ReEntryEvent> = prefMap(eventsPref.data) as Record<string, ReEntryEvent>
  const dispositions: Record<string, ReEntryDisposition> = prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>
  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of evidence.rows) { const symbol = String(row.symbol || '').toUpperCase(); if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), row]) }
    return [...groups.entries()].map(([symbol, rows]) => {
      const sorted = rows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let shares = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of sorted) { const quantity = rowShares(row); const price = rowPrice(row); const cash = finite(row.proceeds_usd); if (quantity !== null) { known = true; shares += quantity; if (price !== null) weighted += quantity * price } if (cash !== null) proceeds += Math.abs(cash) }
      return { symbol, rows: sorted, latest: sorted[0], shares: known ? shares : null, avgExit: shares > 0 && weighted > 0 ? weighted / shares : null, proceeds, eventGapCount: sorted.reduce((sum, row) => sum + (row.evidence_gaps?.length ?? 0), 0), derivedCount: sorted.reduce((sum, row) => sum + (row.derived_fields?.length ?? 0), 0) } satisfies Summary
    })
  }, [evidence.rows])

  const symbols = useMemo(() => summaries.map(summary => summary.symbol).slice(0, 300), [summaries])
  useEffect(() => {
    if (!symbols.length) return
    let dead = false; let cursor = 0
    const controller = new AbortController(); const output: Record<string, any> = {}
    const worker = async () => { while (!dead) { const index = cursor++; if (index >= symbols.length) return; const symbol = symbols[index]; try { const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal: controller.signal }); const payload = unwrap(await response.json()); output[symbol] = (payload?.items ?? [])[0] ?? null } catch { output[symbol] = null } } }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, () => worker())).then(() => { if (!dead) setWatchMap(previous => ({ ...previous, ...output })) })
    return () => { dead = true; controller.abort() }
  }, [symbols.join('|'), watchReload])

  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const heldSet = new Set<string>((unwrap(holdings.data)?.holdings ?? []).filter((row: any) => Number(row.shares ?? row.quantity ?? 0) > 0).map((row: any) => String(row.symbol || '').toUpperCase()))
  const alertRows: any[] = unwrap(alerts.data)?.alerts ?? unwrap(alerts.data)?.items ?? []
  const resistanceMap: Record<string, any> = prefValue(resistancePref.data)?.symbols ?? {}
  const analystMap: Record<string, any> = unwrap(analyst.data)?.map ?? {}

  const rows = useMemo(() => summaries.map(summary => {
    const mandate = normalizedMandate(mandates[summary.symbol])
    const watch = watchMap[summary.symbol]
    const card = cardMap[summary.symbol]
    const intel = deriveIntel(watch, card, heldSet.has(summary.symbol))
    const resistance = resistanceFor(resistanceMap[summary.symbol], watch, card, intel.price)
    const classified = classificationState(mandate, summary.rows, events, dispositions)
    const flags = REENTRY_FLAGS.filter(flag => mandate.flags[flag])
    const completeness = [summary.shares !== null, summary.avgExit !== null, Boolean(watch), intel.price !== null, intel.rsi !== null, intel.entryLow !== null, resistance.level !== null, Boolean(analystMap[summary.symbol])].filter(Boolean).length
    const alertCount = alertRows.filter(row => String(row.symbol || '').toUpperCase() === summary.symbol && !['disabled', 'expired', 'resolved'].includes(String(row.status || '').toLowerCase())).length
    return { ...summary, mandate, watch, card, intel, resistance, classified, flags, completeness, alertCount, analyst: analystMap[summary.symbol] ?? null }
  }), [summaries, mandatesPref.data, eventsPref.data, dispositionsPref.data, watchMap, cards.data, holdings.data, resistancePref.data, analyst.data, alerts.data])

  const shown = rows.filter(row => {
    if (search.trim() && !`${row.symbol} ${row.intel.state} ${row.intel.action} ${row.classified} ${row.mandate.mandate} ${row.flags.join(' ')} ${row.latest.import_source ?? ''} ${(row.latest.evidence_gaps ?? []).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    if (stateFilter !== 'ALL' && row.intel.state !== stateFilter) return false
    if (classificationFilter !== 'ALL' && row.classified !== classificationFilter) return false
    if (gapOnly && row.completeness >= 8 && row.eventGapCount === 0) return false
    return true
  }).sort((a, b) => (a.mandate.priority === 'HIGH' ? -1 : 0) - (b.mandate.priority === 'HIGH' ? -1 : 0) || b.completeness - a.completeness || String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || '')))

  const selectedSymbols = shown.filter(row => selected[row.symbol]).map(row => row.symbol)
  const counts = { symbols: rows.length, classified: rows.filter(row => row.classified === 'CLASSIFIED').length, ready: rows.filter(row => row.intel.state === 'READY TO REVIEW').length, near: rows.filter(row => row.intel.state === 'NEAR ENTRY').length, missing: rows.filter(row => row.completeness < 8 || row.eventGapCount > 0).length }
  const regimeLabel = text(unwrap(regime.data)?.regime_label, unwrap(regime.data)?.label, 'unknown').replace(/_/g, ' ').toUpperCase()
  const refresh = () => { evidence.refetch(); cards.refetch(); holdings.refetch(); alerts.refetch(); regime.refetch(); resistancePref.refetch(); analyst.refetch(); mandatesPref.refetch(); eventsPref.refetch(); dispositionsPref.refetch(); setWatchReload(value => value + 1) }
  const shareCoverage = evidence.sources.map(source => `${source.label} shares ${evidence.sourceFieldCoverage[source.key]?.quantity ?? 0}`).join(' · ')

  return <div style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}><div><div style={{ fontSize: 18, fontWeight: 900 }}>CURRENT RE-ENTRY INTELLIGENCE <HelpTip text="Exit events are reconciled by broker ID and compatible symbol/date/account facts. Every displayed field retains its source; deterministic arithmetic is labeled as derived." /></div><div style={{ fontSize: 10.5, color: BB.text3 }}>Regime {regimeLabel} · {evidence.rows.length} reconciled exit events · {evidence.sources.filter(source => source.available).length}/{evidence.sources.length} sources reporting · contract {evidence.contractVersion} · advisory only</div></div><button onClick={refresh} style={{ ...button(false), marginLeft: 'auto' }}>{evidence.loading || evidence.refreshing ? 'REFRESHING…' : 'REFRESH ALL SOURCES'}</button></div>

    <div style={{ ...panel, marginTop: 8, padding: 8, background: 'var(--bg2)', fontSize: 10.5 }}><b>Source audit:</b> {evidence.sources.map(source => `${source.label} ${source.rows}`).join(' · ')}.<br /><b>Quantity-bearing rows:</b> {shareCoverage}. A remaining blank means no compatible event or aggregate supplied the field; deterministic derivations and account-alias joins are labeled in the expanded audit.</div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(120px,1fr))', gap: 7, marginTop: 9 }}>{[
      ['EXITED SYMBOLS', counts.symbols, stateFilter === 'ALL' && classificationFilter === 'ALL' && !gapOnly, () => { setStateFilter('ALL'); setClassificationFilter('ALL'); setGapOnly(false) }],
      ['CLASSIFIED', counts.classified, classificationFilter === 'CLASSIFIED', () => setClassificationFilter(value => value === 'CLASSIFIED' ? 'ALL' : 'CLASSIFIED')],
      ['READY NOW', counts.ready, stateFilter === 'READY TO REVIEW', () => setStateFilter(value => value === 'READY TO REVIEW' ? 'ALL' : 'READY TO REVIEW')],
      ['NEAR ENTRY', counts.near, stateFilter === 'NEAR ENTRY', () => setStateFilter(value => value === 'NEAR ENTRY' ? 'ALL' : 'NEAR ENTRY')],
      ['EVIDENCE GAPS', counts.missing, gapOnly, () => setGapOnly(value => !value)],
    ].map(([name, value, active, action]) => <button key={String(name)} onClick={action as () => void} style={{ ...panel, padding: 9, textAlign: 'left', cursor: 'pointer', background: active ? BB.blueDim : 'var(--bg2)', color: 'var(--text0)' }}><span style={{ color: BB.text3, fontSize: 10 }}>{String(name)}</span><br /><b style={{ fontSize: 20 }}>{String(value)}</b></button>)}</div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,1fr) 190px 170px auto auto auto', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, state, source or missing field…" style={field} /><select value={stateFilter} onChange={event => setStateFilter(event.target.value)} style={field}><option value="ALL">ALL CURRENT STATES</option>{['READY TO REVIEW', 'NEAR ENTRY', 'WAIT', 'CURRENTLY HELD', 'STALE', 'MISSING PLAN', 'MISSING MARKET'].map(state => <option key={state}>{state}</option>)}</select><select value={classificationFilter} onChange={event => setClassificationFilter(event.target.value)} style={field}><option value="ALL">ALL CLASSIFICATIONS</option><option>CLASSIFIED</option><option>AUTO-TAGGED</option><option>UNCLASSIFIED</option></select><button onClick={() => setSelected(Object.fromEntries(shown.map(row => [row.symbol, true])))} style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelected({})} style={button(false)}>CLEAR</button><button disabled={!selectedSymbols.length} onClick={() => classify(selectedSymbols)} style={{ ...button(Boolean(selectedSymbols.length)), opacity: selectedSymbols.length ? 1 : .5 }}>EDIT SELECTED {selectedSymbols.length}</button></div>

    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1530 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 180px 220px 125px 170px 170px 160px 160px 145px', gap: 8, padding: '7px 9px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol / mandate</span><span>Current decision</span><span>Market</span><span>Exit evidence</span><span>Entry / resistance</span><span>Valuation / analyst</span><span>Evidence audit</span><span>Actions</span></div>{shown.map(row => {
      const open = Boolean(expanded[row.symbol]); const tone = stateTone(row.intel.state); const classTone = row.classified === 'CLASSIFIED' ? BB.green : row.classified === 'AUTO-TAGGED' ? BB.amber : BB.text3
      const mandateLabel = row.mandate.mandate === 'unclassified' && row.flags.length ? 'MANDATE NEEDED' : row.mandate.mandate.replace(/_/g, ' ').toUpperCase()
      const pe = numberFrom([row.watch, row.card, row.watch?.fundamentals, row.watch?.decision_packet?.blind_facts?.fundamentals], ['pe', 'trailing_pe'])
      const fpe = numberFrom([row.watch, row.card, row.watch?.fundamentals, row.watch?.decision_packet?.blind_facts?.fundamentals], ['forward_pe', 'forwardPe', 'fwd_pe'])
      const rec = text(row.analyst?.rec, row.analyst?.recommendation, 'unavailable').replace(/_/g, ' ').toUpperCase()
      return <div key={row.symbol}><div role="button" tabIndex={0} aria-expanded={open} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setExpanded(value => ({ ...value, [row.symbol]: !open })) } }} onClick={() => setExpanded(value => ({ ...value, [row.symbol]: !open }))} style={{ display: 'grid', gridTemplateColumns: '28px 180px 220px 125px 170px 170px 160px 160px 145px', gap: 8, padding: '9px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: open ? 'var(--bg2)' : 'transparent', boxShadow: open ? `inset 3px 0 0 ${BB.blue}` : undefined }}><input type="checkbox" checked={Boolean(selected[row.symbol])} onClick={event => event.stopPropagation()} onChange={event => setSelected(value => ({ ...value, [row.symbol]: event.target.checked }))} /><div><div><b style={{ fontSize: 14 }}>{row.symbol}</b> <span style={{ color: classTone, fontSize: 10 }}>{classificationLabel(row.classified)}</span> <span style={{ color: BB.text3 }}>{open ? '▾' : '▸'}</span></div><div style={{ marginTop: 3, color: mandateLabel === 'MANDATE NEEDED' ? BB.amber : BB.text2 }}>{mandateLabel}</div><div style={{ color: BB.text3 }}>{row.flags.join(' · ') || 'no strategy flags'}</div></div><div><span style={{ color: tone, fontWeight: 900 }}>{row.intel.state}</span><div style={{ marginTop: 3, fontWeight: 800 }}>{row.intel.action}</div><div style={{ color: BB.text3 }}>{row.intel.reason}</div></div><div><b>{money(row.intel.price)}</b><br /><span style={{ color: BB.text3 }}>RSI {row.intel.rsi === null ? '—' : row.intel.rsi.toFixed(1)} · {row.intel.trend}</span><br /><span style={{ color: BB.text3 }}>{age(row.intel.asOf)}</span></div><div><b>{row.rows.length} exits · {row.shares === null ? 'shares unavailable' : `${row.shares.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh`}</b><br /><span>avg {money(row.avgExit)} · {money(row.proceeds)}</span><br /><span style={{ color: BB.text3 }}>{row.latest.trade_date ?? 'date unavailable'}</span></div><div><b>{row.intel.entryLow === null ? 'entry unavailable' : row.intel.entryLow === row.intel.entryHigh ? money(row.intel.entryLow) : `${money(row.intel.entryLow)}–${money(row.intel.entryHigh)}`}</b><br /><span style={{ color: BB.text3 }}>stop {money(row.intel.stop)} · target {money(row.intel.target)}</span><br /><span>{row.resistance.state} {money(row.resistance.level)} · {row.resistance.distancePct === null ? 'distance —' : `${row.resistance.distancePct >= 0 ? '+' : ''}${row.resistance.distancePct.toFixed(1)}%`}</span></div><div><b>P/E {pe === null ? '—' : pe.toFixed(2)} · Fwd {fpe === null ? '—' : fpe.toFixed(2)}</b><br /><span>{rec}</span><br /><span style={{ color: BB.text3 }}>{row.analyst?.n ?? '—'} analysts · target {row.analyst?.target == null ? '—' : money(Number(row.analyst.target))}</span></div><div><b>{row.completeness}/8 current fields</b><br /><span style={{ color: row.eventGapCount ? BB.amber : BB.text3 }}>{row.eventGapCount} event gaps · {row.derivedCount} derived</span><br /><span style={{ color: BB.text3 }}>{row.latest.import_source || 'source unavailable'}</span></div><div onClick={event => event.stopPropagation()}><button onClick={() => setExpanded(value => ({ ...value, [row.symbol]: true }))} style={button(true)}>OPEN EVIDENCE</button><button onClick={() => classify([row.symbol])} style={{ ...button(false), marginTop: 5 }}>CLASSIFY</button><button onClick={() => openWatch(row.symbol)} style={{ ...button(false), marginTop: 5 }}>OPEN WATCH</button></div></div>
      {open && <div style={{ padding: '10px 14px 14px 42px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1.2fr .8fr', gap: 18 }}><div><div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>RECONCILED EXIT HISTORY — FIELD-BY-FIELD AUDIT</div>{row.rows.map(exit => { const event = normalizedEvent(exit, events[exit.event_key]); return <div key={exit.event_key} style={{ padding: '7px 0', borderBottom: '1px solid var(--border)' }}><div style={{ display: 'grid', gridTemplateColumns: '85px 120px 90px 90px 100px 1fr', gap: 7, fontSize: 10 }}><span>{exit.trade_date ?? '—'}</span><span>{exit.account ?? '—'}</span><span>{rowShares(exit) === null ? '—' : `${rowShares(exit)?.toLocaleString(undefined, { maximumFractionDigits: 4 })} sh`}</span><span>{money(rowPrice(exit))}</span><span>{money(finite(exit.proceeds_usd))}</span><span><b>{event.eventType.replace(/_/g, ' ').toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{event.reason || 'reason unavailable'}</span></span></div><div style={{ marginTop: 5, fontSize: 10, color: BB.text3 }}>Sources — account: {sourceFor(exit, 'account')} · shares: {sourceFor(exit, 'quantity')} · price: {sourceFor(exit, 'price')} · proceeds: {sourceFor(exit, 'proceeds_usd')}</div>{Boolean(exit.derived_fields?.length) && <div style={{ marginTop: 3, fontSize: 10, color: BB.blue }}>Derived deterministically: {exit.derived_fields?.join(' · ')}</div>}{Boolean(exit.evidence_gaps?.length) && <div style={{ marginTop: 3, fontSize: 10, color: BB.amber }}>Still missing: {exit.evidence_gaps?.join(' · ')}</div>}</div>})}</div><div><div style={{ fontSize: 10, fontWeight: 900, color: BB.text3, marginBottom: 6 }}>CURRENT WATCH / PORTFOLIO CONTEXT</div><div style={{ fontSize: 10.5, lineHeight: 1.55 }}><b>Mandate:</b> {mandateLabel}<br /><b>Priority:</b> {row.mandate.priority}<br /><b>Thesis:</b> {row.mandate.thesis || 'No operator thesis saved.'}<br /><b>Watch recommendation:</b> {text(row.watch?.synthesis_recommendation, row.watch?.latest_recommendation, 'unavailable').replace(/_/g, ' ')}<br /><b>Sector:</b> {text(row.watch?.profile_sector, row.card?.sector, 'unavailable')}<br /><b>Catalyst:</b> {text(row.watch?.catalyst_headline, 'unavailable')}<br /><b>Earnings:</b> {text(row.watch?.earnings_date, row.watch?.next_earnings_date, 'unavailable')}<br /><b>Resistance source:</b> {row.resistance.source} — {row.resistance.reason}<br /><b>Disposition:</b> {normalizedEvent(row.latest, events[row.latest.event_key]).eventType.replace(/_/g, ' ')}</div><div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}><button onClick={() => classify([row.symbol])} style={button(true)}>EDIT CLASSIFICATION</button><button onClick={() => openWatch(row.symbol)} style={button(false)}>OPEN {row.symbol} IN WATCH</button><button onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(row.symbol)}` }} style={button(false)}>OPEN ROTATION</button></div></div></div>}
      </div>
    })}</div></div>
    {evidence.errors.length > 0 && <div style={{ marginTop: 7, color: BB.red, fontSize: 10 }}>Source warnings: {evidence.errors.join(' · ')}</div>}
    {!shown.length && <div style={{ padding: 14, color: BB.text3 }}>No symbols match the current filters.</div>}
  </div>
}
