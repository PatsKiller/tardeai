import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'
import { HelpTip } from './ReEntryHelpGuide'

const EXIT_CACHE_KEY = 'portfolio.reentry.exit-universe.v1'
const MANDATE_KEY = 'portfolio.reentry.mandates.v4'
const EVENT_KEY = 'portfolio.reentry.event-classifications.v1'
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
type ExitRow = {
  event_key: string
  symbol: string
  account?: string | null
  trade_date?: string | null
  trade_time?: string | null
  quantity?: number | null
  price?: number | null
  proceeds_usd?: number | null
  action?: string | null
  description?: string | null
  import_source?: string | null
  matched_event_id?: number | null
  reconciliation?: string | null
}
type Summary = {
  symbol: string
  rows: ExitRow[]
  latest: ExitRow
  shares: number | null
  avgExit: number | null
  proceeds: number
  accounts: string[]
  scalpCount: number
  suppressedCount: number
  monitoredCount: number
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
function money(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function qty(value: number | null): string { return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 4 }) }
function defaultMandate(): Mandate { return { mandate: 'unclassified', flags: Object.fromEntries(FLAGS.map(flag => [flag, false])) as Record<Flag, boolean>, targetAccount: '', targetWeightPct: null, priority: 'NORMAL', thesis: '', updatedAt: '' } }
function defaultEvent(): EventClass { return { eventType: 'other', reason: '', notes: '', updatedAt: '' } }
function defaultDisposition(): Disposition { return { state: 'review', reason: '', updatedAt: '' } }
function rowShares(row: ExitRow): number | null { const value = finite(row.quantity); return value === null ? null : Math.abs(value) }
function rowPrice(row: ExitRow): number | null { const direct = finite(row.price); if (direct !== null) return direct; const shares = rowShares(row); const proceeds = finite(row.proceeds_usd); return shares && proceeds !== null ? Math.abs(proceeds) / shares : null }
function dispositionFor(row: ExitRow, map: Record<string, Disposition>): Disposition { return { ...defaultDisposition(), ...(map[row.event_key] ?? {}) } }
function eventFor(row: ExitRow, map: Record<string, EventClass>): EventClass { return { ...defaultEvent(), ...(map[row.event_key] ?? {}) } }
function isScalp(row: ExitRow, event: EventClass): boolean { return ['day_trade', 'momentum_scalp'].includes(event.eventType) || /\b(day[ -]?trade|intraday|scalp|round trip)\b/i.test(`${row.action ?? ''} ${row.description ?? ''} ${event.reason}`) }
async function savePref(key: string, value: any) { const response = await fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, value }) }); const payload = await response.json().catch(() => ({})); if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'save failed') }
function openRotation(symbol: string) { const url = new URL(window.location.href); url.searchParams.set('symbol', symbol); url.hash = 'rotation-workspace'; window.location.assign(url.toString()) }

function ClassificationModal({ summaries, editRow, mandates, events, dispositions, onClose, onSaved }: { summaries: Summary[]; editRow: ExitRow | null; mandates: Record<string, Mandate>; events: Record<string, EventClass>; dispositions: Record<string, Disposition>; onClose: () => void; onSaved: (mandates: Record<string, Mandate>, events: Record<string, EventClass>, dispositions: Record<string, Disposition>) => void }) {
  const first = summaries[0]
  const seedRow = editRow ?? first?.latest
  const seedMandate = first ? mandates[first.symbol] : null
  const [mandate, setMandate] = useState<Mandate>({ ...defaultMandate(), ...(seedMandate ?? {}), flags: { ...defaultMandate().flags, ...(seedMandate?.flags ?? {}) } })
  const [eventClass, setEventClass] = useState<EventClass>({ ...defaultEvent(), ...(seedRow ? events[seedRow.event_key] : {}) })
  const [disposition, setDisposition] = useState<Disposition>({ ...defaultDisposition(), ...(seedRow ? dispositions[seedRow.event_key] : {}) })
  const [scope, setScope] = useState<'latest' | 'all'>(editRow ? 'latest' : 'all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const targets = editRow ? [editRow] : summaries.flatMap(summary => scope === 'latest' ? [summary.latest] : summary.rows)
  const save = async () => {
    setBusy(true); setError('')
    try {
      const now = new Date().toISOString()
      const nextMandates = { ...mandates }
      const nextEvents = { ...events }
      const nextDispositions = { ...dispositions }
      for (const summary of summaries) nextMandates[summary.symbol] = { ...mandate, updatedAt: now }
      for (const row of targets) { nextEvents[row.event_key] = { ...eventClass, updatedAt: now }; nextDispositions[row.event_key] = { ...disposition, updatedAt: now } }
      await Promise.all([savePref(MANDATE_KEY, nextMandates), savePref(EVENT_KEY, nextEvents), savePref(DISPOSITION_KEY, nextDispositions)])
      onSaved(nextMandates, nextEvents, nextDispositions)
    } catch (value: any) { setError(String(value?.message || value)); setBusy(false) }
  }
  return <div role="dialog" aria-modal="true" onMouseDown={onClose} style={{ position: 'fixed', inset: 0, zIndex: 1500, display: 'grid', placeItems: 'center', padding: 18, background: 'rgba(2,6,23,.86)' }}><div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(1000px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16 }}>
    <div style={{ display: 'flex', gap: 12, alignItems: 'start' }}><div style={{ flex: 1 }}><div style={{ fontSize: 20, fontWeight: 900 }}>{summaries.map(summary => summary.symbol).join(' · ')} — Classification</div><div style={{ fontSize: 10.5, color: BB.text3 }}>Persistent ticker mandate plus the selected exit event classification and queue disposition.</div></div><button onClick={onClose} style={button(false)}>CLOSE</button></div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
      <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>1 · PERSISTENT INVESTMENT CLASSIFICATION</div><label style={{ fontSize: 10, color: BB.text3 }}>PRIMARY MANDATE<select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as Mandate['mandate'] }))} style={{ ...field, marginTop: 4 }}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select></label><div style={{ fontSize: 10, color: BB.text3, marginTop: 10 }}>MULTI-SELECT STRATEGY FLAGS</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 5 }}>{FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 8, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>PRIORITY<select value={mandate.priority} onChange={event => setMandate(value => ({ ...value, priority: event.target.value as Mandate['priority'] }))} style={{ ...field, marginTop: 4 }}><option>HIGH</option><option>NORMAL</option><option>LOW</option></select></label></div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label></div>
      <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>2 · EXIT EVENT + RE-ENTRY QUEUE</div>{!editRow && <label style={{ fontSize: 10, color: BB.text3 }}>APPLY TO<select value={scope} onChange={event => setScope(event.target.value as typeof scope)} style={{ ...field, marginTop: 4 }}><option value="all">ALL EXIT EVENTS FOR SELECTED SYMBOLS</option><option value="latest">LATEST EXIT ONLY</option></select></label>}<div style={{ ...panel, background: 'var(--bg2)', padding: 8, marginTop: 8, fontSize: 10.5 }}>{targets.length} event{targets.length === 1 ? '' : 's'} selected · {qty(targets.reduce((sum, row) => sum + (rowShares(row) ?? 0), 0))} shares · {money(targets.reduce((sum, row) => sum + Math.abs(finite(row.proceeds_usd) ?? 0), 0))} proceeds</div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>EXIT TYPE<select value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as EventClass['eventType'] }))} style={{ ...field, marginTop: 4 }}>{EVENT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>REASON<input value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>NOTES<textarea rows={4} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><div style={{ ...panel, padding: 9, marginTop: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10, fontWeight: 900 }}>QUEUE DISPOSITION</div>{(['monitor', 'review', 'suppressed'] as const).map(state => <label key={state} style={{ display: 'block', marginTop: 6 }}><input type="radio" name="queue-disposition" checked={disposition.state === state} onChange={() => setDisposition(value => ({ ...value, state }))} /> <b style={{ marginLeft: 5, color: state === 'suppressed' ? BB.amber : state === 'monitor' ? BB.green : 'var(--text1)' }}>{state === 'monitor' ? 'SAVE / MONITOR LONG TERM' : state === 'suppressed' ? 'SUPPRESS FROM RE-ENTRY QUEUE' : 'REVIEW LATER'}</b></label>)}<input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Why save, review or suppress?" style={{ ...field, marginTop: 8 }} /></div></div>
    </div>{error && <div style={{ color: BB.red, fontSize: 10.5, marginTop: 9 }}>SAVE FAILED: {error}</div>}<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button onClick={() => void save()} disabled={busy || !summaries.length} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE CLASSIFICATION'}</button></div>
  </div></div>
}

export default function ReEntryExitWorkbench() {
  const cache = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const history = useJson('/api/v2/redeploy/history?days=365', 120_000)
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const [mandates, setMandates] = useState<Record<string, Mandate>>({})
  const [events, setEvents] = useState<Record<string, EventClass>>({})
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({})
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [modalSymbols, setModalSymbols] = useState<string[]>([])
  const [editRow, setEditRow] = useState<ExitRow | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'long_term' | 'active' | 'scalps' | 'suppressed' | 'all'>('long_term')
  const [showAll, setShowAll] = useState(false)
  const [toast, setToast] = useState('')
  useEffect(() => setMandates(prefMap(mandatesPref.data) as Record<string, Mandate>), [mandatesPref.data])
  useEffect(() => setEvents(prefMap(eventsPref.data) as Record<string, EventClass>), [eventsPref.data])
  useEffect(() => setDispositions(prefMap(dispositionsPref.data) as Record<string, Disposition>), [dispositionsPref.data])
  const cachePayload = prefValue(cache.data)
  const cacheRows: ExitRow[] = Array.isArray(cachePayload?.rows) ? cachePayload.rows : []
  const fallbackRows: ExitRow[] = unwrap(history.data)?.rows ?? []
  const allRows = cacheRows.length ? cacheRows : fallbackRows
  const summaries = useMemo(() => {
    const groups = new Map<string, ExitRow[]>()
    for (const row of allRows) { const symbol = String(row.symbol || '').toUpperCase(); if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), { ...row, symbol }]) }
    return [...groups.entries()].map(([symbol, sourceRows]) => {
      const rows = sourceRows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let sharesTotal = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of rows) { const shares = rowShares(row); const price = rowPrice(row); const rowProceeds = finite(row.proceeds_usd); if (shares !== null) { known = true; sharesTotal += shares; if (price !== null) weighted += shares * price } if (rowProceeds !== null) proceeds += Math.abs(rowProceeds) }
      const scalpCount = rows.filter(row => isScalp(row, eventFor(row, events))).length
      const suppressedCount = rows.filter(row => dispositionFor(row, dispositions).state === 'suppressed').length
      const monitoredCount = rows.filter(row => dispositionFor(row, dispositions).state === 'monitor').length
      return { symbol, rows, latest: rows[0], shares: known ? sharesTotal : null, avgExit: sharesTotal > 0 && weighted > 0 ? weighted / sharesTotal : sharesTotal > 0 && proceeds > 0 ? proceeds / sharesTotal : null, proceeds, accounts: [...new Set(rows.map(row => String(row.account || '')).filter(Boolean))], scalpCount, suppressedCount, monitoredCount } satisfies Summary
    }).sort((a, b) => `${b.latest.trade_date ?? ''}T${b.latest.trade_time ?? ''}`.localeCompare(`${a.latest.trade_date ?? ''}T${a.latest.trade_time ?? ''}`))
  }, [allRows, events, dispositions])
  useEffect(() => {
    const handler = (event: Event) => { const symbol = String((event as CustomEvent)?.detail?.symbol || '').toUpperCase(); if (symbol) { setModalSymbols([symbol]); setEditRow(null) } }
    window.addEventListener('reentry:classify-symbol', handler)
    return () => window.removeEventListener('reentry:classify-symbol', handler)
  }, [])
  const filtered = useMemo(() => summaries.filter(summary => {
    if (search.trim() && !`${summary.symbol} ${summary.accounts.join(' ')} ${summary.rows.map(row => `${row.action ?? ''} ${row.description ?? ''}`).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    const allSuppressed = summary.suppressedCount === summary.rows.length
    const activeNonScalp = summary.rows.some(row => dispositionFor(row, dispositions).state !== 'suppressed' && !isScalp(row, eventFor(row, events)))
    if (scope === 'long_term') return activeNonScalp
    if (scope === 'active') return !allSuppressed
    if (scope === 'scalps') return summary.scalpCount > 0
    if (scope === 'suppressed') return summary.suppressedCount > 0
    return true
  }), [summaries, search, scope, events, dispositions])
  const shown = filtered.slice(0, showAll ? filtered.length : 75)
  const selectedSummaries = summaries.filter(summary => selected[summary.symbol])
  const modalSummaries = summaries.filter(summary => modalSymbols.includes(summary.symbol))
  const sourceLabel = cacheRows.length ? 'FULL-FIDELITY BROKER CACHE' : 'REDEPLOY SUMMARY FALLBACK'
  const generated = cachePayload?.generated_at ? String(cachePayload.generated_at).slice(0, 19).replace('T', ' ') : 'not available'
  return <div id="reentry-exit-summary" style={{ ...panel, padding: 10, borderColor: cacheRows.length ? BB.green : BB.amber }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 14, fontWeight: 900, color: cacheRows.length ? BB.green : BB.amber }}>EXIT CLASSIFICATION WORKBENCH <HelpTip text="This table reads the full broker exit cache, including quantity and execution price. CLASSIFY is always attached to the ticker." /></div><div style={{ fontSize: 10, color: BB.text3 }}>{sourceLabel} · generated {generated} · {allRows.length} exit transactions · {summaries.length} symbols</div></div><button onClick={() => { cache.refetch(); history.refetch() }} style={{ ...button(false), marginLeft: 'auto' }}>{cache.loading || history.loading ? 'REFRESHING…' : 'REFRESH EXIT DATA'}</button></div>
    {!cacheRows.length && <div style={{ color: BB.amber, fontSize: 10.5, marginTop: 7 }}>FULL-FIDELITY CACHE IS EMPTY OR UNAVAILABLE. Shares and average exit may remain blank until the Watch evaluator republishes `{EXIT_CACHE_KEY}`. The page is using the thin Redeploy fallback and labels it honestly.</div>}
    {cache.error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>CACHE ERROR: {cache.error}</div>}
    <div style={{ ...panel, padding: 8, marginTop: 8, borderColor: BB.blue, fontSize: 10.5 }}><b style={{ color: BB.blue }}>HOW TO CLASSIFY:</b> click the blue <b>CLASSIFY</b> button directly below a ticker. Choose CORE/SATELLITE/HEDGE, check any combination of Growth, Compounding, Dividend, Swing, Short, Defensive, Hedge or Rotation, then choose whether the exit stays monitored or is suppressed.</div>
    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbols, accounts or descriptions…" style={{ ...field, maxWidth: 360 }} /><select value={scope} onChange={event => setScope(event.target.value as typeof scope)} style={{ ...field, width: 245 }}><option value="long_term">LONG-TERM QUEUE · HIDE SCALPS</option><option value="active">ALL ACTIVE · INCLUDE SCALPS</option><option value="scalps">DAY TRADES / MOMENTUM SCALPS</option><option value="suppressed">SUPPRESSED ITEMS</option><option value="all">ALL EXITS</option></select><button onClick={() => setSelected(Object.fromEntries(shown.map(summary => [summary.symbol, true])))} style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelected({})} style={button(false)}>CLEAR</button>{selectedSummaries.length > 0 && <button onClick={() => { setModalSymbols(selectedSummaries.map(summary => summary.symbol)); setEditRow(null) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>CLASSIFY SELECTED {selectedSummaries.length}</button>}<button onClick={() => setShowAll(value => !value)} style={button(showAll)}>{showAll ? 'SHOW FIRST 75' : `SHOW ALL ${filtered.length}`}</button></div>
    {toast && <div style={{ color: BB.blue, fontSize: 10.5, marginTop: 6 }}>{toast}</div>}
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1270 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 165px 105px 90px 105px 105px 115px 120px 170px 1fr', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol / controls</span><span>Latest exit</span><span>Executions</span><span>Cum shares</span><span>Avg exit</span><span>Total proceeds</span><span>Queue</span><span>Accounts</span><span>Mandate / event</span></div>{shown.map(summary => {
      const mandate = { ...defaultMandate(), ...(mandates[summary.symbol] ?? {}), flags: { ...defaultMandate().flags, ...(mandates[summary.symbol]?.flags ?? {}) } }
      const latestEvent = eventFor(summary.latest, events)
      const queue = summary.suppressedCount === summary.rows.length ? 'SUPPRESSED' : summary.monitoredCount ? 'MONITORING' : 'REVIEW'
      return <div key={summary.symbol}><div style={{ display: 'grid', gridTemplateColumns: '28px 165px 105px 90px 105px 105px 115px 120px 170px 1fr', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5 }}><input type="checkbox" checked={Boolean(selected[summary.symbol])} onChange={event => setSelected(value => ({ ...value, [summary.symbol]: event.target.checked }))} /><div><button onClick={() => setExpanded(value => ({ ...value, [summary.symbol]: !value[summary.symbol] }))} style={{ border: 'none', background: 'transparent', color: 'var(--text0)', cursor: 'pointer', padding: 0, textAlign: 'left' }}><b style={{ fontSize: 14 }}>{summary.symbol}</b> <span style={{ color: BB.text3 }}>{expanded[summary.symbol] ? '▾' : '▸'}</span></button><div style={{ display: 'flex', gap: 5, marginTop: 5, flexWrap: 'wrap' }}><button onClick={() => { setModalSymbols([summary.symbol]); setEditRow(null) }} style={{ ...button(true), padding: '3px 7px' }}>CLASSIFY</button><button onClick={() => openRotation(summary.symbol)} style={{ ...button(false), padding: '3px 7px' }}>ROTATION DESK</button></div></div><div>{summary.latest.trade_date ?? '—'}<br /><span style={{ color: BB.text3 }}>{summary.latest.trade_time ?? ''}</span></div><div><b>{summary.rows.length}</b> exits<br /><span style={{ color: summary.scalpCount ? BB.amber : BB.text3 }}>{summary.scalpCount} scalp/day</span></div><b>{qty(summary.shares)}</b><b>{money(summary.avgExit)}</b><b>{money(summary.proceeds)}</b><div><b style={{ color: queue === 'MONITORING' ? BB.green : queue === 'SUPPRESSED' ? BB.amber : BB.text3 }}>{queue}</b><br /><span style={{ color: BB.text3 }}>{summary.suppressedCount} suppressed · {summary.monitoredCount} saved</span></div><span>{summary.accounts.join(' · ') || '—'}</span><div><b>{mandate.mandate.toUpperCase()}</b> · {FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()).join(' / ') || 'NO FLAGS'}<br /><span style={{ color: BB.text3 }}>latest: {latestEvent.eventType.replace(/_/g, ' ').toUpperCase()} · {latestEvent.reason || 'No reason saved'}</span></div></div>{expanded[summary.symbol] && <div style={{ padding: '6px 8px 10px 40px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)' }}>{summary.rows.map(row => { const eventClass = eventFor(row, events); const disposition = dispositionFor(row, dispositions); return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '100px 130px 90px 95px 110px 110px 1fr 95px', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}><span>{row.trade_date ?? '—'} {row.trade_time ?? ''}</span><span>{row.account ?? '—'}</span><span>{row.action ?? '—'}</span><span>{qty(rowShares(row))} sh</span><span>{money(rowPrice(row))}</span><span>{money(finite(row.proceeds_usd))}</span><div><b>{eventClass.eventType.replace(/_/g, ' ').toUpperCase()}</b> · <span style={{ color: disposition.state === 'monitor' ? BB.green : disposition.state === 'suppressed' ? BB.amber : BB.text3 }}>{disposition.state.toUpperCase()}</span><br /><span style={{ color: BB.text3 }}>{eventClass.reason || row.description || row.import_source || 'No source description'}</span></div><button onClick={() => { setModalSymbols([summary.symbol]); setEditRow(row) }} style={button(false)}>EDIT EXIT</button></div> })}</div>}</div>
    })}</div></div>
    {!shown.length && <div style={{ padding: 14, color: BB.text3 }}>No exits match the current filter.</div>}
    {modalSummaries.length > 0 && <ClassificationModal summaries={modalSummaries} editRow={editRow} mandates={mandates} events={events} dispositions={dispositions} onClose={() => { setModalSymbols([]); setEditRow(null) }} onSaved={(nextMandates, nextEvents, nextDispositions) => { setMandates(nextMandates); setEvents(nextEvents); setDispositions(nextDispositions); setToast(`${modalSummaries.map(summary => summary.symbol).join(' · ')} classification saved`); setModalSymbols([]); setEditRow(null); setSelected({}) }} />}
  </div>
}
