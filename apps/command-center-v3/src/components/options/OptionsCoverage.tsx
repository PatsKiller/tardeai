import { useState } from 'react'
import { useApi } from '../../hooks/useApi'

type CoverageRow = {
  symbol: string
  source_lanes: string[]
  status: string
  research_status?: string
  chain?: { status?: string; contract_count?: number; fetched_at?: string }
  accounts?: Array<{ account?: string; shares: number; covered_call_capacity: number; excluded?: boolean }>
  proposal_count: number
  ready_count: number
  reasons?: Array<{ reason?: string }>
}
type Coverage = {
  rows: CoverageRow[]; total: number; inventory_count: number; account_position_count: number
  chain_completed_count: number; status: string; as_of?: string; run_id?: string; scan_enabled?: boolean
  scan_capacity?: { minimum_chain_requests_per_minute?: number; priority_symbol_count?: number; refresh_interval_minutes?: number; next_action?: string }
  source_receipts?: Record<string, { status: string; reason?: string; observed_at?: string }>
  runs?: Array<{ run_id: string; profile: string; status: string; completed: number; inventory_count: number }>
}

export default function OptionsCoverage({ requestScan }: { requestScan: (profile: 'full' | 'priority') => Promise<unknown> }) {
  const [page, setPage] = useState(0)
  const [symbol, setSymbol] = useState('')
  const { data, error, loading } = useApi<Coverage>(
    `/api/v2/options/coverage?offset=${page * 100}&limit=100&symbol=${encodeURIComponent(symbol)}`, 60_000)
  const rows = data?.rows || []
  return <section aria-label="Options coverage" style={{ color: 'var(--text0)', padding: 16 }}>
    <h3>All coverage</h3>
    <p>{data?.inventory_count ?? '—'} distinct securities · {data?.account_position_count ?? '—'} account positions · {data?.chain_completed_count ?? '—'} complete chain snapshots</p>
    <p>Scan: {data?.status || 'unavailable'} · As of {data?.as_of ? new Date(data.as_of).toLocaleString() : 'unknown'}</p>
    {!data?.scan_enabled && <p role="status">Expanded scanning is disabled. Requests cannot start until capacity is approved and the worker is activated.</p>}
    {data?.scan_capacity && <p>{data.scan_capacity.priority_symbol_count} priority symbols / {data.scan_capacity.refresh_interval_minutes} minutes requires at least {data.scan_capacity.minimum_chain_requests_per_minute} fresh chain requests/minute, before retries and projection. {data.scan_capacity.next_action}</p>}
    {Object.entries(data?.source_receipts || {}).map(([source, receipt]) =>
      <div key={source}>{source.replace(/_/g, ' ')}: {receipt.status}{receipt.reason ? ` · ${receipt.reason}` : ''}</div>)}
    {(data?.runs || []).slice(0, 2).map(run => <p key={run.run_id}>{run.profile} scan: {run.status} · {run.completed}/{run.inventory_count} securities processed</p>)}
    <p>Every holding, active watch and re-entry record belongs here. Inclusion does not mean an option is suitable or approved. Share coverage is calculated separately for each account.</p>
    <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
      <input aria-label="Find covered security" placeholder="Find symbol" value={symbol} onChange={e => { setSymbol(e.target.value); setPage(0) }} />
      <button disabled={!data?.scan_enabled} onClick={() => requestScan('priority')}>Request priority scan</button>
      <button disabled={!data?.scan_enabled} onClick={() => requestScan('full')}>Request full scan</button>
    </div>
    {error && <p role="alert">Coverage unavailable: {error}</p>}
    {loading && !data && <p>Loading coverage…</p>}
    <table style={{ width: '100%', textAlign: 'left', fontSize: 12 }}>
      <thead><tr><th>Security / source</th><th>Disposition</th><th>Chain coverage</th><th>Account coverage</th><th>Ideas</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.symbol}>
        <td><b>{row.symbol}</b><div>{row.source_lanes.join(', ')}</div></td>
        <td>{row.status}<div>{row.research_status?.replace(/_/g, ' ')}</div><div>{[...new Set((row.reasons || []).map(r => r.reason))].join(', ')}</div></td>
        <td>{row.chain?.status || 'PENDING'}<div>{row.chain?.contract_count ?? '—'} contracts</div><div>{row.chain?.fetched_at ? new Date(row.chain.fetched_at).toLocaleString() : 'No chain timestamp'}</div></td>
        <td>{(row.accounts || []).map((account, index) => <div key={`${account.account}-${index}`}>{account.account || 'unresolved account'}: {account.shares} shares · {account.covered_call_capacity} covered calls{account.excluded ? ' · excluded by policy' : ''}</div>)}</td>
        <td>{row.proposal_count} ideas · {row.ready_count} live eligible</td>
      </tr>)}</tbody>
    </table>
    {!rows.length && !loading && <p>No coverage rows{symbol ? ' match this symbol' : ' have been recorded'}.</p>}
    <div style={{ display: 'flex', gap: 16, marginTop: 12 }}>
      <button disabled={!page} onClick={() => setPage(p => p - 1)}>Previous</button>
      <span>Page {page + 1} · {data?.total ?? 0} matching securities</span>
      <button disabled={(page + 1) * 100 >= (data?.total || 0)} onClick={() => setPage(p => p + 1)}>Next</button>
    </div>
  </section>
}
