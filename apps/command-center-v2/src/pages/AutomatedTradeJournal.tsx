import { useState, useEffect, useCallback } from 'react'
import { Line, Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip } from 'chart.js'
import PageHeader from '../components/PageHeader'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { fmt$, fmtPct } from '../lib/format'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip)

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const thStyle: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }
const tdStyle: React.CSSProperties = { fontSize: 11, padding: '5px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text0)' }
const pill = (color: string): React.CSSProperties => ({ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)', color: color === 'green' ? '#4ADE80' : color === 'red' ? '#F87171' : color === 'blue' ? '#60A5FA' : '#F59E0B', fontWeight: 600 })
const sLbl: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', fontWeight: 600, marginBottom: 6, marginTop: 12 }
const pnlColor = (v: number | null | undefined) => v == null ? 'var(--text3)' : v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text2)'

function timeStr(iso: string | null) {
  if (!iso) return '--'
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function DetailGrid({ items }: { items: [string, string | number | null | undefined][] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6 }}>
      {items.map(([label, value]) => (
        <div key={label}>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{label}</div>
          <div style={{ fontSize: 11, color: 'var(--text0)', ...mono }}>{value ?? '--'}</div>
        </div>
      ))}
    </div>
  )
}

function EventTimeline({ events, alerts }: { events: any[]; alerts: any[] }) {
  const all = [
    ...events.map((e: any) => ({ ...e, _src: 'event' })),
    ...alerts.map((a: any) => ({ ...a, event_type: a.alert_type, event_summary: a.message, agent_name: 'alert', _src: 'alert' })),
  ].sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''))

  const icons: Record<string, string> = {
    'MONITOR_ADJUST_STOP': '↑', 'MONITOR_TIGHTEN_NEAR_TARGET': '⬆', 'MONITOR_CLOSE_TARGET': '$',
    'MONITOR_ADD_STOP': '+', 'MONITOR_PHANTOM_CLOSED': '⛔',
    'IRIS_OUTCOME_WRITEBACK': '🔍', 'AEGIS_POST_TRADE_SYNTHESIS': '🛡',
    'OUTCOME_LESSON_CAPTURED': '📚', 'PATTERN_CHECK': '📊', 'LOCAL_LLM_ANALYSIS': '🤖',
    'OPEN_TRADE_ALERT': '🔔', 'NEAR_STOP': '🔴', 'NEAR_TARGET': '🟢',
    'STALE_TRADE': '⏳', 'NEGATIVE_NEWS': '⚠', 'CRITICAL_NEWS_CLOSE': '🛑',
    'EXTENDED_PROFIT': '🟢', 'AUTO_CLOSE_CRITICAL_NEWS': '🛑',
  }

  if (all.length === 0) return <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', padding: 8 }}>No lifecycle events recorded yet.</div>

  return (
    <div style={{ maxHeight: 300, overflowY: 'auto' }}>
      {all.map((ev, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
          <span style={{ minWidth: 110, color: 'var(--text3)', fontSize: 10, ...mono }}>{timeStr(ev.created_at)}</span>
          <span style={{ minWidth: 16 }}>{icons[ev.event_type] || '•'}</span>
          <span style={{ color: ev._src === 'alert' ? 'var(--amber)' : 'var(--blue)', fontWeight: 600, fontSize: 10, minWidth: 55 }}>
            {ev.agent_name || 'system'}
          </span>
          <span style={{ color: 'var(--text1)', flex: 1 }}>{ev.event_summary}</span>
        </div>
      ))}
    </div>
  )
}

function TradeExpansion({ trade }: { trade: any }) {
  const t = trade
  const alpaca = t.alpaca || {}
  const hasAlpaca = Object.keys(alpaca).length > 0

  return (
    <div style={{ padding: '12px 16px', background: 'var(--bg0)' }}>
      {/* Position & Execution Details */}
      <div style={sLbl}>POSITION & EXECUTION</div>
      <DetailGrid items={[
        ['Direction', 'LONG'],
        ['Shares', t.shares],
        ['Entry Price', t.entry_price != null ? `$${Number(t.entry_price).toFixed(2)}` : null],
        ['Planned Entry', t.planned_entry != null ? `$${Number(t.planned_entry).toFixed(2)}` : null],
        ['Entry Slippage', t.entry_slippage != null ? `${Number(t.entry_slippage).toFixed(2)}%` : null],
        ['Stop Loss', t.stop_loss != null ? `$${Number(t.stop_loss).toFixed(2)}` : null],
        ['Target', t.target_1 != null ? `$${Number(t.target_1).toFixed(2)}` : null],
        ['Current Price', (hasAlpaca ? alpaca.alpaca_current_price : t.current_price) != null
          ? `$${Number(hasAlpaca ? alpaca.alpaca_current_price : t.current_price).toFixed(2)}` : null],
        ['Dollar Size', t.dollar_size != null ? `$${Number(t.dollar_size).toFixed(0)}` : null],
        ['Dollar Risk', t.dollar_risk != null ? `$${Number(t.dollar_risk).toFixed(0)}` : null],
        ['Order Type', t.order_type],
        ['Broker Order', t.broker_order_id ? String(t.broker_order_id).slice(0, 12) + '...' : null],
        ['Broker Status', t.broker_status],
        ['Bracket', t.bracket_order ? 'Yes' : 'No'],
        ['Submitted', timeStr(t.submitted_at)],
        ['Filled', timeStr(t.filled_at)],
      ]} />

      {/* Alpaca Real-Time (open trades only) */}
      {hasAlpaca && (
        <>
          <div style={sLbl}>ALPACA REAL-TIME</div>
          <DetailGrid items={[
            ['Live Price', `$${alpaca.alpaca_current_price?.toFixed(2)}`],
            ['Market Value', `$${alpaca.alpaca_market_value?.toFixed(2)}`],
            ['Cost Basis', `$${alpaca.alpaca_cost_basis?.toFixed(2)}`],
            ['Unrealized P&L', `$${alpaca.alpaca_unrealized_pl?.toFixed(2)}`],
            ['Unrealized %', `${(alpaca.alpaca_unrealized_plpc * 100)?.toFixed(2)}%`],
            ['Intraday P&L', `$${alpaca.alpaca_intraday_pl?.toFixed(2)}`],
            ['Intraday %', `${(alpaca.alpaca_intraday_plpc * 100)?.toFixed(2)}%`],
            ['Change Today', `${(alpaca.alpaca_change_today * 100)?.toFixed(2)}%`],
            ['Side', alpaca.alpaca_side],
          ]} />
          {alpaca.alpaca_orders?.length > 0 && (
            <>
              <div style={{ ...sLbl, marginTop: 8 }}>ACTIVE ORDERS ON ALPACA</div>
              <div style={{ padding: '4px 12px', background: 'var(--bg0)', borderRadius: 6 }}>
                {alpaca.alpaca_orders.map((o: any, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 0', display: 'flex', gap: 10 }}>
                    <span style={{ ...mono, fontWeight: 600, color: o.side === 'sell' ? 'var(--red)' : 'var(--green)' }}>{o.side?.toUpperCase()}</span>
                    <span>{o.type} {o.stop_price ? `@ $${o.stop_price}` : ''} {o.limit_price ? `limit $${o.limit_price}` : ''}</span>
                    <span style={{ color: 'var(--text3)' }}>qty: {o.qty} | status: {o.status}</span>
                    <span style={{ color: 'var(--text3)', ...mono, fontSize: 8 }}>{String(o.order_id).slice(0, 8)}...</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* Strategy & Market Context */}
      <div style={sLbl}>STRATEGY & MARKET CONTEXT</div>
      <DetailGrid items={[
        ['Strategy', t.strategy_id],
        ['Account', t.account],
        ['Market Regime', t.market_regime],
        ['VIX at Entry', t.vix_at_entry],
        ['Score at Entry', t.score_at_entry],
        ['RVOL at Entry', t.rvol_at_entry],
        ['Float (M)', t.float_m_at_entry],
        ['Intel Readiness', t.intel_readiness],
        ['Risk Gate', t.risk_gate_result],
        ['Opened Via', t.opened_via],
        ['Logged By', t.logged_by],
        ['Proposal ID', t.proposal_id],
      ]} />

      {/* Entry Rationale */}
      <div style={sLbl}>ENTRY RATIONALE</div>
      <div style={{ padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6, fontSize: 11, color: 'var(--text1)', lineHeight: 1.6 }}>
        <div>Strategy: <strong>{t.strategy_id}</strong> via {t.opened_via || 'unknown'}</div>
        {t.catalyst_at_entry && (
          <div>Catalyst: <span style={{ color: t.catalyst_verified ? 'var(--green)' : 'var(--amber)' }}>{t.catalyst_verified ? '✓ Verified' : '○ Unverified'}</span> — {t.catalyst_at_entry}</div>
        )}
        {t.risk_gate_reason_codes && <div>Risk gate codes: <span style={{ ...mono, fontSize: 10 }}>{typeof t.risk_gate_reason_codes === 'string' ? t.risk_gate_reason_codes : JSON.stringify(t.risk_gate_reason_codes)}</span></div>}
        {t.notes && <div style={{ marginTop: 4, padding: '6px 8px', background: 'var(--bg1)', borderRadius: 4, color: 'var(--text2)', fontSize: 10 }}>{t.notes}</div>}
      </div>

      {/* Stop & Limit Logic */}
      <div style={sLbl}>STOP & LIMIT LOGIC</div>
      <DetailGrid items={[
        ['Initial Stop', t.stop_loss != null ? `$${Number(t.stop_loss).toFixed(2)}` : null],
        ['Planned Stop', t.planned_stop != null ? `$${Number(t.planned_stop).toFixed(2)}` : null],
        ['Stop Slippage', t.stop_slippage != null ? `${Number(t.stop_slippage).toFixed(2)}%` : null],
        ['Target 1', t.target_1 != null ? `$${Number(t.target_1).toFixed(2)}` : null],
        ['Target 2', t.target_2 != null ? `$${Number(t.target_2).toFixed(2)}` : null],
        ['R-Multiple', t.r_multiple != null ? `${Number(t.r_multiple).toFixed(2)}R` : null],
        ['MFE', t.max_favorable_excursion != null ? `+${Number(t.max_favorable_excursion).toFixed(1)}%` : null],
        ['MAE', t.max_adverse_excursion != null ? `${Number(t.max_adverse_excursion).toFixed(1)}%` : null],
      ]} />

      {/* Execution Log */}
      <div style={sLbl}>EXECUTION LOG ({t.execution_log.length + t.alerts.length} events)</div>
      <div style={{ padding: '4px 8px', background: 'var(--bg0)', borderRadius: 6 }}>
        <EventTimeline events={t.execution_log} alerts={t.alerts} />
      </div>

      {/* Exit & Outcome (closed trades) */}
      {t.status === 'closed' && (
        <>
          <div style={sLbl}>EXIT & OUTCOME</div>
          <DetailGrid items={[
            ['Exit Price', t.exit_price != null ? `$${Number(t.exit_price).toFixed(2)}` : null],
            ['P&L', t.pnl != null ? `$${Number(t.pnl).toFixed(2)}` : null],
            ['P&L %', t.pnl_pct != null ? `${Number(t.pnl_pct).toFixed(1)}%` : null],
            ['R Realized', t.r_multiple != null ? `${Number(t.r_multiple).toFixed(2)}R` : null],
            ['Verdict', t.outcome_verdict],
            ['Exit Reason', t.exit_reason],
            ['Closed Via', t.closed_via],
            ['Hold Time', t.hold_time_min != null ? `${t.hold_time_min}min` : null],
            ['Closed At', timeStr(t.closed_at)],
            ['Analyzed', t.post_trade_analyzed ? 'Yes' : 'No'],
            ['Iris Curated', t.iris_curated ? 'Yes' : 'No'],
            ['Aegis Summarized', t.aegis_summarized ? 'Yes' : 'No'],
          ]} />
        </>
      )}

      {/* Journal Review */}
      {t.journal_reviews?.length > 0 && (
        <>
          <div style={sLbl}>JOURNAL REVIEW</div>
          {t.journal_reviews.map((rv: any, i: number) => (
            <div key={i} style={{ padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6, fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, marginBottom: 6 }}>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 6 }}>
                {rv.setup_name && <span>Setup: <strong>{rv.setup_name}</strong></span>}
                {rv.timeframe && <span>Timeframe: {rv.timeframe}</span>}
                {rv.direction && <span>Direction: {rv.direction}</span>}
                {rv.market_regime && <span>Regime: {rv.market_regime}</span>}
                {rv.catalyst_type && <span>Catalyst: {rv.catalyst_type}</span>}
              </div>
              {rv.execution_quality_score && (
                <div style={{ display: 'flex', gap: 12, marginBottom: 6, fontSize: 10 }}>
                  <span>Execution: <strong>{rv.execution_quality_score}/5</strong></span>
                  <span>Sizing: <strong>{rv.sizing_quality_score}/5</strong></span>
                  <span>Risk Mgmt: <strong>{rv.risk_management_score}/5</strong></span>
                  <span>Followed Plan: <strong style={{ color: rv.followed_plan ? 'var(--green)' : 'var(--red)' }}>{rv.followed_plan ? 'Yes' : 'No'}</strong></span>
                </div>
              )}
              {rv.mistake_tags?.length > 0 && (
                <div style={{ marginBottom: 4 }}>
                  {rv.mistake_tags.map((t: string) => <span key={t} style={{ ...pill('red'), marginRight: 4, display: 'inline-block', marginBottom: 2 }}>{t}</span>)}
                </div>
              )}
              {rv.strength_tags?.length > 0 && (
                <div style={{ marginBottom: 4 }}>
                  {rv.strength_tags.map((t: string) => <span key={t} style={{ ...pill('green'), marginRight: 4, display: 'inline-block', marginBottom: 2 }}>{t}</span>)}
                </div>
              )}
              {rv.lesson_learned && <div><strong>Lesson:</strong> {rv.lesson_learned}</div>}
              {rv.review_notes && <div style={{ marginTop: 4 }}><strong>Notes:</strong> {rv.review_notes}</div>}
              {rv.coach_notes && <div style={{ marginTop: 4, color: 'var(--text3)' }}><strong>System fixes:</strong> {rv.coach_notes}</div>}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ── Professional Journal Entry (closed trade detail) ─────────────────────
function JournalEntry({ tradeId }: { tradeId: number }) {
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/v2/journal/trade-detail/${tradeId}`).then(r => r.json())
      .then(d => { if (d.ok) setDetail(d) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tradeId])

  if (loading) return <div style={{ padding: 16, color: 'var(--text3)', fontSize: 11 }}>Loading journal entry...</div>
  if (!detail) return <div style={{ padding: 16, color: 'var(--red)', fontSize: 11 }}>Could not load trade detail</div>

  const cls = detail.classification || {}
  const timing = detail.timing || {}
  const tech = detail.technicals_at_entry || {}
  const risk = detail.risk_execution || {}
  const narr = detail.narrative || {}
  const review = narr.journal_review || {}
  const thesis = narr.thesis_outcome || {}
  const llm = narr.llm_analysis || {}
  const critiques = detail.agent_critiques || []
  const riskActions = detail.risk_actions || []
  const multiTierReviews = detail.multi_tier_reviews || []

  const secLbl: React.CSSProperties = { fontSize: 10, fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8, marginTop: 14 }
  const kvStyle: React.CSSProperties = { fontSize: 11, color: '#E2E8F0' }
  const kvLbl: React.CSSProperties = { fontSize: 9, color: '#64748B', textTransform: 'uppercase' }

  return (
    <div style={{ padding: '16px 20px', background: '#0B1120' }}>
      {/* ── Classification ── */}
      <div style={secLbl}>TRADE CLASSIFICATION</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8, padding: '8px 12px', background: '#0D1626', borderRadius: 6, marginBottom: 8 }}>
        {[
          ['Direction', cls.direction?.toUpperCase()],
          ['Strategy', cls.strategy],
          ['Setup', cls.setup],
          ['Trade Type', cls.intended_type],
          ['Day', cls.day_of_week],
          ['Time', cls.time_of_day?.replace('_', ' ')],
          ['Regime', cls.market_regime],
        ].map(([l, v]) => (
          <div key={l as string}><div style={kvLbl}>{l}</div><div style={kvStyle}>{v || '—'}</div></div>
        ))}
      </div>

      {/* ── Timing ── */}
      <div style={secLbl}>TIMING</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, padding: '8px 12px', background: '#0D1626', borderRadius: 6, marginBottom: 8 }}>
        {[
          ['Entry', timing.entry_time ? new Date(timing.entry_time).toLocaleString() : '—'],
          ['Exit', timing.exit_time ? new Date(timing.exit_time).toLocaleString() : '—'],
          ['Hold Duration', timing.hold_minutes != null ? (timing.hold_minutes < 60 ? `${timing.hold_minutes}min` : `${(timing.hold_minutes / 60).toFixed(1)}h`) : '—'],
        ].map(([l, v]) => (
          <div key={l as string}><div style={kvLbl}>{l}</div><div style={kvStyle}>{v}</div></div>
        ))}
      </div>

      {/* ── Technical State at Entry ── */}
      <div style={secLbl}>TECHNICAL STATE AT ENTRY</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: 8, padding: '8px 12px', background: '#0D1626', borderRadius: 6, marginBottom: 8 }}>
        {[
          ['VIX', tech.vix != null ? Number(tech.vix).toFixed(1) : null],
          ['RVOL', tech.rvol != null ? `${Number(tech.rvol).toFixed(1)}x` : null],
          ['Score', tech.score],
          ['Grade', tech.signal_grade],
          ['Float', tech.float_m != null ? `${Number(tech.float_m).toFixed(0)}M` : null],
          ['Intel', tech.intel_readiness],
          ['Catalyst', tech.catalyst ? (tech.catalyst as string).slice(0, 50) : null],
          ['Verified', tech.catalyst_verified ? 'Yes' : tech.catalyst ? 'No' : null],
        ].map(([l, v]) => (
          <div key={l as string}><div style={kvLbl}>{l}</div><div style={kvStyle}>{v ?? '—'}</div></div>
        ))}
      </div>

      {/* ── Risk & Execution ── */}
      <div style={secLbl}>RISK & EXECUTION</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 8, padding: '8px 12px', background: '#0D1626', borderRadius: 6, marginBottom: 8 }}>
        {[
          ['Planned Entry', risk.planned_entry ? `$${Number(risk.planned_entry).toFixed(2)}` : null],
          ['Actual Entry', risk.actual_entry ? `$${Number(risk.actual_entry).toFixed(2)}` : null],
          ['Slippage', risk.slippage != null ? `$${Number(risk.slippage).toFixed(4)}` : null],
          ['Stop', risk.stop ? `$${Number(risk.stop).toFixed(2)}` : null],
          ['Target', risk.target ? `$${Number(risk.target).toFixed(2)}` : null],
          ['Exit', risk.exit_price ? `$${Number(risk.exit_price).toFixed(2)}` : null],
          ['P&L', risk.pnl != null ? `$${Number(risk.pnl).toFixed(2)}` : null],
          ['R Multiple', risk.r_multiple != null ? `${Number(risk.r_multiple).toFixed(2)}R` : null],
          ['MAE', risk.mae != null ? `${Number(risk.mae).toFixed(1)}%` : null],
          ['MFE', risk.mfe != null ? `${Number(risk.mfe).toFixed(1)}%` : null],
          ['Exit Reason', risk.exit_reason],
          ['Verdict', risk.outcome_verdict],
        ].map(([l, v]) => {
          const isP = l === 'P&L' || l === 'Verdict'
          const color = isP && v ? (v.includes('-') || v === 'LOSS' || v === 'WRONG' ? '#F87171' : v === 'CORRECT' || v === 'WIN' ? '#4ADE80' : '#E2E8F0') : '#E2E8F0'
          return <div key={l as string}><div style={kvLbl}>{l}</div><div style={{ ...kvStyle, color, fontWeight: isP ? 700 : 400 }}>{v ?? '—'}</div></div>
        })}
      </div>

      {/* ── LLM Analysis (What Went Right / Wrong) ── */}
      {llm.summary && (
        <>
          <div style={secLbl}>LLM POST-TRADE ANALYSIS</div>
          <div style={{ padding: '10px 14px', background: '#0D1626', borderRadius: 6, marginBottom: 8, borderLeft: '3px solid #60A5FA' }}>
            <div style={{ fontSize: 12, color: '#E2E8F0', lineHeight: 1.6, marginBottom: 8 }}>{llm.summary}</div>
            {llm.worked_reasons && (() => { try { const r = typeof llm.worked_reasons === 'string' ? JSON.parse(llm.worked_reasons) : llm.worked_reasons; return r.length > 0 ? <div style={{ marginBottom: 6 }}><span style={{ fontSize: 10, color: '#4ADE80', fontWeight: 600 }}>What worked:</span>{r.map((x: string, i: number) => <div key={i} style={{ fontSize: 11, color: '#94A3B8', paddingLeft: 8 }}>+ {x}</div>)}</div> : null } catch { return null } })()}
            {llm.failed_reasons && (() => { try { const r = typeof llm.failed_reasons === 'string' ? JSON.parse(llm.failed_reasons) : llm.failed_reasons; return r.length > 0 ? <div style={{ marginBottom: 6 }}><span style={{ fontSize: 10, color: '#F87171', fontWeight: 600 }}>What failed:</span>{r.map((x: string, i: number) => <div key={i} style={{ fontSize: 11, color: '#94A3B8', paddingLeft: 8 }}>- {x}</div>)}</div> : null } catch { return null } })()}
            {llm.lessons && (() => { try { const r = typeof llm.lessons === 'string' ? JSON.parse(llm.lessons) : llm.lessons; return r.length > 0 ? <div><span style={{ fontSize: 10, color: '#F59E0B', fontWeight: 600 }}>Lessons:</span>{r.map((x: string, i: number) => <div key={i} style={{ fontSize: 11, color: '#94A3B8', paddingLeft: 8 }}>{x}</div>)}</div> : null } catch { return null } })()}
            <div style={{ fontSize: 9, color: '#475569', marginTop: 6 }}>Model: {llm.model_used} | Confidence: {llm.confidence != null ? `${(Number(llm.confidence) * 100).toFixed(0)}%` : '—'}</div>
          </div>
        </>
      )}

      {/* ── Agent Critiques ── */}
      {critiques.length > 0 && (
        <>
          <div style={secLbl}>AGENT CRITIQUES ({critiques.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
            {critiques.map((ev: any, i: number) => (
              <div key={i} style={{ padding: '8px 12px', background: '#0D1626', borderRadius: 6, borderLeft: `3px solid ${ev.agent_name === 'Iris' ? '#A78BFA' : ev.agent_name === 'Aegis' ? '#60A5FA' : ev.agent_name === 'local_llm' ? '#F59E0B' : '#94A3B8'}` }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: ev.agent_name === 'Iris' ? '#A78BFA' : ev.agent_name === 'Aegis' ? '#60A5FA' : '#F59E0B' }}>{ev.agent_name}</span>
                  <span style={{ fontSize: 9, color: '#475569' }}>{ev.event_type}</span>
                </div>
                <div style={{ fontSize: 11, color: '#CBD5E1', lineHeight: 1.5 }}>{ev.event_summary}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Journal Review (Lessons + Mistakes + Strengths) ── */}
      {review.lesson_learned && (
        <>
          <div style={secLbl}>JOURNAL REVIEW</div>
          <div style={{ padding: '10px 14px', background: '#0D1626', borderRadius: 6, marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: '#E2E8F0', lineHeight: 1.6, marginBottom: 8 }}>{review.lesson_learned}</div>
            {review.review_notes && <div style={{ fontSize: 11, color: '#94A3B8', lineHeight: 1.5, marginBottom: 8 }}>{review.review_notes}</div>}
            {review.coach_notes && <div style={{ fontSize: 11, color: '#60A5FA', lineHeight: 1.5, marginBottom: 8, borderLeft: '2px solid #60A5FA', paddingLeft: 8 }}>{review.coach_notes}</div>}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {(typeof review.mistake_tags === 'string' ? (() => { try { return JSON.parse(review.mistake_tags) } catch { return [] } })() : review.mistake_tags || []).map((t: string) => (
                <span key={t} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: 'rgba(248,113,113,0.15)', color: '#F87171', fontWeight: 600 }}>{t}</span>
              ))}
              {(typeof review.strength_tags === 'string' ? (() => { try { return JSON.parse(review.strength_tags) } catch { return [] } })() : review.strength_tags || []).map((t: string) => (
                <span key={t} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: 'rgba(74,222,128,0.15)', color: '#4ADE80', fontWeight: 600 }}>{t}</span>
              ))}
            </div>
          </div>
        </>
      )}

      {/* ── Risk Actions Timeline ── */}
      {riskActions.length > 0 && (
        <>
          <div style={secLbl}>RISK ACTIONS ({riskActions.length})</div>
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {riskActions.map((a: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid #1E293B', fontSize: 11 }}>
                <span style={{ minWidth: 100, color: '#475569', fontSize: 10 }}>{a.created_at ? new Date(a.created_at).toLocaleString() : '—'}</span>
                <span style={{ color: a.action_type?.includes('close') ? '#F87171' : '#60A5FA', fontWeight: 600, fontSize: 10, minWidth: 80 }}>{a.action_type}</span>
                <span style={{ color: '#CBD5E1', flex: 1 }}>{a.trigger_reason}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Multi-Tier LLM Reviews ── */}
      {multiTierReviews.length > 0 && (
        <>
          <div style={secLbl}>MULTI-TIER REVIEWS ({multiTierReviews.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {multiTierReviews.map((r: any, i: number) => {
              const tierColor: Record<string, string> = { realtime: '#60A5FA', overnight: '#A78BFA', weekly: '#4ADE80', monthly: '#F59E0B' }
              const commentaries = typeof r.agent_commentaries === 'string' ? (() => { try { return JSON.parse(r.agent_commentaries) } catch { return {} } })() : r.agent_commentaries || {}
              return (
                <div key={i} style={{ padding: '10px 14px', background: '#0D1626', borderRadius: 6, borderLeft: `3px solid ${tierColor[r.tier] || '#94A3B8'}` }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: tierColor[r.tier] || '#94A3B8', textTransform: 'uppercase' }}>{r.tier}</span>
                    <span style={{ fontSize: 9, color: '#475569' }}>{r.model_used}</span>
                    <span style={{ fontSize: 9, color: '#475569', marginLeft: 'auto' }}>{r.created_at ? new Date(r.created_at).toLocaleString() : ''}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#CBD5E1', lineHeight: 1.6, marginBottom: 8 }}>{r.review_text}</div>
                  {Object.keys(commentaries).length > 0 && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      {Object.entries(commentaries).map(([agent, comment]) => (
                        <div key={agent} style={{ padding: '6px 8px', background: '#0B1120', borderRadius: 4, fontSize: 10 }}>
                          <div style={{ color: '#64748B', fontWeight: 600, marginBottom: 2, textTransform: 'uppercase', fontSize: 9 }}>{agent.replace('_', ' ')}</div>
                          <div style={{ color: '#94A3B8', lineHeight: 1.4 }}>{String(comment).slice(0, 200)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

// ── Calendar P&L Heatmap ──────────────────────────────────────────────────
function CalendarPL({ daily }: { daily: any[] }) {
  if (!daily.length) return <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }}>No closed trades yet.</div>

  // Group by month
  const byMonth: Record<string, any[]> = {}
  for (const d of daily) {
    const m = d.date.slice(0, 7) // YYYY-MM
    byMonth[m] = byMonth[m] || []
    byMonth[m].push(d)
  }

  const maxPnl = Math.max(1, ...daily.map(d => Math.abs(d.daily_pnl)))

  return (
    <div>
      {Object.entries(byMonth).map(([month, days]) => {
        const firstDay = new Date(days[0].date + 'T00:00')
        const monthLabel = firstDay.toLocaleString('en-US', { month: 'long', year: 'numeric' })
        // Build day lookup
        const dayMap: Record<number, any> = {}
        for (const d of days) {
          const day = new Date(d.date + 'T00:00').getDate()
          dayMap[day] = d
        }
        // Get days in month
        const yr = firstDay.getFullYear()
        const mo = firstDay.getMonth()
        const daysInMonth = new Date(yr, mo + 1, 0).getDate()
        const startDow = new Date(yr, mo, 1).getDay()

        const cells = []
        // Empty cells for offset
        for (let i = 0; i < startDow; i++) cells.push(<div key={`e${i}`} style={{ width: 28, height: 28 }} />)
        for (let day = 1; day <= daysInMonth; day++) {
          const d = dayMap[day]
          const isWeekend = new Date(yr, mo, day).getDay() % 6 === 0
          let bg = 'var(--bg0)'
          let color = 'var(--text3)'
          if (d) {
            const intensity = Math.min(1, Math.abs(d.daily_pnl) / maxPnl)
            const alpha = 0.2 + intensity * 0.6
            bg = d.daily_pnl > 0 ? `rgba(72,187,120,${alpha})` : `rgba(248,113,113,${alpha})`
            color = 'var(--text0)'
          }
          cells.push(
            <div key={day} title={d ? `${d.date}: $${d.daily_pnl.toFixed(2)} (${d.trades} trades, ${d.wins}W ${d.losses}L)` : `Day ${day}`}
              style={{
                width: 28, height: 28, borderRadius: 4, display: 'flex', alignItems: 'center',
                justifyContent: 'center', fontSize: 9, color, background: bg,
                opacity: isWeekend && !d ? 0.3 : 1, cursor: d ? 'pointer' : 'default',
                border: d ? '1px solid rgba(255,255,255,0.1)' : 'none',
              }}>
              {day}
            </div>
          )
        }

        return (
          <div key={month} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text2)', fontWeight: 600, marginBottom: 4 }}>{monthLabel}</div>
            <div style={{ display: 'flex', gap: 2, marginBottom: 2 }}>
              {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
                <div key={i} style={{ width: 28, textAlign: 'center', fontSize: 8, color: 'var(--text3)' }}>{d}</div>
              ))}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>{cells}</div>
          </div>
        )
      })}
    </div>
  )
}

// ── Analytics Section ─────────────────────────────────────────────────────
function AnalyticsSection({ account, closedTrades }: { account: string; closedTrades?: any[] }) {
  const [analytics, setAnalytics] = useState<any>(null)

  useEffect(() => {
    fetch(`/api/v2/paper-analytics`)
      .then(r => r.json())
      .then(d => { if (d.ok) setAnalytics(d) })
      .catch(() => {})
  }, [account])

  if (!analytics) return null

  const eq = analytics.equity_curve || []
  const monthly = analytics.monthly || []
  const weekly = analytics.weekly || []

  // Build daily from closed trades if analytics endpoint doesn't provide it
  let daily = analytics.daily || []
  if (daily.length === 0 && closedTrades && closedTrades.length > 0) {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedTrades) {
      const dateStr = (t.closed_at || '').slice(0, 10)
      if (!dateStr) continue
      if (!byDate[dateStr]) byDate[dateStr] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[dateStr].pnl += (t.pnl ?? 0)
      byDate[dateStr].trades += 1
      if ((t.pnl ?? 0) > 0) byDate[dateStr].wins += 1
      else if ((t.pnl ?? 0) < 0) byDate[dateStr].losses += 1
    }
    daily = Object.entries(byDate).map(([date, v]) => ({
      trade_date: date, daily_pnl: v.pnl, trades: v.trades, wins: v.wins, losses: v.losses,
    })).sort((a, b) => a.trade_date.localeCompare(b.trade_date))
  }

  const hasData = eq.length > 0
  const byStrategy = (analytics.by_strategy || []).filter((s: any) => (s.trades || 0) > 0 || (s.wins || 0) > 0)

  // Equity curve chart data
  const equityData = {
    labels: eq.map((d: any) => d.date.slice(5)), // MM-DD
    datasets: [
      {
        label: 'Cumulative P&L',
        data: eq.map((d: any) => d.cumulative_pnl),
        borderColor: eq.length > 0 && eq[eq.length - 1].cumulative_pnl >= 0 ? '#4ADE80' : '#F87171',
        backgroundColor: eq.length > 0 && eq[eq.length - 1].cumulative_pnl >= 0 ? 'rgba(72,187,120,0.1)' : 'rgba(248,113,113,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 6,
      },
    ],
  }

  const equityOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { tooltip: { backgroundColor: '#0F172A', titleColor: '#E2E8F0', bodyColor: '#94A3B8', borderColor: '#1E293B', borderWidth: 1 } },
    scales: {
      x: { ticks: { color: '#64748B', font: { size: 9 } }, grid: { color: '#1E293B' } },
      y: { ticks: { color: '#64748B', font: { size: 9 }, callback: (v: any) => `$${v}` }, grid: { color: '#1E293B' } },
    },
  }

  // Daily P&L bar chart
  const dailyBarData = {
    labels: eq.map((d: any) => d.date.slice(5)),
    datasets: [{
      label: 'Daily P&L',
      data: eq.map((d: any) => d.daily_pnl),
      backgroundColor: eq.map((d: any) => d.daily_pnl >= 0 ? 'rgba(72,187,120,0.7)' : 'rgba(248,113,113,0.7)'),
      borderRadius: 3,
    }],
  }

  const barOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { tooltip: { backgroundColor: '#0F172A', titleColor: '#E2E8F0', bodyColor: '#94A3B8' } },
    scales: {
      x: { ticks: { color: '#64748B', font: { size: 9 } }, grid: { display: false } },
      y: { ticks: { color: '#64748B', font: { size: 9 }, callback: (v: any) => `$${v}` }, grid: { color: '#1E293B' } },
    },
  }

  return (
    <>
      {hasData && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          {/* Equity Curve */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
            <SectionHeader title="Equity Curve" />
            <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>REALIZED</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor(analytics.realized_total), ...mono }}>{fmt$(analytics.realized_total, 2)}</div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>UNREALIZED</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor(analytics.unrealized_total), ...mono }}>{fmt$(analytics.unrealized_total, 2)}</div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>TOTAL EQUITY</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: pnlColor(analytics.current_equity), ...mono }}>{fmt$(analytics.current_equity, 2)}</div>
              </div>
            </div>
            <div style={{ height: 200 }}>
              <Line data={equityData} options={equityOpts as any} />
            </div>
          </div>

          {/* Daily P&L Bar */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
            <SectionHeader title="Daily P&L" />
            <div style={{ height: 250 }}>
              <Bar data={dailyBarData} options={barOpts as any} />
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: hasData ? '1fr 1fr' : '1fr', gap: 14, marginBottom: 14 }}>
        {/* Calendar Heatmap */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <SectionHeader title="Calendar P&L" />
          <CalendarPL daily={daily.map((d: any) => ({ date: d.trade_date, daily_pnl: d.daily_pnl, trades: d.trades, wins: d.wins, losses: d.losses }))} />
        </div>

        {/* Monthly Summary */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <SectionHeader title="Monthly Summary" />
          {monthly.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }}>No monthly data yet.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Month', 'Trades', 'W/L', 'Win %', 'P&L', 'Avg R', 'Best', 'Worst'].map(h => (
                    <th key={h} style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', padding: '5px 6px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {monthly.map((m: any) => {
                  const wr = m.trades > 0 ? Math.round((m.wins / m.trades) * 100) : 0
                  return (
                    <tr key={m.month}>
                      <td style={{ padding: '4px 6px', fontSize: 11, color: 'var(--text1)', ...mono }}>{m.month}</td>
                      <td style={{ padding: '4px 6px', fontSize: 11, ...mono }}>{m.trades}</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--text2)' }}>{m.wins}W / {m.losses}L</td>
                      <td style={{ padding: '4px 6px', fontSize: 11, color: wr >= 50 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{wr}%</td>
                      <td style={{ padding: '4px 6px', fontSize: 11, color: pnlColor(m.total_pnl), fontWeight: 600, ...mono }}>{fmt$(m.total_pnl, 2)}</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, ...mono, color: pnlColor(m.avg_r) }}>{m.avg_r != null ? `${m.avg_r}R` : '--'}</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--green)', ...mono }}>{fmt$(m.best_trade, 2)}</td>
                      <td style={{ padding: '4px 6px', fontSize: 10, color: 'var(--red)', ...mono }}>{fmt$(m.worst_trade, 2)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}

          {/* Weekly breakdown */}
          {weekly.length > 0 && (
            <>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 600, marginTop: 14, marginBottom: 6 }}>WEEKLY</div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['Week', 'Trades', 'Wins', 'P&L', 'Avg R'].map(h => (
                      <th key={h} style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', padding: '4px 6px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {weekly.map((w: any) => (
                    <tr key={w.week_start}>
                      <td style={{ padding: '3px 6px', fontSize: 10, ...mono, color: 'var(--text2)' }}>{w.week_start}</td>
                      <td style={{ padding: '3px 6px', fontSize: 10, ...mono }}>{w.trades}</td>
                      <td style={{ padding: '3px 6px', fontSize: 10, color: 'var(--green)' }}>{w.wins}</td>
                      <td style={{ padding: '3px 6px', fontSize: 10, color: pnlColor(w.total_pnl), fontWeight: 600, ...mono }}>{fmt$(w.total_pnl, 2)}</td>
                      <td style={{ padding: '3px 6px', fontSize: 10, ...mono, color: pnlColor(w.avg_r) }}>{w.avg_r != null ? `${w.avg_r}R` : '--'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>

      {/* Strategy Breakdown Table */}
      {byStrategy.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <SectionHeader title="Strategy Breakdown" />
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>
                {['Strategy', 'Trades', 'Wins', 'Losses', 'P&L'].map(h => (
                  <th key={h} style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {byStrategy.map((s: any) => (
                <tr key={s.strategy_id}>
                  <td style={{ padding: '5px 8px', fontWeight: 600, color: 'var(--text0)' }}>{s.strategy_id}</td>
                  <td style={{ padding: '5px 8px', ...mono }}>{s.trades || 0}</td>
                  <td style={{ padding: '5px 8px', ...mono, color: 'var(--green)' }}>{s.wins || 0}</td>
                  <td style={{ padding: '5px 8px', ...mono, color: 'var(--red)' }}>{(s.trades || 0) - (s.wins || 0)}</td>
                  <td style={{ padding: '5px 8px', ...mono, fontWeight: 600, color: pnlColor(s.pnl) }}>{s.pnl != null ? fmt$(s.pnl, 2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// ── Governance Sub-tab ────────────────────────────────────────────────────
function GovernanceSubTab({ journalStats }: { journalStats: any }) {
  const [govData, setGovData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    fetch('/api/v2/paper-performance-governance')
      .then(r => r.json())
      .then(d => setGovData(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const gov = govData?.data || govData || []
  const govArray = Array.isArray(gov) ? gov : []
  // Use parent journal stats as primary source
  const jOpen = journalStats?.open ?? 0
  const jClosed = journalStats?.closed ?? 0
  const totalOpen = jOpen || govArray.reduce((s: number, g: any) => s + (g.paper_trades || 0) - (g.closed_trades || 0), 0)
  const totalClosed = jClosed || govArray.reduce((s: number, g: any) => s + (g.closed_trades || 0), 0)
  const strategiesWithData = govArray.filter((g: any) => (g.paper_trades || 0) > 0).length
  const liveEligible = govArray.filter((g: any) => g.live_eligible).length
  const reconIssues = govArray.filter((g: any) => g.recon_issues > 0).length

  const runCheck = async () => {
    setRunning(true)
    try {
      await fetch('/api/v2/paper-performance-governance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      window.location.reload()
    } catch { /* ignore */ }
    setRunning(false)
  }

  if (loading) return <div style={{ padding: 20, color: 'var(--text3)', fontSize: 12 }}>Loading governance data...</div>

  return (
    <div>
      {/* Banner */}
      <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 16 }}>🛑</span>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#EF4444' }}>LIVE TRADING DISABLED</div>
          <div style={{ fontSize: 10, color: '#94A3B8' }}>Paper validation gates must pass before live trading is enabled for any strategy.</div>
        </div>
      </div>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 14 }}>
        {[
          { label: 'Open Trades', value: totalOpen },
          { label: 'Closed Trades', value: totalClosed },
          { label: 'Strategies', value: strategiesWithData },
          { label: 'Live Eligible', value: liveEligible, color: liveEligible > 0 ? 'var(--green)' : 'var(--red)' },
          { label: 'Outcome Reviews', value: govArray.filter((g: any) => g.outcome_reviews > 0).length },
          { label: 'Recon Issues', value: reconIssues, color: reconIssues > 0 ? 'var(--red)' : 'var(--green)' },
        ].map(s => (
          <div key={s.label} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: s.color || 'var(--text0)', fontFamily: 'monospace' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Run button */}
      <div style={{ marginBottom: 14 }}>
        <button onClick={runCheck} disabled={running}
          style={{ padding: '6px 16px', fontSize: 11, fontWeight: 600, border: '1px solid var(--accent)', borderRadius: 6, background: 'rgba(74,144,244,0.1)', color: 'var(--accent)', cursor: running ? 'wait' : 'pointer', fontFamily: 'monospace' }}>
          {running ? 'Running...' : 'Run Governance Check'}
        </button>
      </div>

      {/* Strategy gates */}
      {govArray.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Strategy Validation Status</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>
                {['Strategy', 'Trades', 'Closed', 'Win Rate', 'PF', 'Eligible'].map(h => (
                  <th key={h} style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {govArray.filter((g: any) => g.paper_trades > 0).map((g: any) => (
                <tr key={g.strategy_id}>
                  <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text0)' }}>{g.strategy_id}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{g.paper_trades}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{g.closed_trades}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace', color: (g.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)' }}>{g.win_rate != null ? `${g.win_rate}%` : '--'}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{g.profit_factor != null ? g.profit_factor.toFixed(2) : '--'}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                      background: g.live_eligible ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                      color: g.live_eligible ? 'var(--green)' : 'var(--red)' }}>
                      {g.live_eligible ? 'YES' : 'NO'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Performance Sub-tab ──────────────────────────────────────────────────
function PerformanceSubTab({ journalStats }: { journalStats: any }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/v2/paper-automation-performance')
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ padding: 20, color: 'var(--text3)', fontSize: 12 }}>Loading performance data...</div>

  const perf = data?.data || data?.performance || {}
  const bySource = perf.by_source || perf.by_automation_source || []
  const recentGrades = perf.recent_grades || perf.grade_trend || []
  const sampleSize = journalStats?.closed ?? perf.total_closed ?? perf.sample_size ?? 0

  return (
    <div>
      {sampleSize < 10 && (
        <div style={{ padding: '12px 16px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 8, marginBottom: 14, fontSize: 11, color: '#F59E0B' }}>
          Sample size: {sampleSize} closed trades. Accuracy metrics become reliable after 10+ closed trades.
        </div>
      )}

      {/* By automation source */}
      {(Array.isArray(bySource) ? bySource : Object.entries(bySource).map(([k, v]: [string, any]) => ({ source: k, ...v }))).length > 0 ? (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Performance by Automation Source</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>
                {['Source', 'Trades', 'Win Rate', 'P&L', 'Avg R'].map(h => (
                  <th key={h} style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(Array.isArray(bySource) ? bySource : Object.entries(bySource).map(([k, v]: [string, any]) => ({ source: k, ...v }))).map((s: any) => (
                <tr key={s.source || s.automation_source}>
                  <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text0)' }}>{(s.source || s.automation_source || '').replace(/_/g, ' ')}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{s.count || s.trades || 0}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace', color: (s.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)' }}>{s.win_rate != null ? `${s.win_rate}%` : '--'}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace', color: (s.total_pnl ?? s.pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{fmt$(s.total_pnl ?? s.pnl ?? 0, 2)}</td>
                  <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{s.avg_r != null ? `${Number(s.avg_r).toFixed(2)}R` : '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No automation performance data available yet.</div>
      )}

      {/* Grade trend */}
      {recentGrades.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Recent Trade Grades (last 10)</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {recentGrades.slice(-10).map((g: any, i: number) => {
              const grade = g.grade || g.overall_grade || '--'
              const gradeColor: Record<string, string> = { A: '#4ADE80', B: '#60A5FA', C: '#F59E0B', D: '#F87171' }
              return (
                <div key={i} style={{ background: 'var(--bg0)', borderRadius: 6, padding: '6px 10px', border: '1px solid var(--border)', textAlign: 'center', minWidth: 50 }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: gradeColor[grade] || 'var(--text3)' }}>{grade}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{g.symbol || ''}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Inner Tab Bar ────────────────────────────────────────────────────────
const INNER_TABS = ['Journal', 'Analytics', 'Governance', 'Performance'] as const
type InnerTab = typeof INNER_TABS[number]

export default function AutomatedTradeJournal() {
  const [data, setData] = useState<any>(null)
  const [analyticsData, setAnalyticsData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState('ALPACA_PAPER')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [innerTab, setInnerTab] = useState<InnerTab>('Journal')

  const fetchData = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/v2/paper-journal').then(r => r.json()).catch(() => null),
      fetch('/api/v2/paper-analytics').then(r => r.json()).catch(() => null),
    ]).then(([journal, analytics]) => {
      setData(journal)
      setAnalyticsData(analytics)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    fetchData()
    const iv = setInterval(fetchData, 30000)
    return () => clearInterval(iv)
  }, [fetchData])

  const stats = data?.stats || {}
  const openTrades = data?.open_trades || []
  const closedTrades = data?.closed_trades || []
  const unrealizedPnl = analyticsData?.overall?.total_unrealized_pnl

  return (
    <>
      <PageHeader title="Automated Journal" subtitle="Automated trading log — Alpaca paper trades, bot-executed positions, and validation progress" actions={
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select value={account} onChange={e => setAccount(e.target.value)}
            style={{ background: 'var(--bg1)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 10px', fontSize: 10 }}>
            <option value="ALPACA_PAPER">Alpaca Paper</option>
          </select>
          {data?.alpaca_connected && <span style={pill('green')}>ALPACA LIVE</span>}
          {data?.alpaca_connected === false && <span style={pill('red')}>ALPACA OFFLINE</span>}
          <button onClick={fetchData} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
        </div>
      } />

      {/* Inner tab bar */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 14, borderBottom: '1px solid var(--border)' }}>
        {INNER_TABS.map(tab => (
          <button key={tab} onClick={() => setInnerTab(tab)}
            style={{
              padding: '6px 14px', fontSize: 11, fontWeight: innerTab === tab ? 600 : 400, cursor: 'pointer',
              color: innerTab === tab ? '#60A5FA' : 'var(--text3)',
              background: 'none', border: 'none',
              borderBottom: innerTab === tab ? '2px solid #60A5FA' : '2px solid transparent',
              marginBottom: -1, transition: 'all 0.15s ease',
            }}>
            {tab}
          </button>
        ))}
      </div>

      {/* ── Journal sub-tab (default) ── */}
      {innerTab === 'Journal' && (
        <>
          {/* Stats Tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 10, marginBottom: 14 }}>
            <MetricTile label="Open" value={stats.open ?? 0} />
            <MetricTile label="Closed" value={stats.closed ?? 0} />
            <MetricTile label="Wins" value={stats.wins ?? 0} deltaColor="var(--green)" />
            <MetricTile label="Losses" value={stats.losses ?? 0} deltaColor="var(--red)" />
            <MetricTile label="Win Rate" value={stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(0)}%` : '--'}
              deltaColor={(stats.win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--red)'} />
            <MetricTile label="Avg R" value={analyticsData?.overall?.avg_r != null ? `${Number(analyticsData.overall.avg_r).toFixed(2)}R` : '--'}
              deltaColor={pnlColor(analyticsData?.overall?.avg_r)} />
            <MetricTile label="Realized P&L" value={stats.total_pnl != null ? fmt$(stats.total_pnl, 2) : '--'}
              deltaColor={pnlColor(stats.total_pnl)} />
            <MetricTile label="Unrealized" value={unrealizedPnl != null ? fmt$(unrealizedPnl, 2) : '--'}
              deltaColor={pnlColor(unrealizedPnl)} />
          </div>

          {/* Strategy Breakdown */}
          {analyticsData?.by_strategy?.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
              <SectionHeader title="Strategy Performance" />
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', padding: '6px 0' }}>
                {analyticsData.by_strategy.filter((s: any) => (s.trades || s.count || 0) > 0).map((s: any) => (
                  <div key={s.strategy_id || s.strategy} style={{ background: 'var(--bg0)', borderRadius: 6, padding: '8px 14px', border: '1px solid var(--border)', minWidth: 150 }}>
                    <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>{s.strategy_id || s.strategy}</div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 11, marginTop: 4 }}>
                      <span>{s.trades || s.count || 0} trades</span>
                      <span style={{ color: pnlColor(s.pnl) }}>{fmt$(s.pnl ?? 0, 0)}</span>
                      <span>{s.wins || 0}W</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {loading && <div style={{ padding: 20, color: 'var(--text3)' }}>Loading...</div>}

          {/* Open Trades */}
          {openTrades.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
              <SectionHeader title={`Open Positions (${openTrades.length})`} />
              {openTrades.map((t: any) => {
                const isExpanded = expandedId === t.id
                const alpaca = t.alpaca || {}
                const livePrice = alpaca.alpaca_current_price || t.current_price
                const livePnl = alpaca.alpaca_unrealized_pl ?? t.unrealized_pnl
                return (
                  <div key={t.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <div onClick={() => setExpandedId(isExpanded ? null : t.id)}
                      style={{ padding: '8px 12px', cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{isExpanded ? '▼' : '▶'}</span>
                      <span style={{ fontWeight: 700, ...mono, minWidth: 50, color: 'var(--text0)' }}>{t.symbol}</span>
                      <span style={pill('blue')}>{t.strategy_id}</span>
                      <span style={{ ...mono, fontSize: 10, color: 'var(--text2)' }}>Entry: {fmt$(t.entry_price, 2)}</span>
                      <span style={{ ...mono, fontSize: 10, color: 'var(--red)' }}>Stop: {fmt$(t.stop_loss, 2)}</span>
                      <span style={{ ...mono, fontSize: 10, color: 'var(--green)' }}>Target: {fmt$(t.target_1, 2)}</span>
                      <span style={{ ...mono, fontSize: 10, color: 'var(--text3)' }}>{t.shares}sh</span>
                      {t.broker_status && <span style={pill(t.broker_status === 'filled' ? 'green' : 'amber')}>{t.broker_status}</span>}
                      <span style={pill('blue')}>ALPACA</span>
                      <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, alignItems: 'center' }}>
                        <span style={{ ...mono, fontSize: 11, color: 'var(--text2)' }}>${livePrice?.toFixed(2) || '--'}</span>
                        <span style={{ ...mono, fontSize: 12, fontWeight: 700, color: pnlColor(livePnl) }}>
                          {livePnl != null ? `$${livePnl >= 0 ? '+' : ''}${livePnl.toFixed(2)}` : '--'}
                        </span>
                        <span style={{ ...mono, fontSize: 10, color: pnlColor(t.r_multiple) }}>
                          {t.r_multiple != null ? `${t.r_multiple >= 0 ? '+' : ''}${Number(t.r_multiple).toFixed(1)}R` : ''}
                        </span>
                      </div>
                    </div>
                    {isExpanded && <TradeExpansion trade={t} />}
                  </div>
                )
              })}
            </div>
          )}

          {/* Closed Trades */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
            <SectionHeader title={`Closed Trades (${closedTrades.length})`} />
            {closedTrades.length === 0 ? (
              <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No closed trades yet</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['', 'Symbol', 'Strategy', 'Entry', 'Exit', 'Shares', 'P&L', 'R', 'Verdict', 'Exit Reason', 'Iris', 'Aegis', 'RAG', 'Events', 'Date'].map(h => (
                        <th key={h} style={thStyle}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closedTrades.map((t: any, i: number) => {
                      const isExpanded = expandedId === t.id
                      const verdict = t.outcome_verdict || (t.pnl > 0 ? 'WIN' : t.pnl < 0 ? 'LOSS' : '--')
                      return (
                        <tbody key={t.id}>
                          <tr onClick={() => setExpandedId(isExpanded ? null : t.id)}
                            style={{ background: isExpanded ? 'rgba(59,130,246,0.08)' : i % 2 ? 'var(--bg0)' : 'transparent', cursor: 'pointer' }}>
                            <td style={{ ...tdStyle, width: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 10 }}>{isExpanded ? '▲' : '▼'}</td>
                            <td style={{ ...tdStyle, fontWeight: 700, ...mono }}>{t.symbol}</td>
                            <td style={{ ...tdStyle, fontSize: 10, color: 'var(--text2)' }}>{t.strategy_id}</td>
                            <td style={{ ...tdStyle, ...mono }}>{fmt$(t.entry_price, 2)}</td>
                            <td style={{ ...tdStyle, ...mono }}>{fmt$(t.exit_price, 2)}</td>
                            <td style={{ ...tdStyle, ...mono, fontSize: 10 }}>{t.shares || '--'}</td>
                            <td style={{ ...tdStyle, ...mono, color: pnlColor(t.pnl), fontWeight: 600 }}>{t.pnl != null ? fmt$(t.pnl, 2) : '--'}</td>
                            <td style={{ ...tdStyle, ...mono, color: pnlColor(t.r_multiple) }}>{t.r_multiple != null ? `${Number(t.r_multiple).toFixed(2)}R` : '--'}</td>
                            <td style={tdStyle}><span style={pill(verdict === 'WIN' || verdict === 'CORRECT' ? 'green' : verdict === 'LOSS' || verdict === 'WRONG' ? 'red' : 'amber')}>{verdict}</span></td>
                            <td style={{ ...tdStyle, fontSize: 9, color: 'var(--text3)' }}>{(t.exit_reason || '').slice(0, 30)}</td>
                            <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.iris_curated ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.iris_curated ? '✓' : '-'}</span></td>
                            <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.aegis_summarized ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.aegis_summarized ? '✓' : '-'}</span></td>
                            <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.post_trade_analyzed ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.post_trade_analyzed ? '✓' : '-'}</span></td>
                            <td style={{ ...tdStyle, textAlign: 'center', ...mono, fontSize: 10 }}>{t.execution_log?.length || 0}</td>
                            <td style={{ ...tdStyle, fontSize: 9, color: 'var(--text3)', ...mono }}>{(t.closed_at || '').slice(0, 10) || '--'}</td>
                          </tr>
                          {isExpanded && (
                            <tr><td colSpan={15} style={{ padding: 0, borderBottom: '2px solid var(--border)' }}>
                              <JournalEntry tradeId={t.id} />
                            </td></tr>
                          )}
                        </tbody>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Analytics sub-tab ── */}
      {innerTab === 'Analytics' && (
        <>
          {(stats.closed ?? 0) < 10 && (
            <div style={{ padding: '12px 16px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 8, marginBottom: 14, fontSize: 11, color: '#F59E0B' }}>
              Accumulating data — full analytics available after 10+ closed trades. Currently {stats.closed ?? 0} closed.
            </div>
          )}
          <AnalyticsSection account={account} closedTrades={closedTrades} />
        </>
      )}

      {/* ── Governance sub-tab ── */}
      {innerTab === 'Governance' && <GovernanceSubTab journalStats={stats} />}

      {/* ── Performance sub-tab ── */}
      {innerTab === 'Performance' && <PerformanceSubTab journalStats={stats} />}
    </>
  )
}
