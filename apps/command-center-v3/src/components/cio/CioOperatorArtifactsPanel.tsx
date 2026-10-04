import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'
import { decisionLineageHref } from '../../lib/cioDecisionLineage'
import { ARTIFACT_LABELS, artifactFields, artifactSummary, type CioOperatorArtifact } from '../../lib/cioOperatorArtifacts'

type Props = { decisionId?: string | null; compact?: boolean }

type Payload = {
  ok?: boolean
  artifacts?: CioOperatorArtifact[]
  counts_by_schema?: Record<string, number>
  total_matched?: number
  store_present?: boolean
  error?: string
}

function stamp(value?: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 19) : 'UNKNOWN'
}

/** CIO outputs that used to be transient (Telegram-only or used inside a cycle). */
export default function CioOperatorArtifactsPanel({ decisionId = null, compact = false }: Props) {
  const [schema, setSchema] = useState('')
  const params = new URLSearchParams()
  if (decisionId) params.set('decision_id', decisionId)
  if (schema) params.set('schema', schema)
  params.set('limit', compact ? '10' : '50')
  const { data, loading, error } = useApi<Payload>(`/api/v3/cio/operator-artifacts?${params.toString()}`, 60_000)
  const artifacts = data?.artifacts || []
  const counts = data?.counts_by_schema || {}

  return (
    <section data-testid="cio-operator-artifacts" style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg1)', display: 'grid', gap: 10 }}>
      <div>
        <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.6px' }}>CIO OUTPUTS</div>
        <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: 12, lineHeight: 1.5 }}>
          What the CIO composed and sent or used: advisory messages, briefs, answers, narratives, critiques, decisions and cards.
          {decisionId ? ` Filtered to decision ${decisionId}.` : ''} READ_ONLY_ADVISORY.
        </div>
      </div>
      {!compact && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }} role="group" aria-label="Filter by output type">
          <button type="button" onClick={() => setSchema('')} aria-pressed={!schema}
            style={{ minHeight: 32, padding: '4px 10px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: !schema ? 'var(--bg3)' : 'transparent', color: 'var(--text1)', fontSize: 11 }}>
            All ({data?.total_matched ?? 0})
          </button>
          {Object.entries(counts).map(([key, n]) => (
            <button key={key} type="button" onClick={() => setSchema(key)} aria-pressed={schema === key}
              style={{ minHeight: 32, padding: '4px 10px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: schema === key ? 'var(--bg3)' : 'transparent', color: 'var(--text1)', fontSize: 11 }}>
              {ARTIFACT_LABELS[key] || key} ({n})
            </button>
          ))}
        </div>
      )}
      {loading && !data && <div style={{ color: 'var(--text2)', fontSize: 12 }}>Loading CIO outputs…</div>}
      {(error || data?.ok === false) && <div style={{ color: 'var(--amber)', fontSize: 12 }}>CIO outputs unavailable: {String(error || data?.error || 'error')}</div>}
      {data && data.ok !== false && artifacts.length === 0 && (
        <div style={{ color: 'var(--text2)', fontSize: 12 }}>
          {data.store_present === false
            ? 'No CIO outputs recorded yet. They appear here as the CIO sends or composes them.'
            : 'No CIO outputs match this filter.'}
        </div>
      )}
      {artifacts.map((row, index) => (
        <details key={`${row.original_schema}-${row.artifact_id}-${index}`} data-testid="cio-operator-artifact"
          style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 8 }}>
          <summary style={{ cursor: 'pointer', listStyle: 'revert', fontSize: 12, color: 'var(--text1)' }}>
            <span style={{ fontWeight: 800 }}>{ARTIFACT_LABELS[row.original_schema || ''] || row.original_schema || 'Output'}</span>
            {row.symbol ? ` · ${row.symbol}` : ''} · {stamp(row.persisted_at)}
            <span style={{ display: 'block', color: 'var(--text2)', marginTop: 3 }}>{artifactSummary(row)}</span>
          </summary>
          <div style={{ display: 'grid', gap: 3, fontSize: 11, color: 'var(--text2)', padding: '6px 0 0 14px' }}>
            <div>Producer: {row.producer || 'not recorded'} · source as of {stamp(row.source_as_of)} · {row.evidence_class || 'UNKNOWN'}</div>
            <div>Id: {row.artifact_id || 'UNKNOWN'} ({row.artifact_id_basis || 'unknown basis'}){row.source_ref ? ` · ${row.source_ref}` : ''}</div>
            {row.payload_truncated && <div style={{ color: 'var(--amber)' }}>Payload was truncated when stored.</div>}
            {row.decision_id && <div><Link to={decisionLineageHref(row.decision_id)} style={{ color: 'var(--accent)' }}>Open decision lineage</Link></div>}
            {artifactFields(row).map(([k, v]) => <div key={k}><span style={{ color: 'var(--text3)' }}>{k}:</span> {v}</div>)}
          </div>
        </details>
      ))}
    </section>
  )
}
