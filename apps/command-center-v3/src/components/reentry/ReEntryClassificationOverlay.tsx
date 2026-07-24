import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useApi } from '../../hooks/useApi'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  EXIT_TYPES,
  MANDATE_KEY,
  REENTRY_FLAGS,
  defaultDisposition,
  defaultMandate,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  rowPrice,
  rowShares,
  saveUiPref,
  text,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const btn = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '6px 10px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })
const label: CSSProperties = { display: 'block', fontSize: 10, color: BB.text3 }

function tickerLike(symbol: string): boolean { return /^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol) }
function unwrap(value: any): any { let result = value; for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) result = result.data; return result ?? {} }
function num(...values: any[]): number | null { return finite(...values) }
function money(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function age(value: any): string {
  if (!value) return 'as-of unavailable'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - time) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function dig(value: any, path: string): any { return path.split('.').reduce((current: any, key) => current?.[key], value) }
function firstNumber(objects: any[], paths: string[]): number | null {
  for (const object of objects) for (const path of paths) { const value = num(dig(object, path)); if (value !== null) return value }
  return null
}
function firstText(objects: any[], paths: string[]): string {
  for (const object of objects) for (const path of paths) { const value = text(dig(object, path)); if (value) return value }
  return ''
}
function valuation(watch: any, card: any) {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const objects = [watch, card, watch?.fundamentals, card?.fundamentals, packet?.fundamentals, packet?.current_input_snapshot?.fundamentals, packet?.blind_facts?.fundamentals]
  const pe = firstNumber(objects, ['pe', 'trailing_pe', 'valuation.pe'])
  const forwardPe = firstNumber(objects, ['forward_pe', 'forwardPe', 'fwd_pe', 'valuation.forward_pe'])
  const peg = firstNumber(objects, ['peg', 'peg_ratio', 'valuation.peg'])
  const pb = firstNumber(objects, ['pb', 'price_to_book', 'valuation.pb'])
  const ps = firstNumber(objects, ['ps', 'price_to_sales', 'valuation.ps'])
  const asOf = firstText(objects, ['fundamentals_as_of', 'cached_at', 'as_of']) || text(watch?.last_enriched_at)
  const instrument = text(watch?.instrument_type, watch?.asset_type, card?.instrument_type).toLowerCase()
  return { pe, forwardPe, peg, pb, ps, asOf, notApplicable: /etf|fund|mutual/.test(instrument) }
}
function watchContext(watch: any, card: any, analyst: any, regime: any) {
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const objects = [watch, card, packet, packet?.technical_state, packet?.current_input_snapshot]
  return {
    price: firstNumber(objects, ['price', 'last_price', 'price_live', 'current_price']),
    priceAsOf: firstText(objects, ['price_as_of', 'last_enriched_at', 'computed_at']),
    rsi: firstNumber(objects, ['rsi', 'rsi_14', 'technical.rsi', 'technicals.rsi']),
    trend: firstText(objects, ['trend_state', 'trend_direction', 'technical_state.overall_direction', 'technicals.trend']).replace(/_/g, ' ').toUpperCase(),
    sector: firstText(objects, ['profile_sector', 'sector']),
    recommendation: firstText(objects, ['synthesis_recommendation', 'latest_recommendation', 'preferred_action']).replace(/_/g, ' ').toUpperCase(),
    catalyst: firstText(objects, ['catalyst_headline']),
    catalystAsOf: firstText(objects, ['catalyst_at']),
    earnings: firstText(objects, ['earnings_date', 'next_earnings_date']),
    entryLow: firstNumber(objects, ['entry_zone_low', 'reentry_zone_low', 'entry_low', 'selected_family.mechanics.entry_low']),
    entryHigh: firstNumber(objects, ['entry_zone_high', 'reentry_zone_high', 'entry_high', 'selected_family.mechanics.entry_high']),
    stop: firstNumber(objects, ['entry_stop', 'reentry_stop', 'stop_price', 'selected_family.mechanics.stop']),
    target: firstNumber(objects, ['entry_target', 'reentry_target', 'target_price', 'selected_family.mechanics.target']),
    regime: text(regime?.regime_label, regime?.label, 'unavailable').replace(/_/g, ' ').toUpperCase(),
    analystRec: text(analyst?.rec, analyst?.recommendation, 'unavailable').replace(/_/g, ' ').toUpperCase(),
    analystTarget: num(analyst?.target),
    analystCount: num(analyst?.n),
  }
}

export default function ReEntryClassificationOverlay() {
  const evidence = useReEntryExitEvidence(365)
  const mandatePref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const cards = useApi<any>('/api/v2/symbol-cards', 300_000)
  const analyst = useApi<any>('/api/v2/pro-analyst/pills?map=1', 300_000)
  const regime = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const [symbols, setSymbols] = useState<string[]>([])
  const first = symbols[0] ?? ''
  const watchResult = useApi<any>(`/api/v2/watchlist/items?symbol=${encodeURIComponent(first || 'NONE')}`, 0, { enabled: Boolean(first) })
  const [mandate, setMandate] = useState<ReEntryMandate>(defaultMandate())
  const [eventClass, setEventClass] = useState<ReEntryEvent>({ eventType: 'other', reason: '', notes: '', updatedAt: '' })
  const [disposition, setDisposition] = useState<ReEntryDisposition>(defaultDisposition())
  const [eventScope, setEventScope] = useState<'latest' | 'all'>('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const mandates = prefMap(mandatePref.data)
  const events = prefMap(eventPref.data)
  const dispositions = prefMap(dispositionPref.data)
  const rowsBySymbol = useMemo(() => {
    const map: Record<string, ExitEvidenceRow[]> = {}
    for (const row of evidence.rows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (!symbol) continue
      ;(map[symbol] ??= []).push(row)
    }
    for (const rows of Object.values(map)) rows.sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
    return map
  }, [evidence.rows])

  const open = (nextSymbols: any[]) => {
    const normalized = [...new Set(nextSymbols.map(value => String(value || '').trim().toUpperCase()).filter(Boolean))]
    if (!normalized.length) return
    setSymbols(normalized)
    const url = new URL(window.location.href)
    url.searchParams.set('classify', normalized.join(','))
    window.history.replaceState(window.history.state, '', url)
  }
  const close = () => {
    setSymbols([]); setError(''); setBusy(false)
    const url = new URL(window.location.href)
    url.searchParams.delete('classify')
    window.history.replaceState(window.history.state, '', url)
  }

  useEffect(() => {
    const fromUrl = () => { const value = new URL(window.location.href).searchParams.get('classify'); if (value) open(value.split(',')) }
    const handler = (raw: Event) => {
      raw.stopImmediatePropagation()
      const detail = (raw as CustomEvent)?.detail ?? {}
      open(Array.isArray(detail.symbols) ? detail.symbols : [detail.symbol])
    }
    fromUrl()
    window.addEventListener('popstate', fromUrl)
    window.addEventListener('reentry:classify-symbol', handler, true)
    return () => { window.removeEventListener('popstate', fromUrl); window.removeEventListener('reentry:classify-symbol', handler, true) }
  }, [])

  const selectedRows = useMemo(() => symbols.flatMap(symbol => rowsBySymbol[symbol] ?? []), [symbols.join('|'), rowsBySymbol])
  const latestRows = useMemo(() => symbols.map(symbol => rowsBySymbol[symbol]?.[0]).filter(Boolean) as ExitEvidenceRow[], [symbols.join('|'), rowsBySymbol])
  const eventRows = eventScope === 'all' ? selectedRows : latestRows
  const totalShares = selectedRows.reduce((sum, row) => sum + (rowShares(row) ?? 0), 0)
  const sharesKnown = selectedRows.some(row => rowShares(row) !== null)
  const totalProceeds = selectedRows.reduce((sum, row) => sum + Math.abs(num(row.proceeds_usd) ?? 0), 0)
  const unresolved = symbols.filter(symbol => !tickerLike(symbol))
  const watch = (unwrap(watchResult.data)?.items ?? [])[0] ?? null
  const cardMap = unwrap(cards.data)?.cards ?? {}
  const analystMap = unwrap(analyst.data)?.map ?? {}
  const card = cardMap[first] ?? null
  const analystRow = analystMap[first] ?? null
  const val = valuation(watch, card)
  const context = watchContext(watch, card, analystRow, unwrap(regime.data))

  useEffect(() => {
    if (!symbols.length) return
    const firstRow = rowsBySymbol[first]?.[0]
    const savedMandate = normalizedMandate(mandates[first])
    const savedEvent = firstRow ? normalizedEvent(firstRow, events[firstRow.event_key]) : { eventType: 'other', reason: '', notes: '', updatedAt: '' } as ReEntryEvent
    const savedDisposition = firstRow ? normalizedDisposition(dispositions[firstRow.event_key]) : defaultDisposition()
    const startingNotes = [
      context.recommendation ? `Watch recommendation — ${context.recommendation}` : '',
      context.sector ? `Sector — ${context.sector}` : '',
      context.regime ? `Regime — ${context.regime}` : '',
      context.earnings ? `Earnings — ${context.earnings}` : '',
      context.catalyst ? `Catalyst — ${context.catalyst}` : '',
      context.rsi !== null ? `RSI — ${context.rsi.toFixed(1)}` : '',
      val.pe !== null ? `Trailing P/E — ${val.pe.toFixed(2)}` : '',
      val.forwardPe !== null ? `Forward P/E — ${val.forwardPe.toFixed(2)}` : '',
    ].filter(Boolean).join('\n')
    setMandate(savedMandate)
    setEventClass({ ...savedEvent, notes: savedEvent.notes || startingNotes })
    setDisposition(savedDisposition)
  }, [symbols.join('|'), evidence.rows, mandatePref.data, eventPref.data, dispositionPref.data, watchResult.data, cards.data, analyst.data, regime.data])

  if (!symbols.length || typeof document === 'undefined') return null
  const selectedFlags = REENTRY_FLAGS.filter(flag => mandate.flags[flag])
  const mandateIncomplete = mandate.mandate === 'unclassified' && selectedFlags.length > 0

  const save = async () => {
    if (unresolved.length) return
    setBusy(true); setError('')
    try {
      const now = new Date().toISOString()
      const nextMandates = { ...mandates }
      const nextEvents = { ...events }
      const nextDispositions = { ...dispositions }
      for (const symbol of symbols) nextMandates[symbol] = { ...mandate, updatedAt: now }
      for (const row of eventRows) {
        nextEvents[row.event_key] = { ...eventClass, updatedAt: now }
        nextDispositions[row.event_key] = { ...disposition, updatedAt: now }
      }
      await Promise.all([
        saveUiPref(MANDATE_KEY, nextMandates),
        saveUiPref(EVENT_KEY, nextEvents),
        saveUiPref(DISPOSITION_KEY, nextDispositions),
      ])
      window.dispatchEvent(new CustomEvent('reentry:classification-saved', { detail: { symbols } }))
      mandatePref.refetch(); eventPref.refetch(); dispositionPref.refetch(); evidence.refetch()
      close()
    } catch (value: any) {
      setError(String(value?.message || value)); setBusy(false)
    }
  }

  const coverageRows = [
    ['EXIT EVENTS', String(selectedRows.length), selectedRows.length ? 'available' : 'missing'],
    ['SHARES', sharesKnown ? `${totalShares.toLocaleString()} sh` : 'unavailable', sharesKnown ? 'available' : 'missing'],
    ['WATCH ITEM', watch ? 'available' : 'unavailable', watch ? 'available' : 'missing'],
    ['VALUATION', val.notApplicable ? 'legitimately N/A' : [val.pe, val.forwardPe, val.peg, val.pb, val.ps].some(value => value !== null) ? 'available' : 'unavailable', val.notApplicable || val.pe !== null || val.forwardPe !== null ? 'available' : 'missing'],
    ['ANALYST', analystRow ? 'available' : 'unavailable', analystRow ? 'available' : 'missing'],
    ['IDENTITY', unresolved.length ? 'unresolved' : 'ticker', unresolved.length ? 'missing' : 'available'],
  ]

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`${symbols.join(', ')} classification`} onMouseDown={close} style={{ position: 'fixed', inset: 0, zIndex: 10000, display: 'grid', placeItems: 'center', padding: 16, background: 'rgba(2,6,23,.90)' }}>
      <div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(1240px,98vw)', maxHeight: '95vh', overflowY: 'auto', padding: 16, boxShadow: '0 24px 80px rgba(0,0,0,.5)' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'start' }}>
          <div style={{ flex: 1 }}><div style={{ fontSize: 20, fontWeight: 900 }}>{symbols.join(' · ')} — Classification & Re-Entry Context</div><div style={{ fontSize: 10.5, color: BB.text3 }}>Operator fields, real exit events, current market evidence, valuation and independent source coverage in one review.</div></div>
          <button onClick={close} style={btn(false)}>CLOSE</button>
        </div>

        {unresolved.length > 0 && <div style={{ ...panel, marginTop: 10, padding: 10, borderColor: BB.red, color: BB.red, fontSize: 10.5 }}><b>UNRESOLVED IDENTITY:</b> {unresolved.join(', ')} is not treated as an actionable ticker until symbol resolution is explicit.</div>}
        {mandateIncomplete && <div style={{ ...panel, marginTop: 10, padding: 9, borderColor: BB.amber, color: BB.amber, fontSize: 10.5 }}><b>MANDATE STILL UNCLASSIFIED:</b> strategy flags are saved evidence, but choose CORE, SATELLITE/TACTICAL or HEDGE to remove the visible UNCLASSIFIED mandate state.</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr .8fr', gap: 10, marginTop: 10 }}>
          <div style={{ ...panel, padding: 11 }}>
            <div style={{ fontSize: 11, fontWeight: 900 }}>SOURCE COVERAGE</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(100px,1fr))', gap: 6, marginTop: 7 }}>{coverageRows.map(([name, value, state]) => <div key={name} style={{ ...panel, padding: 7, background: 'var(--bg2)' }}><div style={{ fontSize: 9.5, color: BB.text3 }}>{name}</div><b style={{ color: state === 'missing' ? BB.amber : 'var(--text1)' }}>{value}</b></div>)}</div>
            <div style={{ marginTop: 8, fontSize: 10, color: BB.text3 }}>{evidence.sources.map(source => `${source.label}: ${source.rows}`).join(' · ')}</div>
          </div>
          <div style={{ ...panel, padding: 11 }}>
            <div style={{ fontSize: 11, fontWeight: 900 }}>SELECTED EXIT SCOPE</div>
            <div style={{ marginTop: 7, fontSize: 11 }}>{selectedRows.length} event{selectedRows.length === 1 ? '' : 's'} · {sharesKnown ? `${totalShares.toLocaleString()} shares` : 'shares unavailable'} · {money(totalProceeds)} proceeds</div>
            <div style={{ marginTop: 6, display: 'flex', gap: 6 }}><button onClick={() => setEventScope('latest')} style={btn(eventScope === 'latest')}>LATEST PER SYMBOL</button><button onClick={() => setEventScope('all')} style={btn(eventScope === 'all')}>ALL SELECTED EXITS</button></div>
          </div>
        </div>

        <div style={{ ...panel, padding: 11, marginTop: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 900 }}>CURRENT DECISION EVIDENCE — {first}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(120px,1fr))', gap: 7, marginTop: 7 }}>{[
            ['PRICE', money(context.price), age(context.priceAsOf)],
            ['RSI / TREND', context.rsi === null ? 'unavailable' : context.rsi.toFixed(1), context.trend || 'trend unavailable'],
            ['ENTRY', context.entryLow === null ? 'unavailable' : context.entryLow === context.entryHigh ? money(context.entryLow) : `${money(context.entryLow)}–${money(context.entryHigh)}`, `stop ${money(context.stop)} · target ${money(context.target)}`],
            ['REGIME / SECTOR', context.regime, context.sector || 'sector unavailable'],
            ['ANALYST', context.analystRec, `${context.analystCount ?? '—'} analysts · target ${money(context.analystTarget)}`],
            ['CATALYST / EARNINGS', context.catalyst || 'catalyst unavailable', context.earnings ? `earnings ${context.earnings}` : 'earnings unavailable'],
          ].map(([name, value, detail]) => <div key={name} style={{ ...panel, padding: 8, background: 'var(--bg2)' }}><div style={{ fontSize: 9.5, color: BB.text3 }}>{name}</div><b>{value}</b><div style={{ marginTop: 2, fontSize: 9.5, color: BB.text3 }}>{detail}</div></div>)}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(105px,1fr))', gap: 7, marginTop: 7 }}>{[
            ['TRAILING P/E', val.notApplicable ? 'N/A' : val.pe === null ? 'unavailable' : val.pe.toFixed(2)],
            ['FORWARD P/E', val.notApplicable ? 'N/A' : val.forwardPe === null ? 'unavailable' : val.forwardPe.toFixed(2)],
            ['PEG', val.notApplicable ? 'N/A' : val.peg === null ? 'unavailable' : val.peg.toFixed(2)],
            ['P/B', val.notApplicable ? 'N/A' : val.pb === null ? 'unavailable' : val.pb.toFixed(2)],
            ['P/S', val.notApplicable ? 'N/A' : val.ps === null ? 'unavailable' : val.ps.toFixed(2)],
          ].map(([name, value]) => <div key={name} style={{ ...panel, padding: 7, background: 'var(--bg2)' }}><span style={{ fontSize: 9.5, color: BB.text3 }}>{name}</span><br /><b>{value}</b></div>)}</div>
          <div style={{ marginTop: 6, fontSize: 9.5, color: BB.text3 }}>Valuation source: stored enrichment / blind facts · {age(val.asOf)}. Valuation is evidence, not an action or quality score.</div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          <div style={{ ...panel, padding: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>1 · PERSISTENT INVESTMENT CLASSIFICATION</div>
            <label style={label}>PRIMARY MANDATE<select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as ReEntryMandate['mandate'] }))} style={{ ...field, marginTop: 4 }}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select></label>
            <div style={{ fontSize: 10, color: BB.text3, marginTop: 10 }}>MULTI-SELECT STRATEGY FLAGS</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 5 }}>{REENTRY_FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 8, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)', cursor: 'pointer' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={label}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={label}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label><label style={label}>PRIORITY<select value={mandate.priority} onChange={event => setMandate(value => ({ ...value, priority: event.target.value as ReEntryMandate['priority'] }))} style={{ ...field, marginTop: 4 }}><option>HIGH</option><option>NORMAL</option><option>LOW</option></select></label></div>
            <label style={{ ...label, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={5} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
          </div>

          <div style={{ ...panel, padding: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>2 · EXIT EVENT + RE-ENTRY QUEUE</div>
            {!eventRows.length && <div style={{ color: BB.amber, fontSize: 10.5, marginBottom: 8 }}>No event-level exit evidence is available. The persistent mandate may still be saved; no transaction will be fabricated.</div>}
            <label style={label}>APPLY TO<select value={eventScope} onChange={event => setEventScope(event.target.value as 'latest' | 'all')} style={{ ...field, marginTop: 4 }}><option value="all">ALL SELECTED EXIT EVENTS</option><option value="latest">LATEST EXIT PER SYMBOL</option></select></label>
            <div style={{ ...panel, padding: 8, marginTop: 8, background: 'var(--bg2)', fontSize: 10.5 }}>{eventRows.length} events selected · {sharesKnown ? `${totalShares.toLocaleString()} shares` : 'shares unavailable'} · {money(totalProceeds)} proceeds</div>
            <label style={{ ...label, marginTop: 9 }}>EXIT TYPE<select disabled={!eventRows.length} value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as ReEntryEvent['eventType'] }))} style={{ ...field, marginTop: 4 }}>{EXIT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select></label>
            <label style={{ ...label, marginTop: 9 }}>REASON<input disabled={!eventRows.length} value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} placeholder="Unavailable until broker/journal evidence exists" style={{ ...field, marginTop: 4 }} /></label>
            <label style={{ ...label, marginTop: 9 }}>EDITABLE EVIDENCE NOTES<textarea rows={7} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
            <div style={{ ...panel, padding: 9, marginTop: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10, fontWeight: 900 }}>QUEUE DISPOSITION</div>{(['monitor', 'review', 'suppressed'] as const).map(state => <label key={state} style={{ display: 'block', marginTop: 6 }}><input type="radio" name="overlay-disposition" checked={disposition.state === state} onChange={() => setDisposition(value => ({ ...value, state }))} /> <b style={{ marginLeft: 5 }}>{state === 'monitor' ? 'SAVE / MONITOR LONG TERM' : state === 'review' ? 'REVIEW LATER' : 'SUPPRESS FROM RE-ENTRY QUEUE'}</b></label>)}<input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Why monitor, review, or suppress?" style={{ ...field, marginTop: 8 }} /></div>
          </div>
        </div>

        {(error || evidence.errors.length > 0) && <div style={{ color: BB.red, fontSize: 10.5, marginTop: 9 }}>{error || evidence.errors.join(' · ')}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={close} style={btn(false)}>CANCEL</button><button disabled={busy || unresolved.length > 0} onClick={() => void save()} style={{ ...btn(true), opacity: unresolved.length ? .5 : 1 }}>{busy ? 'SAVING…' : 'SAVE CLASSIFICATION'}</button></div>
      </div>
    </div>,
    document.body,
  )
}
