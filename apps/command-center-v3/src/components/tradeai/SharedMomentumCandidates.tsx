import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'

type Observation = { verdict: string; observed_at: string | null; run_id?: string | null; kind?: string; sent?: boolean | null }
type Source = { status: string; session_state: string; verdicts: string[]; observations: Observation[] }
type Candidate = { candidate_id: string; symbol: string; sources: string[]; classification: string; conflicts: string[]; trade_ai: Source; active_trader: Source }
type Snapshot = {
  schema: 'SharedMomentumCandidates@v1'; snapshot_id: string; status: string; candidate_count: number | null;
  session_date: string; generated_at: string; candidates: Candidate[];
  source_metadata: Record<string, { status: string; cache_run_id?: string | null; stale?: boolean; cache_error?: string | null; tail_truncated?: boolean }>;
}

const observed = (source: Source) => source.observations[0]
const clock = (stamp?: string | null) => stamp ? new Date(stamp).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'time unknown'

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
      <div style={{ color: 'var(--text3)', fontSize: 10 }}>{last ? `${last.kind ?? last.run_id ?? 'run unknown'} · ${clock(last.observed_at)}` : 'No source observation'}</div>
      {source.session_state !== 'CURRENT_SESSION' && <div style={{ color: TOKENS.warning, fontSize: 10 }}>{source.session_state.replace(/_/g, ' ')}</div>}
    </>
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
          <thead><tr style={{ textAlign: 'left', color: 'var(--text3)' }}>{['Symbol', 'TradeAI', 'ActiveTrader', 'Reconciliation'].map(label => <th key={label} style={{ padding: '6px 8px' }}>{label}</th>)}</tr></thead>
          <tbody>{rows.map(row => <tr key={row.candidate_id} data-symbol={row.symbol} style={{ borderTop: '1px solid var(--border)' }}>
            <td style={{ padding: '6px 8px', fontWeight: 700 }}><SymbolLink symbol={row.symbol} /></td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.trade_ai, 'TradeAI')}</td>
            <td style={{ padding: '6px 8px' }}>{sourceCell(row.active_trader, 'ActiveTrader')}</td>
            <td style={{ padding: '6px 8px', color: row.conflicts.length ? TOKENS.warning : 'var(--text2)' }}>
              <div>{row.classification === 'PENDING' ? 'Awaiting TradeAI classification' : row.classification.replace(/_/g, ' ')}</div>
              {row.conflicts.length > 0 && <div style={{ fontSize: 10 }} title={row.conflicts.join(', ')}>Conflicting source verdicts · originals retained</div>}
            </td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  )
}
