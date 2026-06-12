import { fmt$ } from '../lib/format'
import ProAnalystPill from './ProAnalystPill'

// Actionable position decision card (READ-ONLY). 6 zones: header identity, decision banner (most important),
// economics, evidence chips (incl. strategy WHY + sector), catalyst/news, manual-action buttons. No trade
// buttons — all actions are review/open/drill only.

const chip = (bg: string, fg: string) => ({ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: bg, color: fg, whiteSpace: 'nowrap' as const, display: 'inline-block' })
const num = (v: any, d = 2) => (v == null ? '—' : Number(v).toFixed(d))
const pct = (v: any) => (v == null ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`)

// priority → left border + accent
const PRI: Record<string, string> = { critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: '#22c55e' }
const RSI_C = (b: string) => b === 'oversold' ? '#22c55e' : b === 'overbought' ? '#ef4444' : b === 'missing' ? 'var(--text3)' : '#60a5fa'
const BASIS_C: Record<string, string> = { broker: '#22c55e', tax_grade: '#22c55e', verified: '#60a5fa', entry: '#60a5fa', owner_provided: '#a855f7', unknown: '#ef4444' }
const FRESH_C: Record<string, string> = { fresh: '#22c55e', aging: '#f59e0b', stale: '#ef4444', none: 'var(--text3)' }

export default function PositionDecisionCard({ p, paMap, expanded, onToggle, onDrill, onAction }: any) {
  const t = p.technical || {}, sr = p.sector_relative || {}, pr = p.protection || {}
  const priority = p.operator_priority || 'low'
  const border = PRI[priority] || 'var(--border)'
  const news: any[] = (p.news ?? [])
  const ageH = p.latest_news_age_hours

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: `4px solid ${border}`, borderRadius: 10, padding: 12 }}>

      {/* ── ZONE 1: HEADER — identity + account + priority ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>{p.symbol}</span>
          <ProAnalystPill symbol={p.symbol} map={paMap} compact />
          <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>{p.shares} sh · {p.hold_duration ?? '—'}</span>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {p.watchlist_state === 'directive' && <span style={chip('rgba(168,85,247,.18)', '#a855f7')} title="Operator directive-linked">★ directive</span>}
          {p.watchlist_state === 'watchlist' && <span style={chip('rgba(96,165,250,.15)', '#60a5fa')}>watchlist</span>}
          {/* account badge — loud paper-vs-real distinction (operator request 2026-06-12: AGNC/NWG
              exist as BOTH paper trades and real Schwab holdings; the badge disambiguates at a glance) */}
          {(() => {
            const paper = p.environment === 'paper' || String(p.account ?? '').toLowerCase().includes('paper')
            return <span title={`${p.broker}/${p.environment}`} style={chip(
              paper ? 'rgba(96,165,250,.18)' : 'rgba(255,167,38,.18)', paper ? '#60a5fa' : '#ffa726')}>
              {paper ? '📝 PAPER' : '💰 REAL'} · {String(p.account ?? '?').replace(/_/g, ' ').toUpperCase()}</span>
          })()}
          <span style={chip(`${border}22`, border)} title={`Operator priority: ${priority}`}>{priority.toUpperCase()}</span>
          <span style={chip(p.protection_state === 'protected' ? 'rgba(34,197,94,.15)' : p.protection_state === 'partial' ? 'rgba(245,158,11,.15)' : 'rgba(239,68,68,.15)', p.protection_state === 'protected' ? '#22c55e' : p.protection_state === 'partial' ? '#f59e0b' : '#ef4444')}>{p.protection_state}</span>
        </div>
      </div>

      {/* ── ZONE 3: DECISION BANNER (most important text) ── */}
      <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 6, background: `${border}14`, border: `1px solid ${border}44` }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: border }}>{p.operator_decision ?? 'No action — monitored'}</div>
        <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 2 }}>{p.decision_reason}</div>
        {p.primary_next_review && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 3 }}>Next: {p.primary_next_review}</div>}
      </div>

      {/* ── ZONE 2: ECONOMICS ── */}
      <div style={{ display: 'flex', gap: 12, marginTop: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        {p.unrealized_pnl != null ? (<>
          <span style={{ fontSize: 16, fontWeight: 700, color: p.unrealized_pnl >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(p.unrealized_pnl)}</span>
          <span style={{ fontSize: 12, color: (p.unrealized_pnl_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{pct(p.unrealized_pnl_pct)}</span>
        </>) : (<>
          <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(p.market_value ?? 0)}</span>
        </>)}
        {p.today_move_pct != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>today {pct(p.today_move_pct)}</span>}
        {p.r_multiple != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{num(p.r_multiple, 1)}R</span>}
        {p.market_value != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>mv {fmt$(p.market_value, 0)}</span>}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 5, fontFamily: 'monospace' }}>
        {p.basis_kind === 'avg_cost' ? 'avg' : 'entry'} {p.basis_reliable ? num(p.entry_price) : 'n/a'} · now {num(p.current_price)}
        {p.stop_price != null ? ` · stop ${num(p.stop_price)}` : ''}{p.target_price ? ` · tgt ${num(p.target_price)}` : ''}
        {p.basis_reliable && p.cost_basis != null ? ` · basis ${fmt$(p.cost_basis)}` : ''}
        <span style={{ color: BASIS_C[p.basis_quality] || 'var(--text3)', marginLeft: 6 }}>basis: {p.basis_quality}</span>
      </div>

      {/* ── ZONE 4: EVIDENCE CHIPS (incl. strategy WHY + sector) ── */}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
        <span style={chip('var(--bg2)', 'var(--text1)')} title="Strategy assigned to this position">{p.strategy ?? 'unclassified'}</span>
        <span style={chip('var(--bg2)', RSI_C(t.rsi_bucket))}>RSI {t.rsi != null ? num(t.rsi, 0) : '—'} {t.rsi_bucket}</span>
        <span style={chip('var(--bg2)', t.trend_label === 'bullish' ? '#22c55e' : t.trend_label === 'bearish' ? '#ef4444' : 'var(--text2)')}>{t.trend_label}</span>
        {sr.sector && <span style={chip('var(--bg2)', (sr.vs_sector_5d ?? 0) > 1 ? '#22c55e' : (sr.vs_sector_5d ?? 0) < -1 ? '#ef4444' : 'var(--text2)')} title={`vs sector 5d ${sr.vs_sector_5d != null ? pct(sr.vs_sector_5d) : '—'}`}>{sr.sector}{sr.sector_etf ? ` (${sr.sector_etf})` : ''}</span>}
        <span style={chip('var(--bg2)', FRESH_C[p.data_freshness])} title="Technical/price data freshness">data {p.data_freshness}</span>
        <span style={chip('var(--bg2)', FRESH_C[p.news_freshness])} title={ageH != null ? `newest headline ${Math.round(ageH)}h old` : 'no recent news'}>news {p.news_freshness}{ageH != null ? ` ${Math.round(ageH)}h` : ''}</span>
        {(p.risk_flags ?? []).map((r: string) => <span key={r} style={chip('rgba(239,68,68,.13)', '#ef4444')}>{r.replace(/_/g, ' ')}</span>)}
        {(p.opportunity_flags ?? []).map((o: string) => <span key={o} style={chip('rgba(34,197,94,.13)', '#22c55e')}>{o.replace(/_/g, ' ')}</span>)}
        {p.l2_pressure?.imbalance != null && (
          <span style={chip(p.l2_pressure.imbalance > 0.2 ? 'rgba(34,197,94,.13)' : p.l2_pressure.imbalance < -0.2 ? 'rgba(239,68,68,.13)' : 'var(--bg2)',
            p.l2_pressure.imbalance > 0.2 ? '#22c55e' : p.l2_pressure.imbalance < -0.2 ? '#ef4444' : 'var(--text2)')}
            title={`Level-2 book pressure (live stream)\nbid depth ${p.l2_pressure.bid_depth} / ask depth ${p.l2_pressure.ask_depth} · ${p.l2_pressure.at}`}>
            L2 {p.l2_pressure.imbalance > 0 ? '+' : ''}{Number(p.l2_pressure.imbalance).toFixed(2)}
          </span>
        )}
        {p.hermes_rank != null && p.hermes_rank <= 100 && (
          <span style={chip('rgba(167,139,250,.13)', '#a78bfa')} title={`Hermes watchlist intelligence rank (composite ${p.hermes_composite != null ? Number(p.hermes_composite).toFixed(1) : '—'})`}>H#{p.hermes_rank}</span>
        )}
        {p.short_float_pct != null && p.short_float_pct >= 5 && (
          <span style={chip('rgba(245,158,11,.13)', '#f59e0b')} title={`Short float ${p.short_float_pct}% — squeeze/volatility context`}>short {num(p.short_float_pct, 1)}%</span>
        )}
        {p.earnings_date && (
          <span style={chip('rgba(96,165,250,.13)', '#60a5fa')} title="Next earnings date (from enrichment)">earnings {p.earnings_date}</span>
        )}
      </div>

      {/* ── ANALYST LINE (explicit — was cryptic pills) ── */}
      {p.analyst && (p.analyst.rating || p.analyst.target_mean != null) && (
        <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 5 }}
          title={`${p.analyst.source ?? 'analyst consensus'}${p.analyst.latest_event ? `\nlatest: ${p.analyst.latest_event}` : ''}\ntarget range $${p.analyst.target_low ?? '—'} – $${p.analyst.target_high ?? '—'}`}>
          <b style={{ color: 'var(--text1)' }}>Analysts:</b>{' '}
          {p.analyst.rating ? `${String(p.analyst.rating).toUpperCase()}${p.analyst.rating_mean != null ? ` (${Number(p.analyst.rating_mean).toFixed(1)})` : ''}` : 'no consensus'}
          {p.analyst.opinions != null && ` · ${p.analyst.opinions} opinions`}
          {p.analyst.target_mean != null && ` · target $${num(p.analyst.target_mean, 2)}`}
          {p.analyst.target_upside_pct != null && (
            <span style={{ color: p.analyst.target_upside_pct > 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
              {' '}({p.analyst.target_upside_pct > 0 ? '+' : ''}{num(p.analyst.target_upside_pct, 1)}% to target)
            </span>
          )}
        </div>
      )}

      {/* WHY this strategy (operator asked for this) */}
      {p.strategy_rationale && (
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6, fontStyle: 'italic' }} title="Why this strategy applies (from the strategy's purpose)">
          Why <b style={{ color: 'var(--text2)' }}>{p.strategy}</b>: {p.strategy_rationale}
        </div>
      )}

      {/* ── ZONE 6: MANUAL ACTION BUTTONS (read-only / review only) ── */}
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 9, alignItems: 'center' }}>
        {(p.recommended_manual_actions ?? []).slice(0, 4).map((a: string) => (
          <button key={a} onClick={() => onAction?.(a, p)} title="Operator review action (read-only — no order placed)"
            style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>{a}</button>
        ))}
        <span onClick={onToggle} style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer', textDecoration: 'underline', marginLeft: 'auto' }}>{expanded ? 'less' : 'more'}</span>
        <span onClick={() => onDrill({ title: `${p.symbol} — ${p.account}`, subtitle: `${p.strategy ?? ''} · ${p.broker}/${p.environment}`, endpoint: '/api/v2/open-trades/intelligence', rows: [p], subjectType: 'position', subjectKey: p.symbol })}
          style={{ fontSize: 9, color: '#60a5fa', cursor: 'pointer', textDecoration: 'underline' }}>drill</span>
      </div>

      {/* ── ZONE 5: CATALYST / NEWS (expanded) ── */}
      {expanded && (
        <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)', marginBottom: 4 }}>News & catalysts</div>
          {news.length === 0 && <div style={{ fontSize: 9, color: 'var(--text3)' }}>No recent research surfaced.</div>}
          {/* operator 2026-06-12: expanded = FULL text, no truncation — the card is open to be READ */}
          {news.map((n: any, i: number) => {
            const stale = (n.age_hours ?? 0) > 48
            return (
              <div key={i} style={{ fontSize: 10, marginBottom: 6, opacity: stale ? 0.65 : 1, lineHeight: 1.45 }}>
                <div style={{ display: 'flex', gap: 5, alignItems: 'baseline' }}>
                  <span style={chip('var(--bg2)', 'var(--text2)')}>{n.source}</span>
                  {n.age_hours != null && <span style={{ fontSize: 9, color: stale ? '#f59e0b' : 'var(--text3)' }}>{Math.round(n.age_hours)}h{stale ? ' stale' : ''}</span>}
                </div>
                {n.url
                  ? <a href={n.url} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'none', display: 'block', marginTop: 2 }}>{n.title || ''}</a>
                  : <div style={{ color: 'var(--text2)', marginTop: 2 }}>{n.title || ''}</div>}
                {n.why_it_matters && <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 2 }}><b style={{ color: 'var(--text2)' }}>Why it matters:</b> {n.why_it_matters}</div>}
              </div>
            )
          })}
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
            SMA50 {t.sma50_pct != null ? pct(t.sma50_pct) : '—'} · SMA200 {t.sma200_pct != null ? pct(t.sma200_pct) : '—'} · RVOL {t.rvol ?? '—'}
            {sr.sector ? ` · ${sr.sector} ${sr.label}` : ''}{p.last_hermes_review_at ? ` · Hermes ${String(p.last_hermes_review_at).slice(0, 10)}` : ''}
          </div>
        </div>
      )}
    </div>
  )
}
