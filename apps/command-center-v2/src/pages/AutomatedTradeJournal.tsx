import { useState, useEffect } from 'react'

const COLORS = {
  bg: '#1A202C', card: '#2D3748', border: '#4A5568',
  text: '#E2E8F0', muted: '#A0AEC0', accent: '#4A90F4',
  green: '#48BB78', red: '#FC8181', orange: '#F6AD55',
}
const mono: React.CSSProperties = { fontFamily: 'monospace' }

interface Trade {
  id: number; symbol: string; strategy_id: string; account: string
  entry_price: number; exit_price: number | null; current_price: number | null
  shares: number; stop_loss: number | null; target_1: number | null; dollar_risk: number | null
  pnl: number | null; unrealized_pnl: number | null; r_multiple: number | null; pnl_pct: number | null
  status: string; outcome_verdict: string | null; exit_reason: string | null
  market_regime: string | null; vix_at_entry: number | null
  catalyst_at_entry: string | null; catalyst_verified: boolean | null
  risk_gate_result: string | null; risk_gate_reason_codes: string | null
  max_favorable_excursion: number | null; max_adverse_excursion: number | null
  opened_via: string | null; closed_via: string | null; notes: string | null
  entry_time: string | null; closed_at: string | null
  execution_log: any[]; alerts: any[]; journal_reviews: any[]
}

function timeStr(iso: string | null) {
  if (!iso) return '--'
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function PnlBadge({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: COLORS.muted }}>--</span>
  const color = value > 0 ? COLORS.green : value < 0 ? COLORS.red : COLORS.text
  return <span style={{ color, fontWeight: 600, ...mono }}>${value >= 0 ? '+' : ''}{value.toFixed(2)}</span>
}

function EventIcon({ type }: { type: string }) {
  const icons: Record<string, string> = {
    'MONITOR_ADJUST_STOP': '↑', 'MONITOR_TIGHTEN_NEAR_TARGET': '⬆',
    'MONITOR_CLOSE_TARGET': '$', 'MONITOR_ADD_STOP': '+',
    'MONITOR_PHANTOM_CLOSED': '⛔',
    'IRIS_OUTCOME_WRITEBACK': '🔍', 'AEGIS_POST_TRADE_SYNTHESIS': '🛡',
    'OUTCOME_LESSON_CAPTURED': '📚', 'PATTERN_CHECK': '📊',
    'LOCAL_LLM_ANALYSIS': '🤖', 'OPEN_TRADE_ALERT': '🔔',
  }
  return <span>{icons[type] || '•'}</span>
}

function TradeCard({ trade }: { trade: Trade }) {
  const [expanded, setExpanded] = useState(false)
  const isOpen = trade.status === 'open'
  const pnl = isOpen ? trade.unrealized_pnl : trade.pnl
  const borderColor = isOpen ? COLORS.accent : (pnl && pnl > 0 ? COLORS.green : COLORS.red)

  return (
    <div style={{
      background: COLORS.card, borderRadius: 8, marginBottom: 12,
      border: `1px solid ${COLORS.border}`, borderLeft: `3px solid ${borderColor}`,
    }}>
      {/* Header row */}
      <div onClick={() => setExpanded(!expanded)}
        style={{ padding: '12px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 10, color: COLORS.muted }}>{expanded ? '▼' : '▶'}</span>
        <span style={{ fontWeight: 700, fontSize: 15, color: COLORS.text, ...mono, minWidth: 50 }}>{trade.symbol}</span>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
          background: isOpen ? 'rgba(74,144,244,0.15)' : 'rgba(160,174,192,0.15)',
          color: isOpen ? COLORS.accent : COLORS.muted,
        }}>{trade.status.toUpperCase()}</span>
        <span style={{ fontSize: 11, color: COLORS.muted }}>{trade.strategy_id}</span>
        {trade.market_regime && (
          <span style={{ fontSize: 10, color: COLORS.orange, padding: '1px 6px', borderRadius: 3, background: 'rgba(246,173,85,0.1)' }}>
            {trade.market_regime}
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 9, color: COLORS.muted }}>P&L</div>
            <PnlBadge value={pnl} />
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 9, color: COLORS.muted }}>R</div>
            <span style={{ ...mono, fontSize: 12, color: trade.r_multiple && trade.r_multiple > 0 ? COLORS.green : trade.r_multiple && trade.r_multiple < 0 ? COLORS.red : COLORS.text }}>
              {trade.r_multiple != null ? `${trade.r_multiple >= 0 ? '+' : ''}${trade.r_multiple.toFixed(1)}R` : '--'}
            </span>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 9, color: COLORS.muted }}>Events</div>
            <span style={{ ...mono, fontSize: 12, color: COLORS.text }}>{trade.execution_log.length + trade.alerts.length}</span>
          </div>
        </div>
      </div>

      {expanded && (
        <div style={{ padding: '0 16px 16px' }}>
          {/* Position details */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 16, padding: 12, background: '#1A202C', borderRadius: 6 }}>
            {[
              ['POSITION', `${trade.shares} shares LONG`],
              ['ENTRY', `$${trade.entry_price?.toFixed(2) || '--'}`],
              ['STOP', `$${trade.stop_loss?.toFixed(2) || '--'}`],
              ['TARGET', `$${trade.target_1?.toFixed(2) || '--'}`],
              ['CURRENT', `$${(trade.current_price || trade.exit_price)?.toFixed(2) || '--'}`],
              ['RISK $', `$${trade.dollar_risk?.toFixed(0) || '--'}`],
              ['MFE', `${trade.max_favorable_excursion != null ? `+${trade.max_favorable_excursion.toFixed(1)}%` : '--'}`],
              ['MAE', `${trade.max_adverse_excursion != null ? `${trade.max_adverse_excursion.toFixed(1)}%` : '--'}`],
              ['VIX', trade.vix_at_entry?.toFixed(1) || '--'],
              ['REGIME', trade.market_regime || '--'],
              ['RISK GATE', trade.risk_gate_result || '--'],
              ['ACCOUNT', trade.account || '--'],
            ].map(([label, value]) => (
              <div key={label}>
                <div style={{ fontSize: 8, color: COLORS.muted, textTransform: 'uppercase' }}>{label}</div>
                <div style={{ fontSize: 11, color: COLORS.text, ...mono }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Entry rationale */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Entry Rationale</div>
            <div style={{ fontSize: 11, color: COLORS.text, lineHeight: 1.6, padding: 10, background: '#1A202C', borderRadius: 6 }}>
              <div>Strategy: <strong>{trade.strategy_id}</strong> via {trade.opened_via || 'unknown'}</div>
              {trade.catalyst_at_entry && (
                <div>Catalyst: {trade.catalyst_verified ? '✓ Verified' : '○ Unverified'} — {trade.catalyst_at_entry}</div>
              )}
              {trade.risk_gate_reason_codes && <div>Risk gate: {trade.risk_gate_reason_codes}</div>}
              {trade.notes && <div style={{ marginTop: 4, color: COLORS.muted }}>{trade.notes}</div>}
            </div>
          </div>

          {/* Execution log timeline */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>
              Execution Log ({trade.execution_log.length + trade.alerts.length} events)
            </div>
            <div style={{ padding: '8px 12px', background: '#1A202C', borderRadius: 6, maxHeight: 300, overflowY: 'auto' }}>
              {trade.execution_log.length === 0 && trade.alerts.length === 0 ? (
                <div style={{ fontSize: 11, color: COLORS.muted, fontStyle: 'italic' }}>No lifecycle events recorded yet.</div>
              ) : (
                [...trade.execution_log.map(e => ({ ...e, _src: 'event' })),
                 ...trade.alerts.map(a => ({ ...a, event_type: a.alert_type, event_summary: a.message, agent_name: 'alert', _src: 'alert' }))]
                  .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''))
                  .map((ev, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: `1px solid ${COLORS.border}`, fontSize: 11 }}>
                      <span style={{ minWidth: 120, color: COLORS.muted, fontSize: 10, ...mono }}>{timeStr(ev.created_at)}</span>
                      <EventIcon type={ev.event_type} />
                      <span style={{ color: ev._src === 'alert' ? COLORS.orange : COLORS.accent, fontWeight: 600, fontSize: 10, minWidth: 60 }}>
                        {ev.agent_name || 'system'}
                      </span>
                      <span style={{ color: COLORS.text, flex: 1 }}>{ev.event_summary}</span>
                    </div>
                  ))
              )}
            </div>
          </div>

          {/* Exit / Outcome */}
          {trade.status === 'closed' && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Exit & Outcome</div>
              <div style={{ padding: 10, background: '#1A202C', borderRadius: 6, fontSize: 11, color: COLORS.text, lineHeight: 1.6 }}>
                <div>Exit reason: <strong>{trade.exit_reason || '--'}</strong></div>
                <div>Verdict: <strong style={{ color: trade.outcome_verdict === 'CORRECT' || trade.outcome_verdict === 'WIN' ? COLORS.green : COLORS.red }}>
                  {trade.outcome_verdict || '--'}
                </strong></div>
                {trade.closed_via && <div>Closed via: {trade.closed_via}</div>}
              </div>
            </div>
          )}

          {/* Journal review */}
          {trade.journal_reviews.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: COLORS.muted, fontWeight: 600, textTransform: 'uppercase', marginBottom: 4 }}>Journal Review</div>
              {trade.journal_reviews.map((rv: any, i: number) => (
                <div key={i} style={{ padding: 10, background: '#1A202C', borderRadius: 6, fontSize: 11, color: COLORS.text, lineHeight: 1.6, marginBottom: 6 }}>
                  {rv.mistake_tags?.length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: COLORS.red, fontWeight: 600 }}>Mistakes:</span>{' '}
                      {rv.mistake_tags.join(', ')}
                    </div>
                  )}
                  {rv.strength_tags?.length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ color: COLORS.green, fontWeight: 600 }}>Strengths:</span>{' '}
                      {rv.strength_tags.join(', ')}
                    </div>
                  )}
                  {rv.lesson_learned && <div style={{ marginBottom: 4 }}><strong>Lesson:</strong> {rv.lesson_learned}</div>}
                  {rv.coach_notes && <div style={{ color: COLORS.muted }}><strong>System fixes:</strong> {rv.coach_notes}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function AutomatedTradeJournal() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState('ALPACA_PAPER')

  useEffect(() => {
    setLoading(true)
    fetch(`/api/v2/automated-trade-journal?account=${account}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [account])

  const summary = data?.summary || {}

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ color: COLORS.text, fontSize: 18, margin: 0 }}>Automated Trade Journal</h2>
          <p style={{ color: COLORS.muted, fontSize: 12, margin: '2px 0 0' }}>
            Full execution log per trade — position, strategy, rationale, stop adjustments, system observations
          </p>
        </div>
        <select value={account} onChange={e => setAccount(e.target.value)}
          style={{ background: COLORS.card, color: COLORS.text, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: '6px 12px', fontSize: 12 }}>
          <option value="ALPACA_PAPER">Alpaca Paper</option>
          <option value="SIM_PAPER">Sim Paper</option>
        </select>
      </div>

      {/* Summary bar */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        {[
          ['Open', summary.open_count, COLORS.accent],
          ['Closed', summary.closed_count, COLORS.muted],
          ['Realized P&L', summary.total_pnl != null ? `$${summary.total_pnl.toFixed(2)}` : '--', summary.total_pnl > 0 ? COLORS.green : COLORS.red],
          ['Unrealized P&L', summary.unrealized_pnl != null ? `$${summary.unrealized_pnl.toFixed(2)}` : '--', summary.unrealized_pnl > 0 ? COLORS.green : COLORS.red],
        ].map(([label, value, color]) => (
          <div key={String(label)} style={{ background: COLORS.card, borderRadius: 6, padding: '8px 14px', border: `1px solid ${COLORS.border}` }}>
            <div style={{ fontSize: 9, color: COLORS.muted, textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: color as string, ...mono }}>{value}</div>
          </div>
        ))}
      </div>

      {loading && <p style={{ color: COLORS.muted }}>Loading...</p>}

      {data?.open?.map((t: Trade) => <TradeCard key={t.id} trade={t} />)}
      {data?.closed?.map((t: Trade) => <TradeCard key={t.id} trade={t} />)}

      {!loading && !data?.trades?.length && (
        <div style={{ textAlign: 'center', padding: 40, color: COLORS.muted }}>
          No trades found for {account}.
        </div>
      )}
    </div>
  )
}
