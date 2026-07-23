import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useLocation } from 'react-router-dom'
import { BB } from '../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  EXIT_CACHE_KEY,
  MANDATE_KEY,
  SHARED_CONTEXT_KEY,
  classificationLabel,
  classificationState,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  rowPrice,
  rowShares,
  type ExitEvidenceRow,
} from '../lib/reentrySharedContext'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6 }

function useJson(url: string, refreshMs = 120_000) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let dead = false
    const controller = new AbortController()
    fetch(url, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || String(response.status))
        if (!dead) setData(payload?.data && typeof payload.data === 'object' ? payload.data : payload)
      })
      .catch(value => { if (!dead && value?.name !== 'AbortError') setError(String(value?.message || value)) })
    const timer = refreshMs > 0 ? window.setTimeout(() => setTick(value => value + 1), refreshMs) : 0
    return () => { dead = true; controller.abort(); if (timer) window.clearTimeout(timer) }
  }, [url, tick, refreshMs])
  return { data, error, refetch: () => setTick(value => value + 1) }
}
function money(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function tone(state: string): string { return state === 'CLASSIFIED' ? BB.green : state === 'AUTO-TAGGED' ? BB.amber : BB.text3 }

export default function SharedIntelligenceBridge() {
  const location = useLocation()
  const showWatch = location.pathname === '/watch' || location.pathname.startsWith('/watch/')
  const showJournal = location.pathname === '/journal' || location.pathname.startsWith('/journal/')
  const show = showWatch || showJournal
  const exitPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`, 120_000)
  const mandatePref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const sharedPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(SHARED_CONTEXT_KEY)}`, 120_000)
  const [expanded, setExpanded] = useState(false)
  const [query, setQuery] = useState('')

  useEffect(() => {
    const handler = () => { mandatePref.refetch(); eventPref.refetch(); dispositionPref.refetch(); sharedPref.refetch() }
    window.addEventListener('reentry:classification-saved', handler)
    return () => window.removeEventListener('reentry:classification-saved', handler)
  }, [])

  const rows: ExitEvidenceRow[] = prefValue(exitPref.data)?.rows ?? []
  const mandates = prefMap(mandatePref.data)
  const events = prefMap(eventPref.data)
  const dispositions = prefMap(dispositionPref.data)
  const shared = prefValue(sharedPref.data)?.symbols ?? {}

  const symbols = useMemo(() => {
    const grouped = new Map<string, ExitEvidenceRow[]>()
    for (const row of rows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (symbol) grouped.set(symbol, [...(grouped.get(symbol) ?? []), row])
    }
    return [...grouped.entries()].map(([symbol, exits]) => {
      const sorted = exits.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      const mandate = normalizedMandate(mandates[symbol])
      const state = classificationState(mandate, sorted, events, dispositions, shared[symbol])
      const latest = sorted[0]
      const event = normalizedEvent(latest, events[latest.event_key])
      const shares = sorted.reduce((sum, row) => sum + (rowShares(row) ?? 0), 0)
      const weighted = sorted.reduce((sum, row) => sum + (rowShares(row) ?? 0) * (rowPrice(row) ?? 0), 0)
      const avgExit = shares > 0 && weighted > 0 ? weighted / shares : null
      return { symbol, exits: sorted, latest, mandate, state, event, shares, avgExit, context: shared[symbol] ?? null }
    }).filter(row => !query.trim() || `${row.symbol} ${row.event.eventType} ${row.event.reason} ${row.context?.journal_annotation ?? ''}`.toUpperCase().includes(query.trim().toUpperCase())).sort((a, b) => String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || '')))
  }, [rows, mandatePref.data, eventPref.data, dispositionPref.data, sharedPref.data, query])

  if (!show || !rows.length) return null
  const classified = symbols.filter(row => row.state === 'CLASSIFIED').length
  const stopped = symbols.filter(row => row.event.eventType === 'stopped_out').length
  const resistanceMissing = symbols.filter(row => !row.context?.resistance || row.context.resistance.state === 'UNAVAILABLE').length
  const title = showJournal ? 'RE-ENTRY / WATCH JOURNAL ANNOTATIONS' : 'RE-ENTRY CONTEXT ON WATCH'
  const subtitle = showJournal
    ? 'Automatic broker-exit, Watch, regime, catalyst, earnings and resistance context shared with Re-Entry. Operator classifications remain editable in Re-Entry.'
    : 'Closed-position classification, exit reason and rotation/resistance context carried into Watch. Watch mechanics remain the current technical source.'

  return <div style={{ ...panel, padding: 9, marginBottom: 10, borderColor: BB.blue }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><div style={{ fontSize: 11.5, fontWeight: 900, color: BB.blue }}>{title}</div><div style={{ fontSize: 9.5, color: BB.text3 }}>{subtitle}</div></div><div style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}><button onClick={() => setExpanded(value => !value)} title="Expand the shared symbol annotations" style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 8px', borderRadius: 4, border: `1px solid ${BB.blue}`, background: expanded ? BB.blueDim : 'var(--bg2)', color: BB.blue, cursor: 'pointer' }}>{expanded ? 'HIDE CONTEXT' : 'SHOW CONTEXT'}</button><button onClick={() => window.location.assign('/v3/portfolio/re-entry')} title="Open the full Re-Entry classification and rotation workstation" style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>OPEN RE-ENTRY</button></div></div>
    <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 9.5 }}><span title="Operator-saved mandate, event or queue data" style={{ color: BB.green }}>{classified} classified</span><span title="Latest event inferred or saved as stopped out" style={{ color: BB.red }}>{stopped} stopped out</span><span title="No closed-session or Watch fallback resistance evidence" style={{ color: resistanceMissing ? BB.amber : BB.green }}>{resistanceMissing} resistance missing</span><span style={{ color: BB.text3 }}>shared cache {prefValue(sharedPref.data)?.generated_at ? String(prefValue(sharedPref.data).generated_at).slice(0, 16).replace('T', ' ') : 'not refreshed'}</span></div>
    {expanded && <><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter shared symbols or annotations…" style={{ width: '100%', boxSizing: 'border-box', marginTop: 7, fontSize: 10, padding: '5px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} /><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 6, marginTop: 7 }}>{symbols.slice(0, 24).map(row => { const color = tone(row.state); const resistance = row.context?.resistance; return <div key={row.symbol} title={row.context?.journal_annotation ?? row.event.reason} style={{ ...panel, padding: 7, background: 'var(--bg2)', borderColor: color }}><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}><b>{row.symbol}</b><span style={{ color, border: `1px solid ${color}88`, borderRadius: 3, padding: '1px 4px', fontSize: 8.5, fontWeight: 900 }}>{classificationLabel(row.state)}</span><span style={{ marginLeft: 'auto', fontSize: 9, color: row.event.eventType === 'stopped_out' ? BB.red : BB.amber }}>{row.event.eventType.replace(/_/g, ' ').toUpperCase()}</span></div><div style={{ fontSize: 9.5, color: BB.text3, marginTop: 3 }}>{row.latest.trade_date ?? 'date unavailable'} · {row.latest.account ?? 'account unavailable'} · {row.shares ? `${row.shares.toLocaleString()} sh` : 'shares unavailable'} · avg {money(row.avgExit)}</div><div style={{ fontSize: 9.5, marginTop: 3 }}>{row.event.reason}</div><div style={{ fontSize: 9, color: resistance?.state === 'UNAVAILABLE' ? BB.amber : BB.text3, marginTop: 3 }}>resistance {resistance?.state ?? 'UNAVAILABLE'} {resistance?.resistance == null ? '' : `at ${money(Number(resistance.resistance))}`} · Watch {row.context?.watch?.recommendation ?? 'unavailable'}</div></div> })}</div></>}
    {(exitPref.error || sharedPref.error) && <div style={{ color: BB.red, fontSize: 9, marginTop: 5 }}>{[exitPref.error, sharedPref.error].filter(Boolean).join(' · ')}</div>}
  </div>
}
