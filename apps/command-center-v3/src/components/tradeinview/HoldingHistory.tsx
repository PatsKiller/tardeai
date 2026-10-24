/** Holding history is a read-only view of the server's merged, provenance-bearing ledger. */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { HISTORY_SORTS, dateText, decodeHistory, finite, gapText, historyUrl, missingReason, money, namedGaps, numberText, percent, provenanceText, reasonText, segmentGeometry, sortFrom,
  type Gap, type HistoryDetail, type HistorySymbol, type HistoryTrip, type HoldingHistoryPayload } from '../../lib/holdingHistoryModel'
import './HoldingHistory.css'

type Props = { onReplay: (tradeId: string) => void }
const historyStyle = { '--hh-bg': TOKENS.bg[1], '--hh-inset': TOKENS.bg[0], '--hh-border': TOKENS.border, '--hh-muted': TOKENS.text[2], '--hh-text': TOKENS.text[0], '--hh-info': TOKENS.info, '--hh-focus': TOKENS.focusRing,
  '--hh-font': FONT.sans, '--hh-mono': FONT.mono, '--hh-heading': `${TYPE.lg}px`, '--hh-type': `${TYPE.base}px`, '--hh-small': `${TYPE.sm}px` } as CSSProperties
function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 820px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 820px)')
    const update = () => setPhone(query.matches)
    update(); query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return phone
}
function MobileDetail({ symbol, onBack, children }: { symbol: string; onBack: () => void; children: ReactNode }) {
  const sheet = useRef<HTMLDivElement>(null)
  const back = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    back.current?.focus()
    return () => { document.body.style.overflow = previous }
  }, [])
  return createPortal(<div ref={sheet} className="holding-history hh-mobile-sheet cc-terminal-ui" role="dialog" aria-modal="true" aria-labelledby="hh-mobile-title" data-testid="history-detail-sheet" style={historyStyle}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); onBack(); return }
      if (event.key !== 'Tab') return
      const controls = Array.from(sheet.current?.querySelectorAll<HTMLElement>('button:not(:disabled), summary, a[href], [tabindex="0"]') || []).filter(el => el.getClientRects().length)
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }}>
    <header className="hh-sheet-header"><button ref={back} type="button" onClick={onBack} data-testid="history-back">← Back to names</button><h2 id="hh-mobile-title">{symbol} history</h2></header>
    <div className="hh-sheet-body">{children}</div>
  </div>, document.body)
}
const colorFor = (value: unknown) => finite(value) && value !== 0 ? (value > 0 ? TOKENS.success : TOKENS.danger) : TOKENS.text[0]
function Gaps({ gaps, heading = 'Data gaps, shown not hidden' }: { gaps: Gap[]; heading?: string }) {
  if (!gaps.length) return null
  return <aside className="hh-gaps" data-testid="history-gaps" aria-label={heading} style={{ background: toneVars('warning').bg, borderColor: toneVars('warning').border, color: toneVars('warning').color }}>
    <strong>{heading}</strong>{gaps.length > 6 ? <details><summary>{gaps.length} source findings · view all</summary><ul>{gaps.map((g, i) => <li key={`${g.source}-${i}`}>{gapText(g)}</li>)}</ul></details> : <ul>{gaps.map((g, i) => <li key={`${g.source}-${i}`}>{gapText(g)}</li>)}</ul>}
  </aside>
}
function Name({ row, selected, onSelect }: { row: HistorySymbol; selected: boolean; onSelect: () => void }) {
  return <button type="button" className="hh-name" data-testid="history-name" data-symbol={row.symbol} aria-pressed={selected} onClick={onSelect}>
    <span className="hh-name-heading"><b>{row.symbol}</b><span title={row.company_missing_reason || undefined}>{row.company_name || 'Company name unavailable'}</span></span>
    {!row.company_name && <small>{reasonText(row.company_missing_reason)}</small>}
    <span className="hh-muted">{numberText(row.round_trip_count, 0)} round trips · {numberText(row.account_count, 0)} accounts</span>
    {(row.round_trip_count == null || row.account_count == null) && <small>{row.gaps.length ? row.gaps.map(gapText).join(' · ') : 'Count coverage unavailable'}</small>}
    <span className="hh-name-flags">{row.held_now === true ? 'Held now' : row.held_now === false ? 'Not held now' : 'Current holding state unavailable'}{row.basis_unknown ? ' · Basis unknown' : ''}</span>
    {row.held_now && row.accounts.map((a, i) => <small key={a.account_id || i}>{a.account_label || 'Account name unavailable'}: {numberText(a.held_quantity)} sh{a.held_quantity == null ? ' · quantity unavailable' : ''}</small>)}
  </button>
}
function Stats({ detail }: { detail: HistoryDetail }) {
  const s = detail.stats
  const cards = [
    { key: 'times_held', label: 'Times held', value: numberText(s.times_held, 0), sub: s.times_held == null && finite(s.known_holding_stretches) ? `Known stretches ${numberText(s.known_holding_stretches, 0)}` : 'Separate holding stretches', missing: s.times_held == null },
    { key: 'round_trip_count', label: 'Round trips', value: numberText(s.round_trip_count, 0), sub: 'In the selected history range', missing: s.round_trip_count == null },
    { key: 'win_rate_pct', label: 'Win rate', value: percent(s.win_rate_pct), sub: 'By round trip', missing: s.win_rate_pct == null },
    { key: 'realized_pl', label: 'Realized total', value: money(s.realized_pl), sub: s.realized_pl == null && finite(s.known_realized_pl) ? `Known subtotal ${money(s.known_realized_pl)}` : 'All accounts · selected range', missing: s.realized_pl == null, color: colorFor(s.realized_pl) },
    { key: 'avg_hold_days', label: 'Avg hold', value: finite(s.avg_hold_days) ? `${numberText(s.avg_hold_days)} d` : '—', sub: `Median ${finite(s.median_hold_days) ? `${numberText(s.median_hold_days)} d` : 'unavailable'}`, missing: s.avg_hold_days == null || s.median_hold_days == null },
    { key: 'best_trip_pct', label: 'Best / worst', value: `${percent(s.best_trip_pct)} / ${percent(s.worst_trip_pct)}`, sub: 'Per trip', missing: s.best_trip_pct == null || s.worst_trip_pct == null },
  ]
  return <div className="hh-stats" aria-label="Server history statistics">{cards.map(c => <div className="hh-stat" key={c.key} data-testid={`history-stat-${c.key}`}>
    <span className="hh-muted">{c.label}</span><strong style={{ color: c.color || TOKENS.text[0] }}>{c.value}</strong><small>{c.sub}</small>
    {c.missing && <small className="hh-gap-reason">{missingReason(s.coverage, c.key)}</small>}
  </div>)}</div>
}
function Timelines({ data, detail }: { data: HoldingHistoryPayload; detail: HistoryDetail }) {
  return <section className="hh-timelines" aria-label="When you held it by account"><h3>Recorded holding observations · by account</h3><p className="hh-muted">Bars show stored observations and recorded trip intervals; they do not prove uninterrupted ownership.</p>
    {!detail.account_segments.length && <p className="hh-muted">No holding segments on file. {missingReason(detail.stats.coverage)}</p>}
    {detail.account_segments.map((a, i) => <div className="hh-account-timeline" key={a.account_id || i} data-testid="history-account-timeline">
      <div><strong>{a.account_label || 'Account name unavailable'}</strong><small>Observed {dateText(a.as_of)}</small></div>
      <div className="hh-segments"><div className="hh-track" aria-hidden="true">{a.segments.map((s, n) => {
        const g = segmentGeometry(data.range, s)
        return g ? <span key={n} className="hh-segment" style={{ left: `${g.left}%`, width: `${g.width}%` }} /> : null
      })}</div>
      <div className="hh-axis"><span>{dateText(data.range.start_date)}</span><span>{dateText(data.range.end_date)}</span></div>
      {!a.segments.length && <small>No observed holding stretches on file</small>}
      <ul className="hh-segment-notes">{a.segments.map((s, n) => <li key={n}>{dateText(s.start_at || s.start_date)} → {dateText(s.end_at || s.end_date)}
        {' · '}{s.status ? reasonText(s.status) : 'Status unavailable'} · {s.source || 'Source unavailable'}{s.precision ? ` · ${reasonText(s.precision)}` : ''}
        {!segmentGeometry(data.range, s) && <small>Timeline position unavailable: a source endpoint or range is missing</small>}
        {!!s.gaps?.length && <span className="hh-gap-reason">{s.gaps.map(gapText).join(' · ')}</span>}
      </li>)}</ul></div>
    </div>)}
  </section>
}
function Trip({ trip: t, onReplay, accountOptions }: { trip: HistoryTrip; onReplay: Props['onReplay']; accountOptions?: { id: string; label: string }[] }) {
  const provenance = provenanceText(t.provenance)
  return <div className="hh-trip" data-testid="history-trip" role="row">
    <div role="cell" data-label="Account"><span>{t.account_label || 'Account name unavailable'}</span></div>
    <div role="cell" data-label="Bought"><b>{money(t.entry_price)}</b><small>{dateText(t.entry_at || t.entry_date)}</small>{t.entry_price == null && <small className="hh-gap-reason">{reasonText(t.basis_reason)}</small>}</div>
    <div role="cell" data-label="Sold"><b>{money(t.exit_price)}</b><small>{dateText(t.exit_at || t.exit_date)}</small>{t.exit_price == null && <small>Exit price unavailable</small>}</div>
    <div role="cell" data-label="Shares"><b>{numberText(t.shares)}</b>{t.shares == null && <small>Quantity unavailable</small>}</div>
    <div role="cell" data-label="Days"><b>{numberText(t.hold_days)}</b><small>{t.hold_days_basis ? reasonText(t.hold_days_basis) : 'Hold-day basis unavailable'}</small></div>
    <div role="cell" data-label="Result"><b style={{ color: colorFor(t.realized_pl) }}>{money(t.realized_pl)}</b><small>{percent(t.return_pct)}</small>{(t.basis_unknown || t.realized_pl == null) && <small className="hh-gap-reason">{t.basis_unknown ? 'Basis unknown' : 'Result unavailable'} · {reasonText(t.basis_reason)}</small>}</div>
    <div role="cell" data-label="Source"><span className="hh-muted">{t.source || 'Source unavailable'}</span>
      <details><summary>Provenance</summary>{provenance.length ? <ul>{provenance.map((p, i) => <li key={i}>{p}</li>)}</ul> : <small>No additional provenance on file</small>}</details>
      {!!t.gaps?.length && <small className="hh-gap-reason">{namedGaps(t.gaps, accountOptions).map(gapText).join(' · ')}</small>}
      {t.trade_id ? <button type="button" className="hh-replay" data-testid="history-replay" data-trade-id={t.trade_id} onClick={() => onReplay(t.trade_id!)} aria-label={`Replay ${t.symbol || ''} trade`}>Replay this trip →</button> : <small>Replay unavailable: trade ID missing</small>}
    </div>
  </div>
}
function Request({ path, selectedSymbol, onSelect, sort, onSort, onReplay, phone, onBack, returnFocusSymbol }: Props & { path: string; selectedSymbol: string | null; onSelect: (symbol: string) => void; sort: string; onSort: (sort: string) => void; phone: boolean; onBack: () => void; returnFocusSymbol: string | null }) {
  const { data: raw, loading, refreshing, error, stale, refetch } = useApi<unknown>(path)
  const data = decodeHistory(raw)
  const mismatch = data?.detail && selectedSymbol && data.detail.symbol.toUpperCase() !== selectedSymbol.toUpperCase()
  const detail = mismatch ? null : data?.detail
  const selected = data?.symbols.find(r => r.symbol === detail?.symbol)
  const names = useRef<HTMLDivElement>(null)
  const sheetOpen = phone && !!selectedSymbol
  useEffect(() => {
    if (!phone || selectedSymbol || !returnFocusSymbol || !data) return
    const button = Array.from(names.current?.querySelectorAll<HTMLButtonElement>('[data-symbol]') || []).find(el => el.dataset.symbol === returnFocusSymbol)
    button?.focus({ preventScroll: true }); button?.scrollIntoView({ block: 'nearest' })
  }, [phone, selectedSymbol, returnFocusSymbol, data])
  const status = <><div className="hh-request-status"><span>{data ? `Collected ${dateText(data.as_of)} · ${data.range.basis || 'Range basis unavailable'}` : loading ? 'Loading holding history…' : 'Holding history unavailable'}</span>
    <button type="button" onClick={refetch} disabled={loading || refreshing}>{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    {stale && <p role="status" className="hh-transport-warning">Showing the previously collected history; refresh did not succeed. {error || 'Server unavailable'} · original collection time retained.</p>}
    {!data && !loading && <p role="alert">{error || 'Holding history response is missing or does not match the read-only schema.'}</p>}</>
  const content = data && <>
      <Gaps gaps={namedGaps(data.gaps, data.account_options)} />
      {!data.ok && <p role="status" className="hh-transport-warning">Stored history coverage is incomplete. See the source gaps below.</p>}
      {mismatch && <p role="alert">Selected history unavailable: the server detail does not match {selectedSymbol}.</p>}
      {!detail && !mismatch && <div className="hh-panel"><p>{selectedSymbol ? `No stored detail for ${selectedSymbol}.` : 'Choose a name to see its account history.'}</p></div>}
      {detail && <><div className="hh-panel"><header className="hh-detail-heading"><h2><span>{detail.symbol}</span> · {detail.company_name || 'Company name unavailable'}</h2>
        <p>{selected?.held_now === true ? 'Held now' : selected?.held_now === false ? 'Not held now' : 'Current holding state unavailable'} · {numberText(selected?.account_count, 0)} accounts</p>
        {selected?.account_count == null && <small>Account count not supplied in the symbol summary</small>}
        {!detail.company_name && <small>{reasonText(detail.company_missing_reason)}</small>}</header>
        <Gaps gaps={namedGaps(detail.gaps, data.account_options)} heading={`${detail.symbol} source gaps`} /><Stats detail={detail} /><Timelines data={data} detail={detail} /></div>
        <section className="hh-trips hh-panel" aria-label="Every recorded trip">
          {!detail.trips.length && <p className="hh-empty">No trip rows returned for this name. {missingReason(detail.stats.coverage)}</p>}
          <div role="table" aria-label="Holding history trips"><div className="hh-trip-head" role="row">{['Account', 'Bought', 'Sold', 'Shares', 'Days', 'Result', 'Source'].map(label => <span key={label} role="columnheader">{label}</span>)}</div>
          {detail.trips.map((t, i) => <Trip key={t.trade_id || i} trip={t} onReplay={onReplay} accountOptions={data.account_options} />)}</div>
        </section></>}
    </>
  return <>
    <section className="holding-history" aria-label="Holding history" style={historyStyle} aria-hidden={sheetOpen || undefined} ref={el => { if (el) el.inert = sheetOpen }}>
      {status}
      {data && <div className="hh-layout"><aside className="hh-names" aria-label="Names with repeat or multiple-account holdings">
        <p className="hh-muted">Names you held more than once, or in more than one account</p>
        <div className="hh-sorts" role="group" aria-label="History sort">{HISTORY_SORTS.map(s => <button key={s.id} type="button" aria-pressed={s.id === sort} onClick={() => onSort(s.id)}>{s.label}</button>)}</div>
        {!data.symbols.length && <p>No names returned by holding history. {missingReason(data.range.coverage)}</p>}
        <div ref={names} className="hh-name-list">{data.symbols.map(row => <Name key={row.symbol} row={row} selected={row.symbol === (selectedSymbol || (!phone && detail?.symbol))} onSelect={() => onSelect(row.symbol)} />)}</div>
      </aside>{phone ? !sheetOpen && <div className="hh-main"><Gaps gaps={namedGaps(data.gaps, data.account_options)} />{!data.ok && <p className="hh-transport-warning">Stored history coverage is incomplete. See the source gaps.</p>}</div> : <div className="hh-main">{content}</div>}</div>}
    </section>
    {sheetOpen && <MobileDetail symbol={selectedSymbol!} onBack={onBack}>{status}<div className="hh-main">{content}</div></MobileDetail>}
  </>
}
export default function HoldingHistory({ onReplay }: Props) {
  const [params, setParams] = useSearchParams()
  const location = useLocation(), navigate = useNavigate()
  const phone = usePhone()
  const returnFocusSymbol = useRef<string | null>(null)
  const symbol = params.get('symbol')?.trim().toUpperCase() || null
  const sort = sortFrom(params.get('history_sort'))
  const path = historyUrl(symbol, sort)
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); next.set(key, value); setParams(next) }
  const select = (value: string) => {
    returnFocusSymbol.current = value
    const next = new URLSearchParams(params); next.set('symbol', value)
    setParams(next, { state: { ...location.state, historyNamesEntry: !symbol } })
  }
  const back = () => {
    returnFocusSymbol.current = symbol
    if (location.state?.historyNamesEntry) navigate(-1)
    else { const next = new URLSearchParams(params); next.delete('symbol'); setParams(next, { replace: true }) }
  }
  return <Request key={path} path={path} selectedSymbol={symbol} phone={phone} onBack={back} returnFocusSymbol={returnFocusSymbol.current} sort={sort} onSelect={select} onSort={s => { returnFocusSymbol.current = null; update('history_sort', s) }} onReplay={onReplay} />
}
