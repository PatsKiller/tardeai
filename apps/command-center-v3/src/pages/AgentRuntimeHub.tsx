import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import type { DrillContext } from '../components/DetailDrawer'
import { BB, T, TYPE, rowRail, numStyle } from '../lib/watchTokens'
import { Chip, ChipLegend } from '../components/TerminalChip'
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
import { resolveAgentRuntimeView, readApiBaseFromEnv, type ResolvedRuntimeView } from '../lib/agentRuntimeReadAdapter'
import { resolveAgentRuntimeDetail, type AgentDetailView } from '../lib/agentRuntimeDetailAdapter'
import {
  maturityHealthLabel,
  resolveAgentMaturityView,
  eligibilityRank,
  eligibilityTone,
  healthTone as maturityHealthTone,
  lifecycleTone as maturityLifecycleTone,
  maturityRail,
  needsAttention,
  samplePct,
  fleetGateCoveragePct,
  previewMaturityView,
  type ResolvedAgentMaturityView,
  type AgentMaturityObservation,
} from '../lib/agentMaturityObservability'

interface Props { onDrill: (ctx: DrillContext) => void }
type View = 'Runtime' | 'Legacy analytics'
type BadgeTone = 'blue' | 'green' | 'amber' | 'red' | 'slate'

const lifecycleTone: Record<AgentLifecycle, BadgeTone> = {
  DESIGNED: 'slate',
  SHADOW: 'blue',
  OPERATIONAL: 'green',
  RESTRICTED: 'amber',
  RETOOL: 'amber',
  RETIRED: 'slate',
}

const badgeTone: Record<BadgeTone, { color: string; background: string; border: string }> = {
  blue: { color: T.link, background: 'rgba(96,165,250,.12)', border: 'rgba(96,165,250,.34)' },
  green: { color: BB.green, background: BB.greenDim, border: 'rgba(34,197,94,.34)' },
  amber: { color: BB.amber, background: BB.amberDim, border: 'rgba(255,176,0,.34)' },
  red: { color: BB.red, background: BB.redDim, border: 'rgba(239,68,68,.34)' },
  slate: { color: BB.text3, background: 'rgba(148,163,184,.10)', border: 'rgba(148,163,184,.28)' },
}

const panel: CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: 14,
}
const label: CSSProperties = {
  fontSize: TYPE.xs,
  color: 'var(--text3)',
  textTransform: 'uppercase',
  letterSpacing: .5,
  fontWeight: 750,
}

function StatusBadge({ children, tone = 'blue' }: { children: ReactNode; tone?: BadgeTone }) {
  const colors = badgeTone[tone]
  return <span style={{
    display: 'inline-flex', alignItems: 'center', padding: '2px 7px', borderRadius: 999,
    border: `1px solid ${colors.border}`, background: colors.background, color: colors.color,
    fontSize: TYPE.xs, fontWeight: 800,
  }}>{children}</span>
}

function MetricCard({ value, title, detail, tone }: { value: string | number; title: string; detail: string; tone?: BadgeTone }) {
  return <div style={{ ...panel, minHeight: 82 }}>
    <div style={{ fontSize: TYPE.xl, fontWeight: 800, color: tone ? badgeTone[tone].color : 'var(--text0)', lineHeight: 1 }}>{value}</div>
    <div style={{ marginTop: 7, fontSize: TYPE.xs, fontWeight: 750, color: 'var(--text1)' }}>{title}</div>
    <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.4 }}>{detail}</div>
  </div>
}

function AgentDetail({ agent }: { agent: AgentRuntimeDefinition }) {
  const details: Array<[string, string]> = [
    ['Owner', agent.owner],
    ['Trigger', agent.trigger],
    ['Artifact', agent.artifact],
    ['Independent reviewer', agent.reviewer],
    ['Scorer', agent.scorer],
    ['Budget', `${agent.budget.maxModelCalls} model · ${agent.budget.maxToolCalls} tools · $${agent.budget.maxCostUsd.toFixed(2)} · ${agent.budget.deadlineSeconds}s`],
  ]
  return <div style={{ ...panel, position: 'sticky', top: 0 }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
      <div>
        <div style={{ fontSize: TYPE.lg, fontWeight: 800 }}>{agent.displayName}</div>
        <div style={{ marginTop: 2, fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{agent.agentId} · {agent.version}</div>
      </div>
      <StatusBadge tone={lifecycleTone[agent.lifecycle]}>{agent.lifecycle}</StatusBadge>
    </div>
    <div style={{ marginTop: 12, fontSize: TYPE.sm, color: 'var(--text1)', lineHeight: 1.5 }}>{agent.objective}</div>
    {details.map(([key, value]) => <div key={key} style={{ marginTop: 10 }}>
      <div style={label}>{key}</div>
      <div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.4 }}>{value}</div>
    </div>)}
    <div style={{ marginTop: 12 }}>
      <div style={label}>Current limitations</div>
      {agent.limitations.map(item => <div key={item} style={{ marginTop: 5, fontSize: TYPE.xs, color: BB.amber }}>• {item}</div>)}
    </div>
    <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
      <div style={label}>Disable / rollback</div>
      <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text2)' }}>{agent.disableControl}</div>
      <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text3)' }}>{agent.rollbackControl}</div>
    </div>
  </div>
}

function EmptyEvidence({ title, description }: { title: string; description: string }) {
  return <div style={{ ...panel, minHeight: 150 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <div style={{ fontSize: TYPE.base, fontWeight: 800 }}>{title}</div>
      <StatusBadge tone="slate">NOT RUN</StatusBadge>
    </div>
    <div style={{ marginTop: 12, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.55 }}>{description}</div>
    <div style={{ marginTop: 14, padding: 10, borderRadius: 8, background: 'var(--bg2)', fontFamily: 'var(--mono)', fontSize: TYPE.xs, color: 'var(--text3)' }}>
      Authoritative read adapter: NOT CONNECTED<br />Fixture is contract preview only; no production-derived evidence is displayed.
    </div>
  </div>
}


function LiveDesk({ title, badge, children }: { title: string; badge: string; children: ReactNode }) {
  return <div style={{ ...panel, minHeight: 150 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
      <div style={{ fontSize: TYPE.base, fontWeight: 800 }}>{title}</div>
      <StatusBadge tone="green">{badge}</StatusBadge>
    </div>
    <div style={{ marginTop: 10 }}>{children}</div>
    <div style={{ marginTop: 10, fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>Live read-only · agent-runtime read API · NO FINANCIAL AUTHORITY</div>
  </div>
}

function RunTimelineDesk({ d }: { d: AgentDetailView }) {
  return <LiveDesk title="Run queue and timeline" badge={`${d.runs.length} RUN${d.runs.length === 1 ? '' : 'S'}`}>
    <div style={{ fontSize: TYPE.xs, color: 'var(--text2)' }}>Role <b>{d.role.toUpperCase()}</b> · produced {d.counts.produced} · reviewed {d.counts.reviewed} · scored {d.counts.scored}</div>
    <div style={{ marginTop: 8, display: 'grid', gap: 5 }}>
      {d.runs.slice(0, 6).map(r => <div key={r.runId} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '5px 8px', borderRadius: 6, background: 'var(--bg2)', fontSize: TYPE.xs }}>
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--text3)' }}>{r.runId.slice(0, 14)}</span>
        <span><StatusBadge tone={r.status === 'COMPLETED' ? 'green' : r.status === 'FAILED' ? 'red' : 'slate'}>{r.status || 'UNKNOWN'}</StatusBadge></span>
      </div>)}
      {d.runs.length === 0 && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>No runs attributed to this agent yet (it has not produced/reviewed/scored).</div>}
    </div>
  </LiveDesk>
}

function ArtifactReviewDesk({ d }: { d: AgentDetailView }) {
  const verdicts = Object.entries(d.counts.byVerdict)
  return <LiveDesk title="Artifact review desk" badge={`${d.artifacts.length} SHOWN`}>
    {verdicts.length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>{verdicts.map(([v, n]) => <StatusBadge key={v} tone={v === 'PASS' ? 'green' : v === 'QUARANTINE' ? 'amber' : 'slate'}>{v} {n}</StatusBadge>)}</div>}
    <div style={{ display: 'grid', gap: 4, maxHeight: 190, overflowY: 'auto' }}>
      {d.artifacts.slice(0, 12).map(a => <div key={a.artifactId} style={{ padding: '5px 8px', borderRadius: 6, background: 'var(--bg2)', fontSize: TYPE.xs }}>
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--text3)' }}>{a.payloadHash.slice(0, 10) || a.artifactId.slice(0, 10)}</span>
        <span style={{ color: 'var(--text2)' }}> · {a.producer || '—'}</span>
        {a.reviewer && <span> · rev <b>{a.reviewer}</b>{a.verdict ? ` (${a.verdict})` : ''}</span>}
        {a.scorer && <span> · scr {a.scorer}</span>}
      </div>)}
      {d.artifacts.length === 0 && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>No artifacts attributed to this agent yet.</div>}
    </div>
  </LiveDesk>
}

function KnowledgeDesk({ d }: { d: AgentDetailView }) {
  return <LiveDesk title="Knowledge and learning" badge={`${d.lessons.total} LESSONS · ${d.cases.total} CASES`}>
    <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }}>Fleet knowledge base (read-only). Automatic production promotion remains impossible.</div>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {Object.entries(d.lessons.byLifecycle).map(([k, n]) => <StatusBadge key={k} tone="slate">lesson {k} {n}</StatusBadge>)}
      {Object.entries(d.cases.byType).map(([k, n]) => <StatusBadge key={k} tone="slate">case {k.replace(/_/g, ' ')} {n}</StatusBadge>)}
      {d.lessons.total === 0 && d.cases.total === 0 && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>No cases or lessons persisted yet.</div>}
    </div>
  </LiveDesk>
}

function SampleBar({ row }: { row: AgentMaturityObservation }) {
  const pct = samplePct(row)
  const text = `${row.sample_size ?? '—'} / ${row.required_sample_size ?? '—'}`
  return <div style={{ minWidth: 92, display: 'inline-block' }}>
    <div style={{ ...numStyle, fontSize: TYPE.xs, textAlign: 'right', color: pct === null ? 'var(--text3)' : 'var(--text1)' }}>{text}</div>
    <div style={{ marginTop: 3, height: 4, borderRadius: 2, background: 'rgba(148,163,184,0.18)', overflow: 'hidden' }}>
      <div style={{ width: `${pct ?? 0}%`, height: '100%', background: pct === null ? 'transparent' : BB.amber, transition: 'width .2s ease' }} />
    </div>
  </div>
}

function DetailField({ name, value, tone }: { name: string; value: ReactNode; tone?: string }) {
  return <div>
    <div style={label}>{name}</div>
    <div style={{ marginTop: 3, fontSize: TYPE.xs, color: tone ?? 'var(--text2)', lineHeight: 1.45, fontFamily: 'var(--mono)' }}>{value}</div>
  </div>
}

function MaturityDetail({ row }: { row: AgentMaturityObservation }) {
  const alerts = [...row.warnings, ...row.operator_checks_required]
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, padding: '10px 14px 14px 26px', background: 'var(--bg2)' }}>
    <DetailField name="Subsystem" value={row.subsystem} />
    <DetailField name="Environment" value={row.environment} />
    <DetailField name="Authority" value={row.effective_authority_state.replace(/_/g, ' ')} />
    <DetailField name="Denied authorities" value={row.denied_authorities.join(', ') || 'none listed'} />
    <DetailField name="Activation" value={`declared ${row.declared_production_activation_authorized === null ? 'UNKNOWN' : row.declared_production_activation_authorized ? 'YES' : 'NO'} · live verified ${row.effective_production_activation_verified ? 'YES' : 'NO'}`} tone={row.effective_production_activation_verified ? BB.green : BB.amber} />
    <DetailField name="Framework" value={`${row.maturity_framework} · ${row.maturity_framework_version ?? 'UNKNOWN'}`} />
    <DetailField name="Next gate" value={row.next_gate_id ?? row.next_gate_state} />
    <DetailField name="Gate detail" value={row.next_gate_description ?? '—'} />
    <DetailField name="Last healthy review" value={row.last_successful_review_at ?? 'NOT RUN'} />
    <DetailField name="Last degraded review" value={row.last_degraded_review_at ?? 'NOT RUN'} tone={row.last_degraded_review_at ? BB.amber : undefined} />
    <DetailField name="Last restriction" value={row.last_restriction_or_demotion_at ?? '—'} />
    <DetailField name="Freshness" value={row.freshness_state.replace(/_/g, ' ')} tone={row.freshness_state.includes('UNVERIFIED') ? BB.amber : undefined} />
    <DetailField name="Evidence" value={row.evidence_refs.join(', ') || '—'} />
    {alerts.length > 0 && <div style={{ gridColumn: '1 / -1' }}>
      <div style={label}>Warnings and operator checks</div>
      {alerts.map(a => <div key={a} style={{ marginTop: 4, fontSize: TYPE.xs, color: BB.amber, lineHeight: 1.45 }}>• {a}</div>)}
    </div>}
  </div>
}

function MaturityScoreboard({ view }: { view: ResolvedAgentMaturityView }) {
  const [preview, setPreview] = useState(false)
  const [filter, setFilter] = useState<'all' | 'shadow' | 'designed' | 'attention'>('all')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const effView = preview ? previewMaturityView() : view
  const payload = effView.payload
  const summary = payload?.summary
  const allRows = payload?.data ?? []

  const rows = useMemo(() => {
    const f = allRows.filter(r =>
      filter === 'all' ? true
        : filter === 'shadow' ? r.declared_lifecycle_state === 'SHADOW'
          : filter === 'designed' ? r.declared_lifecycle_state === 'DESIGNED'
            : needsAttention(r))
    return [...f].sort((a, b) => eligibilityRank(a) - eligibilityRank(b) || a.display_name.localeCompare(b.display_name))
  }, [allRows, filter])

  const total = summary?.total_agents ?? 0
  const eligible = summary?.eligible_for_human_review ?? 0
  const capped = summary?.sample_size_capped_agents ?? 0
  const unverified = summary?.unverified_runtime_status ?? 0
  const coverage = fleetGateCoveragePct(allRows)
  const attentionCount = allRows.filter(needsAttention).length
  const showUnverifiedBanner = !!summary && !preview && total > 0 && eligible === 0 && capped === 0 && unverified >= total

  const headers = ['Agent', 'Lifecycle', 'Sample gate', 'Review health', 'Next gate', 'Eligibility', '']
  const filters: Array<{ key: typeof filter; label: string; count: number }> = [
    { key: 'all', label: 'All', count: allRows.length },
    { key: 'shadow', label: 'Shadow', count: allRows.filter(r => r.declared_lifecycle_state === 'SHADOW').length },
    { key: 'designed', label: 'Designed', count: allRows.filter(r => r.declared_lifecycle_state === 'DESIGNED').length },
    { key: 'attention', label: 'Needs attention', count: attentionCount },
  ]

  return <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
    {/* Header: title, provenance, connection state, chip legend, preview toggle */}
    <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
      <div>
        <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Maturity scoreboard</div>
        <div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.45 }}>{effView.detail}</div>
        {payload && <div style={{ marginTop: 5, ...numStyle, fontSize: TYPE.xs, color: 'var(--text3)' }}>{payload.contract} · {payload.schema_version} · {payload.generated_at}</div>}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
        <ChipLegend />
        <button
          type="button"
          onClick={() => setPreview(p => !p)}
          title="Front-end-only illustrative sample rows; never live data."
          style={{ ...actionToggleStyle(preview) }}>
          {preview ? 'PREVIEW ON' : 'PREVIEW'}
        </button>
        <Chip kind="state" tone={effView.state === 'CONNECTED' ? (preview ? 'amber' : 'green') : effView.state === 'NOT_CONNECTED' ? 'amber' : 'red'}>
          {preview ? 'SAMPLE - NOT LIVE' : effView.state}
        </Chip>
      </div>
    </div>

    {/* Honest single empty-state banner when nothing is verifiable yet */}
    {showUnverifiedBanner && <div style={{ margin: '12px 14px', padding: '10px 12px', borderRadius: 6, border: `1px solid ${BB.amber}`, background: BB.amberDim, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <span style={{ color: BB.amber, fontWeight: 900, fontSize: TYPE.md, lineHeight: 1 }}>!</span>
      <div style={{ fontSize: TYPE.xs, color: 'var(--text1)', lineHeight: 1.5 }}>
        <b>Runtime evidence not connected</b> — showing declared repository posture for {total} agents. Live gates, sample counts, and review health populate once the runtime read adapter (DSN) is wired. No agent can be eligible without verified evidence. Use <b>Preview</b> to see the populated layout.
      </div>
    </div>}

    {/* FLEET summary strip */}
    {payload && <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .5, fontWeight: 750 }}>Fleet</div>
        <div style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 800, color: 'var(--text0)' }}>{eligible} <span style={{ fontSize: TYPE.sm, color: 'var(--text3)', fontWeight: 700 }}>of {total} eligible</span></div>
      </div>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 4 }}>
          <span>Sample gate coverage</span><span style={{ ...numStyle, color: 'var(--text2)' }}>{coverage}%</span>
        </div>
        <div style={{ height: 6, borderRadius: 3, background: 'rgba(148,163,184,0.16)', overflow: 'hidden' }}>
          <div style={{ width: `${coverage}%`, height: '100%', background: coverage > 0 ? BB.green : 'transparent', transition: 'width .2s ease' }} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
        <Chip kind="count" warn={capped > 0}>{capped}</Chip><span style={{ fontSize: TYPE.xs, color: 'var(--text3)', alignSelf: 'center' }}>capped</span>
        <Chip kind="count" warn={attentionCount > 0}>{attentionCount}</Chip><span style={{ fontSize: TYPE.xs, color: 'var(--text3)', alignSelf: 'center' }}>attention</span>
        <Chip kind="count" warn={unverified > 0}>{unverified}</Chip><span style={{ fontSize: TYPE.xs, color: 'var(--text3)', alignSelf: 'center' }}>unverified</span>
      </div>
    </div>}

    {/* Filter segment */}
    {payload && <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {filters.map(f => <button key={f.key} type="button" onClick={() => setFilter(f.key)} style={filterTabStyle(filter === f.key)}>
        {f.label} <span style={{ ...numStyle, color: filter === f.key ? BB.amber : 'var(--text3)' }}>{f.count}</span>
      </button>)}
    </div>}

    {/* Ranked board */}
    <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
      <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>{headers.map((header, i) => <th key={header || `h${i}`} style={{ ...label, textAlign: header === 'Agent' || header === 'Next gate' ? 'left' : header === '' ? 'center' : 'left', padding: '8px 10px' }}>{header}</th>)}</tr></thead>
      <tbody>{rows.map(row => {
        const open = !!expanded[row.agent_id]
        return <FragmentRow key={row.agent_id}
          row={row} open={open}
          onToggle={() => setExpanded(e => ({ ...e, [row.agent_id]: !e[row.agent_id] }))} />
      })}
      {payload && rows.length === 0 && <tr><td colSpan={headers.length} style={{ padding: 16, textAlign: 'center', fontSize: TYPE.xs, color: 'var(--text3)' }}>No agents match this filter.</td></tr>}
      </tbody>
    </table></div>
    {!payload && <div style={{ padding: 14, fontSize: TYPE.xs, color: BB.amber }}>RUNTIME STATUS UNVERIFIED · no maturity payload is available.</div>}
    {payload && <MaturityLegend />}
  </div>
}

// Canonical operator-facing truth-labels for the maturity vocabulary. The board
// and legend render these verbatim so meaning is never lost to a generic
// underscore-replace. (These exact strings are the maturity contract's truth
// vocabulary and are asserted by the observability guard test.)
const ELIGIBILITY_LABELS: Record<string, string> = {
  ELIGIBLE_FOR_HUMAN_REVIEW: 'ELIGIBLE FOR HUMAN REVIEW',
  HUMAN_REVIEW_REQUIRED: 'HUMAN REVIEW REQUIRED',
  NOT_ELIGIBLE: 'NOT ELIGIBLE',
  RESTRICTED: 'RESTRICTED',
  UNKNOWN: 'UNKNOWN',
}
const HEALTH_LABELS: Record<string, string> = {
  HEALTHY: 'HEALTHY',
  DEGRADED_FALLBACK: 'DEGRADED — DETERMINISTIC FALLBACK',
  STALE_CACHE: 'STALE CACHED REVIEW',
  NOT_RUN: 'NOT RUN',
  TIMEOUT: 'TIMEOUT',
  INVALID_OUTPUT: 'INVALID OUTPUT',
  MISSING_REVIEWER: 'MISSING REVIEWER',
  INCOMPLETE_CONSENSUS: 'INCOMPLETE CONSENSUS',
  PROVIDER_UNAVAILABLE: 'PROVIDER UNAVAILABLE',
  UNKNOWN: 'UNKNOWN',
}
const GATE_LABELS: Record<string, string> = {
  CAPPED_BY_SAMPLE_SIZE: 'CAPPED BY SAMPLE SIZE',
}

function eligibilityLabel(state: string): string {
  return ELIGIBILITY_LABELS[state] ?? GATE_LABELS[state] ?? state.replace(/_/g, ' ')
}
function healthLabelText(state: string): string {
  return HEALTH_LABELS[state] ?? maturityHealthLabel(state)
}

// Compact legend of the truth vocabulary — advisory only, carries NO authority
// controls (no Promote/Activate/Deploy). Reinforces what each state means.
function MaturityLegend() {
  const groupStyle: CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }
  const cap: CSSProperties = { fontWeight: 750, letterSpacing: '.04em', textTransform: 'uppercase', color: 'var(--text2)' }
  return <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'center', fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.5 }}>
    <span style={cap}>Legend</span>
    <span style={groupStyle}><b style={cap}>Eligibility:</b> {ELIGIBILITY_LABELS.ELIGIBLE_FOR_HUMAN_REVIEW} · {ELIGIBILITY_LABELS.HUMAN_REVIEW_REQUIRED} · {GATE_LABELS.CAPPED_BY_SAMPLE_SIZE}</span>
    <span style={groupStyle}><b style={cap}>Review health:</b> {HEALTH_LABELS.DEGRADED_FALLBACK} · {HEALTH_LABELS.STALE_CACHE} · {HEALTH_LABELS.NOT_RUN}</span>
    <span style={groupStyle}><b style={cap}>Provenance:</b> RUNTIME STATUS UNVERIFIED until measured</span>
    <span style={{ color: BB.amber, fontWeight: 750 }}>NO FINANCIAL AUTHORITY</span>
  </div>
}

function FragmentRow({ row, open, onToggle }: { row: AgentMaturityObservation; open: boolean; onToggle: () => void }) {
  const nextGate = row.next_gate_state === 'PASSED' ? 'gate passed' : (row.next_gate_id ?? row.next_gate_state.replace(/_/g, ' ').toLowerCase())
  return <>
    <tr onClick={onToggle} title={row.next_step_hint ? `Next step: ${row.next_step_hint}` : undefined} style={{ borderBottom: open ? 'none' : '1px solid var(--border-subtle)', cursor: 'pointer', background: open ? 'var(--bg2)' : undefined }}>
      <td style={{ padding: '9px 10px', ...rowRail(maturityRail(row)), paddingLeft: 12 }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 750 }}>{row.display_name}</div>
        <div style={{ ...numStyle, fontSize: TYPE.xs, color: 'var(--text3)' }}>{row.agent_id}</div>
      </td>
      <td style={{ padding: '9px 10px' }}><Chip kind="state" tone={maturityLifecycleTone(row.declared_lifecycle_state)}>{row.declared_lifecycle_state}</Chip></td>
      <td style={{ padding: '9px 10px' }}><SampleBar row={row} /></td>
      <td style={{ padding: '9px 10px' }}>
        <Chip kind="state" tone={maturityHealthTone(row.review_health)}>{healthLabelText(row.review_health)}</Chip>
        <div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text3)' }}>{row.review_provenance.replace(/_/g, ' ')}</div>
      </td>
      <td style={{ padding: '9px 10px', fontSize: TYPE.xs, color: 'var(--text2)', maxWidth: 220 }} title={row.next_step_hint || row.next_gate_description || undefined}>
        <span style={{ color: BB.amber }}>&rarr;</span> {nextGate}
        {row.next_step_hint && <div style={{ marginTop: 2, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.35 }}>{row.next_step_hint}</div>}
      </td>
      <td style={{ padding: '9px 10px' }}><Chip kind="state" tone={eligibilityTone(row.promotion_eligibility)}>{eligibilityLabel(row.promotion_eligibility)}</Chip></td>
      <td style={{ padding: '9px 10px', textAlign: 'center', color: 'var(--text3)', fontSize: TYPE.sm }}>{open ? '\u25be' : '\u25b8'}</td>
    </tr>
    {open && <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}><td colSpan={7} style={{ padding: 0 }}><MaturityDetail row={row} /></td></tr>}
  </>
}

function actionToggleStyle(active: boolean): CSSProperties {
  return {
    fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.04em', textTransform: 'uppercase',
    border: `1px solid ${active ? BB.amber : 'var(--border)'}`,
    background: active ? BB.amberDim : 'transparent',
    color: active ? BB.amber : 'var(--text3)',
    padding: '2px 9px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap',
  }
}

function filterTabStyle(active: boolean): CSSProperties {
  return {
    fontSize: TYPE.xs, fontWeight: 750,
    border: `1px solid ${active ? 'rgba(255,176,0,.34)' : 'var(--border)'}`,
    background: active ? BB.amberDim : 'var(--bg1)',
    color: active ? BB.amber : 'var(--text2)',
    padding: '4px 10px', borderRadius: 7, cursor: 'pointer', whiteSpace: 'nowrap',
  }
}

function RuntimeView() {
  const summary = useMemo(() => summarizeAgentRuntime(), [])
  const [selectedId, setSelectedId] = useState('sentinel')
  // Replace the fixture snapshot only when the read API is available; otherwise keep the explicit
  // fallback state (FIXTURE / NOT CONNECTED / UNAVAILABLE / STALE / SHADOW). Env unset => FIXTURE.
  const [runtimeView, setRuntimeView] = useState<ResolvedRuntimeView>(() => ({
    state: 'FIXTURE', snapshot: AGENT_RUNTIME_SNAPSHOT, detail: 'Resolving read API…', live: false,
  }))
  const [maturityView, setMaturityView] = useState<ResolvedAgentMaturityView>(() => ({
    state: 'UNAVAILABLE', payload: null, detail: 'Resolving maturity read API…',
  }))
  const [detail, setDetail] = useState<AgentDetailView | null>(null)
  useEffect(() => {
    let active = true
    resolveAgentRuntimeView({ baseUrl: readApiBaseFromEnv() })
      .then(view => { if (active) setRuntimeView(view) })
      .catch(() => { if (active) setRuntimeView({ state: 'UNAVAILABLE', snapshot: AGENT_RUNTIME_SNAPSHOT, detail: 'Adapter error', live: false }) })
    resolveAgentMaturityView()
      .then(view => { if (active) setMaturityView(view) })
      .catch(() => { if (active) setMaturityView({ state: 'UNAVAILABLE', payload: null, detail: 'Maturity adapter error' }) })
    return () => { active = false }
  }, [])
  // Per-agent live detail for the desks (Run timeline / Artifact desk / Knowledge),
  // refetched when the selected agent changes. Fail-closed: null => honest empty desks.
  useEffect(() => {
    let active = true
    setDetail(null)
    resolveAgentRuntimeDetail(selectedId, { baseUrl: readApiBaseFromEnv() })
      .then(d => { if (active) setDetail(d) })
      .catch(() => { if (active) setDetail(null) })
    return () => { active = false }
  }, [selectedId])
  const snapshot = runtimeView.snapshot
  const selected = AGENT_RUNTIME_CATALOG.find(agent => agent.agentId === selectedId) || AGENT_RUNTIME_CATALOG[0]
  const acceptance: Array<[string, string, string]> = detail?.live
    ? [
      ['Reviewed Watch artifacts', `${detail.counts.reviewed} / 100`, detail.counts.reviewed >= 100 ? 'MET' : detail.counts.reviewed > 0 ? 'IN PROGRESS' : 'NOT RUN'],
      ['Known-bad fixtures', `${detail.cases.byType['known_bad_fixture'] ?? 0} connected`, (detail.cases.byType['known_bad_fixture'] ?? 0) > 0 ? 'CONNECTED' : 'NOT RUN'],
      ['Darwin scoring coverage', `${detail.counts.scored} scored`, detail.counts.scored > 0 ? 'IN PROGRESS' : 'NOT RUN'],
      ['Produced artifacts', `${detail.counts.produced}`, detail.counts.produced > 0 ? 'IN PROGRESS' : 'NOT RUN'],
      ['Candidate lessons (fleet)', `${detail.lessons.byLifecycle['CANDIDATE'] ?? 0} candidate · ${detail.lessons.total} total`, detail.lessons.total > 0 ? 'CONNECTED' : 'NOT RUN'],
      ['Independent review of own output', detail.counts.produced > 0 ? 'required' : 'n/a (critic role)', 'HUMAN REVIEW REQUIRED'],
    ]
    : [
      ['Reviewed Watch artifacts', '0 / 100', 'NOT RUN'],
      ['Known-bad fixtures', '0 / 20 connected', 'NOT RUN'],
      ['Retrieval coverage', 'Not measured', 'NOT RUN'],
      ['Deterministic failures released', 'Not measured', 'NOT RUN'],
      ['Darwin scoring coverage', 'Not measured', 'NOT RUN'],
      ['Candidate lesson adjudication', 'Not connected', 'NOT RUN'],
    ]

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ ...panel, borderColor: 'rgba(96,165,250,.36)', background: 'rgba(96,165,250,.06)' }}>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center' }}>
        <StatusBadge tone={runtimeView.state === 'SHADOW' ? 'green' : runtimeView.state === 'STALE' ? 'amber' : runtimeView.state === 'UNAVAILABLE' ? 'red' : 'slate'}>{runtimeView.state.replace('_', ' ')}</StatusBadge>
        <StatusBadge tone="green">READ ONLY</StatusBadge>
        <StatusBadge tone="amber">SHADOW ONLY</StatusBadge>
        {runtimeView.live && <StatusBadge tone="green">LIVE</StatusBadge>}
      </div>
      <div style={{ marginTop: 9, fontSize: TYPE.sm, color: 'var(--text1)', lineHeight: 1.5 }}>
        {runtimeView.live
          ? 'This workspace renders live, read-only data from the agent-runtime read API. It never issues writes, provider calls, approvals, or service control.'
          : 'This workspace renders the approved monitoring contract before the authoritative persistence read adapter is integrated. It does not claim live runs, artifacts, reviews, scores, cases, lessons, or operational agents.'}
      </div>
      <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
        {AGENT_RUNTIME_CONTRACT} · source={snapshot.source} · adapter={snapshot.adapterState} · as_of={snapshot.asOf} · state={runtimeView.state}
      </div>
      {summary.catalogIssues.length > 0 && <div style={{ marginTop: 8, color: BB.red, fontSize: TYPE.xs }}>BLOCKED CONTRACT: {summary.catalogIssues.join(' · ')}</div>}
    </div>

    <MaturityScoreboard view={maturityView} />

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
      <MetricCard value={summary.total} title="Canonical agents" detail="Stable IDs in the maturity catalog" />
      <MetricCard value={summary.lifecycle.SHADOW} title="Shadow agents" detail="Enabled only inside LAB/SHADOW authority" tone="blue" />
      <MetricCard value={summary.lifecycle.DESIGNED} title="Designed agents" detail="Not enabled; prerequisites remain visible" />
      <MetricCard value={summary.lifecycle.OPERATIONAL} title="Operational agents" detail="Cannot be claimed before acceptance evidence" tone="green" />
      <MetricCard value={summary.retrievalRequired} title="Retrieval required" detail="Definitions requiring memory before reasoning" />
      <MetricCard value={DENIED_AUTHORITIES.length} title="Denied authority classes" detail="Financial and production authority remains absent" tone="amber" />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(280px,1fr)', gap: 12, alignItems: 'start' }}>
      <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
          <div><div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Agent catalog</div><div style={{ marginTop: 2, fontSize: TYPE.xs, color: 'var(--text3)' }}>Click an agent to inspect its bounded contract.</div></div>
          <StatusBadge tone="slate">{summary.total} DEFINITIONS</StatusBadge>
        </div>
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
          <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>{['Agent', 'Role', 'Lifecycle', 'Enabled', 'Retrieval', 'Deadline'].map(header => <th key={header} style={{ ...label, textAlign: header === 'Agent' || header === 'Role' ? 'left' : 'right', padding: '8px 10px' }}>{header}</th>)}</tr></thead>
          <tbody>{AGENT_RUNTIME_CATALOG.map(agent => <tr key={agent.agentId} onClick={() => setSelectedId(agent.agentId)} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', background: selectedId === agent.agentId ? 'rgba(96,165,250,.07)' : undefined }}>
            <td style={{ padding: '9px 10px' }}><div style={{ fontSize: TYPE.sm, fontWeight: 750 }}>{agent.displayName}</div><div style={{ fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{agent.agentId}</div></td>
            <td style={{ padding: '9px 10px', fontSize: TYPE.xs, color: 'var(--text2)' }}>{agent.role}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right' }}><StatusBadge tone={lifecycleTone[agent.lifecycle]}>{agent.lifecycle}</StatusBadge></td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: TYPE.xs, color: agent.enabled ? T.link : 'var(--text3)' }}>{agent.enabled ? 'SHADOW' : 'NO'}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: TYPE.xs }}>{agent.retrievalRequired ? 'REQUIRED' : 'N/A'}</td>
            <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: TYPE.xs, fontFamily: 'var(--mono)' }}>{agent.budget.deadlineSeconds}s</td>
          </tr>)}</tbody>
        </table></div>
      </div>
      <AgentDetail agent={selected} />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
      {detail?.live
        ? <><RunTimelineDesk d={detail} /><ArtifactReviewDesk d={detail} /><KnowledgeDesk d={detail} /></>
        : <>
          <EmptyEvidence title="Run queue and timeline" description="No persisted run timeline is connected. Running, blocked, failed, stale, cancelled, deadline-exceeded, checkpoint, budget, tool-call, and stop-reason states will come from the approved read adapter." />
          <EmptyEvidence title="Artifact review desk" description="No authoritative artifacts are loaded. Immutable hash, producer, independent reviewer, scorer, deterministic gate, contradictions, operator disposition, outcome, and Darwin score remain zero rather than inferred." />
          <EmptyEvidence title="Knowledge and learning" description="Cases, candidate lessons, ratified lessons, contradictions, Nightly Reflection outputs, and Iris/operator dispositions are not connected. Automatic production promotion remains impossible." />
        </>}
    </div>

    <div style={{ ...panel }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
        <div><div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Authority and safety</div><div style={{ marginTop: 2, fontSize: TYPE.xs, color: 'var(--text3)' }}>Deterministic financial authority remains outside the reflective runtime.</div></div>
        <StatusBadge tone="green">ZERO FINANCIAL AUTHORITY</StatusBadge>
      </div>
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 12 }}>{DENIED_AUTHORITIES.map(item => <StatusBadge key={item} tone="amber">DENIED · {item}</StatusBadge>)}</div>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.25fr) minmax(280px,.75fr)', gap: 12 }}>
      <div style={{ ...panel }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Minimum Viable Loop acceptance</div>
        <div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text3)' }}>Badges remain NOT RUN until evidence is connected and reviewed.</div>
        <div style={{ marginTop: 10 }}>{acceptance.map(([name, value, state]) => <div key={name} style={{ display: 'grid', gridTemplateColumns: '1fr 150px 80px', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', alignItems: 'center' }}>
          <div style={{ fontSize: TYPE.xs }}>{name}</div><div style={{ fontSize: TYPE.xs, color: 'var(--text2)', textAlign: 'right' }}>{value}</div><div style={{ textAlign: 'right' }}><StatusBadge tone="slate">{state}</StatusBadge></div>
        </div>)}</div>
      </div>
      <div style={{ ...panel }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Watch context contract</div>
        <div style={{ marginTop: 8, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.55 }}>The first contextual panel will expose Sentinel integrity, reflective review state, Argus population findings, Darwin score, and related cases/lessons. It is read-only and cannot change the sovereign Watch decision or authorize an action.</div>
        <div style={{ marginTop: 12, display: 'grid', gap: 7 }}>{['Sentinel integrity · NOT CONNECTED', 'Argus findings · NOT RUN', 'Darwin score · NOT RUN', 'Case and lesson links · NOT CONNECTED', 'Action authority · NONE'].map(item => <div key={item} style={{ padding: 8, borderRadius: 7, background: 'var(--bg2)', fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{item}</div>)}</div>
      </div>
    </div>
  </div>
}

export default function AgentRuntimeHub({ onDrill }: Props) {
  const [view, setView] = useState<View>('Runtime')
  return <div>
    <div className="hub-title-row" style={{ marginBottom: 14 }}>
      <div><div style={{ fontSize: 22, fontWeight: 800 }}>Agents</div><div style={{ marginTop: 3, fontSize: TYPE.xs, color: 'var(--text3)' }}>Governed runtime maturity, evidence, monitoring, and existing agent analytics.</div></div>
      <div className="hub-tabs" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{(['Runtime', 'Legacy analytics'] as View[]).map(item => <button key={item} type="button" onClick={() => setView(item)} style={{ border: '1px solid var(--border)', borderRadius: 7, background: view === item ? 'rgba(96,165,250,.14)' : 'var(--bg1)', color: view === item ? T.link : 'var(--text2)', padding: '6px 10px', fontSize: TYPE.xs, fontWeight: 750, cursor: 'pointer' }}>{item}</button>)}</div>
    </div>
    {view === 'Runtime' ? <RuntimeView /> : <AgentsHub onDrill={onDrill} />}
  </div>
}
