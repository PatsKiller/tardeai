import { useMemo, useState } from 'react'
import type * as React from 'react'
import type { DrillContext } from '../components/DetailDrawer'
import AgentsHub from './AgentsHub'
import {
  AGENT_RUNTIME_CATALOG,
  AGENT_RUNTIME_CONTRACT,
  AGENT_RUNTIME_SNAPSHOT,
  DENIED_AUTHORITIES,
  summarizeAgentRuntime,
  type AgentLifecycle,
  type AgentRuntimeDefinition,
} from '../lib/agentRuntimeMonitoring'

interface Props { onDrill: (ctx: DrillContext) => void }
type View = 'Runtime' | 'Legacy analytics'

const lifecycleColor: Record<AgentLifecycle, string> = {
  DESIGNED: '#94a3b8', SHADOW: '#60a5fa', OPERATIONAL: '#22c55e', RESTRICTED: '#f59e0b', RETOOL: '#f97316', RETIRED: '#64748b',
}

const panel: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }
const label: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .5, fontWeight: 750 }

function StatusBadge({ children, color = '#60a5fa' }: { children: React.ReactNode; color?: string }) {
  return <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 7px', borderRadius: 999, border: `1px solid ${color}55`, background: `${color}18`, color, fontSize: 9, fontWeight: 800 }}>{children}</span>
}

function MetricCard({ value, title, detail, color }: { value: string | number; title: string; detail: string; color?: string }) {
  return <div style={{ ...panel, minHeight: 82 }}>
    <div style={{ fontSize: 24, fontWeight: 800, color: color || 'var(--text0)', lineHeight: 1 }}>{value}</div>
    <div style={{ marginTop: 7, fontSize: 10, fontWeight: 750, color: 'var(--text1)' }}>{title}</div>
    <div style={{ marginTop: 4, fontSize: 9, color: 'var(--text3)', lineHeight: 1.4 }}>{detail}</div>
  </div>
}

function AgentDetail({ agent }: { agent: AgentRuntimeDefinition }) {
  return <div style={{ ...panel, position: 'sticky', top: 0 }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{agent.displayName}</div>
        <div style={{ marginTop: 2, fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{agent.agentId} · {agent.version}</div>
      </div>
      <StatusBadge color={lifecycleColor[agent.lifecycle]}>{agent.lifecycle}</StatusBadge>
    </div>
    <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>{agent.objective}</div>
    {[
      ['Owner', agent.owner], ['Trigger', agent.trigger], ['Artifact', agent.artifact], ['Independent reviewer', agent.reviewer], ['Scorer', agent.scorer],
      ['Budget', `${agent.budget.maxModelCalls} model · ${agent.budget.maxToolCalls} tools · $${agent.budget.maxCostUsd.toFixed(2)} · ${agent.budget.deadlineSeconds}s`],
    ].map(([k, v]) => <div key={k} style={{ marginTop: 10 }}><div style={label}>{k}</div><div style={{ marginTop: 3, fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>{v}</div></div>)}
    <div style={{ marginTop: 12 }}><div style={label}>Current limitations</div>{agent.limitations.map(item => <div key={item} style={{ marginTop: 5, fontSize: 10, color: '#f5c76a' }}>• {item}</div>)}</div>
    <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
      <div style={label}>Disable / rollback</div>
      <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text2)' }}>{agent.disableControl}</div>
      <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text3)' }}>{agent.rollbackControl}</div>
    </div>
  </div>
}

function EmptyEvidence({ title, description }: { title: string; description: string }) {
  return <div style={{ ...panel, minHeight: 150 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><div style={{ fontSize: 12, fontWeight: 800 }}>{title}</div><StatusBadge color="#94a3b8">NOT RUN</StatusBadge></div>
    <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text3)', lineHeight: 1.55 }}>{description}</div>
    <div style={{ marginTop: 14, padding: 10, borderRadius: 8, background: 'var(--bg2)', fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--text3)' }}>Authoritative read adapter: NOT CONNECTED<br />Fixture is contract preview only; no production-derived evidence is displayed.</div>
  </div>
}

function RuntimeView() {
  const summary = useMemo(() => summarizeAgentRuntime(), [])
  const [selectedId, setSelectedId] = useState('sentinel')
  const selected = AGENT_RUNTIME_CATALOG.find(agent => agent.agentId === selectedId) || AGENT_RUNTIME_CATALOG[0]
  const acceptance = [
    ['Reviewed Watch artifacts', '0 / 100', 'NOT RUN'], ['Known-bad fixtures', '0 / 20 connected', 'NOT RUN'], ['Retrieval coverage', 'Not measured', 'NOT RUN'],
    ['Deterministic failures released', 'Not measured', 'NOT RUN'], ['Darwin scoring coverage', 'Not measured', 'NOT RUN'], ['Candidate lesson adjudication', 'Not connected', 'NOT RUN'],
  ]

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ ...panel, borderColor: 'rgba(96,165,250,.36)', background: 'rgba(96,165,250,.06)' }}>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center' }}>
        <StatusBadge>FIXTURE</StatusBadge><StatusBadge color="#94a3b8">NOT RUN</StatusBadge><StatusBadge color="#22c55e">READ ONLY</StatusBadge><StatusBadge color="#f59e0b">SHADOW ONLY</StatusBadge>
      </div>
      <div style={{ marginTop: 9, fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>This workspace renders the approved monitoring contract before the authoritative persistence read adapter is integrated. It does not claim live runs, artifacts, reviews, scores, cases, lessons, or operational agents.</div>
      <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{AGENT_RUNTIME_CONTRACT} · source={AGENT_RUNTIME_SNAPSHOT.source} · adapter={AGENT_RUNTIME_SNAPSHOT.adapterState} · as_of={AGENT_RUNTIME_SNAPSHOT.asOf}</div>
      {summary.catalogIssues.length > 0 && <div style={{ marginTop: 8, color: '#ef4444', fontSize: 10 }}>BLOCKED CONTRACT: {summary.catalogIssues.join(' · ')}</div>}
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
      <MetricCard value={summary.total} title="Canonical agents" detail="Stable IDs in the maturity catalog" />
      <MetricCard value={summary.lifecycle.SHADOW} title="Shadow agents" detail="Enabled only inside LAB/SHADOW authority" color="#60a5fa" />
      <MetricCard value={summary.lifecycle.DESIGNED} title="Designed agents" detail="Not enabled; prerequisites remain visible" />
      <MetricCard value={summary.lifecycle.OPERATIONAL} title="Operational agents" detail="Cannot be claimed before acceptance evidence" color="#22c55e" />
      <MetricCard value={summary.retrievalRequired} title="Retrieval required" detail="Definitions requiring memory before reasoning" />
      <MetricCard value={DENIED_AUTHORITIES.length} title="Denied authority classes" detail="Financial and production authority remains absent" color="#f59e0b" />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(280px,1fr)', gap: 12, alignItems: 'start' }}>
      <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}><div><div style={{ fontSize: 13, fontWeight: 800 }}>Agent catalog</div><div style={{ marginTop: 2, fontSize: 9, color: 'var(--text3)' }}>Click an agent to inspect its bounded contract.</div></div><StatusBadge color="#94a3b8">{summary.total} DEFINITIONS</StatusBadge></div>
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
          <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>{['Agent', 'Role', 'Lifecycle', 'Enabled', 'Retrieval', 'Deadline'].map(h => <th key={h} style={{ ...label, textAlign: h === 'Agent' || h === 'Role' ? 'left' : 'right', padding: '8px 10px' }}>{h}</th>)}</tr></thead>
          <tbody>{AGENT_RUNTIME_CATALOG.map(agent => <tr key={agent.agentId} onClick={() => setSelectedId(agent.agentId)} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', background: selectedId === agent.agentId ? 'rgba(96,165,250,.07)' : undefined }}>
            <td style={{ padding: '9px 10px' }}><div style={{ fontSize: 11, fontWeight: 750 }}>{agent.displayName}</div><div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{agent.agentId}</div></td>
            <td style={{ padding: '9px 10px', fontSize: 10, color: 'var(--text2)' }}>{agent.role}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right' }}><StatusBadge color={lifecycleColor[agent.lifecycle]}>{agent.lifecycle}</StatusBadge></td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 10, color: agent.enabled ? '#60a5fa' : 'var(--text3)' }}>{agent.enabled ? 'SHADOW' : 'NO'}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 10 }}>{agent.retrievalRequired ? 'REQUIRED' : 'N/A'}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 10, fontFamily: 'var(--mono)' }}>{agent.budget.deadlineSeconds}s</td>
          </tr>)}</tbody>
        </table></div>
      </div>
      <AgentDetail agent={selected} />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
      <EmptyEvidence title="Run queue and timeline" description="No persisted run timeline is connected. Running, blocked, failed, stale, cancelled, deadline-exceeded, checkpoint, budget, tool-call, and stop-reason states will come from the approved read adapter." />
      <EmptyEvidence title="Artifact review desk" description="No authoritative artifacts are loaded. Immutable hash, producer, independent reviewer, scorer, deterministic gate, contradictions, operator disposition, outcome, and Darwin score remain zero rather than inferred." />
      <EmptyEvidence title="Knowledge and learning" description="Cases, candidate lessons, ratified lessons, contradictions, Nightly Reflection outputs, and Iris/operator dispositions are not connected. Automatic production promotion remains impossible." />
    </div>

    <div style={{ ...panel }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}><div><div style={{ fontSize: 13, fontWeight: 800 }}>Authority and safety</div><div style={{ marginTop: 2, fontSize: 9, color: 'var(--text3)' }}>Deterministic financial authority remains outside the reflective runtime.</div></div><StatusBadge color="#22c55e">ZERO FINANCIAL AUTHORITY</StatusBadge></div>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 12 }}>{DENIED_AUTHORITIES.map(item => <StatusBadge key={item} color="#f59e0b">DENIED · {item}</StatusBadge>)}</div>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.25fr) minmax(280px,.75fr)', gap: 12 }}>
      <div style={{ ...panel }}><div style={{ fontSize: 13, fontWeight: 800 }}>Minimum Viable Loop acceptance</div><div style={{ marginTop: 3, fontSize: 9, color: 'var(--text3)' }}>Badges remain NOT RUN until evidence is connected and reviewed.</div>
        <div style={{ marginTop: 10 }}>{acceptance.map(([name, value, state]) => <div key={name} style={{ display: 'grid', gridTemplateColumns: '1fr 150px 80px', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', alignItems: 'center' }}><div style={{ fontSize: 10 }}>{name}</div><div style={{ fontSize: 10, color: 'var(--text2)', textAlign: 'right' }}>{value}</div><div style={{ textAlign: 'right' }}><StatusBadge color="#94a3b8">{state}</StatusBadge></div></div>)}</div>
      </div>
      <div style={{ ...panel }}><div style={{ fontSize: 13, fontWeight: 800 }}>Watch context contract</div><div style={{ marginTop: 8, fontSize: 10, color: 'var(--text2)', lineHeight: 1.55 }}>The first contextual panel will expose Sentinel integrity, reflective review state, Argus population findings, Darwin score, and related cases/lessons. It is read-only and cannot change the sovereign Watch decision or authorize an action.</div>
        <div style={{ marginTop: 12, display: 'grid', gap: 7 }}>{['Sentinel integrity · NOT CONNECTED', 'Argus findings · NOT RUN', 'Darwin score · NOT RUN', 'Case and lesson links · NOT CONNECTED', 'Action authority · NONE'].map(item => <div key={item} style={{ padding: 8, borderRadius: 7, background: 'var(--bg2)', fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{item}</div>)}</div>
      </div>
    </div>
  </div>
}

export default function AgentRuntimeHub({ onDrill }: Props) {
  const [view, setView] = useState<View>('Runtime')
  return <div>
    <div className="hub-title-row" style={{ marginBottom: 14 }}>
      <div><div style={{ fontSize: 22, fontWeight: 800 }}>Agents</div><div style={{ marginTop: 3, fontSize: 10, color: 'var(--text3)' }}>Governed runtime maturity, evidence, monitoring, and existing agent analytics.</div></div>
      <div className="hub-tabs" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{(['Runtime', 'Legacy analytics'] as View[]).map(item => <button key={item} type="button" onClick={() => setView(item)} style={{ border: '1px solid var(--border)', borderRadius: 7, background: view === item ? 'rgba(96,165,250,.14)' : 'var(--bg1)', color: view === item ? '#93c5fd' : 'var(--text2)', padding: '6px 10px', fontSize: 10, fontWeight: 750, cursor: 'pointer' }}>{item}</button>)}</div>
    </div>
    {view === 'Runtime' ? <RuntimeView /> : <AgentsHub onDrill={onDrill} />}
  </div>
}
