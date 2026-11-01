import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import type { DrillContext } from './DetailDrawer'
import { W7Gap, W7Metric, W7Panel, W7PolicyLimits, grid, line, linkStyle, mono, pct, text, usd, when } from './W7PagePanels'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'
import { STOP_CATEGORY_LABEL, STOP_CATEGORY_TONE, stopCategory, stopDistancePct, stopLossUsd, symbolList, type StopCategory } from '../lib/stopDisplay'
import { toneVars } from '../lib/designTokens'
import { ShadowTag } from './home/MarketRiskBanner'
import { bannerVisible, episodeLine, fmtPct, pointsSum, shortTime, tierTone, unwrapMarketRisk, type MarketRisk } from '../lib/marketRisk'

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
      <W7Metric label="Awaiting fill" value={<span data-testid="risk-kpi-awaiting">{awaiting.length}</span>} detail={awaiting.length ? `${symbolList(awaiting)} · ${filledRows.length ? (filledRows.find((p: any) => p.reason)?.reason || 'stop filled · awaiting holdings sync') : 'mark at or below the stop · fill not confirmed'}` : 'No stop has filled or been crossed.'} />
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

/** Design risk/v002: the "Market risk" tab — tier card, contributors, nine categories, your book vs budget, probabilities,
 *  score history, alert episodes, and the kept legacy regime panel as the last block. Advisory only; no size, order or
 *  stop control. A tier the engine did not compute renders NOT EVALUATED, never a guess. */
export function W7RiskMarketRisk({ data, mr: resp, error }: { data: any, mr: any, error?: unknown }) {
  const mr: MarketRisk | null = unwrapMarketRisk(resp)
  const [ack, setAck] = useState<string | null>(null)
  const tone = mr ? (mr.state === 'not_evaluated' ? 'neutral' : tierTone(mr.tier)) : 'neutral'
  const tv = toneVars(tone)
  const chip = (state: string) => {
    const t = state === 'STRESS' ? 'danger' : state === 'WARN' ? 'warning' : state === 'CALM' ? 'success' : 'neutral'
    const v = toneVars(t)
    return <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '0.04em', borderRadius: RADIUS.pill, padding: '3px 8px', color: TOKENS.bg[0], background: t === 'neutral' ? TOKENS.text[3] : v.color }}>{state}</span>
  }
  const acknowledge = async () => {
    try {
      const r = await fetch('/api/v2/market-risk/ack', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ episode_id: mr?.episode?.id ?? null }) })
      const j: any = await r.json().catch(() => ({}))
      setAck(r.ok ? `Acknowledged ${shortTime(new Date().toISOString())}` : `Not recorded: ${j?.error ?? `HTTP ${r.status}`}${j?.detail ? ` — ${j.detail}` : ''}`)
    } catch (e) { setAck(`Not recorded: ${String(e)}`) }
  }
  const row: CSSProperties = { display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'baseline', minHeight: 34, borderTop: `1px solid ${TOKENS.borderSubtle}`, fontSize: TYPE.base }
  return <>
    <W7Panel title="Market risk" testId="risk-market-risk">
      {error ? <W7Gap>Market risk unavailable: {String(error)}</W7Gap> : null}
      {!mr && !error && <p style={{ color: TOKENS.text[2] }}>Loading…</p>}
      {mr && <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 12, borderRadius: RADIUS.lg, background: tv.bg, border: `1px solid ${tv.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span data-testid="risk-market-risk-tier" style={{ fontSize: TYPE.base, fontWeight: 800, letterSpacing: '0.04em', color: TOKENS.bg[0], background: tone === 'neutral' ? TOKENS.text[3] : tv.color, borderRadius: RADIUS.pill, padding: '4px 10px' }}>{mr.state === 'not_evaluated' ? 'NOT EVALUATED' : mr.tier}</span>
          <ShadowTag mr={mr} testid="risk-market-risk-shadow" />
          <span style={{ ...mono, fontSize: TYPE.xl, fontWeight: 700, color: TOKENS.text[0] }}>{mr.score != null ? Math.round(mr.score) : '—'}<span style={{ fontSize: TYPE.md, color: TOKENS.text[2] }}>/100</span></span>
          {mr.confirming && <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{mr.confirming.n} of {mr.confirming.of} categories confirm</span>}
        </div>
        <p style={{ margin: 0, color: TOKENS.text[2], fontSize: TYPE.base }}>
          {mr.state === 'not_evaluated' ? mr.reason : <>{episodeLine(mr) || 'no open episode'} · evaluated {shortTime(mr.as_of)}{mr.state === 'stale' ? ' · STALE' : ''}</>}
        </p>
        {mr.deescalates_if && <p style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[2] }}><b style={{ color: TOKENS.text[0] }}>De-escalates if</b> {mr.deescalates_if}</p>}
        {bannerVisible(mr) && !mr.episode?.acknowledged_at && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" data-testid="risk-market-risk-ack" onClick={acknowledge} style={{ minHeight: 44, padding: '0 20px', borderRadius: RADIUS.md, border: 0, background: tv.color, color: TOKENS.bg[0], fontSize: TYPE.md, fontWeight: 800, cursor: 'pointer' }}>Acknowledge</button>
          <Link to="/risk?tab=exposure" style={{ ...linkStyle, minHeight: 44, display: 'inline-flex', alignItems: 'center', padding: '0 14px', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>Review stops</Link>
        </div>}
        {ack && <p role="status" style={{ margin: 0, fontSize: TYPE.base, color: ack.startsWith('Not recorded') ? toneVars('warning').color : toneVars('success').color }}>{ack}</p>}
        <p style={{ margin: 0, fontSize: TYPE.sm, color: TOKENS.text[3] }}>Advisory. No order, size or stop level is implied.</p>
      </div>}
    </W7Panel>

    {mr && mr.contributors.length > 0 && <W7Panel title="Contributors" testId="risk-market-risk-contributors">
      {mr.contributors.slice(0, 5).map((c, i) => <div key={i} style={row}><span>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}{c.as_of ? ` · ${shortTime(c.as_of)}` : ''}</span> : null}</span><span style={{ ...mono, color: tv.color }}>{c.points >= 0 ? '+' : ''}{Math.round(c.points)}</span></div>)}
      {mr.uplift && <div style={{ ...row, color: TOKENS.text[2] }}><span>{mr.uplift.note ?? `Market ${mr.uplift.market_score ?? '—'} → ${mr.tier} after portfolio vulnerability ${mr.uplift.vulnerability ?? '—'}`}</span><span style={{ ...mono, color: TOKENS.text[0] }}>= {mr.score != null ? Math.round(mr.score) : '—'}</span></div>}
      {!mr.uplift && pointsSum(mr) != null && mr.score != null && Math.round(pointsSum(mr)!) !== Math.round(mr.score) && <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: toneVars('warning').color }}>Contributors sum to {Math.round(pointsSum(mr)!)}, score is {Math.round(mr.score)} — the engine owes an explanation line.</p>}
    </W7Panel>}

    {mr && mr.categories.length > 0 && <W7Panel title="Nine categories" testId="risk-market-risk-categories">
      {mr.categories.map((c, i) => <div key={i} data-testid="risk-market-risk-category" style={row}><span>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}</span> : null}{c.weight != null && c.weight < 1 && c.state !== 'UNKNOWN' ? <span style={{ color: TOKENS.text[3] }}> · weight {c.weight}</span> : null}</span>{chip(c.state)}</div>)}
      <p style={{ margin: '6px 0 0', fontSize: TYPE.sm, color: TOKENS.text[3] }}>UNKNOWN = a source not read since its stale window; never counted as calm.</p>
    </W7Panel>}

    {mr?.book?.budgets?.length ? <W7Panel title="Your book vs budget" testId="risk-market-risk-book">
      {mr.book.budgets.map((b, i) => {
        const ratio = b.limit > 0 ? b.actual / b.limit : 0
        const t = b.breached || ratio >= 1 ? 'danger' : ratio >= 0.9 ? 'warning' : 'success'
        return <div key={i} data-testid="risk-market-risk-budget" style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 0', borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: TYPE.base }}><span>{b.budget}</span><span style={{ ...mono, color: toneVars(t).color }}>{b.actual}{b.unit ?? '%'} / {b.limit}{b.unit ?? '%'}</span></div>
          <div style={{ height: 8, borderRadius: RADIUS.sm, background: TOKENS.bg[3] }}><div style={{ width: `${Math.min(100, Math.round(ratio * 100))}%`, height: 8, borderRadius: RADIUS.sm, background: toneVars(t).color }} /></div>
        </div>
      })}
      {mr.book.positions?.length ? <p style={{ margin: '8px 0 0', fontSize: TYPE.base, color: TOKENS.text[2] }}>Driving positions: {mr.book.positions.map(p => `${p.symbol}${p.stop_distance_pct != null ? ` stop ${fmtPct(p.stop_distance_pct / 100)} below` : ''}${p.note ? ` (${p.note})` : ''}`).join(' · ')}. Symbols and stop distance only; the limits are yours.</p> : null}
    </W7Panel> : null}

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
  </>
}
