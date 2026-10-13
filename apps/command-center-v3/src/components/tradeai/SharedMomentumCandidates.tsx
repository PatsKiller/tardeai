import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'

type SetupEvidence = {
  source_name: string; passed_count: number; required_count: number; source_observation_state: string;
  criteria_source: string; policy_path: string;
  catalyst: { text: string | null; source: string | null; url: string | null; reported_verified: boolean | null; verification_status: string; factual_verification_status?: string; verification_method?: string | null; relevance?: string | boolean | number | null; relevance_reason?: string | null; model_confidence?: number | null; published_at: string | null; observed_at: string | null; publication_state: string };
  pillars: { id: string; label: string; value: number | boolean | null; status: string; observed_at?: string | null; source_ref?: string | null; threshold: Record<string, unknown> }[];
  social_scout: { reported_count: number | null; reported_met: string[] | null; reported_missing: string[] | null };
}

type Observation = { verdict: string; observed_at: string | null; event_at?: string | null; source_ref?: string | null; run_id?: string | null; kind?: string; sent?: boolean | null; lineage?: { event_id?: string | null; run_attempt_id?: string | null; source_sha?: string | null }; setup_evidence?: SetupEvidence }
type Source = { status: string; session_state: string; verdicts: string[]; observations: Observation[] }
type Candidate = { candidate_id: string; symbol: string; security_guid?: string | null; event_at?: string | null; session_date?: string | null; reconciliation_status?: string; sources: string[]; classification: string; conflicts: string[]; trade_ai: Source; active_trader: Source }
type Snapshot = {
  schema: 'SharedMomentumCandidates@v1'; snapshot_id: string; status: string; candidate_count: number | null;
  session_date: string; generated_at: string; candidates: Candidate[];
  source_metadata: Record<string, { status: string; cache_run_id?: string | null; stale?: boolean; cache_error?: string | null; tail_truncated?: boolean }>;
}

const observed = (source: Source) => source.observations[0]
const clock = (stamp?: string | null) => stamp ? `${new Date(stamp).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ET` : 'time unknown'

/** Both pages render this exact server snapshot. Source verdicts never grant approval. */
export default function SharedMomentumCandidates() {
  const { data, loading, error, stale } = useApi<Snapshot>('/api/v2/trade-ai/candidates', 30_000)
  const valid = data?.schema === 'SharedMomentumCandidates@v1' && Array.isArray(data.candidates)
  const retained = stale || Boolean(error)
  const rows = valid ? data.candidates : []
  const sourceCell = (source: Source, label: string) => {
    const last = observed(source)
    return <>
      <div>{source.verdicts.length ? source.verdicts.join(' / ').replace(/_/g, ' ') : `${label} unknown`}</div>
      <div data-source={label} data-run-id={last?.run_id ?? ''} data-observed-at={last?.observed_at ?? ''} data-event-at={last?.event_at ?? ''} data-source-ref={last?.source_ref ?? ''} style={{ color: 'var(--text3)', fontSize: 10 }}>{last ? `${last.kind ?? last.run_id ?? 'run unknown'} · ${clock(last.observed_at)}` : 'No source observation'}</div>
      {last && <div style={{ color: 'var(--text3)', fontSize: 10 }}>Run {last.run_id ?? 'unknown'} · event {clock(last.event_at)} · source {last.source_ref ?? 'unknown'}</div>}
      {source.observations.length > 1 && <details><summary>Observation history ({source.observations.length})</summary>{source.observations.map((item, index) => <div key={index}>{item.verdict} · {item.run_id ?? 'run unknown'} · observed {clock(item.observed_at)} · event {item.lineage?.event_id ?? 'unknown'}</div>)}</details>}
      {source.session_state !== 'CURRENT_SESSION' && <div style={{ color: TOKENS.warning, fontSize: 10 }}>{source.session_state.replace(/_/g, ' ')}</div>}
    </>
  }
  const setupCell = (source: Source, label: string) => {
    const facts = observed(source)?.setup_evidence
    if (!facts) return <div style={{ color: 'var(--text3)' }}>{label} setup facts unknown</div>
    const catalyst = facts.catalyst
    const sourceVerified = catalyst.reported_verified === true ? 'source says verified' : catalyst.reported_verified === false ? 'source says unverified' : 'verification unknown'
    return <div style={{ marginBottom: 8 }}>
      <strong>{label} · {facts.passed_count}/5 source facts</strong>
      <div>{catalyst.text ?? 'Catalyst unknown'}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>{catalyst.source ?? 'source unknown'} · {sourceVerified} · {catalyst.verification_status.replace(/_/g, ' ')}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>Fact verification: {catalyst.factual_verification_status ?? 'UNKNOWN'} · {catalyst.verification_method ?? 'method unknown'}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }} title={catalyst.relevance_reason ?? undefined}>Relevance: {catalyst.relevance == null ? 'unknown' : String(catalyst.relevance)} · model confidence: {catalyst.model_confidence == null ? 'unknown' : String(catalyst.model_confidence)}</div>
      <div data-published-at={catalyst.published_at ?? ''} style={{ fontSize: 10, color: 'var(--text3)' }}>Published {clock(catalyst.published_at)} · observed {clock(catalyst.observed_at)} · {catalyst.publication_state.replace(/_/g, ' ')}</div>
      {catalyst.url && <a href={catalyst.url} target="_blank" rel="noopener noreferrer" style={{ color: TOKENS.info }}>Catalyst source</a>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
        {facts.pillars.map(pillar => <span key={pillar.id} title={`${pillar.label}: ${JSON.stringify(pillar.threshold)} · observed ${clock(pillar.observed_at)} · source ${pillar.source_ref ?? 'unknown'} · policy ${facts.policy_path}`}
          style={{ color: pillar.status === 'PASSED' ? TOKENS.success : TOKENS.warning, fontSize: 10 }}>
          {pillar.label} {pillar.value == null ? 'unknown' : String(pillar.value)} · {pillar.status}
        </span>)}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>{facts.source_observation_state.replace(/_/g, ' ')} · recency not measured · metadata only</div>
      {facts.social_scout.reported_count != null && <div style={{ fontSize: 10, color: 'var(--text3)' }} title={`Met: ${facts.social_scout.reported_met?.join(', ') ?? 'unknown'}; missing: ${facts.social_scout.reported_missing?.join(', ') ?? 'unknown'}`}>SocialScout {facts.social_scout.reported_count}/5 reported upstream · different pillars</div>}
    </div>
  }
  return (
    <section data-testid="shared-momentum-candidates" data-snapshot-id={valid ? data.snapshot_id : ''}
      style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg1)', marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Shared momentum candidates · {valid && data.candidate_count != null ? data.candidate_count : '—'}</strong>
        <span style={{ fontSize: 10, color: 'var(--text3)' }} title={valid ? data.snapshot_id : undefined}>
          {valid ? `${data.session_date} · snapshot ${data.snapshot_id.slice(0, 10)}` : 'Snapshot unavailable'}
        </span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 8 }}>Same candidate list on Active Trader and TradeAI. Source observations and verdicts stay separate.</div>
      {!valid && <div style={{ color: TOKENS.warning }}>{loading ? 'Loading shared candidates…' : 'Shared candidates unavailable · count not measured.'}</div>}
      {valid && (retained || data.status !== 'AVAILABLE') && <div style={{ fontSize: 11, color: TOKENS.warning, marginBottom: 8 }}>
        {retained ? 'Retained snapshot · latest read failed. ' : ''}Source state {data.status} · {Object.entries(data.source_metadata).map(([name, meta]) => `${name} ${meta.status}${meta.tail_truncated ? ' (journal tail only)' : ''}`).join(' · ')}
      </div>}
      {valid && (data.source_metadata.TRADE_AI?.stale || data.source_metadata.TRADE_AI?.cache_error) && <div style={{ fontSize: 11, color: TOKENS.warning, marginBottom: 8 }}>TradeAI cache reports stale or failed output.</div>}
      {valid && data.candidate_count === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No candidates in the observed sources.</div>}
      {rows.length > 0 && <div style={{ overflowX: 'auto', maxHeight: 360, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }} aria-label="Shared momentum candidate observations">
          <thead><tr style={{ textAlign: 'left', color: 'var(--text3)' }}>{['Symbol', 'TradeAI', 'ActiveTrader', 'Catalyst / five facts', 'Reconciliation'].map(label => <th key={label} style={{ padding: '6px 8px' }}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(row => <tr key={row.candidate_id} data-symbol={row.symbol} style={{ borderTop: '1px solid var(--border)' }}>
            <td style={{ padding: '6px 8px', fontWeight: 700 }}><SymbolLink symbol={row.symbol} /></td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.trade_ai, 'TradeAI')}</td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.active_trader, 'ActiveTrader')}</td>
            <td style={{ padding: '6px 8px', minWidth: 300 }}>{setupCell(row.trade_ai, 'TradeAI')}{row.active_trader.observations.length > 0 && setupCell(row.active_trader, 'ActiveTrader')}</td>
            <td style={{ padding: '6px 8px', color: row.conflicts.length ? TOKENS.warning : 'var(--text2)' }}>
              <div>{row.classification === 'PENDING' ? 'Awaiting TradeAI classification' : row.classification.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 10 }}>{row.reconciliation_status?.replace(/_/g, ' ') ?? 'reconciliation unmeasured'} · {row.session_date ?? 'session unknown'}</div>
              <div style={{ fontSize: 10 }} title={row.security_guid ?? undefined}>Security {row.security_guid ?? 'identity unresolved'}</div>
              {row.conflicts.length > 0 && <div style={{ fontSize: 10 }} title={row.conflicts.join(', ')}>Conflicting source verdicts · originals retained</div>}
            </td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  )
}
