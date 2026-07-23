import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'

const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const EVENT_KEY = 'portfolio.reentry.event-classifications.v1'
const ROTATION_KEY = 'portfolio.reentry.rotation-links.v1'
const COMPOSITE_ALERT_KEY = 'portfolio.reentry.composite-alerts.v1'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const btn = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 800, padding: '6px 10px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

const STRATEGY_FLAGS = ['growth', 'compounding', 'dividend', 'swing', 'short', 'defensive', 'hedge', 'rotation'] as const
const EVENT_TYPES = ['stopped_out', 'discretionary_sale', 'partial_trim', 'rebalance', 'tax_sale', 'rotation', 'assignment_expiration', 'other'] as const
const ROTATION_REASONS = ['volatility_reduction', 'income', 'defensive_posture', 'tax', 'other'] as const

type StrategyFlag = typeof STRATEGY_FLAGS[number]
type EventType = typeof EVENT_TYPES[number]
type MandateType = 'core' | 'satellite' | 'hedge' | 'unclassified'
type GateState = 'PASS' | 'WAIT' | 'BLOCK' | 'UNAVAILABLE'

type Mandate = {
  mandate: MandateType
  flags: Record<StrategyFlag, boolean>
  targetAccount: string
  targetWeightPct: number | null
  priority: 'HIGH' | 'NORMAL' | 'LOW'
  thesis: string
  updatedAt: string
}

type EventClassification = {
  eventType: EventType
  reason: string
  notes: string
  updatedAt: string
}

type RotationLink = {
  id: string
  sourceEventId: number | null
  sourceSymbol: string
  destinationSymbol: string
  account: string
  amountMoved: number | null
  sourceShares: number | null
  sourceExitDate: string
  sourceExitPrice: number | null
  destinationPurchaseDate: string
  destinationCost: number | null
  destinationShares: number | null
  reason: typeof ROTATION_REASONS[number]
  intendedDurationDays: number | null
  switchType: 'temporary' | 'permanent'
  targetSourceAllocationPct: number | null
  returnMode: 'full' | 'staged'
  tranches: number[]
  thesis: string
  invalidation: string
  confirmed: boolean
  suggested: boolean
  rsThresholdPct: number
  taxClear: boolean
  accountClear: boolean
  settlementClear: boolean
  createdAt: string
  updatedAt: string
}

type CompositeAlert = {
  linkId: string
  armed: boolean
  createdAt: string
  updatedAt: string
}

type Technical = {
  symbol: string
  price: number | null
  rsi: number | null
  entryLow: number | null
  entryHigh: number | null
  resistance: number | null
  resistanceDistancePct: number | null
  resistanceSide: 'ABOVE' | 'BELOW' | 'TESTING' | 'UNAVAILABLE'
  resistanceHoldDays: number | null
  resistanceHoldStart: string | null
  resistanceTests: number | null
  trend: 'IMPROVING' | 'CONSTRUCTIVE' | 'DETERIORATING' | 'EXTENDED' | 'UNAVAILABLE'
  macd: string
  relativeStrength: number | null
  ma20: number | null
  ma50: number | null
  ma200: number | null
  asOf: string | null
}

function useJson(url: string | null, ms = 120_000) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!url) return
    let dead = false
    const controller = new AbortController()
    setLoading(true); setError('')
    fetch(url, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `${response.status}`)
        if (!dead) setData(payload?.data && typeof payload.data === 'object' ? payload.data : payload)
      })
      .catch(errorValue => { if (!dead && errorValue?.name !== 'AbortError') setError(String(errorValue?.message || errorValue)) })
      .finally(() => { if (!dead) setLoading(false) })
    const timer = ms > 0 ? window.setTimeout(() => setTick(value => value + 1), ms) : 0
    return () => { dead = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [url, tick, ms])
  return { data, loading, error, refetch: () => setTick(value => value + 1) }
}

function unwrap(value: any): any {
  let result = value
  for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) result = result.data
  return result ?? {}
}
function rows(value: any, keys: string[]): any[] {
  const payload = unwrap(value)
  for (const key of keys) if (Array.isArray(payload?.[key])) return payload[key]
  return Array.isArray(payload) ? payload : []
}
function finite(...values: any[]): number | null {
  for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value)
  return null
}
function text(...values: any[]): string {
  for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  return ''
}
function path(object: any, value: string): any { return value.split('.').reduce((result: any, key) => result?.[key], object) }
function pickNumber(objects: any[], paths: string[]): number | null {
  for (const object of objects) for (const item of paths) { const value = finite(path(object, item)); if (value !== null) return value }
  return null
}
function pickText(objects: any[], paths: string[]): string | null {
  for (const object of objects) for (const item of paths) { const value = text(path(object, item)); if (value) return value }
  return null
}
function day(value: any): string {
  const raw = text(value)
  if (!raw) return ''
  const date = new Date(raw)
  return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : raw.slice(0, 10)
}
function dollars(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function pct(value: number | null, places = 1): string { return value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(places)}%` }
function age(value: string | null): string {
  if (!value) return 'timestamp unavailable'
  const t = new Date(value).getTime()
  if (!Number.isFinite(t)) return value.slice(0, 16)
  const h = Math.max(0, Math.round((Date.now() - t) / 36e5))
  return h < 1 ? 'current' : h < 48 ? `${h}h old` : `${Math.round(h / 24)}d old`
}
function defaultMandate(): Mandate {
  return { mandate: 'unclassified', flags: Object.fromEntries(STRATEGY_FLAGS.map(flag => [flag, false])) as Record<StrategyFlag, boolean>, targetAccount: '', targetWeightPct: null, priority: 'NORMAL', thesis: '', updatedAt: '' }
}
function defaultEvent(): EventClassification { return { eventType: 'other', reason: '', notes: '', updatedAt: '' } }
function prefValue(data: any): Record<string, any> {
  const value = unwrap(data)?.value
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}
async function savePref(key: string, value: any) {
  const response = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, value }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'preference save failed')
}

function technical(symbol: string, cardMap: Record<string, any>, watchMap: Record<string, any>): Technical {
  const card = cardMap[symbol] ?? {}
  const watch = watchMap[symbol] ?? {}
  const packet = watch?.decision_packet ?? card?.decision_packet ?? {}
  const mechanics = packet?.selected_family?.mechanics ?? packet?.current_mechanics ?? packet?.mechanics ?? {}
  const objects = [watch, card, packet, mechanics]
  const price = pickNumber(objects, ['last_price', 'price', 'current_price', 'quote_price', 'quote.last'])
  const rsi = pickNumber(objects, ['rsi', 'rsi_14', 'current_rsi', 'technicals.rsi', 'indicators.rsi'])
  let entryLow = pickNumber(objects, ['reentry_low', 'reentry_zone_low', 'entry_zone_low', 'entry_low', 'mechanics.entry_low'])
  let entryHigh = pickNumber(objects, ['reentry_high', 'reentry_zone_high', 'entry_zone_high', 'entry_high', 'mechanics.entry_high'])
  const entry = pickNumber(objects, ['reentry_price', 'entry_limit', 'entry_price', 'mechanics.entry'])
  if (entryLow === null) entryLow = entry
  if (entryHigh === null) entryHigh = entry
  if (entryLow !== null && entryHigh !== null && entryLow > entryHigh) [entryLow, entryHigh] = [entryHigh, entryLow]
  const resistance = pickNumber(objects, ['resistance', 'resistance_price', 'sc_resistance', 'technical.resistance', 'technicals.resistance', 'trigger_price', 'mechanics.trigger'])
  const tolerance = resistance === null ? null : Math.max(resistance * 0.005, 0.02)
  const distance = price !== null && resistance !== null && resistance > 0 ? ((price - resistance) / resistance) * 100 : null
  const resistanceSide: Technical['resistanceSide'] = price === null || resistance === null || tolerance === null
    ? 'UNAVAILABLE' : Math.abs(price - resistance) <= tolerance ? 'TESTING' : price > resistance ? 'ABOVE' : 'BELOW'
  const holdDays = pickNumber(objects, ['resistance_hold_days', 'days_above_resistance', 'breakout_hold_days', 'reclaim_hold_days', 'technicals.resistance_hold_days'])
  const holdStart = pickText(objects, ['resistance_hold_start', 'breakout_hold_start', 'reclaim_date', 'technicals.resistance_hold_start'])
  const resistanceTests = pickNumber(objects, ['resistance_tests', 'resistance_test_count', 'breakout_test_count', 'technicals.resistance_tests'])
  const ma20 = pickNumber(objects, ['ma20', 'sma20', 'technicals.sma20', 'technical.ma20'])
  const ma50 = pickNumber(objects, ['ma50', 'sma50', 'technicals.sma50', 'technical.ma50'])
  const ma200 = pickNumber(objects, ['ma200', 'sma200', 'technicals.sma200', 'technical.ma200'])
  const macdHistogram = pickNumber(objects, ['macd_histogram', 'macd_hist', 'technicals.macd_histogram', 'technical.macd_histogram'])
  const macdSlope = pickNumber(objects, ['macd_histogram_change', 'macd_slope', 'technicals.macd_histogram_change'])
  const relativeStrength = pickNumber(objects, ['relative_strength', 'rs_score', 'relative_strength_pct', 'technicals.relative_strength'])
  const explicitTrend = text(pickText(objects, ['trend_direction', 'trend_state', 'technicals.trend', 'technical.trend'])).toUpperCase()
  let trend: Technical['trend'] = 'UNAVAILABLE'
  if (/DETERIOR|BEAR|DOWN/.test(explicitTrend)) trend = 'DETERIORATING'
  else if (/IMPROV|RECOVER|UP/.test(explicitTrend)) trend = 'IMPROVING'
  else if (/CONSTRUCT|BULL/.test(explicitTrend)) trend = 'CONSTRUCTIVE'
  else if (/EXTEND|OVERBOUGHT/.test(explicitTrend)) trend = 'EXTENDED'
  else if (price !== null && ma20 !== null && ma50 !== null) {
    if (price > ma20 && ma20 > ma50 && (macdHistogram === null || macdHistogram >= 0)) trend = macdSlope !== null && macdSlope > 0 ? 'IMPROVING' : 'CONSTRUCTIVE'
    else if (price < ma20 && ma20 < ma50) trend = 'DETERIORATING'
    else if (rsi !== null && rsi >= 70) trend = 'EXTENDED'
  }
  const macd = macdHistogram === null ? 'UNAVAILABLE' : `${macdHistogram >= 0 ? 'positive' : 'negative'}${macdSlope === null ? '' : macdSlope > 0 ? ' · improving' : macdSlope < 0 ? ' · deteriorating' : ' · flat'}`
  return { symbol, price, rsi, entryLow, entryHigh, resistance, resistanceDistancePct: distance, resistanceSide, resistanceHoldDays: holdDays, resistanceHoldStart: holdStart, resistanceTests, trend, macd, relativeStrength, ma20, ma50, ma200, asOf: pickText(objects, ['last_enriched_at', 'computed_at', 'as_of', 'updated_at', 'quote_time', 'technicals.as_of']) }
}

function analystFor(symbol: string, analystData: any) {
  const payload = unwrap(analystData)
  const map = payload?.by_symbol ?? payload?.symbols ?? payload?.analysts ?? payload
  return map?.[symbol] ?? map?.[symbol.toUpperCase()] ?? null
}
function lookthroughFor(symbol: string, lookthroughData: any) {
  const payload = unwrap(lookthroughData)
  const maps = [payload?.by_symbol, payload?.funds, payload?.etfs, payload?.lookthrough, payload]
  for (const map of maps) if (map?.[symbol]) return map[symbol]
  return null
}
function positionRows(data: any): any[] { return rows(data, ['positions', 'rows', 'holdings', 'open_positions']) }
function positionSymbol(row: any): string { return text(row.symbol, row.ticker).toUpperCase() }
function positionAccount(row: any): string { return text(row.account, row.account_key, row.account_name) }
function positionAmount(row: any): number | null { return finite(row.cost_basis, row.market_value, row.value, row.position_value, finite(row.avg_price, row.cost_per_share) && finite(row.shares, row.quantity) ? Number(row.avg_price ?? row.cost_per_share) * Number(row.shares ?? row.quantity) : null) }

function gate(state: GateState, label: string, current: string, threshold: string, why: string) { return { state, label, current, threshold, why } }
function gateColor(state: GateState): string { return state === 'PASS' ? BB.green : state === 'BLOCK' ? BB.red : state === 'WAIT' ? BB.amber : BB.text3 }

function returnGates(link: RotationLink, source: Technical, destination: Technical, regimeData: any, taxRows: any[]) {
  const regime = text(unwrap(regimeData)?.regime_label, unwrap(regimeData)?.label).toUpperCase()
  const constructive = regime ? !/RISK_OFF|DEFENSIVE|DISRUPT|BEAR/.test(regime) : null
  const rsSpread = source.relativeStrength !== null && destination.relativeStrength !== null ? source.relativeStrength - destination.relativeStrength : null
  const inZone = source.price !== null && source.entryLow !== null && source.entryHigh !== null ? source.price >= source.entryLow && source.price <= source.entryHigh : null
  const rsiGood = source.rsi !== null ? source.rsi >= 40 && source.rsi < 70 : null
  const hasWashFlag = taxRows.some(row => text(row.symbol, row.ticker).toUpperCase() === link.sourceSymbol && /wash|disallow|block/i.test(`${text(row.status)} ${text(row.note)} ${text(row.reason)}`))
  return [
    constructive === null ? gate('UNAVAILABLE', 'Risk regime constructive', 'unavailable', 'constructive / risk-on', 'Current risk-regime evidence is unavailable.') : constructive ? gate('PASS', 'Risk regime constructive', regime, 'constructive / risk-on', 'The current regime is not labeled risk-off or defensive.') : gate('WAIT', 'Risk regime constructive', regime, 'constructive / risk-on', 'The current regime is still defensive or risk-off.'),
    source.trend === 'UNAVAILABLE' ? gate('UNAVAILABLE', 'Source trend improving', 'unavailable', 'IMPROVING or CONSTRUCTIVE', 'Trend evidence is unavailable.') : ['IMPROVING', 'CONSTRUCTIVE'].includes(source.trend) ? gate('PASS', 'Source trend improving', source.trend, 'IMPROVING or CONSTRUCTIVE', 'The source trend has improved enough for review.') : gate('WAIT', 'Source trend improving', source.trend, 'IMPROVING or CONSTRUCTIVE', 'The source trend remains deteriorating or extended.'),
    rsSpread === null ? gate('UNAVAILABLE', 'Relative strength reclaimed', 'unavailable', `≥ ${link.rsThresholdPct.toFixed(1)}%`, 'Both source and destination relative-strength values are required.') : rsSpread >= link.rsThresholdPct ? gate('PASS', 'Relative strength reclaimed', pct(rsSpread), `≥ ${link.rsThresholdPct.toFixed(1)}%`, 'Source relative strength has reclaimed the configured spread.') : gate('WAIT', 'Relative strength reclaimed', pct(rsSpread), `≥ ${link.rsThresholdPct.toFixed(1)}%`, 'Source relative strength still trails the return threshold.'),
    inZone === null ? gate('UNAVAILABLE', 'Re-entry zone confirmed', 'unavailable', 'price inside validated zone', 'A current source price and validated entry zone are required.') : inZone ? gate('PASS', 'Re-entry zone confirmed', dollars(source.price), `${dollars(source.entryLow)}–${dollars(source.entryHigh)}`, 'Source price is inside the validated re-entry zone.') : gate('WAIT', 'Re-entry zone confirmed', dollars(source.price), `${dollars(source.entryLow)}–${dollars(source.entryHigh)}`, 'Source price is outside the validated re-entry zone.'),
    rsiGood === null ? gate('UNAVAILABLE', 'RSI constructive, not overbought', 'unavailable', '40 ≤ RSI < 70', 'Current RSI is required.') : rsiGood ? gate('PASS', 'RSI constructive, not overbought', source.rsi!.toFixed(1), '40 ≤ RSI < 70', 'RSI is constructive without being overbought.') : gate('WAIT', 'RSI constructive, not overbought', source.rsi!.toFixed(1), '40 ≤ RSI < 70', source.rsi! >= 70 ? 'RSI is overbought.' : 'RSI is not yet constructive.'),
    !link.taxClear || !link.accountClear || !link.settlementClear || hasWashFlag ? gate('BLOCK', 'No tax, wash-sale, account, or settlement block', `tax ${link.taxClear ? 'clear' : 'blocked'} · account ${link.accountClear ? 'clear' : 'blocked'} · settlement ${link.settlementClear ? 'clear' : 'blocked'}${hasWashFlag ? ' · wash flag' : ''}`, 'all clear', 'At least one operator or tax-lot constraint blocks rotation back.') : gate('PASS', 'No tax, wash-sale, account, or settlement block', 'all clear', 'all clear', 'No configured constraint blocks advisory review.'),
  ]
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode }) {
  return <div role="dialog" aria-modal="true" onMouseDown={onClose} style={{ position: 'fixed', inset: 0, zIndex: 1200, background: 'rgba(2,6,23,.82)', display: 'grid', placeItems: 'center', padding: 18 }}>
    <div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(920px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}><div style={{ flex: 1 }}><div style={{ fontSize: 20, fontWeight: 900 }}>{title}</div><div style={{ fontSize: 10.5, color: BB.text3 }}>{subtitle}</div></div><button onClick={onClose} style={btn(false)}>CLOSE</button></div>
      {children}
    </div>
  </div>
}

function MandateEventModal({ symbol, event, mandate, classification, onClose, onSave }: { symbol: string; event: any; mandate: Mandate; classification: EventClassification; onClose: () => void; onSave: (mandate: Mandate, classification: EventClassification) => Promise<void> }) {
  const [m, setM] = useState<Mandate>({ ...defaultMandate(), ...mandate, flags: { ...defaultMandate().flags, ...(mandate?.flags ?? {}) } })
  const [c, setC] = useState<EventClassification>({ ...defaultEvent(), ...classification })
  const [busy, setBusy] = useState(false)
  return <Modal title={`${symbol} · Mandate and Exit Classification`} subtitle="Symbol mandate is persistent; this event's exit classification remains separate." onClose={onClose}>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
      <div style={{ ...panel, padding: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>SYMBOL MANDATE</div>
        <select value={m.mandate} onChange={eventValue => setM(value => ({ ...value, mandate: eventValue.target.value as MandateType }))} style={field}>
          <option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option>
        </select>
        <div style={{ fontSize: 10.5, fontWeight: 850, margin: '12px 0 6px' }}>INDEPENDENT STRATEGY FLAGS</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {STRATEGY_FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 8, background: m.flags[flag] ? BB.blueDim : 'var(--bg2)' }}><input type="checkbox" checked={m.flags[flag]} onChange={eventValue => setM(value => ({ ...value, flags: { ...value.flags, [flag]: eventValue.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
          <label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={m.targetAccount} onChange={eventValue => setM(value => ({ ...value, targetAccount: eventValue.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
          <label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={m.targetWeightPct ?? ''} onChange={eventValue => setM(value => ({ ...value, targetWeightPct: eventValue.target.value === '' ? null : Number(eventValue.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
        </div>
        <label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 10 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={m.thesis} onChange={eventValue => setM(value => ({ ...value, thesis: eventValue.target.value }))} style={{ ...field, marginTop: 4, resize: 'vertical' }} /></label>
      </div>
      <div style={{ ...panel, padding: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>SELECTED EXIT EVENT</div>
        <div style={{ fontSize: 10.5, color: BB.text3, marginBottom: 8 }}>{day(event?.sold_at ?? event?.close_date)} · {text(event?.account, event?.account_key) || 'account unavailable'} · {dollars(finite(event?.proceeds_usd, event?.proceeds))}</div>
        <select value={c.eventType} onChange={eventValue => setC(value => ({ ...value, eventType: eventValue.target.value as EventType }))} style={field}>{EVENT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select>
        <label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 10 }}>REASON<input value={c.reason} onChange={eventValue => setC(value => ({ ...value, reason: eventValue.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
        <label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 10 }}>EVENT NOTES<textarea rows={8} value={c.notes} onChange={eventValue => setC(value => ({ ...value, notes: eventValue.target.value }))} style={{ ...field, marginTop: 4, resize: 'vertical' }} /></label>
      </div>
    </div>
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={onClose} style={btn(false)}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); void onSave({ ...m, updatedAt: new Date().toISOString() }, { ...c, updatedAt: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...btn(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE MANDATE + EVENT'}</button></div>
  </Modal>
}

function RotationModal({ sourceEvent, positions, existing, onClose, onSave }: { sourceEvent: any; positions: any[]; existing?: RotationLink; onClose: () => void; onSave: (link: RotationLink) => Promise<void> }) {
  const sourceSymbol = text(sourceEvent?.symbol).toUpperCase()
  const sourceAmount = finite(sourceEvent?.proceeds_usd, sourceEvent?.proceeds, sourceEvent?.net_proceeds)
  const sourceAccount = text(sourceEvent?.account, sourceEvent?.account_key)
  const candidates = positions.filter(position => positionSymbol(position) && positionSymbol(position) !== sourceSymbol && (!sourceAccount || !positionAccount(position) || positionAccount(position) === sourceAccount)).map(position => {
    const amount = positionAmount(position)
    const score = sourceAmount && amount ? Math.abs(amount - sourceAmount) / Math.max(sourceAmount, 1) : 1
    return { position, score }
  }).sort((a, b) => a.score - b.score)
  const suggestion = candidates[0]?.position
  const base: RotationLink = existing ?? {
    id: `rotation:${sourceEvent?.event_id ?? sourceSymbol}:${Date.now()}`, sourceEventId: finite(sourceEvent?.event_id), sourceSymbol,
    destinationSymbol: positionSymbol(suggestion), account: sourceAccount || positionAccount(suggestion), amountMoved: sourceAmount,
    sourceShares: finite(sourceEvent?.shares_sold, sourceEvent?.shares), sourceExitDate: day(sourceEvent?.sold_at ?? sourceEvent?.close_date), sourceExitPrice: finite(sourceEvent?.sell_price, sourceEvent?.exit_price, sourceEvent?.price),
    destinationPurchaseDate: day(suggestion?.held_since ?? suggestion?.purchase_date ?? suggestion?.open_date), destinationCost: finite(suggestion?.avg_price, suggestion?.cost_per_share, suggestion?.cost_basis_per_share), destinationShares: finite(suggestion?.shares, suggestion?.quantity),
    reason: 'volatility_reduction', intendedDurationDays: 90, switchType: 'temporary', targetSourceAllocationPct: 100, returnMode: 'staged', tranches: [25, 25, 50], thesis: '', invalidation: '', confirmed: false, suggested: Boolean(suggestion), rsThresholdPct: 0, taxClear: false, accountClear: true, settlementClear: Boolean(sourceEvent?.settled), createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
  }
  const [value, setValue] = useState<RotationLink>(base)
  const [busy, setBusy] = useState(false)
  const total = value.tranches.reduce((sum, item) => sum + Number(item || 0), 0)
  const valid = value.sourceSymbol && value.destinationSymbol && (value.returnMode === 'full' || Math.abs(total - 100) < 0.01)
  return <Modal title={`${sourceSymbol} · Rotation Link`} subtitle="Automatic matches are suggestions only. Confirm the source-to-destination capital lineage explicitly." onClose={onClose}>
    {base.suggested && <div style={{ ...panel, padding: 9, marginBottom: 10, borderColor: BB.amber }}><b style={{ color: BB.amber }}>SUGGESTED MATCH:</b> {sourceSymbol} → {base.destinationSymbol || 'no candidate'} based on same-account/current-position evidence. Not confirmed.</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 9 }}>
      <label style={{ fontSize: 10, color: BB.text3 }}>SOURCE POSITION<input value={value.sourceSymbol} disabled style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>TEMPORARY DESTINATION<input value={value.destinationSymbol} onChange={event => setValue(current => ({ ...current, destinationSymbol: event.target.value.toUpperCase() }))} list="rotation-destinations" style={{ ...field, marginTop: 4 }} /><datalist id="rotation-destinations">{positions.map(position => <option key={`${positionSymbol(position)}:${positionAccount(position)}`} value={positionSymbol(position)} />)}</datalist></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>ACCOUNT<input value={value.account} onChange={event => setValue(current => ({ ...current, account: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>AMOUNT MOVED<input type="number" value={value.amountMoved ?? ''} onChange={event => setValue(current => ({ ...current, amountMoved: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>SOURCE SHARES<input type="number" value={value.sourceShares ?? ''} onChange={event => setValue(current => ({ ...current, sourceShares: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>SOURCE EXIT DATE<input type="date" value={value.sourceExitDate} onChange={event => setValue(current => ({ ...current, sourceExitDate: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>SOURCE EXIT PRICE<input type="number" step="0.01" value={value.sourceExitPrice ?? ''} onChange={event => setValue(current => ({ ...current, sourceExitPrice: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION PURCHASE DATE<input type="date" value={value.destinationPurchaseDate} onChange={event => setValue(current => ({ ...current, destinationPurchaseDate: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION COST / SHARE<input type="number" step="0.01" value={value.destinationCost ?? ''} onChange={event => setValue(current => ({ ...current, destinationCost: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION SHARES<input type="number" value={value.destinationShares ?? ''} onChange={event => setValue(current => ({ ...current, destinationShares: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>REASON<select value={value.reason} onChange={event => setValue(current => ({ ...current, reason: event.target.value as RotationLink['reason'] }))} style={{ ...field, marginTop: 4 }}>{ROTATION_REASONS.map(reason => <option key={reason} value={reason}>{reason.replace(/_/g, ' ').toUpperCase()}</option>)}</select></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>INTENDED DURATION (DAYS)<input type="number" min="0" value={value.intendedDurationDays ?? ''} onChange={event => setValue(current => ({ ...current, intendedDurationDays: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>SWITCH TYPE<select value={value.switchType} onChange={event => setValue(current => ({ ...current, switchType: event.target.value as RotationLink['switchType'] }))} style={{ ...field, marginTop: 4 }}><option value="temporary">TEMPORARY</option><option value="permanent">PERMANENT</option></select></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>TARGET SOURCE ALLOCATION %<input type="number" min="0" max="100" value={value.targetSourceAllocationPct ?? ''} onChange={event => setValue(current => ({ ...current, targetSourceAllocationPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>RETURN MODE<select value={value.returnMode} onChange={event => setValue(current => ({ ...current, returnMode: event.target.value as RotationLink['returnMode'] }))} style={{ ...field, marginTop: 4 }}><option value="full">FULL RETURN</option><option value="staged">STAGED RETURN</option></select></label>
      <label style={{ fontSize: 10, color: BB.text3 }}>RS RECLAIM THRESHOLD %<input type="number" step="0.1" value={value.rsThresholdPct} onChange={event => setValue(current => ({ ...current, rsThresholdPct: Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label>
    </div>
    {value.returnMode === 'staged' && <div style={{ ...panel, padding: 10, marginTop: 10 }}><div style={{ fontSize: 10.5, fontWeight: 850 }}>ROTATION-BACK TRANCHES · total {total.toFixed(1)}%</div><div style={{ display: 'flex', gap: 8, marginTop: 6 }}>{value.tranches.map((tranche, index) => <input key={index} type="number" min="0" max="100" value={tranche} onChange={event => setValue(current => ({ ...current, tranches: current.tranches.map((item, itemIndex) => itemIndex === index ? Number(event.target.value) : item) }))} style={{ ...field, width: 100 }} />)}</div>{Math.abs(total - 100) >= 0.01 && <div style={{ fontSize: 10, color: BB.red, marginTop: 4 }}>Staged percentages must total 100%.</div>}</div>}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9, marginTop: 10 }}><label style={{ fontSize: 10, color: BB.text3 }}>ROTATION THESIS<textarea rows={4} value={value.thesis} onChange={event => setValue(current => ({ ...current, thesis: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>INVALIDATION<textarea rows={4} value={value.invalidation} onChange={event => setValue(current => ({ ...current, invalidation: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label></div>
    <div style={{ display: 'flex', gap: 12, marginTop: 10, flexWrap: 'wrap' }}><label><input type="checkbox" checked={value.taxClear} onChange={event => setValue(current => ({ ...current, taxClear: event.target.checked }))} /> Tax / wash-sale reviewed clear</label><label><input type="checkbox" checked={value.accountClear} onChange={event => setValue(current => ({ ...current, accountClear: event.target.checked }))} /> Account constraints clear</label><label><input type="checkbox" checked={value.settlementClear} onChange={event => setValue(current => ({ ...current, settlementClear: event.target.checked }))} /> Settlement clear</label><label><input type="checkbox" checked={value.confirmed} onChange={event => setValue(current => ({ ...current, confirmed: event.target.checked, suggested: !event.target.checked && current.suggested }))} /> Operator confirms capital lineage</label></div>
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}><button onClick={onClose} style={btn(false)}>CANCEL</button><button disabled={busy || !valid} onClick={() => { setBusy(true); void onSave({ ...value, updatedAt: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...btn(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : value.confirmed ? 'SAVE CONFIRMED LINK' : 'SAVE SUGGESTION'}</button></div>
  </Modal>
}

function AnalystPill({ symbol, data, isFund }: { symbol: string; data: any; isFund: boolean }) {
  if (isFund) {
    const value = finite(data?.analyst_look_through_pct, data?.look_through_analyst_pct, data?.analystLookThroughPct)
    return <span title="ETF/fund look-through analyst measure; not a direct ETF analyst consensus" style={{ fontSize: 10, fontWeight: 850, color: value === null ? BB.text3 : BB.blue, border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px' }}>{value === null ? 'LOOK-THROUGH UNAVAILABLE' : `LOOK-THROUGH ${value.toFixed(0)}%`}</span>
  }
  const label = text(data?.consensus_label, data?.rating, data?.consensus, data?.recommendation)
  const count = finite(data?.analyst_count, data?.count, data?.total)
  const upside = finite(data?.upside_pct, data?.target_upside_pct, data?.mean_upside_pct)
  return <span title={`Real analyst consensus${count === null ? '' : ` · ${count} analysts`}${upside === null ? '' : ` · ${pct(upside)} to mean target`}`} style={{ fontSize: 10, fontWeight: 850, color: label ? BB.blue : BB.text3, border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px' }}>{label ? `${label.toUpperCase()}${count === null ? '' : ` · ${count}`}${upside === null ? '' : ` · ${pct(upside)}`}` : 'ANALYST UNAVAILABLE'}</span>
}

function TechnicalCard({ value, analyst, lookthrough }: { value: Technical; analyst: any; lookthrough: any }) {
  const isFund = Boolean(lookthrough || /ETF|FUND/i.test(text(analyst?.instrument_type)))
  return <div style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center' }}><b style={{ fontSize: 16 }}>{value.symbol}</b><AnalystPill symbol={value.symbol} data={isFund ? lookthrough : analyst} isFund={isFund} /><span style={{ fontSize: 10, color: BB.text3 }}>{age(value.asOf)}</span></div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 7, marginTop: 8, fontSize: 10.5 }}>
      <div><span style={{ color: BB.text3 }}>Price</span><br /><b>{dollars(value.price)}</b></div><div><span style={{ color: BB.text3 }}>RSI</span><br /><b>{value.rsi === null ? '—' : value.rsi.toFixed(1)}</b></div><div><span style={{ color: BB.text3 }}>Trend</span><br /><b>{value.trend}</b></div>
      <div><span style={{ color: BB.text3 }}>Resistance</span><br /><b>{dollars(value.resistance)}</b></div><div><span style={{ color: BB.text3 }}>Distance</span><br /><b>{value.resistanceSide} · {pct(value.resistanceDistancePct)}</b></div><div><span style={{ color: BB.text3 }}>Held above</span><br /><b>{value.resistanceHoldDays === null ? 'UNAVAILABLE' : `${value.resistanceHoldDays} closed sessions`}</b></div>
      <div><span style={{ color: BB.text3 }}>Hold start</span><br /><b>{value.resistanceHoldStart || 'UNAVAILABLE'}</b></div><div><span style={{ color: BB.text3 }}>Tests</span><br /><b>{value.resistanceTests === null ? 'UNAVAILABLE' : value.resistanceTests}</b></div><div><span style={{ color: BB.text3 }}>MACD</span><br /><b>{value.macd}</b></div>
      <div><span style={{ color: BB.text3 }}>MA20 / 50 / 200</span><br /><b>{dollars(value.ma20)} / {dollars(value.ma50)} / {dollars(value.ma200)}</b></div><div><span style={{ color: BB.text3 }}>Relative strength</span><br /><b>{pct(value.relativeStrength)}</b></div><div><span style={{ color: BB.text3 }}>Entry zone</span><br /><b>{dollars(value.entryLow)}–{dollars(value.entryHigh)}</b></div>
    </div>
    {isFund && <div style={{ fontSize: 10, color: BB.text3, marginTop: 7 }}>Expense {finite(lookthrough?.expense_ratio) === null ? '—' : `${finite(lookthrough?.expense_ratio)!.toFixed(2)}%`} · yield {finite(lookthrough?.distribution_yield, lookthrough?.yield_pct) === null ? '—' : `${finite(lookthrough?.distribution_yield, lookthrough?.yield_pct)!.toFixed(2)}%`} · effective weights and top holdings from fund look-through when available.</div>}
  </div>
}

export default function ReEntryRotationWorkspace({ mode = 'full', eventId: eventIdProp, initialSymbol }: { mode?: 'full' | 'bridge'; eventId?: number | null; initialSymbol?: string }) {
  const book = useJson('/api/v2/redeploy/book?limit=1000&include_dismissed=1')
  const journal = useJson('/api/v2/journal')
  const positions = useJson('/api/v2/rec-intel/open-positions')
  const cards = useJson('/api/v2/symbol-cards', 300_000)
  const analyst = useJson('/api/v2/analyst-detail', 300_000)
  const lookthrough = useJson('/api/v2/portfolio/lookthrough', 300_000)
  const dividends = useJson('/api/v2/dividends', 300_000)
  const taxLots = useJson('/api/v2/tax-lots', 300_000)
  const regime = useJson('/api/v2/risk-regime/latest', 300_000)
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const rotationsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(ROTATION_KEY)}`, 0)
  const alertsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(COMPOSITE_ALERT_KEY)}`, 0)

  const [mandates, setMandates] = useState<Record<string, Mandate>>({})
  const [classifications, setClassifications] = useState<Record<string, EventClassification>>({})
  const [links, setLinks] = useState<Record<string, RotationLink>>({})
  const [compositeAlerts, setCompositeAlerts] = useState<Record<string, CompositeAlert>>({})
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [search, setSearch] = useState(initialSymbol ?? '')
  const [selectedEvent, setSelectedEvent] = useState<any>(null)
  const [rotationEvent, setRotationEvent] = useState<any>(null)
  const [expandedLink, setExpandedLink] = useState<string | null>(null)
  const [toast, setToast] = useState('')

  useEffect(() => { setMandates(prefValue(mandatesPref.data) as Record<string, Mandate>) }, [mandatesPref.data])
  useEffect(() => { setClassifications(prefValue(eventsPref.data) as Record<string, EventClassification>) }, [eventsPref.data])
  useEffect(() => { setLinks(prefValue(rotationsPref.data) as Record<string, RotationLink>) }, [rotationsPref.data])
  useEffect(() => { setCompositeAlerts(prefValue(alertsPref.data) as Record<string, CompositeAlert>) }, [alertsPref.data])

  const bookRows = rows(book.data, ['rows'])
  const journalRows = rows(journal.data, ['trades'])
  const allEvents = useMemo(() => {
    const byId = new Map<string, any>()
    const add = (row: any, source: string, index: number) => {
      const symbol = text(row.symbol, row.ticker).toUpperCase()
      if (!symbol) return
      const id = text(row.event_id, row.trade_key, row.id, `${source}:${symbol}:${day(row.sold_at ?? row.close_date)}:${index}`)
      const prior = byId.get(id) ?? {}
      byId.set(id, { ...prior, ...row, symbol, _eventKey: id, _source: source })
    }
    bookRows.forEach((row, index) => add(row, 'redeploy-book', index))
    journalRows.forEach((row, index) => add(row, 'real-journal', index))
    return [...byId.values()].sort((a, b) => day(b.sold_at ?? b.close_date).localeCompare(day(a.sold_at ?? a.close_date)))
  }, [bookRows, journalRows])

  const currentEvent = eventIdProp ? allEvents.find(row => Number(row.event_id) === Number(eventIdProp)) : null
  useEffect(() => { if (currentEvent && mode === 'bridge') setSearch(currentEvent.symbol) }, [currentEvent?._eventKey, mode])

  const symbols = useMemo(() => [...new Set([...allEvents.map(row => row.symbol), ...Object.values(links).flatMap(link => [link.sourceSymbol, link.destinationSymbol])].filter(Boolean))].slice(0, 300), [allEvents, links])
  useEffect(() => {
    if (!symbols.length) return
    let dead = false
    const controller = new AbortController()
    let cursor = 0
    const output: Record<string, any> = {}
    const worker = async () => {
      while (!dead) {
        const index = cursor++
        if (index >= symbols.length) return
        const symbol = symbols[index]
        try {
          const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal: controller.signal })
          const payload = unwrap(await response.json())
          output[symbol] = (payload?.items ?? [])[0] ?? null
        } catch { output[symbol] = null }
      }
    }
    void Promise.all(Array.from({ length: Math.min(8, symbols.length) }, () => worker())).then(() => { if (!dead) setWatchMap(previous => ({ ...previous, ...output })) })
    return () => { dead = true; controller.abort() }
  }, [symbols.join('|')])

  const cardMap: Record<string, any> = unwrap(cards.data)?.cards ?? {}
  const openPositions = positionRows(positions.data)
  const taxRows = rows(taxLots.data, ['lots', 'rows', 'tax_lots'])
  const dividendRows = rows(dividends.data, ['rows', 'dividends', 'payments'])
  const filteredEvents = allEvents.filter(row => !search.trim() || `${row.symbol} ${text(row.account, row.account_key)} ${text(row.reason, row.exit_reason)}`.toUpperCase().includes(search.trim().toUpperCase()))
  const sourceErrors = [book.error && `Redeploy book: ${book.error}`, journal.error && `Real journal: ${journal.error}`, positions.error && `Open positions: ${positions.error}`].filter(Boolean)

  const saveMandateAndEvent = async (event: any, mandate: Mandate, classification: EventClassification) => {
    const nextMandates = { ...mandates, [event.symbol]: mandate }
    const nextClassifications = { ...classifications, [event._eventKey]: classification }
    await Promise.all([savePref(MANDATE_KEY, nextMandates), savePref(EVENT_KEY, nextClassifications)])
    setMandates(nextMandates); setClassifications(nextClassifications); setToast(`${event.symbol} mandate and event classification saved`); setSelectedEvent(null)
  }
  const saveRotation = async (link: RotationLink) => {
    const next = { ...links, [link.id]: link }
    await savePref(ROTATION_KEY, next)
    setLinks(next); setToast(`${link.sourceSymbol} → ${link.destinationSymbol} ${link.confirmed ? 'confirmed' : 'saved as suggestion'}`); setRotationEvent(null)
  }
  const armComposite = async (link: RotationLink, gates: ReturnType<typeof returnGates>) => {
    if (gates.some(item => item.state === 'UNAVAILABLE')) { setToast('Composite alert not armed: mandatory evidence is unavailable.'); return }
    const next = { ...compositeAlerts, [link.id]: { linkId: link.id, armed: true, createdAt: compositeAlerts[link.id]?.createdAt ?? new Date().toISOString(), updatedAt: new Date().toISOString() } }
    await savePref(COMPOSITE_ALERT_KEY, next)
    setCompositeAlerts(next); setToast(`${link.sourceSymbol} return-to-growth composite monitor armed`)
  }

  const header = <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}><div><div style={{ fontSize: mode === 'full' ? 24 : 18, fontWeight: 900 }}>Re-Entry + Rotation Intelligence</div><div style={{ fontSize: 10.5, color: BB.text3 }}>Authoritative exits · persistent mandate + event classification · confirmed capital lineage · analyst/look-through · resistance · six-gate return monitor</div></div>{mode === 'bridge' && <Link to={`/portfolio/re-entry${currentEvent?.symbol ? `?symbol=${encodeURIComponent(currentEvent.symbol)}` : ''}`} style={{ ...btn(true), textDecoration: 'none' }}>OPEN FULL RE-ENTRY WORKSTATION</Link>}</div>

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
    {header}
    {sourceErrors.length > 0 && <div style={{ ...panel, padding: 10, borderColor: BB.red }}><b style={{ color: BB.red }}>COVERAGE BLOCKED</b>{sourceErrors.map(error => <div key={String(error)} style={{ fontSize: 10, color: BB.red }}>{error}</div>)}</div>}
    <div style={{ ...panel, padding: 9, display: 'grid', gridTemplateColumns: mode === 'full' ? 'minmax(220px,1fr) repeat(4,minmax(120px,160px))' : '1fr', gap: 8 }}>
      <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbol, account, or reason…" style={field} />
      {mode === 'full' && <><div style={{ fontSize: 10, color: BB.text3 }}>Events<br /><b style={{ fontSize: 18, color: BB.text0 }}>{allEvents.length}</b></div><div style={{ fontSize: 10, color: BB.text3 }}>Symbols<br /><b style={{ fontSize: 18, color: BB.text0 }}>{new Set(allEvents.map(row => row.symbol)).size}</b></div><div style={{ fontSize: 10, color: BB.text3 }}>Confirmed rotations<br /><b style={{ fontSize: 18, color: BB.text0 }}>{Object.values(links).filter(link => link.confirmed).length}</b></div><div style={{ fontSize: 10, color: BB.text3 }}>Composite monitors<br /><b style={{ fontSize: 18, color: BB.text0 }}>{Object.values(compositeAlerts).filter(alert => alert.armed).length}</b></div></>}
    </div>
    {toast && <div style={{ fontSize: 10.5, color: BB.blue }}>{toast}</div>}

    <div style={{ ...panel, overflowX: 'auto' }}><div style={{ minWidth: 1180 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '72px 110px 110px 100px 220px 250px 220px', gap: 8, padding: '7px 10px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Date / account</span><span>Exit</span><span>Proceeds</span><span>Mandate / strategy</span><span>Event classification</span><span>Actions</span></div>
      {filteredEvents.slice(0, mode === 'bridge' ? 10 : 500).map(event => {
        const mandate = { ...defaultMandate(), ...(mandates[event.symbol] ?? {}), flags: { ...defaultMandate().flags, ...(mandates[event.symbol]?.flags ?? {}) } }
        const classification = { ...defaultEvent(), ...(classifications[event._eventKey] ?? {}) }
        const related = Object.values(links).filter(link => link.sourceEventId === Number(event.event_id) || (!link.sourceEventId && link.sourceSymbol === event.symbol && link.sourceExitDate === day(event.sold_at ?? event.close_date)))
        return <div key={event._eventKey} style={{ display: 'grid', gridTemplateColumns: '72px 110px 110px 100px 220px 250px 220px', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}>
          <b style={{ fontSize: 13 }}>{event.symbol}</b><div>{day(event.sold_at ?? event.close_date) || 'date unavailable'}<br /><span style={{ color: BB.text3 }}>{text(event.account, event.account_key) || 'account unavailable'}</span></div><div>{dollars(finite(event.sell_price, event.exit_price, event.price))}<br /><span style={{ color: BB.text3 }}>{finite(event.shares_sold, event.shares) ?? '—'} shares</span></div><b>{dollars(finite(event.proceeds_usd, event.proceeds, event.net_proceeds))}</b>
          <div><b>{mandate.mandate.replace(/_/g, ' ').toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{STRATEGY_FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()).join(' · ') || 'NO STRATEGY FLAGS'}</span></div>
          <div><b>{classification.eventType.replace(/_/g, ' ').toUpperCase()}</b><br /><span style={{ color: BB.text3 }}>{classification.reason || text(event.reason, event.exit_reason, event.completion_status) || 'reason not classified'}</span>{related.map(link => <div key={link.id} style={{ color: link.confirmed ? BB.green : BB.amber }}>{link.confirmed ? 'CONFIRMED' : 'SUGGESTED'} {link.sourceSymbol} → {link.destinationSymbol}</div>)}</div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}><button onClick={() => setSelectedEvent(event)} style={btn(false)}>MANDATE + EXIT</button><button onClick={() => setRotationEvent(event)} style={btn(Boolean(related.length))}>ROTATION LINK</button></div>
        </div>
      })}
    </div></div>

    {Object.values(links).length > 0 && <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
      <div style={{ fontSize: 13, fontWeight: 900 }}>ROTATION PAIRS — BOTH-SIDE MONITORING</div>
      {Object.values(links).map(link => {
        const source = technical(link.sourceSymbol, cardMap, watchMap)
        const destination = technical(link.destinationSymbol, cardMap, watchMap)
        const sourceAnalyst = analystFor(link.sourceSymbol, analyst.data)
        const destAnalyst = analystFor(link.destinationSymbol, analyst.data)
        const sourceLook = lookthroughFor(link.sourceSymbol, lookthrough.data)
        const destLook = lookthroughFor(link.destinationSymbol, lookthrough.data)
        const gates = returnGates(link, source, destination, regime.data, taxRows)
        const pass = gates.filter(item => item.state === 'PASS').length
        const blocked = gates.some(item => item.state === 'BLOCK')
        const unavailable = gates.some(item => item.state === 'UNAVAILABLE')
        const destinationValue = destination.price !== null && link.destinationShares !== null ? destination.price * link.destinationShares : null
        const destinationCostValue = link.destinationCost !== null && link.destinationShares !== null ? link.destinationCost * link.destinationShares : null
        const destinationPnl = destinationValue !== null && destinationCostValue !== null ? destinationValue - destinationCostValue : null
        const sourceMove = source.price !== null && link.sourceExitPrice !== null ? ((source.price - link.sourceExitPrice) / link.sourceExitPrice) * 100 : null
        const destinationMove = destination.price !== null && link.destinationCost !== null ? ((destination.price - link.destinationCost) / link.destinationCost) * 100 : null
        const spread = sourceMove !== null && destinationMove !== null ? sourceMove - destinationMove : null
        const income = dividendRows.filter(row => text(row.symbol, row.ticker).toUpperCase() === link.destinationSymbol && (!link.destinationPurchaseDate || day(row.pay_date ?? row.date) >= link.destinationPurchaseDate)).reduce((sum, row) => sum + Number(finite(row.amount, row.cash_amount, row.net_amount) ?? 0), 0)
        const available = link.amountMoved === null ? destinationValue : destinationValue === null ? link.amountMoved : Math.min(link.amountMoved + income, destinationValue)
        return <div key={link.id} style={{ ...panel, padding: 11, borderColor: link.confirmed ? BB.green : BB.amber }}>
          <div onClick={() => setExpandedLink(expandedLink === link.id ? null : link.id)} style={{ cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><b style={{ fontSize: 16 }}>{link.sourceSymbol} → {link.destinationSymbol}</b><span style={{ color: link.confirmed ? BB.green : BB.amber }}>{link.confirmed ? 'CONFIRMED LINEAGE' : 'SUGGESTION — CONFIRM REQUIRED'}</span><span style={{ color: blocked ? BB.red : unavailable ? BB.text3 : pass === 6 ? BB.green : BB.amber }}>{blocked ? 'BLOCKED' : unavailable ? 'EVIDENCE INCOMPLETE' : `${pass}/6 RETURN GATES`}</span><span style={{ marginLeft: 'auto', color: BB.text3 }}>{expandedLink === link.id ? '▾ collapse' : '▸ intelligence'}</span></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(110px,1fr))', gap: 7, marginTop: 8, fontSize: 10.5 }}><div><span style={{ color: BB.text3 }}>Amount moved</span><br /><b>{dollars(link.amountMoved)}</b></div><div><span style={{ color: BB.text3 }}>Destination value</span><br /><b>{dollars(destinationValue)}</b></div><div><span style={{ color: BB.text3 }}>Destination P&L</span><br /><b style={{ color: destinationPnl === null ? BB.text3 : destinationPnl >= 0 ? BB.green : BB.red }}>{dollars(destinationPnl)}</b></div><div><span style={{ color: BB.text3 }}>Income earned</span><br /><b>{dollars(income)}</b></div><div><span style={{ color: BB.text3 }}>Source vs destination</span><br /><b>{pct(spread)}</b></div><div><span style={{ color: BB.text3 }}>Available to rotate back</span><br /><b>{dollars(available)}</b></div></div>
          {expandedLink === link.id && <div style={{ marginTop: 10 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}><TechnicalCard value={source} analyst={sourceAnalyst} lookthrough={sourceLook} /><TechnicalCard value={destination} analyst={destAnalyst} lookthrough={destLook} /></div>
            <div style={{ ...panel, padding: 10, marginTop: 9 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 7 }}>RETURN-TO-GROWTH COMPOSITE GATE</div>{gates.map(item => <div key={item.label} style={{ display: 'grid', gridTemplateColumns: '86px 245px 180px 180px 1fr', gap: 7, padding: '4px 0', fontSize: 10.5, borderBottom: '1px solid var(--border)' }}><b style={{ color: gateColor(item.state) }}>{item.state}</b><b>{item.label}</b><span>{item.current}</span><span style={{ color: BB.text3 }}>{item.threshold}</span><span style={{ color: BB.text3 }}>{item.why}</span></div>)}<div style={{ display: 'flex', gap: 8, marginTop: 9, alignItems: 'center' }}><button onClick={() => setRotationEvent(allEvents.find(event => Number(event.event_id) === link.sourceEventId) ?? { symbol: link.sourceSymbol, event_id: link.sourceEventId, sold_at: link.sourceExitDate, sell_price: link.sourceExitPrice, proceeds_usd: link.amountMoved, account: link.account })} style={btn(false)}>EDIT ROTATION</button><button onClick={() => void armComposite(link, gates)} disabled={!link.confirmed || gates.some(item => item.state === 'UNAVAILABLE')} style={btn(Boolean(compositeAlerts[link.id]?.armed))}>{compositeAlerts[link.id]?.armed ? 'COMPOSITE MONITOR ARMED' : 'ARM SIX-GATE MONITOR'}</button><span style={{ fontSize: 10, color: BB.text3 }}>Advisory only. One price boolean cannot satisfy this monitor.</span></div></div>
          </div>}
        </div>
      })}
    </div>}

    {selectedEvent && <MandateEventModal symbol={selectedEvent.symbol} event={selectedEvent} mandate={mandates[selectedEvent.symbol] ?? defaultMandate()} classification={classifications[selectedEvent._eventKey] ?? defaultEvent()} onClose={() => setSelectedEvent(null)} onSave={(mandate, classification) => saveMandateAndEvent(selectedEvent, mandate, classification)} />}
    {rotationEvent && <RotationModal sourceEvent={rotationEvent} positions={openPositions} existing={Object.values(links).find(link => link.sourceEventId === Number(rotationEvent.event_id))} onClose={() => setRotationEvent(null)} onSave={saveRotation} />}
  </div>
}
