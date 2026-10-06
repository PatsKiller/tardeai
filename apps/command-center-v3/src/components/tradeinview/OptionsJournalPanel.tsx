import { useEffect, useState } from 'react'
import { useApi } from '../../hooks/useApi'

const money = (v: unknown) => v == null ? 'unknown' : Number(v).toLocaleString(undefined, { style: 'currency', currency: 'USD' })
const strategies = ['covered_call', 'cash_secured_put', 'long_call', 'long_put', 'protective_put', 'credit_spread', 'debit_spread', 'collar']
export default function OptionsJournalPanel({ account, days }: { account?: string; days: number }) {
  const [strategy, setStrategy] = useState(''), [status, setStatus] = useState(''), [symbol, setSymbol] = useState('')
  const [offset, setOffset] = useState(0), [error, setError] = useState('')
  const [spid, setSpid] = useState(() => new URLSearchParams(window.location.search).get('spid') || '')
  const [rollRoot, setRollRoot] = useState('')
  useEffect(() => setOffset(0), [account, days, strategy, status, symbol, spid, rollRoot])
  const params = new URLSearchParams({ days: String(days), limit: '25', offset: String(offset), strategy, status, symbol, spid, roll_root: rollRoot })
  if (account) params.set('account', account)
  const q = `/api/v2/journal/options-summary?${params}`
  const { data } = useApi<any>(q, 120_000)
  const d = data?.data ?? data, summary = d?.summary || {}
  async function download() {
    setError('')
    try {
      const response = await fetch(q + '&export=1'), raw = await response.json(), result = raw.data ?? raw
      if (!response.ok || !result.csv) throw new Error(result.error || 'Export unavailable')
      const url = URL.createObjectURL(new Blob([result.csv], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a'); a.href = url; a.download = 'options-journal.csv'; a.click(); URL.revokeObjectURL(url)
    } catch (e: any) { setError(e.message || String(e)) }
  }
  return <section aria-label="Options TradeInView journal">
    <h2>Options journal</h2>
    <p>{summary.total_strategies ?? '—'} strategies · {summary.completed_trades ?? '—'} completed · {summary.incomplete_outcomes ?? '—'} incomplete outcomes · known realized P&amp;L {money(summary.known_realized_pnl)} · known unrealized P&amp;L {money(summary.known_unrealized_pnl)} · {summary.unknown_unrealized ?? '—'} unknown marks</p>
    <p>Win rate {summary.win_rate == null ? 'unknown' : `${summary.win_rate}%`} among {summary.known_outcomes ?? '—'} known outcomes. Totals cover the complete filtered dataset.</p>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <label>Strategy <select aria-label="Strategy" value={strategy} onChange={e => setStrategy(e.target.value)}><option value="">All</option>{strategies.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}</select></label>
      <label>Status <select value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{['open', 'closing', 'closed', 'rolled', 'assigned', 'exercised', 'expired'].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Symbol <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} /></label>
      <button onClick={download}>Export all filtered strategies</button>
      {(spid || rollRoot) && <button onClick={() => { setSpid(''); setRollRoot('') }}>Show all identities</button>}
    </div>
    <p>{d?.audit_note} <a href="/v3/trading?tab=Options&otab=Proposals">Proposal audit and review</a></p>
    {(error || d?.error) && <p role="alert">{error || d.error}</p>}
    {(d?.data_warnings || []).map((s: string) => <p key={s}>{s}</p>)}
    {(d?.entries || []).map((r: any) => <details key={r.strategy_position_id} style={{ border: '1px solid var(--border-color)', padding: 12, marginTop: 10 }} open={!!spid}>
      <summary>{r.underlying} · {r.strategy_type.replace(/_/g, ' ')} · {r.account_key} · #{r.strategy_position_id} · {r.status} · realized {money(r.realized_pnl)} · basis {r.basis_status}</summary>
      <p>Opened {r.opened_at || 'unknown'} · closed {r.closed_at || '—'} · {r.outcome_validity} · source {r.source || 'unknown'}</p>
      <p><a href={r.deep_link}>Open lifecycle</a>{r.roll_root_id && <> · <button onClick={() => { setSpid(''); setRollRoot(String(r.roll_root_id)) }}>Roll lineage #{r.roll_root_id}</button></>}</p>
      <table style={{ width: '100%' }}><thead><tr><th>Contract</th><th>Side</th><th>Quantity</th><th>Multiplier</th><th>Entry / exit</th><th>Entry fees</th><th>Moneyness</th></tr></thead><tbody>
        {(r.legs || []).map((l: any, i: number) => <tr key={i}><td>{l.occ} · {l.expiration} · {l.strike} {l.option_type}</td><td>{l.side}</td><td>{l.contracts}</td><td>{l.multiplier ?? 'unknown'}</td><td>{money(l.opening_price)} / {money(l.closed_price)}</td><td>{money(l.opening_fees)}</td><td title={`Underlying ${l.moneyness_underlying_price ?? 'unknown'} as of ${l.moneyness_as_of ?? 'unknown'}`}>{l.moneyness}</td></tr>)}
      </tbody></table>
      <h3>Event timeline</h3>
      <ol>{(r.events || []).map((e: any, i: number) => <li key={e.event_id || i}>{e.at} · {e.event} · {e.source} · evidence {e.ref || 'unknown'}<pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(e.details || {}, null, 2)}</pre></li>)}</ol>
      <details><summary>Order / fill evidence, fees and references</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(r.fill_evidence || [], null, 2)}</pre></details>
      <details><summary>Entry, latest and exit snapshots · Greeks and collateral</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify({ entry: r.entry_snapshot, latest: r.latest_snapshot, exit: r.exit_snapshot, references: r.notes }, null, 2)}</pre></details>
      {!!r.stock_transfers?.length && <details><summary>Assignment / exercise → stock basis records</summary><p>Premium accounting follows the recorded transfer mode; this journal does not add the transferred premium again.</p><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(r.stock_transfers, null, 2)}</pre></details>}
    </details>)}
    {d && !d.entries?.length && <p>No strategies match these filters.</p>}
    <nav aria-label="Options journal pages" style={{ marginTop: 12 }}><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button> {offset + 1}–{offset + (d?.entries?.length || 0)} of {d?.total ?? '—'} <button disabled={!d?.has_more} onClick={() => setOffset(offset + 25)}>Next</button></nav>
  </section>
}
