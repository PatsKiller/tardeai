import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'
import { isCioLineageState, type CioLineageState } from '../../lib/cioDecisionLineage'

type Stage = {
  state?: CioLineageState
  producer?: string | null
  consumer?: string | null
  source_ref?: string | null
  source_as_of?: string | null
  composition_as_of?: string | null
  evidence_class?: string | null
  source_sha?: string | null
  run_id?: string | null
  trace_id?: string | null
  value?: unknown
}

type Lineage = {
  schema?: string
  decision_id?: string
  lineage_id?: string | null
  composition_as_of?: string | null
  source_as_of?: string | null
  authority?: string
  stages?: Record<string, Stage>
  decision?: Record<string, unknown> | null
}

type Props = { decisionId?: string | null }

const STAGES: Array<[string, string]> = [
  ['wake_event', 'Wake / event'],
  ['security_identity', 'Security identity'],
  ['office_truth', 'Office truth'],
  ['institutional_cognition', 'Institutional cognition'],
  ['canon_frameworks', 'Canon / frameworks'],
  ['research_retrieved', 'Research retrieved'],
  ['research_used', 'Research used in judgment'],
  ['research_rejected', 'Research rejected'],
  ['research_gap', 'Research gap'],
  ['specialist_delegation', 'Specialist delegation'],
  ['specialist_disagreement', 'Specialist disagreement'],
  ['model_route', 'Model route'],
  ['judgment', 'Judgment'],
  ['counter_thesis', 'Counter-thesis'],
  ['confidence', 'Confidence'],
  ['falsifier', 'Falsifier'],
  ['notification', 'Notification decision'],
  ['operator_disposition', 'Operator disposition'],
  ['checkpoint', 'Outcome checkpoint'],
  ['outcome', 'Outcome'],
  ['belief_calibration_lesson', 'Belief / calibration / lesson'],
]

function stamp(value?: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 19) : 'UNKNOWN'
}

function stateTone(state: string): string {
  if (state === 'LIVE') return 'var(--green)'
  if (state === 'PARTIAL' || state === 'PENDING' || state === 'UNWIRED') return 'var(--amber)'
  if (state === 'UNAVAILABLE') return 'var(--red)'
  return 'var(--text3)'
}

export default function CioDecisionLineagePanel({ decisionId }: Props) {
  const path = decisionId ? `/api/v3/cio/decision/${encodeURIComponent(decisionId)}/lineage` : '/api/v3/cio/decision/_not_selected/lineage'
  const { data, loading, error } = useApi<{ ok?: boolean; lineage?: Lineage; error?: string }>(path, undefined, { enabled: Boolean(decisionId) })
  const lineage = data?.lineage

  return (
    <section data-testid="cio-decision-lineage" style={{ display: 'grid', gap: 12 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg2)' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.6px' }}>CIO DECISION LINEAGE</div>
        <div style={{ marginTop: 5, color: 'var(--text1)', fontSize: 12, lineHeight: 1.5 }}>
          Direct decision projection from canonical CIO evidence. Control Plane remains the diagnostic/engineering view.
        </div>
        <div style={{ marginTop: 8, color: 'var(--text3)', fontSize: 11 }}>
          {decisionId ? `Decision: ${decisionId}` : 'Open this view from a decision card to select a decision.'} · READ_ONLY_ADVISORY
        </div>
      </div>

      {!decisionId && <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, color: 'var(--text2)' }}>No decision selected. Nothing is fetched or inferred.</div>}
      {loading && decisionId && !lineage && <div style={{ color: 'var(--text2)' }}>Loading decision lineage…</div>}
      {error && <div style={{ border: '1px solid var(--amber)', borderRadius: RADIUS.md, padding: 12, color: 'var(--amber)' }}>Lineage unavailable: {String(error)}</div>}
      {!loading && decisionId && !lineage && !error && <div style={{ border: '1px solid var(--amber)', borderRadius: RADIUS.md, padding: 12, color: 'var(--amber)' }}>No exact CIODecisionLineage@v1 record is available for this decision. State: UNKNOWN.</div>}

      {lineage && (
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg1)' }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', color: 'var(--text2)', fontSize: 11 }}>
            <span>Schema: {lineage.schema || 'UNKNOWN'}</span><span>Lineage: {lineage.lineage_id || 'UNKNOWN'}</span><span>Authority: {lineage.authority || 'UNKNOWN'}</span>
          </div>
          <div style={{ marginTop: 8, color: 'var(--text3)', fontSize: 10 }}>Source as of {stamp(lineage.source_as_of)} · composed {stamp(lineage.composition_as_of)}</div>
          <div style={{ display: 'grid', gap: 6, marginTop: 14 }}>
            {STAGES.map(([key, label], index) => {
              const stage = lineage.stages?.[key]
              const state = isCioLineageState(stage?.state) ? stage.state : 'UNKNOWN'
              return <div key={key} style={{ display: 'grid', gridTemplateColumns: '24px minmax(180px, 1fr) minmax(120px, auto)', gap: 8, alignItems: 'center', borderTop: '1px solid var(--border-subtle)', padding: '7px 0', fontSize: 11 }}>
                <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{index + 1}</span>
                <span style={{ color: 'var(--text1)' }}>{label}<small style={{ display: 'block', color: 'var(--text3)', marginTop: 2 }}>{stage?.producer || 'producer not exposed'} · {stage?.source_ref || 'source not exposed'}</small></span>
                <span style={{ color: stateTone(state), fontWeight: 800, fontFamily: 'var(--mono)' }}>{state}</span>
              </div>
            })}
          </div>
        </div>
      )}
    </section>
  )
}
