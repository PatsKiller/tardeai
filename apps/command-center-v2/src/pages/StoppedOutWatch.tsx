import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import { useApi } from '../hooks/useApi'
import { useFetch } from '../hooks/useFetch'
import { fmt$, fmtPct, deltaColor, timeAgo } from '../lib/format'

interface StopConf { id: number; symbol: string; account: string; stop_status: string; stop_confirmed: boolean; stop_price_confirmed: number | null; reminder_count: number; updated_at: string }
interface StopConfData { count: number; items: StopConf[] }
interface NotifItem { notification_type: string; channel: string; subject: string; body_summary: string; status: string; sent_at: string }
interface NotifData { count: number; notifications: NotifItem[] }

interface WatchItem {
  id: number; symbol: string; account: string; stopped_out_at: string; exit_price: number
  stop_price: number; reason: string; setup_name: string | null; thesis_at_exit: string | null
  realized_pnl: number | null; status: string; analyst_verdict: string | null
  analyst_confidence: number | null; analyst_summary: string | null
  reentry_trigger: string | null; invalidated_if: string | null
  evidence_payload: Record<string, unknown>; escalated_to: string | null
  escalation_reason: string | null; auto_created: boolean
  next_review_at: string | null; last_reviewed_at: string | null
  temp_allocation_verdict: string | null; temp_allocation_confidence: number | null
  temp_allocation_target: string | null; temp_allocation_reason: string | null
  temp_allocation_until: string | null; temp_allocation_exit_trigger: string | null
  current_price: number | null; current_rsi: number | null; current_sma200_pct: number | null
  recovery_pct: number | null; days_since_stop: number | null
}
interface PortfolioContext { heat_pct: number; total_with_stops: number; total_unprotected: number; watchlist_candidates: number; pipeline_status: string; regime: string }
interface WatchData { count: number; items: WatchItem[]; portfolio_context?: PortfolioContext }

const verdictColor: Record<string, string> = { reentry_candidate: 'var(--green)', wait_monitor: 'var(--amber)', do_not_reenter: 'var(--red)' }
const verdictBg: Record<string, string> = { reentry_candidate: 'var(--green-dim)', wait_monitor: 'var(--amber-dim)', do_not_reenter: 'var(--red-dim)' }
const verdictLabel: Record<string, string> = { reentry_candidate: 'Re-entry Candidate', wait_monitor: 'Wait / Monitor', do_not_reenter: 'Do Not Re-enter' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }

export default function StoppedOutWatch() {
  const navigate = useNavigate()
  const { data } = useApi<WatchData>('/api/v2/stopped-out-watch')
  const { data: confData } = useApi<StopConfData>('/api/v2/stop-confirmations')
  const { data: notifData } = useApi<NotifData>('/api/v2/notifications/recent')
  const [selected, setSelected] = useState<WatchItem | null>(null)
  const [escalateStatus, setEscalateStatus] = useState<Record<number, string>>({})
  const [reviewRunning, setReviewRunning] = useState(false)
  const [reviewResult, setReviewResult] = useState<string | null>(null)

  const items = data?.items ?? []
  const reentryCount = items.filter(i => i.analyst_verdict === 'reentry_candidate').length
  const waitCount = items.filter(i => i.analyst_verdict === 'wait_monitor').length
  const dontCount = items.filter(i => i.analyst_verdict === 'do_not_reenter').length

  const handleEscalate = useCallback(async (watchId: number, to: string) => {
    setEscalateStatus(s => ({ ...s, [watchId]: 'sending' }))
    try {
      const r = await fetch('/api/v2/stopped-out-watch/escalate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ watch_id: watchId, escalate_to: to, note: `Escalated for ${to} review` }),
      })
      const d = await r.json()
      setEscalateStatus(s => ({ ...s, [watchId]: d.ok ? `Sent to ${to}` : 'Failed' }))
    } catch { setEscalateStatus(s => ({ ...s, [watchId]: 'Failed' })) }
  }, [])

  return (
    <>
      <PageHeader title="Recovery Watch" subtitle={items.length > 0 ? `${items.length} position${items.length !== 1 ? 's' : ''} under review` : 'No positions under watch'} actions={
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button onClick={async () => {
            setReviewRunning(true); setReviewResult(null)
            try {
              const r = await fetch('/api/run-recovery-review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
              const d = await r.json()
              setReviewResult(d.ok ? 'Review triggered' : d.error || 'Failed')
              if (d.ok) setTimeout(() => window.location.reload(), 3000)
            } catch { setReviewResult('Failed') }
            setReviewRunning(false)
          }} disabled={reviewRunning} style={{ padding: '3px 10px', fontSize: 10, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: reviewRunning ? 'wait' : 'pointer', fontFamily: 'var(--mono)', opacity: reviewRunning ? 0.5 : 1 }}>
            {reviewRunning ? 'Running...' : 'Run Analyst Review'}
          </button>
          {reviewResult && <span style={{ fontSize: 9, color: reviewResult.includes('Failed') ? 'var(--red)' : 'var(--green)' }}>{reviewResult}</span>}
        </div>
      } />

      {/* Quick nav */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/morning-brief')} style={linkStyle}>Morning Brief</button>
        <button onClick={() => navigate('/risk')} style={linkStyle}>Risk</button>
        <button onClick={() => navigate('/approvals')} style={linkStyle}>Approvals</button>
        <button onClick={() => navigate('/actions')} style={linkStyle}>Actions</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Active Watch" value={String(items.length)} />
        <MetricTile label="Re-entry" value={String(reentryCount)} deltaColor="var(--green)" />
        <MetricTile label="Wait / Monitor" value={String(waitCount)} deltaColor="var(--amber)" />
        <MetricTile label="Do Not Re-enter" value={String(dontCount)} deltaColor="var(--red)" />
      </div>

      {/* Portfolio context for strategic reasoning */}
      {data?.portfolio_context && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 12, padding: '8px 12px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--text2)' }}>
          <span>Regime: <strong style={{ color: data.portfolio_context.regime?.toLowerCase().includes('bull') ? 'var(--green)' : data.portfolio_context.regime?.toLowerCase().includes('bear') ? 'var(--red)' : 'var(--text1)' }}>{data.portfolio_context.regime}</strong></span>
          <span>Heat: <strong style={{ color: data.portfolio_context.heat_pct > 5 ? 'var(--red)' : 'var(--amber)' }}>{data.portfolio_context.heat_pct.toFixed(1)}%</strong></span>
          <span>Stops: <strong>{data.portfolio_context.total_with_stops}</strong> / Unprotected: <strong style={{ color: data.portfolio_context.total_unprotected > 5 ? 'var(--amber)' : 'var(--text1)' }}>{data.portfolio_context.total_unprotected}</strong></span>
          <span>Watchlist: <strong>{data.portfolio_context.watchlist_candidates}</strong> candidates</span>
        </div>
      )}

      {items.length === 0 ? (
        <Card><div style={{ color: 'var(--text3)', textAlign: 'center', padding: 40 }}>No stopped-out positions under watch. Aegis adds new items when stops trigger.</div></Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {items.map(item => {
            const v = item.analyst_verdict || 'wait_monitor'
            const ev = (item.evidence_payload || {}) as Record<string, unknown>
            const exitCtx = (ev.exit_context || {}) as Record<string, unknown>
            const isOverdue = item.next_review_at ? new Date(item.next_review_at) < new Date() : false
            return (
              <div key={item.id} style={{
                background: 'var(--bg2)', border: `1px solid ${verdictColor[v] ? 'var(--border)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-lg)', padding: '16px 20px',
                borderLeft: `4px solid ${verdictColor[v] || 'var(--amber)'}`,
              }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 800, color: 'var(--text0)' }}>{item.symbol}</span>
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, textTransform: 'uppercase',
                    background: verdictBg[v] || 'var(--amber-dim)', color: verdictColor[v] || 'var(--amber)',
                  }}>{verdictLabel[v] || v}</span>
                  {isOverdue && (
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>REVIEW OVERDUE</span>
                  )}
                  {item.escalated_to && (
                    <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 3, background: 'var(--accent-dim)', color: 'var(--accent)' }}>
                      Escalated to {item.escalated_to}
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>
                    {item.days_since_stop != null ? `${item.days_since_stop}d since stop` : '—'}
                  </span>
                  {item.analyst_confidence != null && (
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 16, fontWeight: 800, color: verdictColor[v] || 'var(--text1)' }}>{(item.analyst_confidence * 100).toFixed(0)}%</div>
                      <div style={lbl}>Confidence</div>
                    </div>
                  )}
                </div>

                {/* Price comparison grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 10, padding: '10px 12px', background: 'var(--bg3)', borderRadius: 'var(--radius)' }}>
                  <div><div style={lbl}>Exit Price</div><div style={{ fontSize: 14, fontWeight: 700, color: 'var(--red)' }}>{item.exit_price ? fmt$(item.exit_price, 2) : '—'}</div></div>
                  <div><div style={lbl}>Stop Level</div><div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text2)' }}>{item.stop_price ? fmt$(item.stop_price, 2) : '—'}</div></div>
                  <div><div style={lbl}>Current Price</div><div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{item.current_price ? fmt$(item.current_price, 2) : 'N/A'}</div></div>
                  <div><div style={lbl}>Recovery</div><div style={{ fontSize: 14, fontWeight: 700, color: item.recovery_pct != null ? deltaColor(item.recovery_pct) : 'var(--text3)' }}>{item.recovery_pct != null ? `${item.recovery_pct > 0 ? '+' : ''}${item.recovery_pct}%` : '—'}</div></div>
                  <div><div style={lbl}>Stop Date</div><div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)' }}>{item.stopped_out_at || '—'}</div></div>
                </div>

                {/* Technical context */}
                {(item.current_rsi != null || item.current_sma200_pct != null) && (
                  <div style={{ display: 'flex', gap: 16, fontSize: 10, color: 'var(--text2)', marginBottom: 10 }}>
                    {item.current_rsi != null && <span>RSI: <strong style={{ color: item.current_rsi > 70 ? 'var(--red)' : item.current_rsi < 30 ? 'var(--green)' : 'var(--text1)' }}>{item.current_rsi.toFixed(0)}</strong></span>}
                    {item.current_sma200_pct != null && <span>SMA200: <strong style={{ color: item.current_sma200_pct > 0 ? 'var(--green)' : 'var(--red)' }}>{item.current_sma200_pct > 0 ? '+' : ''}{item.current_sma200_pct.toFixed(1)}%</strong></span>}
                    {item.reason && <span>Stop reason: <strong>{item.reason}</strong></span>}
                    {item.account && <span>Account: <strong>{item.account.replace('schwab_', '')}</strong></span>}
                  </div>
                )}

                {/* Analyst summary */}
                {item.analyst_summary && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                    <div style={{ ...lbl, marginBottom: 4, fontWeight: 600 }}>Analyst Assessment</div>
                    <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6 }}>{item.analyst_summary}</div>
                  </div>
                )}

                {/* Journal history context */}
                {(() => {
                  const jh = (ev.journal_history || {}) as Record<string, unknown>
                  if (!jh.has_history) return null
                  return (
                    <div style={{ padding: '8px 10px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                      <div style={{ ...lbl, marginBottom: 4, fontWeight: 600 }}>Journal Review History — {item.symbol}</div>
                      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: 'var(--text2)' }}>
                        <span>{jh.review_count as number} review{(jh.review_count as number) !== 1 ? 's' : ''}</span>
                        {jh.well_executed_rate != null && <span>Well executed: <strong style={{ color: (jh.well_executed_rate as number) >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{((jh.well_executed_rate as number) * 100).toFixed(0)}%</strong></span>}
                        {jh.avg_execution != null && <span>Avg exec: <strong>{(jh.avg_execution as number).toFixed(1)}</strong>/5</span>}
                      </div>
                      {(jh.setups_used as string[] || []).length > 0 && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>Setups: {(jh.setups_used as string[]).join(', ')}</div>}
                      {(jh.common_mistakes as string[] || []).length > 0 && <div style={{ fontSize: 9, color: 'var(--red)', marginTop: 2 }}>Past mistakes: {(jh.common_mistakes as string[]).join(', ')}</div>}
                    </div>
                  )
                })()}

                {/* Temporary Allocation Recommendation */}
                {item.temp_allocation_verdict && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <div style={{ ...lbl, fontWeight: 600 }}>Capital Allocation</div>
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: item.temp_allocation_verdict === 'hold_for_reentry' ? 'var(--green-dim)' : item.temp_allocation_verdict === 'rotate_existing_conviction' ? 'var(--accent-dim)' : 'var(--bg3)', color: item.temp_allocation_verdict === 'hold_for_reentry' ? 'var(--green)' : item.temp_allocation_verdict === 'rotate_existing_conviction' ? 'var(--accent)' : 'var(--text2)' }}>
                        {(item.temp_allocation_verdict || '').replace(/_/g, ' ').toUpperCase()}
                      </span>
                      {item.temp_allocation_confidence != null && <span style={{ fontSize: 9, color: 'var(--text3)' }}>{(item.temp_allocation_confidence * 100).toFixed(0)}% conf</span>}
                    </div>
                    {item.temp_allocation_target && <div style={{ fontSize: 10, color: 'var(--text1)', marginBottom: 4 }}>Target: <strong>{item.temp_allocation_target}</strong></div>}
                    {item.temp_allocation_reason && <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 4 }}>{item.temp_allocation_reason}</div>}
                    <div style={{ display: 'flex', gap: 12, fontSize: 9, color: 'var(--text3)' }}>
                      {item.temp_allocation_until && <span>Until: {item.temp_allocation_until}</span>}
                      {item.temp_allocation_exit_trigger && <span>Exit: {item.temp_allocation_exit_trigger}</span>}
                    </div>
                    {/* Ranked alternatives */}
                    <div style={{ marginTop: 6, padding: '6px 8px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9 }}>
                      <div style={{ color: 'var(--text3)', fontWeight: 600, marginBottom: 3 }}>Alternatives (if conditions change)</div>
                      {item.analyst_verdict === 'wait_monitor' && (
                        <>
                          <div style={{ color: 'var(--text2)' }}>2nd: Cash equivalent (money market) — if heat drops below 3%</div>
                          <div style={{ color: 'var(--text2)' }}>3rd: Hold for re-entry — if verdict upgrades to reentry_candidate</div>
                        </>
                      )}
                      {item.analyst_verdict === 'reentry_candidate' && (
                        <>
                          <div style={{ color: 'var(--text2)' }}>2nd: Cash equivalent — if trigger fails to confirm within 5 days</div>
                          <div style={{ color: 'var(--text2)' }}>3rd: Treasury ballast — if verdict downgrades to do_not_reenter</div>
                        </>
                      )}
                      {item.analyst_verdict === 'do_not_reenter' && (
                        <>
                          <div style={{ color: 'var(--text2)' }}>2nd: Rotate to top watchlist conviction — if watchlist has GO candidate</div>
                          <div style={{ color: 'var(--text2)' }}>3rd: Stay cash — default if no better opportunity</div>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* Re-entry / Invalidation conditions */}
                {(item.reentry_trigger || item.invalidated_if) && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                    {item.reentry_trigger && (
                      <div style={{ padding: '8px 10px', background: 'var(--green-dim)', border: '1px solid var(--green)', borderRadius: 'var(--radius)', fontSize: 10 }}>
                        <div style={{ fontWeight: 600, color: 'var(--green)', marginBottom: 3 }}>Re-entry Trigger</div>
                        <div style={{ color: 'var(--text1)' }}>{item.reentry_trigger}</div>
                      </div>
                    )}
                    {item.invalidated_if && (
                      <div style={{ padding: '8px 10px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', fontSize: 10 }}>
                        <div style={{ fontWeight: 600, color: 'var(--red)', marginBottom: 3 }}>Invalidated If</div>
                        <div style={{ color: 'var(--text1)' }}>{item.invalidated_if}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* Actions */}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>Review in:</span>
                  <button onClick={() => navigate(`/risk?symbol=${item.symbol}`)} style={linkStyle}>Risk</button>
                  <button onClick={() => navigate(`/portfolio?symbol=${item.symbol}`)} style={linkStyle}>Holdings</button>
                  <button onClick={() => navigate(`/research?symbol=${item.symbol}`)} style={linkStyle}>Research</button>
                  <a href={`https://finviz.com/quote.ashx?t=${item.symbol}`} target="_blank" rel="noreferrer" style={{ ...linkStyle, textDecoration: 'none' }}>Finviz</a>
                  <span style={{ marginLeft: 'auto' }} />
                  {!item.escalated_to && (
                    <>
                      <button onClick={() => handleEscalate(item.id, 'maria')} style={{ ...linkStyle, border: '1px solid var(--accent)', color: 'var(--accent)' }}>
                        {escalateStatus[item.id] === 'sending' ? '...' : 'Escalate to Maria'}
                      </button>
                      <button onClick={() => handleEscalate(item.id, 'steph')} style={{ ...linkStyle, border: '1px solid var(--accent)', color: 'var(--accent)' }}>
                        {escalateStatus[item.id] === 'sending' ? '...' : 'Escalate to Steph'}
                      </button>
                    </>
                  )}
                  {escalateStatus[item.id] && escalateStatus[item.id] !== 'sending' && (
                    <span style={{ fontSize: 9, color: escalateStatus[item.id].includes('Failed') ? 'var(--red)' : 'var(--green)' }}>{escalateStatus[item.id]}</span>
                  )}
                </div>

                {/* Review metadata */}
                <div style={{ marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
                  {item.last_reviewed_at && `Last reviewed by Aegis: ${timeAgo(item.last_reviewed_at)}`}
                  {item.next_review_at && ` | Next review: ${item.next_review_at}`}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Stop Confirmation Status */}
      {(confData?.items?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Stop Confirmation Status" count={confData?.count} />
          <Card compact>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {(confData?.items || []).map(c => (
                <div key={c.id} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                  <span style={{
                    fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: c.stop_status === 'confirmed' ? 'var(--green-dim)' : c.stop_status === 'intentional_no_stop' ? 'var(--bg3)' : 'var(--amber-dim)',
                    color: c.stop_status === 'confirmed' ? 'var(--green)' : c.stop_status === 'intentional_no_stop' ? 'var(--text3)' : 'var(--amber)',
                  }}>{c.stop_status.replace(/_/g, ' ').toUpperCase()}</span>
                  <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{c.symbol}</span>
                  <span style={{ color: 'var(--text3)' }}>{c.account?.replace('schwab_', '')}</span>
                  {c.stop_price_confirmed && <span style={{ color: 'var(--green)' }}>Stop: {fmt$(c.stop_price_confirmed, 2)}</span>}
                  {c.reminder_count > 0 && <span style={{ color: 'var(--text3)' }}>{c.reminder_count} reminder{c.reminder_count !== 1 ? 's' : ''}</span>}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* Notification Audit Trail */}
      {(() => {
        const recoveryNotifs = (notifData?.notifications || []).filter(n => n.notification_type === 'recovery_escalation' || n.notification_type === 'stop_confirmation_reminder')
        return recoveryNotifs.length > 0 ? (
          <>
            <SectionHeader title="Recent Notifications" count={recoveryNotifs.length} />
            <Card compact>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {recoveryNotifs.map((n, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 9, alignItems: 'center' }}>
                    <span style={{
                      fontSize: 7, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                      background: n.notification_type === 'recovery_escalation' ? 'var(--accent-dim)' : 'var(--amber-dim)',
                      color: n.notification_type === 'recovery_escalation' ? 'var(--accent)' : 'var(--amber)',
                    }}>{n.notification_type === 'recovery_escalation' ? 'ESCALATION' : 'REMINDER'}</span>
                    <span style={{ color: 'var(--text2)' }}>{n.channel}</span>
                    <span style={{ flex: 1, color: 'var(--text1)' }}>{n.subject || n.body_summary?.slice(0, 60)}</span>
                    <span style={{ color: n.status === 'sent' ? 'var(--green)' : 'var(--text3)' }}>{n.status}</span>
                    {n.sent_at && <span style={{ color: 'var(--text3)' }}>{timeAgo(n.sent_at)}</span>}
                  </div>
                ))}
              </div>
            </Card>
          </>
        ) : null
      })()}
    </>
  )
}

const linkStyle: React.CSSProperties = { fontSize: 9, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }
