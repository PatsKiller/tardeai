import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { RADIUS } from '../../lib/designTokens'
import { Tooltip } from '../primitives'

export type ProposalSource = { proposal_id?: string; directive_id?: number | string; play?: string; contract_guid?: string }
const greekHelp: Record<string, string> = { delta: 'Price sensitivity to a $1 change in the stock. It is not assignment probability.', gamma: 'How delta changes as the stock moves $1.', theta: 'Estimated daily time decay, holding other inputs constant.', vega: 'Sensitivity to a one percentage point change in implied volatility.', rho: 'Sensitivity to a one percentage point change in interest rates.' }
const box: CSSProperties = { border: '1px solid var(--border-color)', borderRadius: RADIUS.sm, padding: 12, marginTop: 10 }
const money = (v: unknown) => v == null ? 'unknown' : Number(v).toLocaleString(undefined, { style: 'currency', currency: 'USD' })
const value = (v: unknown) => v == null ? 'unknown' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })
async function post(operation: string, body: unknown) {
  const response = await fetch(`/api/v2/options/${operation}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const raw = await response.json(), result = raw.data ?? raw
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`)
  return result
}

/** One review surface for existing proposals and unstaged standing-plan matches.
 * Authentication stays in Broker Orders/Telegram and the existing order router.
 */
export default function StrategyProposalModal({ source, onClose, onManual }: {
  source: ProposalSource; onClose: () => void; onManual: (proposal: any) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [result, setResult] = useState<any>(null), [analysis, setAnalysis] = useState<any>(null)
  const [account, setAccount] = useState(''), [contracts, setContracts] = useState('1')
  const [tif, setTif] = useState('DAY'), [limit, setLimit] = useState(''), [lane, setLane] = useState('chatgpt')
  const [dirty, setDirty] = useState(true), [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [intent, setIntent] = useState('')
  const [preview, setPreview] = useState<any>(null)
  const [disposition, setDisposition] = useState('')
  const [scenarioPrices, setScenarioPrices] = useState('')
  const p = result?.proposal, economics = preview || p?.workflow_economics
  const quantityValid = /^\d+$/.test(contracts) && Number(contracts) > 0 && Number.isSafeInteger(Number(contracts))
  const accountInfo = result?.accounts?.find((a: any) => a.account_key === account)
  const reasons = result?.refusals || []
  function invalidate() { setDirty(true); setReviewed(false); setAnalysis(null); setMessage('Changes require refreshed quotes, analysis and review.'); setIntent('') }
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialog.current?.showModal()
    return () => opener?.focus()
  }, [])
  useEffect(() => {
    if (!p || !quantityValid) { setPreview(null); return }
    let cancelled = false
    const timer = window.setTimeout(() => {
      post('proposal/preview', { proposal_id: p.id, contracts: Number(contracts), limit_price: limit || undefined, tif, account_key: account, scenario_prices: scenarioPrices.trim() ? scenarioPrices.split(',').map(s => Number(s.trim())) : [] })
        .then(r => { if (!cancelled) setPreview(r.economics || null) }).catch((e: Error) => { if (!cancelled) { setPreview(null); setMessage(`Preview unavailable: ${e.message}`) } })
    }, 200)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [p, contracts, limit, tif, account, quantityValid, scenarioPrices])
  async function run(action: 'prepare' | 'analyze' | 'status' | 'review' | 'submit' | 'disposition') {
    setBusy(true); setMessage('')
    try {
      let r
      const binding = { proposal_id: p?.id, revision: p?.revision, account_key: account }
      if (action === 'prepare') {
        r = await post('proposal/prepare', { ...(p ? { proposal_id: p.id } : source), account_key: account, contracts: Number(contracts), tif, analysis_lane: lane, limit_price: limit || undefined })
        setResult(r); setAnalysis(r.analysis || null); setReviewed(false); setPreview(null)
        if (r.ok) { setDirty(false); setLimit(String(r.proposal.premium)); setAccount(r.proposal.account || '') }
      } else if (action === 'analyze' || action === 'status') {
        r = await post('proposal/analysis', { ...binding, request: action === 'analyze' })
        if (r.analysis) setAnalysis(r.analysis)
        if (r.status) setMessage(`Analysis ${r.status}. Check status when complete.`)
      } else if (action === 'disposition') {
        r = await post('proposal/disposition', { ...binding, note: disposition })
        if (r.ok) setMessage('Disposition recorded on the existing CIO review.')
      } else if (action === 'review') {
        r = await post('proposal/review', binding)
        setReviewed(!!r.ok)
        if (r.ok) setMessage('This revision is reviewed. Continue through the existing order approval process.')
      } else {
        r = await post('preflight', binding)
        if (r.ok && r.intent_id) { setIntent(r.intent_id); setMessage('Per-order approval requested. Confirm in Broker Orders or Telegram. Account resources and exact quotes will be checked again after approval.') }
      }
      if (!r.ok) setMessage(r.error || (r.refusals || r.blocks || []).map((x: any) => x.reason || x.code || x).join(' · ') || 'Unable to continue')
    } catch (e: any) { setMessage(e.message || String(e)) } finally { setBusy(false) }
  }
  const locked = busy || !!intent
  return <dialog ref={dialog} aria-labelledby="strategy-proposal-title" onCancel={onClose}
    style={{ width: 'min(960px, 94vw)', maxHeight: '90vh', overflowY: 'auto', background: 'var(--bg-0)', color: 'var(--text-0)', border: '1px solid var(--border-color)', borderRadius: RADIUS.md, padding: 20 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}><h2 id="strategy-proposal-title">Strategy Proposal</h2><button type="button" onClick={onClose} aria-label="Close strategy proposal">Close</button></div>
    {result?.environment === 'dry_test' && <p role="note">DRY RUN ONLY — no order transmitted.</p>}
    <p>{p ? `${p.symbol} · ${p.strategy.replace(/_/g, ' ')} · ${p.expiration}` : 'Refresh the selected contract to prepare an account-specific proposal.'}</p>
    <fieldset disabled={locked} style={box}><legend>Order choices</legend>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <label>{p?.strategy?.includes('spread') ? 'Number of spreads' : 'Number of contracts'} <input type="number" min="1" step="1" value={contracts} onChange={e => { setContracts(e.target.value); invalidate() }} style={{ width: 80 }} /></label>
        <label>Limit per unit <input type="number" min="0.01" step="0.01" value={limit} placeholder="Current quote" onChange={e => { setLimit(e.target.value); invalidate() }} style={{ width: 100 }} /></label>
        <label title="DAY expires at session end. GTC remains active until filled, cancelled or the broker's expiry limit.">Time in force <select value={tif} onChange={e => { setTif(e.target.value); invalidate() }}>
          {['DAY', 'GTC'].map(t => <option key={t} disabled={!!accountInfo && !accountInfo.supported_tif.includes(t)}>{t}</option>)}
        </select></label>
        <label>Analysis lane <select value={lane} onChange={e => { setLane(e.target.value); invalidate() }}><option value="chatgpt">ChatGPT</option><option value="grok">Grok</option><option value="deepseek-flash">DeepSeek Flash</option></select></label>
      </div>
      {!quantityValid && <p role="alert">Enter a positive whole number of contracts or spreads.</p>}
      <div role="radiogroup" aria-label="Account" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
        {(result?.accounts || []).map((a: any) => <label key={a.account_key} style={{ ...box, opacity: a.eligible ? 1 : .7 }}>
          <input type="radio" name="proposal-account" value={a.account_key} checked={account === a.account_key} disabled={!a.eligible} onChange={() => { setAccount(a.account_key); invalidate() }} /> {a.display_name} · {a.account_type}
          <div>{a.route === 'manual' ? 'Manual Fidelity workflow' : a.broker} · {a.freshness}</div>
          <div>Buying power {money(a.buying_power)} · available cash {money(a.available_cash)}</div>
          <div>Required capital {money(a.capital_required)} · shares {value(a.shares_required)} / available {value(a.uncommitted_shares)}</div>
          <small>{a.as_of ? new Date(a.as_of).toLocaleString() : 'Balance timestamp unknown'}</small>
          {(a.refusals || []).map((r: any, i: number) => <div key={i}>{r.reason}</div>)}
        </label>)}
      </div>
      <button type="button" disabled={!quantityValid} onClick={() => run('prepare')}>{busy ? 'Refreshing…' : 'Refresh quotes and accounts'}</button>
    </fieldset>
    {p && <>
      <p>Revision {p.revision.slice(0, 12)} · {dirty ? 'Changes awaiting refresh' : 'Prepared'} · {account || 'Account required'} · {contracts} × · {tif}</p>
      <table style={{ width: '100%' }}><caption>Every leg · quantities for the selected order</caption><thead><tr><th>Contract</th><th>Side</th><th>Quantity</th><th>Multiplier</th><th>Bid / ask</th><th>Provider quote time</th></tr></thead><tbody>
        {p.legs.map((l: any, i: number) => <tr key={i}><td>{l.expiration} {l.strike} {l.option_type}</td><td>{l.side}</td><td>{quantityValid ? Number(contracts) * l.ratio : 'invalid'}</td><td>{l.multiplier ?? 'unknown'}</td><td>{money(l.bid)} / {money(l.ask)}</td><td>{l.quote_time ? new Date(l.quote_time).toLocaleTimeString() : 'unknown'}</td></tr>)}
      </tbody></table>
      <details><summary>Market fields and their timestamps</summary>{p.legs.map((l: any, i: number) => <p key={i}>
        {l.strike} {l.option_type}: midpoint {money(l.mid)}, last {money(l.last)} (trade time {l.trade_time || 'unknown'}), IV {value(l.iv)}, volume {value(l.volume)} (as of {l.volume_time || 'unknown'}), OI {value(l.oi)} (publication {l.oi_time || 'unknown'}).
        {l.volume_warning ? ` Unusual volume: ${l.volume_warning}` : ' Unusual-volume assessment unavailable unless supplied by the data provider.'}
      </p>)}</details>
      {economics && <section style={box} aria-label="Deterministic economics"><h3>Reviewed economics {dirty && '(preview)'}</h3>
        <table><thead><tr><th>Measure</th><th>Per contract / spread</th><th>Position total</th></tr></thead><tbody>
          {['premium_total', 'fees_total', 'capital_required', 'max_profit', 'max_loss'].map(k => <tr key={k}><th>{k.replace(/_/g, ' ')}</th><td>{money(economics.per_contract?.[k])}</td><td>{k === 'max_profit' && economics.profit_unlimited ? 'Uncapped' : k === 'max_loss' && economics.loss_unlimited ? 'Unbounded' : money(economics[k])}</td></tr>)}
          {['delta', 'gamma', 'theta', 'vega', 'rho'].map(k => <tr key={k}><th><Tooltip content={greekHelp[k]}><button type="button" aria-label={`Explain ${k}`}>{k} ⓘ</button></Tooltip></th><td>{value(economics.per_contract?.greeks?.[k])}</td><td>{value(economics.greeks?.[k])}</td></tr>)}
        </tbody></table>
        <p>Break-even at expiry: {(economics.breakevens || []).map(money).join(', ') || 'unavailable'} · {economics.package_basis} · fees {economics.fees_basis}</p>
        <p>{economics.scenario_basis}. Best {money(economics.best_scenario?.combined_pl ?? economics.best_scenario?.option_pl)}, base {money(economics.base_scenario?.combined_pl ?? economics.base_scenario?.option_pl)}, worst {money(economics.worst_scenario?.combined_pl ?? economics.worst_scenario?.option_pl)}.</p>
        <h3>What-if outcomes at expiry · {economics.expiry_date}</h3>
        <label>Additional stock prices (comma separated) <input value={scenarioPrices} onChange={e => setScenarioPrices(e.target.value)} placeholder="Add prices to compare" /></label>
        <p>All dollar outcomes below cover {contracts} contract(s) / spread(s), using actual multipliers. Unknown fees are excluded.</p>
        <table><thead><tr><th>Stock at expiry</th><th>Option value / liability</th><th>Profit / loss</th><th>Return</th><th>Shares would return</th><th>Stock + option P&amp;L</th><th>Moneyness</th></tr></thead><tbody>{economics.scenarios.map((s: any, i: number) => <tr key={i}><td>{money(s.underlying_price)} ({s.label})</td><td>{money(s.option_expiry_value)}</td><td>{money(s.option_pl)}</td><td title={s.return_basis}>{value(s.option_return_pct)}%</td><td>{value(s.stock_return_pct)}%</td><td>{money(s.combined_pl)}</td><td>{s.moneyness.map((m: any) => `${m.strike} ${m.option_type}: ${m.state}`).join(' · ')}</td></tr>)}</tbody></table>
        {p.strategy === 'long_call' && <p>Per contract, option cost {money(economics.stock_comparison?.option_cost)} versus {money(economics.stock_comparison?.stock_cost)} for {value(economics.stock_comparison?.equivalent_shares)} shares. Time value is {money(economics.stock_comparison?.extrinsic_per_share)} per share and expires to zero. Share returns exclude dividends. At expiry, the option's percentage return overtakes shares above approximately {money(economics.stock_comparison?.outperformance_stock_price_at_expiry)}, before unknown fees.</p>}
        <p>{economics.before_expiry_note}</p>
        <p>POP model estimate: {value(economics.probability_of_profit_pct)}%. {economics.probability_basis}. Delta is price sensitivity, not assignment probability.</p>
        <p>{economics.assignment_note} <a href="https://www.optionseducation.org/referencelibrary/faq/options-assignment" target="_blank" rel="noreferrer">Assignment mechanics</a></p>
      </section>}
      <section style={box}><h3>Strategy explanation</h3><p>Analysis uses the selected existing lane and its budget. It explains supplied facts; it grants no execution authority.</p>
        <p>Status: {analysis?.status || 'Required'}</p><p>{analysis?.error}</p>
        {(analysis?.votes || []).map((v: any, i: number) => <p key={i} style={{ whiteSpace: 'pre-wrap' }}>{v.reasoning || v.rationale}</p>)}
        {!!analysis?.objections?.length && <div><p>Model objections require a recorded disposition in the existing CIO review.</p>
          <label>Disposition and rationale <textarea value={disposition} onChange={e => setDisposition(e.target.value)} /></label>
          <button disabled={locked || dirty || !disposition.trim()} onClick={() => run('disposition')}>Record in existing CIO review</button>
        </div>}
        <button disabled={locked || dirty} onClick={() => run('analyze')}>Request analysis</button>{' '}<button disabled={locked || dirty} onClick={() => run('status')}>Check analysis status</button>
      </section>
      {reasons.map((r: any, i: number) => <p key={i}>{r.reason}</p>)}
      <div style={box}><button disabled={locked || dirty || !account || reasons.length > 0 || analysis?.status !== 'completed'} onClick={() => run('review')}>Review this revision</button>{' '}
        {accountInfo?.route === 'manual' ? <button disabled={locked || dirty || !reviewed} onClick={() => onManual(p)}>Open existing Fidelity manual workflow</button>
          : <button disabled={locked || dirty || !reviewed} onClick={() => run('submit')}>Continue to existing 2FA</button>}
      </div>
    </>}
    <p role="status" aria-live="polite">{message}</p>
    {intent && <p>Intent {intent} · <a href="/v3/trading?tab=Broker%20Orders">Open Broker Orders</a>. Submission can stop for stale data or changed economics; return here to refresh and review.</p>}
    <p><a href="/v3/trading?tab=Options&otab=Lifecycle">Monitor options</a> · <a href="/v3/journal?tab=Options">TradeInView journal</a></p>
  </dialog>
}
