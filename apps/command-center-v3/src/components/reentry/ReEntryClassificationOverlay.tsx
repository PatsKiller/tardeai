import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  EXIT_CACHE_KEY,
  EXIT_TYPES,
  MANDATE_KEY,
  REENTRY_FLAGS,
  defaultDisposition,
  defaultMandate,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  prefValue,
  saveUiPref,
  text,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6 }
const field: CSSProperties = { width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '7px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const btn = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '6px 10px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

function useJson(url: string) {
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
    return () => { dead = true; controller.abort() }
  }, [url, tick])
  return { data, error, refetch: () => setTick(value => value + 1) }
}

function tickerLike(symbol: string): boolean {
  return /^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol)
}

function num(...values: any[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function dig(value: any, path: string): any {
  return path.split('.').reduce((current: any, key) => current?.[key], value)
}

function valuation(watch: any): { pe: number | null; forwardPe: number | null; peg: number | null; source: string; asOf: string } {
  const objects = [
    watch,
    watch?.fundamentals,
    watch?.decision_packet?.fundamentals,
    watch?.decision_packet?.current_input_snapshot?.fundamentals,
    watch?.decision_packet?.blind_facts?.fundamentals,
  ]
  const first = (paths: string[]) => {
    for (const object of objects) for (const path of paths) {
      const value = num(dig(object, path))
      if (value !== null) return value
    }
    return null
  }
  const pe = first(['pe', 'trailing_pe', 'trailingPe', 'valuation.pe'])
  const forwardPe = first(['forward_pe', 'forwardPe', 'fwd_pe', 'valuation.forward_pe'])
  const peg = first(['peg', 'peg_ratio', 'valuation.peg'])
  const asOf = text(
    watch?.fundamentals_as_of,
    watch?.decision_packet?.fundamentals?.fundamentals_as_of,
    watch?.decision_packet?.current_input_snapshot?.fundamentals?.fundamentals_as_of,
    watch?.last_enriched_at,
  )
  return { pe, forwardPe, peg, source: pe !== null || forwardPe !== null || peg !== null ? 'FINVIZ ENRICHMENT / BLIND FACTS' : 'NO VALUATION SOURCE', asOf }
}

function watchAnnotations(symbol: string, watch: any): string[] {
  if (!watch) return [`${symbol}: Watch context unavailable; refresh Watch inputs before relying on an empty field.`]
  const packet = watch.decision_packet ?? {}
  const lines = [
    text(watch.profile_sector, watch.sector) ? `Sector — ${text(watch.profile_sector, watch.sector)}` : '',
    text(watch.synthesis_recommendation, watch.latest_recommendation) ? `Watch recommendation — ${text(watch.synthesis_recommendation, watch.latest_recommendation).replace(/_/g, ' ')}` : '',
    text(watch.market_regime, watch.risk_regime, packet?.context?.regime) ? `Regime — ${text(watch.market_regime, watch.risk_regime, packet?.context?.regime).replace(/_/g, ' ')}` : '',
    text(watch.catalyst_headline) ? `Catalyst — ${text(watch.catalyst_headline)}` : '',
    text(watch.earnings_date, watch.next_earnings_date) ? `Earnings — ${text(watch.earnings_date, watch.next_earnings_date)}` : '',
    num(watch.rsi, watch.rsi_14) !== null ? `RSI — ${num(watch.rsi, watch.rsi_14)?.toFixed(1)}` : '',
  ].filter(Boolean)
  return lines.length ? lines : [`${symbol}: no current Watch annotations were present in the API response.`]
}

export default function ReEntryClassificationOverlay() {
  const exitPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EXIT_CACHE_KEY)}`)
  const mandatePref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`)
  const eventPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`)
  const dispositionPref = useJson(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`)
  const [symbols, setSymbols] = useState<string[]>([])
  const [watchMap, setWatchMap] = useState<Record<string, any>>({})
  const [mandate, setMandate] = useState<ReEntryMandate>(defaultMandate())
  const [eventClass, setEventClass] = useState<ReEntryEvent>({ eventType: 'other', reason: '', notes: '', updatedAt: '' })
  const [disposition, setDisposition] = useState<ReEntryDisposition>(defaultDisposition())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const rows: ExitEvidenceRow[] = prefValue(exitPref.data)?.rows ?? []
  const mandates = prefMap(mandatePref.data)
  const events = prefMap(eventPref.data)
  const dispositions = prefMap(dispositionPref.data)
  const rowsBySymbol = useMemo(() => {
    const map: Record<string, ExitEvidenceRow[]> = {}
    for (const row of rows) {
      const symbol = String(row.symbol || '').toUpperCase()
      if (!symbol) continue
      ;(map[symbol] ??= []).push(row)
    }
    for (const values of Object.values(map)) values.sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
    return map
  }, [rows])

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
    const fromUrl = () => {
      const value = new URL(window.location.href).searchParams.get('classify')
      if (value) open(value.split(','))
    }
    const handler = (raw: Event) => {
      raw.stopImmediatePropagation()
      const detail = (raw as CustomEvent)?.detail ?? {}
      open(Array.isArray(detail.symbols) ? detail.symbols : [detail.symbol])
    }
    fromUrl()
    window.addEventListener('popstate', fromUrl)
    window.addEventListener('reentry:classify-symbol', handler, true)
    return () => {
      window.removeEventListener('popstate', fromUrl)
      window.removeEventListener('reentry:classify-symbol', handler, true)
    }
  }, [])

  useEffect(() => {
    if (!symbols.length) return
    let dead = false
    const controller = new AbortController()
    Promise.all(symbols.map(async symbol => {
      try {
        const response = await fetch(`/api/v2/watchlist/items?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal: controller.signal })
        const payload = await response.json()
        const data = payload?.data ?? payload
        return [symbol, (data?.items ?? [])[0] ?? null] as const
      } catch {
        return [symbol, null] as const
      }
    })).then(entries => { if (!dead) setWatchMap(Object.fromEntries(entries)) })
    return () => { dead = true; controller.abort() }
  }, [symbols.join('|')])

  useEffect(() => {
    if (!symbols.length) return
    const first = symbols[0]
    const firstRow = rowsBySymbol[first]?.[0]
    const savedMandate = normalizedMandate(mandates[first])
    const savedEvent = firstRow ? normalizedEvent(firstRow, events[firstRow.event_key]) : { eventType: 'other', reason: '', notes: '', updatedAt: '' } as ReEntryEvent
    const savedDisposition = firstRow ? normalizedDisposition(dispositions[firstRow.event_key]) : defaultDisposition()
    const notes = savedEvent.notes || watchAnnotations(first, watchMap[first]).join('\n')
    setMandate(savedMandate)
    setEventClass({ ...savedEvent, notes })
    setDisposition(savedDisposition)
  }, [symbols.join('|'), rows, mandatePref.data, eventPref.data, dispositionPref.data, watchMap])

  if (!symbols.length || typeof document === 'undefined') return null
  const unresolved = symbols.filter(symbol => !tickerLike(symbol))
  const first = symbols[0]
  const latestRows = symbols.map(symbol => rowsBySymbol[symbol]?.[0]).filter(Boolean) as ExitEvidenceRow[]
  const watch = watchMap[first]
  const val = valuation(watch)
  const annotations = watchAnnotations(first, watch)

  const save = async () => {
    if (unresolved.length) return
    setBusy(true); setError('')
    try {
      const now = new Date().toISOString()
      const nextMandates = { ...mandates }
      const nextEvents = { ...events }
      const nextDispositions = { ...dispositions }
      for (const symbol of symbols) nextMandates[symbol] = { ...mandate, updatedAt: now }
      for (const row of latestRows) {
        nextEvents[row.event_key] = { ...eventClass, updatedAt: now }
        nextDispositions[row.event_key] = { ...disposition, updatedAt: now }
      }
      await Promise.all([
        saveUiPref(MANDATE_KEY, nextMandates),
        saveUiPref(EVENT_KEY, nextEvents),
        saveUiPref(DISPOSITION_KEY, nextDispositions),
      ])
      window.dispatchEvent(new CustomEvent('reentry:classification-saved', { detail: { symbols } }))
      mandatePref.refetch(); eventPref.refetch(); dispositionPref.refetch()
      close()
    } catch (value: any) {
      setError(String(value?.message || value)); setBusy(false)
    }
  }

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`${symbols.join(', ')} classification`} onMouseDown={close} style={{ position: 'fixed', inset: 0, zIndex: 10000, display: 'grid', placeItems: 'center', padding: 16, background: 'rgba(2,6,23,.90)' }}>
      <div onMouseDown={event => event.stopPropagation()} style={{ ...panel, width: 'min(1120px,97vw)', maxHeight: '94vh', overflowY: 'auto', padding: 16, boxShadow: '0 24px 80px rgba(0,0,0,.5)' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'start' }}><div style={{ flex: 1 }}><div style={{ fontSize: 20, fontWeight: 900 }}>{symbols.join(' · ')} — Classification</div><div style={{ fontSize: 10.5, color: BB.text3 }}>Body-level overlay · deep-linkable · operator edits remain separate from deterministic and model evidence.</div></div><button onClick={close} style={btn(false)}>CLOSE</button></div>

        {unresolved.length > 0 && <div style={{ ...panel, marginTop: 10, padding: 10, borderColor: BB.red, background: 'rgba(239,68,68,.08)', color: BB.red, fontSize: 10.5 }}><b>UNRESOLVED IDENTITY:</b> {unresolved.join(', ')} resembles a CUSIP/account identifier rather than a supported ticker. It is excluded from classification and actionable counts until symbol resolution is explicit.</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
          <div style={{ ...panel, padding: 11 }}><div style={{ fontSize: 11, fontWeight: 900 }}>DETERMINISTIC SOURCE COVERAGE</div><div style={{ marginTop: 7, display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>{[
            ['EXIT EVENTS', String(latestRows.length), latestRows.length ? BB.green : BB.amber],
            ['WATCH ITEM', watch ? 'AVAILABLE' : 'UNAVAILABLE', watch ? BB.green : BB.amber],
            ['IDENTITY', unresolved.length ? 'UNRESOLVED' : 'TICKER', unresolved.length ? BB.red : BB.green],
          ].map(([label, value, color]) => <div key={label} style={{ ...panel, padding: 7, background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: BB.text3 }}>{label}</div><b style={{ color }}>{value}</b></div>)}</div><div style={{ marginTop: 8, fontSize: 10, lineHeight: 1.55 }}>{annotations.map(line => <div key={line}>• {line}</div>)}</div></div>
          <div style={{ ...panel, padding: 11, borderColor: val.pe !== null || val.forwardPe !== null ? BB.green : BB.amber }}><div style={{ fontSize: 11, fontWeight: 900 }}>VALUATION — STORED FUNDAMENTAL EVIDENCE</div><div style={{ fontSize: 10, color: BB.text3, marginTop: 2 }}>P/E is evidence, never an action or quality score. Missing values remain unavailable.</div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6, marginTop: 8 }}>{[
            ['TRAILING P/E', val.pe === null ? 'UNAVAILABLE' : val.pe.toFixed(2)],
            ['FORWARD P/E', val.forwardPe === null ? 'UNAVAILABLE' : val.forwardPe.toFixed(2)],
            ['PEG', val.peg === null ? 'UNAVAILABLE' : val.peg.toFixed(2)],
          ].map(([label, value]) => <div key={label} style={{ ...panel, padding: 7, background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: BB.text3 }}>{label}</div><b style={{ color: value === 'UNAVAILABLE' ? BB.amber : 'var(--text0)' }}>{value}</b></div>)}</div><div style={{ fontSize: 10, color: BB.text3, marginTop: 7 }}>Source: {val.source} · as of {val.asOf || 'unavailable'}</div></div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
          <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>1 · PERSISTENT INVESTMENT CLASSIFICATION</div><label style={{ fontSize: 10, color: BB.text3 }}>PRIMARY MANDATE<select value={mandate.mandate} onChange={event => setMandate(value => ({ ...value, mandate: event.target.value as ReEntryMandate['mandate'] }))} style={{ ...field, marginTop: 4 }}><option value="core">CORE HOLDING</option><option value="satellite">SATELLITE / TACTICAL</option><option value="hedge">HEDGE</option><option value="unclassified">UNCLASSIFIED</option></select></label><div style={{ fontSize: 10, color: BB.text3, marginTop: 10 }}>MULTI-SELECT STRATEGY FLAGS</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 5 }}>{REENTRY_FLAGS.map(flag => <label key={flag} style={{ ...panel, padding: 8, background: mandate.flags[flag] ? BB.blueDim : 'var(--bg2)', cursor: 'pointer' }}><input type="checkbox" checked={mandate.flags[flag]} onChange={event => setMandate(value => ({ ...value, flags: { ...value.flags, [flag]: event.target.checked } }))} /> <b style={{ marginLeft: 5 }}>{flag.toUpperCase()}</b></label>)}</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 9 }}><label style={{ fontSize: 10, color: BB.text3 }}>TARGET ACCOUNT<input value={mandate.targetAccount} onChange={event => setMandate(value => ({ ...value, targetAccount: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>TARGET WEIGHT %<input type="number" min="0" max="100" step="0.1" value={mandate.targetWeightPct ?? ''} onChange={event => setMandate(value => ({ ...value, targetWeightPct: event.target.value === '' ? null : Number(event.target.value) }))} style={{ ...field, marginTop: 4 }} /></label><label style={{ fontSize: 10, color: BB.text3 }}>PRIORITY<select value={mandate.priority} onChange={event => setMandate(value => ({ ...value, priority: event.target.value as ReEntryMandate['priority'] }))} style={{ ...field, marginTop: 4 }}><option>HIGH</option><option>NORMAL</option><option>LOW</option></select></label></div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>THESIS / WHAT MUST BE TRUE<textarea rows={4} value={mandate.thesis} onChange={event => setMandate(value => ({ ...value, thesis: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label></div>
          <div style={{ ...panel, padding: 12 }}><div style={{ fontSize: 11, fontWeight: 900, marginBottom: 8 }}>2 · LATEST EXIT EVENT + QUEUE</div>{latestRows.length === 0 && <div style={{ color: BB.amber, fontSize: 10.5, marginBottom: 8 }}>No full-fidelity exit row is available. The persistent mandate can still be saved; event-specific fields will not fabricate a transaction.</div>}<label style={{ display: 'block', fontSize: 10, color: BB.text3 }}>EXIT TYPE<select disabled={!latestRows.length} value={eventClass.eventType} onChange={event => setEventClass(value => ({ ...value, eventType: event.target.value as ReEntryEvent['eventType'] }))} style={{ ...field, marginTop: 4 }}>{EXIT_TYPES.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ').toUpperCase()}</option>)}</select></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>REASON<input disabled={!latestRows.length} value={eventClass.reason} onChange={event => setEventClass(value => ({ ...value, reason: event.target.value }))} placeholder="Unavailable until broker/journal evidence exists" style={{ ...field, marginTop: 4 }} /></label><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 9 }}>EDITABLE NOTES<textarea rows={8} value={eventClass.notes} onChange={event => setEventClass(value => ({ ...value, notes: event.target.value }))} style={{ ...field, marginTop: 4 }} /></label><div style={{ ...panel, padding: 9, marginTop: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10, fontWeight: 900 }}>QUEUE DISPOSITION</div>{(['monitor', 'review', 'suppressed'] as const).map(state => <label key={state} style={{ display: 'block', marginTop: 6 }}><input type="radio" name="overlay-disposition" checked={disposition.state === state} onChange={() => setDisposition(value => ({ ...value, state }))} /> <b style={{ marginLeft: 5, color: state === 'monitor' ? BB.green : state === 'suppressed' ? BB.amber : 'var(--text1)' }}>{state.toUpperCase()}</b></label>)}<input value={disposition.reason} onChange={event => setDisposition(value => ({ ...value, reason: event.target.value }))} placeholder="Why monitor, review, or suppress?" style={{ ...field, marginTop: 8 }} /></div></div>
        </div>
        {(error || exitPref.error) && <div style={{ color: BB.red, fontSize: 10.5, marginTop: 9 }}>{error || exitPref.error}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}><button onClick={close} style={btn(false)}>CANCEL</button><button disabled={busy || unresolved.length > 0} onClick={() => void save()} style={{ ...btn(true), borderColor: BB.green, color: BB.green, opacity: unresolved.length ? .5 : 1 }}>{busy ? 'SAVING…' : 'SAVE CLASSIFICATION'}</button></div>
      </div>
    </div>,
    document.body,
  )
}
