import { useApi } from '../hooks/useApi'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

/* ── Types ── */
interface AgentHealth { agent: string; total: number; latest: string; age_days: number; max_days: number; status: string }
interface QueueSummary { queued: number; processing: number; completed: number; failed: number }
interface EvalResult { agent: string; symbol: string; recommendation: string; confidence: number; model: string; rag_count: number; age: string }

interface LifecycleData {
  agent_health: AgentHealth[]
  queue: QueueSummary
  recent_results: EvalResult[]
  stop_audit_count: number
  pipeline_ok: boolean
  pipeline_note: string
  stale_agents: string[]
  total_agents: number
  healthy_count: number
}

/* ── Lifecycle Stage Config ── */
const STAGES = [
  { id: 'define', num: 1, label: 'DEFINE', color: '#4a90f4', icon: '1',
    who: 'Product Owner, Stakeholders', what: 'Define the agent\'s job — not features',
    when: 'Before any design/build', why: 'Prevent drift, hallucination, wasted build cycles',
    how: 'Use real use-cases (NOT theoretical prompts). Define success criteria (observable outputs).',
    action: 'Create Requirement', actionRoute: '/governance',
    tooltip: 'If you cannot test it, you didn\'t define it.' },
  { id: 'design', num: 2, label: 'DESIGN', color: '#8b5cf6', icon: '2',
    who: 'Architect, Prompt Engineer, SME', what: 'Decision paths + prompt structure',
    when: 'After definition is locked', why: 'Avoid brittle or unpredictable behavior',
    how: 'Map inputs → decisions → outputs. Define constraints (guardrails, tone, scope).',
    action: 'Open Flow Designer', actionRoute: '/strategy-admin',
    tooltip: 'Every branch = a predictable outcome. No blind reasoning.' },
  { id: 'build', num: 3, label: 'BUILD', color: '#f59e0b', icon: '3',
    who: 'Engineer', what: 'Implement logic in system',
    when: 'After design is locked', why: 'Convert theory → working system',
    how: 'Connect APIs / data. Apply prompts / functions. Modularize components.',
    action: 'Start Build', actionRoute: '/pipeline',
    tooltip: 'If you can\'t isolate a failure, your build is too coupled.' },
  { id: 'evaluate', num: 4, label: 'EVALUATE', color: '#ef4444', icon: '4',
    who: 'QA, Analyst, Human reviewers', what: 'Measure output quality',
    when: 'Continuous (NOT one-time)', why: 'Stop hallucinations & unsafe outputs',
    how: 'Golden dataset. Human scoring. Pass/fail thresholds.',
    action: 'Run Evaluation', actionRoute: '/agent-calibration',
    tooltip: 'If evaluation is weak, your agent is unsafe. Period.', critical: true },
  { id: 'deploy', num: 5, label: 'DEPLOY', color: '#10b981', icon: '5',
    who: 'DevOps / Platform', what: 'Push agent to production',
    when: 'AFTER passing evaluation', why: 'Deliver usable value',
    how: 'API / UI release. Version tagging. Rollback capability.',
    action: 'Deploy Agent', actionRoute: '/ops',
    tooltip: 'If you can\'t roll it back, don\'t deploy it.' },
  { id: 'monitor', num: 6, label: 'MONITOR', color: '#06b6d4', icon: '6',
    who: 'Ops + QA', what: 'Track real-world performance',
    when: 'Immediately after deployment', why: 'Detect drift + failure patterns',
    how: 'Logs. User feedback. Error tracking.',
    action: 'View Metrics', actionRoute: '/agent-pipeline',
    tooltip: 'Production is where truth shows up.' },
  { id: 'improve', num: 7, label: 'IMPROVE', color: '#ec4899', icon: '7',
    who: 'Full team', what: 'Iterate agent',
    when: 'Continuous cycle', why: 'Maintain relevance + accuracy',
    how: 'Feed evaluation + monitoring data back into design. Retrain / refine prompts.',
    action: 'Create New Iteration', actionRoute: '/self-improvement',
    tooltip: 'No iteration = slow decay.' },
]

const QUALITY_DIMS = [
  { dim: 'Accuracy', what: 'Correct output vs expectation', how: 'Test cases' },
  { dim: 'Consistency', what: 'Same input → same output', how: 'Repeat runs' },
  { dim: 'Grounding', what: 'Based on real data', how: 'Source linking' },
  { dim: 'Safety', what: 'No harmful output', how: 'Guardrails' },
  { dim: 'Explainability', what: 'Reasoning is traceable', how: 'Logging' },
]

/* ── Styled helpers ── */
const Card = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => (
  <div style={{ padding: '14px 16px', background: 'var(--bg1, #1e1e2e)', borderRadius: 8,
    border: '1px solid var(--border1, #2a2a3a)', ...style }}>{children}</div>
)

const Tip = ({ text }: { text: string }) => {
  const [show, setShow] = useState(false)
  return (
    <span style={{ position: 'relative', cursor: 'help' }}
      onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      <span style={{ display: 'inline-block', width: 14, height: 14, borderRadius: '50%', background: 'rgba(255,255,255,.06)',
        fontSize: 9, textAlign: 'center', lineHeight: '14px', color: 'var(--text3)' }}>?</span>
      {show && (
        <span style={{ position: 'absolute', bottom: '120%', left: '50%', transform: 'translateX(-50%)',
          whiteSpace: 'nowrap', padding: '6px 10px', borderRadius: 6, fontSize: 10,
          background: '#2a2a3a', color: '#f0b90b', border: '1px solid #3a3a4a', zIndex: 10,
          fontStyle: 'italic', maxWidth: 280 }}>{text}</span>
      )}
    </span>
  )
}

const AgentDot = ({ status }: { status: string }) => {
  const c = status === 'healthy' ? '#0ecb81' : status === 'stale' ? '#f0b90b' : '#f6465d'
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: c }} />
}

/* ── Main Page ── */
export default function AgentLifecycle() {
  const { data: cmd } = useApi<any>('/api/v2/command', 300_000)
  const nav = useNavigate()
  const [expanded, setExpanded] = useState<string | null>(null)

  const agents = (cmd?.agent_health || []) as AgentHealth[]
  const stale = agents.filter(a => a.status !== 'healthy')
  const healthy = agents.filter(a => a.status === 'healthy')

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ═══ HEADER ═══ */}
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', margin: '0 0 4px 0' }}>Agent Lifecycle</h2>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>
          Operational model — Define, Design, Build, Evaluate, Deploy, Monitor, Improve
        </div>
      </div>

      {/* ═══ LIVE AGENT STATUS STRIP ═══ */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Live Agent Status</div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>
            {healthy.length}/{agents.length} healthy
            {stale.length > 0 && <span style={{ color: '#f6465d', marginLeft: 8 }}>{stale.length} need attention</span>}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8 }}>
          {agents.map(a => (
            <div key={a.agent} onClick={() => nav(`/agent-dashboard/${a.agent}`)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                background: a.status !== 'healthy' ? 'rgba(246,70,93,.06)' : 'rgba(14,203,129,.04)',
                border: `1px solid ${a.status !== 'healthy' ? 'rgba(246,70,93,.2)' : 'rgba(14,203,129,.15)'}` }}>
              <AgentDot status={a.status} />
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: a.status !== 'healthy' ? '#f6465d' : 'var(--text0)' }}>{a.agent}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                  {a.age_days < 0.04 ? 'just now' : a.age_days < 1 ? `${(a.age_days * 24).toFixed(0)}h ago` : `${a.age_days.toFixed(0)}d ago`}
                  {' '}{a.total} runs
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ═══ LIFECYCLE PIPELINE — 7 stages ═══ */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Lifecycle Pipeline</div>

        {/* Visual flow bar */}
        <div style={{ display: 'flex', gap: 2, marginBottom: 12 }}>
          {STAGES.map((s, i) => (
            <div key={s.id} onClick={() => setExpanded(expanded === s.id ? null : s.id)}
              style={{ flex: 1, padding: '8px 4px', textAlign: 'center', cursor: 'pointer', borderRadius: i === 0 ? '6px 0 0 6px' : i === 6 ? '0 6px 6px 0' : 0,
                background: expanded === s.id ? s.color : `${s.color}20`,
                border: `1px solid ${s.color}40`, transition: 'all .15s' }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: expanded === s.id ? '#fff' : s.color, letterSpacing: '0.05em' }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Loop indicator */}
        <div style={{ fontSize: 9, color: 'var(--text3)', textAlign: 'center', marginBottom: 8, letterSpacing: '0.02em' }}>
          DEFINE → DESIGN → BUILD → EVALUATE → DEPLOY → MONITOR → IMPROVE → loop
        </div>

        {/* Expanded stage detail */}
        {expanded && (() => {
          const s = STAGES.find(st => st.id === expanded)!
          return (
            <Card style={{ border: `1px solid ${s.color}40`, marginBottom: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%',
                      background: s.color, fontSize: 11, fontWeight: 700, color: '#fff' }}>{s.num}</span>
                    <span style={{ fontSize: 15, fontWeight: 700, color: s.color }}>{s.label}</span>
                    {s.critical && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, background: 'rgba(239,68,68,.15)', color: '#ef4444', fontWeight: 600 }}>CRITICAL GATE</span>}
                    <Tip text={s.tooltip} />
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text1)', fontWeight: 500 }}>{s.what}</div>
                </div>
                <button onClick={() => nav(s.actionRoute)}
                  style={{ padding: '6px 14px', fontSize: 11, fontWeight: 600, border: `1px solid ${s.color}60`, borderRadius: 6,
                    background: `${s.color}15`, color: s.color, cursor: 'pointer', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  {s.action} →
                </button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12, fontSize: 11 }}>
                <div><span style={{ color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase' }}>Who</span><div style={{ color: 'var(--text1)', marginTop: 2 }}>{s.who}</div></div>
                <div><span style={{ color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase' }}>When</span><div style={{ color: 'var(--text1)', marginTop: 2 }}>{s.when}</div></div>
                <div><span style={{ color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase' }}>Why</span><div style={{ color: 'var(--text1)', marginTop: 2 }}>{s.why}</div></div>
                <div><span style={{ color: 'var(--text3)', fontSize: 9, textTransform: 'uppercase' }}>How</span><div style={{ color: 'var(--text1)', marginTop: 2 }}>{s.how}</div></div>
              </div>
            </Card>
          )
        })()}
      </div>

      {/* ═══ QUALITY MODEL ═══ */}
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
          Quality Model — No Hallucination Standard
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
          {QUALITY_DIMS.map(q => (
            <div key={q.dim} style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(74,144,244,.04)', border: '1px solid rgba(74,144,244,.1)' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent, #4a90f4)', marginBottom: 4 }}>{q.dim}</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4 }}>{q.what}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', fontStyle: 'italic' }}>Enforce: {q.how}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* ═══ SYSTEM CONNECTIONS ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>Evaluation blocks Deployment</div>
          <div style={{ fontSize: 10, color: 'var(--text2)' }}>No agent ships without passing quality gates. Accuracy, consistency, and grounding must meet thresholds.</div>
          <button onClick={() => nav('/agent-calibration')} style={{ marginTop: 8, padding: '4px 10px', fontSize: 10, border: '1px solid #ef444440', borderRadius: 5, background: 'rgba(239,68,68,.08)', color: '#ef4444', cursor: 'pointer', fontFamily: 'monospace' }}>Calibration →</button>
        </Card>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#06b6d4', marginBottom: 6 }}>Monitoring feeds Improvement</div>
          <div style={{ fontSize: 10, color: 'var(--text2)' }}>Production drift, error rates, and user friction signals drive the next iteration cycle.</div>
          <button onClick={() => nav('/agent-pipeline')} style={{ marginTop: 8, padding: '4px 10px', fontSize: 10, border: '1px solid #06b6d440', borderRadius: 5, background: 'rgba(6,182,212,.08)', color: '#06b6d4', cursor: 'pointer', fontFamily: 'monospace' }}>Agent Pipeline →</button>
        </Card>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#ec4899', marginBottom: 6 }}>Improvement restarts Design</div>
          <div style={{ fontSize: 10, color: 'var(--text2)' }}>Each iteration re-enters the design phase with updated constraints from real-world performance data.</div>
          <button onClick={() => nav('/self-improvement')} style={{ marginTop: 8, padding: '4px 10px', fontSize: 10, border: '1px solid #ec489940', borderRadius: 5, background: 'rgba(236,72,153,.08)', color: '#ec4899', cursor: 'pointer', fontFamily: 'monospace' }}>Self-Improvement →</button>
        </Card>
      </div>

    </div>
  )
}
