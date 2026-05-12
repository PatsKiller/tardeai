import { useState, useEffect, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { fmt$, fmtPct } from '../lib/format'

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

export default function AutomatedTradeJournal() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState('ALPACA_PAPER')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const fetchData = useCallback(() => {
    setLoading(true)
    fetch(`/api/v2/automated-trade-journal?account=${account}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [account])

  useEffect(() => {
    fetchData()
    const iv = setInterval(fetchData, 30000) // refresh every 30s for real-time
    return () => clearInterval(iv)
  }, [fetchData])

  const summary = data?.summary || {}
  const openTrades = data?.open || []
  const closedTrades = data?.closed || []

  return (
    <>
      <PageHeader title="Automated Journal" subtitle={`${account.replace('_', ' ')} — real-time execution log and trade lifecycle`} actions={
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

      {/* Stats Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Open" value={summary.open_count ?? 0} />
        <MetricTile label="Closed" value={summary.closed_count ?? 0} />
        <MetricTile label="Wins" value={summary.wins ?? 0} deltaColor="var(--green)" />
        <MetricTile label="Losses" value={summary.losses ?? 0} deltaColor="var(--red)" />
        <MetricTile label="Win Rate" value={summary.win_rate != null ? `${summary.win_rate}%` : '--'}
          deltaColor={(summary.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)'} />
        <MetricTile label="Avg R" value={summary.avg_r != null ? `${summary.avg_r}R` : '--'}
          deltaColor={(summary.avg_r ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'} />
        <MetricTile label="Realized P&L" value={summary.total_pnl != null ? fmt$(summary.total_pnl, 2) : '--'}
          deltaColor={pnlColor(summary.total_pnl)} />
        <MetricTile label="Unrealized" value={summary.unrealized_pnl != null ? fmt$(summary.unrealized_pnl, 2) : '--'}
          deltaColor={pnlColor(summary.unrealized_pnl)} />
      </div>

      {/* Strategy Breakdown */}
      {summary.by_strategy?.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <SectionHeader title="Strategy Performance" />
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', padding: '6px 0' }}>
            {summary.by_strategy.map((s: any) => (
              <div key={s.strategy} style={{ background: 'var(--bg0)', borderRadius: 6, padding: '8px 14px', border: '1px solid var(--border)', minWidth: 150 }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>{s.strategy}</div>
                <div style={{ display: 'flex', gap: 8, fontSize: 11, marginTop: 4 }}>
                  <span>{s.count} trades</span>
                  <span style={{ color: pnlColor(s.pnl) }}>{fmt$(s.pnl, 0)}</span>
                  <span>{s.win_rate}% WR</span>
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
                          <TradeExpansion trade={t} />
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
  )
}
