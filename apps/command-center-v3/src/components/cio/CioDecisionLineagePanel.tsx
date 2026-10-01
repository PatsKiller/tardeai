import { useMemo, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

type Lineage = {
  lineage_id?: string
  decision_id?: string | null
  symbol?: string | null
  status?: string | null
  origin?: string | null
  authority?: string | null
  created_at?: string | null
  updated_at?: string | null
  transitions?: Array<{ status?: string; producer?: string; at?: string; reason?: string }>
  [key: string]: unknown
}

type Props = { decisionId?: string | null }

const STAGES = [
  ['wake/event', 'discovery_id'],
  ['subject/security identity', 'subject_guid'],
  ['portfolio truth', 'portfolio_truth'],
  ['persistent memory', 'memory_ids'],
  ['canon/framework retrieval', 'framework_refs'],
  ['Hermes/RAG/web research', 'research_result_ids'],
  ['research gap', 'research_gap'],
  ['specialist delegation', 'specialist_artifacts'],
  ['specialist disagreement', 'specialist_disagreement'],
  ['model route', 'model_route'],
  ['judgment', 'decision_id'],
  ['counter-thesis', 'counter_thesis'],
  ['confidence', 'confidence'],
  ['falsifier', 'falsifier'],
  ['notification policy', 'notification_policy'],
  ['operator disposition', 'operator_disposition'],
  ['checkpoint', 'checkpoint_id'],
  ['outcome', 'outcome_id'],
  ['belief/lesson/calibration update', 'lesson_id'],
] as const

function missingState(key: string, lineage: Lineage): string {
  if (key === 'outcome_id' || key === 'lesson_id') return 'OUTCOME_PENDING'
  if (key === 'specialist_artifacts' || key === 'specialist_disagreement') return 'UNWIRED'
  if (key === 'framework_refs' || key === 'research_gap') return 'NOT_RUN'
  if (lineage.status === 'DISCOVERED') return 'NOT_APPLICABLE'
  return 'UNAVAILABLE'
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0
  return value !== null && value !== undefined && String(value).trim() !== ''
}

function stamp(value: unknown): string {
  return value ? String(value).replace('T', ' ').slice(0, 19) : 'UNAVAILABLE'
}

export default function CioDecisionLineagePanel({ decisionId }: Props) {
  const { data, loading, error } = useApi<any>('/api/v3/intelligence/lineages', 30_000)
  const [open, setOpen] = useState<string | null>(null)
  const detail = useApi<any>(open ? `/api/v3/intelligence/lineage/${encodeURIComponent(open)}` : '/api/v3/intelligence/authority', undefined, { enabled: Boolean(open) })
  const rows: Lineage[] = data?.lineages || []
  const matches = useMemo(() => {
    if (!decisionId) return rows
    return rows.filter(row => String(row.decision_id || '') === decisionId || String(row.lineage_id || '') === decisionId)
  }, [decisionId, rows])
  const lineage = (detail.data?.lineage || matches[0]) as Lineage | undefined

  return (
    <section data-testid="cio-decision-lineage" style={{ display: 'grid', gap: 12 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg2)' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.6px' }}>CIO DECISION LINEAGE</div>
        <div style={{ marginTop: 5, color: 'var(--text1)', fontSize: 12, lineHeight: 1.5 }}>
          Operator investment-office trace. Control Plane remains the diagnostic/engineering view. Missing stages are disclosed; they are never inferred from neighboring records.
        </div>
        <div style={{ marginTop: 8, color: 'var(--text3)', fontSize: 11 }}>
          {decisionId ? `Requested decision: ${decisionId}` : 'Select a lineage record below.'} · READ_ONLY_ADVISORY
        </div>
      </div>

      {loading && !data && <div style={{ color: 'var(--text2)' }}>Loading decision lineage…</div>}
      {error && <div style={{ color: 'var(--amber)' }}>Lineage unavailable: {String(error)}</div>}
      {!loading && decisionId && matches.length === 0 && <div style={{ border: '1px solid var(--amber)', borderRadius: RADIUS.md, padding: 12, color: 'var(--amber)' }}>No lineage record is runtime-linked to this decision. Status: UNAVAILABLE.</div>}

      {!decisionId && rows.length > 0 && (
        <div style={{ display: 'grid', gap: 6 }}>
          {rows.slice(0, 20).map(row => (
            <button key={row.lineage_id} type="button" onClick={() => setOpen(String(row.lineage_id || ''))} style={{ textAlign: 'left', border: '1px solid var(--border)', borderRadius: RADIUS.sm, padding: 10, background: 'var(--bg1)', color: 'var(--text1)', cursor: 'pointer' }}>
              <strong>{row.symbol || 'BOOK'}</strong> · {row.status || 'UNAVAILABLE'} · <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{row.lineage_id || 'MISSING_ID'}</span>
            </button>
          ))}
        </div>
      )}

      {lineage && (
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg1)' }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', color: 'var(--text2)', fontSize: 11 }}>
            <span>Entity: {lineage.symbol || 'BOOK'}</span><span>Status: {lineage.status || 'UNAVAILABLE'}</span><span>Lineage: {lineage.lineage_id || 'MISSING_ID'}</span>
          </div>
          <div style={{ marginTop: 10, color: 'var(--text3)', fontSize: 10 }}>Created {stamp(lineage.created_at)} · updated {stamp(lineage.updated_at)} · producer {lineage.origin || 'UNAVAILABLE'}</div>
          <div style={{ display: 'grid', gap: 6, marginTop: 14 }}>
            {STAGES.map(([label, key], index) => {
              const value = lineage[key]
              const live = hasValue(value)
              const state = live ? 'LIVE' : missingState(key, lineage)
              const transition = lineage.transitions?.find(t => String(t.status || '').toLowerCase() === label.toLowerCase())
              return <div key={key} style={{ display: 'grid', gridTemplateColumns: '24px minmax(180px, 1fr) auto', gap: 8, alignItems: 'center', borderTop: '1px solid var(--border-subtle)', padding: '7px 0', fontSize: 11 }}>
                <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{index + 1}</span>
                <span style={{ color: 'var(--text1)' }}>{label}<small style={{ display: 'block', color: 'var(--text3)', marginTop: 2 }}>{transition?.producer || (live ? 'lineage record' : 'producer not evidenced')}</small></span>
                <span style={{ color: live ? 'var(--green)' : state === 'UNWIRED' ? 'var(--amber)' : 'var(--text3)', fontWeight: 800, fontFamily: 'var(--mono)' }} title={live ? JSON.stringify(value) : undefined}>{state}</span>
              </div>
            })}
          </div>
          {detail.loading && open && <div style={{ marginTop: 10, color: 'var(--text3)' }}>Loading selected record…</div>}
        </div>
      )}
    </section>
  )
}
