import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'
import ListPager, { useListOffset } from '../ListPager'
import type { ListPage } from '../ListPager'

type SetupEvidence = {
  source_name: string; passed_count: number; required_count: number; source_observation_state: string;
  criteria_source: string; policy_path: string;
  catalyst: { text: string | null; source: string | null; url: string | null; reported_verified: boolean | null; verification_status: string; factual_verification_status?: string; verification_method?: string | null; relevance?: string | boolean | number | null; relevance_reason?: string | null; model_confidence?: number | null; published_at: string | null; observed_at: string | null; publication_state: string };
  pillars: { id: string; label: string; value: number | boolean | null; status: string; observed_at?: string | null; source_ref?: string | null; threshold: Record<string, unknown> }[];
  social_scout: { reported_count: number | null; reported_met: string[] | null; reported_missing: string[] | null };
}

type Observation = { verdict: string; observed_at: string | null; event_at?: string | null; source_ref?: string | null; run_id?: string | null; kind?: string; sent?: boolean | null; lineage?: { event_id?: string | null; run_attempt_id?: string | null; source_sha?: string | null }; setup_evidence?: SetupEvidence }
type Source = { status: string; session_state: string; verdicts: string[]; observations: Observation[]; observation_count?: number }
type Candidate = { candidate_id: string; symbol: string; security_guid?: string | null; event_at?: string | null; session_date?: string | null; reconciliation_status?: string; sources: string[]; classification: string; conflicts: string[]; trade_ai: Source; active_trader: Source }
type Snapshot = {
  schema: 'SharedMomentumCandidates@v1'; snapshot_id: string; status: string; candidate_count: number | null;
  session_date: string; generated_at: string; candidates: Candidate[];
  source_metadata: Record<string, { status: string; cache_run_id?: string | null; stale?: boolean; cache_error?: string | null; tail_truncated?: boolean }>;
  pagination?: ListPage; filter_counts?: Record<string, number | null>; payload_gap?: { reason: string };
  history_source?: string;
}

type FilterMode = 'ACTIONABLE' | 'CONFLICT' | 'CURRENT' | 'ALL'

const observed = (source: Source) => source.observations[0]
const clock = (stamp?: string | null) => stamp ? `${new Date(stamp).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ET` : 'time unknown'

function isActionableRow(row: Candidate): boolean {
  if (row.conflicts.length > 0) return true
  if (row.classification === 'PENDING') return true
  const ta = row.trade_ai
  const at = row.active_trader
  if (at.session_state === 'CURRENT_SESSION' && at.observations.length > 0) return true
  if (ta.session_state === 'CURRENT_SESSION' && ta.observations.length > 0) {
    const facts = observed(ta)?.setup_evidence
    if (facts && (facts.passed_count > 0 || facts.catalyst?.text)) return true
    if (ta.verdicts.some(v => ['GO', 'WAIT', 'NOGO', 'NO_GO', 'AVOID', 'MANUAL_REVIEW'].includes(v))) return true
  }
  return false
}

/** Both pages render this exact server snapshot. Source verdicts never grant approval. */
export default function SharedMomentumCandidates() {
  const [filter, setFilter] = useState<FilterMode>('ACTIONABLE')
  const paging = useListOffset(filter)
  const { data, loading, error, stale } = useApi<Snapshot>(`/api/v2/trade-ai/candidates?filter=${filter}&offset=${paging.offset}&limit=20`, 30_000)
  const [params, setParams] = useSearchParams()
  const historyId = params.get('candidate')
  const setHistoryId = (id: string | null) => setParams(p => { if (id) p.set('candidate', id); else p.delete('candidate'); return p })
  const [historySource, setHistorySource] = useState<'TRADE_AI' | 'ACTIVE_TRADER'>('TRADE_AI')
  const historyPaging = useListOffset(`${historyId}:${historySource}`)
  const { data: history, loading: historyLoading, error: historyError } = useApi<Snapshot>(`/api/v2/trade-ai/candidates?candidate_id=${encodeURIComponent(historyId || '')}&history_source=${historySource}&offset=${historyPaging.offset}&limit=10`, 0, { enabled: !!historyId })
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const valid = data?.schema === 'SharedMomentumCandidates@v1' && Array.isArray(data.candidates)
  const retained = stale || Boolean(error)
  const allRows = valid ? data.candidates : []
  const rows = useMemo(() => {
    if (data?.pagination) return allRows
    if (filter === 'ALL') return allRows
    if (filter === 'CONFLICT') return allRows.filter(r => r.conflicts.length > 0)
    if (filter === 'CURRENT') {
      return allRows.filter(r =>
        r.trade_ai.session_state === 'CURRENT_SESSION' || r.active_trader.session_state === 'CURRENT_SESSION')
    }
    return allRows.filter(isActionableRow)
  }, [allRows, filter, data?.pagination])

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

  const setupCell = (source: Source, label: string, rowKey: string) => {
    const facts = observed(source)?.setup_evidence
    if (!facts) return <div style={{ color: 'var(--text3)' }}>{label} setup facts unknown</div>
    const open = !!expanded[`${rowKey}:${label}`]
    const catalyst = facts.catalyst
    const sourceVerified = catalyst.reported_verified === true ? 'source says verified' : catalyst.reported_verified === false ? 'source says unverified' : 'verification unknown'
    return <div style={{ marginBottom: 6 }}>
      <button type="button" onClick={() => setExpanded(e => ({ ...e, [`${rowKey}:${label}`]: !open }))}
        style={{ background: 'transparent', border: 0, padding: 0, cursor: 'pointer', color: 'var(--text0)', textAlign: 'left' }}>
        <strong>{label} · {facts.passed_count}/{facts.required_count} facts</strong>
        <span style={{ color: 'var(--text3)', fontSize: 10 }}> {open ? '▾' : '▸'}</span>
      </button>
      <div style={{ fontSize: 11 }}>{catalyst.text ?? 'Catalyst unknown'}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }}>Fact verification: {catalyst.factual_verification_status ?? 'UNKNOWN'} · {catalyst.verification_method ?? 'method unknown'}</div>
      <div style={{ fontSize: 10, color: 'var(--text3)' }} title={catalyst.relevance_reason ?? undefined}>Relevance: {catalyst.relevance == null ? 'unknown' : String(catalyst.relevance)} · model confidence: {catalyst.model_confidence == null ? 'unknown' : String(catalyst.model_confidence)}</div>
      <div data-published-at={catalyst.published_at ?? ''} style={{ fontSize: 10, color: 'var(--text3)' }}>Published {clock(catalyst.published_at)} · observed {clock(catalyst.observed_at)} · {catalyst.publication_state.replace(/_/g, ' ')}</div>
      {catalyst.url && <a href={catalyst.url} target="_blank" rel="noopener noreferrer" style={{ color: TOKENS.info }}>Catalyst source</a>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
        {facts.pillars.map(pillar => (
          <span key={pillar.id}
            title={`${pillar.label}: ${JSON.stringify(pillar.threshold)} · observed ${clock(pillar.observed_at)} · source ${pillar.source_ref ?? 'unknown'} · policy ${facts.policy_path}`}
            style={{
              fontSize: 10, padding: '1px 5px', borderRadius: RADIUS.sm,
              background: pillar.status === 'PASSED' ? 'rgba(34,197,94,.15)' : pillar.status === 'FAILED' ? 'rgba(239,68,68,.12)' : 'var(--bg2)',
              color: pillar.status === 'PASSED' ? TOKENS.success : pillar.status === 'FAILED' ? TOKENS.danger : 'var(--text3)',
            }}>
            {pillar.label} {pillar.value == null ? '—' : String(pillar.value)} · {pillar.status}
          </span>
        ))}
      </div>
      {open && (
        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>
          <div>{catalyst.source ?? 'source unknown'} · {sourceVerified} · {catalyst.verification_status.replace(/_/g, ' ')}</div>
          <div>{facts.source_observation_state.replace(/_/g, ' ')} · recency not measured · metadata only</div>
          {facts.social_scout.reported_count != null && (
            <div>SocialScout {facts.social_scout.reported_count}/5 reported upstream · different pillars</div>
          )}
        </div>
      )}
    </div>
  }

  const filters: { id: FilterMode; label: string }[] = [
    { id: 'ACTIONABLE', label: 'Actionable' },
    { id: 'CONFLICT', label: 'Conflicts' },
    { id: 'CURRENT', label: 'Current session' },
    { id: 'ALL', label: 'All' },
  ]

  return (
    <section className="shared-candidates" data-testid="shared-momentum-candidates" data-snapshot-id={valid ? data.snapshot_id : ''}
      style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg1)', marginBottom: 12 }}>
      <style>{`.shared-candidates button,.shared-candidates summary{min-height:44px;min-width:44px}.candidate-history{position:fixed;inset:80px 12px 12px auto;width:600px;max-width:calc(100vw - 24px);overflow:auto;background:var(--bg1);padding:16px;border:1px solid var(--border);z-index:1200;box-sizing:border-box}@media(max-width:820px){.shared-candidates table,.shared-candidates tbody,.shared-candidates tr,.shared-candidates td{display:block;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere}.shared-candidates thead{display:none}.shared-candidates td{min-width:0!important}.candidate-history{inset:0;width:100%;max-width:none}}`}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Shared momentum candidates · {valid && data.candidate_count != null ? data.candidate_count : '—'}</strong>
        <span style={{ fontSize: 10, color: 'var(--text3)' }} title={valid ? data.snapshot_id : undefined}>
          {valid ? `${data.session_date} · snapshot ${data.snapshot_id.slice(0, 10)}` : 'Snapshot unavailable'}
        </span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 8 }}>
        Same candidate list on Active Trader and TradeAI. Catalyst / five facts must appear for both sources when scan data exists. Verdicts never grant approval.
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {filters.map(f => (
          <button key={f.id} type="button" data-testid={`shared-candidates-filter-${f.id}`}
            onClick={() => { setFilter(f.id); paging.reset(); setHistoryId(null) }}
            style={{
              fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: RADIUS.md, cursor: 'pointer',
              border: `1px solid ${filter === f.id ? TOKENS.info : 'var(--border)'}`,
              background: filter === f.id ? 'rgba(59,130,246,.15)' : 'var(--bg2)',
              color: filter === f.id ? TOKENS.info : 'var(--text2)',
            }}>
            {f.label}{valid ? ` (${data.filter_counts ? data.filter_counts[f.id] ?? '—' : f.id === 'ALL' ? data.candidate_count ?? '—' : allRows.filter(isActionableRow).length})` : ''}
          </button>
        ))}
      </div>
      <ListPager page={data?.pagination} previous={paging.previous} next={paging.next} busy={loading} gap={data?.payload_gap} />
      {!valid && <div style={{ color: TOKENS.warning }}>{loading ? 'Loading shared candidates…' : 'Shared candidates unavailable · count not measured.'}</div>}
      {valid && (retained || data.status !== 'AVAILABLE') && <div style={{ fontSize: 11, color: TOKENS.warning, marginBottom: 8 }}>
        {retained ? 'Retained snapshot · latest read failed. ' : ''}Source state {data.status} · {Object.entries(data.source_metadata).map(([name, meta]) => `${name} ${meta.status}${meta.tail_truncated ? ' (journal tail only)' : ''}`).join(' · ')}
      </div>}
      {valid && (data.source_metadata.TRADE_AI?.stale || data.source_metadata.TRADE_AI?.cache_error) && <div style={{ fontSize: 11, color: TOKENS.warning, marginBottom: 8 }}>TradeAI cache reports stale or failed output.</div>}
      {valid && data.candidate_count === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No candidates in the observed sources.</div>}
      {valid && rows.length === 0 && allRows.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>No rows match this filter · switch to All to see the full list.</div>
      )}
      {rows.length > 0 && <div style={{ overflowX: 'auto', maxHeight: 360, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }} aria-label="Shared momentum candidate observations">
          <thead><tr style={{ textAlign: 'left', color: 'var(--text3)' }}>{['Symbol', 'TradeAI', 'ActiveTrader', 'Catalyst / five facts', 'Reconciliation'].map(label => <th key={label} style={{ padding: '6px 8px' }}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(row => <tr key={row.candidate_id} data-symbol={row.symbol} style={{ borderTop: '1px solid var(--border)' }}>
            <td style={{ padding: '6px 8px', fontWeight: 700 }}><SymbolLink symbol={row.symbol} />
              {['trade_ai', 'active_trader'].some(k => ((row[k as 'trade_ai' | 'active_trader'].observation_count ?? 0) > 1)) && <button type="button" onClick={() => setHistoryId(row.candidate_id)}>Observation history</button>}
            </td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.trade_ai, 'TradeAI')}</td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.active_trader, 'ActiveTrader')}</td>
            <td style={{ padding: '6px 8px', minWidth: 280 }}>
              {setupCell(row.trade_ai, 'TradeAI', row.candidate_id)}
              {row.active_trader.observations.length > 0 && setupCell(row.active_trader, 'ActiveTrader', row.candidate_id)}
            </td>
            <td style={{ padding: '6px 8px', color: row.conflicts.length ? TOKENS.warning : 'var(--text2)' }}>
              <div>{row.classification === 'PENDING' ? 'Awaiting TradeAI classification' : row.classification.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: 10 }}>{row.reconciliation_status?.replace(/_/g, ' ') ?? 'reconciliation unmeasured'} · {row.session_date ?? 'session unknown'}</div>
              <div style={{ fontSize: 10 }} title={row.security_guid ?? undefined}>Security {row.security_guid ?? 'identity unresolved'}</div>
              {row.conflicts.length > 0 && <div style={{ fontSize: 10 }} title={row.conflicts.join(', ')}>Conflicting source verdicts · originals retained</div>}
            </td>
          </tr>)}</tbody>
        </table>
      </div>}
      {historyId && <aside className="candidate-history" role="dialog" aria-modal="true" aria-label="Candidate observation history">
        <button type="button" autoFocus onClick={() => setHistoryId(null)}>Back to candidates</button>
        <div>{(['TRADE_AI', 'ACTIVE_TRADER'] as const).map(source => <button key={source} type="button" aria-pressed={source === historySource} onClick={() => setHistorySource(source)}>{source === 'TRADE_AI' ? 'TradeAI' : 'Active Trader'}</button>)}</div>
        <ListPager page={history?.pagination} previous={historyPaging.previous} next={historyPaging.next} busy={historyLoading} gap={history?.payload_gap} />
        {history?.candidates?.[0]?.candidate_id === historyId && (!history.history_source || history.history_source === historySource) ? <>
          <h3>{history.candidates[0].symbol} observation history</h3>
          {sourceCell(historySource === 'TRADE_AI' ? history.candidates[0].trade_ai : history.candidates[0].active_trader, historySource === 'TRADE_AI' ? 'TradeAI' : 'ActiveTrader')}
        </> : <div role="status">{history?.payload_gap || historyError ? 'Observation history unavailable for this read.' : 'Loading observation history…'}</div>}
      </aside>}
    </section>
  )
}
