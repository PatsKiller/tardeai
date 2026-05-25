import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

/* ── palette ── */
const G = '#0ecb81', R = '#f6465d', Y = '#f0b90b', B = '#4a90f4', DIM = '#848e9c'
const bg = (c: string, a = .08) => `rgba(${c === G ? '14,203,129' : c === R ? '246,70,93' : c === Y ? '240,185,11' : '74,144,244'},${a})`

/* ── helpers ── */
const pct = (v: unknown) => typeof v === 'number' ? `${(v * 100).toFixed(0)}%` : '—'
const n2 = (v: unknown) => typeof v === 'number' ? v.toFixed(2) : '—'
const fmt = (v: number) => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)

function timeAgo(ts: string | null | undefined): string {
  if (!ts) return 'never'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return 'never'
  const sec = Math.floor((Date.now() - d.getTime()) / 1000)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}
function freshnessColor(ts: string | null | undefined): string {
  if (!ts) return R
  const hrs = (Date.now() - new Date(ts).getTime()) / 3600000
  return hrs < 24 ? G : hrs < 72 ? Y : R
}

function AccuracyRing({ accuracy, size = 64 }: { accuracy: number | null; size?: number }) {
  const pctVal = typeof accuracy === 'number' ? accuracy * 100 : 0
  const color = pctVal >= 70 ? G : pctVal >= 50 ? Y : R
  const r = (size - 8) / 2, c = 2 * Math.PI * r
  const offset = c - (c * Math.min(pctVal, 100) / 100)
  return (
    <svg width={size} height={size} style={{ display: 'block' }}>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--border)" strokeWidth={6} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={6}
        strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
        transform={`rotate(-90 ${size/2} ${size/2})`} />
      <text x={size/2} y={size/2 + 1} textAnchor="middle" dominantBaseline="middle"
        style={{ fontSize: size > 50 ? 16 : 12, fontWeight: 800, fill: color }}>
        {typeof accuracy === 'number' ? `${pctVal.toFixed(0)}%` : '—'}
      </text>
    </svg>
  )
}

function CalBar({ correct, incorrect, neutral, unresolved }: { correct: number; incorrect: number; neutral: number; unresolved: number }) {
  const total = correct + incorrect + neutral + unresolved
  if (!total) return null
  const segs = [
    { w: correct / total, c: G, l: `${correct} correct` },
    { w: incorrect / total, c: R, l: `${incorrect} incorrect` },
    { w: neutral / total, c: '#555', l: `${neutral} neutral` },
    { w: unresolved / total, c: 'var(--border)', l: `${unresolved} unresolved` },
  ]
  return (
    <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', width: '100%' }}
      title={segs.map(s => s.l).join(', ')}>
      {segs.filter(s => s.w > 0).map((s, i) => (
        <div key={i} style={{ width: `${s.w * 100}%`, background: s.c, minWidth: s.w > 0 ? 2 : 0 }} />
      ))}
    </div>
  )
}

function SignalDot({ value, thresholds }: { value: number | null; thresholds: [number, number] }) {
  if (value == null) return <span style={{ color: DIM }}>—</span>
  const color = value <= thresholds[0] ? G : value <= thresholds[1] ? Y : R
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={{ width: 6, height: 6, borderRadius: 3, background: color, display: 'inline-block' }} />
      <span style={{ color, fontWeight: 600 }}>{value.toFixed(2)}</span>
    </span>
  )
}

const btn: React.CSSProperties = { fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: 'var(--text1)', cursor: 'pointer' }

export default function AgentCalibration() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const { data: status } = useApi<any>(`/api/v2/agent-calibration/status?_r=${rk}`)
  const { data: agentList } = useApi<any>(`/api/v2/agent-calibration/agents?_r=${rk}`)
  const { data: windowList } = useApi<any>(`/api/v2/agent-calibration/windows?_r=${rk}`)
  const { data: eventList } = useApi<any>(`/api/v2/agent-calibration/events?_r=${rk}`)
  const { data: disagreeList } = useApi<any>(`/api/v2/agent-calibration/disagreements?_r=${rk}`)
  const { data: proposalList } = useApi<any>(`/api/v2/agent-calibration/weight-proposals?_r=${rk}`)

  const s = status || {}
  const agents: any[] = agentList || []
  const windows: any[] = windowList || []
  const allEvents: any[] = eventList || []
  const disagreements: any[] = disagreeList || []
  const proposals: any[] = proposalList || []

  // Filter events by selected agent
  const events = selectedAgent ? allEvents.filter((e: any) => e.agent_name === selectedAgent) : allEvents

  // Derive agent health signals from windows
  const agentCards = windows.map((w: any) => {
    const agentRecs = agents.find((a: any) => a.agent_name === w.agent_name)
    const calHealth = (w.calibration_error ?? 1) <= 0.2 ? 'good' : (w.calibration_error ?? 1) <= 0.4 ? 'warning' : 'poor'
    return { ...w, totalRecs: agentRecs?.total ?? 0, totalSymbols: agentRecs?.symbols ?? 0, calHealth }
  })

  // Agents without calibration windows (not enough data)
  const uncalibratedAgents = agents.filter((a: any) => !windows.some((w: any) => w.agent_name === a.agent_name))

  const tabBtn = (t: string, label: string, count?: number) => (
    <button onClick={() => { setTab(t); if (t === 'overview') setSelectedAgent(null) }} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)',
      color: tab === t ? '#fff' : 'var(--text1)',
      fontWeight: tab === t ? 700 : 400,
    }}>{label}{count !== undefined ? ` (${count})` : ''}</button>
  )

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1280 }}>
      <PageHeader title="Agent Calibration" subtitle="Are agents right? How confident should they be?" actions={
        <button onClick={() => setRk(k => k + 1)} style={{ ...btn, background: 'var(--accent)', color: '#fff' }}>Refresh</button>
      } />

      {/* ── Tab bar ── */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('events', 'Event Log', events.length)}
        {tabBtn('disagreements', 'Disagreements', disagreements.length)}
        {tabBtn('proposals', 'Weight Proposals', proposals.length)}
        {selectedAgent && (
          <span style={{ fontSize: 10, color: B, marginLeft: 8, cursor: 'pointer' }}
            onClick={() => setSelectedAgent(null)}>
            Filtering: <strong>{selectedAgent}</strong> &times;
          </span>
        )}
      </div>

      {/* ═══════════════ OVERVIEW ═══════════════ */}
      {tab === 'overview' && (<>

        {/* ── Pipeline health strip ── */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          {([
            ['Recommendations', s.recommendations_total, 'Total agent recs logged'],
            ['Linked to Outcomes', s.outcome_links_total, 'Recs matched to trades/proposals'],
            ['Scored Events', s.calibration_events_total, 'Events with pass/fail grades'],
            ['Link Rate', s.outcome_links_total && s.recommendations_total
              ? `${((s.outcome_links_total / s.recommendations_total) * 100).toFixed(1)}%` : '—',
              'What % of recs have outcome data'],
          ] as [string, any, string][]).map(([label, value, tip]) => (
            <div key={label} title={tip} style={{
              flex: '1 1 140px', padding: '10px 14px', borderRadius: 6,
              background: 'var(--bg1)', border: '1px solid var(--border)',
            }}>
              <div style={{ fontSize: 9, color: DIM, textTransform: 'uppercase', letterSpacing: '.5px' }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 800, marginTop: 2 }}>
                {typeof value === 'number' ? fmt(value) : value}
              </div>
            </div>
          ))}
        </div>

        {/* ── Freshness timestamps ── */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, padding: '8px 14px', borderRadius: 6,
          background: 'var(--bg1)', border: '1px solid var(--border)', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 9, color: DIM, textTransform: 'uppercase', fontWeight: 700, letterSpacing: '.5px' }}>Freshness</span>
          {([
            ['Last Calibration', s.last_calibration_run],
            ['Last Recommendation', s.last_recommendation],
            ['Last Outcome Link', s.last_outcome_link],
          ] as [string, string | null][]).map(([label, ts]) => (
            <span key={label} style={{ fontSize: 10, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: 3, background: freshnessColor(ts), display: 'inline-block' }} />
              <span style={{ color: DIM }}>{label}:</span>
              <span style={{ fontWeight: 600, color: freshnessColor(ts) }} title={ts || 'never'}>{timeAgo(ts)}</span>
            </span>
          ))}
        </div>

        {/* ── Agent scorecards ── */}
        {agentCards.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: DIM, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8 }}>
              Calibrated Agents
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
              {agentCards.map((w: any) => (
                <div key={w.agent_name} style={{
                  padding: '14px 16px', borderRadius: 8, background: 'var(--bg1)',
                  border: `1px solid ${w.calHealth === 'good' ? G : w.calHealth === 'warning' ? Y : R}33`,
                  cursor: 'pointer', transition: 'border-color .15s',
                }} onClick={() => { setSelectedAgent(w.agent_name); setTab('events') }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700 }}>{w.agent_name}</div>
                      <div style={{ fontSize: 10, color: DIM, marginTop: 2 }}>
                        {fmt(w.totalRecs)} recs &middot; {w.totalSymbols} symbols &middot; {w.resolved} resolved
                      </div>
                      <div style={{ fontSize: 9, color: freshnessColor(w.created_at), marginTop: 2 }}
                        title={w.created_at}>
                        Scored {timeAgo(w.created_at)}
                      </div>
                      <div style={{ fontSize: 9, marginTop: 4, padding: '2px 6px', borderRadius: 3, display: 'inline-block',
                        background: bg(w.sample_size_status === 'proposal_allowed' ? G : w.sample_size_status === 'shadow_only' ? B : Y),
                        color: w.sample_size_status === 'proposal_allowed' ? G : w.sample_size_status === 'shadow_only' ? B : Y,
                        fontWeight: 700 }}>
                        {w.sample_size_status?.replace('_', ' ').toUpperCase()}
                      </div>
                    </div>
                    <AccuracyRing accuracy={w.accuracy} />
                  </div>

                  {/* outcome bar */}
                  <CalBar correct={w.correct} incorrect={w.incorrect} neutral={w.neutral ?? 0} unresolved={w.unresolved ?? 0} />
                  <div style={{ fontSize: 9, color: DIM, marginTop: 4, display: 'flex', gap: 12 }}>
                    <span><span style={{ color: G }}>&#9632;</span> {w.correct} correct</span>
                    <span><span style={{ color: R }}>&#9632;</span> {w.incorrect} wrong</span>
                    <span><span style={{ color: '#555' }}>&#9632;</span> {w.neutral ?? 0} neutral</span>
                  </div>

                  {/* metrics row */}
                  <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 10 }}>
                    <div title="Average stated confidence">
                      <span style={{ color: DIM }}>Confidence </span>
                      <span style={{ fontWeight: 700 }}>{pct(w.avg_confidence)}</span>
                    </div>
                    <div title="Mean absolute error between confidence and outcome (lower = better calibrated)">
                      <span style={{ color: DIM }}>Cal Error </span>
                      <SignalDot value={w.calibration_error} thresholds={[0.2, 0.4]} />
                    </div>
                    <div title="Says confident but wrong (lower = better)">
                      <span style={{ color: DIM }}>Overconf </span>
                      <SignalDot value={w.overconfidence_score} thresholds={[0.15, 0.3]} />
                    </div>
                    <div title="Says unsure but right (lower = better)">
                      <span style={{ color: DIM }}>Underconf </span>
                      <SignalDot value={w.underconfidence_score} thresholds={[0.15, 0.3]} />
                    </div>
                  </div>

                  {/* action hint */}
                  <div style={{ marginTop: 10, fontSize: 10, color: B, fontWeight: 600, cursor: 'pointer' }}>
                    View {w.agent_name}'s scored events &rarr;
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Uncalibrated agents ── */}
        {uncalibratedAgents.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: DIM, textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8 }}>
              Not Yet Calibrated
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {uncalibratedAgents.map((a: any) => (
                <div key={a.agent_name} style={{
                  padding: '8px 12px', borderRadius: 6, background: 'var(--bg1)',
                  border: '1px solid var(--border)', fontSize: 11,
                }}>
                  <span style={{ fontWeight: 600 }}>{a.agent_name}</span>
                  <span style={{ color: DIM, marginLeft: 6 }}>{a.total} recs &middot; needs outcome links</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Empty state ── */}
        {!agentCards.length && !uncalibratedAgents.length && (
          <Card title="">
            <div style={{ textAlign: 'center', padding: 32, color: DIM }}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>No Calibration Data</div>
              <div style={{ fontSize: 11 }}>Run the calibration engine after paper trades close to see agent accuracy.</div>
            </div>
          </Card>
        )}
      </>)}

      {/* ═══════════════ EVENT LOG ═══════════════ */}
      {tab === 'events' && (
        <Card title={selectedAgent ? `${selectedAgent} — Scored Events` : 'All Scored Events'}>
          {!events.length ? <div style={{ color: DIM, padding: 16 }}>No events yet.</div> : (<>
            {/* outcome summary bar for filtered view */}
            {selectedAgent && (() => {
              const correct = events.filter((e: any) => e.actual_outcome === 'correct').length
              const incorrect = events.filter((e: any) => e.actual_outcome === 'incorrect').length
              const neutral = events.filter((e: any) => e.actual_outcome === 'neutral').length
              const unresolved = events.filter((e: any) => e.actual_outcome === 'unresolved').length
              return (
                <div style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 6, background: 'var(--bg0)' }}>
                  <div style={{ fontSize: 10, color: DIM, marginBottom: 4 }}>
                    {events.length} events: {correct} correct, {incorrect} incorrect, {neutral} neutral, {unresolved} pending
                  </div>
                  <CalBar correct={correct} incorrect={incorrect} neutral={neutral} unresolved={unresolved} />
                </div>
              )
            })()}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Agent', 'Symbol', 'Call', 'Conf', 'Outcome', 'P&L', 'Cal Err', 'When', 'Detail'].map(h =>
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: DIM, fontSize: 10 }}>{h}</th>)}
                </tr></thead>
                <tbody>{events.slice(0, 60).map((e: any, i: number) => {
                  const oc = e.actual_outcome === 'correct' ? G : e.actual_outcome === 'incorrect' ? R
                    : e.actual_outcome === 'neutral' ? '#555' : DIM
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px', cursor: 'pointer', color: B, fontWeight: 600 }}
                        onClick={() => { setSelectedAgent(e.agent_name); setTab('events') }}>
                        {e.agent_name}
                      </td>
                      <td style={{ padding: '6px 8px', fontWeight: 600 }}>{e.symbol}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <span style={{ padding: '1px 5px', borderRadius: 3, fontSize: 9, fontWeight: 700,
                          background: e.predicted_action === 'avoid' || e.predicted_action === 'sell' ? bg(R) : bg(G),
                          color: e.predicted_action === 'avoid' || e.predicted_action === 'sell' ? R : G,
                        }}>{e.predicted_action?.toUpperCase()}</span>
                      </td>
                      <td style={{ padding: '6px 8px' }}>{pct(e.predicted_confidence)}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ width: 6, height: 6, borderRadius: 3, background: oc }} />
                          <span style={{ color: oc, fontWeight: 600 }}>{e.actual_outcome}</span>
                        </span>
                      </td>
                      <td style={{ padding: '6px 8px', color: e.pnl > 0 ? G : e.pnl < 0 ? R : DIM, fontWeight: 600 }}>
                        {e.pnl != null ? `$${Number(e.pnl).toFixed(0)}` : '—'}
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        <SignalDot value={e.calibration_error} thresholds={[0.2, 0.4]} />
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 9, color: freshnessColor(e.created_at), whiteSpace: 'nowrap' }}
                        title={e.created_at}>
                        {timeAgo(e.created_at)}
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 10, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: DIM }}
                        title={e.explanation}>
                        {e.explanation}
                      </td>
                    </tr>
                  )
                })}</tbody>
              </table>
            </div>
            {events.length > 60 && <div style={{ padding: 8, fontSize: 10, color: DIM }}>Showing 60 of {events.length} events</div>}
          </>)}
        </Card>
      )}

      {/* ═══════════════ DISAGREEMENTS ═══════════════ */}
      {tab === 'disagreements' && (
        <Card title="Agent Disagreements">
          {!disagreements.length ? (
            <div style={{ textAlign: 'center', padding: 32, color: DIM }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>No disagreements recorded</div>
              <div style={{ fontSize: 11 }}>When agents disagree on a symbol, outcomes are tracked here to see who was right.</div>
            </div>
          ) : (
            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Symbol', 'Type', 'Agents', 'Winner', 'Loser', 'Outcome', 'Resolved'].map(h =>
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: DIM, fontSize: 10 }}>{h}</th>)}
              </tr></thead>
              <tbody>{disagreements.slice(0, 20).map((d: any, i: number) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{d.symbol}</td>
                  <td style={{ padding: '6px 8px' }}>{d.disagreement_type}</td>
                  <td style={{ padding: '6px 8px', fontSize: 10 }}>{JSON.stringify(d.agents_involved).slice(0, 40)}</td>
                  <td style={{ padding: '6px 8px', color: G, fontWeight: 600 }}>{d.winning_view || '—'}</td>
                  <td style={{ padding: '6px 8px', color: R }}>{d.losing_view || '—'}</td>
                  <td style={{ padding: '6px 8px', fontSize: 10 }}>{(d.outcome_summary || '').slice(0, 50)}</td>
                  <td style={{ padding: '6px 8px' }}>
                    {d.resolved
                      ? <span style={{ color: G, fontWeight: 700 }}>Yes</span>
                      : <span style={{ color: Y }}>Pending</span>}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {/* ═══════════════ WEIGHT PROPOSALS ═══════════════ */}
      {tab === 'proposals' && (
        <Card title="Agent Weight Proposals">
          {!proposals.length ? (
            <div style={{ textAlign: 'center', padding: 32, color: DIM }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>No weight proposals yet</div>
              <div style={{ fontSize: 11 }}>After 100+ resolved outcomes, the system proposes weight adjustments for each agent.</div>
            </div>
          ) : (
            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Agent', 'Domain', 'Current', 'Proposed', 'Delta', 'Sample', 'Status'].map(h =>
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: DIM, fontSize: 10 }}>{h}</th>)}
              </tr></thead>
              <tbody>{proposals.map((p: any) => (
                <tr key={p.shadow_proposal_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{p.agent_name}</td>
                  <td style={{ padding: '6px 8px' }}>{p.domain}</td>
                  <td style={{ padding: '6px 8px' }}>{n2(p.current_weight)}</td>
                  <td style={{ padding: '6px 8px', fontWeight: 700 }}>{n2(p.proposed_weight)}</td>
                  <td style={{ padding: '6px 8px', color: (p.weight_delta ?? 0) > 0 ? G : (p.weight_delta ?? 0) < 0 ? R : DIM, fontWeight: 700 }}>
                    {(p.weight_delta ?? 0) > 0 ? '+' : ''}{n2(p.weight_delta)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>{p.sample_size}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ padding: '2px 6px', borderRadius: 3, fontSize: 9, fontWeight: 700,
                      background: p.status === 'approved' ? bg(G) : p.status === 'rejected' ? bg(R) : bg(Y),
                      color: p.status === 'approved' ? G : p.status === 'rejected' ? R : Y,
                    }}>{p.status?.toUpperCase()}</span>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
