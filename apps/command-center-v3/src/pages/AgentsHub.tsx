import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import type { DrillContext } from '../components/DetailDrawer'
import OperatorInboxPanel from '../components/OperatorInboxPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
// Inbox hidden until v3 resolve is wired (was read-only pointer to v2).
const TABS = ['Roster', 'Calibration', 'Workflow', 'Performance', 'Weekly Learning'] as const

const G = '#22c55e', R = '#ef4444', A = '#f59e0b', B = '#60a5fa'
// Ground truth: AGENT_ROSTER.md (validated 2026-06-02). Roles are static identity, not in the API.
const ROLES: Record<string, string> = {
  alex: 'CIO / escalation arbiter', cio_engine: 'CIO decision engine',
  maria: 'Research analyst / catalyst', maria_research: 'Deep RAG research',
  steph: 'Income guardian / allocation', risk_agent: 'Risk / stops / portfolio heat',
  tax_agent: 'Tax / Roth / harvest', aegis: 'Surveillance / briefs',
  iris: 'Librarian / RAG coverage', social_scalp: 'Social mention scanner',
  scalp_critic: 'Scalp critic / validation',
}
// Real runtime model (roster doc lists qwen3:14b but its header marks that SUPERSEDED/disabled).
const RUNTIME_MODEL = 'gemma3:12b'
// RACI summary from agent_raci.yaml / AGENT_ROSTER.md (ground truth — not in the API).
const RACI: Record<string, string> = {
  alex: 'R: governance, escalation arbiter, retirement/IRMAA', cio_engine: 'R: CIO decisions',
  maria: 'R: daily watchlist batch, CIO analysis', maria_research: 'R: deep RAG research',
  steph: 'R: watchlist batch · C: overnight surveillance', risk_agent: 'R: watchlist batch · C: surveillance',
  tax_agent: 'C: daily watchlist batch', aegis: 'R: overnight surveillance, briefs',
  iris: 'R: RAG coverage, taxonomy', social_scalp: 'R: scalp scan', scalp_critic: 'R: scalp validation',
}
// Documented configured chain (agent_raci.yaml portfolio_allocation) — reference, not live activity.
const CONFIGURED_CHAIN = [['maria', 'steph'], ['steph', 'risk_agent'], ['risk_agent', 'tax_agent']]
// Grouped layout (Alex orchestrator hub on top; workers by function). Fallback grid for unknowns.
const POS: Record<string, { x: number; y: number }> = {
  alex: { x: 430, y: 0 }, cio_engine: { x: 650, y: 0 },
  maria: { x: 120, y: 150 }, steph: { x: 330, y: 150 }, risk_agent: { x: 540, y: 150 }, tax_agent: { x: 750, y: 150 },
  maria_research: { x: 120, y: 270 },
  aegis: { x: 360, y: 290 }, iris: { x: 520, y: 290 },
  social_scalp: { x: 720, y: 290 }, scalp_critic: { x: 880, y: 290 },
  auto_research: { x: 120, y: 40 }, synthesis: { x: 700, y: 420 }, human_review: { x: 900, y: 420 },
}
// Non-roster pipeline endpoints that appear in handoffs but aren't agents — describe them so the drawer is actionable.
const PIPELINE_NODES: Record<string, { label: string; desc: string; action: string }> = {
  human_review: { label: 'Human Review — operator escalation queue', desc: 'Escalation sink, not an autonomous agent. Escalated handoffs land here for operator decision.', action: 'Review escalated items in Home → Operator Inbox or Agents → Workflow.' },
  synthesis: { label: 'Synthesis step', desc: 'Aggregates agent outputs into a synthesized view and routes conflicts/escalations to Human Review.', action: 'No action — pipeline stage. Escalations it raises appear under Human Review.' },
  auto_research: { label: 'Auto-research dispatcher', desc: 'Automated research trigger that fans research tasks out to worker agents (maria/steph/risk).', action: 'No action — pipeline stage feeding the worker agents.' },
}
const normAgent = (s: string) => (s || '').toLowerCase()
const num = (n: any) => Number(n ?? 0)
const fmtPct = (v: any) => v == null ? '—' : (num(v) <= 1 ? (num(v) * 100).toFixed(0) : num(v).toFixed(0)) + '%'
const acc01 = (v: any) => num(v) <= 1 ? num(v) * 100 : num(v) // accuracy may be 0-1 or 0-100
function timeAgo(iso?: string) {
  if (!iso) return '—'
  const d = Date.parse(iso); if (isNaN(d)) return '—'
  const days = Math.floor((Date.now() - d) / 86400000)
  return days <= 0 ? 'today' : days === 1 ? '1d ago' : `${days}d ago`
}
// Staleness color for a last-run timestamp: fresh ≤1d green, ≤3d amber, older red.
// Prevention: a genuinely-stopped agent shows red instead of a misleading neutral grey.
function staleColor(iso?: string): string {
  if (!iso) return 'var(--text3)'
  const d = Date.parse(iso); if (isNaN(d)) return 'var(--text3)'
  const days = (Date.now() - d) / 86400000
  return days <= 1.5 ? G : days <= 3 ? A : R
}

function AccuracyRing({ accuracy, size = 60 }: { accuracy: any; size?: number }) {
  const pct = accuracy == null ? null : acc01(accuracy)
  const r = size / 2 - 6, c = 2 * Math.PI * r
  const col = pct == null ? 'var(--text3)' : pct >= 55 ? G : pct >= 35 ? A : R
  return (
    <svg width={size} height={size} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg2)" strokeWidth={5} />
      {pct != null && <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={col} strokeWidth={5}
        strokeDasharray={`${c * pct / 100} ${c}`} strokeLinecap="round" transform={`rotate(-90 ${size / 2} ${size / 2})`} />}
      <text x="50%" y="52%" textAnchor="middle" dominantBaseline="middle" fontSize={14} fontWeight={700} fill={col}>
        {pct != null ? `${pct.toFixed(0)}%` : '—'}
      </text>
    </svg>
  )
}

function CalBar({ correct, incorrect, neutral, unresolved }: any) {
  const total = Math.max(1, num(correct) + num(incorrect) + num(neutral) + num(unresolved))
  const segs = [
    { w: num(correct) / total, c: G }, { w: num(incorrect) / total, c: R },
    { w: num(neutral) / total, c: '#555' }, { w: num(unresolved) / total, c: 'var(--bg2)' },
  ]
  return (
    <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', background: 'var(--bg2)' }}>
      {segs.map((s, i) => <div key={i} style={{ width: `${s.w * 100}%`, background: s.c }} />)}
    </div>
  )
}

function SignalDot({ value, thresholds }: { value: any; thresholds: [number, number] }) {
  const v = num(value)
  const col = v <= thresholds[0] ? G : v <= thresholds[1] ? A : R
  return <span style={{ fontWeight: 700, color: col }}>{value == null ? '—' : v.toFixed(2)}</span>
}

export default function AgentsHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Roster')
  const { data: summary } = useApi<any>('/api/v2/agents/summary', 120_000)
  const { data: perfData } = useApi<any>('/api/v2/agent-performance', 120_000)
  const { data: calStatus } = useApi<any>('/api/v2/agent-calibration/status', 120_000)
  const { data: calAgents } = useApi<any>('/api/v2/agent-calibration/agents', 120_000)
  const { data: calWindows } = useApi<any>('/api/v2/agent-calibration/windows', 120_000)
  const { data: pipeline } = useApi<any>('/api/v2/agent-pipeline?limit=50', 120_000)
  const { data: weekly } = useApi<any>('/api/v2/weekly-learning', 300_000)

  const agents: any[] = summary?.agents ?? []
  const handoffs: any[] = summary?.handoffs ?? []
  const perf: any[] = perfData?.history ?? []
  const windows: any[] = (Array.isArray(calWindows) ? calWindows : calWindows?.windows) ?? []
  const agentList: any[] = (Array.isArray(calAgents) ? calAgents : calAgents?.agents) ?? []
  const symbolsByAgent: Record<string, number> = {}
  for (const a of agentList) symbolsByAgent[a.agent_name] = a.symbols ?? a.total ?? 0

  const allowed = windows.filter(w => w.sample_size_status === 'proposal_allowed').length

  // ── Workflow graph: nodes = agents, LIVE edges from /agent-pipeline (real from→to + escalated) ──
  const winByAgent: Record<string, any> = {}
  for (const w of windows) winByAgent[w.agent_name] = w
  const pipeHandoffs: any[] = pipeline?.handoffs ?? []
  // recent handoffs per agent (normalized) for the node drawer
  const handoffsByAgent: Record<string, any[]> = {}
  for (const h of pipeHandoffs) {
    const f = normAgent(h.from_agent), t = normAgent(h.to_agent)
    ;(handoffsByAgent[f] ||= []).push(h); (handoffsByAgent[t] ||= []).push(h)
  }
  const { rfNodes, rfEdges, liveEdgeCount } = useMemo(() => {
    const rosterNames = new Set(agents.map(a => a.agent))
    // aggregate live edges (normalized, deduped with counts + escalated flag)
    const live: Record<string, { from: string; to: string; cnt: number; esc: boolean }> = {}
    for (const h of pipeHandoffs) {
      const f = normAgent(h.from_agent), t = normAgent(h.to_agent)
      if (!f || !t) continue
      const k = `${f}>${t}`
      if (!live[k]) live[k] = { from: f, to: t, cnt: 0, esc: false }
      live[k].cnt++; live[k].esc = live[k].esc || !!h.escalated
    }
    const names = new Set<string>(rosterNames)
    Object.values(live).forEach(e => { names.add(e.from); names.add(e.to) })
    const list = [...names]
    // layout: POS map; unknown nodes fall into a bottom fallback row
    let fb = 0
    const nodes = list.map(n => {
      const w = winByAgent[n]
      const isRoster = rosterNames.has(n) || ROLES[n]
      const st = w?.sample_size_status
      const col = !isRoster ? '#64748b' : st === 'proposal_allowed' ? G : st === 'shadow_only' ? B : A
      const accTxt = w?.accuracy != null ? ` · ${acc01(w.accuracy).toFixed(0)}%` : ''
      const pos = POS[n] || { x: (fb++ % 5) * 200 + 60, y: 470 }
      const isHub = n === 'alex' || n === 'cio_engine'
      return {
        id: n, position: pos,
        data: { label: `${isHub ? '★ ' : ''}${n}${accTxt}${!isRoster ? '  (pipeline)' : ''}` },
        style: {
          background: `${col}1a`, border: `${isHub ? 2.5 : 1.5}px solid ${col}`, color: 'var(--text0)',
          borderRadius: 8, fontSize: 11, fontWeight: isHub ? 800 : 600, padding: '8px 12px',
          width: 168, opacity: isRoster ? 1 : 0.75,
        },
      }
    })
    // LIVE edges (animated). Escalated → amber, routed as drawn (e.g. synthesis→human_review).
    const liveEdges = Object.entries(live).map(([k, e]) => ({
      id: 'live_' + k, source: e.from, target: e.to, animated: true,
      label: e.esc ? `${e.cnt} escalation` : `${e.cnt}`,
      labelStyle: { fontSize: 9, fill: e.esc ? A : 'var(--text3)' }, labelBgStyle: { fill: 'var(--bg1)' },
      style: { stroke: e.esc ? A : B, strokeWidth: e.esc ? 2 : 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: e.esc ? A : B },
    }))
    // CONFIGURED chain (dashed, NOT animated, labeled) — drawn only if both ends exist & not already a live edge.
    const configEdges = CONFIGURED_CHAIN
      .filter(([f, t]) => names.has(f) && names.has(t) && !live[`${f}>${t}`])
      .map(([f, t]) => ({
        id: `cfg_${f}_${t}`, source: f, target: t, animated: false,
        label: 'configured', labelStyle: { fontSize: 8, fill: 'var(--text3)' }, labelBgStyle: { fill: 'var(--bg1)' },
        style: { stroke: 'var(--text3)', strokeWidth: 1, strokeDasharray: '5 4', opacity: 0.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--text3)' },
      }))
    return { rfNodes: nodes, rfEdges: [...configEdges, ...liveEdges], liveEdgeCount: liveEdges.length }
  }, [agents, pipeHandoffs, windows])

  return (
    <div>
      <div className="hub-title-row">
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Agents</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{agents.length} agents · {handoffs.length} recent handoffs · {allowed}/{windows.length} proposal-allowed</div>
        </div>
        <div className="hub-tabs">
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? B : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {/* ===== ROSTER ===== */}
      {tab === 'Roster' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          {agents.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 16 }}>No agent data from /agents/summary.</div> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Agent / role', 'Model', 'Actions', 'Buy / Sell / Hold', 'Avg conf', 'Last run'].map(h => <th key={h} style={{ textAlign: ['Agent / role', 'Model'].includes(h) ? 'left' : 'right', padding: '7px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
              </tr></thead>
              <tbody>{agents.map((a: any, i: number) => {
                const win = windows.find(w => w.agent_name === a.agent)
                return (
                  <tr key={i} onClick={() => onDrill({ title: a.agent, subtitle: `${ROLES[a.agent] ?? ''} · ${RUNTIME_MODEL}`, endpoint: '/api/v2/agents/summary', rows: [{ ...a, role: ROLES[a.agent] ?? '—', runtime_model: RUNTIME_MODEL }] })}
                    style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                    <td style={{ padding: '9px 10px' }}>
                      <div style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
                        {a.agent}
                        {win && <span style={{ marginLeft: 8, fontSize: 8, padding: '1px 6px', borderRadius: 3, fontWeight: 700,
                          background: win.sample_size_status === 'proposal_allowed' ? 'rgba(34,197,94,.12)' : 'rgba(96,165,250,.12)',
                          color: win.sample_size_status === 'proposal_allowed' ? G : B }}>
                          {(win.sample_size_status || '').replace('_', ' ').toUpperCase()}</span>}
                      </div>
                      <div style={{ fontSize: 9, color: 'var(--text3)' }}>{ROLES[a.agent] ?? '—'}</div>
                    </td>
                    <td style={{ padding: '9px 10px', fontSize: 10 }}><span style={{ fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{RUNTIME_MODEL}</span></td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', color: 'var(--text2)' }}>{a.actions_taken ?? a.total ?? '—'}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 11, color: 'var(--text3)' }}>
                      <span style={{ color: G }}>{a.buy_count ?? 0}</span> / <span style={{ color: R }}>{a.sell_count ?? 0}</span> / <span style={{ color: 'var(--text2)' }}>{a.hold_count ?? 0}</span>
                    </td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', color: 'var(--text2)' }}>{fmtPct(a.avg_confidence)}</td>
                    <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 10, color: staleColor(a.last_run), fontWeight: 600 }} title={a.last_run ? `Last run: ${new Date(a.last_run).toLocaleString()}` : 'No recorded run'}>{timeAgo(a.last_run)}</td>
                  </tr>
                )
              })}</tbody>
            </table>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/agents/summary (field: agent) + calibration gate from /agent-calibration/windows</div>
        </div>
      )}

      {/* ===== CALIBRATION ===== */}
      {tab === 'Calibration' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {calStatus && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Recommendations', v: calStatus.recommendations_total },
                { k: 'Calibration events', v: calStatus.calibration_events_total },
                { k: 'Outcome links', v: calStatus.outcome_links_total },
                { k: 'Proposal-allowed', v: `${allowed}/${windows.length}`, c: G },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: s.c || 'var(--text0)' }}>{s.v ?? 0}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{s.k}</div>
                </div>
              ))}
            </div>
          )}
          {windows.length === 0 ? (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 28, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
              No calibration windows yet. Run the calibration engine after paper trades close to score agent accuracy.
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 12 }}>
              {windows.map((w: any) => {
                const neutral = Math.max(0, num(w.resolved) - num(w.correct) - num(w.incorrect))
                const unresolved = Math.max(0, num(w.recommendations) - num(w.resolved))
                const status = w.sample_size_status
                const sc = status === 'proposal_allowed' ? G : status === 'shadow_only' ? B : A
                return (
                  <div key={w.window_id} onClick={() => onDrill({ title: w.agent_name, subtitle: `${(status || '').replace('_', ' ')} · ${w.recommendation ?? ''}`, endpoint: '/api/v2/agent-calibration/windows', rows: [w] })}
                    style={{ background: 'var(--bg1)', border: `1px solid ${sc}33`, borderRadius: 10, padding: 14, cursor: 'pointer' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{w.agent_name}</div>
                        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                          {num(w.recommendations)} recs · {symbolsByAgent[w.agent_name] ?? 0} symbols · {num(w.resolved)} resolved
                        </div>
                        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>Scored {timeAgo(w.created_at)} · {w.domain}</div>
                        <div style={{ fontSize: 9, marginTop: 4, padding: '2px 6px', borderRadius: 3, display: 'inline-block', fontWeight: 700, background: `${sc}22`, color: sc }}>
                          {(status || 'unscored').replace('_', ' ').toUpperCase()}
                        </div>
                      </div>
                      <AccuracyRing accuracy={w.accuracy} />
                    </div>
                    <CalBar correct={w.correct} incorrect={w.incorrect} neutral={neutral} unresolved={unresolved} />
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 12 }}>
                      <span><span style={{ color: G }}>■</span> {num(w.correct)} correct</span>
                      <span><span style={{ color: R }}>■</span> {num(w.incorrect)} wrong</span>
                      <span><span style={{ color: '#555' }}>■</span> {neutral} neutral</span>
                    </div>
                    <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 10, flexWrap: 'wrap' }}>
                      <div><span style={{ color: 'var(--text3)' }}>Confidence </span><span style={{ fontWeight: 700, color: 'var(--text1)' }}>{fmtPct(w.avg_confidence)}</span></div>
                      <div title="Mean abs error (lower better)"><span style={{ color: 'var(--text3)' }}>Cal err </span><SignalDot value={w.calibration_error} thresholds={[0.2, 0.4]} /></div>
                      <div title="Confident but wrong (lower better)"><span style={{ color: 'var(--text3)' }}>Overconf </span><SignalDot value={w.overconfidence_score} thresholds={[0.15, 0.3]} /></div>
                      <div title="Right but unsure (lower better)"><span style={{ color: 'var(--text3)' }}>Underconf </span><SignalDot value={w.underconfidence_score} thresholds={[0.15, 0.3]} /></div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/agent-calibration/{'{status,windows,agents}'} · accuracy=correct/resolved · PROPOSAL ALLOWED = trusted to propose, SHADOW ONLY = logged not acted</div>
        </div>
      )}

      {/* ===== WORKFLOW (React Flow) ===== */}
      {tab === 'Workflow' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 4 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Operator Inbox</div>
            <OperatorInboxPanel compact maxItems={5} />
          </div>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 10, color: 'var(--text3)', flexWrap: 'wrap' }}>
            <span>★ = orchestrator (Alex/CIO)</span>
            <span><span style={{ color: G }}>■</span> proposal-allowed</span>
            <span><span style={{ color: B }}>■</span> shadow-only</span>
            <span><span style={{ color: A }}>■</span> unscored</span>
            <span><span style={{ color: '#64748b' }}>■</span> pipeline (non-roster)</span>
            <span><span style={{ color: B }}>—</span> live handoff · <span style={{ color: A }}>—</span> escalation · <span style={{ color: 'var(--text3)' }}>--</span> configured</span>
            <span style={{ marginLeft: 'auto' }}>click node → calibration · RACI · handoffs</span>
          </div>
          <div style={{ height: 540, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
            {rfNodes.length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text3)', fontSize: 12 }}>No agent data to graph.</div>
            ) : (
              <ReactFlow
                nodes={rfNodes} edges={rfEdges} fitView proOptions={{ hideAttribution: true }}
                nodesDraggable={false} nodesConnectable={false} elementsSelectable={true}
                onNodeClick={(_e, node) => {
                  const all = handoffsByAgent[node.id] ?? []
                  const recent = all.slice(0, 8).map((h: any) => `${normAgent(h.from_agent)}→${normAgent(h.to_agent)}${h.escalated ? ' (esc)' : ''}${h.symbol ? ' ' + h.symbol : ''}${h.reason ? ' — ' + h.reason : ''}`)
                  const pn = PIPELINE_NODES[node.id]
                  if (pn) {
                    // Non-roster pipeline node — describe it + surface its real routed items (actionable, not dashes).
                    const escal = all.filter((h: any) => h.escalated || normAgent(h.to_agent) === node.id)
                    const isHumanReview = node.id === 'human_review'
                    onDrill({
                      title: pn.label, subtitle: 'pipeline endpoint — not an agent',
                      endpoint: '/api/v2/agent-pipeline (handoffs)',
                      links: isHumanReview ? [
                        { label: 'Home → Operator Inbox', href: '/v3/', note: 'Escalations + CIO review + pending proposals (last 14d)' },
                        { label: 'Agents → Workflow', href: '/v3/agents?tab=workflow', note: 'Pipeline graph + handoff drill-down' },
                      ] : undefined,
                      rows: [{
                        what_it_is: pn.desc,
                        items_routed_here: escal.length,
                        escalated: all.filter((h: any) => h.escalated).length,
                        what_to_do: isHumanReview
                          ? 'These are advisory escalations synthesis raised for a human to look at (e.g. a flagged symbol). Open Home → Operator Inbox or stay on Workflow (links above), review each flagged symbol, and route to Trading/Risk as needed. No trade executes from here — review-only.'
                          : pn.action,
                        routed_items: recent.length ? recent : '(none in last 50 handoffs)',
                      }],
                    })
                    return
                  }
                  const w = winByAgent[node.id]
                  const a = agents.find((x: any) => x.agent === node.id)
                  onDrill({
                    title: node.id,
                    subtitle: `${ROLES[node.id] ?? 'agent'}${w ? ` · ${(w.sample_size_status || '').replace('_', ' ')}` : ''}`,
                    endpoint: '/api/v2/agent-calibration/windows + /agent-pipeline',
                    rows: [{
                      agent: node.id, role: ROLES[node.id] ?? '—', runtime_model: RUNTIME_MODEL,
                      raci: RACI[node.id] ?? '—',
                      calibration: w ? `${acc01(w.accuracy).toFixed(0)}% acc · ${w.sample_size_status}` : 'no calibration window yet',
                      correct: w?.correct ?? '—', incorrect: w?.incorrect ?? '—', avg_confidence: w?.avg_confidence ?? '—',
                      ...(a ? {
                        working_on: `${a.buy_count ?? 0} buy · ${a.sell_count ?? 0} sell · ${a.hold_count ?? 0} hold (${a.total ?? 0} total recs)`,
                        schedule: '*/10–15 min via agent job worker',
                        last_run: a.last_run,
                      } : {}),
                      recent_handoffs: recent.length
                        ? recent
                        : 'None — collaboration edges (agent_handoffs) are written by the synthesis / escalation pipeline (synthesis, Alex, auto_research, system), not by individual worker agents. This agent collaborates by feeding its outputs downstream, which is expected — not a fault.',
                    }],
                  })
                }}
              >
                <Background color="var(--border)" gap={20} />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
          {liveEdgeCount === 0 && (
            <div style={{ fontSize: 9, color: A }}>No live handoff edges from /agent-pipeline — showing nodes + configured chain (dashed) only; no live edges fabricated.</div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Live edges: /api/v2/agent-pipeline (from_agent→to_agent, escalated). Node health: /agent-calibration/windows. Dashed = configured chain (agent_raci.yaml), not live. None fabricated.</div>
        </div>
      )}

      {/* ===== PERFORMANCE ===== */}
      {tab === 'Performance' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Agent Performance History ({perf.length})</div>
          {perf.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 11, padding: 16, lineHeight: 1.55 }}>
              No performance history recorded yet. Agent performance rolls up weekly via cron — check{' '}
              <Link to="/system?tab=jobs" style={{ color: '#60a5fa' }}>System → Jobs</Link> or{' '}
              <Link to="/health" style={{ color: '#60a5fa' }}>Health</Link> if runs look stuck.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Agent', 'Period', 'Recs', 'Accuracy', 'Avg conf', 'Rule viol.', 'Overrides'].map(h => <th key={h} style={{ textAlign: ['Agent', 'Period'].includes(h) ? 'left' : 'right', padding: '7px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                </tr></thead>
                <tbody>{perf.slice(0, 40).map((h: any, i: number) => (
                  <tr key={h.id ?? i} onClick={() => onDrill({ title: h.agent, subtitle: `${String(h.period_start).slice(0, 10)} → ${String(h.period_end).slice(0, 10)}`, endpoint: '/api/v2/agent-performance', rows: [h] })}
                    style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                    <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{h.agent}</td>
                    <td style={{ padding: '8px 10px', fontSize: 10, color: 'var(--text3)' }}>{String(h.period_start).slice(0, 10)} → {String(h.period_end).slice(0, 10)}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: 'var(--text2)' }}>{h.total_recommendations ?? '—'}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: acc01(h.accuracy_pct) >= 55 ? G : acc01(h.accuracy_pct) >= 35 ? A : R }}>{h.accuracy_pct != null ? fmtPct(h.accuracy_pct) : '—'}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: 'var(--text2)' }}>{fmtPct(h.avg_confidence)}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: num(h.rule_violations) > 0 ? R : 'var(--text3)' }}>{h.rule_violations ?? 0}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: num(h.human_overrides) > 0 ? A : 'var(--text3)' }}>{h.human_overrides ?? 0}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/agent-performance (fields: agent, accuracy_pct, avg_confidence, rule_violations, human_overrides)</div>
        </div>
      )}

      {/* ===== WEEKLY LEARNING ===== */}
      {tab === 'Weekly Learning' && (() => {
        const w = weekly?.data ?? weekly ?? {}
        const reviews = w.reviews ?? []
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--text2)' }}>
              <span>{w.review_count ?? 0} reviews</span>
              {(w.by_tier ?? []).map((t: any) => <span key={t.tier} style={{ color: 'var(--text3)' }}>{t.tier}: {t.count}</span>)}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 480, overflowY: 'auto' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Weekly trade reviews</div>
              {reviews.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--text3)', lineHeight: 1.55, padding: '8px 0' }}>
                  No weekly reviews yet — generated after closed paper trades. See{' '}
                  <Link to="/journal" style={{ color: '#60a5fa' }}>Journal</Link> or{' '}
                  <Link to="/system?tab=jobs" style={{ color: '#60a5fa' }}>System → Jobs</Link> for the review cron.
                </div>
              )}
              {reviews.map((r: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: `Trade #${r.paper_trade_id} · ${r.tier}`, subtitle: r.model_used ?? '', endpoint: '/api/v2/weekly-learning', rows: [r] })}
                  style={{ padding: '7px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: '#60a5fa' }}>{r.tier} · trade #{r.paper_trade_id}</span>
                    <span style={{ fontSize: 8, color: 'var(--text3)' }}>{r.model_used} · {timeAgo(r.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.4, maxHeight: 48, overflow: 'hidden' }}>{(r.review ?? '').slice(0, 240)}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/weekly-learning — multi-tier trade reviews + agent performance trend.</div>
          </div>
        )
      })()}
    </div>
  )
}
