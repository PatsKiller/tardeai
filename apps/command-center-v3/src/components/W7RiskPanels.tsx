import { useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { DrillContext } from './DetailDrawer'
import { W7Gap, W7Metric, W7Panel, W7PolicyLimits, grid, line, linkStyle, mono, pct, text, usd, when } from './W7PagePanels'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'
import { STOP_CATEGORY_LABEL, STOP_CATEGORY_TONE, stopCategory, stopDistancePct, stopLossUsd, symbolList, type StopCategory } from '../lib/stopDisplay'
import { snapshotFacts, stopReadFreshness } from '../lib/portfolioV002'
import { stopReconciliation } from '../lib/stopReconciliation'
import { toneVars } from '../lib/designTokens'
import { ShadowTag } from './home/MarketRiskBanner'
import { Explain, GlossaryProvider } from './home/MarketRiskActions'
import { RecoveryListView } from './recovery/RecoveryViews'
import { useCaseGates } from './recovery/RecoveryCaseCard'
import { byImpact, recoveryProjection } from '../lib/recoveryCases'
import { plainEngineReason, shadowMarker, bannerVisible, budgetLabel, contributorsDisagreeWithScore, episodeLine, fmtPct, pointsSum, pointsToScore, renderedTier, shortTime, tierTone, unwrapMarketRisk, type MarketRisk } from '../lib/marketRisk'
import { isDeadCusipHolding } from '../lib/deadCusipHolding'
import { heatText, scoreText, unprotectedFact } from '../lib/metricAuthority'

const stateLabel: Record<string, string> = { active: 'Active', pending_activation: 'Pending activation', pending: 'Pending activation', filled: 'Filled', none: 'None' }
const sourceLabel: Record<string, string> = { broker: 'Broker resting', broker_resting: 'Broker resting', planned: 'Planned', none: 'None', confirmed: 'Operator confirmed' }
const toneColor = { good: TOKENS.success, warn: TOKENS.warning, bad: TOKENS.danger }
const plural = (n: number) => `${n} ${n === 1 ? 'position' : 'positions'}`
const money = (v: number | null) => v == null ? 'Not available' : usd(v)
/** operator 2026-11-06: a missing percentage says why, never a bare "Not measured" (W7PagePanels.pct is shared, so the
 *  reason is supplied here). */
const pctWhy = (v: unknown, why: string) => typeof v === 'number' && Number.isFinite(v) ? pct(v) : why
/** LQ-20261107-1837 (C4): portfolio heat has ONE precision everywhere — this page used `pct` (2 dp, "1.27%")
 *  while Home and Health showed 1 dp ("1.3%"). Same authority field, same face. */
const heatWhy = (v: unknown, why: string) => typeof v === 'number' && Number.isFinite(v) ? heatText(v) : why
/** Correlation (i) when the API sent no glossary (this panel is outside the market-risk card). The 20-return floor is
 *  scripts/portfolio_correlation.py's; the text names it so a blank cell is explained, not hidden. */
const CORR_NO_VALUE = { label: 'Why no correlation value?', text: 'A pair gets a value only when both symbols have at least 20 shared daily returns and neither price series is flat. A newer holding or a pair with gaps in its price history has no value yet.' }
const price = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? `$${v.toLocaleString('en-US', { maximumFractionDigits: 4 })}` : 'Not available'
/** PR-015: the execution-read watermark that turns a count into an observation. Without one a zero is UNKNOWN. */
const awaitingThrough = (stops: any): string | null =>
  typeof stops?.last_broker_read_label === 'string' && stops.last_broker_read_label.trim() ? stops.last_broker_read_label.trim() : null
function awaitingDetail(stops: any, filledRows: any[], crossed: any[]): string {
  const through = awaitingThrough(stops)
  const filled = filledRows.length, crossedN = crossed.length
  const queues = `${filled} recorded fill${filled === 1 ? '' : 's'} awaiting holdings sync · ${crossedN} quote crossing${crossedN === 1 ? '' : 's'}`
  if (!through) return `${queues} — no execution read is published, so a zero here is UNKNOWN, not proof that nothing filled`
  if (!filled && !crossedN) return `No fill recorded and no stop crossed through the last broker read ${through}. A quote crossing without a broker fill is not a fill.`
  const names = [...filledRows, ...crossed].map((p: any) => p.symbol).filter(Boolean)
  return `${queues}${names.length ? ` (${names.join(', ')})` : ''} · through the last broker read ${through}. A crossing is not a fill, and a fill is not yet a holdings change.`
}

/** PR-012: a price is an observation with its own clock, and the book clock is not that clock. A row carries a quote
 *  time only when the projection publishes one (`price_as_of`); until it does the row says so rather than inheriting
 *  `positions.as_of`. `To stop` and `Loss at stop` rest on that quote, so a quote that is stale, in the future or
 *  unreadable is qualified below the table instead of silently presented as current. */
const QUOTE_FRESH_MS = 15 * 60_000
const QUOTE_SKEW_MS = 5 * 60_000
const QUOTE_CLOCK_KEYS = ['price_as_of', 'quote_at', 'priced_at', 'price_time'] as const
type QuoteState = { kind: 'unpublished' } | { kind: 'invalid' } | { kind: 'future' } | { kind: 'aged'; text: string; stale: boolean }
function rowQuoteState(row: any, nowMs: number): QuoteState {
  for (const k of QUOTE_CLOCK_KEYS) {
    const raw = row?.[k]
    if (raw == null || raw === '') continue
    if (typeof raw !== 'string' || !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(raw)) return { kind: 'invalid' }
    const at = Date.parse(raw)
    if (!Number.isFinite(at)) return { kind: 'invalid' }
    if (at > nowMs + QUOTE_SKEW_MS) return { kind: 'future' }
    const minutes = Math.max(0, Math.floor((nowMs - at) / 60_000))
    const text = minutes < 1 ? 'just now' : minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : `${Math.floor(minutes / 1440)}d ago`
    return { kind: 'aged', text, stale: nowMs - at > QUOTE_FRESH_MS }
  }
  return { kind: 'unpublished' }
}
function quoteStateLine(q: QuoteState): string {
  if (q.kind === 'unpublished') return 'quote time not published'
  if (q.kind === 'invalid') return 'quote time unreadable'
  if (q.kind === 'future') return 'quote time needs review'
  return q.stale ? `quote ${q.text} · stale` : `quote ${q.text}`
}
/** Rows whose stop distance and loss at stop should not be read as current (the sheet states it in words too). */
function quoteQualified(rows: any[], nowMs: number): string[] {
  // An unpublished clock is stated once above the table; it is not a fact about each row here.
  return rows.filter(p => { const q = rowQuoteState(p, nowMs); return q.kind === 'future' || q.kind === 'invalid' || (q.kind === 'aged' && q.stale) })
    .map(p => `${p.symbol ?? 'symbol unavailable'} · ${quoteStateLine(rowQuoteState(p, nowMs))}`)
}

/** Board 15: KPI row + one positions table with the stop source per position (CIO record only). */
export function W7RiskExposure({ data, onDrill: _onDrill }: { data: any, onDrill: (ctx: DrillContext) => void }) {
  const positions = data.positions || {}, stops = data.stops || {}, summary = positions
  const allRows: any[] = (positions.rows || []).filter((p: any) => !isDeadCusipHolding({
    symbol: p?.symbol,
    current_price: p?.current_price ?? p?.price,
    market_value: p?.market_value,
  }))
  const hasCounted = allRows.some(p => typeof p.counted === 'boolean')
  const counted = hasCounted ? allRows.filter(p => p.counted) : allRows
  const notCounted = hasCounted ? allRows.filter(p => !p.counted) : []
  const [showAll, setShowAll] = useState(false)
  const rows = [...counted, ...(showAll ? notCounted : [])]
  // PR-012: render-time clock for the per-row quote state. Nothing here refreshes a price.
  const nowMs = Date.now()
  const quotePublished = rows.some(p => rowQuoteState(p, nowMs).kind !== 'unpublished')
  const qualified = quoteQualified(rows, nowMs)
  const detail = useW7Detail()
  const key = (p: any) => `position:${p.account_id || p.account}:${p.symbol}`
  const selected = allRows.find(p => key(p) === detail.selected)
  const bd = summary.stop_breakdown || null
  const n = (cat: string) => bd?.[cat]?.count ?? counted.filter(p => stopCategory(p) === cat).length
  // LQ-20261107-1837 (C4): the headline unprotected count is cio_truth's `stops.unprotected_count`, and its value
  // is the one summed over the SAME rows (`positions.unprotected_counted_value_usd`). Re-adding `none + planned`
  // here was a second calculation of the same figure that could drift from the number Home and Health print.
  const unprotected = unprotectedFact(data)
  const filledRows: any[] = stops.filled_awaiting_sync || counted.filter(p => stopCategory(p) === 'filled')
  const crossed: any[] = stops.awaiting_fill || []
  const awaiting = [...filledRows, ...crossed]
  const unknown = counted.filter(p => stopCategory(p) === 'unknown')
  const restingLoss = typeof summary.loss_at_resting_stops_usd === 'number' ? summary.loss_at_resting_stops_usd : null
  // OBS-R1 (operator, live Chrome 2026-11-14): the card read "$14,793 · 0 active, 8 pending activation · active
  // stops only Not available" — a HYPOTHETICAL resting-order scenario spliced to the ACTIVE-stop figure on one
  // line, the scenario summed over held shares instead of the quantity each broker order actually covers, and
  // "pending activation" named with no broker order state behind it. Two figures now, each labelled as what it
  // measures; the counts and the value-with-no-stop card are unchanged. Nothing is recomputed on this page: the
  // covered quantity arrives as `resting_loss_coverage`, the broker states as `stops.pending_broker_states`.
  const activeCount = n('active'), pendingCount = n('pending_activation'), restingCount = activeCount + pendingCount
  const activeLoss = typeof summary.loss_at_stop_usd === 'number' ? summary.loss_at_stop_usd : null
  const qtyText = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? String(v) : 'quantity not published'
  const coverageText = ((): string => {
    const cov = summary.resting_loss_coverage
    if (!cov || typeof cov !== 'object') return 'coverage basis not published'
    const shortfalls: any[] = Array.isArray(cov.shortfalls) ? cov.shortfalls.filter((s: any) => s && s.symbol) : []
    const unknownQty: any[] = Array.isArray(cov.qty_not_published) ? cov.qty_not_published : []
    const lead = shortfalls.length
      ? `covered quantity basis — ${shortfalls.map(s => `${s.symbol} ${qtyText(s.covered)} of ${qtyText(s.held)} held covered`).join('; ')}`
      : unknownQty.length ? 'covered quantity basis' : 'covered quantity basis — every resting order covers its whole holding'
    const tail = unknownQty.length
      ? `; order quantity not published for ${unknownQty.join(', ')}, so the held quantity was used for ${unknownQty.length === 1 ? 'that row' : 'those rows'}`
      : ''
    return lead + tail
  })()
  const pendingStates = !pendingCount ? '' : (() => {
    const states: any[] = Array.isArray(stops.pending_broker_states) ? stops.pending_broker_states.filter((s: any) => s && s.status) : []
    if (!states.length) return ' (broker order state not published)'
    return ` (broker ${states.length === 1 ? 'state' : 'states'} ${states.map(s => typeof s.count === 'number' && s.count !== pendingCount ? `${s.status} × ${s.count}` : String(s.status)).join(', ')})`
  })()
  // OBS-R2: the two clocks describe different books when the stop read predates the positions snapshot. One shared
  // rule (lib/stopReconciliation) states which; the clocks line never prints an unexplained pair.
  const rec = stopReconciliation({ positionsAsOf: positions.as_of, stopsAsOf: stops.as_of })
  const stopClock = stops.last_broker_read_label ? `last broker read ${stops.last_broker_read_label}` : when(stops.as_of)
  const recHeadline = rec.state === 'reconciled' ? 'Reconciled'
    : rec.state === 'unreconciled' ? `Unreconciled since ${stops.last_broker_read_label || when(rec.since)}`
      : 'Reconciliation unknown'
  // R5c (b6): the SAME accessor Portfolio uses, over the cio/pages shape — one computation, one sentence. The
  // account scope is named because this page has no account filter: it always covers every account the read drew.
  const snap = snapshotFacts(data, allRows.map((p: any) => ({ account_id: p.account_id ?? p.account })))
  return <div style={{ display: 'grid', gap: 12 }}>
    <p style={{ margin: 0, color: TOKENS.text[2], fontSize: TYPE.base }} data-testid="snapshot-line">{snap.line}</p>
    <div style={grid} data-testid="risk-kpis">
      <W7Metric label="Loss if every resting stop fills" value={restingLoss != null ? usd(restingLoss) : 'Not available'}
        detail={<span data-testid="risk-kpi-loss">
          {`hypothetical, not a measure of active protection · if all ${restingCount} resting ${restingCount === 1 ? 'stop' : 'stops'} fill at ${restingCount === 1 ? 'its' : 'their'} stop prices · `}
          {`${pctWhy(summary.resting_heat_pct, 'share of book not sent')} of book not sent · `}
          {coverageText}
          {' · price gaps can increase losses'}
        </span>} />
      <W7Metric label="Loss at active stops" value={activeLoss != null ? usd(activeLoss) : 'Not available'}
        detail={<span data-testid="risk-kpi-active-stops">
          {`${activeCount} armed ${activeCount === 1 ? 'stop' : 'stops'}`}
          {activeLoss == null
            ? ' · Not available is not $0: no armed stop has a published loss, so this figure is unmeasured'
            : ` · ${heatWhy(summary.portfolio_heat_pct, 'share of portfolio not sent')} of portfolio not sent`}
          {pendingCount ? ` · ${pendingCount} resting ${pendingCount === 1 ? 'stop is' : 'stops are'} pending activation` : ''}
          {pendingStates}
          {pendingCount ? ` — live at the broker and not yet active, so ${pendingCount === 1 ? 'it belongs' : 'they belong'} to the hypothetical scenario above, not to an active-stop figure` : ''}
        </span>} />
      <W7Metric label="Value with no broker stop" value={money(unprotected.valueUsd)} detail={<span data-testid="risk-kpi-nostop">{unprotected.count == null ? 'Position count unavailable' : `${unprotected.count} counted ${unprotected.count === 1 ? 'position' : 'positions'}`}{n('planned') ? ` · ${n('planned')} with a planned level only` : ''}</span>} />
      <W7Metric label="Largest position" value={summary.largest_name ? `${summary.largest_name.symbol} ${pctWhy(summary.largest_name.pct, '(weight not sent)')}` : 'Not available'} detail={summary.largest_name?.classification_label && summary.largest_name?.limit_pct != null ? `${summary.largest_name.classification_label} · limit ${pct(summary.largest_name.limit_pct)}` : 'Classification and limit not published'} />
      {/* PR-015: two different measured queues, each named with its own through-time. A quote at or below the stop
          is a CROSSING, never a broker fill; with no execution read published the zero is UNKNOWN, not proof. */}
      <W7Metric label="Stops filled / crossed" value={<span data-testid="risk-kpi-awaiting">{awaitingThrough(stops) ? awaiting.length : 'UNKNOWN'}</span>} detail={awaitingDetail(stops, filledRows, crossed)} />
    </div>
    {bd && <p data-testid="risk-stop-breakdown" style={{ margin: 0, color: TOKENS.text[2], fontSize: TYPE.base }}>
      {(['active', 'pending_activation', 'filled', 'unknown', 'planned', 'none'] as StopCategory[]).filter(c => n(c)).map(c => `${n(c)} ${STOP_CATEGORY_LABEL[c].toLowerCase()}`).join(' · ')}
      {stops.position_count != null ? ` — of ${stops.position_count} counted positions` : ''}
    </p>}
    {unknown.length > 0 && <W7Gap>{unknown.map(p => `${p.symbol} · ${p.account_label || 'account unavailable'}`).join(', ')}: a broker stop was read but its state was not recorded. Check it at the broker before relying on it.</W7Gap>}
    <W7Panel title="Positions and stops" testId="risk-positions">
      <p style={{ color: TOKENS.text[2] }}>Positions · {when(positions.as_of)} · Stops · {stopClock}
        <span data-testid="risk-stops-reconciliation" data-reconciliation={rec.state} style={rec.state === 'unreconciled' ? { color: TOKENS.warning } : undefined}>
          {' — '}{recHeadline} — {rec.reason}
        </span>
        {rows.length > 0 && !quotePublished && <span data-testid="risk-quote-absent"> · no per-row quote time is published, so the positions clock is the book’s, not each row’s</span>}</p>
      {positions.gap && <W7Gap>{typeof positions.gap === 'string' ? positions.gap : positions.gap.reason}</W7Gap>}
      {stops.gap && <W7Gap>{typeof stops.gap === 'string' ? stops.gap : stops.gap.reason}</W7Gap>}
      <div className="w7-position-head" style={{ gridTemplateColumns: '80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr)) 128px', gap: 10, color: TOKENS.text[2], fontSize: 11, padding: '8px 0' }}><span>Symbol</span><span>Account</span><span>Shares</span><span>Price</span><span>Stop</span><span>To stop</span><span>Loss at stop</span><span>Stop source</span><span /></div>
      {rows.map((p, i) => { const cat = stopCategory(p); const dist = stopDistancePct(p), loss = stopLossUsd(p)
        return <article key={`${p.account_id || p.account}-${p.symbol}-${i}`} className="w7-position-row" data-stop-state={p.stop_state || 'unknown'} data-stop-category={cat}>
        <b style={mono}>{p.symbol}</b>
        <span>{p.account_label || 'Account name unavailable'}</span>
        <span style={mono}><small className="w7-field-label">Shares </small>{text(p.shares ?? p.quantity)}</span>
        <span style={mono}><small className="w7-field-label">Price </small>{price(p.price)}
          {/* A chip only when the quote is not current: an aged-fresh row needs no mark, and the absence of a per-row
              clock is stated once above the table, not repeated on every row. */}
          {(() => { const q = rowQuoteState(p, nowMs); if (q.kind === 'unpublished' || (q.kind === 'aged' && !q.stale)) return null
            const state = q.kind === 'aged' ? 'stale' : q.kind
            return <small data-testid="risk-quote-state" data-quote-state={state} title={quoteStateLine(q)} style={{ display: 'block', fontWeight: 'normal', color: TOKENS.warning }}>{q.kind === 'aged' ? `stale ${q.text}` : 'needs review'}</small> })()}</span>
        <span style={mono}><small className="w7-field-label">Stop </small>{p.stop_price == null ? 'None' : price(p.stop_price)}</span>
        <span style={mono}><small className="w7-field-label">To stop </small>{dist != null ? pct(dist) : cat === 'filled' ? 'Filled' : '—'}</span>
        <span style={mono}><small className="w7-field-label">Loss at stop </small>{loss != null ? usd(loss) : '—'}</span>
        <span style={{ color: toneColor[STOP_CATEGORY_TONE[cat]] }}><small className="w7-field-label">Stop source </small>{STOP_CATEGORY_LABEL[cat]}</span>
        <button className="w7-position-action" onClick={() => detail.open(key(p))} style={{ minHeight: 44, color: TOKENS.info, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>Review {p.symbol} →</button>
      </article> })}
      {qualified.length > 0 && <W7Gap><span data-testid="risk-quote-qualified">Distance to stop and loss at stop rest on a quote that is not current: {qualified.join('; ')}. The figures are as observed, not refreshed.</span></W7Gap>}
      {notCounted.length > 0 && <button type="button" data-testid="risk-toggle-small" onClick={() => setShowAll(v => !v)} style={{ minHeight: 44, width: '100%', marginTop: 8, color: TOKENS.info, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>
        {showAll ? `Hide ${plural(notCounted.length)} not counted` : `Show ${plural(notCounted.length)} not counted`} (small or unpriced holdings)
      </button>}
      {!allRows.length && !positions.gap && <W7Gap>No positions have been published.</W7Gap>}
    </W7Panel>
    {selected && <W7DetailSheet title={`${selected.symbol} · stop details`} onClose={detail.close}>
      <W7StopDetail selected={selected} nowMs={nowMs} />
    </W7DetailSheet>}
  </div>
}

/** Risk › Exposure stop-detail body. Exported so the sheet's content is rendered by a test without a browser
 *  (the sheet itself is a portal; the body is not).
 *  R5b #1 (2026-11-14, SEV-3 cross-page): AMANX read UNKNOWN on Portfolio ("stop read 210 d old, limit 3 d") while
 *  this sheet read "Planned level · no resting order · State None · Observed Apr 18" with no freshness verdict. The
 *  row here comes from /api/v2/cio/pages and carries no protection verdict, so the freshness is drawn by the SAME
 *  rule Portfolio uses — `stopReadFreshness` in lib/portfolioV002 reads the same clock (`stop_captured_at`) and the
 *  same limit (STOP_READ_MAX_AGE_MS, 15 m in session / 72 h off-hours). Nothing is recomputed on this page. */
export function W7StopDetail({ selected, nowMs = Date.now() }: { selected: any, nowMs?: number }) {
  const f = stopReadFreshness(selected, nowMs)
  return <>
    <p>{selected.account_label || 'Account name unavailable'}</p>
    <div style={line}><span>Stop</span><b>{STOP_CATEGORY_LABEL[stopCategory(selected)]}</b></div>
    <div style={line}><span>Stop price</span><b style={mono}>{selected.stop_price == null ? 'None' : price(selected.stop_price)}</b></div>
    <div style={line}><span>Price</span><b style={mono}>{price(selected.price)}</b></div>
    <div style={line}><span>Quote time</span><b data-testid="risk-sheet-quote-state">{quoteStateLine(rowQuoteState(selected, nowMs))}</b></div>
    <div style={line}><span>To stop</span><b style={mono}>{stopDistancePct(selected) != null ? pct(stopDistancePct(selected)) : '—'}</b></div>
    <div style={line}><span>Loss at stop</span><b style={mono}>{stopLossUsd(selected) != null ? usd(stopLossUsd(selected)) : '—'}</b></div>
    <div style={line}><span>Source</span><b>{selected.stop_source === 'broker_resting' && !['active', 'pending_activation'].includes(stopCategory(selected)) ? 'Broker stop order' : sourceLabel[selected.stop_source] || 'Source unavailable'}</b></div>
    <div style={line}><span>State</span><b>{stateLabel[selected.stop_state] || 'State not recorded'}</b></div>
    <p>Observed {when(selected.stop_captured_at || selected.stop_evidence?.as_of)}</p>
    {stopCategory(selected) === 'pending_activation' && <W7Gap>This stop is resting at the broker but awaiting activation. It does not provide active protection yet.</W7Gap>}
    {stopCategory(selected) === 'filled' && <W7Gap>The broker stop filled. The sale is not in the holdings sync yet, so the position still shows here.</W7Gap>}
    {stopCategory(selected) === 'planned' && <W7Gap>This is a planned level only. No order is resting at the broker.</W7Gap>}
    {/* The freshness verdict the Portfolio page applies, drawn here instead of leaving "Observed Apr 18" to read as
        current. It is the same rule over the same read clock; a stale read makes the served state last-known. */}
    <div style={line}><span>Stop read</span><b data-testid="risk-sheet-freshness" data-freshness={f.kind}
      data-served-stale={f.servedStale == null ? undefined : String(f.servedStale)}
      data-agrees={f.agreesWithServed == null ? undefined : String(f.agreesWithServed)}
      style={f.kind === 'fresh' ? undefined : { color: TOKENS.warning }}>{f.line}</b></div>
    {f.kind === 'fresh' && <p style={{ color: TOKENS.text[2] }}>Freshness is the same limit Portfolio applies to this row's stop read, not a separate Risk calculation.</p>}
    <Link to="/portfolio?tab=Stop%20Management" style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 20 }}>Stop review and advice →</Link>
    <Link to={`/trading?tab=Open+Trades&symbol=${encodeURIComponent(selected.symbol)}`} style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 8 }}>Review position in Trading →</Link>
  </>
}

export function W7RiskConcentration({ data }: { data: any }) {
  const model = data.positions || {}, rows: any[] = model.concentration || []
  return <W7Panel title="Concentration">
    <W7PolicyLimits policy={data.concentration_policy} />
    {rows.map((p, i) => <div key={p.symbol || i} style={line}><b style={mono}>{p.symbol}</b><span style={mono}>{usd(p.value_usd)} · {pctWhy(p.pct, 'weight not sent')}</span>
      {p.classification_label && p.limit_pct != null ? <span style={{ flexBasis: '100%' }}>{p.classification_label} · limit {pct(p.limit_pct)} · warning at {pctWhy(p.near_limit_pct, 'no warning level published')}{p.status_label ? ` · ${p.status_label}` : ''}</span> : <W7Gap>{(typeof p.gap === 'string' ? p.gap : p.gap?.reason) || 'Classification and limit have not been published for this position.'}</W7Gap>}
    </div>)}
    {!rows.length && <W7Gap>Concentration has not been published on the current portfolio basis.</W7Gap>}
    <Link to="/portfolio?tab=Look-through" style={linkStyle}>Underlying stocks, sectors and industries →</Link>
  </W7Panel>
}
export function W7RiskRegime({ data }: { data: any }) {
  const regime = data.regime || {}
  return <W7Panel title="CIO market regime">
    <p><b>{text(regime.label, 'Not classified')}</b> · VIX {text(regime.vix)}</p>
    <p style={{ color: TOKENS.text[2] }}>Published {when(regime.as_of)}{regime.stale ? ' · Refresh overdue' : ''}</p>
    {regime.gap && <W7Gap>{typeof regime.gap === 'string' ? regime.gap : regime.gap.reason}</W7Gap>}
    <Link style={linkStyle} to="/watch?tab=sectors">Sector trends and leaders →</Link>
  </W7Panel>
}
export function W7RiskCorrelation({ data, error }: { data: any, error?: unknown }) {
  const matrix = data?.correlation_matrix || {}
  const symbols = Object.keys(matrix)
  return <W7Panel title="Correlation">
    {data?.as_of && <p style={{ color: TOKENS.text[2] }}>Published {when(data.as_of)}</p>}
    {symbols.map((a, i) => <div key={a} style={line}><b>{a}</b><div>{symbols.slice(i + 1).map(b => <div key={b}>{b} · {matrix[a]?.[b] == null ? <span data-testid="risk-corr-no-value">no value yet (under 20 shared trading days or a flat price) <Explain term="correlation_no_value" fallback={CORR_NO_VALUE} /></span> : String(matrix[a][b])}</div>)}</div></div>)}
    {!symbols.length && <W7Gap>{error ? 'Correlation could not be loaded.' : 'No correlation measurement has been published.'}</W7Gap>}
    <Link style={linkStyle} to="/strategy?tab=planner">Review in Strategy →</Link>
  </W7Panel>
}
/** Risk → Recovery (piece D, mockup approved 2026-11-06): the recovery_cases projection from GET /api/v2/recovery.
 *  A server that predates the projection still shows the legacy recovery-watch rows, labelled as such. */
export function W7RiskRecovery({ data, error, stale }: { data: any, error?: unknown, stale?: boolean }) {
  const [params, setParams] = useSearchParams()
  const projection = recoveryProjection(data, error)
  const gates = useCaseGates(projection.cases)
  const rows: any[] = data?.items || []
  const select = (key: string) => { const next = new URLSearchParams(params); next.set('case', key); setParams(next, { replace: true }) }
  const selectedKey = params.get('case') ?? ([...projection.cases].sort(byImpact)[0]?.key ?? null)
  return <div style={{ display: 'grid', gap: 12 }}>
    <RecoveryListView projection={projection} sourceUnavailable={!!error || !!stale} selectedKey={selectedKey} onSelect={select}
      gate={gates.gate} onReview={gates.review} legacyCount={Array.isArray(data?.items) ? data.items.length : null} />
    {projection.state === 'missing' && <W7Panel title="Recovery watch (legacy)">
      {rows.map((r, i) => <div key={r.symbol || i} style={line}><b>{r.symbol}</b><span>{r.account_label}</span><p style={{ flexBasis: '100%', margin: 0 }}>{r.analyst_verdict || r.reason || 'Review evidence on the Re-Entry desk.'}</p><Link to={`/portfolio/re-entry?symbol=${encodeURIComponent(r.symbol || '')}`} style={linkStyle}>Review recovery evidence →</Link></div>)}
      {!rows.length && <W7Gap>{error ? 'Recovery watch could not be loaded.' : 'No recovery evidence has been published.'}</W7Gap>}
    </W7Panel>}
  </div>
}

export function W7RiskStyles() { return <style>{`.w7-position-head{display:grid}.w7-position-row{display:grid;grid-template-columns:80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr)) 128px;gap:10px;padding:8px 0;border-top:1px solid var(--border-subtle);align-items:center;font-size:12px}.w7-field-label{display:none}@media(max-width:1000px){.w7-position-head{display:none}.w7-position-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:12px 0;align-items:start}.w7-position-action{grid-column:1/-1}.w7-field-label{display:block;color:var(--text-2);font:11px var(--font-sans)}}`}</style> }

/** Design risk/v002: the "Market risk" tab — tier card, contributors, nine categories, your book vs budget, probabilities,
 *  score history, alert episodes, and the kept legacy regime panel as the last block. Advisory only; no size, order or
 *  stop control. A tier the engine did not compute renders NOT EVALUATED, never a guess. */
export function W7RiskMarketRisk({ data, mr: resp, error }: { data: any, mr: any, error?: unknown }) {
  const mr: MarketRisk | null = unwrapMarketRisk(resp)
  const [ack, setAck] = useState<string | null>(null)
  const shown = mr && mr.state !== 'not_evaluated' ? renderedTier(mr.tier, mr.score, mr.uplift) : mr?.tier
  const tone = mr ? (mr.state === 'not_evaluated' ? 'neutral' : tierTone(shown)) : 'neutral'
  const tv = toneVars(tone)
  const chip = (state: string) => {
    const t = state === 'STRESS' ? 'danger' : state === 'WARN' ? 'warning' : state === 'CALM' ? 'success' : 'neutral'
    const v = toneVars(t)
    return <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '0.04em', borderRadius: RADIUS.pill, padding: '3px 8px', color: TOKENS.bg[0], background: t === 'neutral' ? TOKENS.text[3] : v.color }}>{state}</span>
  }
  const acknowledge = async () => {
    try {
      const r = await fetch('/api/v2/market-risk/ack', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ episode_id: mr?.episode?.id ?? null, episode_tier: mr?.episode?.tier ?? null }) })
      const j: any = await r.json().catch(() => ({}))
      setAck(r.ok ? `Acknowledged ${shortTime(new Date().toISOString())}` : `Not recorded: ${j?.error ?? `HTTP ${r.status}`}${j?.detail ? ` — ${j.detail}` : ''}`)
    } catch (e) { setAck(`Not recorded: ${String(e)}`) }
  }
  const row: CSSProperties = { display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'baseline', minHeight: 34, borderTop: `1px solid ${TOKENS.borderSubtle}`, fontSize: TYPE.base }
  return <GlossaryProvider terms={mr?.glossary ?? {}}>
    <W7Panel title="Market risk" testId="risk-market-risk">
      {error ? <W7Gap>Market risk unavailable: {String(error)}</W7Gap> : null}
      {!mr && !error && <p style={{ color: TOKENS.text[2] }}>Loading…</p>}
      {mr && <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 12, borderRadius: RADIUS.lg, background: tv.bg, border: `1px solid ${tv.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span data-testid="risk-market-risk-tier" style={{ fontSize: TYPE.base, fontWeight: 800, letterSpacing: '0.04em', color: TOKENS.bg[0], background: tone === 'neutral' ? TOKENS.text[3] : tv.color, borderRadius: RADIUS.pill, padding: '4px 10px' }}>{mr.state === 'not_evaluated' ? 'NOT EVALUATED' : shown}</span>
          <ShadowTag mr={mr} testid="risk-market-risk-shadow" />
          {/* LQ-20261107-1837 (C4): one precision for the market-risk score, the same as Home's ("44.2", not 44). */}
          <span style={{ ...mono, fontSize: TYPE.xl, fontWeight: 700, color: TOKENS.text[0] }}>{scoreText(mr.score)}<span style={{ fontSize: TYPE.md, color: TOKENS.text[2] }}>/100</span></span>
          {mr.confirming && <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{mr.confirming.n} of {mr.confirming.of} categories confirm</span>}
        </div>
        <p style={{ margin: 0, color: TOKENS.text[2], fontSize: TYPE.base }}>
          {mr.state === 'not_evaluated' ? mr.reason : <>{episodeLine(mr) || 'no open episode'} · evaluated {shortTime(mr.as_of)}{mr.state === 'stale' ? ' · STALE' : ''}</>}
        </p>
        {mr.deescalates_if && <p style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[2] }}><b style={{ color: TOKENS.text[0] }}>De-escalates if</b> {mr.deescalates_if}</p>}
        {bannerVisible(mr) && !mr.episode?.acknowledged_at && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" data-testid="risk-market-risk-ack" onClick={acknowledge} disabled={!!shadowMarker(mr)} style={{ minHeight: 44, padding: '0 20px', borderRadius: RADIUS.md, border: 0, background: tv.color, color: TOKENS.bg[0], fontSize: TYPE.md, fontWeight: 800, cursor: shadowMarker(mr) ? 'default' : 'pointer', opacity: shadowMarker(mr) ? 0.7 : 1 }}>{shadowMarker(mr) ? `${shadowMarker(mr).startsWith('SHADOW') ? 'Shadow' : 'Carried'}: nothing to acknowledge` : 'Acknowledge'}</button>
          <Link to="/risk?tab=exposure" style={{ ...linkStyle, minHeight: 44, display: 'inline-flex', alignItems: 'center', padding: '0 14px', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>Review stops</Link>
        </div>}
        {ack && <p role="status" style={{ margin: 0, fontSize: TYPE.base, color: ack.startsWith('Not recorded') ? toneVars('warning').color : toneVars('success').color }}>{ack}</p>}
        <p style={{ margin: 0, fontSize: TYPE.sm, color: TOKENS.text[3] }}>Advisory. No order, size or stop level is implied.</p>
      </div>}
    </W7Panel>

    {mr && mr.contributors.length > 0 && <W7Panel title="Contributors" testId="risk-market-risk-contributors">
      {mr.contributors.slice(0, 5).map((c, i) => <div key={i} style={row}><span>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}{c.as_of ? ` · ${shortTime(c.as_of)}` : ''}</span> : null}</span><span style={{ ...mono, color: tv.color, whiteSpace: 'nowrap' }}>{pointsToScore(c.points)} <Explain term="pts_to_score" /></span></div>)}
      {mr.uplift && <div style={{ ...row, color: TOKENS.text[2] }}><span>{mr.uplift.note ?? `Market ${mr.uplift.market_score ?? '—'} → ${mr.tier} after portfolio vulnerability ${mr.uplift.vulnerability ?? '—'}`}</span><span style={{ ...mono, color: TOKENS.text[0] }}>= {scoreText(mr.score)}</span></div>}
      {contributorsDisagreeWithScore(mr) && <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: toneVars('warning').color }}>Contributors sum to {scoreText(pointsSum(mr))}, score is {scoreText(mr.score)} — the engine owes an explanation line.</p>}
    </W7Panel>}

    {mr && mr.categories.length > 0 && <W7Panel title="Nine categories" testId="risk-market-risk-categories">
      {mr.categories.map((c, i) => {
        if (!c || typeof c !== 'object') return <W7Gap key={i}>Category evidence could not be read; its state is unavailable.</W7Gap>
        const category = c as typeof c & { score?: number | null; category?: string }
        const name = (typeof c.name === 'string' && c.name.trim()) || (typeof category.category === 'string' && category.category.replace(/_/g, ' ')) || 'Category name unavailable'
        const score = typeof category.score === 'number' && Number.isFinite(category.score) ? category.score : null
        return <div key={i} data-testid="risk-market-risk-category" style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 0', borderTop: `1px solid ${TOKENS.borderSubtle}`, minWidth: 0 }}>
          {/* Keep the name and state in one header: the global phone rule collapses inline grids. */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontWeight: 700 }}>{name}</span>{chip(c.state || 'UNKNOWN')}
          </div>
          {c.state === 'UNKNOWN'
            ? <div data-testid="risk-market-risk-category-why" style={{ color: TOKENS.text[2], fontSize: TYPE.base, overflowWrap: 'anywhere' }}>No reading: {c.detail ? plainEngineReason(c.detail) : 'the engine gave no reason'} — adds 0 points <Explain term="missing_inputs" detail={c.detail ? `Engine reason: ${c.detail}` : null} /></div>
            : c.detail && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base, overflowWrap: 'anywhere' }}>{c.detail}</div>}
          {score != null && <div style={{ color: TOKENS.text[3], fontSize: TYPE.sm }}>Category score {score}/100{c.state === 'CALM' && score > 0 ? ' — below this category’s warning level.' : ''}</div>}
          {c.weight != null && c.weight < 1 && c.state !== 'UNKNOWN' && <div style={{ color: TOKENS.text[3], fontSize: TYPE.sm }}>Weight {c.weight}</div>}
        </div>
      })}
      <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: TOKENS.text[3] }}>UNKNOWN = a source not read since its stale window; never counted as calm.</p>
    </W7Panel>}

    {mr && <W7Panel title="Your book vs budget" testId="risk-market-risk-book">
      {/* book.budgets contains names only; budgets_detail is the numeric account-scoped API join Home uses. */}
      {(mr.budgets_detail ?? []).map((b, i) => {
        if (!b || typeof b !== 'object') return <W7Gap key={i}>A budget row could not be read; its numbers are unavailable.</W7Gap>
        const actual = typeof b.actual === 'number' && Number.isFinite(b.actual) ? b.actual : null
        const limit = typeof b.limit === 'number' && Number.isFinite(b.limit) ? b.limit : null
        const ratio = actual != null && limit != null && limit > 0 ? actual / limit : null
        const t = ratio == null ? 'warning' : ratio >= 1 ? 'danger' : ratio >= 0.9 ? 'warning' : 'success'
        const unit = b.unit || '%'
        const account = (typeof b.account_label === 'string' && b.account_label.trim()) || 'Account scope unavailable'
        const name = budgetLabel(b.budget)
        return <div key={i} data-testid="risk-market-risk-budget" style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8, fontSize: TYPE.base }}>
            <span><b>{account}</b> · {name}</span>
            <span style={{ ...mono, color: toneVars(t).color }}>{actual == null ? 'Actual unavailable' : `${actual}${unit}`} / {limit == null ? 'Limit unavailable' : `${limit}${unit} limit`}</span>
          </div>
          {ratio != null ? <div role="img" aria-label={`${account} ${name}: ${actual}${unit} against ${limit}${unit} limit`} data-testid="risk-market-budget-bar" style={{ height: 8, borderRadius: RADIUS.sm, background: TOKENS.bg[3] }}>
            <div style={{ width: `${Math.max(0, Math.min(100, ratio * 100))}%`, height: 8, borderRadius: RADIUS.sm, background: toneVars(t).color }} />
          </div> : <div style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{limit === 0 ? 'This limit is zero; a percentage bar is not defined.' : 'A bar is unavailable until both numbers and a positive limit are supplied.'}</div>}
        </div>
      })}
      {!mr.budgets_detail?.length && <W7Gap>Budget numbers unavailable{mr.book?.budgets?.length ? ` for the named breaches: ${mr.book.budgets.map(b => budgetLabel(b.budget)).join(', ')}` : ''}.</W7Gap>}
      {mr.book?.positions?.length ? <p style={{ margin: '8px 0 0', fontSize: TYPE.base, color: TOKENS.text[2] }}>Driving positions: {mr.book.positions.map(p => `${p.symbol}${p.stop_distance_pct != null ? ` stop ${fmtPct(p.stop_distance_pct / 100)} below` : ''}${p.note ? ` (${p.note})` : ''}`).join(' · ')}. Symbols and stop distance only; the limits are yours.</p> : null}
    </W7Panel>}

    {mr?.probabilities?.length ? <W7Panel title="Probabilities" testId="risk-market-risk-probabilities">
      <div style={{ overflowX: 'auto' }}>
        <table style={{ ...mono, borderCollapse: 'collapse', fontSize: TYPE.base, minWidth: 460, width: '100%', color: TOKENS.text[1] }}>
          <thead><tr style={{ color: TOKENS.text[2] }}><th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${TOKENS.border}` }}>Horizon</th>{['Move ≥1.5%', 'Move ≥3%', 'Up', 'Down', 'VIX +20%', 'Trend continues'].map(h => <th key={h} style={{ padding: '6px 8px', borderBottom: `1px solid ${TOKENS.border}` }}>{h}</th>)}</tr></thead>
          <tbody>{mr.probabilities.map((r, i) => <tr key={i}><td style={{ padding: '6px 8px' }}>{r.horizon}</td>{[r.move_1_5, r.move_3, r.up, r.down, r.vix_up_20, r.trend_continues].map((v, j) => <td key={j} style={{ padding: '6px 8px', textAlign: 'center' }}>{fmtPct(v)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: TOKENS.text[3] }}>Empirical frequencies by tier × category state over the scenario library; analogs explain, never score.</p>
    </W7Panel> : null}

    {mr?.history?.length ? <W7Panel title={`Score, last ${mr.history.length} sessions`} testId="risk-market-risk-history">
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 96, borderBottom: `1px solid ${TOKENS.border}`, paddingBottom: 4 }}>
        {mr.history.map((h, i) => <div key={i} title={`${shortTime(h.as_of)} · ${h.tier} ${h.score}${h.sent ? ` · ${h.sent} sent` : ''}`} style={{ flex: 1, height: `${Math.max(2, Math.min(100, h.score))}%`, background: toneVars(tierTone(h.tier)).color, borderRadius: RADIUS.sm }} />)}
      </div>
      <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: TOKENS.text[3] }}>Bars coloured by tier; alerts sent are in each bar's tooltip.</p>
    </W7Panel> : null}

    {mr?.episode && <W7Panel title="Alert episodes" testId="risk-market-risk-episodes">
      <div style={row}><span>{chip(mr.episode.tier)} {shortTime(mr.episode.opened_at)}{mr.episode.repeats != null ? ` · ${mr.episode.repeats} repeats` : ''}</span><span style={{ color: mr.episode.acknowledged_at ? TOKENS.text[2] : tv.color, fontSize: TYPE.base }}>{mr.episode.acknowledged_at ? `acknowledged ${shortTime(mr.episode.acknowledged_at)}` : (mr.episode.status ?? 'open').toLowerCase()}</span></div>
    </W7Panel>}

    <div data-testid="risk-market-risk-legacy-regime"><W7RiskRegime data={data} /></div>
  </GlossaryProvider>
}
