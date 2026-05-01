import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { SmartTextarea } from './shared/SmartTextarea'

export interface TaskItem {
  id: number; source: string; category: string; symbol: string
  title: string; description: string; priority: string; status: string
  recommendation?: string; confidence?: number; due_by?: string
  linked_route?: string; followup?: string; decided_at?: string
  created_at?: string; provenance?: Record<string, unknown>
}

interface Props {
  task: TaskItem | null
  onClose: () => void
  onDecided?: (taskId: number, status: string) => void
}

const PRIORITY_COLOR: Record<string, string> = { urgent: 'var(--red)', high: 'var(--amber)', normal: 'var(--accent)', low: 'var(--text3)' }
const STATUS_LABEL: Record<string, string> = { pending_john: 'Needs John', decided_action: 'Resolved', deferred: 'Deferred', rejected: 'Rejected', revisit_later: 'Revisit', closed: 'Closed', failed_stop_review: 'Auto-Review Failed', failed_automation: 'Automation Failed' }
const CATEGORY_LABEL: Record<string, string> = { failed_stop_review: 'Failed Stop Review', failed_automation: 'Failed Automation', covered_call_decision: 'Covered Call', rotation_decision: 'Rotation', recovery_reentry_decision: 'Recovery Re-entry', risk_decision: 'Risk', thesis_decision: 'Thesis', general: 'General' }
const REC_COLOR: Record<string, string> = { BUY: '#00ff88', SELL: '#ff3355', HOLD: '#4499ff', TRIM: '#ffaa00', IGNORE: '#5a7fa8', RESEARCH_MORE: '#aa55ff' }
const AGENT_COLOR: Record<string, string> = { maria: '#ffaa00', risk_agent: '#ff4466', steph: '#00cc88', tax_agent: '#EF9F27', alex: '#aa55ff' }
const SOURCE_COLOR: Record<string, string> = { yahoo_rss: '#4499ff', google_news: '#00cc88', finnhub: '#aa55ff' }

function humanize(v?: string) { return v ? (STATUS_LABEL[v] || CATEGORY_LABEL[v] || v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase())) : '—' }

export default function TaskDetailDrawer({ task, onClose, onDecided }: Props) {
  const nav = useNavigate()
  const [note, setNote] = useState('')
  const [deciding, setDeciding] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [td, setTd] = useState<any>(null)
  const [ctx, setCtx] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!task?.id) return
    setTd(null); setCtx(null); setLoading(true)
    Promise.all([
      fetch(`/api/v2/task-detail/${task.id}`).then(r => r.json()).then(d => { if (d.ok) setTd(d.data) }).catch(() => {}),
      task.symbol ? fetch(`/api/v2/watchlist/context/${task.symbol}`).then(r => r.json()).then(d => { if (d.ok) setCtx(d.data) }).catch(() => {}) : Promise.resolve(),
    ]).finally(() => setLoading(false))
  }, [task?.id, task?.symbol])

  const handleDecision = useCallback(async (status: string) => {
    if (!task) return
    if (!note.trim()) { alert('A rationale note is required.'); return }
    setDeciding(status)
    try {
      // Use the new /tasks/<id>/resolve|defer|reject endpoint for john_decision_queue
      // Fall back to /approvals/decision for action_queue items
      const actionMap: Record<string, string> = { decided_action: 'resolve', deferred: 'defer', rejected: 'reject' }
      const action = actionMap[status] || 'resolve'
      let endpoint: string, reqBody: Record<string, unknown>
      if (task.source === 'action_queue') {
        const decisionMap: Record<string, string> = { decided_action: 'approved', deferred: 'deferred', rejected: 'rejected' }
        endpoint = '/api/v2/approvals/decision'
        reqBody = { queue_id: task.id, decision: decisionMap[status] || 'approved', note: note.trim() }
      } else {
        endpoint = `/api/v2/tasks/${task.id}/${action}`
        reqBody = { note: note.trim() }
      }
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(reqBody) })
      const d = await r.json()
      if (d.ok) { setResult(humanize(status)); onDecided?.(task.id, status); setTimeout(() => onClose(), 1200) }
      else alert(d.error || 'Decision failed')
    } catch { alert('Network error') }
    setDeciding(null)
  }, [task, note, onClose, onDecided])

  if (!task) return null

  const prov = task.provenance || {}
  const priColor = PRIORITY_COLOR[task.priority] || 'var(--text3)'
  const isFailed = task.category === 'failed_stop_review' || task.category === 'failed_automation'
  const failureReason = String(prov.failure_reason || '')

  const pnl = td?.pnl_summary as Record<string, any> | undefined
  const agents = (td?.agent_results || []) as any[]
  const news = (td?.news || []) as any[]
  const pastDec = (td?.past_decisions || []) as any[]
  const synth = ctx?.synthesis as any
  const conflict = ctx?.conflict as any
  const tech = ctx?.technicals || td?.technicals || {}
  const companyName = td?.holdings?.[0]?.security_name || ctx?.fundamentals?.name || ''
  const strategy = ctx?.strategy || ''

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '20px 24px', width: 580, maxHeight: '92vh', overflowY: 'auto', fontFamily: 'var(--sans)' }} onClick={e => e.stopPropagation()}>

        {/* === A: HEADER — company identity === */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: 24, fontWeight: 800, color: '#fff' }}>{task.symbol}</span>
              <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, textTransform: 'uppercase', background: `color-mix(in srgb, ${priColor} 15%, transparent)`, color: priColor }}>{task.priority}</span>
              {isFailed && <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>STOP TRIGGERED</span>}
            </div>
            {companyName && <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 2 }}>{companyName}</div>}
            {strategy && <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{strategy.replace(/_/g, ' ')}</div>}
            {news[0]?.title && <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic', marginTop: 4 }}>{news[0].title.slice(0, 80)}</div>}
          </div>
          <button onClick={onClose} style={{ fontSize: 14, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'transparent', color: 'var(--text3)', cursor: 'pointer', flexShrink: 0 }}>x</button>
        </div>

        {/* Description */}
        <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 12, padding: '8px 12px', background: 'var(--bg3)', borderRadius: 6, borderLeft: `3px solid ${priColor}` }}>{task.description}</div>

        {/* === B: P&L TILES === */}
        {pnl && (() => {
          const entry = Number(pnl.entry_price || 0), current = Number(pnl.current_price || 0)
          const stop = Number(pnl.stop_price || 0), shares = Number(pnl.total_shares || 0)
          const mktVal = Number(pnl.total_market_value || 0)
          const pnlD = Number(pnl.current_pnl_dollars || 0), pnlP = Number(pnl.current_pnl_pct || 0)
          const stopD = Number(pnl.stop_pnl_dollars || 0), stopP = Number(pnl.stop_pnl_pct || 0)
          const dist = Number(pnl.distance_to_stop_pct || 0), breached = Boolean(pnl.stop_breached)
          const pnlCol = pnlD >= 0 ? 'var(--green)' : 'var(--red)'
          const stopCol = breached ? 'var(--red)' : dist < 2 ? 'var(--amber)' : undefined
          return (
            <div style={{ marginBottom: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 5, marginBottom: 5 }}>
                <Tile label="Entry" value={entry > 0 ? `$${entry.toFixed(2)}` : '—'} />
                <Tile label="Current" value={current > 0 ? `$${current.toFixed(2)}` : '—'} />
                <Tile label="Shares" value={shares > 0 ? String(shares) : '—'} />
                <Tile label="Value" value={mktVal > 0 ? `$${mktVal.toLocaleString()}` : '—'} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 5 }}>
                <Tile label={breached ? 'STOP BREACHED' : 'Stop'} value={stop > 0 ? `$${stop.toFixed(2)}` : '—'} color={stopCol} />
                <Tile label="P&L" value={`${pnlD >= 0 ? '+' : ''}$${pnlD.toFixed(0)} (${pnlP >= 0 ? '+' : ''}${pnlP.toFixed(1)}%)`} color={pnlCol} />
                <Tile label="If Stopped" value={`$${stopD.toFixed(0)} (${stopP.toFixed(1)}%)`} color="var(--amber)" />
              </div>
            </div>
          )
        })()}
        {loading && !pnl && <Skeleton lines={2} />}

        {/* === C: AGENT CONFLICT BANNER === */}
        {conflict?.is_conflict && (
          <div style={{ background: 'rgba(255,170,0,.08)', border: '1px solid rgba(255,170,0,.25)', borderRadius: 6, padding: '10px 12px', marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--amber)', marginBottom: 4 }}>AGENT CONFLICT</div>
            <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
              {agents.filter(a => ['BUY','STRONG_BUY'].includes(a.recommendation)).map(a => a.agent_name?.replace('_agent','')).join(', ') || 'none'} say BUY vs {agents.filter(a => ['SELL','TRIM'].includes(a.recommendation)).map(a => a.agent_name?.replace('_agent','')).join(', ') || 'none'} say TRIM/SELL
            </div>
          </div>
        )}

        {/* === DATA QUALITY WARNING === */}
        {td?.data_quality?.all_research_more && (
          <div style={{ background: 'rgba(255,170,0,.1)', border: '1px solid rgba(255,170,0,.4)', borderLeft: '3px solid #ffaa00', borderRadius: 6, padding: '10px 14px', marginBottom: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#ffaa00', marginBottom: 4 }}>
              {td.data_quality.enrichment_attempted ? 'Agents still uncertain after data refresh' : 'Insufficient data for agent analysis'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>
              {td.data_quality.enrichment_attempted
                ? 'Auto-enrichment ran but agents still returned RESEARCH_MORE \u2014 genuine uncertainty, not a data gap.'
                : 'All agents returned RESEARCH_MORE \u2014 not enough data for a confident recommendation. Fresh enrichment has been queued automatically.'}
            </div>
            {td.data_quality.enrichment_date && (
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>Data refreshed: {td.data_quality.enrichment_date}</div>
            )}
            {(td.data_quality.missing_data?.length ?? 0) > 0 && (
              <div style={{ fontSize: 10, color: '#ffaa00', marginTop: 4 }}>Missing: {td.data_quality.missing_data.join(', ')}</div>
            )}
          </div>
        )}
        {/* Enrichment banner (when enrichment ran but agents are NOT all RESEARCH_MORE) */}
        {td?.data_quality?.enrichment_attempted && !td?.data_quality?.all_research_more && (
          <div style={{ background: 'rgba(0,212,255,.06)', border: '1px solid rgba(0,212,255,.2)', borderRadius: 6, padding: '6px 12px', marginBottom: 10, fontSize: 10, color: 'var(--accent)' }}>
            Data was auto-refreshed before this review \u2014 enrichment ran on {td.data_quality.enrichment_date || 'recently'}
          </div>
        )}

        {/* === D: CIO SYNTHESIS === */}
        {synth?.recommendation && (() => {
          const lowConf = (synth.confidence || 0) < 0.6 && synth.recommendation === 'HOLD'
          return (
            <div style={{ background: 'var(--bg3)', borderRadius: 6, padding: '10px 12px', marginBottom: 12, borderLeft: `3px solid ${lowConf ? '#5a7fa8' : (REC_COLOR[synth.recommendation] || 'var(--text3)')}` }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 9, fontWeight: 800 }}>{lowConf ? 'CIO: INSUFFICIENT DATA' : 'CIO SYNTHESIS'}</span>
                <RecBadge rec={synth.recommendation} />
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>conf {Math.round((synth.confidence || 0) * 100)}%</span>
              </div>
              {lowConf && <div style={{ fontSize: 10, color: '#ffaa00', marginBottom: 4 }}>Defaulting to HOLD — agent data insufficient for confident call</div>}
              {synth.synthesis_narrative && <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.6 }}>{synth.synthesis_narrative.slice(0, 250)}{synth.synthesis_narrative.length > 250 ? '...' : ''}</div>}
              {synth.action && <div style={{ fontSize: 10, color: 'var(--accent)', marginTop: 4, fontWeight: 600 }}>{String(synth.action).slice(0, 120)}</div>}
            </div>
          )
        })()}
        {loading && !synth && <Skeleton lines={3} />}

        {/* === E: AGENT VIEWS === */}
        {agents.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Agent Views</div>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(agents.length, 3)},1fr)`, gap: 6 }}>
              {agents.map((a, i) => {
                const name = (a.agent_name || '').replace('_agent', '')
                const col = AGENT_COLOR[a.agent_name] || AGENT_COLOR[name] || 'var(--text3)'
                return (
                  <div key={i} style={{ background: 'var(--bg-card)', border: `1px solid ${col}22`, borderRadius: 6, padding: '8px 10px' }}>
                    <div style={{ fontSize: 9, fontWeight: 800, color: col, textTransform: 'uppercase', marginBottom: 4 }}>{name}</div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
                      <RecBadge rec={a.recommendation} />
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{Math.round((a.confidence_score || 0) * 100)}%</span>
                      {a.recommendation === 'RESEARCH_MORE' && td?.data_quality?.enrichment_attempted && (
                        <span style={{ fontSize: 8, color: '#ffaa00', fontStyle: 'italic' }}>after refresh</span>
                      )}
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text2)', lineHeight: 1.5 }}>{(a.summary || '').slice(0, 100)}{(a.summary || '').length > 100 ? '...' : ''}</div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {loading && agents.length === 0 && <Skeleton lines={2} />}

        {/* === F: RECENT NEWS === */}
        {news.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>Recent News</div>
            {news.slice(0, 5).map((n: any, i: number) => {
              const src = n.source || 'unknown'
              const srcCol = SOURCE_COLOR[src] || '#5a7fa8'
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 2, background: `${srcCol}18`, color: srcCol, flexShrink: 0, textTransform: 'uppercase' }}>{src.replace(/_/g, ' ').slice(0, 12)}</span>
                  <span style={{ fontSize: 10, color: 'var(--text2)', flex: 1 }}>{(n.title || '').slice(0, 70)}</span>
                  {n.quality_score != null && <span style={{ fontSize: 8, color: 'var(--text3)', flexShrink: 0 }}>Q{n.quality_score}</span>}
                </div>
              )
            })}
          </div>
        )}

        {/* === G: TECHNICALS STRIP === */}
        {Object.keys(tech).length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
            {tech.rsi != null && <Pill label={`RSI ${Number(tech.rsi).toFixed(1)}`} color={Number(tech.rsi) > 70 ? 'var(--red)' : Number(tech.rsi) < 30 ? 'var(--green)' : 'var(--text3)'} />}
            {tech.beta != null && <Pill label={`Beta ${Number(tech.beta).toFixed(2)}`} />}
            {tech.sma_50 != null && <Pill label={`50d MA $${Number(tech.sma_50).toFixed(0)}`} />}
            {tech.sma_200 != null && <Pill label={`200d MA $${Number(tech.sma_200).toFixed(0)}`} />}
          </div>
        )}

        {/* === H: PAST DECISIONS === */}
        {pastDec.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 4 }}>Past Decisions</div>
            {pastDec.slice(0, 3).map((d: any, i: number) => (
              <div key={i} style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 3 }}>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 4px', borderRadius: 2, background: 'var(--bg3)', color: 'var(--text3)', marginRight: 6 }}>{humanize(d.status || d.decision)}</span>
                {d.decided_at?.slice(0, 10) || d.created_at?.slice(0, 10)} — {(d.reasoning || d.note || '').slice(0, 60)}
              </div>
            ))}
          </div>
        )}

        {/* === I: FAILURE NOTICE === */}
        {isFailed && failureReason && (
          <div style={{ fontSize: 10, color: 'var(--red)', padding: '6px 10px', background: 'var(--red-dim)', borderRadius: 4, marginBottom: 10, lineHeight: 1.4 }}>Failure: {failureReason}</div>
        )}
        {task.followup && <div style={{ fontSize: 11, color: 'var(--green)', fontWeight: 700, marginBottom: 8 }}>Next: {task.followup}</div>}
        {task.due_by && <div style={{ fontSize: 10, color: priColor, marginBottom: 8 }}>Due: {task.due_by}</div>}

        {task.linked_route && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            <button onClick={() => nav(task.linked_route!)} style={routeBtn}>Risk Manager</button>
            <button onClick={() => nav('/recovery')} style={routeBtn}>Recovery Watch</button>
            <button onClick={() => nav('/approvals')} style={routeBtn}>All Tasks</button>
          </div>
        )}

        {/* === J: DECISION === */}
        {result && (
          <div style={{ padding: '8px 12px', background: 'var(--green-dim)', border: '1px solid var(--green)', borderRadius: 6, marginBottom: 12, fontSize: 11, fontWeight: 700, color: 'var(--green)', textAlign: 'center' }}>Decision saved: {result}</div>
        )}
        {!result && (
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
            <div style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700, marginBottom: 6 }}>Decision note required</div>
            <SmartTextarea value={note} onChange={setNote} placeholder="Type your rationale here..." minHeight={70} showMic showAiRewrite pageType="approval" />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <DecisionBtn label="Resolve" color="var(--green)" status="decided_action" deciding={deciding} onClick={handleDecision} />
              <DecisionBtn label="Defer" color="var(--amber)" status="deferred" deciding={deciding} onClick={handleDecision} />
              <DecisionBtn label="Reject" color="var(--red)" status="rejected" deciding={deciding} onClick={handleDecision} />
            </div>
          </div>
        )}

        <div style={{ marginTop: 12, padding: '6px 8px', background: 'var(--bg3)', borderRadius: 4, fontSize: 9, color: 'var(--text3)' }}>
          Source: {task.source?.replace(/_/g, ' ')} | Created: {task.created_at?.slice(0, 16) || '—'} | ID: {task.id}
        </div>
      </div>
    </div>
  )
}

function Tile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '6px 8px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 5 }}>
      <div style={{ fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 2, fontFamily: 'var(--sans)' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 800, color: color || 'var(--text0)', fontFamily: 'var(--sans)' }}>{value}</div>
    </div>
  )
}

function RecBadge({ rec }: { rec: string }) {
  const col = REC_COLOR[rec] || '#5a7fa8'
  return <span style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 3, background: `${col}18`, color: col, textTransform: 'uppercase' }}>{rec}</span>
}

function Pill({ label, color = 'var(--text3)' }: { label: string; color?: string }) {
  return <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 10, background: 'var(--bg3)', color, border: '1px solid var(--border-subtle)', fontFamily: 'var(--mono)' }}>{label}</span>
}

function Skeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div style={{ marginBottom: 12 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 4, height: 14, width: `${60 + i * 15}%`, marginBottom: 6, animation: 'pulse 1.5s ease-in-out infinite' }} />
      ))}
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
    </div>
  )
}

function DecisionBtn({ label, color, status, deciding, onClick }: { label: string; color: string; status: string; deciding: string | null; onClick: (s: string) => void }) {
  return (
    <button onClick={() => onClick(status)} disabled={deciding !== null}
      style={{ flex: 1, padding: '8px 14px', fontSize: 11, fontWeight: 800, fontFamily: 'var(--sans)',
        border: `1px solid ${color}`, borderRadius: 6,
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
        color, cursor: deciding ? 'wait' : 'pointer', opacity: deciding && deciding !== status ? 0.4 : 1,
      }}>
      {deciding === status ? 'Saving...' : label}
    </button>
  )
}

const routeBtn: React.CSSProperties = { fontSize: 9, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--sans)' }
