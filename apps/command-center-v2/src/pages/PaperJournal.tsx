import React, { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'

import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct } from '../lib/format'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const thStyle: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)' }
const tdStyle: React.CSSProperties = { fontSize: 11, padding: '5px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text0)' }
const pill = (color: string): React.CSSProperties => ({ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : 'rgba(251,191,36,0.15)', color: `var(--${color})`, fontWeight: 600 })
const sectionLbl: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', fontWeight: 600, marginBottom: 4 }

function TradeDetail({ tradeId }: { tradeId: number }) {
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  React.useEffect(() => {
    Promise.all([
      fetch(`/api/v2/paper-trade-analysis`).then(r => r.json()),
      fetch(`/api/v2/agent-curation-events`).then(r => r.json()),
      fetch(`/api/v2/open-trade-monitor`).then(r => r.json()),
    ]).then(([analysisResp, eventsResp, monitorResp]) => {
      const ad = analysisResp.data || analysisResp
      const ed = eventsResp.data || eventsResp
      const md = monitorResp.data || monitorResp
      const analyses = (ad.analyses || []).filter((a: any) => a.paper_trade_id === tradeId)
      const events = (ed.events || []).filter((e: any) => e.paper_trade_id === tradeId)
      const alerts = (md.alerts || []).filter((a: any) => a.paper_trade_id === tradeId)
      setDetail({ analyses, events, alerts })
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [tradeId])

  if (loading) return <div style={{ padding: 12, color: 'var(--text3)', fontSize: 11 }}>Loading details...</div>
  if (!detail) return <div style={{ padding: 12, color: 'var(--red)', fontSize: 11 }}>Failed to load</div>

  const { analyses, events, alerts } = detail
  const irisEvents = events.filter((e: any) => e.agent_name === 'Iris')
  const aegisEvents = events.filter((e: any) => e.agent_name === 'Aegis')
  const llmEvents = events.filter((e: any) => e.agent_name === 'local_llm')
  const hasContent = analyses.length > 0 || events.length > 0 || alerts.length > 0

  if (!hasContent) {
    return <div style={{ padding: 12, color: 'var(--text3)', fontSize: 11, fontStyle: 'italic' }}>No curation data for this trade yet.</div>
  }

  return (
    <div style={{ padding: '12px 16px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      {/* LLM Analysis */}
      <div>
        <div style={sectionLbl}>LLM Post-Trade Analysis</div>
        {analyses.length > 0 ? analyses.map((a: any) => (
          <div key={a.id} style={{ background: 'var(--bg1)', borderRadius: 6, padding: 10, marginBottom: 6, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>Model: {a.model_used || 'unknown'} | Confidence: {a.confidence != null ? `${(a.confidence * 100).toFixed(0)}%` : '--'}</div>
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>{a.summary?.slice(0, 400)}</div>
            {a.lessons && Array.isArray(a.lessons) && a.lessons.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 2 }}>Lessons:</div>
                {a.lessons.slice(0, 3).map((l: string, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '1px 0' }}>- {l}</div>
                ))}
              </div>
            )}
          </div>
        )) : <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>Not yet analyzed</div>}
      </div>

      {/* Iris + Aegis + Alerts */}
      <div>
        {/* Aegis Synthesis */}
        <div style={sectionLbl}>Aegis Synthesis</div>
        {aegisEvents.length > 0 ? aegisEvents.map((e: any) => (
          <div key={e.id} style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 8, padding: 8, background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border)' }}>
            {e.event_summary}
          </div>
        )) : <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 8 }}>No synthesis yet</div>}

        {/* Iris Events */}
        <div style={sectionLbl}>Iris Intelligence</div>
        {irisEvents.length > 0 ? irisEvents.map((e: any) => (
          <div key={e.id} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0', marginBottom: 2 }}>
            <span style={{ color: 'var(--green)', fontWeight: 600 }}>{e.event_type}</span>: {e.event_summary?.slice(0, 120)}
          </div>
        )) : <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 8 }}>No Iris events</div>}

        {/* Alerts */}
        {alerts.length > 0 && (<>
          <div style={{ ...sectionLbl, marginTop: 8 }}>Trade Alerts ({alerts.length})</div>
          {alerts.slice(0, 5).map((a: any) => (
            <div key={a.id} style={{ fontSize: 10, padding: '2px 0', display: 'flex', gap: 6 }}>
              <span style={{
                fontWeight: 700, minWidth: 55,
                color: a.severity === 'CRITICAL' ? 'var(--red)' : a.severity === 'WARN' ? 'var(--amber)' : 'var(--text3)',
              }}>{a.severity}</span>
              <span style={{ color: 'var(--text2)' }}>{a.alert_type}: {a.title}</span>
            </div>
          ))}
        </>)}
      </div>
    </div>
  )
}

export default function PaperJournal() {
  const { data, refetch } = useApi<any>('/api/v2/automated-journal', 60000)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [expandedOpen, setExpandedOpen] = useState<number | null>(null)
  const [actionRunning, setActionRunning] = useState<string | null>(null)
  const [closeReason, setCloseReason] = useState<Record<number, string>>({})

  const runJournalAction = async (actionName: string, endpoint: string, body?: any) => {
    setActionRunning(actionName)
    try {
      const r = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      })
      const d = await r.json()
      if (!d.ok) alert(d.error || `${actionName} failed`)
      else refetch()
    } catch { alert('Network error') }
    setActionRunning(null)
  }

  const stats = data?.stats || {}
  const openTrades = data?.open_trades ?? data?.open ?? []
  const closedRaw = data?.closed_trades ?? data?.closed ?? []
  const validation = data?.validation || {}

  const closed = [...closedRaw].sort((a: any, b: any) => {
    const da = a.closed_at || a.exit_date || ''
    const db = b.closed_at || b.exit_date || ''
    return db.localeCompare(da)
  })

  const pnlColor = (v: number | null | undefined) => v == null ? 'var(--text3)' : v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text2)'

  return (
    <>
      <PageHeader title="Paper Journal" subtitle="Paper trading performance and validation progress" actions={
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => runJournalAction('monitor', '/api/v2/paper-trades/monitor')}
            disabled={!!actionRunning}
            style={{ padding: '4px 10px', fontSize: 10, background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 6, color: '#60A5FA', cursor: 'pointer', fontWeight: 600 }}>
            {actionRunning === 'monitor' ? '...' : 'Monitor Paper Trades'}
          </button>
          <button onClick={() => runJournalAction('reconcile', '/api/v2/paper-reconciliation/run')}
            disabled={!!actionRunning}
            style={{ padding: '4px 10px', fontSize: 10, background: 'rgba(168,85,247,0.15)', border: '1px solid rgba(168,85,247,0.3)', borderRadius: 6, color: '#A855F7', cursor: 'pointer', fontWeight: 600 }}>
            {actionRunning === 'reconcile' ? '...' : 'Run Reconciliation'}
          </button>
          <button onClick={refetch} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
        </div>
      } />

      {/* Stats Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Paper Closed" value={stats.closed ?? 0} />
        <MetricTile label="Paper Open" value={stats.open ?? 0} />
        <MetricTile label="Wins" value={stats.wins ?? 0} deltaColor="var(--green)" />
        <MetricTile label="Losses" value={stats.losses ?? 0} deltaColor="var(--red)" />
        <MetricTile label="Win Rate (all paper)" value={stats.win_rate != null ? fmtPct(stats.win_rate, 1) : '--'}
          deltaColor={(stats.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)'} />
        <MetricTile label="Total P&L" value={stats.total_pnl != null ? fmt$(stats.total_pnl, 2) : '--'}
          deltaColor={pnlColor(stats.total_pnl)} />
      </div>

      {/* Validation Progress */}
      {(validation.trades_target || validation.threshold) && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <SectionHeader title="Validation Progress" />
          <div style={{ padding: '10px 14px', display: 'flex', gap: 24, alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Trades</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', ...mono }}>
                {stats.closed ?? 0} / {validation.trades_target ?? 30}
              </div>
            </div>
            <div style={{ flex: 1, height: 6, background: 'var(--bg0)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${Math.min(100, ((stats.closed ?? 0) / (validation.trades_target ?? 30)) * 100)}%`, background: 'var(--green)', borderRadius: 3, transition: 'width 0.3s' }} />
            </div>
            <div>
              <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Win Rate vs Target</div>
              <div style={{ fontSize: 14, fontWeight: 700, ...mono, color: (stats.win_rate ?? 0) >= (validation.threshold ?? 50) ? 'var(--green)' : 'var(--red)' }}>
                {stats.win_rate != null ? `${stats.win_rate.toFixed(1)}%` : '--'} / {validation.threshold ?? 50}%
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Open Trades */}
      {openTrades.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }}>
          <SectionHeader title={`Open Trades (${openTrades.length})`} />
          <div style={{ padding: '6px 12px' }}>
            {openTrades.map((t: any, i: number) => {
              const entry = t.entry ?? t.entry_price
              const stop = t.stop_loss ?? t.stop
              const target = t.target_1 ?? t.target ?? t.take_profit_price
              const shares = t.shares ?? t.qty
              const riskPerShare = entry && stop ? Math.abs(entry - stop) : 0
              const riskTotal = riskPerShare * (shares || 0)
              const currentPrice = t.current_price
              const unrealizedR = riskPerShare > 0 && currentPrice && entry
                ? ((currentPrice - entry) / riskPerShare)
                : null
              const isExpanded = expandedOpen === t.id
              return (
                <div key={t.id ?? i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                  onClick={() => setExpandedOpen(isExpanded ? null : t.id)}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 11 }}>
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>{isExpanded ? '▼' : '▶'}</span>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', minWidth: 50, ...mono }}>{t.symbol}</span>
                    <span style={{ color: 'var(--text3)', fontSize: 9 }}>{t.strategy || t.strategy_id || ''}</span>
                    {(t.grade || t.signal_grade) && <span style={pill((t.grade || t.signal_grade) === 'A' || (t.grade || t.signal_grade) === 'A+' ? 'green' : 'amber')}>{t.grade || t.signal_grade}</span>}
                    <span style={{ ...mono, fontSize: 10, color: 'var(--text2)' }}>Entry: {entry != null ? fmt$(entry, 2) : '--'}</span>
                    <span style={{ ...mono, fontSize: 10, color: 'var(--text3)' }}>Stop: {stop != null ? fmt$(stop, 2) : '--'}</span>
                    <span style={{ ...mono, fontSize: 10, color: 'var(--text3)' }}>Target: {target != null ? fmt$(target, 2) : '--'}</span>
                    <span style={{ ...mono, fontSize: 10, color: 'var(--text3)' }}>{shares ? `${shares}sh` : ''}</span>
                    {t.broker_status && <span style={pill(t.broker_status === 'filled' ? 'green' : t.broker_status === 'new' || t.broker_status === 'accepted' ? 'amber' : 'red')}>{t.broker_status}</span>}
                    {t.broker_order_id && <span style={{ fontSize: 8, color: 'var(--text3)', ...mono }}>order: {String(t.broker_order_id).slice(0, 8)}...</span>}
                    {(t.account === 'ALPACA_PAPER' || t.broker === 'alpaca_paper') && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(59,130,246,0.1)', color: '#60A5FA', fontWeight: 600 }}>ALPACA</span>}
                    <span style={{ ...mono, fontSize: 10, color: pnlColor(t.unrealized_pnl), marginLeft: 'auto' }}>
                      {t.unrealized_pnl != null ? fmt$(t.unrealized_pnl, 2) : ''}
                      {unrealizedR != null && <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 4 }}>({unrealizedR >= 0 ? '+' : ''}{unrealizedR.toFixed(1)}R)</span>}
                    </span>
                  </div>
                  {isExpanded && (
                    <div style={{ marginTop: 8, padding: '8px 12px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10 }}
                      onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 8 }}>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>ENTRY</div><div style={{ ...mono, color: 'var(--text0)' }}>${entry?.toFixed(2) || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>STOP</div><div style={{ ...mono, color: 'var(--red)' }}>${stop?.toFixed(2) || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>TARGET</div><div style={{ ...mono, color: 'var(--green)' }}>${target?.toFixed(2) || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>CURRENT</div><div style={{ ...mono, color: pnlColor(t.unrealized_pnl) }}>${currentPrice?.toFixed(2) || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>SHARES</div><div style={{ ...mono }}>{shares || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>RISK $</div><div style={{ ...mono, color: 'var(--red)' }}>${riskTotal.toFixed(0)}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>UNREAL P/L</div><div style={{ ...mono, color: pnlColor(t.unrealized_pnl) }}>{t.unrealized_pnl != null ? fmt$(t.unrealized_pnl, 2) : '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>UNREAL R</div><div style={{ ...mono, color: pnlColor(unrealizedR) }}>{unrealizedR != null ? `${unrealizedR >= 0 ? '+' : ''}${unrealizedR.toFixed(2)}R` : '--'}</div></div>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 8 }}>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>ACCOUNT</div><div style={{ ...mono, fontSize: 9 }}>{t.account || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>BROKER</div><div style={{ ...mono, fontSize: 9 }}>{t.broker || t.broker_status || '--'}</div></div>
                        <div><div style={{ fontSize: 8, color: 'var(--text3)' }}>ORDER ID</div><div style={{ ...mono, fontSize: 9 }}>{t.broker_order_id ? String(t.broker_order_id).slice(0, 12) + '...' : t.client_order_id || '--'}</div></div>
                      </div>
                      {t.proposal_id && <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Proposal #{t.proposal_id}</div>}
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input
                          type="text" placeholder="Close reason..."
                          value={closeReason[t.id] || ''}
                          onChange={e => setCloseReason(prev => ({ ...prev, [t.id]: e.target.value }))}
                          style={{ fontSize: 9, padding: '2px 6px', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 3, color: 'var(--text1)', width: 150, ...mono }}
                        />
                        <button onClick={() => {
                          if (!confirm(`Close PAPER trade ${t.symbol} #${t.id}? This cannot be undone.`)) return
                          runJournalAction(`close-${t.id}`, '/api/v2/paper-trades/close', {
                            paper_trade_id: t.id,
                            reason: closeReason[t.id] || 'manual_close_via_ui',
                          })
                        }}
                          disabled={!!actionRunning}
                          style={{ padding: '2px 8px', fontSize: 9, fontWeight: 600, border: '1px solid #DC2626', borderRadius: 4, cursor: 'pointer', color: '#EF4444', background: 'rgba(239,68,68,0.1)' }}>
                          {actionRunning === `close-${t.id}` ? '...' : 'Close Paper Trade'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Closed Trades Table */}
      <div style={{background:"var(--bg1)",border:"1px solid var(--border)",borderRadius:8,padding:14}}>
        <SectionHeader title={`Closed Trades (${closed.length})`} />
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Click a row to expand curation details</div>
        {closed.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No closed trades yet</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['', 'Symbol', 'Strategy', 'Grade', 'Entry', 'Exit', 'P&L', 'R', 'Verdict', 'Broker', 'Source', 'Analyzed', 'Iris', 'Aegis', 'Date'].map(h => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {closed.map((t: any, i: number) => {
                  const pnl = t.pnl ?? t.realized_pnl ?? null
                  const r = t.r_multiple ?? t.r ?? null
                  const verdict = t.verdict || t.outcome_verdict || (pnl != null ? (pnl > 0 ? 'WIN' : 'LOSS') : '--')
                  const isExpanded = expandedId === t.id
                  return (
                    <React.Fragment key={t.id ?? i}>
                      <tr
                        onClick={() => setExpandedId(isExpanded ? null : t.id)}
                        style={{ background: isExpanded ? 'rgba(59,130,246,0.08)' : i % 2 ? 'var(--bg0)' : 'transparent', cursor: 'pointer' }}
                      >
                        <td style={{ ...tdStyle, width: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 10 }}>
                          {isExpanded ? '\u25B2' : '\u25BC'}
                        </td>
                        <td style={{ ...tdStyle, fontWeight: 700, ...mono }}>{t.symbol}</td>
                        <td style={{ ...tdStyle, fontSize: 10, color: 'var(--text2)' }}>{t.strategy || t.strategy_id || '--'}</td>
                        <td style={tdStyle}>{(t.grade || t.signal_grade) ? <span style={pill((t.grade || t.signal_grade) === 'A' || (t.grade || t.signal_grade) === 'A+' ? 'green' : (t.grade || t.signal_grade) === 'B' ? 'amber' : 'red')}>{t.grade || t.signal_grade}</span> : '--'}</td>
                        <td style={{ ...tdStyle, ...mono }}>{(t.entry ?? t.entry_price) != null ? fmt$(t.entry ?? t.entry_price, 2) : '--'}</td>
                        <td style={{ ...tdStyle, ...mono }}>{(t.exit ?? t.exit_price) != null ? fmt$(t.exit ?? t.exit_price, 2) : '--'}</td>
                        <td style={{ ...tdStyle, ...mono, color: pnlColor(pnl), fontWeight: 600 }}>{pnl != null ? fmt$(pnl, 2) : '--'}</td>
                        <td style={{ ...tdStyle, ...mono, color: pnlColor(r) }}>{r != null ? Number(r).toFixed(2) : '--'}</td>
                        <td style={tdStyle}><span style={pill(verdict === 'WIN' || verdict === 'CORRECT' ? 'green' : verdict === 'LOSS' || verdict === 'WRONG' ? 'red' : 'amber')}>{verdict}</span></td>
                        <td style={{ ...tdStyle, fontSize: 9, color: 'var(--text3)', ...mono }}>
                          {t.account === 'ALPACA_PAPER' ? (
                            <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: 'rgba(59,130,246,0.1)', color: '#60A5FA', fontWeight: 600 }}>ALPACA</span>
                          ) : t.account || '--'}
                          {t.broker_status && <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.broker_status}</div>}
                        </td>
                        <td style={{ ...tdStyle, fontSize: 10, color: 'var(--text3)' }}>{t.source || t.opened_via || '--'}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.post_trade_analyzed ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.post_trade_analyzed ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.iris_curated ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.iris_curated ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.aegis_summarized ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.aegis_summarized ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, fontSize: 9, color: 'var(--text3)', ...mono }}>{(t.closed_at || t.exit_date || '').slice(0, 10) || '--'}</td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={15} style={{ padding: 0, borderBottom: '2px solid var(--border)', background: 'var(--bg0)' }}>
                            <TradeDetail tradeId={t.id} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
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
