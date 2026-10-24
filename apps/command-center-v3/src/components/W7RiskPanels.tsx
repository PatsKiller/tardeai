import { Link } from 'react-router-dom'
import type { DrillContext } from './DetailDrawer'
import { W7Gap, W7Metric, W7Panel, grid, line, linkStyle, mono, pct, text, usd, when } from './W7PagePanels'
import { RADIUS, TOKENS } from '../lib/designTokens'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'

const stateLabel: Record<string, string> = { active: 'Active', pending_activation: 'Pending activation', pending: 'Pending activation', filled: 'Filled', none: 'None' }
const sourceLabel: Record<string, string> = { broker: 'Broker resting', broker_resting: 'Broker resting', planned: 'Planned', none: 'None', confirmed: 'Operator confirmed' }

export function W7RiskExposure({ data, onDrill }: { data: any, onDrill: (ctx: DrillContext) => void }) {
  const positions = data.positions || {}, stops = data.stops || {}, summary = positions, capital = data.capital || {}
  const rows: any[] = positions.rows || []
  const detail = useW7Detail()
  const key = (p: any) => `position:${p.account_id || p.account}:${p.symbol}`
  const selected = rows.find(p => key(p) === detail.selected)
  return <div style={{ display: 'grid', gap: 12 }}>
    <div style={grid}>
      <W7Metric label="Loss if every active stop fills" value={usd(summary.loss_at_stop_usd)} detail={`${pct(summary.portfolio_heat_pct)} of portfolio · price gaps can increase losses`} />
      <W7Metric label="Value without active protection" value={usd(summary.unprotected_value_usd)} detail={stops.unprotected_count == null ? 'Position count unavailable' : `${stops.unprotected_count} positions`} />
      <W7Metric label="Largest single name" value={summary.largest_name ? `${summary.largest_name.symbol} ${pct(summary.largest_name.pct)}` : 'Not available'} detail={`Policy max ${pct(capital.policy_max_pct)}`} />
      <W7Metric label="Awaiting fill" value={text(stops.awaiting_fill_count)} detail="Pending activation is shown separately on each position." />
    </div>
    <W7Panel title="Positions and stops" testId="risk-positions">
      <p style={{ color: TOKENS.text[2] }}>Positions · {when(positions.as_of)} · Stops · {when(stops.as_of)}</p>
      {positions.gap && <W7Gap>{typeof positions.gap === 'string' ? positions.gap : positions.gap.reason}</W7Gap>}
      {stops.gap && <W7Gap>{typeof stops.gap === 'string' ? stops.gap : stops.gap.reason}</W7Gap>}
      <div className="w7-position-head" style={{ gridTemplateColumns: '80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr))', gap: 10, color: TOKENS.text[2], fontSize: 11, padding: '8px 0' }}><span>Symbol</span><span>Account</span><span>Shares</span><span>Price</span><span>Stop</span><span>To stop</span><span>Loss at stop</span><span>Source / state</span></div>
      {rows.map((p, i) => <article key={`${p.account_id || p.account}-${p.symbol}-${i}`} className="w7-position-row" data-stop-state={p.stop_state || 'unknown'}>
        <b style={mono}>{p.symbol}</b>
        <span>{p.account_label || 'Account name unavailable'}</span>
        <span style={mono}><small className="w7-field-label">Shares </small>{text(p.shares ?? p.quantity)}</span>
        <span style={mono}><small className="w7-field-label">Price </small>{(p.current_price ?? p.price) == null ? 'Not available' : `$${(p.current_price ?? p.price).toLocaleString('en-US', { maximumFractionDigits: 4 })}`}</span>
        <span style={mono}><small className="w7-field-label">Stop </small>{p.stop_price == null ? 'None published' : `$${p.stop_price.toLocaleString('en-US', { maximumFractionDigits: 4 })}`}</span>
        <span style={mono}><small className="w7-field-label">To stop </small>{pct(p.distance_to_stop_pct)}</span>
        <span style={mono}><small className="w7-field-label">Loss at stop </small>{usd(p.loss_at_stop_usd ?? p.risk_usd)}</span>
        <span style={{ color: p.stop_state === 'active' ? TOKENS.success : TOKENS.warning }}><span>{sourceLabel[p.stop_source] || 'Source unavailable'}</span><small style={{ display: 'block' }}>{stateLabel[p.stop_state] || 'State unavailable'}</small></span>
        <button className="w7-position-action" onClick={() => detail.open(key(p))} style={{ minHeight: 44, color: TOKENS.info, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, cursor: 'pointer' }}>Review {p.symbol} →</button>
      </article>)}
      {!rows.length && !positions.gap && <W7Gap>No positions have been published.</W7Gap>}
    </W7Panel>
    {selected && <W7DetailSheet title={`${selected.symbol} · stop details`} onClose={detail.close}>
      <p>{selected.account_label || 'Account name unavailable'}</p>
      <div style={line}><span>Stop price</span><b>{usd(selected.stop_price)}</b></div>
      <div style={line}><span>Source</span><b>{sourceLabel[selected.stop_source] || 'Source unavailable'}</b></div>
      <div style={line}><span>State</span><b>{stateLabel[selected.stop_state] || 'State unavailable'}</b></div>
      <p>Observed {when(selected.stop_captured_at || selected.stop_evidence?.as_of)}</p>
      {selected.stop_state === 'pending_activation' && <W7Gap>This stop is awaiting activation. It does not provide active protection yet.</W7Gap>}
      <Link to={`/trading?tab=Open+Trades&symbol=${encodeURIComponent(selected.symbol)}`} style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 20 }}>Review position in Trading →</Link>
    </W7DetailSheet>}
  </div>
}

export function W7RiskConcentration({ data }: { data: any }) {
  const model = data.positions || {}, rows: any[] = model.concentration || []
  return <W7Panel title="Concentration">
    <p>Max single name {pct(data.capital?.policy_max_pct)} · alert level {pct(data.capital?.alert_level_pct)}</p>
    {rows.map((p, i) => <div key={p.symbol || i} style={line}><b style={mono}>{p.symbol}</b><span style={mono}>{usd(p.value_usd)} · {pct(p.pct)}</span></div>)}
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

export function W7RiskStyles() { return <style>{`.w7-position-head{display:grid}.w7-position-row{display:grid;grid-template-columns:80px minmax(130px,1.4fr) repeat(6,minmax(65px,1fr));gap:10px;padding:12px 0;border-top:1px solid var(--border-subtle);align-items:start;font-size:12px}.w7-position-action{grid-column:1/-1}.w7-field-label{display:none}@media(max-width:1000px){.w7-position-head{display:none}.w7-position-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.w7-field-label{display:block;color:var(--text-2);font:11px var(--font-sans)}}`}</style> }
