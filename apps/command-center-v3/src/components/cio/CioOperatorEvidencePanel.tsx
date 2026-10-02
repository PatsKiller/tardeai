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
  result_id?: string | null
  status?: string
  status_basis?: string | null
  source_store?: string | null
  provider?: string | null
  symbol?: string | null
  use_receipt_ref?: { lineage_id?: string | null; decision_id?: string | null; at?: string | null; source_ref?: string | null } | null
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
type CognitionItem = Record<string, any>
type CognitionBlock = Envelope & {
  items?: CognitionItem[]
  office_truth_boundary?: string[]
  office_truth?: { authority?: string; categories?: string[]; sourced_from_memory?: boolean; replaceable_by_cognition?: boolean; reason?: string }
  institutional_cognition?: { authority?: string; kinds?: string[]; item_count?: number; may_inform?: string }
  contradictory_items?: CognitionItem[]
  prior_operator_decisions?: CognitionItem[]
  counts?: Record<string, number>
}
type LinkEdge = { from_type?: string; from_id?: string; relation?: string; to_type?: string; to_id?: string; resolved?: boolean; via?: string }
type LinkGraph = {
  decision_to_outcomes?: Record<string, string[]>
  outcome_to_beliefs?: Record<string, string[]>
  belief_to_lessons_hypotheses?: Record<string, { lesson_ids?: string[]; hypothesis_ids?: string[] }>
  lesson_to_sources?: Record<string, { outcome_ids?: string[]; decision_ids?: string[] }>
  edges?: LinkEdge[]
  edge_count?: number
  relation_counts?: Record<string, number>
  unresolved_edge_count?: number
  rule?: string
}
type Calibration = { method?: string; groups?: Array<{ population?: string; horizon?: string; sample_size?: number; successful?: number; success_rate?: number }> }
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
  horizons?: string[]
  calibration?: Calibration | null
  calibration_reason?: string | null
  maturity_state?: string | null
  settled_count?: number | null
  settled_without_verdict_count?: number | null
  sample_rule?: string
  producer_review_ready_unproven?: number
  evidence_state_counts?: Record<string, number>
  link_graph?: LinkGraph
}
type KnownDarkItem = { module: string; cio_relevant?: boolean; census_state?: string; classification?: string; reason?: string; consumer_or_successor?: string; action_status?: string }
type KnownDarkBlock = { status?: string; source_ref?: string; doc_ref?: string; items?: KnownDarkItem[]; counts?: Record<string, number>; baseline_check?: string; unclassified_baseline_modules?: string[] | null; reason?: string }
type CoverageBlock = Envelope & { rows?: CoverageRow[]; counts?: Record<string, number>; freshness_counts?: Record<string, number>; known_dark_classification?: KnownDarkBlock }
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
  freshness?: string
  stale_after_seconds?: number
  producer_predicate?: string
  discriminated?: boolean
  producer_module_declared?: boolean
  producer_row_count?: number
  consumer_reference_count?: number
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
  if (s === 'LIVE' || s === 'USED_IN_JUDGMENT' || s === 'USED' || s === 'PROVEN' || s === 'FRESH' || s === 'WIRE') return 'var(--green)'
  if (s === 'PARTIAL' || s === 'PENDING' || s === 'PENDING_OUTCOME' || s === 'RETRIEVED' || s === 'UNKNOWN' || s === 'STALE' || s === 'INSUFFICIENT_EVIDENCE' || s === 'RETAIN_WITH_REASON') return 'var(--amber)'
  if (s === 'DARK' || s === 'UNWIRED' || s === 'REJECTED' || s === 'CONTRADICTORY' || s === 'RETIRE') return 'var(--red)'
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
          <div>type {a.source_type || 'UNKNOWN'} · publisher {a.publisher || 'UNKNOWN'} · provider {a.provider || 'UNKNOWN'} · class {a.evidence_class || 'UNKNOWN'}</div>
          <div>published {stamp(a.publication_date)} · retrieved {stamp(a.retrieved_at)} · source_as_of {stamp(a.source_as_of)}</div>
          <div>symbol {a.symbol || 'UNKNOWN'} · entities {symbols.join(', ') || 'UNKNOWN'} · subject {a.subject_guid || 'UNKNOWN'} · relevance {a.relevance ?? 'UNKNOWN'} · {a.support_or_challenge || 'support/challenge UNKNOWN'}</div>
          <div>run {a.research_run_id || 'UNKNOWN'} · agent/model {a.agent_model || 'UNKNOWN'} · trace {a.trace_id || 'UNKNOWN'} · ref {a.source_ref || 'UNKNOWN'} · store {a.source_store || 'UNKNOWN'} · url {a.source_url || 'UNKNOWN'}</div>
          <div>status basis {a.status_basis || 'no receipt'} · decisions {decisions.join(', ') || 'none recorded'}{a.use_receipt_ref ? ` · use receipt ${a.use_receipt_ref.source_ref || ''} ${a.use_receipt_ref.lineage_id || ''} at ${stamp(a.use_receipt_ref.at)}` : ''}</div>
          {a.status === 'USED_IN_JUDGMENT' && <div>use reason {a.reason_used_or_rejected || 'not recorded by producer'}</div>}
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

function Tile({ label, value, state }: { label: string; value: unknown; state?: string }) {
  return <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 8 }}><div style={{ color: 'var(--text3)', fontSize: 10 }}>{label}</div><div style={{ color: tone(state || label), fontSize: 16, fontWeight: 800 }}>{typeof value === 'number' ? String(value) : 'UNKNOWN'}</div></div>
}

function Group({ title, testId, children, open = false }: { title: string; testId?: string; children: ReactNode; open?: boolean }) {
  return <details open={open} data-testid={testId}><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>{title}</summary><div style={{ padding: '6px 0 2px 14px' }}>{children}</div></details>
}

function CognitionRow({ item }: { item: CognitionItem }) {
  const state = item.state || 'UNKNOWN'
  return <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6, fontSize: 11 }}>
    <span style={{ color: tone(state), fontWeight: 800 }}>{state}</span> · {item.kind || 'cognition'} · {item.summary || 'no summary'}
    {item.changed_question_or_view ? <span style={{ color: 'var(--accent)' }}> · CHANGED</span> : null}
    {item.contradictory ? <span style={{ color: 'var(--red)' }}> · CONTRADICTORY</span> : null}
    {item.operator_decision ? <span style={{ color: 'var(--amber)' }}> · operator {item.operator_decision}</span> : null}
    <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 2 }}>
      availability {item.availability || 'UNKNOWN'} ({item.availability_reason || 'no reason'}) · retrieval {item.retrieval_basis || 'none'} · use {item.used_basis || 'none'} · influence {item.influence || 'NOT_PROVEN'}{item.influence_basis ? ` (${item.influence_basis})` : ''}
      <br />symbol {item.symbol || 'UNKNOWN'} · decision {item.decision_id || 'none'} · source {item.source_ref || 'UNKNOWN'} · as_of {stamp(item.source_as_of)}
      {item.advice ? <><br />advice {String(item.advice)}</> : null}
      {(item.office_truth_fields_withheld || []).length ? <><br /><span style={{ color: 'var(--amber)' }}>office-truth fields withheld: {(item.office_truth_fields_withheld || []).join(', ')}</span></> : null}
    </div>
  </div>
}

function CognitionPanel({ block }: { block?: CognitionBlock }) {
  const items = block?.items || []
  const counts = block?.counts || {}
  const office = block?.office_truth
  const cognition = block?.institutional_cognition
  const prior = block?.prior_operator_decisions || []
  const contradictory = block?.contradictory_items || []
  return <Card title="Institutional cognition — advisory context, not office truth" testId="cio-institutional-cognition">
    <Provenance block={block} />
    <div data-testid="cognition-office-truth-boundary" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 8, margin: '8px 0' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 8, fontSize: 10 }}>
        <div style={{ fontWeight: 800, color: 'var(--text1)' }}>OFFICE_TRUTH · {office?.authority || 'UNKNOWN'}</div>
        <div style={{ color: 'var(--text2)', marginTop: 3 }}>{(office?.categories || block?.office_truth_boundary || []).join(' · ') || 'UNAVAILABLE'}</div>
        <div style={{ color: 'var(--amber)', marginTop: 3 }}>sourced from memory {String(office?.sourced_from_memory ?? 'UNKNOWN')} · replaceable by cognition {String(office?.replaceable_by_cognition ?? 'UNKNOWN')}</div>
        {office?.reason ? <div style={{ color: 'var(--text3)', marginTop: 3 }}>{office.reason}</div> : null}
      </div>
      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 8, fontSize: 10 }}>
        <div style={{ fontWeight: 800, color: 'var(--text1)' }}>INSTITUTIONAL_COGNITION · {cognition?.authority || 'UNKNOWN'}</div>
        <div style={{ color: 'var(--text2)', marginTop: 3 }}>{(cognition?.kinds || []).join(' · ') || 'UNAVAILABLE'}</div>
        <div style={{ color: 'var(--text3)', marginTop: 3 }}>may inform: {cognition?.may_inform || 'UNKNOWN'}</div>
      </div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(90px,1fr))', gap: 8, margin: '8px 0' }}>
      <Tile label="AVAILABLE" value={counts.available} state="LIVE" />
      <Tile label="RETRIEVED" value={counts.retrieved} state="RETRIEVED" />
      <Tile label="USED" value={counts.used} state="USED" />
      <Tile label="CHANGED" value={counts.changed} state="LIVE" />
      <Tile label="CONTRADICTORY" value={counts.contradictory} state="CONTRADICTORY" />
      <Tile label="INFLUENCE PROVEN" value={counts.influence_proven} state="PROVEN" />
    </div>
    {!items.length && <Empty text="No cognition receipts recorded; absence is not proof that no memory exists." />}
    <div style={{ display: 'grid', gap: 8 }}>
      <Group title={`Prior operator reject / defer advice · ${prior.length}`} testId="cognition-prior-operator-decisions" open={prior.length > 0}>
        {prior.length ? prior.slice(0, 25).map((item, i) => <CognitionRow key={`${item.id}-${i}`} item={item} />) : <Empty text="No prior operator rejection or deferral is recorded for this scope." />}
      </Group>
      <Group title={`Contradictory context · ${contradictory.length}`} testId="cognition-contradictory">
        {contradictory.length ? contradictory.slice(0, 25).map((item, i) => <CognitionRow key={`${item.id}-${i}`} item={item} />) : <Empty text="No cognition row carries a contradiction receipt." />}
      </Group>
      <Group title={`All cognition items · ${items.length}`} testId="cognition-items">
        {items.slice(0, 50).map((item, i) => <CognitionRow key={`${item.id || item.kind}-${i}`} item={item} />)}
      </Group>
    </div>
  </Card>
}

function LearningRows({ rows, idKey }: { rows?: any[]; idKey: string }) {
  if (!rows?.length) return <Empty text="None recorded." />
  return <div style={{ display: 'grid', gap: 4 }}>{rows.slice(0, 40).map((row: any, i: number) => <div key={`${row[idKey]}-${i}`} style={{ fontSize: 10, color: 'var(--text3)', borderTop: '1px solid var(--border-subtle)', paddingTop: 4 }}>
    <span style={{ color: tone(row.evidence_state), fontWeight: 800 }}>{row.evidence_state || 'UNKNOWN'}</span> · {row[idKey] || 'UNKNOWN'} · producer {row.producer_status || row.state || 'UNKNOWN'}{row.statement ? ` · ${String(row.statement).slice(0, 140)}` : ''}
    <br />settled {(row.resolved_outcome_ids || []).join(', ') || 'none'} · pending {(row.pending_outcome_ids || []).join(', ') || 'none'} · unresolved {(row.unresolved_evidence_ids || []).join(', ') || 'none'}{row.evidence_reason ? ` · ${row.evidence_reason}` : ''}
    {row.calibration_reason ? <><br />calibration {row.calibration ? `${row.calibration.method} · rate ${row.calibration.success_rate}` : `null · ${row.calibration_reason}`}</> : null}
  </div>)}</div>
}

function LinkMap({ title, map }: { title: string; map?: Record<string, unknown> }) {
  const entries = Object.entries(map || {})
  return <div style={{ fontSize: 10, color: 'var(--text3)' }}><div style={{ fontWeight: 800, color: 'var(--text2)' }}>{title} · {entries.length}</div>
    {entries.length ? entries.slice(0, 30).map(([k, v]) => <div key={k}>{k} → {Array.isArray(v) ? v.join(', ') : Object.entries((v || {}) as Record<string, string[]>).map(([kk, vv]) => `${kk}: ${(vv || []).join(', ') || 'none'}`).join(' · ')}</div>) : <div>No links from real refs.</div>}
  </div>
}

function LearningPanel({ block }: { block?: LearningBlock }) {
  const count = (value: unknown) => typeof value === 'number' ? String(value) : 'UNKNOWN'
  const states = block?.evidence_state_counts || {}
  const graph = block?.link_graph
  const calibration = block?.calibration
  return <Card title="Learning / belief cockpit — no self-promotion" testId="cio-learning-cockpit">
    <Provenance block={block} />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(100px,1fr))', gap: 8, margin: '10px 0' }}>
      <Tile label="SETTLED" value={block?.settled_count ?? block?.settled_outcomes?.length} state="LIVE" />
      <Tile label="PENDING" value={block?.pending_outcomes?.length} state="PENDING" />
      <Tile label="SAMPLE SIZE" value={block?.sample_size} state={block?.sample_size ? 'LIVE' : 'UNKNOWN'} />
      <Tile label="REVIEW_READY" value={block?.review_ready?.length} state="PROVEN" />
      <Tile label="PROVEN" value={states.PROVEN} state="PROVEN" />
      <Tile label="PENDING_OUTCOME" value={states.PENDING_OUTCOME} state="PENDING_OUTCOME" />
      <Tile label="INSUFFICIENT_EVIDENCE" value={states.INSUFFICIENT_EVIDENCE} state="INSUFFICIENT_EVIDENCE" />
    </div>
    <div style={{ color: 'var(--text2)', fontSize: 11 }}>state <span style={{ color: tone(block?.maturity_state || undefined), fontWeight: 800 }}>{block?.maturity_state || 'UNKNOWN'}</span> · successful {count(block?.successful_count)} · success rate {block?.success_rate == null ? 'UNKNOWN' : `${(block.success_rate * 100).toFixed(1)}%`} · settled without verdict {count(block?.settled_without_verdict_count)} · horizons {(block?.horizons || []).join(', ') || 'UNKNOWN'}</div>
    <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 3 }}>{block?.sample_rule || ''}{typeof block?.producer_review_ready_unproven === 'number' ? ` · ${block.producer_review_ready_unproven} producer REVIEW_READY rows lack settled evidence` : ''}</div>
    <div data-testid="learning-calibration" style={{ color: 'var(--text3)', fontSize: 10, marginTop: 6 }}>
      {calibration ? <><div>calibration method: {calibration.method}</div>{(calibration.groups || []).map((g, i) => <div key={i}>{g.population} · {g.horizon} · n={g.sample_size} · successful {g.successful} · rate {g.success_rate}</div>)}</> : <div>calibration null · {block?.calibration_reason || 'reason not recorded'}</div>}
    </div>
    <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
      <Group title={`Link graph · ${count(graph?.edge_count)} edges · ${count(graph?.unresolved_edge_count)} unresolved`} testId="learning-link-graph">
        <div style={{ color: 'var(--text3)', fontSize: 10, marginBottom: 4 }}>{graph?.rule || ''} {Object.entries(graph?.relation_counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>
        <div style={{ display: 'grid', gap: 6 }}>
          <LinkMap title="decision → outcomes" map={graph?.decision_to_outcomes} />
          <LinkMap title="outcome → beliefs" map={graph?.outcome_to_beliefs} />
          <LinkMap title="belief → lessons / hypotheses" map={graph?.belief_to_lessons_hypotheses} />
          <LinkMap title="lesson → source outcomes / decisions" map={graph?.lesson_to_sources} />
        </div>
      </Group>
      <Group title={`Beliefs · ${count(block?.beliefs?.length)}`}><LearningRows rows={block?.beliefs} idKey="belief_id" /></Group>
      <Group title={`Lessons · ${count(block?.lessons?.length)} (outcome-derived ${count(block?.outcome_derived_lessons?.length)} · research-derived ${count(block?.research_derived_lessons?.length)})`}><LearningRows rows={block?.lessons} idKey="lesson_id" /></Group>
      <Group title={`Hypotheses · ${count(block?.hypotheses?.length)} · experiments ${count(block?.experiments?.length)}`}><LearningRows rows={block?.hypotheses} idKey="hypothesis_id" /></Group>
    </div>
  </Card>
}

function KnownDarkTable({ block }: { block?: KnownDarkBlock }) {
  const items = block?.items || []
  return <details data-testid="coverage-known-dark" style={{ marginTop: 8 }}><summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 800 }}>KNOWN_DARK classification · {items.length} · baseline {block?.baseline_check || 'UNKNOWN'} · {Object.entries(block?.counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</summary>
    {block?.status !== 'AVAILABLE' && <Empty text={`Classification unavailable: ${block?.reason || 'not reported'}`} />}
    {(block?.unclassified_baseline_modules || []).length > 0 && <div style={{ color: 'var(--red)', fontSize: 10 }}>unclassified: {(block?.unclassified_baseline_modules || []).join(', ')}</div>}
    <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, marginTop: 6 }}>
      <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}><th>module</th><th>CIO</th><th>census</th><th>class</th><th>action</th><th>reason</th><th>consumer / successor</th></tr></thead>
      <tbody>{items.map((item) => <tr key={item.module} style={{ borderTop: '1px solid var(--border-subtle)', verticalAlign: 'top' }}>
        <td style={{ fontFamily: 'monospace' }}>{item.module}</td><td>{item.cio_relevant ? 'yes' : 'no'}</td><td>{item.census_state || 'UNKNOWN'}</td>
        <td style={{ color: tone(item.classification), fontWeight: 800 }}>{item.classification || 'UNKNOWN'}</td><td>{item.action_status || 'UNKNOWN'}</td>
        <td style={{ color: 'var(--text3)' }}>{item.reason || 'no reason'}</td><td style={{ color: 'var(--text3)' }}>{item.consumer_or_successor || 'UNKNOWN'}</td>
      </tr>)}</tbody>
    </table></div>
    <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 4 }}>source {block?.source_ref || 'UNKNOWN'} · doc {block?.doc_ref || 'UNKNOWN'}</div>
  </details>
}

function CoveragePanel({ block }: { block?: CoverageBlock }) {
  const rows = block?.rows || []
  return <Card title="Capability coverage — runtime artifact census" testId="cio-capability-coverage">
    <Provenance block={block} />
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '8px 0', fontSize: 10 }}>{Object.entries(block?.counts || {}).map(([key, value]) => <span key={key} style={{ color: tone(key), fontWeight: 800 }}>{key} {String(value)}</span>)}<span style={{ color: 'var(--text3)' }}>|</span>{Object.entries(block?.freshness_counts || {}).map(([key, value]) => <span key={key} style={{ color: tone(key), fontWeight: 800 }}>{key} {String(value)}</span>)}</div>
    {!rows.length && <Empty text="Capability producer evidence unavailable; this is not a clean zero." />}
    <div style={{ display: 'grid', gap: 5 }}>{rows.map((row: CoverageRow) => { const state = row.state || row.current_status || 'UNKNOWN'; return <details key={row.capability} style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}><summary style={{ cursor: 'pointer', fontSize: 11 }}><span style={{ color: tone(state), fontWeight: 800 }}>{state}</span> · <span style={{ color: tone(row.freshness), fontWeight: 700 }}>{row.freshness || 'UNKNOWN'}</span> · {row.capability}</summary><div style={{ color: 'var(--text3)', fontSize: 10, padding: '5px 0 2px 14px', lineHeight: 1.45 }}>contract {row.contract || 'UNKNOWN'} · producer {row.producer || 'UNKNOWN'} (module {row.producer_module_declared ? 'declared' : 'not found'}) · consumer {row.consumer || 'UNKNOWN'}<br />predicate {row.producer_predicate || 'UNKNOWN'} · discriminated {row.discriminated == null ? 'UNKNOWN' : String(row.discriminated)} · producer rows {row.producer_row_count ?? 'UNKNOWN'} · consumer refs {row.consumer_reference_count ?? 'UNKNOWN'}<br />artifact {row.durable_artifact || 'UNKNOWN'} · last produced {stamp(row.last_produced_at || row.last_producer_event)} · last consumed {stamp(row.last_consumed_at)} · age {row.artifact_age == null ? 'UNKNOWN' : `${row.artifact_age}s`} · stale after {row.stale_after_seconds == null ? 'UNKNOWN' : `${row.stale_after_seconds}s`}<br />{row.reason || 'No reason recorded.'}</div></details> })}</div>
    <KnownDarkTable block={block?.known_dark_classification} />
  </Card>
}

export default function CioOperatorEvidencePanel({ section = 'all' }: { section?: 'all' | 'research' | 'cognition' | 'learning' | 'coverage' }) {
  const [searchParams] = useSearchParams()
  const decisionId = section === 'research' ? (searchParams.get('decision') || '').trim() : ''
  const endpoint = section === 'research'
    ? `/api/v3/cio/research-provenance${decisionId ? `?decision_id=${encodeURIComponent(decisionId)}` : ''}`
    : '/api/v3/cio/operator-evidence'
  // Composition is shared server-side for 2 min; polling faster only re-reads the cache.
  const { data, loading, error } = useApi<Payload & ResearchBlock>(endpoint, 300_000)
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
