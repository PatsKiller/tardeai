import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { RADIUS } from '../lib/designTokens'
import {
  decisionLineageHref,
  decisionLinkState,
  hermesProvenanceHref,
  linkItems,
  researchLinksUrl,
  symbolResearchHref,
  thesisHref,
  type HermesResearchLinksPayload,
} from '../lib/hermesResearchLinks'

// Hermes run/result → CIO decisions that consumed it (HermesResearchLinks@v1).
// Read-only. NOT_RECORDED is shown verbatim — the client never infers a decision link.
export default function HermesDecisionLinksPanel({
  symbol,
  decisionId,
  resultId,
  limit = 25,
  title = 'Hermes research → CIO decisions',
  showProvenanceLink = false,
}: {
  symbol?: string
  decisionId?: string
  resultId?: string
  limit?: number
  title?: string
  showProvenanceLink?: boolean
}) {
  const url = researchLinksUrl({ symbol: symbol?.trim() || undefined, decisionId, resultId, limit })
  const { data, loading, error } = useApi<HermesResearchLinksPayload>(url, 120_000)
  const items = linkItems(data)
  const recorded = items.filter(item => decisionLinkState(item) === 'RECORDED').length
  const link = { color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' } as const
  return <div data-testid="hermes-decision-links" style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
      <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>{title}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
        {data ? `${recorded}/${items.length} with recorded decision link · composed ${String(data.composition_as_of ?? 'UNKNOWN')}` : loading ? 'Loading…' : error ? 'UNAVAILABLE' : 'UNKNOWN'}
      </div>
    </div>
    {error && !data && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--amber)' }}>Research-link read failed: {String(error)}</div>}
    {data && items.length === 0 && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text3)' }}>No completed Hermes results in the read window{symbol ? ` for ${symbol.toUpperCase()}` : ''}.</div>}
    <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
      {items.map(item => {
        const state = decisionLinkState(item)
        return <div key={item.result_id} data-testid="hermes-decision-link-row" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline', fontSize: 11, padding: '5px 8px', borderRadius: RADIUS.sm, background: 'var(--bg2)' }}>
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{item.result_id}</span>
          {item.symbol ? <Link to={symbolResearchHref(item.symbol)} style={link}>{item.symbol}</Link> : <span style={{ color: 'var(--amber)' }}>symbol NOT_RECORDED</span>}
          <span style={{ color: 'var(--text3)' }}>{item.classification ?? ''}</span>
          {state === 'RECORDED'
            ? item.decision_ids.slice(0, 3).map(id => <Link key={id} to={decisionLineageHref(id)} style={link}>Decision {id} →</Link>)
            : <span style={{ color: 'var(--amber)', fontWeight: 700 }} title={item.decision_link?.reason ?? ''}>decision NOT_RECORDED</span>}
          {item.decision_ids.length > 3 && <span style={{ color: 'var(--text3)' }}>+{item.decision_ids.length - 3} more</span>}
          {item.thesis_refs.length > 0
            ? item.thesis_refs.slice(0, 2).map(ref => <Link key={ref} to={thesisHref(ref)} style={link}>Thesis {ref}</Link>)
            : <span style={{ color: 'var(--text3)' }}>thesis NOT_RECORDED</span>}
          {showProvenanceLink && <Link to={hermesProvenanceHref(item.result_id)} style={{ ...link, color: 'var(--text3)' }}>Hermes provenance</Link>}
        </div>
      })}
    </div>
    <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text3)' }}>Source: /api/v3/hermes/research-links (ResearchImpact@v1 · IntelligenceLineage@v1 · current CIO product). A recorded link shows the result was consumed by that decision; it does not claim the result changed the judgment.</div>
  </div>
}
