import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'

const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const EVENT_KEY = 'portfolio.reentry.event-classifications.v1'
const ROTATION_KEY = 'portfolio.reentry.rotation-links.v1'

const FLAGS = ['growth', 'compounding', 'dividend', 'swing', 'short', 'defensive', 'hedge', 'rotation'] as const
const EVENT_TYPES = ['stopped_out', 'discretionary_sale', 'partial_trim', 'rebalance', 'tax_sale', 'rotation', 'assignment_expiration', 'other'] as const

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
function defaultMandate(): Mandate {
  return { mandate: 'unclassified', flags: Object.fromEntries(FLAGS.map(flag => [flag, false])) as Record<Flag, boolean>, targetAccount: '', targetWeightPct: null, priority: 'NORMAL', thesis: '', updatedAt: '' }
}
function defaultEvent(): EventClass { return { eventType: 'other', reason: '', notes: '', updatedAt: '' } }
function prefMap(data: any): Record<string, any> {
  const value = unwrap(data)?.value
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}
async function savePref(key: string, value: any) {
  const response = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, value }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed')
}
function modal(title: string, subtitle: string, close: () => void, body: React.ReactNode) {
  return <div role="dialog" aria-modal="true" onMouseDown={close} style={{ position: 'fixed', inset: 0, zIndex: 1300, background: 'rgba(2,6,23,.84)', display: 'grid', placeItems: 'center', padding: 18 }}><div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(900px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16 }}><div style={{ display: 'flex', gap: 12, marginBottom: 12 }}><div style={{ flex: 1 }}><div style={{ fontSize: 19, fontWeight: 900 }}>{title}</div><div style={{ fontSize: 10.5, color: BB.text3 }}>{subtitle}</div></div><button onClick={close} style={button(false)}>CLOSE</button></div>{body}</div></div>
}

function ClassifyModal({ row, initialMandate, initialEvent, onClose, onSave }: { row: HistoryRow; initialMandate: Mandate; initialEvent: EventClass; onClose: () => void; onSave: (mandate: Mandate, eventClass: EventClass) => Promise<void> }) {
  const [mandate, setMandate] = useState<Mandate>({ ...defaultMandate(), ...initialMandate, flags: { ...defaultMandate().flags, ...(initialMandate?.flags ?? {}) } })
  const [eventClass, setEventClass] = useState<EventClass>({ ...defaultEvent(), ...initialEvent })
  const [busy, setBusy] = useState(false)
  return modal(`${row.symbol} · Mandate and Exit`, 'This same persistent classification is shared with Redeploy and the rotation workstation.', onClose,
    <><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      <div style={{ ...panel, padding: 11 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 7 }}>SYMBOL MANDATE</div><select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as Mandate['mandate'] }))} style={field}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 9 }}>{FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 7, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label></div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label></div>
      <div style={{ ...panel, padding: 11 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 7 }}>EVENT CLASSIFICATION</div><div style={{ fontSize: 10.5, color: BB.text3, marginBottom: 7 }}>{row.trade_date || 'date unavailable'} · {row.account || 'account unavailable'} · {money(finite(row.proceeds_usd))}</div><select value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as EventClass['eventType'] }))} style={field}>{EVENT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>REASON<input value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>EVENT NOTES<textarea rows={8} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label></div>
    </div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy} onClick={() => { setBusy(true); void onSave({ ...mandate, updatedAt: new Date().toISOString() }, { ...eventClass, updatedAt: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE'}</button></div></>)
}

function QuickRotationModal({ row, existing, onClose, onSave }: { row: HistoryRow; existing: any; onClose: () => void; onSave: (value: any) => Promise<void> }) {
  const base = existing ?? { id: `rotation:${row.event_key}`, sourceEventId: row.matched_event_id ?? null, sourceSymbol: row.symbol, destinationSymbol: '', account: row.account ?? '', amountMoved: finite(row.proceeds_usd), sourceShares: finite(row.quantity), sourceExitDate: row.trade_date ?? '', sourceExitPrice: finite(row.price), destinationPurchaseDate: '', destinationCost: null, destinationShares: null, reason: 'volatility_reduction', intendedDurationDays: 90, switchType: 'temporary', targetSourceAllocationPct: 100, returnMode: 'staged', tranches: [25, 25, 50], thesis: '', invalidation: '', confirmed: false, suggested: false, rsThresholdPct: 0, taxClear: false, accountClear: true, settlementClear: Boolean(row.matched_event_id), createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() }
  const [value, setValue] = useState<any>(base)
  const [busy, setBusy] = useState(false)
  const total = (value.tranches ?? []).reduce((sum: number, item: number) => sum + Number(item || 0), 0)
  return modal(`${row.symbol} · Rotation Link`, 'Link the exact capital destination. Nothing is confirmed automatically.', onClose,
    <><div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}><label style={{ fontSize: 10, color: BB.text3 }}>SOURCE<input value={value.sourceSymbol} disabled style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TEMPORARY DESTINATION<input value={value.destinationSymbol} onChange={event => setValue((current: any) => ({ ...current, destinationSymbol: event.target.value.toUpperCase() }))} placeholder="SCHD" style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>ACCOUNT<input value={value.account} onChange={event => setValue((current: any) => ({ ...current, account: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>AMOUNT MOVED<input type="number" value={value.amountMoved ?? ''} onChange={event => setValue((current: any) => ({ ...current, amountMoved: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION PURCHASE DATE<input type="date" value={value.destinationPurchaseDate} onChange={event => setValue((current: any) => ({ ...current, destinationPurchaseDate: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION COST<input type="number" step="0.01" value={value.destinationCost ?? ''} onChange={event => setValue((current: any) => ({ ...current, destinationCost: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>DESTINATION SHARES<input type="number" value={value.destinationShares ?? ''} onChange={event => setValue((current: any) => ({ ...current, destinationShares: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>REASON<select value={value.reason} onChange={event => setValue((current: any) => ({ ...current, reason: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="volatility_reduction">VOLATILITY REDUCTION</option><option value="income">INCOME</option><option value="defensive_posture">DEFENSIVE POSTURE</option><option value="tax">TAX</option><option value="other">OTHER</option></select></label><label style={{ fontSize: 10, color: BB.text3 }}>INTENDED DURATION DAYS<input type="number" value={value.intendedDurationDays ?? ''} onChange={event => setValue((current: any) => ({ ...current, intendedDurationDays: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>SWITCH<select value={value.switchType} onChange={event => setValue((current: any) => ({ ...current, switchType: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="temporary">TEMPORARY</option><option value="permanent">PERMANENT</option></select></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET SOURCE ALLOCATION %<input type="number" value={value.targetSourceAllocationPct ?? ''} onChange={event => setValue((current: any) => ({ ...current, targetSourceAllocationPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>RETURN MODE<select value={value.returnMode} onChange={event => setValue((current: any) => ({ ...current, returnMode: event.target.value }))} style={{ ...field, marginTop: 3 }}><option value="full">FULL</option><option value="staged">STAGED</option></select></label></div>{value.returnMode === 'staged' && <div style={{ ...panel, padding: 9, marginTop: 9 }}><b style={{ fontSize: 10.5 }}>RETURN TRANCHES · {total}%</b><div style={{ display: 'flex', gap: 7, marginTop: 5 }}>{(value.tranches ?? []).map((item: number, index: number) => <input key={index} type="number" value={item} onChange={event => setValue((current: any) => ({ ...current, tranches: current.tranches.map((old: number, oldIndex: number) => oldIndex === index ? Number(event.target.value) : old) }))} style={{ ...field, width: 90 }} />)}</div>{total !== 100 && <div style={{ color: BB.red, fontSize: 10 }}>Tranches must total 100%.</div>}</div>}<div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>THESIS<textarea rows={4} value={value.thesis} onChange={event => setValue((current: any) => ({ ...current, thesis: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>INVALIDATION<textarea rows={4} value={value.invalidation} onChange={event => setValue((current: any) => ({ ...current, invalidation: event.target.value }))} style={{ ...field, marginTop: 3 }} /></label></div><div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 9 }}><label><input type="checkbox" checked={value.taxClear} onChange={event => setValue((current: any) => ({ ...current, taxClear: event.target.checked }))} /> Tax/wash clear</label><label><input type="checkbox" checked={value.accountClear} onChange={event => setValue((current: any) => ({ ...current, accountClear: event.target.checked }))} /> Account clear</label><label><input type="checkbox" checked={value.settlementClear} onChange={event => setValue((current: any) => ({ ...current, settlementClear: event.target.checked }))} /> Settlement clear</label><label><input type="checkbox" checked={value.confirmed} onChange={event => setValue((current: any) => ({ ...current, confirmed: event.target.checked }))} /> Confirm capital lineage</label></div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button disabled={busy || !value.destinationSymbol || (value.returnMode === 'staged' && total !== 100)} onClick={() => { setBusy(true); void onSave({ ...value, updatedAt: new Date().toISOString() }).finally(() => setBusy(false)) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE ROTATION LINK'}</button></div></>)
}

export default function AuthoritativeExitUniverse() {
  const history = useJson('/api/v2/redeploy/history?days=365')
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const rotationsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(ROTATION_KEY)}`, 0)
  const [mandates, setMandates] = useState<Record<string, Mandate>>({})
  const [events, setEvents] = useState<Record<string, EventClass>>({})
  const [rotations, setRotations] = useState<Record<string, any>>({})
  const [selected, setSelected] = useState<HistoryRow | null>(null)
  const [rotationRow, setRotationRow] = useState<HistoryRow | null>(null)
  const [search, setSearch] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [toast, setToast] = useState('')
  useEffect(() => setMandates(prefMap(mandatesPref.data) as Record<string, Mandate>), [mandatesPref.data])
  useEffect(() => setEvents(prefMap(eventsPref.data) as Record<string, EventClass>), [eventsPref.data])
  useEffect(() => setRotations(prefMap(rotationsPref.data)), [rotationsPref.data])
  const allRows: HistoryRow[] = unwrap(history.data)?.rows ?? []
  const displayed = useMemo(() => allRows.filter(row => !search.trim() || `${row.symbol} ${row.account} ${row.description} ${row.action}`.toUpperCase().includes(search.trim().toUpperCase())).slice(0, showAll ? 2000 : 75), [allRows, search, showAll])
  const counts = unwrap(history.data)?.counts ?? {}
  return <div style={{ ...panel, padding: 10, borderColor: history.error ? BB.red : BB.green }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 13, fontWeight: 900, color: history.error ? BB.red : BB.green }}>AUTHORITATIVE REAL-ACCOUNT EXIT UNIVERSE</div><div style={{ fontSize: 10, color: BB.text3 }}>Every real-account exposure-reducing transaction · no $500 minimum · same-day and unreconciled rows included</div></div><span style={{ marginLeft: 'auto', fontSize: 10.5 }}>found <b>{counts.sells_found ?? allRows.length}</b> · matched <b>{counts.matched ?? '—'}</b> · pending reconciliation <b style={{ color: Number(counts.unmatched || 0) ? BB.amber : BB.green }}>{counts.unmatched ?? '—'}</b></span></div>
    {history.error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>BLOCKING: {history.error}</div>}
    <div style={{ display: 'flex', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search all exits…" style={{ ...field, maxWidth: 320 }} /><button onClick={() => history.refetch()} style={button(false)}>{history.loading ? 'REFRESHING…' : 'REFRESH'}</button><button onClick={() => setShowAll(value => !value)} style={button(showAll)}>{showAll ? 'SHOW RECENT 75' : `SHOW ALL ${allRows.length}`}</button></div>
    {toast && <div style={{ color: BB.blue, fontSize: 10, marginTop: 5 }}>{toast}</div>}
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1160 }}><div style={{ display: 'grid', gridTemplateColumns: '92px 70px 135px 100px 100px 110px 210px 250px', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Date/time</span><span>Symbol</span><span>Account</span><span>Exit price</span><span>Proceeds</span><span>Reconciliation</span><span>Mandate / event</span><span>Actions</span></div>{displayed.map(row => {
      const mandate = { ...defaultMandate(), ...(mandates[row.symbol] ?? {}), flags: { ...defaultMandate().flags, ...(mandates[row.symbol]?.flags ?? {}) } }
      const eventClass = { ...defaultEvent(), ...(events[row.event_key] ?? {}) }
      const rotation = Object.values(rotations).find((item: any) => item.sourceEventId === row.matched_event_id || (!item.sourceEventId && item.sourceSymbol === row.symbol && item.sourceExitDate === row.trade_date)) as any
      return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '92px 70px 135px 100px 100px 110px 210px 250px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}><div>{row.trade_date || '—'}<br /><span style={{ color: BB.text3 }}>{row.trade_time || ''}</span></div><b style={{ fontSize: 12 }}>{row.symbol}</b><span>{row.account || '—'}</span><span>{money(finite(row.price, finite(row.proceeds_usd) && finite(row.quantity) ? Number(row.proceeds_usd) / Math.abs(Number(row.quantity)) : null))}</span><b>{money(finite(row.proceeds_usd))}</b><span style={{ color: row.matched_event_id ? BB.green : BB.amber }}>{row.matched_event_id ? `MATCHED #${row.matched_event_id}` : 'PENDING'}</span><div><b>{mandate.mandate.toUpperCase()}</b> · {FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()).join(' / ') || 'NO FLAGS'}<br /><span style={{ color: BB.text3 }}>{eventClass.eventType.replace(/_/g, ' ').toUpperCase()} · {eventClass.reason || row.description || row.action || 'unclassified'}</span>{rotation && <div style={{ color: rotation.confirmed ? BB.green : BB.amber }}>{rotation.confirmed ? 'CONFIRMED' : 'SUGGESTED'} {rotation.sourceSymbol} → {rotation.destinationSymbol}</div>}</div><div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}><button onClick={() => setSelected(row)} style={button(false)}>MANDATE + EXIT</button><button onClick={() => setRotationRow(row)} style={button(Boolean(rotation))}>ROTATION LINK</button></div></div>
    })}</div></div>
    {!history.loading && !displayed.length && <div style={{ padding: 14, color: BB.text3 }}>No exits match the current filter. A source error above is blocking and must not be interpreted as zero exits.</div>}
    {selected && <ClassifyModal row={selected} initialMandate={mandates[selected.symbol] ?? defaultMandate()} initialEvent={events[selected.event_key] ?? defaultEvent()} onClose={() => setSelected(null)} onSave={async (mandate, eventClass) => { const nextMandates = { ...mandates, [selected.symbol]: mandate }; const nextEvents = { ...events, [selected.event_key]: eventClass }; await Promise.all([savePref(MANDATE_KEY, nextMandates), savePref(EVENT_KEY, nextEvents)]); setMandates(nextMandates); setEvents(nextEvents); setToast(`${selected.symbol} saved`); setSelected(null) }} />}
    {rotationRow && <QuickRotationModal row={rotationRow} existing={Object.values(rotations).find((item: any) => item.sourceEventId === rotationRow.matched_event_id || (!item.sourceEventId && item.sourceSymbol === rotationRow.symbol && item.sourceExitDate === rotationRow.trade_date))} onClose={() => setRotationRow(null)} onSave={async value => { const next = { ...rotations, [value.id]: value }; await savePref(ROTATION_KEY, next); setRotations(next); setToast(`${value.sourceSymbol} → ${value.destinationSymbol} saved`); setRotationRow(null) }} />}
  </div>
}
