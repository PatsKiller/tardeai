import { Link, useSearchParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

type Envelope = {
  source_as_of?: string | null
  composition_as_of?: string | null
  producer?: string
  authority?: string
  freshness?: string | null
}

type ResearchArtifact = {
  artifact_id?: string
  research_id?: string | null
  status?: string
  source_type?: string | null
  source?: string
  publisher?: string | null
  source_url?: string | null
  source_ref?: string | null
  publication_date?: string | null
  retrieved_at?: string | null
  source_as_of?: string | null
  affected_entities?: string[]
  subject_guid?: string | null
  research_run_id?: string | null
  relevance?: string | number | null
  support_or_challenge?: string | null
  reason_used_or_rejected?: string | null
  agent_model?: string | null
  decision_id?: string | null
  decision_ids?: string[]
  related_decisions?: string[]
  related_securities?: string[]
  thesis_refs?: string[]
  trace_id?: string | null
  evidence_class?: string | null
}

type ResearchBlock = Envelope & { schema?: string; artifacts?: ResearchArtifact[]; retrieved?: ResearchArtifact[]; used_in_judgment?: ResearchArtifact[]; rejected?: ResearchArtifact[]; unknown?: ResearchArtifact[]; counts?: Record<string, number> }
type CognitionBlock = Envelope & { items?: Array<Record<string, any>>; office_truth_boundary?: string[] }
type LearningBlock = Envelope & {
  settled_outcomes?: any[]
  pending_outcomes?: any[]
  beliefs?: any[]
  lessons?: any[]
  research_derived_lessons?: any[]
  outcome_derived_lessons?: any[]
  hypotheses?: any[]
  experiments?: any[]
  review_ready?: any[]
  sample_size?: number | null
  successful_count?: number | null
  success_rate?: number | null
  horizon?: string | null
  calibration?: unknown
  maturity_state?: string | null
}
type CoverageBlock = Envelope & { rows?: CoverageRow[]; counts?: Record<string, number> }
type Blocks = { research?: ResearchBlock; institutional_cognition?: CognitionBlock; learning?: LearningBlock; capability_coverage?: CoverageBlock }

type CoverageRow = {
  capability: string
  contract?: string
  producer?: string
  consumer?: string
  current_status?: string
  state?: string
  durable_artifact?: string
  last_producer_event?: string | null
  reason?: string
  last_produced_at?: string | null
  last_consumed_at?: string | null
  artifact_age?: number | null
}

type Payload = {
  ok?: boolean
  source_as_of?: string | null
  composition_as_of?: string | null
  authority?: string
  blocks?: Blocks
}

function stamp(value?: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 19) : 'UNKNOWN'
}

function tone(state?: string): string {
  const s = String(state || '').toUpperCase()
  if (s === 'LIVE' || s === 'USED_IN_JUDGMENT' || s === 'PROVEN') return 'var(--green)'
  if (s === 'PARTIAL' || s === 'PENDING' || s === 'RETRIEVED' || s === 'UNKNOWN') return 'var(--amber)'
  if (s === 'DARK' || s === 'UNWIRED' || s === 'REJECTED') return 'var(--red)'
  return 'var(--text3)'
}

function Card({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
  return <section data-testid={testId} style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }}><div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text1)', letterSpacing: '.35px', marginBottom: 8 }}>{title}</div>{children}</section>
}

function Empty({ text }: { text: string }) {
  return <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }}>{text}</div>
}

function Provenance({ block }: { block?: Envelope }) {
  return <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', color: 'var(--text3)', fontSize: 10 }}>
    <span>source_as_of {stamp(block?.source_as_of)}</span><span>composition_as_of {stamp(block?.composition_as_of)}</span><span>freshness {block?.freshness || 'UNKNOWN'}</span><span>producer {block?.producer || 'UNKNOWN'}</span>
  </div>
}

function ResearchPanel({ block }: { block?: ResearchBlock }) {
  const artifacts = block?.artifacts || []
  const counts = block?.counts || {}
  // Group membership is assigned by the backend receipt projection.  The
  // frontend only renders those explicit groups and never upgrades a status
  // by inspecting neighboring artifact fields.
  const used = block?.used_in_judgment || []
  const rejected = block?.rejected || []
  const retrieved = block?.retrieved || []
  const unknown = block?.unknown || []

  function ArtifactList({ rows, emptyText }: { rows: ResearchArtifact[]; emptyText: string }) {
    if (!rows.length) return <Empty text={emptyText} />
    return <div style={{ display: 'grid', gap: 6 }}>{rows.slice(0, 50).map((a, i) => {
      const symbols = a.related_securities?.length ? a.related_securities : (a.affected_entities || [])
      const decisions = a.related_decisions?.length ? a.related_decisions : (a.decision_ids || (a.decision_id ? [a.decision_id] : []))
      const thesisRefs = a.thesis_refs || []
      const decisionId = decisions[0]
      const researchHref = `/cio?tab=research${decisionId ? `&decision=${encodeURIComponent(decisionId)}` : ''}${a.artifact_id ? `&artifact=${encodeURIComponent(a.artifact_id)}` : ''}`
      return <details key={`${a.artifact_id}-${i}`} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
        <summary style={{ cursor: 'pointer', fontSize: 11 }}><span style={{ color: tone(a.status), fontWeight: 800 }}>{a.status || 'UNKNOWN'}</span> · {a.artifact_id || 'UNKNOWN'} · {a.publisher || a.source || 'source unavailable'}</summary>
        <div style={{ color: 'var(--text3)', fontSize: 10, lineHeight: 1.5, padding: '6px 0 2px 14px' }}>
          <div>type {a.source_type || 'UNKNOWN'} · publisher {a.publisher || a.source || 'UNKNOWN'} · class {a.evidence_class || 'UNKNOWN'}</div>
          <div>published {stamp(a.publication_date)} · retrieved {stamp(a.retrieved_at)} · source_as_of {stamp(a.source_as_of)}</div>
          <div>entities {symbols.join(', ') || 'UNKNOWN'} · relevance {a.relevance ?? 'UNKNOWN'} · {a.support_or_challenge || 'classification UNKNOWN'}</div>
          <div>run {a.research_run_id || 'UNKNOWN'} · model {a.agent_model || 'UNKNOWN'} · trace {a.trace_id || 'UNKNOWN'} · ref {a.source_ref || 'UNKNOWN'}</div>
          {a.status === 'REJECTED' && <div style={{ color: 'var(--red)' }}>rejected because {a.reason_used_or_rejected || 'reason unavailable'}</div>}
          {a.status === 'RETRIEVED' && <div>use receipt {a.reason_used_or_rejected || 'not recorded'} · retrieval alone does not prove judgment use</div>}
          {a.status === 'UNKNOWN' && <div>use/rejection state UNKNOWN · no canonical receipt was found</div>}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 3 }}>
            <Link to={researchHref} style={{ color: 'var(--accent)' }}>Open research artifact</Link>
            {decisions.map((id) => <Link key={id} to={`/cio?tab=decisions&decision=${encodeURIComponent(id)}`} style={{ color: 'var(--accent)' }}>Open CIO decision {id}</Link>)}
            {symbols.map((symbol) => <Link key={symbol} to={`/research-intelligence?symbol=${encodeURIComponent(symbol)}`} style={{ color: 'var(--accent)' }}>Open security/thesis {symbol}</Link>)}
            {thesisRefs.map((ref) => <Link key={ref} to={`/research-intelligence?q=${encodeURIComponent(ref)}`} style={{ color: 'var(--accent)' }}>Open thesis {ref}</Link>)}
            {a.source_url ? <a href={a.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>Source</a> : null}
          </div>
        </div>
      </details>
    })}</div>
  }

  return <Card title="Research provenance — found is not relied upon" testId="cio-research-provenance">
    <Provenance block={block} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8, margin: '10px 0' }}>
      {(['retrieved', 'used_in_judgment', 'rejected', 'unknown'] as const).map(k => <div key={k} style={{ border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 8 }}><div style={{ color: 'var(--text3)', fontSize: 10 }}>{k.replace('_', ' ').toUpperCase()}</div><div style={{ color: tone(k === 'used_in_judgment' ? 'USED_IN_JUDGMENT' : k === 'rejected' ? 'REJECTED' : k.toUpperCase()), fontSize: 18, fontWeight: 800 }}>{counts[k] == null ? 'UNKNOWN' : counts[k]}</div></div>)}
    </div>
    {!artifacts.length && <Empty text="No research artifacts are recorded in the canonical result stores; requests alone are not evidence." />}
    <div style={{ display: 'grid', gap: 8 }}>
      <details open data-testid="research-used-group"><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>Evidence actually used · {used.length}</summary><ArtifactList rows={used} emptyText="No artifact has a canonical receipt proving it was used in judgment." /></details>
      <details data-testid="research-retrieved-group"><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>Retrieved but not proven used · {retrieved.length}</summary><ArtifactList rows={retrieved} emptyText="No retrieved-only research artifacts." /></details>
      <details data-testid="research-rejected-group"><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>Rejected with reason · {rejected.length}</summary><ArtifactList rows={rejected} emptyText="No artifact has an explicit rejection receipt and reason." /></details>
      <details data-testid="research-unknown-group"><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>Provenance unknown · {unknown.length}</summary><ArtifactList rows={unknown} emptyText="No artifacts have an unknown provenance state." /></details>
    </div>
  </Card>
}

function CognitionPanel({ block }: { block?: CognitionBlock }) {
  const items = block?.items || []
  return <Card title="Institutional cognition — advisory context, not office truth" testId="cio-institutional-cognition">
    <Provenance block={block} />
    <div style={{ margin: '8px 0', fontSize: 10, color: 'var(--amber)' }}>OFFICE_TRUTH remains canonical: {(block?.office_truth_boundary || []).join(' · ') || 'UNAVAILABLE'}. Cognition cannot overwrite it.</div>
    {!items.length && <Empty text="No cognition receipts recorded; absence is not proof that no memory exists." />}
    {items.length > 0 && <div style={{ display: 'grid', gap: 5 }}>{items.slice(0, 12).map((item: Record<string, any>, i: number) => <div key={`${item.id || item.kind}-${i}`} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6, fontSize: 11 }}><span style={{ color: tone(item.influence === 'PROVEN' ? 'PROVEN' : item.state), fontWeight: 800 }}>{item.influence === 'PROVEN' ? 'USED' : item.state || 'UNKNOWN'}</span> · {item.kind || 'cognition'} · {item.summary || 'no summary'} {item.contradictory ? <span style={{ color: 'var(--red)' }}>· CONTRADICTORY</span> : null}<div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 2 }}>source {item.source_ref || 'UNKNOWN'} · as_of {stamp(item.source_as_of)} · influence {item.influence || 'NOT_PROVEN'}</div></div>)}</div>}
  </Card>
}

function LearningPanel({ block }: { block?: LearningBlock }) {
  const count = (value: unknown) => typeof value === 'number' ? String(value) : 'UNKNOWN'
  return <Card title="Learning / belief cockpit — no self-promotion" testId="cio-learning-cockpit">
    <Provenance block={block} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8, margin: '10px 0' }}>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SETTLED</span><strong style={{ display: 'block', fontSize: 16 }}>{count(block?.settled_outcomes?.length)}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>PENDING</span><strong style={{ display: 'block', fontSize: 16 }}>{count(block?.pending_outcomes?.length)}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SAMPLE SIZE</span><strong style={{ display: 'block', fontSize: 16 }}>{count(block?.sample_size)}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>REVIEW_READY</span><strong style={{ display: 'block', fontSize: 16 }}>{count(block?.review_ready?.length)}</strong></div>
    </div>
    <div style={{ color: 'var(--text2)', fontSize: 11 }}>state {block?.maturity_state || 'UNKNOWN'} · successful {count(block?.successful_count)} · success rate {block?.success_rate == null ? 'UNKNOWN' : `${(block.success_rate * 100).toFixed(1)}%`} · horizon {block?.horizon || 'UNKNOWN'} · calibration {block?.calibration == null ? 'UNKNOWN' : 'RECORDED'}</div>
    <details><summary style={{ cursor: 'pointer', fontSize: 11 }}>Beliefs, lessons, hypotheses, experiments</summary><div style={{ color: 'var(--text3)', fontSize: 10, lineHeight: 1.5, padding: 8 }}>Beliefs {count(block?.beliefs?.length)} · lessons {count(block?.lessons?.length)} · outcome-derived lessons {count(block?.outcome_derived_lessons?.length)} · research-derived lessons {count(block?.research_derived_lessons?.length)} · hypotheses {count(block?.hypotheses?.length)} · experiments {count(block?.experiments?.length)}. Backend evidence links determine maturity; insufficient samples remain INSUFFICIENT_EVIDENCE.</div></details>
  </Card>
}

function CoveragePanel({ block }: { block?: CoverageBlock }) {
  const rows = block?.rows || []
  return <Card title="Capability coverage — runtime artifact census" testId="cio-capability-coverage">
    <Provenance block={block} />
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '8px 0', fontSize: 10 }}>{Object.entries(block?.counts || {}).map(([key, value]) => <span key={key} style={{ color: tone(key), fontWeight: 800 }}>{key} {String(value)}</span>)}</div>
    {!rows.length && <Empty text="Capability producer evidence unavailable; this is not a clean zero." />}
    <div style={{ display: 'grid', gap: 5 }}>{rows.map((row: CoverageRow) => { const state = row.state || row.current_status || 'UNKNOWN'; return <details key={row.capability} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}><summary style={{ cursor: 'pointer', fontSize: 11 }}><span style={{ color: tone(state), fontWeight: 800 }}>{state}</span> · {row.capability}</summary><div style={{ color: 'var(--text3)', fontSize: 10, padding: '5px 0 2px 14px', lineHeight: 1.45 }}>contract {row.contract || 'UNKNOWN'} · producer {row.producer || 'UNKNOWN'} · consumer {row.consumer || 'UNKNOWN'}<br />artifact {row.durable_artifact || 'UNKNOWN'} · last produced {stamp(row.last_produced_at || row.last_producer_event)} · last consumed {stamp(row.last_consumed_at)} · age {row.artifact_age == null ? 'UNKNOWN' : `${row.artifact_age}s`}<br />{row.reason || 'No reason recorded.'}</div></details> })}</div>
  </Card>
}

export default function CioOperatorEvidencePanel({ section = 'all' }: { section?: 'all' | 'research' | 'cognition' | 'learning' | 'coverage' }) {
  const [searchParams] = useSearchParams()
  const decisionId = section === 'research' ? (searchParams.get('decision') || '').trim() : ''
  const endpoint = section === 'research'
    ? `/api/v3/cio/research-provenance${decisionId ? `?decision_id=${encodeURIComponent(decisionId)}` : ''}`
    : '/api/v3/cio/operator-evidence'
  const { data, loading, error } = useApi<Payload & ResearchBlock>(endpoint, 60_000)
  if (loading && !data) return <div style={{ color: 'var(--text2)' }} data-testid="cio-operator-evidence-loading">Loading operator evidence…</div>
  if (error && !data) return <div style={{ color: 'var(--amber)' }} data-testid="cio-operator-evidence-error">Operator evidence unavailable: {String(error)}</div>
  const blocks = data?.blocks || {}
  const research = section === 'research' ? (data || undefined) : blocks.research
  return <section data-testid="cio-operator-evidence" style={{ display: 'grid', gap: 12 }}>
    <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.55px' }}>CIO OPERATOR EVIDENCE</div><div style={{ marginTop: 5, fontSize: 12, color: 'var(--text1)' }}>Research, cognition, learning, and runtime coverage joined for the investment-office operator. Control Plane remains diagnostic/engineering only.</div><Provenance block={data || undefined} /></div>
    {(section === 'all' || section === 'research') && <ResearchPanel block={research} />}
    {(section === 'all' || section === 'cognition') && <CognitionPanel block={blocks.institutional_cognition} />}
    {(section === 'all' || section === 'learning') && <LearningPanel block={blocks.learning} />}
    {(section === 'all' || section === 'coverage') && <CoveragePanel block={blocks.capability_coverage} />}
  </section>
}
