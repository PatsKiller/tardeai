import { useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'
import {
  DISPOSITION_KEY,
  EVENT_KEY,
  MANDATE_KEY,
  REENTRY_FLAGS,
  classificationLabel,
  classificationState,
  finite,
  normalizedDisposition,
  normalizedEvent,
  normalizedMandate,
  prefMap,
  rowPrice,
  rowShares,
  type ExitEvidenceRow,
  type ReEntryDisposition,
  type ReEntryEvent,
  type ReEntryMandate,
} from '../../lib/reentrySharedContext'
import { HelpTip } from './ReEntryHelpGuide'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const field: CSSProperties = { fontSize: 11.5, padding: '7px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text0)' }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 850, padding: '5px 9px', borderRadius: 4, cursor: 'pointer', border: `1px solid ${active ? BB.blue : 'var(--border)'}`, background: active ? BB.blueDim : 'var(--bg2)', color: active ? BB.blue : 'var(--text2)' })

type Summary = { symbol: string; rows: ExitEvidenceRow[]; latest: ExitEvidenceRow; shares: number | null; avgExit: number | null; proceeds: number; accounts: string[]; scalpCount: number; monitorCount: number; suppressedCount: number }
function money(value: number | null): string { return value === null ? '—' : `$${value.toFixed(2)}` }
function qty(value: number | null): string { return value === null ? '—' : value.toLocaleString() }
function classify(symbols: string[]) { window.dispatchEvent(new CustomEvent('reentry:classify-symbol', { detail: { symbols } })) }
function isScalp(row: ExitEvidenceRow, event: ReEntryEvent): boolean { return event.eventType === 'day_trade' || event.eventType === 'momentum_scalp' || /day.?trade|scalp|intraday/i.test(`${row.description ?? ''} ${row.action ?? ''}`) }

export default function ReEntryExitWorkbench() {
  const evidence = useReEntryExitEvidence(365)
  const mandatesPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(MANDATE_KEY)}`, 0)
  const eventsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(EVENT_KEY)}`, 0)
  const dispositionsPref = useApi<any>(`/api/v2/ui/prefs/get?key=${encodeURIComponent(DISPOSITION_KEY)}`, 0)
  const mandates: Record<string, ReEntryMandate> = prefMap(mandatesPref.data) as Record<string, ReEntryMandate>
  const events: Record<string, ReEntryEvent> = prefMap(eventsPref.data) as Record<string, ReEntryEvent>
  const dispositions: Record<string, ReEntryDisposition> = prefMap(dispositionsPref.data) as Record<string, ReEntryDisposition>
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'long_term' | 'active' | 'scalps' | 'suppressed' | 'all'>('long_term')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [showAll, setShowAll] = useState(false)

  const summaries = useMemo(() => {
    const groups = new Map<string, ExitEvidenceRow[]>()
    for (const row of evidence.rows) { const symbol = String(row.symbol || '').toUpperCase(); if (symbol) groups.set(symbol, [...(groups.get(symbol) ?? []), row]) }
    return [...groups.entries()].map(([symbol, sourceRows]) => {
      const rows = sourceRows.slice().sort((a, b) => `${b.trade_date ?? ''}T${b.trade_time ?? ''}`.localeCompare(`${a.trade_date ?? ''}T${a.trade_time ?? ''}`))
      let shares = 0; let weighted = 0; let proceeds = 0; let known = false
      let scalpCount = 0; let monitorCount = 0; let suppressedCount = 0
      for (const row of rows) {
        const amount = rowShares(row); const price = rowPrice(row); const cash = finite(row.proceeds_usd)
        if (amount !== null) { known = true; shares += amount; if (price !== null) weighted += amount * price }
        if (cash !== null) proceeds += Math.abs(cash)
        const event = normalizedEvent(row, events[row.event_key]); const disposition = normalizedDisposition(dispositions[row.event_key])
        if (isScalp(row, event)) scalpCount += 1
        if (disposition.state === 'monitor') monitorCount += 1
        if (disposition.state === 'suppressed') suppressedCount += 1
      }
      return { symbol, rows, latest: rows[0], shares: known ? shares : null, avgExit: shares > 0 && weighted > 0 ? weighted / shares : null, proceeds, accounts: [...new Set(rows.map(row => String(row.account || '')).filter(Boolean))], scalpCount, monitorCount, suppressedCount } satisfies Summary
    }).sort((a, b) => String(b.latest.trade_date || '').localeCompare(String(a.latest.trade_date || '')))
  }, [evidence.rows, eventsPref.data, dispositionsPref.data])

  const filtered = summaries.filter(summary => {
    if (search.trim() && !`${summary.symbol} ${summary.accounts.join(' ')} ${summary.rows.map(row => `${row.action ?? ''} ${row.description ?? ''}`).join(' ')}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    const allSuppressed = summary.suppressedCount === summary.rows.length
    const activeNonScalp = summary.rows.some(row => normalizedDisposition(dispositions[row.event_key]).state !== 'suppressed' && !isScalp(row, normalizedEvent(row, events[row.event_key])))
    if (scope === 'long_term') return activeNonScalp
    if (scope === 'active') return !allSuppressed
    if (scope === 'scalps') return summary.scalpCount > 0
    if (scope === 'suppressed') return summary.suppressedCount > 0
    return true
  })
  const shown = filtered.slice(0, showAll ? filtered.length : 75)
  const selectedSymbols = shown.filter(summary => selected[summary.symbol]).map(summary => summary.symbol)
  const sourceCount = evidence.sources.filter(source => source.available).length

  return <div id="reentry-exit-summary" style={{ ...panel, padding: 10 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}><div><div style={{ fontSize: 14, fontWeight: 900 }}>EXIT CLASSIFICATION WORKBENCH <HelpTip text="The exit universe is reconciled from all available broker/journal/redeploy sources. Classification always opens the shared evidence-complete modal." /></div><div style={{ fontSize: 10, color: BB.text3 }}>{evidence.rows.length} reconciled exit transactions · {summaries.length} symbols · {sourceCount}/{evidence.sources.length} sources reporting</div></div><button onClick={() => { evidence.refetch(); mandatesPref.refetch(); eventsPref.refetch(); dispositionsPref.refetch() }} style={{ ...button(false), marginLeft: 'auto' }}>{evidence.loading || evidence.refreshing ? 'REFRESHING…' : 'REFRESH EXIT DATA'}</button></div>

    <div style={{ ...panel, padding: 8, marginTop: 8, background: 'var(--bg2)', fontSize: 10 }}><b>Evidence sources:</b> {evidence.sources.map(source => `${source.label} ${source.rows}`).join(' · ')}. Missing shares or prices remain explicit; no values are inferred from prose or an LLM.</div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px,1fr) 250px auto auto auto auto', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search symbols, accounts or descriptions…" style={field} /><select value={scope} onChange={event => setScope(event.target.value as typeof scope)} style={field}><option value="long_term">LONG-TERM QUEUE · HIDE SCALPS</option><option value="active">ALL ACTIVE · INCLUDE SCALPS</option><option value="scalps">DAY TRADES / MOMENTUM SCALPS</option><option value="suppressed">SUPPRESSED ITEMS</option><option value="all">ALL EXITS</option></select><button onClick={() => setSelected(Object.fromEntries(shown.map(summary => [summary.symbol, true])))} style={button(false)}>SELECT VISIBLE</button><button onClick={() => setSelected({})} style={button(false)}>CLEAR</button><button disabled={!selectedSymbols.length} onClick={() => classify(selectedSymbols)} style={{ ...button(Boolean(selectedSymbols.length)), opacity: selectedSymbols.length ? 1 : .5 }}>CLASSIFY SELECTED {selectedSymbols.length}</button><button onClick={() => setShowAll(value => !value)} style={button(showAll)}>{showAll ? 'SHOW FIRST 75' : `SHOW ALL ${filtered.length}`}</button></div>

    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1320 }}><div style={{ display: 'grid', gridTemplateColumns: '28px 190px 105px 95px 110px 110px 120px 120px 170px 1fr', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span></span><span>Symbol / classification</span><span>Latest exit</span><span>Executions</span><span>Cum shares</span><span>Avg exit</span><span>Proceeds</span><span>Queue</span><span>Accounts</span><span>Mandate / source</span></div>{shown.map(summary => {
      const mandate = normalizedMandate(mandates[summary.symbol]); const state = classificationState(mandate, summary.rows, events, dispositions); const open = Boolean(expanded[summary.symbol]); const flags = REENTRY_FLAGS.filter(flag => mandate.flags[flag]).map(flag => flag.toUpperCase()); const mandateLabel = mandate.mandate === 'unclassified' && flags.length ? 'MANDATE NEEDED' : mandate.mandate.toUpperCase(); const queue = summary.suppressedCount === summary.rows.length ? 'SUPPRESSED' : summary.monitorCount ? 'MONITORING' : 'REVIEW'
      return <div key={summary.symbol}><div onClick={() => setExpanded(value => ({ ...value, [summary.symbol]: !open }))} style={{ display: 'grid', gridTemplateColumns: '28px 190px 105px 95px 110px 110px 120px 120px 170px 1fr', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: open ? 'var(--bg2)' : 'transparent' }}><input type="checkbox" checked={Boolean(selected[summary.symbol])} onClick={event => event.stopPropagation()} onChange={event => setSelected(value => ({ ...value, [summary.symbol]: event.target.checked }))} /><div><div><b style={{ fontSize: 14 }}>{summary.symbol}</b> <span style={{ color: state === 'CLASSIFIED' ? BB.green : state === 'AUTO-TAGGED' ? BB.amber : BB.text3, fontSize: 10 }}>{classificationLabel(state)}</span> <span style={{ color: BB.text3 }}>{open ? '▾' : '▸'}</span></div><button onClick={event => { event.stopPropagation(); classify([summary.symbol]) }} style={{ ...button(true), padding: '3px 7px', marginTop: 5 }}>{state === 'CLASSIFIED' ? 'EDIT CLASSIFICATION' : 'CLASSIFY'}</button></div><span>{summary.latest.trade_date ?? '—'}</span><span><b>{summary.rows.length}</b> exits<br /><span style={{ color: BB.text3 }}>{summary.scalpCount} scalp/day</span></span><b>{qty(summary.shares)}</b><b>{money(summary.avgExit)}</b><b>{money(summary.proceeds)}</b><span><b>{queue}</b><br /><span style={{ color: BB.text3 }}>{summary.suppressedCount} suppressed · {summary.monitorCount} saved</span></span><span>{summary.accounts.join(' · ') || '—'}</span><span><b style={{ color: mandateLabel === 'MANDATE NEEDED' ? BB.amber : 'var(--text1)' }}>{mandateLabel}</b> · {flags.join(' / ') || 'NO FLAGS'}<br /><span style={{ color: BB.text3 }}>{summary.latest.import_source || 'source unavailable'}</span></span></div>
      {open && <div style={{ padding: '6px 8px 10px 40px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)' }}>{summary.rows.map(row => { const event = normalizedEvent(row, events[row.event_key]); const disposition = normalizedDisposition(dispositions[row.event_key]); return <div key={row.event_key} style={{ display: 'grid', gridTemplateColumns: '100px 130px 85px 95px 110px 110px 1fr 95px', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}><span>{row.trade_date ?? '—'} {row.trade_time ?? ''}</span><span>{row.account ?? '—'}</span><span>{qty(rowShares(row))} sh</span><span>{money(rowPrice(row))}</span><span>{money(finite(row.proceeds_usd))}</span><span>{event.eventType.replace(/_/g, ' ').toUpperCase()}</span><span>{event.reason || 'reason unavailable'}<br /><span style={{ color: BB.text3 }}>{row.description || 'source description unavailable'} · {row.import_source || 'source unavailable'}</span></span><span>{disposition.state.toUpperCase()}</span></div>})}</div>}
      </div>
    })}</div></div>
    {evidence.errors.length > 0 && <div style={{ color: BB.red, fontSize: 10, marginTop: 6 }}>Source warnings: {evidence.errors.join(' · ')}</div>}
  </div>
}
