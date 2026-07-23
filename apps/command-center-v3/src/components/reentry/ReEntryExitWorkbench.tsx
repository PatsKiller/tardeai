import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'
import { HelpTip } from './ReEntryHelpGuide'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  EXIT_CACHE_KEY,
  EXIT_TYPES,
  MANDATE_KEY,
  REENTRY_FLAGS,
  SHARED_CONTEXT_KEY,
  classificationLabel,
  classificationState,
  defaultDisposition,
  defaultMandate,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  rowPrice,
  rowShares,
  saveUiPref,
  suggestedNotes,
  text,
  unwrap,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

type Summary = {
  symbol: string
  rows: ExitEvidenceRow[]
  latest: ExitEvidenceRow
  shares: number | null
  avgExit: number | null
  proceeds: number
  accounts: string[]
  scalpCount: number
  suppressedCount: number
  monitoredCount: number
}

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
function money(value: number | null): string { return value === null ? '—' : fmt$(value, 2) }
function qty(value: number | null): string { return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 4 }) }
function isScalp(row: ExitEvidenceRow, event: ReEntryEvent): boolean { return ['day_trade', 'momentum_scalp'].includes(event.eventType) || /\b(day[ -]?trade|intraday|scalp|round trip)\b/i.test(`${row.action ?? ''} ${row.description ?? ''} ${event.reason}`) }
function openRotation(symbol: string) { const url = new URL(window.location.href); url.searchParams.set('symbol', symbol); url.hash = 'rotation-workspace'; window.location.assign(url.toString()) }
function stateTone(state: string): string { return state === 'CLASSIFIED' ? BB.green : state === 'AUTO-TAGGED' ? BB.amber : BB.text3 }

function ClassificationModal({ summaries, editRow, mandates, events, dispositions, sharedMap, onClose, onSaved }: {
  summaries: Summary[]
  editRow: ExitEvidenceRow | null
  mandates: Record<string, ReEntryMandate>
  events: Record<string, ReEntryEvent>
  dispositions: Record<string, ReEntryDisposition>
  sharedMap: Record<string, any>
  onClose: () => void
  onSaved: (mandates: Record<string, ReEntryMandate>, events: Record<string, ReEntryEvent>, dispositions: Record<string, ReEntryDisposition>) => void
}) {
  const first = summaries[0]
  const seedRow = editRow ?? first?.latest
  const seedMandate = first ? normalizedMandate(mandates[first.symbol]) : defaultMandate()
  const inferredEvent = seedRow ? normalizedEvent(seedRow, events[seedRow.event_key]) : { eventType: 'other', reason: '', notes: '', updatedAt: '' } as ReEntryEvent
  const shared = first ? sharedMap[first.symbol] : null
  const [mandate, setMandate] = useState<ReEntryMandate>(seedMandate)
  const [eventClass, setEventClass] = useState<ReEntryEvent>({
    ...inferredEvent,
    notes: inferredEvent.notes || (seedRow ? suggestedNotes(seedRow, shared) : ''),
  })
  const [disposition, setDisposition] = useState<ReEntryDisposition>(seedRow ? normalizedDisposition(dispositions[seedRow.event_key]) : defaultDisposition())
  const [scope, setScope] = useState<'latest' | 'all'>(editRow ? 'latest' : 'all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const targets = editRow ? [editRow] : summaries.flatMap(summary => scope === 'latest' ? [summary.latest] : summary.rows)
  const sourceAnnotations: any[] = Array.isArray(shared?.annotations) ? shared.annotations : []

  const save = async () => {
    setBusy(true); setError('')
    try {
      const now = new Date().toISOString()
      const nextMandates = { ...mandates }
      const nextEvents = { ...events }
      const nextDispositions = { ...dispositions }
      for (const summary of summaries) nextMandates[summary.symbol] = { ...mandate, updatedAt: now }
      for (const row of targets) {
        nextEvents[row.event_key] = { ...eventClass, updatedAt: now }
        nextDispositions[row.event_key] = { ...disposition, updatedAt: now }
      }
      await Promise.all([
        saveUiPref(MANDATE_KEY, nextMandates),
        saveUiPref(EVENT_KEY, nextEvents),
        saveUiPref(DISPOSITION_KEY, nextDispositions),
      ])
      window.dispatchEvent(new CustomEvent('reentry:classification-saved', { detail: { symbols: summaries.map(summary => summary.symbol) } }))
      onSaved(nextMandates, nextEvents, nextDispositions)
    } catch (value: any) {
      setError(String(value?.message || value)); setBusy(false)
    }
  }

  return <div role="dialog" aria-modal="true" onMouseDown={onClose} style={{ position: 'fixed', inset: 0, zIndex: 1500, display: 'grid', placeItems: 'center', padding: 18, background: 'rgba(2,6,23,.86)' }}><div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(1080px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16 }}>
    <div style={{ display: 'flex', gap: 12, alignItems: 'start' }}><div style={{ flex: 1 }}><div style={{ fontSize: 20, fontWeight: 900 }}>{summaries.map(summary => summary.symbol).join(' · ')} — Classification</div><div style={{ fontSize: 10.5, color: BB.text3 }}>Operator-saved fields become green CLASSIFIED. Journal/Watch suggestions remain editable and are never treated as operator confirmation.</div></div><button onClick={onClose} style={button(false)}>CLOSE</button></div>
    {sourceAnnotations.length > 0 && <div style={{ ...panel, padding: 9, marginTop: 10, borderColor: BB.amber, background: BB.amberDim }}><div style={{ fontSize: 10.5, fontWeight: 900, color: BB.amber }}>AUTO-TAGGED STARTING EVIDENCE <HelpTip text="Generated from the broker/journal exit, current Watch packet, sector, earnings/catalyst, technical and resistance caches. Edit before saving." /></div><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>{sourceAnnotations.slice(0, 8).map((item, index) => <span key={`${item.label}-${index}`} title={`${item.detail ?? ''}${item.source ? ` · source ${item.source}` : ''}`} style={{ fontSize: 10, color: BB.amber, border: `1px solid ${BB.amber}66`, borderRadius: 4, padding: '3px 6px', cursor: 'help' }}>{item.label}</span>)}</div></div>}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
      <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>1 · PERSISTENT INVESTMENT CLASSIFICATION <HelpTip text="Shared by every exit for this ticker and visible on Re-Entry, Watch, Rotation and Journal context." /></div><label style={{ fontSize: 10, color: BB.text3 }}>PRIMARY MANDATE<select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as ReEntryMandate['mandate'] }))} style={{ ...field, marginTop: 4 }}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select></label><div style={{ fontSize: 10, color: BB.text3, marginTop: 10 }}>MULTI-SELECT STRATEGY FLAGS <HelpTip text="Independent flags may be combined. For example CORE + GROWTH + DIVIDEND." /></div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 5 }}>{REENTRY_FLAGS.map(flag => <label key={flag} title={`${first?.symbol ?? 'Ticker'}: toggle ${flag} as an independent persistent strategy flag`} style={{ ...panel, padding: 8, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)', cursor: 'pointer' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>PRIORITY<select value={mandate.priority} onChange={event => setMandate(value => ({ ...value, priority: event.target.value as ReEntryMandate['priority'] }))} style={{ ...field, marginTop: 4 }}><option>HIGH</option><option>NORMAL</option><option>LOW</option></select></label></div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label></div>
      <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>2 · EXIT EVENT + RE-ENTRY QUEUE <HelpTip text="The exit event is separate from the ticker mandate. A core holding may have a stopped-out event, partial trim or discretionary sale." /></div>{!editRow && <label style={{ fontSize: 10, color: BB.text3 }}>APPLY TO<select value={scope} onChange={event => setScope(event.target.value as typeof scope)} style={{ ...field, marginTop: 4 }}><option value="all">ALL EXIT EVENTS FOR SELECTED SYMBOLS</option><option value="latest">LATEST EXIT ONLY</option></select></label>}<div style={{ ...panel, background: 'var(--bg2)', padding: 8, marginTop: 8, fontSize: 10.5 }}>{targets.length} event{targets.length === 1 ? '' : 's'} selected · {qty(targets.reduce((sum, row) => sum + (rowShares(row) ?? 0), 0))} shares · {money(targets.reduce((sum, row) => sum + Math.abs(finite(row.proceeds_usd) ?? 0), 0))} proceeds</div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>EXIT TYPE<select value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as ReEntryEvent['eventType'] }))} style={{ ...field, marginTop: 4 }}>{EXIT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>REASON<input value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} placeholder="Prefilled from broker/journal evidence when available" style={{ ...field, marginTop: 4 }} /></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>NOTES<textarea rows={7} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} placeholder="Watch/regime/earnings/resistance evidence appears here as an editable starting point" style={{ ...field, marginTop: 4 }} /></label><div style={{ ...panel, padding: 9, marginTop: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10, fontWeight: 900 }}>QUEUE DISPOSITION <HelpTip text="Monitor keeps it active. Review Later leaves it uncommitted. Suppress hides it from the default queue but never deletes source history." /></div>{(['monitor', 'review', 'suppressed'] as const).map(state => <label key={state} style={{ display: 'block', marginTop: 6, cursor: 'pointer' }}><input type="radio" name="queue-disposition" checked={disposition.state === state} onChange={() => setDisposition(value => ({ ...value, state }))} /> <b style={{ marginLeft: 5, color: state === 'suppressed' ? BB.amber : state === 'monitor' ? BB.green : 'var(--text1)' }}>{state === 'monitor' ? 'SAVE / MONITOR LONG TERM' : state === 'suppressed' ? 'SUPPRESS FROM RE-ENTRY QUEUE' : 'REVIEW LATER'}</b></label>)}<input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Why save, review or suppress?" style={{ ...field, marginTop: 8 }} /></div></div>
    </div>{error && <div style={{ color: BB.red, fontSize: 10.5, marginTop: 9 }}>SAVE FAILED: {error}</div>}<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={onClose} style={button(false)}>CANCEL</button><button onClick={() => void save()} disabled={busy || !summaries.length} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>{busy ? 'SAVING…' : 'SAVE CLASSIFICATION'}</button></div>
  </div></div>
}

export default function ReEntryExitWorkbench() {
  const cache = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const history = useJson('/api/v2/redeploy/history?days=365', 120_000)
  const mandatesPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const sharedPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(SHARED_CONTEXT_KEY)}`, 120_000)
  const [mandates, setMandates] = useState<Record<string, ReEntryMandate>>({})
  const [events, setEvents] = useState<Record<string, ReEntryEvent>>({})
  const [dispositions, setDispositions] = useState<Record<string, ReEntryDisposition>>({})
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [modalSymbols, setModalSymbols] = useState<string[]>([])
  const [editRow, setEditRow] = useState<ExitEvidenceRow | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'long_term' | 'active' | 'scalps' | 'suppressed' | 'all'>('long_term')
  const [showAll, setShowAll] = useState(false)
  const [toast, setToast] = useState('')

  useEffect(() => setMandates(prefMap(mandatesPref.data) as Record<string, ReEntryMandate>), [mandatesPref.data])
  useEffect(() => setEvents(prefMap(eventsPref.data) as Record<string, ReEntryEvent>), [eventsPref.data])
  useEffect(() => setDispositions(prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>), [dispositionsPref.data])

  const cachePayload = prefValue(cache.data)
  const cacheRows: ExitEvidenceRow[] = Array.isArray(cachePayload?.rows) ? cachePayload.rows : []
  const fallbackRows: ExitEvidenceRow[] = unwrap(history.data)?.rows ?? []
  const allRows = cacheRows.length ? cacheRows : fallbackRows
  const sharedMap: Record<string, any> = prefValue(sharedPref.data)?.symbols ?? {}

  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of allRows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), { ...row, symbol }])
    }
    return [...groups.entries()].map(([symbol, sourceRows]) => {
      const rows = sourceRows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let sharesTotal = 0; let weighted = 0; let proceeds = 0; let known = false
      for (const row of rows) {
        const shares = rowShares(row); const price = rowPrice(row); const rowProceeds = finite(row.proceeds_usd)
        if (shares !== null) { known = true; sharesTotal += shares; if (price !== null) weighted += shares * price }
        if (rowProceeds !== null) proceeds += Math.abs(rowProceeds)
      }
      const scalpCount = rows.filter(row => isScalp(row, normalizedEvent(row, events[row.event_key]))).length
      const suppressedCount = rows.filter(row => normalizedDisposition(dispositions[row.event_key]).state === 'suppressed').length
      const monitoredCount = rows.filter(row => normalizedDisposition(dispositions[row.event_key]).state === 'monitor').length
      return { symbol, rows, latest: rows[0], shares: known ? sharesTotal : null, avgExit: sharesTotal > 0 && weighted > 0 ? weighted / sharesTotal : sharesTotal > 0 && proceeds > 0 ? proceeds / sharesTotal : null, proceeds, accounts: [...new Set(rows.map(row => String(row.account || '')).filter(Boolean))], scalpCount, suppressedCount, monitoredCount } satisfies Summary
    }).sort((a, b) => `${b.latest.trade_date ?? ''}T${b.latest.trade_time ?? ''}`.localeCompare(`${a.latest.trade_date ?? ''}T${a.latest.trade_time ?? ''}`))
  }, [allRows, events, dispositions])

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent)?.detail ?? {}
      const symbols = Array.isArray(detail.symbols) ? detail.symbols : detail.symbol ? [detail.symbol] : []
      const normalized = symbols.map((symbol: any) => String(symbol).toUpperCase()).filter(Boolean)
      if (normalized.length) { setModalSymbols(normalized); setEditRow(null) }
    }
    window.addEventListener('reentry:classify-symbol', handler)
    return () => window.removeEventListener('reentry:classify-symbol', handler)
  }, [])

  const filtered = useMemo(() => summaries.filter(summary => {
    if (search.trim() && !`${summary.symbol} ${summary.accounts.join(' ')} ${summary.rows.map(row => `${row.action ?? ''} ${row.description ?? ''}`).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    const allSuppressed = summary.suppressedCount === summary.rows.length
    const activeNonScalp = summary.rows.some(row => normalizedDisposition(dispositions[row.event_key]).state !== 'suppressed' && !isScalp(row, normalizedEvent(row, events[row.event_key])))
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
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 14, fontWeight: 900, color: cacheRows.length ? BB.green : BB.amber }}>EXIT CLASSIFICATION WORKBENCH <HelpTip text="Rows expand on click. Green means operator-classified; amber means auto-tagged from source evidence; gray means no classification evidence." /></div><div style={{ fontSize: 10, color: BB.text3 }}>{sourceLabel} · generated {generated} · {allRows.length} exit transactions · {summaries.length} symbols</div></div><button onClick={() => { cache.refetch(); history.refetch(); sharedPref.refetch() }} style={{ ...button(false), marginLeft: 'auto' }}>{cache.loading || history.loading ? 'REFRESHING…' : 'REFRESH EXIT DATA'}</button></div>
    {!cacheRows.length && <div style={{ color: BB.amber, fontSize: 10.5, marginTop: 7 }}>FULL-FIDELITY CACHE IS EMPTY OR UNAVAILABLE. Shares and average exit may remain blank until the Watch evaluator republishes `{EXIT_CACHE_KEY}`.</div>}
    {cache.error && <div style={{ color: BB.red, fontSize: 10, marginTop: 5 }}>CACHE ERROR: {cache.error}</div>}
    <div style={{ ...panel, padding: 8, marginTop: 8, borderColor: BB.blue, fontSize: 10.5 }}><b style={{ color: BB.blue }}>OPERATING TIP:</b> click any ticker row to expand its broker exits. Check multiple symbols and use <b>CLASSIFY SELECTED</b> for one shared mandate/flag/edit pass.</div>
    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbols, accounts or descriptions…" style={{ ...field, maxWidth: 360 }} /><select value={scope} onChange={event => setScope(event.target.value as typeof scope)} style={{ ...field, width: 245 }}><option value="long_term">LONG-TERM QUEUE · HIDE SCALPS</option><option value="active">ALL ACTIVE · INCLUDE SCALPS</option><option value="scalps">DAY TRADES / MOMENTUM SCALPS</option><option value="suppressed">SUPPRESSED ITEMS</option><option value="all">ALL EXITS</option></select><button onClick={() => setSelected(Object.fromEntries(shown.map(summary => [summary.symbol, true])))} title={`Select all ${shown.length} visible symbols for bulk classification`} style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelected({})} style={button(false)}>CLEAR</button>{selectedSummaries.length > 0 && <button onClick={() => { setModalSymbols(selectedSummaries.map(summary => summary.symbol)); setEditRow(null) }} style={{ ...button(true), color: BB.green, borderColor: BB.green }}>CLASSIFY SELECTED {selectedSummaries.length}</button>}<button onClick={() => setShowAll(value => !value)} style={button(showAll)}>{showAll ? 'SHOW FIRST 75' : `SHOW ALL ${filtered.length}`}</button></div>
    {toast && <div style={{ color: BB.green, fontSize: 10.5, marginTop: 6 }}>{toast}</div>}
    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1320 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 185px 105px 90px 105px 105px 115px 120px 170px 1fr', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol / classification</span><span>Latest exit</span><span>Executions</span><span>Cum shares</span><span>Avg exit</span><span>Total proceeds</span><span>Queue</span><span>Accounts</span><span>Mandate / event</span></div>{shown.map(summary => {
      const mandate = normalizedMandate(mandates[summary.symbol])
      const latestEvent = normalizedEvent(summary.latest, events[summary.latest.event_key])
      const state = classificationState(mandate, summary.rows, events, dispositions, sharedMap[summary.symbol])
      const tone = stateTone(state)
      const queue = summary.suppressedCount === summary.rows.length ? 'SUPPRESSED' : summary.monitoredCount ? 'MONITORING' : 'REVIEW'
      return <div key={summary.symbol}><div onClick={() => setExpanded(value => ({ ...value, [summary.symbol]: !value[summary.symbol] }))} title={`${summary.symbol}: ${classificationLabel(state)}. Click to ${expanded[summary.symbol] ? 'collapse' : 'expand'} ${summary.rows.length} exit records.`} style={{ display: 'grid', gridTemplateColumns: '28px 185px 105px 90px 105px 105px 115px 120px 170px 1fr', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: expanded[summary.symbol] ? BB.blueDim : 'transparent' }}><input type="checkbox" checked={Boolean(selected[summary.symbol])} onClick={event => event.stopPropagation()} onChange={event => setSelected(value => ({ ...value, [summary.symbol]: event.target.checked }))} title={`Select ${summary.symbol} for bulk edit`} /><div><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}><b style={{ fontSize: 14 }}>{summary.symbol}</b><span style={{ color: tone, border: `1px solid ${tone}88`, background: `${tone}18`, borderRadius: 4, padding: '2px 5px', fontSize: 10, fontWeight: 900 }}>{classificationLabel(state)}</span><span style={{ color: BB.text3 }}>{expanded[summary.symbol] ? '▾' : '▸'}</span></div><div style={{ display: 'flex', gap: 5, marginTop: 5, flexWrap: 'wrap' }} onClick={event => event.stopPropagation()}><button onClick={() => { setModalSymbols([summary.symbol]); setEditRow(null) }} title={`${summary.symbol}: open persistent mandate, multi-select flags, exit reason and queue disposition`} style={{ ...button(state === 'CLASSIFIED'), padding: '3px 7px', color: state === 'CLASSIFIED' ? BB.green : state === 'AUTO-TAGGED' ? BB.amber : BB.blue, borderColor: tone }}>{state === 'CLASSIFIED' ? 'EDIT CLASSIFICATION' : 'CLASSIFY'}</button><button onClick={() => openRotation(summary.symbol)} title={`${summary.symbol}: open source-to-destination rotation lineage and return gates`} style={{ ...button(false), padding: '3px 7px' }}>ROTATION DESK</button></div></div><div>{summary.latest.trade_date ?? '—'}<br /><span style={{ color: BB.text3 }}>{summary.latest.trade_time ?? ''}</span></div><div><b>{summary.rows.length}</b> exits<br /><span style={{ color: summary.scalpCount ? BB.amber : BB.text3 }}>{summary.scalpCount} scalp/day</span></div><b>{qty(summary.shares)}</b><b>{money(summary.avgExit)}</b><b>{money(summary.proceeds)}</b><div><b style={{ color: queue === 'MONITORING' ? BB.green : queue === 'SUPPRESSED' ? BB.amber : BB.text3 }}>{queue}</b><br /><span style={{ color: BB.text3 }}>{summary.suppressedCount} suppressed · {summary.monitoredCount} saved</span></div><span>{summary.accounts.join(' · ') || '—'}</span><div><b>{mandate.mandate.toUpperCase()}</b> · {REENTRY_FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()).join(' / ') || 'NO FLAGS'}<br /><span style={{ color: latestEvent.updatedAt ? BB.green : BB.amber }}>{latestEvent.updatedAt ? 'saved' : 'auto'}: {latestEvent.eventType.replace(/_/g, ' ').toUpperCase()}</span><br /><span style={{ color: BB.text3 }}>{latestEvent.reason || 'No reason available'}</span></div></div>
      {expanded[summary.symbol] && <div style={{ padding: '6px 8px 10px 40px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)' }}>{summary.rows.map(row => { const eventClass = normalizedEvent(row, events[row.event_key]); const disposition = normalizedDisposition(dispositions[row.event_key]); return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '100px 130px 90px 95px 110px 110px 1fr 95px', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}><span>{row.trade_date ?? '—'} {row.trade_time ?? ''}</span><span>{row.account ?? '—'}</span><span>{row.action ?? '—'}</span><span>{qty(rowShares(row))} sh</span><span>{money(rowPrice(row))}</span><span>{money(finite(row.proceeds_usd))}</span><div><b style={{ color: eventClass.updatedAt ? BB.green : BB.amber }}>{eventClass.updatedAt ? 'SAVED' : 'AUTO'} · {eventClass.eventType.replace(/_/g, ' ').toUpperCase()}</b> · <span style={{ color: disposition.state === 'monitor' ? BB.green : disposition.state === 'suppressed' ? BB.amber : BB.text3 }}>{disposition.state.toUpperCase()}</span><br /><span style={{ color: BB.text3 }}>{eventClass.reason || row.description || row.import_source || 'No source description'}</span></div><button onClick={() => { setModalSymbols([summary.symbol]); setEditRow(row) }} style={button(false)}>EDIT EXIT</button></div> })}</div>}</div>
    })}</div></div>
    {!shown.length && <div style={{ padding: 14, color: BB.text3 }}>No exits match the current filter.</div>}
    {modalSummaries.length > 0 && <ClassificationModal summaries={modalSummaries} editRow={editRow} mandates={mandates} events={events} dispositions={dispositions} sharedMap={sharedMap} onClose={() => { setModalSymbols([]); setEditRow(null) }} onSaved={(nextMandates, nextEvents, nextDispositions) => { setMandates(nextMandates); setEvents(nextEvents); setDispositions(nextDispositions); setToast(`${modalSummaries.map(summary => summary.symbol).join(' · ')} is now CLASSIFIED`); setModalSymbols([]); setEditRow(null); setSelected({}); sharedPref.refetch() }} />}
  </div>
}
