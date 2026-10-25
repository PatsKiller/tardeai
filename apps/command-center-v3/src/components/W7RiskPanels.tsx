import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { DrillContext } from './DetailDrawer'
import { W7Gap, W7Metric, W7Panel, W7PolicyLimits, grid, line, linkStyle, mono, pct, text, usd, when } from './W7PagePanels'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'
import { STOP_CATEGORY_LABEL, STOP_CATEGORY_TONE, stopCategory, stopDistancePct, stopLossUsd, symbolList, type StopCategory } from '../lib/stopDisplay'

const stateLabel: Record<string, string> = { active: 'Active', pending_activation: 'Pending activation', pending: 'Pending activation', filled: 'Filled', none: 'None' }
const sourceLabel: Record<string, string> = { broker: 'Broker resting', broker_resting: 'Broker resting', planned: 'Planned', none: 'None', confirmed: 'Operator confirmed' }
const toneColor = { good: TOKENS.success, warn: TOKENS.warning, bad: TOKENS.danger }
const plural = (n: number) => `${n} ${n === 1 ? 'position' : 'positions'}`
const money = (v: number | null) => v == null ? 'Not available' : usd(v)
const price = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? `$${v.toLocaleString('en-US', { maximumFractionDigits: 4 })}` : 'Not available'

/** Board 15: KPI row + one positions table with the stop source per position (CIO record only). */
export function W7RiskExposure({ data, onDrill: _onDrill }: { data: any, onDrill: (ctx: DrillContext) => void }) {
  const positions = data.positions || {}, stops = data.stops || {}, summary = positions
  const allRows: any[] = positions.rows || []
  const hasCounted = allRows.some(p => typeof p.counted === 'boolean')
  const counted = hasCounted ? allRows.filter(p => p.counted) : allRows
  const notCounted = hasCounted ? allRows.filter(p => !p.counted) : []
  const [showAll, setShowAll] = useState(false)
  const rows = [...counted, ...(showAll ? notCounted : [])]
  const detail = useW7Detail()
  const key = (p: any) => `position:${p.account_id || p.account}:${p.symbol}`
  const selected = allRows.find(p => key(p) === detail.selected)
  const bd = summary.stop_breakdown || null
  const n = (cat: string) => bd?.[cat]?.count ?? counted.filter(p => stopCategory(p) === cat).length
  const noStop = bd ? [bd.none, bd.planned] : null
  const noStopValue = noStop ? (noStop.every((g: any) => typeof g?.value_usd === 'number') ? noStop.reduce((a: number, g: any) => a + g.value_usd, 0) : null) : null
  const filledRows: any[] = stops.filled_awaiting_sync || counted.filter(p => stopCategory(p) === 'filled')
  const crossed: any[] = stops.awaiting_fill || []
  const awaiting = [...filledRows, ...crossed]
  const unknown = counted.filter(p => stopCategory(p) === 'unknown')
  const restingLoss = typeof summary.loss_at_resting_stops_usd === 'number' ? summary.loss_at_resting_stops_usd : null
  return <div style={{ display: 'grid', gap: 12 }}>
    <div style={grid} data-testid="risk-kpis">
      {restingLoss != null
        ? <W7Metric label="Loss if every resting stop fills" value={usd(restingLoss)} detail={<span data-testid="risk-kpi-loss">{pct(summary.resting_heat_pct)} of book · {n('active')} active, {n('pending_activation')} pending activation · active stops only {usd(summary.loss_at_stop_usd)} · price gaps can increase losses</span>} />
        : <W7Metric label="Loss if every active stop fills" value={usd(summary.loss_at_stop_usd)} detail={`${pct(summary.portfolio_heat_pct)} of portfolio · price gaps can increase losses`} />}
      {bd
        ? <W7Metric label="Value with no broker stop" value={money(noStopValue)} detail={<span data-testid="risk-kpi-nostop">{n('none') + n('planned')} positions{n('planned') ? ` · ${n('planned')} with a planned level only` : ''}</span>} />
        : <W7Metric label="Value without active protection" value={usd(summary.unprotected_value_usd)} detail={stops.unprotected_count == null ? 'Position count unavailable' : `${stops.unprotected_count} positions`} />}
      <W7Metric label="Largest position" value={summary.largest_name ? `${summary.largest_name.symbol} ${pct(summary.largest_name.pct)}` : 'Not available'} detail={summary.largest_name?.classification_label && summary.largest_name?.limit_pct != null ? `${summary.largest_name.classification_label} · limit ${pct(summary.largest_name.limit_pct)}` : 'Classification and limit not published'} />
      <W7Metric label="Awaiting fill" value={<span data-testid="risk-kpi-awaiting">{awaiting.length}</span>} detail={awaiting.length ? `${symbolList(awaiting)} · ${filledRows.length ? 'stop filled · awaiting holdings sync' : 'mark at or below the stop · fill not confirmed'}` : 'No stop has filled or been crossed.'} />
    </div>
    {bd && <p data-testid="risk-stop-breakdown" style={{ margin: 0, color: TOKENS.text[2], fontSize: TYPE.base }}>
      {(['active', 'pending_activation', 'filled', 'unknown', 'planned', 'none'] as StopCategory[]).filter(c => n(c)).map(c => `${n(c)} ${STOP_CATEGORY_LABEL[c].toLowerCase()}`).join(' · ')}
      {stops.position_count != null ? ` — of ${stops.position_count} counted positions` : ''}
    </p>}
    {unknown.length > 0 && <W7Gap>{unknown.map(p => `${p.symbol} · ${p.account_label || 'account unavailable'}`).join(', ')}: a broker stop was read but its state was not recorded. Check it at the broker before relying on it.</W7Gap>}
    <W7Panel title="Positions and stops" testId="risk-positions">
      <p style={{ color: TOKENS.text[2] }}>Positions · {when(positions.as_of)} · Stops · {stops.last_broker_read_label ? `last broker read ${stops.last_broker_read_label}` : when(stops.as_of)}</p>
      {positions.gap && <W7Gap>{typeof positions.gap === 'string' ? positions.gap : positions.gap.reason}</W7Gap>}
      {stops.gap && <W7Gap>{typeof stops.gap === 'string' ? stops.gap : stops.gap.reason}</W7Gap>}
      <div className="w7-position-head" style={{ gridTemplateColumns: '80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr)) 128px', gap: 10, color: TOKENS.text[2], fontSize: 11, padding: '8px 0' }}><span>Symbol</span><span>Account</span><span>Shares</span><span>Price</span><span>Stop</span><span>To stop</span><span>Loss at stop</span><span>Stop source</span><span /></div>
      {rows.map((p, i) => { const cat = stopCategory(p); const dist = stopDistancePct(p), loss = stopLossUsd(p)
        return <article key={`${p.account_id || p.account}-${p.symbol}-${i}`} className="w7-position-row" data-stop-state={p.stop_state || 'unknown'} data-stop-category={cat}>
        <b style={mono}>{p.symbol}</b>
        <span>{p.account_label || 'Account name unavailable'}</span>
        <span style={mono}><small className="w7-field-label">Shares </small>{text(p.shares ?? p.quantity)}</span>
        <span style={mono}><small className="w7-field-label">Price </small>{price(p.price)}</span>
        <span style={mono}><small className="w7-field-label">Stop </small>{p.stop_price == null ? 'None' : price(p.stop_price)}</span>
        <span style={mono}><small className="w7-field-label">To stop </small>{dist != null ? pct(dist) : cat === 'filled' ? 'Filled' : '—'}</span>
        <span style={mono}><small className="w7-field-label">Loss at stop </small>{loss != null ? usd(loss) : '—'}</span>
        <span style={{ color: toneColor[STOP_CATEGORY_TONE[cat]] }}><small className="w7-field-label">Stop source </small>{STOP_CATEGORY_LABEL[cat]}</span>
        <button className="w7-position-action" onClick={() => detail.open(key(p))} style={{ minHeight: 44, color: TOKENS.info, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>Review {p.symbol} →</button>
      </article> })}
      {notCounted.length > 0 && <button type="button" data-testid="risk-toggle-small" onClick={() => setShowAll(v => !v)} style={{ minHeight: 44, width: '100%', marginTop: 8, color: TOKENS.info, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>
        {showAll ? `Hide ${plural(notCounted.length)} not counted` : `Show ${plural(notCounted.length)} not counted`} (small or unpriced holdings)
      </button>}
      {!allRows.length && !positions.gap && <W7Gap>No positions have been published.</W7Gap>}
    </W7Panel>
    {selected && <W7DetailSheet title={`${selected.symbol} · stop details`} onClose={detail.close}>
      <p>{selected.account_label || 'Account name unavailable'}</p>
      <div style={line}><span>Stop</span><b>{STOP_CATEGORY_LABEL[stopCategory(selected)]}</b></div>
      <div style={line}><span>Stop price</span><b style={mono}>{selected.stop_price == null ? 'None' : price(selected.stop_price)}</b></div>
      <div style={line}><span>Price</span><b style={mono}>{price(selected.price)}</b></div>
      <div style={line}><span>To stop</span><b style={mono}>{stopDistancePct(selected) != null ? pct(stopDistancePct(selected)) : '—'}</b></div>
      <div style={line}><span>Loss at stop</span><b style={mono}>{stopLossUsd(selected) != null ? usd(stopLossUsd(selected)) : '—'}</b></div>
      <div style={line}><span>Source</span><b>{selected.stop_source === 'broker_resting' && !['active', 'pending_activation'].includes(stopCategory(selected)) ? 'Broker stop order' : sourceLabel[selected.stop_source] || 'Source unavailable'}</b></div>
      <div style={line}><span>State</span><b>{stateLabel[selected.stop_state] || 'State not recorded'}</b></div>
      <p>Observed {when(selected.stop_captured_at || selected.stop_evidence?.as_of)}</p>
      {stopCategory(selected) === 'pending_activation' && <W7Gap>This stop is resting at the broker but awaiting activation. It does not provide active protection yet.</W7Gap>}
      {stopCategory(selected) === 'filled' && <W7Gap>The broker stop filled. The sale is not in the holdings sync yet, so the position still shows here.</W7Gap>}
      {stopCategory(selected) === 'planned' && <W7Gap>This is a planned level only. No order is resting at the broker.</W7Gap>}
      <Link to="/portfolio?tab=Stop%20Management" style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 20 }}>Stop review and advice →</Link>
      <Link to={`/trading?tab=Open+Trades&symbol=${encodeURIComponent(selected.symbol)}`} style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 8 }}>Review position in Trading →</Link>
    </W7DetailSheet>}
  </div>
}

export function W7RiskConcentration({ data }: { data: any }) {
  const model = data.positions || {}, rows: any[] = model.concentration || []
  return <W7Panel title="Concentration">
    <W7PolicyLimits policy={data.concentration_policy} />
    {rows.map((p, i) => <div key={p.symbol || i} style={line}><b style={mono}>{p.symbol}</b><span style={mono}>{usd(p.value_usd)} · {pct(p.pct)}</span>
      {p.classification_label && p.limit_pct != null ? <span style={{ flexBasis: '100%' }}>{p.classification_label} · limit {pct(p.limit_pct)} · warning at {pct(p.near_limit_pct)}{p.status_label ? ` · ${p.status_label}` : ''}</span> : <W7Gap>{(typeof p.gap === 'string' ? p.gap : p.gap?.reason) || 'Classification and limit have not been published for this position.'}</W7Gap>}
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
    {symbols.map((a, i) => <div key={a} style={line}><b>{a}</b><div>{symbols.slice(i + 1).map(b => <div key={b}>{b} · {text(matrix[a]?.[b], 'Not measured')}</div>)}</div></div>)}
    {!symbols.length && <W7Gap>{error ? 'Correlation could not be loaded.' : 'No correlation measurement has been published.'}</W7Gap>}
    <Link style={linkStyle} to="/strategy?tab=planner">Review in Strategy →</Link>
  </W7Panel>
}
export function W7RiskRecovery({ data, error }: { data: any, error?: unknown }) {
  const rows: any[] = data?.items || []
  return <W7Panel title="Recovery watch">
    {rows.map((r, i) => <div key={r.symbol || i} style={line}><b>{r.symbol}</b><span>{r.account_label}</span><p style={{ flexBasis: '100%', margin: 0 }}>{r.analyst_verdict || r.reason || 'Review evidence on the Re-Entry desk.'}</p><Link to={`/portfolio/re-entry?symbol=${encodeURIComponent(r.symbol || '')}`} style={linkStyle}>Review recovery evidence →</Link></div>)}
    {!rows.length && <W7Gap>{error ? 'Recovery watch could not be loaded.' : 'No recovery evidence has been published.'}</W7Gap>}
  </W7Panel>
}

export function W7RiskStyles() { return <style>{`.w7-position-head{display:grid}.w7-position-row{display:grid;grid-template-columns:80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr)) 128px;gap:10px;padding:8px 0;border-top:1px solid var(--border-subtle);align-items:center;font-size:12px}.w7-field-label{display:none}@media(max-width:1000px){.w7-position-head{display:none}.w7-position-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:12px 0;align-items:start}.w7-position-action{grid-column:1/-1}.w7-field-label{display:block;color:var(--text-2);font:11px var(--font-sans)}}`}</style> }
