import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'

export const usd = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) : 'Not available'
export const pct = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? `${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}%` : 'Not measured'
export const text = (v: unknown, gap = 'Not available') => v == null ? gap : String(v)
const localHref = (v: unknown) => typeof v === 'string' ? v.replace(/^\/v3(?=\/|$)/, '') || '/' : null
export const when = (v: unknown) => {
  if (!v) return 'Time unavailable'
  const d = new Date(String(v))
  return Number.isNaN(d.getTime()) ? 'Time unavailable' : d.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}
export const grid: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,290px),1fr))', gap: 12, alignItems: 'start' }
export const line: CSSProperties = { display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderTop: `1px solid ${TOKENS.borderSubtle}`, flexWrap: 'wrap' }
export const linkStyle: CSSProperties = { color: TOKENS.info, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', minHeight: 44, padding: '8px 0', boxSizing: 'border-box' }
export const mono: CSSProperties = { fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' }

export function W7Panel({ title, children, testId }: { title: string, children: ReactNode, testId?: string }) {
  return <section data-testid={testId} style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: 16, minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2 style={{ fontSize: TYPE.md, fontWeight: 600, margin: '0 0 12px' }}>{title}</h2>{children}
  </section>
}
export function W7Gap({ children }: { children?: ReactNode }) {
  const t = toneVars('warning')
  return <p role="status" style={{ margin: '8px 0', padding: 10, borderRadius: RADIUS.md, background: t.bg, border: `1px dashed ${t.border}`, color: t.color, fontSize: TYPE.base }}>{children || 'The source has not published this measurement.'}</p>
}
export function W7Metric({ label, value, detail }: { label: string, value: ReactNode, detail?: ReactNode }) {
  return <div style={{ minWidth: 0, background: TOKENS.bg[2], padding: 12, borderRadius: RADIUS.md }}><div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>{label}</div><div style={{ ...mono, fontSize: TYPE.lg, margin: '6px 0', overflowWrap: 'anywhere' }}>{value}</div>{detail && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>{detail}</div>}</div>
}
export function useW7Pages(enabled = true) { return useApi<any>('/api/v2/cio/pages', 60_000, { enabled }) }
export function W7Load({ loading, error }: { loading?: boolean, error?: unknown }) {
  return <W7Gap>{loading ? 'Loading the CIO record…' : error ? 'The CIO record could not be loaded. Please try again.' : 'The CIO record has not been published.'}</W7Gap>
}

export function W7HomePanels({ data }: { data: any }) {
  const todo = data.do_now || {}, stops = data.stops || {}, regime = data.regime || {}, approvals = data.approvals || {}
  const items: any[] = todo.items || []
  const nearest = stops.nearest
  const awaiting: any[] = stops.awaiting_fill || []
  return <div style={{ ...grid, gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,360px),1fr))' }}>
    <W7Panel title="Do now" testId="home-do-now">
      <p style={{ color: TOKENS.text[2], marginTop: 0 }}>Ranked by the CIO · up to 7</p>
      {todo.gap && <W7Gap>{typeof todo.gap === 'string' ? todo.gap : todo.gap.reason}</W7Gap>}
      {!items.length && !todo.gap && <p>No actions published by the CIO.</p>}
      {items.map((item, i) => <div key={item.id || i} style={line}>
        <div style={{ flex: '1 1 220px' }}><b>{item.symbol && <span style={mono}>{item.symbol} </span>}{item.title || item.text}</b>
          {item.account_label && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>{item.account_label}</div>}
          <div style={{ color: TOKENS.text[2], marginTop: 4 }}>{item.reason || item.why || item.detail}</div>
          {item.stance && <span>CIO {item.stance} · conviction {text(item.conviction)}</span>}
          {item.conflicts?.length > 0 && <W7Gap>{item.conflicts.map((c: any) => c.reason || c.note || c.field).join(' · ')}</W7Gap>}
        </div>{localHref(item.href || item.action?.where) && <Link style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2] }} to={localHref(item.href || item.action?.where)!}>{item.cta || item.action?.label || 'Review'} →</Link>}
      </div>)}
    </W7Panel>
    <div style={{ display: 'grid', gap: 12 }}>
      <W7Panel title="Protection">
        <div style={grid}>
          <W7Metric label="With an active broker stop" value={text(stops.active_count)} detail={stops.pending_count == null ? undefined : `${stops.pending_count} pending activation`} />
          <W7Metric label="Awaiting fill" value={awaiting.length ? awaiting.map(p => p.symbol).join(', ') : text(stops.awaiting_fill_count)} />
          <W7Metric label="Nearest active stop" value={nearest ? `${nearest.symbol} ${pct(nearest.distance_pct)}` : 'Not available'} />
        </div>
        {stops.gap && <W7Gap>{typeof stops.gap === 'string' ? stops.gap : stops.gap.reason}</W7Gap>}
        <p><Link to="/risk" style={linkStyle}>All positions and stops → Risk</Link></p>
      </W7Panel>
      <W7Panel title="CIO view of the market">
        <p>Regime <b>{text(regime.label, 'Not classified')}</b> · VIX <b>{text(regime.vix)}</b></p>
        <p style={{ color: TOKENS.text[2] }}>{when(regime.as_of)}{regime.stale ? ' · Last published view; refresh overdue' : ''}</p>
        {regime.gap && <W7Gap>{typeof regime.gap === 'string' ? regime.gap : regime.gap.reason}</W7Gap>}
        <p>Favoured sectors: {data.sectors?.favoured?.join(', ') || 'Not published'}</p>
        <Link to="/watch?tab=sectors" style={linkStyle}>Sector trends and leaders →</Link>
      </W7Panel>
      <W7Panel title="Waiting on you">
        <div style={line}><Link to="/trading?tab=Proposals" style={linkStyle}>Approvals</Link><b style={mono}>{text(approvals.total)}</b></div>
        {approvals.gap && <W7Gap>{typeof approvals.gap === 'string' ? approvals.gap : approvals.gap.reason}</W7Gap>}
        <div style={line}><Link to="/cio/questions" style={linkStyle}>My questions</Link><span>Review replies →</span></div>
        <div style={line}><Link to="/releases" style={linkStyle}>Releases</Link><span>Review readiness →</span></div>
      </W7Panel>
    </div>
  </div>
}

export function W7CioStatus({ data }: { data: any }) {
  const model = data.cio_status || {}, evaluations = model.evaluations || []
  const rows = Array.isArray(evaluations) ? evaluations : Object.entries(evaluations).map(([label, v]: any) => ({ label, ...v }))
  return <W7Panel title="Is the CIO working?" testId="cio-single-status">
    <p style={{ color: TOKENS.text[2] }}>One evaluation for each part of the investment office.</p>
    {model.gap && <W7Gap>{typeof model.gap === 'string' ? model.gap : model.gap.reason}</W7Gap>}
    {!rows.length && <W7Gap>No evaluations have been published.</W7Gap>}
    {rows.map((r: any, i: number) => <div key={r.id || r.key || i} style={line}><b>{r.label || r.title || r.name}</b><span>{text(r.status)}</span><div style={{ flexBasis: '100%', color: TOKENS.text[2] }}>{r.reason || r.verdict || r.measurement || r.detail || 'Measurement unavailable'} · {when(r.as_of || model.as_of)}</div>{(r.metrics || []).map((m: any, j: number) => <span key={j}>{m.label}: <b style={mono}>{typeof m.value === 'object' && m.value !== null ? 'Not available' : text(m.value)}</b></span>)}</div>)}
    <Link style={linkStyle} to="/cio?tab=evidence-comms">Review evidence →</Link>
  </W7Panel>
}
export function W7Capital({ data }: { data: any }) {
  const c = data.capital || {}
  const rows: [string, unknown][] = [['Cash on hand', c.cash_usd], ['Reserved', c.reserved_usd], ['Earmarked for redeployment', c.earmarked_usd], ['Investable today', c.investable_usd]]
  return <W7Panel title="Cash, counted once" testId="cio-cash-waterfall">
    {rows.map(([label, value]) => <div key={label} style={{ ...line, fontWeight: label === 'Investable today' ? 700 : undefined }}><span>{label}</span><span style={mono}>{usd(value)}</span></div>)}
    <div style={{ ...line, marginTop: 16 }}><span>Potential raise from future trims</span><span style={mono}>{usd(c.prospective_raise_usd)}</span></div>
    <p style={{ color: TOKENS.text[2] }}>Potential proceeds are shown separately from cash on hand.</p>
    <h3 style={{ fontSize: TYPE.md }}>Policy limits</h3>
    <div style={line}><span>Max single name</span><span style={mono}>{pct(c.policy_max_pct)}</span></div>
    <div style={line}><span>Concentration alert level</span><span style={mono}>{pct(c.alert_level_pct)}</span></div>
    <div style={line}><span>Cash band</span><span style={mono}>{pct(c.cash_band?.min)} – {pct(c.cash_band?.max)}</span></div>
    <div style={line}><span>Current cash</span><span style={mono}>{pct(c.current_cash_pct)}</span></div>
    <div style={line}><span>After plan</span><span style={mono}>{pct(c.post_plan_cash_pct)}</span></div>
    {c.gap && <W7Gap>{typeof c.gap === 'string' ? c.gap : c.gap.reason}</W7Gap>}
    <p style={{ color: TOKENS.text[2] }}>{when(c.as_of)}</p>
  </W7Panel>
}
