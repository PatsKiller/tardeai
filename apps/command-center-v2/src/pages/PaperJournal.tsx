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
  const { data, refetch } = useApi<any>('/api/v2/paper-journal', 60000)
  const [expandedId, setExpandedId] = useState<number | null>(null)

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
        <button onClick={refetch} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
      } />

      {/* Stats Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Closed" value={stats.closed ?? 0} />
        <MetricTile label="Open" value={stats.open ?? 0} />
        <MetricTile label="Wins" value={stats.wins ?? 0} deltaColor="var(--green)" />
        <MetricTile label="Losses" value={stats.losses ?? 0} deltaColor="var(--red)" />
        <MetricTile label="Win Rate" value={stats.win_rate != null ? fmtPct(stats.win_rate, 1) : '--'}
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
            {openTrades.map((t: any, i: number) => (
              <div key={t.id ?? i} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ fontWeight: 700, color: 'var(--text0)', minWidth: 50, ...mono }}>{t.symbol}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{t.strategy || t.strategy_id || ''}</span>
                {(t.grade || t.signal_grade) && <span style={pill((t.grade || t.signal_grade) === 'A' || (t.grade || t.signal_grade) === 'A+' ? 'green' : 'amber')}>{t.grade || t.signal_grade}</span>}
                <span style={{ ...mono, fontSize: 10, color: 'var(--text2)' }}>Entry: {(t.entry ?? t.entry_price) != null ? fmt$(t.entry ?? t.entry_price, 2) : '--'}</span>
                <span style={{ ...mono, fontSize: 10, color: pnlColor(t.unrealized_pnl), marginLeft: 'auto' }}>
                  {t.unrealized_pnl != null ? fmt$(t.unrealized_pnl, 2) : ''}
                </span>
              </div>
            ))}
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
                  {['', 'Symbol', 'Strategy', 'Grade', 'Entry', 'Exit', 'P&L', 'R', 'Verdict', 'Source', 'Analyzed', 'Iris', 'Aegis', 'Date'].map(h => (
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
                        <td style={{ ...tdStyle, fontSize: 10, color: 'var(--text3)' }}>{t.source || t.opened_via || '--'}</td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.post_trade_analyzed ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.post_trade_analyzed ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.iris_curated ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.iris_curated ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, textAlign: 'center' }}><span style={{ color: t.aegis_summarized ? 'var(--green)' : 'var(--text3)', fontSize: 10 }}>{t.aegis_summarized ? 'Y' : '-'}</span></td>
                        <td style={{ ...tdStyle, fontSize: 9, color: 'var(--text3)', ...mono }}>{(t.closed_at || t.exit_date || '').slice(0, 10) || '--'}</td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={14} style={{ padding: 0, borderBottom: '2px solid var(--border)', background: 'var(--bg0)' }}>
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
