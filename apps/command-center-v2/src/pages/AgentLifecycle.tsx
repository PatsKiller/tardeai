import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import ActionButton from '../components/ActionButton'
import StatusBadge from '../components/StatusBadge'
import AgentChip from '../components/AgentChip'

/* ── Types ── */
interface AgentHealth { agent: string; total: number; latest: string; age_days: number; max_days: number; status: string }
interface CalAgent { agent_name: string; total_recommendations: number; accuracy_pct: number; correct_count: number; wrong_count: number; calibration_error: number; sample_size_status: string }
interface HealthAgent { agent: string; total_analyses: number; avg_confidence: number; last_run: string; low_conf_count: number }
interface Requirement { id: number; agent_name: string; use_case: string; expected_output: string; failure_conditions: string; acceptance_criteria: string; status: string; created_at: string }
interface QualityScores { [agent: string]: { accuracy: number; consistency: number; grounding: number; safety: number; explainability: number } }

/* ── Constants ── */
const AGENTS = ['maria', 'steph', 'risk_agent', 'tax_agent', 'alex', 'aegis', 'iris', 'maria_research']

const CHAINS: Record<string, { agents: string[]; desc: string }> = {
  portfolio_allocation: { agents: ['maria_research', 'steph', 'risk_agent', 'tax_agent'], desc: 'Full portfolio analysis chain' },
  market_research: { agents: ['maria_research'], desc: 'Single-agent market research' },
  stop_decision: { agents: ['risk_agent', 'maria_research'], desc: 'Stop-loss evaluation' },
  tax_or_roth: { agents: ['tax_agent', 'steph'], desc: 'Tax optimization routing' },
  escalation: { agents: ['maria_research', 'risk_agent', 'steph', 'alex'], desc: 'Multi-agent escalation' },
  portfolio_surveillance: { agents: ['aegis', 'steph'], desc: 'Overnight portfolio monitoring' },
  taxonomy_intelligence: { agents: ['iris'], desc: 'Research library management' },
}

const ESCALATION_RULES = [
  { rule: 'agent_conflict', trigger: 'Risk + Steph disagree on same symbol', action: 'Trigger debate, escalate to operator' },
  { rule: 'roth_conversion', trigger: 'Tax + Alex both flag Roth opportunity', action: 'Route to operator with combined analysis' },
  { rule: 'income_critical', trigger: 'Dividend cut or suspension detected', action: 'Alert operator, flag in portfolio' },
  { rule: 'ssdi_impact', trigger: 'Position change affects SSDI income threshold', action: 'Block execution, require operator review' },
]

const STAGES = [
  { id: 'define', num: 1, label: 'DEFINE', color: '#4a90f4',
    who: 'Product Owner', what: 'Define the agent\'s job — not features',
    tooltip: 'If you cannot test it, you didn\'t define it.' },
  { id: 'design', num: 2, label: 'DESIGN', color: '#8b5cf6',
    who: 'Architect, SME', what: 'Decision paths + prompt structure',
    tooltip: 'Every branch = a predictable outcome. No blind reasoning.' },
  { id: 'build', num: 3, label: 'BUILD', color: '#f59e0b',
    who: 'Engineer', what: 'Implement logic in system',
    tooltip: 'If you can\'t isolate a failure, your build is too coupled.' },
  { id: 'evaluate', num: 4, label: 'EVALUATE', color: '#ef4444',
    who: 'QA, Analyst', what: 'Measure output quality', critical: true,
    tooltip: 'If evaluation is weak, your agent is unsafe. Period.' },
  { id: 'deploy', num: 5, label: 'DEPLOY', color: '#10b981',
    who: 'DevOps', what: 'Push agent to production',
    tooltip: 'If you can\'t roll it back, don\'t deploy it.' },
  { id: 'monitor', num: 6, label: 'MONITOR', color: '#06b6d4',
    who: 'Ops + QA', what: 'Track real-world performance',
    tooltip: 'Production is where truth shows up.' },
  { id: 'improve', num: 7, label: 'IMPROVE', color: '#ec4899',
    who: 'Full team', what: 'Iterate agent',
    tooltip: 'No iteration = slow decay.' },
]

const QDIMS = [
  { key: 'accuracy', label: 'Accuracy', what: 'Correct output vs expectation', how: 'Test cases' },
  { key: 'consistency', label: 'Consistency', what: 'Same input = same output', how: 'Repeat runs' },
  { key: 'grounding', label: 'Grounding', what: 'Based on real data', how: 'Source linking' },
  { key: 'safety', label: 'Safety', what: 'No harmful output', how: 'Guardrails' },
  { key: 'explainability', label: 'Explainability', what: 'Reasoning is traceable', how: 'Logging' },
]

/* ── Helpers ── */
const Dot = ({ color, size = 8 }: { color: string; size?: number }) =>
  <span style={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', background: color, flexShrink: 0 }} />

const scoreColor = (v: number) => v >= 0.8 ? '#0ecb81' : v >= 0.6 ? '#f0b90b' : v >= 0.01 ? '#f6465d' : 'var(--text3)'

const Tip = ({ text }: { text: string }) => {
  const [show, setShow] = useState(false)
  return (
    <span style={{ position: 'relative', cursor: 'help' }} onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, borderRadius: '50%', background: 'rgba(255,255,255,.06)', fontSize: 9, color: 'var(--text3)' }}>?</span>
      {show && <span style={{ position: 'absolute', bottom: '130%', left: '50%', transform: 'translateX(-50%)', padding: '6px 10px', borderRadius: 6, fontSize: 10, background: '#2a2a3a', color: '#f0b90b', border: '1px solid #3a3a4a', zIndex: 10, fontStyle: 'italic', maxWidth: 280, whiteSpace: 'normal' }}>{text}</span>}
    </span>
  )
}

function computeStage(agent: string, health?: AgentHealth, calAgents?: CalAgent[]): { stage: string; status: 'ok' | 'warning' | 'blocked'; reason: string } {
  if (!health) return { stage: 'define', status: 'blocked', reason: 'No data' }
  if (health.status === 'dead') return { stage: 'monitor', status: 'blocked', reason: 'Agent dead' }
  const cal = (calAgents || []).find(c => c.agent_name === agent)
  if (!cal || cal.total_recommendations < 5) return { stage: 'evaluate', status: 'warning', reason: 'Insufficient calibration' }
  if (cal.accuracy_pct < 60) return { stage: 'evaluate', status: 'blocked', reason: `Accuracy ${cal.accuracy_pct}% < 60%` }
  if (health.status === 'stale') return { stage: 'monitor', status: 'warning', reason: 'Stale — needs attention' }
  return { stage: 'monitor', status: 'ok', reason: 'Operational' }
}

/* ── RequirementModal ── */
function RequirementModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ agent_name: 'maria', use_case: '', expected_output: '', failure_conditions: '', acceptance_criteria: '' })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const r = await fetch('/api/v2/agent-lifecycle/requirements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      const d = await r.json()
      if (d.ok) { onSaved(); onClose() } else setMsg(d.error || 'Save failed')
    } catch { setMsg('Network error') }
    setSaving(false)
  }

  const inputStyle = { width: '100%', padding: '6px 8px', background: 'var(--bg2, #161622)', border: '1px solid var(--border1, #2a2a3a)', borderRadius: 4, color: '#fff', fontSize: 11, fontFamily: 'monospace', resize: 'vertical' as const, minHeight: 50 }
  const labelStyle = { fontSize: 10, fontWeight: 700 as const, color: 'var(--text3)', textTransform: 'uppercase' as const, letterSpacing: '0.04em', marginBottom: 3 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1, #1e1e2e)', border: '1px solid var(--border1, #2a2a3a)', borderRadius: 10, padding: 24, width: '90vw', maxWidth: 600, maxHeight: '85vh', overflow: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>Create Agent Requirement</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', fontSize: 18, cursor: 'pointer' }}>x</button>
        </div>
        {msg && <div style={{ fontSize: 11, padding: '6px 10px', borderRadius: 6, background: 'rgba(246,70,93,.1)', color: '#f6465d', marginBottom: 10 }}>{msg}</div>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={labelStyle}>Agent</div>
            <select value={form.agent_name} onChange={e => set('agent_name', e.target.value)} style={{ ...inputStyle, minHeight: 30 }}>
              {AGENTS.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div><div style={labelStyle}>Use-Case</div><textarea value={form.use_case} onChange={e => set('use_case', e.target.value)} style={inputStyle} placeholder="What real scenario triggers this agent?" /></div>
          <div><div style={labelStyle}>Expected Output</div><textarea value={form.expected_output} onChange={e => set('expected_output', e.target.value)} style={inputStyle} placeholder="What observable output should the agent produce?" /></div>
          <div><div style={labelStyle}>Failure Conditions</div><textarea value={form.failure_conditions} onChange={e => set('failure_conditions', e.target.value)} style={inputStyle} placeholder="What would make this output wrong or harmful?" /></div>
          <div><div style={labelStyle}>Acceptance Criteria</div><textarea value={form.acceptance_criteria} onChange={e => set('acceptance_criteria', e.target.value)} style={inputStyle} placeholder="How do you test it passed? Measurable thresholds." /></div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <ActionButton variant="ghost" size="sm" onClick={onClose}>Cancel</ActionButton>
          <ActionButton variant="primary" size="sm" onClick={save} loading={saving} disabled={!form.use_case.trim()}>Save Requirement</ActionButton>
        </div>
      </div>
    </div>
  )
}

/* ── Main Page ── */
export default function AgentLifecycle() {
  const { data: cmd } = useApi<any>('/api/v2/command', 300_000)
  const { data: calData } = useApi<any>('/api/v2/agent-calibration/agents', 300_000)
  const { data: healthData } = useApi<any>('/api/v2/agent-health', 60_000)
  const { data: reqData, refetch: refetchReqs } = useApi<any>('/api/v2/agent-lifecycle/requirements', 60_000)
  const { data: qsData } = useApi<any>('/api/v2/agent-lifecycle/quality-scores', 300_000)
  const { data: improveData } = useApi<any>('/api/v2/self-improvement/status', 300_000)

  const [expanded, setExpanded] = useState<string | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [showReqModal, setShowReqModal] = useState(false)
  const nav = useNavigate()

  const agents = (cmd?.agent_health || []) as AgentHealth[]
  const calAgents = (calData?.agents || []) as CalAgent[]
  const healthAgents = (healthData?.agents || []) as HealthAgent[]
  const requirements = (reqData?.requirements || []) as Requirement[]
  const qualityScores = (qsData?.scores || {}) as QualityScores
  const staleAgents = agents.filter(a => a.status !== 'healthy')

  const filteredReqs = selectedAgent ? requirements.filter(r => r.agent_name === selectedAgent) : requirements

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <PageHeader title="Agent Lifecycle" subtitle="Operational model — Define, Design, Build, Evaluate, Deploy, Monitor, Improve"
        actions={
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <select value={selectedAgent || ''} onChange={e => setSelectedAgent(e.target.value || null)}
              style={{ padding: '4px 8px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border1, #2a2a3a)', borderRadius: 4, color: 'var(--text1)', fontFamily: 'monospace' }}>
              <option value="">All Agents</option>
              {AGENTS.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        }
      />

      {/* ═══ PER-AGENT LIFECYCLE STATE ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(155px, 1fr))', gap: 6 }}>
        {agents.map(a => {
          const s = computeStage(a.agent, a, calAgents)
          const stageConf = STAGES.find(st => st.id === s.stage)
          const isSelected = selectedAgent === a.agent
          return (
            <div key={a.agent} onClick={() => setSelectedAgent(isSelected ? null : a.agent)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                background: isSelected ? 'rgba(74,144,244,.08)' : a.status !== 'healthy' ? 'rgba(246,70,93,.04)' : 'var(--bg1, #1e1e2e)',
                border: isSelected ? '1px solid var(--accent)' : `1px solid ${a.status !== 'healthy' ? 'rgba(246,70,93,.2)' : 'var(--border1, #2a2a3a)'}` }}>
              <Dot color={s.status === 'ok' ? '#0ecb81' : s.status === 'warning' ? '#f0b90b' : '#f6465d'} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{a.agent}</div>
                <div style={{ fontSize: 8, color: 'var(--text3)' }}>{s.reason}</div>
              </div>
              <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: `${stageConf?.color || '#888'}20`, color: stageConf?.color || '#888', fontWeight: 600 }}>
                {s.stage.toUpperCase()}
              </span>
            </div>
          )
        })}
      </div>

      {/* ═══ LIFECYCLE PIPELINE BAR ═══ */}
      <div>
        <div style={{ display: 'flex', gap: 2, marginBottom: 4 }}>
          {STAGES.map((s, i) => (
            <div key={s.id} onClick={() => setExpanded(expanded === s.id ? null : s.id)}
              style={{ flex: 1, padding: '8px 4px', textAlign: 'center', cursor: 'pointer',
                borderRadius: i === 0 ? '6px 0 0 6px' : i === 6 ? '0 6px 6px 0' : 0,
                background: expanded === s.id ? s.color : `${s.color}20`,
                border: `1px solid ${s.color}40`, transition: 'all .15s' }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: expanded === s.id ? '#fff' : s.color, letterSpacing: '0.05em' }}>{s.label}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 8, color: 'var(--text3)', textAlign: 'center', letterSpacing: '0.02em' }}>
          DEFINE → DESIGN → BUILD → EVALUATE → DEPLOY → MONITOR → IMPROVE → loop
        </div>
      </div>

      {/* ═══ EXPANDED STAGE PANELS ═══ */}
      {expanded === 'define' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#4a90f4', fontSize: 11, fontWeight: 700, color: '#fff' }}>1</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#4a90f4' }}>DEFINE</span>
              <span style={{ fontSize: 10, color: 'var(--text2)' }}>Define the agent's job — not features</span>
              <Tip text="If you cannot test it, you didn't define it." />
            </div>
            <ActionButton variant="primary" size="sm" onClick={() => setShowReqModal(true)}>Create Requirement</ActionButton>
          </div>
          {filteredReqs.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No requirements defined yet. Create one to start.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {filteredReqs.map(r => (
                <div key={r.id} style={{ padding: '8px 10px', borderRadius: 6, background: 'rgba(74,144,244,.04)', border: '1px solid rgba(74,144,244,.1)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <AgentChip name={r.agent_name} size="sm" />
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', flex: 1 }}>{r.use_case}</span>
                    <StatusBadge status={r.status === 'active' ? 'fresh' : 'stale'} label={r.status} size="sm" />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontSize: 10, color: 'var(--text2)' }}>
                    <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Output:</span> {r.expected_output?.slice(0, 60)}</div>
                    <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Failure:</span> {r.failure_conditions?.slice(0, 60)}</div>
                    <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Acceptance:</span> {r.acceptance_criteria?.slice(0, 60)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {expanded === 'design' && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#8b5cf6', fontSize: 11, fontWeight: 700, color: '#fff' }}>2</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: '#8b5cf6' }}>DESIGN</span>
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>Decision paths + prompt structure</span>
            <Tip text="Every branch = a predictable outcome. No blind reasoning." />
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Agent Chains</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
            {Object.entries(CHAINS).map(([name, chain]) => (
              <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 6, background: 'rgba(139,92,246,.04)', border: '1px solid rgba(139,92,246,.1)' }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: '#8b5cf6', minWidth: 140 }}>{name.replace(/_/g, ' ')}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {chain.agents.map((a, i) => (
                    <span key={a} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      {i > 0 && <span style={{ color: 'var(--text3)', fontSize: 10 }}>→</span>}
                      <AgentChip name={a} size="sm" />
                    </span>
                  ))}
                </div>
                <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>{chain.desc}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Escalation Rules</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            {ESCALATION_RULES.map(r => (
              <div key={r.rule} style={{ padding: '6px 10px', borderRadius: 6, background: 'rgba(246,70,93,.04)', border: '1px solid rgba(246,70,93,.1)', fontSize: 10 }}>
                <div style={{ fontWeight: 700, color: '#f6465d', marginBottom: 2 }}>{r.rule.replace(/_/g, ' ')}</div>
                <div style={{ color: 'var(--text2)' }}>{r.trigger}</div>
                <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 2 }}>→ {r.action}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {expanded === 'build' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#f59e0b', fontSize: 11, fontWeight: 700, color: '#fff' }}>3</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#f59e0b' }}>BUILD</span>
              <span style={{ fontSize: 10, color: 'var(--text2)' }}>Implement logic in system</span>
              <Tip text="If you can't isolate a failure, your build is too coupled." />
            </div>
            <ActionButton variant="secondary" size="sm" onClick={() => nav('/strategy-admin')}>Open Config →</ActionButton>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            {[{ label: 'agents.yaml', desc: 'Agent definitions, confidence thresholds, intent routing' },
              { label: 'agent_raci.yaml', desc: 'RACI process definitions, cron triggers' },
              { label: 'agent_runtime.json', desc: 'Chains, operating windows, escalation rules' }
            ].map(f => (
              <div key={f.label} style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(245,158,11,.04)', border: '1px solid rgba(245,158,11,.1)' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', marginBottom: 2 }}>{f.label}</div>
                <div style={{ fontSize: 10, color: 'var(--text2)' }}>{f.desc}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {expanded === 'evaluate' && (
        <Card style={{ border: '1px solid rgba(239,68,68,.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#ef4444', fontSize: 11, fontWeight: 700, color: '#fff' }}>4</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#ef4444' }}>EVALUATE</span>
              <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, background: 'rgba(239,68,68,.15)', color: '#ef4444', fontWeight: 600 }}>CRITICAL GATE</span>
              <Tip text="If evaluation is weak, your agent is unsafe. Period." />
            </div>
            <ActionButton variant="danger" size="sm" onClick={() => nav('/agent-calibration')}>Full Calibration →</ActionButton>
          </div>
          {calAgents.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No calibration data available. Run calibration engine first.</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
              {calAgents.filter(c => !selectedAgent || c.agent_name === selectedAgent).map(c => {
                const pass = c.accuracy_pct >= 60
                return (
                  <div key={c.agent_name} style={{ padding: '10px 12px', borderRadius: 6,
                    background: pass ? 'rgba(14,203,129,.04)' : 'rgba(246,70,93,.06)',
                    border: `1px solid ${pass ? 'rgba(14,203,129,.2)' : 'rgba(246,70,93,.2)'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <AgentChip name={c.agent_name} size="sm" />
                      <span style={{ fontSize: 16, fontWeight: 700, color: pass ? '#0ecb81' : '#f6465d' }}>{c.accuracy_pct}%</span>
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                      {c.correct_count} correct · {c.wrong_count} wrong · {c.total_recommendations} total
                    </div>
                    <div style={{ fontSize: 9, marginTop: 2 }}>
                      <span style={{ color: pass ? '#0ecb81' : '#f6465d', fontWeight: 600 }}>{pass ? 'PASS' : 'FAIL'}</span>
                      <span style={{ color: 'var(--text3)', marginLeft: 6 }}>Gate: 60% minimum</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      )}

      {expanded === 'deploy' && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#10b981', fontSize: 11, fontWeight: 700, color: '#fff' }}>5</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: '#10b981' }}>DEPLOY</span>
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>Agent deployment status</span>
            <Tip text="If you can't roll it back, don't deploy it." />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6 }}>
            {agents.filter(a => !selectedAgent || a.agent === selectedAgent).map(a => (
              <div key={a.agent} onClick={() => nav(`/agent-dashboard/${a.agent}`)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                  background: 'rgba(16,185,129,.04)', border: '1px solid rgba(16,185,129,.15)' }}>
                <Dot color={a.status === 'healthy' ? '#0ecb81' : a.status === 'stale' ? '#f0b90b' : '#f6465d'} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{a.agent}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                    {a.status === 'healthy' ? 'Running' : a.status === 'stale' ? 'Degraded' : 'Stopped'}
                    {' · '}{a.age_days < 1 ? `${(a.age_days * 24).toFixed(0)}h ago` : `${a.age_days.toFixed(0)}d ago`}
                  </div>
                </div>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{a.total} runs</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {expanded === 'monitor' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#06b6d4', fontSize: 11, fontWeight: 700, color: '#fff' }}>6</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#06b6d4' }}>MONITOR</span>
              <span style={{ fontSize: 10, color: 'var(--text2)' }}>Track real-world performance</span>
              <Tip text="Production is where truth shows up." />
            </div>
            <ActionButton variant="secondary" size="sm" onClick={() => nav('/agent-pipeline')}>Full Pipeline →</ActionButton>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
            {healthAgents.filter(a => !selectedAgent || a.agent === selectedAgent).map(h => {
              const errRate = h.total_analyses > 0 ? (h.low_conf_count / h.total_analyses * 100) : 0
              return (
                <div key={h.agent} style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(6,182,212,.04)', border: '1px solid rgba(6,182,212,.1)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <AgentChip name={h.agent} size="sm" />
                    <span style={{ fontSize: 12, fontWeight: 700, color: h.avg_confidence >= 0.65 ? '#0ecb81' : '#f0b90b' }}>{(h.avg_confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div style={{ display: 'flex', gap: 12, fontSize: 9, color: 'var(--text2)' }}>
                    <span>{h.total_analyses} analyses</span>
                    <span style={{ color: errRate > 20 ? '#f6465d' : 'var(--text3)' }}>err: {errRate.toFixed(0)}%</span>
                    <span>{h.last_run ? new Date(h.last_run).toLocaleDateString() : 'never'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {expanded === 'improve' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: '#ec4899', fontSize: 11, fontWeight: 700, color: '#fff' }}>7</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#ec4899' }}>IMPROVE</span>
              <span style={{ fontSize: 10, color: 'var(--text2)' }}>Feed evaluation + monitoring data back into design</span>
              <Tip text="No iteration = slow decay." />
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <ActionButton variant="secondary" size="sm" onClick={() => nav('/self-improvement')}>View Lessons →</ActionButton>
              <ActionButton variant="primary" size="sm" onClick={() => setExpanded('define')}>Loop to Define →</ActionButton>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(236,72,153,.04)', border: '1px solid rgba(236,72,153,.1)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ec4899', marginBottom: 4 }}>Latest Intelligence</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
                {improveData?.latest_lessons || 'No lessons recorded yet. Run calibration + outcome scoring to generate improvement data.'}
              </div>
            </div>
            <div style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(236,72,153,.04)', border: '1px solid rgba(236,72,153,.1)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ec4899', marginBottom: 4 }}>Feedback Loop</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
                Evaluation → Monitoring → Improvement → Design restart. Each iteration re-enters the design phase with updated constraints from real-world performance data.
              </div>
              <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text3)' }}>
                Stale agents: {staleAgents.length > 0 ? staleAgents.map(a => a.agent).join(', ') : 'None'}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* ═══ QUALITY MODEL — LIVE SCORES ═══ */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Quality Model — No Hallucination Standard</span>
          {selectedAgent && <span style={{ fontSize: 10, color: 'var(--accent)' }}>Showing: {selectedAgent}</span>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
          {QDIMS.map(q => {
            const agentScores = selectedAgent ? qualityScores[selectedAgent] : null
            const avgScore = agentScores ? (agentScores as any)[q.key] || 0
              : Object.values(qualityScores).length > 0
                ? Object.values(qualityScores).reduce((sum, s) => sum + ((s as any)[q.key] || 0), 0) / Object.values(qualityScores).length
                : 0
            return (
              <div key={q.key} style={{ padding: '10px 12px', borderRadius: 6, background: 'rgba(74,144,244,.04)', border: '1px solid rgba(74,144,244,.1)', cursor: q.key === 'accuracy' ? 'pointer' : 'default' }}
                onClick={() => q.key === 'accuracy' && nav('/agent-calibration')}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 2 }}>{q.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: scoreColor(avgScore), marginBottom: 2 }}>{(avgScore * 100).toFixed(0)}%</div>
                <div style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 2 }}>{q.what}</div>
                <div style={{ fontSize: 8, color: 'var(--text3)', fontStyle: 'italic' }}>Enforce: {q.how}</div>
              </div>
            )
          })}
        </div>
      </Card>

      {/* ═══ SYSTEM CONNECTIONS ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 4 }}>Evaluation blocks Deployment</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 8 }}>No agent ships without passing quality gates.</div>
          <ActionButton variant="ghost" size="sm" onClick={() => nav('/agent-calibration')}>Calibration →</ActionButton>
        </Card>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#06b6d4', marginBottom: 4 }}>Monitoring feeds Improvement</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 8 }}>Drift, errors, and friction drive the next cycle.</div>
          <ActionButton variant="ghost" size="sm" onClick={() => nav('/agent-pipeline')}>Agent Pipeline →</ActionButton>
        </Card>
        <Card>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#ec4899', marginBottom: 4 }}>Improvement restarts Design</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 8 }}>Each iteration re-enters with updated constraints.</div>
          <ActionButton variant="ghost" size="sm" onClick={() => nav('/self-improvement')}>Self-Improvement →</ActionButton>
        </Card>
      </div>

      {showReqModal && <RequirementModal onClose={() => setShowReqModal(false)} onSaved={() => refetchReqs()} />}
    </div>
  )
}
