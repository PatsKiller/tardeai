import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

type Envelope = {
  source_as_of?: string | null
  composition_as_of?: string | null
  producer?: string
  authority?: string
}

type ResearchArtifact = {
  artifact_id?: string
  status?: string
  source?: string
  source_url?: string | null
  publication_date?: string | null
  retrieved_at?: string | null
  affected_entities?: string[]
  relevance?: string | number | null
  support_or_challenge?: string | null
  reason_used_or_rejected?: string | null
  agent_model?: string | null
  decision_id?: string | null
  trace_id?: string | null
}

type ResearchBlock = Envelope & { artifacts?: ResearchArtifact[]; counts?: Record<string, number> }
type CognitionBlock = Envelope & { items?: Array<Record<string, any>>; office_truth_boundary?: string[] }
type LearningBlock = Envelope & { settled_outcomes?: any[]; pending_outcomes?: any[]; beliefs?: any[]; lessons?: any[]; hypotheses?: any[]; experiments?: any[]; review_ready?: any[]; sample_size?: number }
type CoverageBlock = Envelope & { rows?: CoverageRow[]; counts?: Record<string, number> }
type Blocks = { research?: ResearchBlock; institutional_cognition?: CognitionBlock; learning?: LearningBlock; capability_coverage?: CoverageBlock }

type CoverageRow = {
  capability: string
  contract?: string
  producer?: string
  consumer?: string
  current_status?: string
  durable_artifact?: string
  last_producer_event?: string | null
  reason?: string
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
    <span>source_as_of {stamp(block?.source_as_of)}</span><span>composition_as_of {stamp(block?.composition_as_of)}</span><span>producer {block?.producer || 'UNKNOWN'}</span>
  </div>
}

function ResearchPanel({ block }: { block?: ResearchBlock }) {
  const artifacts = block?.artifacts || []
  const counts = block?.counts || {}
  return <Card title="Research provenance — found is not relied upon" testId="cio-research-provenance">
    <Provenance block={block} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8, margin: '10px 0' }}>
      {(['retrieved', 'used_in_judgment', 'rejected', 'unknown'] as const).map(k => <div key={k} style={{ border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 8 }}><div style={{ color: 'var(--text3)', fontSize: 10 }}>{k.replace('_', ' ').toUpperCase()}</div><div style={{ color: tone(k === 'used_in_judgment' ? 'USED_IN_JUDGMENT' : k === 'rejected' ? 'REJECTED' : k.toUpperCase()), fontSize: 18, fontWeight: 800 }}>{counts[k] ?? 0}</div></div>)}
    </div>
    {!artifacts.length && <Empty text="No research artifacts are recorded in the canonical result stores; requests alone are not evidence." />}
    {artifacts.length > 0 && <div style={{ display: 'grid', gap: 6 }}>{artifacts.slice(0, 12).map((a: ResearchArtifact, i: number) => <details key={`${a.artifact_id}-${i}`} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
      <summary style={{ cursor: 'pointer', fontSize: 11 }}><span style={{ color: tone(a.status), fontWeight: 800 }}>{a.status || 'UNKNOWN'}</span> · {a.artifact_id || 'UNKNOWN'} · {a.source || 'source unavailable'}</summary>
      <div style={{ color: 'var(--text3)', fontSize: 10, lineHeight: 1.5, padding: '6px 0 2px 14px' }}>
        <div>published {stamp(a.publication_date)} · retrieved {stamp(a.retrieved_at)} · entities {(a.affected_entities || []).join(', ') || 'UNKNOWN'}</div>
        <div>relevance {a.relevance ?? 'UNKNOWN'} · {a.support_or_challenge || 'classification UNKNOWN'} · reason {a.reason_used_or_rejected || 'not recorded'}</div>
        <div>consumer {a.agent_model || 'UNKNOWN'} · trace {a.trace_id || 'UNKNOWN'} {a.source_url ? <>· <a href={a.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>source</a></> : null}</div>
        {a.decision_id && <Link to={`/cio?tab=decisions&decision=${encodeURIComponent(a.decision_id)}`} style={{ color: 'var(--accent)' }}>Open CIO decision {a.decision_id}</Link>}
      </div>
    </details>)}</div>}
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
  return <Card title="Learning / belief cockpit — no self-promotion" testId="cio-learning-cockpit">
    <Provenance block={block} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8, margin: '10px 0' }}>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SETTLED</span><strong style={{ display: 'block', fontSize: 16 }}>{block?.settled_outcomes?.length ?? 0}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>PENDING</span><strong style={{ display: 'block', fontSize: 16 }}>{block?.pending_outcomes?.length ?? 0}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>SAMPLE SIZE</span><strong style={{ display: 'block', fontSize: 16 }}>{block?.sample_size ?? 0}</strong></div>
      <div><span style={{ color: 'var(--text3)', fontSize: 10 }}>REVIEW_READY</span><strong style={{ display: 'block', fontSize: 16 }}>{block?.review_ready?.length ?? 0}</strong></div>
    </div>
    <details><summary style={{ cursor: 'pointer', fontSize: 11 }}>Beliefs, lessons, hypotheses, experiments</summary><div style={{ color: 'var(--text3)', fontSize: 10, lineHeight: 1.5, padding: 8 }}>Beliefs {block?.beliefs?.length ?? 0} · lessons {block?.lessons?.length ?? 0} · hypotheses {block?.hypotheses?.length ?? 0} · experiments {block?.experiments?.length ?? 0}. Source outcome links are required; insufficient samples remain INSUFFICIENT_EVIDENCE. Promotion: NOT_PERFORMED.</div></details>
  </Card>
}

function CoveragePanel({ block }: { block?: CoverageBlock }) {
  const rows = block?.rows || []
  return <Card title="Capability coverage — runtime artifact census" testId="cio-capability-coverage">
    <Provenance block={block} />
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '8px 0', fontSize: 10 }}>{Object.entries(block?.counts || {}).map(([key, value]) => <span key={key} style={{ color: tone(key), fontWeight: 800 }}>{key} {String(value)}</span>)}</div>
    {!rows.length && <Empty text="Capability producer evidence unavailable; this is not a clean zero." />}
    <div style={{ display: 'grid', gap: 5 }}>{rows.map((row: CoverageRow) => <details key={row.capability} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}><summary style={{ cursor: 'pointer', fontSize: 11 }}><span style={{ color: tone(row.current_status), fontWeight: 800 }}>{row.current_status || 'UNKNOWN'}</span> · {row.capability}</summary><div style={{ color: 'var(--text3)', fontSize: 10, padding: '5px 0 2px 14px', lineHeight: 1.45 }}>producer {row.producer || 'UNKNOWN'} · consumer {row.consumer || 'UNKNOWN'}<br />artifact {row.durable_artifact || 'UNKNOWN'} · last producer {stamp(row.last_producer_event)}<br />{row.reason || 'No reason recorded.'}</div></details>)}</div>
  </Card>
}

export default function CioOperatorEvidencePanel({ section = 'all' }: { section?: 'all' | 'research' }) {
  const { data, loading, error } = useApi<Payload>('/api/v3/cio/operator-evidence', 60_000)
  if (loading && !data) return <div style={{ color: 'var(--text2)' }} data-testid="cio-operator-evidence-loading">Loading operator evidence…</div>
  if (error && !data) return <div style={{ color: 'var(--amber)' }} data-testid="cio-operator-evidence-error">Operator evidence unavailable: {String(error)}</div>
  const blocks = data?.blocks || {}
  return <section data-testid="cio-operator-evidence" style={{ display: 'grid', gap: 12 }}>
    <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.55px' }}>CIO OPERATOR EVIDENCE</div><div style={{ marginTop: 5, fontSize: 12, color: 'var(--text1)' }}>Research, cognition, learning, and runtime coverage joined for the investment-office operator. Control Plane remains diagnostic/engineering only.</div><Provenance block={data || undefined} /></div>
    {(section === 'all' || section === 'research') && <ResearchPanel block={blocks.research} />}
    {section === 'all' && <><CognitionPanel block={blocks.institutional_cognition} /><LearningPanel block={blocks.learning} /><CoveragePanel block={blocks.capability_coverage} /></>}
  </section>
}
