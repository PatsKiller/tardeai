import { useState, useEffect, useCallback } from 'react'

// ── Types ──

interface Strategy {
  strategy_id: string
  display_name: string
  status: string
  description?: string
  timeframe?: string
  account_fit?: string
  min_price?: number
  max_price?: number
  max_float_m?: number
  min_rvol?: number
  risk_per_trade?: number
  min_win_rate?: number
  target_win_rate?: number
  total_signals: number
  trades_taken: number
  signals_today: number
  aplus_today: number
  high_grade_today: number
  objective?: string
}

interface Signal {
  id: number
  symbol: string
  strategy_id: string
  signal_grade: string
  signal_score: number
  price?: number
  rvol?: number
  float_m?: number
  gap_pct?: number
  catalyst?: string
  catalyst_verified?: boolean
  entry_low?: number
  entry_high?: number
  stop_loss?: number
  target_1?: number
  target_2?: number
  shares?: number
  dollar_risk?: number
  risk_reward?: number
  intel_readiness?: number
  setup_description?: string
  fired_at: string
}

interface DeskData {
  ok: boolean
  strategies: Strategy[]
  signals_by_strategy: Record<string, Signal[]>
  top_signals: Signal[]
  performance_30d: Record<string, { trade_count: number; wins: number; win_rate: number | null; total_pnl: number | null }>
  recent_transitions: { strategy_id: string; from_status: string; to_status: string; reason: string; created_at: string }[]
  pattern_summary: Record<string, number>
  patterns_by_strategy: Record<string, { pattern_name: string; pattern_type: string; win_rate: number; trade_count: number; expectancy?: number }[]>
}

// ── Constants ──

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  TESTING:        { bg: '#422006', text: '#F59E0B', border: '#92400E' },
  VALIDATED:      { bg: '#052e16', text: '#10B981', border: '#065F46' },
  SCALING:        { bg: '#1e1b4b', text: '#818CF8', border: '#3730A3' },
  UNVALIDATED:    { bg: '#1F2937', text: '#6B7280', border: '#374151' },
  WATCHLIST:      { bg: '#2D1B69', text: '#A78BFA', border: '#5B21B6' },
  KILLING_REVIEW: { bg: '#450A0A', text: '#EF4444', border: '#991B1B' },
  KILLED:         { bg: '#1C1917', text: '#78716C', border: '#44403C' },
}

const GRADE_COLORS: Record<string, string> = {
  'A+': '#F59E0B',
  'A':  '#10B981',
  'B':  '#60A5FA',
  'C':  '#6B7280',
}

// ── Strategy Card ──

function StrategyCard({ strategy, isSelected, onClick }: {
  strategy: Strategy; isSelected: boolean; onClick: () => void
}) {
  const sc = STATUS_COLORS[strategy.status] || STATUS_COLORS.UNVALIDATED
  const validationPct = Math.min(((strategy.trades_taken || 0) / 30) * 100, 100)

  return (
    <div onClick={onClick} style={{
      background: isSelected ? '#0F2A3F' : '#0A1628',
      border: `1px solid ${isSelected ? '#2563EB' : sc.border}`,
      borderRadius: 8, padding: '16px 20px', cursor: 'pointer',
      transition: 'all 0.15s ease', position: 'relative',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <span style={{ color: '#E2E8F0', fontWeight: 700, fontSize: 14, fontFamily: 'monospace' }}>
          {strategy.display_name}
        </span>
        <span style={{
          background: sc.bg, color: sc.text, border: `1px solid ${sc.border}`,
          borderRadius: 3, padding: '2px 7px', fontSize: 10, fontWeight: 700, fontFamily: 'monospace',
        }}>{strategy.status}</span>
      </div>

      {/* Description */}
      {(strategy.description || strategy.objective) && (
        <div style={{ color: '#64748B', fontSize: 11, marginBottom: 8, lineHeight: 1.4 }}>
          {(strategy.description || strategy.objective || '').slice(0, 80)}
          {(strategy.description || strategy.objective || '').length > 80 ? '...' : ''}
        </div>
      )}

      {/* Signal counts */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 10, alignItems: 'center' }}>
        <span style={{ color: '#94A3B8', fontSize: 12 }}>
          {strategy.signals_today > 0 ? `${strategy.signals_today} signals today` : '0 signals'}
        </span>
        {strategy.high_grade_today > 0 && (
          <span style={{ color: '#10B981', fontSize: 12, fontWeight: 600, fontFamily: 'monospace' }}>
            {strategy.high_grade_today} A
          </span>
        )}
        {strategy.aplus_today > 0 && (
          <span style={{ color: '#F59E0B', fontSize: 12, fontWeight: 700, fontFamily: 'monospace' }}>
            {strategy.aplus_today} A+
          </span>
        )}
      </div>

      {/* Validation progress */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ flex: 1, background: '#1E293B', borderRadius: 2, height: 4, overflow: 'hidden' }}>
          <div style={{
            width: `${validationPct}%`, height: '100%',
            background: validationPct >= 100 ? '#10B981' : sc.text,
            borderRadius: 2, transition: 'width 0.3s ease',
          }} />
        </div>
        <span style={{ color: '#475569', fontSize: 10, whiteSpace: 'nowrap' }}>
          {strategy.trades_taken || 0}/30
        </span>
        <span style={{ color: '#475569', fontSize: 10 }}>{validationPct.toFixed(0)}%</span>
      </div>

      {/* Click hint */}
      <div style={{ position: 'absolute', bottom: 10, right: 14, color: '#334155', fontSize: 10 }}>
        {isSelected ? '◀ open' : 'click ▶'}
      </div>
    </div>
  )
}

// ── Signal Row ──

function SignalRow({ signal, onPropose, proposing }: {
  signal: Signal; onPropose: (id: number) => void; proposing: number | null
}) {
  const hasplan = !!(signal.entry_high && signal.stop_loss)
  const gc = GRADE_COLORS[signal.signal_grade] || '#6B7280'

  const rr = hasplan && signal.entry_high && signal.stop_loss && signal.target_1
    ? ((signal.target_1 - signal.entry_high) / (signal.entry_high - signal.stop_loss)).toFixed(1)
    : null

  return (
    <tr style={{ borderBottom: '1px solid #1E293B' }}>
      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
        <span style={{ color: '#F1F5F9', fontWeight: 700, fontFamily: 'monospace', fontSize: 13 }}>
          {signal.symbol}
        </span>
        <span style={{ marginLeft: 6, color: gc, fontSize: 11, fontWeight: 700, fontFamily: 'monospace' }}>
          {signal.signal_grade}
        </span>
      </td>
      <td style={{ padding: '8px 6px', color: '#94A3B8', fontSize: 12, textAlign: 'right' }}>
        {signal.signal_score}
      </td>
      <td style={{ padding: '8px 6px', color: '#60A5FA', fontSize: 12, textAlign: 'right' }}>
        {signal.rvol ? `${Number(signal.rvol).toFixed(1)}x` : '\u2014'}
      </td>
      <td style={{ padding: '8px 6px', textAlign: 'right' }}>
        {signal.intel_readiness ? (
          <span style={{
            color: signal.intel_readiness >= 75 ? '#10B981' : signal.intel_readiness >= 50 ? '#F59E0B' : '#EF4444',
            fontSize: 11,
          }}>{signal.intel_readiness}</span>
        ) : '\u2014'}
      </td>
      <td style={{
        padding: '8px 8px', color: '#64748B', fontSize: 11, maxWidth: 180,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {signal.catalyst_verified && <span style={{ color: '#10B981', marginRight: 4 }}>&#10003;</span>}
        {signal.catalyst?.slice(0, 50) || '\u2014'}
      </td>
      {hasplan ? (<>
        <td style={{ padding: '8px 6px', color: '#A3E635', fontSize: 11, textAlign: 'right', fontFamily: 'monospace' }}>
          ${signal.entry_high?.toFixed(2)}
        </td>
        <td style={{ padding: '8px 6px', color: '#EF4444', fontSize: 11, textAlign: 'right', fontFamily: 'monospace' }}>
          ${signal.stop_loss?.toFixed(2)}
        </td>
        <td style={{ padding: '8px 6px', color: '#60A5FA', fontSize: 11, textAlign: 'right', fontFamily: 'monospace' }}>
          ${signal.target_1?.toFixed(2)}
        </td>
        <td style={{ padding: '8px 6px', color: '#94A3B8', fontSize: 11, textAlign: 'right' }}>
          {signal.shares}sh
        </td>
        <td style={{ padding: '8px 6px', color: '#F59E0B', fontSize: 11, textAlign: 'right' }}>
          ${signal.dollar_risk?.toFixed(0)}
        </td>
        <td style={{ padding: '8px 6px', color: '#818CF8', fontSize: 11, textAlign: 'right' }}>
          {rr ? `${rr}R` : '\u2014'}
        </td>
      </>) : (
        <td colSpan={6} style={{ padding: '8px 6px', color: '#374151', fontSize: 11, fontStyle: 'italic' }}>
          No trade plan
        </td>
      )}
      <td style={{ padding: '8px 8px' }}>
        {hasplan ? (
          <button
            onClick={(e) => { e.stopPropagation(); onPropose(signal.id) }}
            disabled={proposing === signal.id}
            title="Create paper trade proposal from this signal"
            style={{
              background: proposing === signal.id ? '#1E293B' : '#1E3A5F',
              color: proposing === signal.id ? '#475569' : '#60A5FA',
              border: '1px solid #2563EB', borderRadius: 4, padding: '3px 10px',
              fontSize: 11, cursor: proposing === signal.id ? 'default' : 'pointer',
              fontWeight: 600, whiteSpace: 'nowrap',
            }}
          >{proposing === signal.id ? '...' : '+ Propose'}</button>
        ) : (
          <span style={{ color: '#374151', fontSize: 11 }}
                title="No trade plan available — wait for next screener run">
            {'\u2014'}
          </span>
        )}
      </td>
    </tr>
  )
}

// ── Detail Panel ──

function StrategyDetailPanel({ strategy, signals, performance, patterns, onClose }: {
  strategy: Strategy; signals: Signal[]; performance: any; patterns: any[]; onClose: () => void
}) {
  const [proposing, setProposing] = useState<number | null>(null)
  const [toasts, setToasts] = useState<string[]>([])
  const sc = STATUS_COLORS[strategy.status] || STATUS_COLORS.UNVALIDATED
  const validationPct = Math.min(((strategy.trades_taken || 0) / 30) * 100, 100)

  const handlePropose = async (signalId: number) => {
    setProposing(signalId)
    try {
      const resp = await fetch('/api/v2/paper-proposals/from-signal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId }),
      })
      if (!resp.ok && resp.status >= 500) {
        const text = await resp.text()
        setToasts(t => [...t, `Server error ${resp.status}: ${text.slice(0, 120)}`])
        return
      }
      const json = await resp.json()
      const d = json.data || json
      const sig = signals.find(s => s.id === signalId)
      if (d.ok) {
        setToasts(t => [...t, `Proposal #${d.proposal_id} created for ${d.symbol || sig?.symbol}`])
      } else {
        const existing = d.proposal_id ? ` (#${d.proposal_id})` : ''
        setToasts(t => [...t, `${d.error || 'Failed to create proposal'}${existing}`])
      }
    } catch (e: any) {
      setToasts(t => [...t, `Network error: ${e?.message || e}`])
    } finally {
      setProposing(null)
      setTimeout(() => setToasts(t => t.slice(1)), 5000)
    }
  }

  const signalsWithPlan = signals.filter(s => s.entry_high && s.stop_loss)

  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0, width: 720,
      background: '#0A1628', borderLeft: '1px solid #1E3A5F',
      overflowY: 'auto', zIndex: 100, boxShadow: '-4px 0 24px rgba(0,0,0,0.4)',
    }}>
      {/* Toast notifications */}
      {toasts.length > 0 && (
        <div style={{ position: 'sticky', top: 0, zIndex: 10, padding: '8px 16px', background: '#0A1628' }}>
          {toasts.map((t, i) => (
            <div key={i} style={{
              background: t.startsWith('Proposal') ? '#052E16' : '#450A0A',
              border: `1px solid ${t.startsWith('Proposal') ? '#065F46' : '#991B1B'}`,
              borderRadius: 4, padding: '6px 12px',
              color: t.startsWith('Proposal') ? '#10B981' : '#EF4444',
              fontSize: 12, marginBottom: 4,
            }}>{t}</div>
          ))}
        </div>
      )}

      {/* Panel header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid #1E293B',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        position: 'sticky', top: toasts.length > 0 ? 40 : 0, background: '#0A1628', zIndex: 9,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ color: '#F1F5F9', fontFamily: 'monospace', fontSize: 16, fontWeight: 700, margin: 0 }}>
            {strategy.display_name}
          </h2>
          <span style={{
            background: sc.bg, color: sc.text, border: `1px solid ${sc.border}`,
            borderRadius: 3, padding: '2px 8px', fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
          }}>{strategy.status}</span>
        </div>
        <button onClick={onClose} style={{
          background: 'transparent', color: '#64748B', border: '1px solid #334155',
          borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 13,
        }}>Close</button>
      </div>

      <div style={{ padding: '16px 20px' }}>
        {/* Description */}
        {(strategy.description || strategy.objective) && (
          <div style={{
            background: '#0F2A3F', border: '1px solid #1E3A5F',
            borderRadius: 6, padding: 12, marginBottom: 16,
          }}>
            <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.6 }}>
              {strategy.description || strategy.objective}
            </div>
          </div>
        )}

        {/* Parameters grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
          {[
            { label: 'Timeframe', value: strategy.timeframe?.replace(/_/g, ' ') },
            { label: 'Accounts', value: strategy.account_fit?.replace(/,/g, ', ') },
            { label: 'Price Range', value: strategy.min_price && strategy.max_price
                ? `$${strategy.min_price}\u2013$${strategy.max_price}` : null },
            { label: 'Max Float', value: strategy.max_float_m ? `${strategy.max_float_m}M` : null },
            { label: 'Min RVOL', value: strategy.min_rvol ? `${strategy.min_rvol}x` : null },
            { label: 'Risk/Trade', value: strategy.risk_per_trade ? `$${strategy.risk_per_trade}` : null },
          ].filter(p => p.value).map(p => (
            <div key={p.label} style={{ background: '#0D1F2D', borderRadius: 4, padding: '8px 10px' }}>
              <div style={{ color: '#475569', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>
                {p.label}
              </div>
              <div style={{ color: '#CBD5E1', fontSize: 12, fontWeight: 600, marginTop: 2 }}>
                {p.value}
              </div>
            </div>
          ))}
        </div>

        {/* Validation Gate */}
        <div style={{ background: '#0D1F2D', borderRadius: 6, padding: 12, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ color: '#94A3B8', fontSize: 12, fontWeight: 600 }}>Validation Gate</span>
            <span style={{ color: sc.text, fontSize: 12 }}>
              {strategy.trades_taken || 0}/30 trades
              {' \u00B7 '}Win rate needed: {'\u2265'}{((strategy.min_win_rate || 0.55) * 100).toFixed(0)}%
            </span>
          </div>
          <div style={{ background: '#1E293B', borderRadius: 2, height: 6, overflow: 'hidden' }}>
            <div style={{
              width: `${validationPct}%`, height: '100%',
              background: validationPct >= 100 ? '#10B981' : sc.text, borderRadius: 2,
            }} />
          </div>
          {performance && performance.win_rate != null && (
            <div style={{ color: '#64748B', fontSize: 11, marginTop: 6 }}>
              Current: {(performance.win_rate * 100).toFixed(1)}% win rate
              {' \u00B7 '}P&L: ${performance.total_pnl?.toFixed(0)}
            </div>
          )}
        </div>

        {/* Today's Signals */}
        <div style={{ marginBottom: 16 }}>
          <div style={{
            color: '#94A3B8', fontSize: 12, fontWeight: 600,
            marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            Today's Signals
            <span style={{ color: '#475569', fontWeight: 400 }}>
              ({signals.length} total {'\u00B7'} {signalsWithPlan.length} with trade plan)
            </span>
          </div>
          {signals.length === 0 ? (
            <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: 8 }}>
              No signals fired today for this strategy.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: '#0D1F2D' }}>
                    {['Symbol', 'Score', 'RVOL', 'Intel', 'Catalyst',
                      'Entry', 'Stop', 'Target', 'Size', 'Risk', 'R:R', 'Action'
                    ].map(h => (
                      <th key={h} style={{
                        padding: '6px 8px', color: '#475569', fontSize: 10,
                        textAlign: h === 'Symbol' || h === 'Catalyst' ? 'left' : 'right',
                        fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5,
                        whiteSpace: 'nowrap', borderBottom: '1px solid #1E293B',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {signals.map(sig => (
                    <SignalRow key={sig.id} signal={sig} onPropose={handlePropose} proposing={proposing} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Pattern Library */}
        {patterns && patterns.length > 0 && (
          <div>
            <div style={{ color: '#94A3B8', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
              Pattern Library ({patterns.length})
            </div>
            {patterns.slice(0, 5).map((p, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '6px 10px', marginBottom: 4, background: '#0D1F2D', borderRadius: 4,
                border: `1px solid ${p.pattern_type === 'PROVEN' ? '#065F46' : p.pattern_type === 'KILLED' ? '#991B1B' : '#1E293B'}`,
              }}>
                <span style={{ color: '#CBD5E1', fontSize: 11 }}>
                  {p.pattern_name?.replace(/_/g, ' ')}
                </span>
                <span style={{
                  color: p.pattern_type === 'PROVEN' ? '#10B981' : p.pattern_type === 'KILLED' ? '#EF4444' : '#6B7280',
                  fontSize: 11, fontFamily: 'monospace',
                }}>
                  {p.pattern_type} {'\u00B7'} {p.win_rate != null ? `${(p.win_rate * 100).toFixed(0)}%` : '--'} {'\u00B7'} {p.trade_count}t
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Page ──

export default function StrategyDesk() {
  const [data, setData] = useState<DeskData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runHealth, setRunHealth] = useState<any>(null)

  const fetchData = useCallback(async () => {
    try {
      const resp = await fetch('/api/v2/strategy-desk')
      const json = await resp.json()
      setData(json.data || json)
    } catch (e) {
      console.error('Strategy desk fetch error:', e)
    } finally {
      setLoading(false)
    }
    try {
      const rh = await fetch('/api/v2/pipeline-run-health')
      const rhj = await rh.json()
      if (rhj.ok) setRunHealth(rhj)
    } catch {}
  }, [])

  useEffect(() => {
    fetchData()
    const iv = setInterval(fetchData, 60000)
    return () => clearInterval(iv)
  }, [fetchData])

  if (loading) return <div style={{ padding: 40, color: '#475569', fontFamily: 'monospace' }}>Loading strategy desk...</div>
  if (!data?.ok) return <div style={{ padding: 40, color: '#EF4444' }}>Failed to load strategy desk</div>

  const strategies = data.strategies || []
  const totalSignals = strategies.reduce((acc, s) => acc + (s.signals_today || 0), 0)

  const selectedStrategy = selectedId ? strategies.find(s => s.strategy_id === selectedId) : null
  const selectedSignals = selectedId ? (data.signals_by_strategy?.[selectedId] || []) : []
  const selectedPerf = selectedId ? data.performance_30d?.[selectedId] : null
  const selectedPatterns = selectedId ? data.patterns_by_strategy?.[selectedId] || [] : []

  return (
    <div style={{
      marginRight: selectedId ? 724 : 0,
      transition: 'margin-right 0.2s ease',
      padding: '16px 24px', maxWidth: 1200,
    }}>
      {/* Run health banner */}
      {runHealth?.latest_run && (
        <div style={{
          padding: '6px 14px', marginBottom: 10, borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: runHealth.latest_run.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.08)' :
                      runHealth.latest_run.status === 'RUN_UNDERFILLED' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.08)',
          border: `1px solid ${runHealth.latest_run.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.25)' :
                   runHealth.latest_run.status === 'RUN_UNDERFILLED' ? 'rgba(239,68,68,0.25)' : 'rgba(245,158,11,0.25)'}`,
          color: runHealth.latest_run.status === 'RUN_HEALTHY' ? '#4ADE80' :
                 runHealth.latest_run.status === 'RUN_UNDERFILLED' ? '#F87171' : '#FBBF24',
        }}>
          Run {runHealth.latest_run.run_label} &middot; {runHealth.latest_run.run_date} &middot; {runHealth.latest_run.symbols_scanned} symbols &middot; {runHealth.latest_run.status}
          {runHealth.strategy_signals && ` · ${runHealth.strategy_signals.today_count} signals today`}
          {runHealth.trade_plans && ` · ${runHealth.trade_plans.planned}/${runHealth.trade_plans.proposal_worthy} planned`}
        </div>
      )}
      {/* Page header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ color: '#F1F5F9', fontFamily: 'monospace', fontSize: 22, fontWeight: 700, margin: 0 }}>
          Strategy Desk
        </h1>
        <span style={{ color: '#475569', fontSize: 13 }}>
          {strategies.length} strategies {'\u00B7'} {totalSignals} signals today
          {data.recent_transitions && data.recent_transitions.length > 0 && (
            <span style={{ color: '#F59E0B', marginLeft: 8 }}>
              {'\u00B7'} {data.recent_transitions.length} lifecycle changes
            </span>
          )}
        </span>
      </div>

      {/* Strategy grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: selectedId ? '1fr' : 'repeat(2, 1fr)',
        gap: 12, marginBottom: 24,
      }}>
        {strategies.map(strategy => (
          <StrategyCard
            key={strategy.strategy_id}
            strategy={strategy}
            isSelected={selectedId === strategy.strategy_id}
            onClick={() => setSelectedId(
              selectedId === strategy.strategy_id ? null : strategy.strategy_id
            )}
          />
        ))}
      </div>

      {/* Bottom sections — pattern + transitions */}
      {!selectedId && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={{ background: '#0A1628', border: '1px solid #1E293B', borderRadius: 8, padding: 14 }}>
            <h3 style={{ fontSize: 13, fontWeight: 600, color: '#F1F5F9', marginTop: 0, marginBottom: 8 }}>Pattern Library</h3>
            <div style={{ fontSize: 12, color: '#94A3B8' }}>
              {Object.entries(data.pattern_summary || {}).map(([type, count]) => (
                <div key={type} style={{ marginBottom: 4 }}>
                  <span style={{ color: type === 'proven' ? '#10B981' : type === 'killed' ? '#EF4444' : '#94A3B8' }}>
                    {type}: {count as number}
                  </span>
                </div>
              ))}
              {Object.keys(data.pattern_summary || {}).length === 0 && (
                <span style={{ color: '#64748B' }}>Accumulating data</span>
              )}
            </div>
          </div>
          <div style={{ background: '#0A1628', border: '1px solid #1E293B', borderRadius: 8, padding: 14 }}>
            <h3 style={{ fontSize: 13, fontWeight: 600, color: '#F1F5F9', marginTop: 0, marginBottom: 8 }}>Lifecycle Changes</h3>
            {data.recent_transitions.length > 0 ? (
              data.recent_transitions.slice(0, 5).map((t, i) => (
                <div key={i} style={{ fontSize: 12, color: '#94A3B8', marginBottom: 6 }}>
                  <span style={{ fontWeight: 600 }}>{t.strategy_id}</span>: {t.from_status} {'→'}{' '}
                  <span style={{ color: '#F59E0B' }}>{t.to_status}</span>
                  <div style={{ fontSize: 10, color: '#64748B' }}>{t.reason?.slice(0, 80)}</div>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 12, color: '#64748B' }}>No transitions yet</div>
            )}
          </div>
        </div>
      )}

      {/* Detail panel */}
      {selectedStrategy && (
        <StrategyDetailPanel
          strategy={selectedStrategy}
          signals={selectedSignals}
          performance={selectedPerf}
          patterns={selectedPatterns}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}
