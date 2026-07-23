import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'
import { HelpTip } from './ReEntryHelpGuide'

const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const EVENT_KEY = 'portfolio.reentry.event-classifications.v1'
const ROTATION_KEY = 'portfolio.reentry.rotation-links.v1'
const DISPOSITION_KEY = 'portfolio.reentry.dispositions.v1'

const FLAGS = ['growth', 'compounding', 'dividend', 'swing', 'short', 'defensive', 'hedge', 'rotation'] as const
const EVENT_TYPES = ['stopped_out', 'discretionary_sale', 'partial_trim', 'rebalance', 'tax_sale', 'rotation', 'day_trade', 'momentum_scalp', 'assignment_expiration', 'not_relevant', 'other'] as const

type Flag = typeof FLAGS[number]
type Mandate = {
  mandate: 'core' | 'satellite' | 'hedge' | 'unclassified'
  flags: Record<Flag, boolean>
  targetAccount: string
  targetWeightPct: number | null
  priority: 'HIGH' | 'NORMAL' | 'LOW'
  thesis: string
  updatedAt: string
}
type EventClass = { eventType: typeof EVENT_TYPES[number]; reason: string; notes: string; updatedAt: string }
type Disposition = { state: 'review' | 'monitor' | 'suppressed'; reason: string; updatedAt: string }
type HistoryRow = {
  event_key: string
  symbol: string
  account?: string
  trade_date?: string
  proceeds_usd?: number
  matched_event_id?: number | null
  event_status?: string | null
  action?: string
  quantity?: number
  price?: number
  description?: string
  import_source?: string
  trade_time?: string
}
type SymbolSummary = {
  symbol: string
  rows: HistoryRow[]
  latest: HistoryRow
  accounts: string[]
  cumulativeShares: number | null
  averageExitPrice: number | null
  totalProceeds: number
  scalpCount: number
  suppressedCount: number
  monitorCount: number
}

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

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
function unwrap(value: any): any {
  let result = value
  for (let index = 0; index < 3 && result?.data && typeof result.data === 'object'; index += 1) result = result.data
  return result ?? {}
}
function finite(...values: any[]): number | null {
  for (const value of values) if (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) return Number(value)
  return null
}
function text(...values: any[]): string {
  for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  return ''
}
function money(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function shares(value: number | null): string { return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 4 }) }
function defaultMandate(): Mandate {
  return { mandate: 'unclassified', flags: Object.fromEntries(FLAGS.map(flag => [flag, false])) as Record<Flag, boolean>, targetAccount: '', targetWeightPct: null, priority: 'NORMAL', thesis: '', updatedAt: '' }
}
function defaultEvent(): EventClass { return { eventType: 'other', reason: '', notes: '', updatedAt: '' } }
function defaultDisposition(): Disposition { return { state: 'review', reason: '', updatedAt: '' } }
function prefMap(data: any): Record<string, any> {
  const value = unwrap(data)?.value
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}
async function savePref(key: string, value: any) {
  const response = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, value }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed')
}
function rowShares(row: HistoryRow): number | null {
  const value = finite(row.quantity)
  return value === null ? null : Math.abs(value)
}
function rowPrice(row: HistoryRow): number | null {
  const direct = finite(row.price)
  if (direct !== null) return direct
  const qty = rowShares(row)
  const proceeds = finite(row.proceeds_usd)
  return qty && proceeds !== null ? Math.abs(proceeds) / qty : null
}
function dispositionFor(row: HistoryRow, dispositions: Record<string, Disposition>): Disposition {
  return { ...defaultDisposition(), ...(dispositions[row.event_key] ?? {}) }
}
function isScalp(row: HistoryRow, eventClass: EventClass): boolean {
  if (eventClass.eventType === 'day_trade' || eventClass.eventType === 'momentum_scalp') return true
  return /\b(day[ -]?trade|intraday|scalp|momentum scalp|round trip)\b/i.test(`${row.action ?? ''} ${row.description ?? ''} ${eventClass.reason ?? ''} ${eventClass.notes ?? ''}`)
}
function modal(title: string, subtitle: string, close: () => void, body: React.ReactNode) {
  return <div role="dialog" aria-modal="true" onMouseDown={close} style={{ position: 'fixed', inset: 0, zIndex: 1300, background: 'rgba(2,6,23,.84)', display: 'grid', placeItems: 'center', padding: 18 }}><div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(980px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16 }}><div style={{ display: 'flex', gap: 12, marginBottom: 12 }}><div style={{ flex: 1 }}><div style={{ fontSize: 19, fontWeight: 900 }}>{title}</div><div style={{ fontSize: 10.5, color: BB.text3 }}>{subtitle}</div></div><button onClick={close} style={button(false)}>CLOSE</button></div>{body}</div></div>
}

function ClassifyModal({ row, initialMandate, initialEvent, initialDisposition, onClose, onSave }: { row: HistoryRow; initialMandate: Mandate; initialEvent: EventClass; initialDisposition: Disposition; onClose: () => void; onSave: (mandate: Mandate, eventClass: EventClass, disposition: Disposition) => Promise<void> }) {
  const [mandate, setMandate] = useState<Mandate>({ ...defaultMandate(), ...initialMandate, flags: { ...defaultMandate().flags, ...(initialMandate?.flags ?? {}) } })
  const [eventClass, setEventClass] = useState<EventClass>({ ...defaultEvent(), ...initialEvent })
  const [disposition, setDisposition] = useState<Disposition>({ ...defaultDisposition(), ...initialDisposition })
  const [busy, setBusy] = useState(false)
  return modal(`${row.symbol} · Mandate, Exit and Queue`, 'Strategy flags are multi-selectable. Suppressing an exit hides it from the long-term queue but preserves the broker record.', onClose,
    <><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      <div style={{ ...panel, padding: 11 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 7 }}>SYMBOL MANDATE <HelpTip text="Persistent investment role for the ticker. It is shared across all exits and Redeploy." /></div><select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as Mandate['mandate'] }))} style={field}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 9 }}>{FLAGS.map(flag => <label key={flag} title="Independent flags may be combined" style={{ ...panel, padding: 7, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label></div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label></div>
      <div style={{ ...panel, padding: 11 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 7 }}>EXIT + QUEUE DECISION <HelpTip text="Classify the specific exit separately from the persistent ticker mandate." /></div><div style={{ fontSize: 10.5, color: BB.text3, marginBottom: 7 }}>{row.trade_date || 'date unavailable'} · {row.account || 'account unavailable'} · {shares(rowShares(row))} shares · {money(rowPrice(row))} average/exit · {money(finite(row.proceeds_usd))}</div><select value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as EventClass['eventType'] }))} style={field}>{EVENT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>REASON<input value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>EVENT NOTES<textarea rows={4} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><div style={{ ...panel, padding: 8, marginTop: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10, fontWeight: 900, marginBottom: 5 }}>RE-ENTRY QUEUE DISPOSITION</div>{(['monitor', 'review', 'suppressed'] as const).map(state => <label key={state} style={{ display: 'block', margin: '4px 0', color: state === 'suppressed' ? BB.amber : 'var(--text1)' }}><input type="radio" name="disposition" checked={disposition.state === state} onChange={() => setDisposition(value => ({ ...value, state }))} /> <b style={{ marginLeft: 5 }}>{state === 'monitor' ? 'SAVE / MONITOR LONG TERM' : state === 'suppressed' ? 'SUPPRESS FROM RE-ENTRY QUEUE' : 'REVIEW LATER'}</b></label>)}<input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Why monitor or suppress this exit?" style={{ ...field, marginTop: 5 }} /></div></div>
    </div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); const now = new Date().toISOString(); void onSave({ ...mandate, updatedAt: now }, { ...eventClass, updatedAt: now }, { ...disposition, updatedAt: now }).finally(() => setBusy(false)) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE'}</button></div></>)
}

function BulkClassifyModal({ summaries, mandates, events, dispositions, onClose, onSave }: { summaries: SymbolSummary[]; mandates: Record<string, Mandate>; events: Record<string, EventClass>; dispositions: Record<string, Disposition>; onClose: () => void; onSave: (nextMandates: Record<string, Mandate>, nextEvents: Record<string, EventClass>, nextDispositions: Record<string, Disposition>) => Promise<void> }) {
  const [applyMandate, setApplyMandate] = useState(true)
  const [applyEvent, setApplyEvent] = useState(true)
  const [mandate, setMandate] = useState<Mandate>(defaultMandate())
  const [eventClass, setEventClass] = useState<EventClass>(defaultEvent())
  const [disposition, setDisposition] = useState<Disposition>({ state: 'monitor', reason: '', updatedAt: '' })
  const [busy, setBusy] = useState(false)
  const eventCount = summaries.reduce((sum, summary) => sum + summary.rows.length, 0)
  return modal(`Bulk classify · ${summaries.length} symbols`, `${eventCount} exit transactions selected. Checked strategy flags are added to each symbol's existing flags.`, onClose,
    <><div style={{ ...panel, padding: 10, borderColor: BB.blue }}><b>{summaries.map(summary => summary.symbol).join(' · ')}</b><div style={{ fontSize: 10, color: BB.text3, marginTop: 3 }}>Use this for groups such as long-term exits, momentum scalps, or exits that should be suppressed together.</div></div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 10 }}>
      <div style={{ ...panel, padding: 11 }}><label style={{ fontSize: 11, fontWeight: 900 }}><input type="checkbox" checked={applyMandate} onChange={event => setApplyMandate(event.target.checked)} /> APPLY SYMBOL MANDATE</label><select disabled={!applyMandate} value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as Mandate['mandate'] }))} style={{ ...field, marginTop: 8 }}>{['core', 'satellite', 'hedge', 'unclassified'].map(value => <option key={value} value={value}>{value.replace(/_/g, ' ').toUpperCase()}</option>)}</select><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>{FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 7, opacity: applyMandate ? 1 : .55, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)' }}><input disabled={!applyMandate} type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> {flag.toUpperCase()}</label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 8 }}><input disabled={!applyMandate} value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} placeholder="Target account (optional)" style={field} /><input disabled={!applyMandate} type="number" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} placeholder="Target weight %" style={field} /></div></div>
      <div style={{ ...panel, padding: 11 }}><label style={{ fontSize: 11, fontWeight: 900 }}><input type="checkbox" checked={applyEvent} onChange={event => setApplyEvent(event.target.checked)} /> APPLY EVENT CLASSIFICATION</label><select disabled={!applyEvent} value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as EventClass['eventType'] }))} style={{ ...field, marginTop: 8 }}>{EVENT_TYPES.map(value => <option key={value} value={value}>{value.replace(/_/g, ' ').toUpperCase()}</option>)}</select><input disabled={!applyEvent} value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} placeholder="Reason applied to selected exits" style={{ ...field, marginTop: 8 }} /><textarea disabled={!applyEvent} rows={4} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} placeholder="Notes" style={{ ...field, marginTop: 8 }} /><div style={{ ...panel, background: 'var(--bg2)', padding: 8, marginTop: 8 }}><div style={{ fontSize: 10, fontWeight: 900 }}>QUEUE DISPOSITION FOR ALL SELECTED EXITS</div><select value={disposition.state} onChange={event => setDisposition(value => ({ ...value, state: event.target.value as Disposition['state'] }))} style={{ ...field, marginTop: 6 }}><option value="monitor">SAVE / MONITOR LONG TERM</option><option value="review">REVIEW LATER</option><option value="suppressed">SUPPRESS FROM RE-ENTRY QUEUE</option></select><input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Disposition reason" style={{ ...field, marginTop: 6 }} /></div></div>
    </div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); const now = new Date().toISOString(); const nextMandates = { ...mandates }; const nextEvents = { ...events }; const nextDispositions = { ...dispositions }; for (const summary of summaries) { if (applyMandate) { const prior = { ...defaultMandate(), ...(nextMandates[summary.symbol] ?? {}), flags: { ...defaultMandate().flags, ...(nextMandates[summary.symbol]?.flags ?? {}) } }; nextMandates[summary.symbol] = { ...prior, mandate: mandate.mandate, targetAccount: mandate.targetAccount || prior.targetAccount, targetWeightPct: mandate.targetWeightPct ?? prior.targetWeightPct, flags: Object.fromEntries(FLAGS.map(flag => [flag, prior.flags[flag] || mandate.flags[flag]])) as Record<Flag, boolean>, updatedAt: now } } for (const row of summary.rows) { if (applyEvent) nextEvents[row.event_key] = { ...eventClass, updatedAt: now }; nextDispositions[row.event_key] = { ...disposition, updatedAt: now } } } void onSave(nextMandates, nextEvents, nextDispositions).finally(() => setBusy(false)) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : `APPLY TO ${summaries.length} SYMBOLS`}</button></div></>)
}

function QuickRotationModal({ row, existing, onClose, onSave }: { row: HistoryRow; existing: any; onClose: () => void; onSave: (value: any) => Promise<void> }) {
  const base = existing ?? { id: `rotation:${row.event_key}`, sourceEventId: row.matched_event_id ?? null, sourceSymbol: row.symbol, destinationSymbol: '', account: row.account ?? '', amountMoved: finite(row.proceeds_usd), sourceShares: rowShares(row), sourceExitDate: row.trade_date ?? '', sourceExitPrice: rowPrice(row), destinationPurchaseDate: '', destinationCost: null, destinationShares: null, reason: 'volatility_reduction', intendedDurationDays: 90, switchType: 'temporary', targetSourceAllocationPct: 100, returnMode: 'staged', tranches: [25, 25, 50], thesis: '', invalidation: '', confirmed: false, suggested: false, rsThresholdPct: 0, taxClear: false, accountClear: true, settlementClear: Boolean(row.matched_event_id), createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() }
  const [value, setValue] = useState<any>(base)
  const [busy, setBusy] = useState(false)
  const total = (value.tranches ?? []).reduce((sum: number, item: number) => sum + Number(item || 0), 0)
  return modal(`${row.symbol} · Rotation Link`, 'The system can prefill evidence, but capital lineage is manual. After confirmation, the six-gate monitor can run automatically; execution remains manual.', onClose,
    <><div style={{ ...panel, padding: 9, marginBottom: 9, borderColor: BB.blue, fontSize: 10.5 }}><b style={{ color: BB.blue }}>TRACKING MODEL:</b> manual source/destination confirmation → automatic 20-minute advisory monitoring → manual rotation-back order.</div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}><label style={{ fontSize: 10, color: BB.text3 }}>SOURCE<input value={value.sourceSymbol} disabled style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TEMPORARY DESTINATION<input value={value.destinationSymbol} onChange={event => setValue((current: any) => ({ ...current, destinationSymbol: event.target.value.toUpperCase() }))} placeholder="SCHD" style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>ACCOUNT<input value={value.account} onChange={event => setValue((current: any) => ({ ...current, account: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>AMOUNT MOVED<input type="number" value={value.amountMoved ?? ''} onChange={event => setValue((current: any) => ({ ...current, amountMoved: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>SOURCE SHARES<input type="number" value={value.sourceShares ?? ''} onChange={event => setValue((current: any) => ({ ...current, sourceShares: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>SOURCE EXIT PRICE<input type="number" step="0.01" value={value.sourceExitPrice ?? ''} onChange={event => setValue((current: any) => ({ ...current, sourceExitPrice: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION PURCHASE DATE<input type="date" value={value.destinationPurchaseDate} onChange={event => setValue((current: any) => ({ ...current, destinationPurchaseDate: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION COST<input type="number" step="0.01" value={value.destinationCost ?? ''} onChange={event => setValue((current: any) => ({ ...current, destinationCost: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION SHARES<input type="number" value={value.destinationShares ?? ''} onChange={event => setValue((current: any) => ({ ...current, destinationShares: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>REASON<select value={value.reason} onChange={event => setValue((current: any) => ({ ...current, reason: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="volatility_reduction">VOLATILITY REDUCTION</option><option value="income">INCOME</option><option value="defensive_posture">DEFENSIVE POSTURE</option><option value="tax">TAX</option><option value="other">OTHER</option></select></label><label style={{ fontSize: 10, color: BB.text3 }}>INTENDED DURATION DAYS<input type="number" value={value.intendedDurationDays ?? ''} onChange={event => setValue((current: any) => ({ ...current, intendedDurationDays: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>SWITCH<select value={value.switchType} onChange={event => setValue((current: any) => ({ ...current, switchType: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="temporary">TEMPORARY</option><option value="permanent">PERMANENT</option></select></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET SOURCE ALLOCATION %<input type="number" value={value.targetSourceAllocationPct ?? ''} onChange={event => setValue((current: any) => ({ ...current, targetSourceAllocationPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>RETURN MODE<select value={value.returnMode} onChange={event => setValue((current: any) => ({ ...current, returnMode: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="full">FULL</option><option value="staged">STAGED</option></select></label></div>{value.returnMode === 'staged' && <div style={{ ...panel, padding: 9, marginTop: 9 }}><b style={{ fontSize: 10.5 }}>RETURN TRANCHES · {total}%</b><div style={{ display: 'flex', gap: 7, marginTop: 5 }}>{(value.tranches ?? []).map((item: number, index: number) => <input key={index} type="number" value={item} onChange={event => setValue((current: any) => ({ ...current, tranches: current.tranches.map((old: number, oldIndex: number) => oldIndex === index ? Number(event.target.value) : old) }))} style={{ ...field, width: 90 }} />)}</div>{total !== 100 && <div style={{ color: BB.red, fontSize: 10 }}>Tranches must total 100%.</div>}</div>}<div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>THESIS<textarea rows={4} value={value.thesis} onChange={event => setValue((current: any) => ({ ...current, thesis: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>INVALIDATION<textarea rows={4} value={value.invalidation} onChange={event => setValue((current: any) => ({ ...current, invalidation: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label></div><div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 9 }}><label><input type="checkbox" checked={value.taxClear} onChange={event => setValue((current: any) => ({ ...current, taxClear: event.target.checked }))} /> Tax/wash clear</label><label><input type="checkbox" checked={value.accountClear} onChange={event => setValue((current: any) => ({ ...current, accountClear: event.target.checked }))} /> Account clear</label><label><input type="checkbox" checked={value.settlementClear} onChange={event => setValue((current: any) => ({ ...current, settlementClear: event.target.checked }))} /> Settlement clear</label><label><input type="checkbox" checked={value.confirmed} onChange={event => setValue((current: any) => ({ ...current, confirmed: event.target.checked }))} /> Confirm capital lineage</label></div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy || !value.destinationSymbol || (value.returnMode === 'staged' && total !== 100)} onClick={() => { setBusy(true); void onSave({ ...value, updatedAt: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE ROTATION LINK'}</button></div></>)
}

export default function AuthoritativeExitUniverse() {
  const history = useJson('/api/v2/redeploy/history?days=365')
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const rotationsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(ROTATION_KEY)}`, 0)
  const dispositionPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const [mandates, setMandates] = useState<Record<string, Mandate>>({})
  const [events, setEvents] = useState<Record<string, EventClass>>({})
  const [rotations, setRotations] = useState<Record<string, any>>({})
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({})
  const [selectedRow, setSelectedRow] = useState<HistoryRow | null>(null)
  const [rotationRow, setRotationRow] = useState<HistoryRow | null>(null)
  const [bulkSymbols, setBulkSymbols] = useState<string[]>([])
  const [selectedSymbols, setSelectedSymbols] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'long_term' | 'active' | 'scalps' | 'suppressed' | 'all'>('long_term')
  const [showAll, setShowAll] = useState(false)
  const [toast, setToast] = useState('')
  useEffect(() => setMandates(prefMap(mandatesPref.data) as Record<string, Mandate>), [mandatesPref.data])
  useEffect(() => setEvents(prefMap(eventsPref.data) as Record<string, EventClass>), [eventsPref.data])
  useEffect(() => setRotations(prefMap(rotationsPref.data)), [rotationsPref.data])
  useEffect(() => setDispositions(prefMap(dispositionPref.data) as Record<string, Disposition>), [dispositionPref.data])
  const allRows: HistoryRow[] = unwrap(history.data)?.rows ?? []
  const summaries = useMemo(() => {
    const groups = new Map<string, HistoryRow[]>()
    for (const row of allRows) groups.set(row.symbol, [...(groups.get(row.symbol) ?? []), row])
    const output: SymbolSummary[] = []
    for (const [symbol, sourceRows] of groups) {
      const rows = sourceRows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let totalShares = 0; let weighted = 0; let totalProceeds = 0; let knownShares = false
      for (const row of rows) { const qty = rowShares(row); const price = rowPrice(row); const proceeds = finite(row.proceeds_usd); if (qty !== null) { knownShares = true; totalShares += qty; if (price !== null) weighted += qty * price } if (proceeds !== null) totalProceeds += Math.abs(proceeds) }
      const scalpCount = rows.filter(row => isScalp(row, { ...defaultEvent(), ...(events[row.event_key] ?? {}) })).length
      const suppressedCount = rows.filter(row => dispositionFor(row, dispositions).state === 'suppressed').length
      const monitorCount = rows.filter(row => dispositionFor(row, dispositions).state === 'monitor').length
      output.push({ symbol, rows, latest: rows[0], accounts: [...new Set(rows.map(row => row.account).filter(Boolean) as string[])], cumulativeShares: knownShares ? totalShares : null, averageExitPrice: totalShares > 0 && weighted > 0 ? weighted / totalShares : totalShares > 0 && totalProceeds > 0 ? totalProceeds / totalShares : null, totalProceeds, scalpCount, suppressedCount, monitorCount })
    }
    return output.sort((a, b) => `${b.latest.trade_date ?? ''}T${b.latest.trade_time ?? ''}`.localeCompare(`${a.latest.trade_date ?? ''}T${a.latest.trade_time ?? ''}`))
  }, [allRows, events, dispositions])
  const filtered = useMemo(() => summaries.filter(summary => {
    if (search.trim() && !`${summary.symbol} ${summary.accounts.join(' ')} ${summary.rows.map(row => `${row.description ?? ''} ${row.action ?? ''}`).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    const allSuppressed = summary.suppressedCount === summary.rows.length
    const hasActiveNonScalp = summary.rows.some(row => dispositionFor(row, dispositions).state !== 'suppressed' && !isScalp(row, { ...defaultEvent(), ...(events[row.event_key] ?? {}) }))
    if (scope === 'long_term') return hasActiveNonScalp
    if (scope === 'active') return !allSuppressed
    if (scope === 'scalps') return summary.scalpCount > 0
    if (scope === 'suppressed') return summary.suppressedCount > 0
    return true
  }), [summaries, search, scope, dispositions, events])
  const displayed = filtered.slice(0, showAll ? filtered.length : 75)
  const selectedList = filtered.filter(summary => selectedSymbols[summary.symbol])
  const bulkList = summaries.filter(summary => bulkSymbols.includes(summary.symbol))
  const counts = unwrap(history.data)?.counts ?? {}
  const saveAll = async (nextMandates: Record<string, Mandate>, nextEvents: Record<string, EventClass>, nextDispositions: Record<string, Disposition>) => {
    await Promise.all([savePref(MANDATE_KEY, nextMandates), savePref(EVENT_KEY, nextEvents), savePref(DISPOSITION_KEY, nextDispositions)])
    setMandates(nextMandates); setEvents(nextEvents); setDispositions(nextDispositions); setToast(`Saved ${bulkList.length || selectedList.length} symbol selections`); setBulkSymbols([]); setSelectedSymbols({})
  }
  return <div style={{ ...panel, padding: 10, borderColor: history.error ? BB.red : BB.green }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 13, fontWeight: 900, color: history.error ? BB.red : BB.green }}>RE-ENTRY EXIT SUMMARY <HelpTip text="Aggregated by symbol from every real-account exit. Expand a row to audit individual broker transactions." /></div><div style={{ fontSize: 10, color: BB.text3 }}>Cumulative shares · share-weighted average exit · total proceeds · multi-select classification · persistent save/suppress controls</div></div><span style={{ marginLeft: 'auto', fontSize: 10.5 }}>transactions <b>{counts.sells_found ?? allRows.length}</b> · symbols <b>{summaries.length}</b> · pending reconciliation <b style={{ color: Number(counts.unmatched || 0) ? BB.amber : BB.green }}>{counts.unmatched ?? '—'}</b></span></div>
    {history.error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>BLOCKING: {history.error}</div>}
    <div style={{ ...panel, padding: 8, marginTop: 8, borderColor: BB.blue, fontSize: 10.5 }}><b style={{ color: BB.blue }}>OPERATING TIP:</b> Default view hides detected/specified day trades and suppressed exits. Use the scope filter to view them, select symbols with checkboxes, then bulk save/monitor or suppress. Suppression never deletes source history.</div>
    <div style={{ display: 'flex', gap: 7, marginTop: 8, flexWrap: 'wrap' }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbols, accounts, actions or descriptions…" style={{ ...field, maxWidth: 360 }} /><select value={scope} onChange={event => setScope(event.target.value as typeof scope)} title="Choose whether to hide or inspect day trades and suppressed exits" style={{ ...field, width: 240 }}><option value="long_term">LONG-TERM QUEUE · HIDE SCALPS</option><option value="active">ALL ACTIVE · INCLUDE SCALPS</option><option value="scalps">DAY TRADES / MOMENTUM SCALPS</option><option value="suppressed">SUPPRESSED ITEMS</option><option value="all">ALL EXITS</option></select><button onClick={() => history.refetch()} title="Reload authoritative real-account exit transactions" style={button(false)}>{history.loading ? 'REFRESHING…' : 'REFRESH'}</button><button onClick={() => setShowAll(value => !value)} title="Toggle row limit" style={button(showAll)}>{showAll ? 'SHOW RECENT 75' : `SHOW ALL ${filtered.length}`}</button><button onClick={() => setSelectedSymbols(Object.fromEntries(displayed.map(summary => [summary.symbol, true])))} title="Select every symbol currently visible after filters" style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelectedSymbols({})} style={button(false)}>CLEAR</button>{selectedList.length > 0 && <button onClick={() => setBulkSymbols(selectedList.map(summary => summary.symbol))} title="Apply one mandate, multi-select flags, event classification and queue disposition to all selected symbols" style={{ ...button(true), color: BB.green, borderColor: BB.green }}>BULK CLASSIFY {selectedList.length}</button>}</div>
    {toast && <div style={{ color: BB.blue, fontSize: 10, marginTop: 5 }}>{toast}</div>}
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1440 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 80px 112px 92px 110px 110px 115px 125px 175px 240px 235px', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol</span><span>Latest exit</span><span>Executions</span><span>Cum shares <HelpTip text="Sum of absolute exit quantities across the selected 12-month window." /></span><span>Avg exit <HelpTip text="Share-weighted average exit price. Falls back to total proceeds divided by cumulative shares when a price is missing." /></span><span>Total proceeds</span><span>Queue</span><span>Accounts</span><span>Mandate / event</span><span>Actions</span></div>{displayed.map(summary => {
      const mandate = { ...defaultMandate(), ...(mandates[summary.symbol] ?? {}), flags: { ...defaultMandate().flags, ...(mandates[summary.symbol]?.flags ?? {}) } }
      const latestClass = { ...defaultEvent(), ...(events[summary.latest.event_key] ?? {}) }
      const rotation = Object.values(rotations).find((item: any) => item.sourceSymbol === summary.symbol) as any
      const queueLabel = summary.suppressedCount === summary.rows.length ? 'SUPPRESSED' : summary.monitorCount ? 'MONITORING' : 'REVIEW'
      const queueColor = queueLabel === 'SUPPRESSED' ? BB.amber : queueLabel === 'MONITORING' ? BB.green : BB.text3
      return <div key={summary.symbol}><div style={{ display: 'grid', gridTemplateColumns: '28px 80px 112px 92px 110px 110px 115px 125px 175px 240px 235px', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}><input type="checkbox" checked={Boolean(selectedSymbols[summary.symbol])} onChange={event => setSelectedSymbols(value => ({ ...value, [summary.symbol]: event.target.checked }))} title={`Select ${summary.symbol} for bulk classification`} /><button onClick={() => setExpanded(value => ({ ...value, [summary.symbol]: !value[summary.symbol] }))} title="Expand individual exit transactions" style={{ border: 'none', background: 'transparent', color: 'var(--text0)', textAlign: 'left', cursor: 'pointer', padding: 0 }}><b style={{ fontSize: 13 }}>{summary.symbol}</b><br /><span style={{ color: BB.text3 }}>{expanded[summary.symbol] ? '▾ hide exits' : '▸ show exits'}</span></button><div>{summary.latest.trade_date || '—'}<br /><span style={{ color: BB.text3 }}>{summary.latest.trade_time || ''}</span></div><div><b>{summary.rows.length}</b> exits<br /><span style={{ color: summary.scalpCount ? BB.amber : BB.text3 }}>{summary.scalpCount} scalp/day</span></div><b>{shares(summary.cumulativeShares)}</b><b>{money(summary.averageExitPrice)}</b><b>{money(summary.totalProceeds)}</b><div><b style={{ color: queueColor }}>{queueLabel}</b><br /><span style={{ color: BB.text3 }}>{summary.suppressedCount} suppressed · {summary.monitorCount} saved</span></div><span>{summary.accounts.join(' · ') || '—'}</span><div><b>{mandate.mandate.toUpperCase()}</b> · {FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()).join(' / ') || 'NO FLAGS'}<br /><span style={{ color: BB.text3 }}>latest: {latestClass.eventType.replace(/_/g, ' ').toUpperCase()}</span>{rotation && <div style={{ color: rotation.confirmed ? BB.green : BB.amber }}>{rotation.confirmed ? 'CONFIRMED' : 'SUGGESTED'} {rotation.sourceSymbol} → {rotation.destinationSymbol}</div>}</div><div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}><button onClick={() => setBulkSymbols([summary.symbol])} title="Open a multi-select mandate/event/disposition modal for this symbol's exits" style={button(false)}>CLASSIFY</button><button onClick={() => setRotationRow(summary.latest)} title="Manually confirm where this exit capital was parked" style={button(Boolean(rotation))}>ROTATION LINK</button></div></div>
      {expanded[summary.symbol] && <div style={{ padding: '6px 8px 10px 36px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)' }}>{summary.rows.map(row => { const eventClass = { ...defaultEvent(), ...(events[row.event_key] ?? {}) }; const disposition = dispositionFor(row, dispositions); return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '105px 115px 100px 105px 115px 115px 1fr 115px', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}><span>{row.trade_date ?? '—'} {row.trade_time ?? ''}</span><span>{row.account ?? '—'}</span><span>{row.action ?? '—'}</span><span>{shares(rowShares(row))} sh</span><span>{money(rowPrice(row))}</span><span>{money(finite(row.proceeds_usd))}</span><div><b>{eventClass.eventType.replace(/_/g, ' ').toUpperCase()}</b> · <span style={{ color: disposition.state === 'suppressed' ? BB.amber : disposition.state === 'monitor' ? BB.green : BB.text3 }}>{disposition.state.toUpperCase()}</span><br /><span style={{ color: BB.text3 }}>{eventClass.reason || row.description || 'No reason saved'}</span></div><button onClick={() => setSelectedRow(row)} style={button(false)}>EDIT EXIT</button></div> })}</div>}
      </div>
    })}</div></div>
    {!history.loading && !displayed.length && <div style={{ padding: 14, color: BB.text3 }}>No exits match the current filter. A source error above is blocking and must not be interpreted as zero exits.</div>}
    {selectedRow && <ClassifyModal row={selectedRow} initialMandate={mandates[selectedRow.symbol] ?? defaultMandate()} initialEvent={events[selectedRow.event_key] ?? defaultEvent()} initialDisposition={dispositions[selectedRow.event_key] ?? defaultDisposition()} onClose={() => setSelectedRow(null)} onSave={async (mandate, eventClass, disposition) => { const nextMandates = { ...mandates, [selectedRow.symbol]: mandate }; const nextEvents = { ...events, [selectedRow.event_key]: eventClass }; const nextDispositions = { ...dispositions, [selectedRow.event_key]: disposition }; await Promise.all([savePref(MANDATE_KEY, nextMandates), savePref(EVENT_KEY, nextEvents), savePref(DISPOSITION_KEY, nextDispositions)]); setMandates(nextMandates); setEvents(nextEvents); setDispositions(nextDispositions); setToast(`${selectedRow.symbol} saved`); setSelectedRow(null) }} />}
    {bulkList.length > 0 && <BulkClassifyModal summaries={bulkList} mandates={mandates} events={events} dispositions={dispositions} onClose={() => setBulkSymbols([])} onSave={saveAll} />}
    {rotationRow && <QuickRotationModal row={rotationRow} existing={Object.values(rotations).find((item: any) => item.sourceEventId === rotationRow.matched_event_id || (!item.sourceEventId && item.sourceSymbol === rotationRow.symbol && item.sourceExitDate === rotationRow.trade_date))} onClose={() => setRotationRow(null)} onSave={async value => { const next = { ...rotations, [value.id]: value }; await savePref(ROTATION_KEY, next); setRotations(next); setToast(`${value.sourceSymbol} → ${value.destinationSymbol} saved`); setRotationRow(null) }} />}
  </div>
}
