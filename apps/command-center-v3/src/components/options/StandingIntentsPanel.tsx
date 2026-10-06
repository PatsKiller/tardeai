import { useState, type CSSProperties } from 'react'
import { RADIUS } from '../../lib/designTokens'
import { TipKpi } from '../OptionsTip'
import { Tooltip } from '../primitives'
import { EnsembleValidationInline } from '../EnsembleValidationCard'
import StandingIntentModal from './StandingIntentModal'

// Operator options intents (2026-10-05). The operator's standing plan for a name (e.g. SPCX: accumulate
// with cash-secured puts at or below support, covered calls only at strikes that keep the run toward
// $300) and the live Schwab contracts the matcher found for it. GET /api/v2/options/intents.
// Advisory only — no order control here.

type Row = {
  play?: string; exp?: string; strike?: number; mid?: number; iv?: number; delta?: number; oi?: number
  credit_per_contract?: number; collateral_per_contract?: number; annualized_pct?: number; breakeven?: number
  upside_kept_pct?: number; cost_per_contract?: number; stock_cost_100?: number; time_value_pct?: number
  crosses_earnings?: boolean | null; quote_time?: string; contract_guid?: string; desk_status?: string; next_action?: string
  desk_links?: Array<{ proposal_id?: string; account?: string; relationship?: string; options_thesis_pin?: string }>
}
type Match = {
  as_of?: string; spot?: number; quote_time?: string; earnings?: { date?: string | null; source?: string }
  plays?: Record<string, Row[]>; empty_reasons?: Record<string, string>; covered_call_floor?: number | null
  shares_by_account?: Record<string, number>
}
export type Intent = {
  symbol: string; directive_id?: number; status?: string; thesis_target?: number | null; thesis_source?: string
  goals?: string[]; plays?: Record<string, Record<string, unknown>>; rationale?: string; updated_at?: string
  avoid_earnings_cross?: boolean; earnings_estimate?: string; matches?: Match | null
  llm_review?: { target_id: string; target_type: string; content: string; task: string; as_of?: string }
}
export type IntentFeed = { status?: string; mode?: 'shadow' | 'send'; intents?: Intent[]; match_count?: number; unstaged_count?: number }

const PLAY_NAME: Record<string, string> = {
  cash_secured_put: 'Cash-secured puts — get paid to buy lower',
  covered_call: 'Covered calls — income with capped upside',
  leap_call: 'LEAP calls — stock substitute',
}
const PLAY_TIP: Record<string, { short: string; more: string; watch: string }> = {
  cash_secured_put: { short: 'Sell a put and reserve the cash to buy the shares if assigned.', more: 'For a standard contract, assignment means buying 100 shares at the strike. The premium reduces the effective purchase cost. Assignment can happen before expiry.', watch: 'The stock can fall far below your purchase price. Confirm account cash and willingness to own the shares.' },
  covered_call: { short: 'Collect premium by agreeing to sell shares you hold at the strike.', more: 'A standard call needs 100 available shares in the same account. Upside above the strike is capped; early assignment is possible. The strike floor is your preference, not a guarantee of retaining shares.', watch: 'Most stock downside remains. A rally beyond the strike can mean giving up substantial upside.' },
  leap_call: { short: 'Buy a long-dated call for upside exposure with less initial cash than shares.', more: 'It can expire worthless. The strike plus premium is the option breakeven at expiry. You own an option, not shares: no dividends or voting rights, and time decay and volatility changes affect value.', watch: 'You can lose the entire premium. A long call does not automatically authorize or cover a short call in your account.' },
}

function RiskReward({ row: r, spot }: { row: Row; spot?: number }) {
  const premium = r.mid, strike = r.strike
  const valid = premium != null && strike != null && Number.isFinite(premium) && Number.isFinite(strike) && premium > 0
  const downside = !valid ? null : r.play === 'cash_secured_put' ? Math.max(0, (strike! - premium!) * 100) : r.play === 'covered_call' ? (spot ? Math.max(0, (spot - premium!) * 100) : null) : premium! * 100
  const gain = !valid ? null : r.play === 'cash_secured_put' ? premium! * 100 : r.play === 'covered_call' && spot ? (strike! - spot + premium!) * 100 : null
  const ratio = gain != null && downside != null && downside > 0 ? (gain / downside).toFixed(2) : 'not finite'
  const tip = { short: 'Reward/risk = maximum gain divided by maximum loss at expiry; it is not the chance of winning.',
    more: 'These are estimates for one standard 100-share contract at the captured midpoint, before fees and slippage. Covered calls include the covered shares marked from captured spot; cash-secured puts include the obligation to buy. Long-call upside has no fixed maximum, so a finite ratio is unavailable.',
    watch: 'Compare capital, downside and time horizon. A small income ratio or an unlimited-upside label does not establish suitability.' }
  return <div style={muted}>
    <Tooltip placement="bottom" content={<><b>{tip.short}</b><p>{tip.more}</p><p>{tip.watch}</p></>}><button type="button" style={{ color: 'inherit', border: 0, background: 'none', padding: 0, cursor: 'help' }} aria-label="Explain risk and reward">Risk / reward ⓘ</button></Tooltip>
    {' '}· max gain {gain == null ? (valid && r.play === 'leap_call' ? 'uncapped' : 'unknown') : usd(gain)} · max loss {usd(downside)} · reward/risk {ratio} · per standard contract, midpoint estimate
  </div>
}

const n = (v?: number | null, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d))
const usd = (v?: number | null) => (v == null || !Number.isFinite(v) ? '—' : `$${Math.round(v).toLocaleString()}`)

const panel: CSSProperties = { background: 'var(--bg-1)', border: '1px solid var(--border-color)', borderRadius: RADIUS.md, padding: '10px 14px', marginBottom: 14 }
const muted: CSSProperties = { color: 'var(--text-3)', fontSize: 12 }
const mono: CSSProperties = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 12 }

function line(r: Row): string {
  if (r.play === 'cash_secured_put') {
    return `${r.exp} $${r.strike}P · mid $${n(r.mid)} · ${usd(r.credit_per_contract)} on ${usd(r.collateral_per_contract)} · ${n(r.annualized_pct, 0)}% annualized premium yield · breakeven $${n(r.breakeven)} · IV ${n(r.iv, 0)}% · Δ ${n(r.delta)} (price sensitivity, not assignment odds) · OI ${r.oi ?? '—'}`
  }
  if (r.play === 'covered_call') {
    return `${r.exp} $${r.strike}C · mid $${n(r.mid)} · ${usd(r.credit_per_contract)}/contract · keeps +${n(r.upside_kept_pct, 0)}% · ${n(r.annualized_pct, 0)}% annualized premium yield · IV ${n(r.iv, 0)}% · Δ ${n(r.delta)} · OI ${r.oi ?? '—'}`
  }
  return `${r.exp} $${r.strike}C · ${usd(r.cost_per_contract)} vs ${usd(r.stock_cost_100)} stock · time value ${n(r.time_value_pct, 1)}% · Δ ${n(r.delta)} · OI ${r.oi ?? '—'}`
}

export default function StandingIntentsPanel({ data, onSelectSymbol, onSaved }: { data?: IntentFeed | null; onSelectSymbol?: (symbol: string) => void; onSaved?: () => void }) {
  const [showCreate, setShowCreate] = useState(false)
  const [saved, setSaved] = useState(false)
  const intents = data?.intents ?? []
  return (
    <section style={panel} data-testid="options-standing-intents" aria-label="Your standing intents">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 14, color: 'var(--text-0)' }}>Your standing intents</strong>
        <span style={muted}>
          {data?.mode === 'send' ? 'Telegram digest on a better contract' : 'Shadow: shown here, no Telegram'} · captured Schwab quotes · advisory only
        </span>
      </div>
      <p style={muted}>This panel matches your explicit standing plans. Only symbols with a saved standing plan appear here; holdings and watchlist membership alone do not create one. Use the same workflow for any other symbol.</p>
      <button type="button" onClick={() => { setSaved(false); setShowCreate(true) }}>Create standing plan</button>
      {saved && <p role="status">Advisory plan saved. Waiting for the scheduled matcher; this does not approve a trade.</p>}
      {!intents.length && <p style={muted}>No standing plans recorded. Holdings, watch and reentry coverage remain in the desk below.</p>}
      {showCreate && <StandingIntentModal intents={intents} onClose={() => setShowCreate(false)} onSaved={() => { setSaved(true); onSaved?.() }} />}
      {intents.map(it => {
        const m = it.matches
        return (
          <div key={it.symbol} style={{ borderTop: '1px solid var(--border-subtle)', marginTop: 10, paddingTop: 10 }} data-testid="options-intent">
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <strong style={{ fontSize: 18, color: 'var(--text-0)' }}>{it.symbol}</strong>
              <TipKpi tip={it.thesis_source || 'Your thesis target'} label="Target" value={it.thesis_target ? `$${it.thesis_target}` : '—'} color="var(--text-1)" />
              <TipKpi tip={`Schwab quote ${m?.quote_time ?? ''}`} label="Captured spot" value={m?.spot ? `$${n(m.spot)}` : '—'} color="var(--text-1)" />
              <TipKpi tip={`Earnings date source: ${m?.earnings?.source ?? 'unknown'}`} label="Earnings" value={m?.earnings?.date ?? 'unknown'}
                color={it.avoid_earnings_cross ? 'var(--warning-color)' : 'var(--text-1)'} />
              <span style={muted}>{(it.goals ?? []).join(' + ')} · directive #{it.directive_id}</span>
            </div>
            {it.rationale && <p style={{ ...muted, margin: '6px 0' }}>{it.rationale}</p>}
            {!m && <p style={muted}>No recorded contract scan. The existing matcher supplies captured quotes.</p>}
            {m && Object.keys(it.plays ?? {}).map(play => {
              const rows = m.plays?.[play] ?? []
              return (
                <div key={play} style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>
                    <Tooltip placement="bottom" content={<><b>{PLAY_TIP[play]?.short}</b><p>{PLAY_TIP[play]?.more}</p><p>{PLAY_TIP[play]?.watch}</p></>}><button type="button" style={{ color: 'inherit', border: 0, background: 'none', padding: 0, cursor: 'help', fontWeight: 700 }} aria-label={`Explain ${PLAY_NAME[play] ?? play}`}>{PLAY_NAME[play] ?? play} ⓘ</button></Tooltip>
                    {play === 'covered_call' && m.covered_call_floor ? <span style={muted}> · floor ${n(m.covered_call_floor, 0)}</span> : null}
                  </div>
                  {rows.length === 0
                    ? <div style={muted}>No recorded matches — {m.empty_reasons?.[play] ?? 'no match'}</div>
                    : rows.slice(0, 3).map((r, i) => <div key={r.contract_guid || i} style={{ ...mono, color: 'var(--text-2)', marginBottom: 8 }}>
                        {line(r)}
                        <RiskReward row={r} spot={m.spot} />
                        <div style={muted}>Contract quoted: {r.quote_time ? new Date(r.quote_time).toLocaleString() : 'unknown'} · {r.desk_status === 'LINKED' ? 'Linked to an existing idea' : 'Not staged as an account-specific proposal'}</div>
                        <div style={muted}>{r.next_action || 'Account allocation and thesis review required.'}</div>
                        {(r.desk_links || []).map(link => <div key={link.proposal_id} style={muted}>
                          {link.relationship === 'same_strategy' ? 'Same strategy' : 'Same contract, different strategy'} · {link.account?.replace(/_/g, ' ')} · {link.options_thesis_pin || 'thesis unavailable'}
                          {onSelectSymbol && <button onClick={() => onSelectSymbol(it.symbol)}>View linked idea</button>}
                        </div>)}
                      </div>)}
                </div>
              )
            })}
            {it.llm_review && <details style={{ marginTop: 10 }}><summary style={{ cursor: 'pointer', fontWeight: 700 }}>LLM summary of this standing plan</summary>
              <p style={muted}>Explains these preferences and captured contracts. No new market research or order authority. A changed plan or scan gets a separate review; requests use the existing model budget.</p>
              <EnsembleValidationInline key={it.llm_review.target_id} targetType={it.llm_review.target_type} targetId={it.llm_review.target_id} content={it.llm_review.content} subject={`${it.symbol} standing options plan`} task={it.llm_review.task} narrative />
            </details>}
            {m?.as_of && <div style={{ ...muted, marginTop: 6 }}>Scan captured {new Date(m.as_of).toLocaleString()} · Underlying quoted {m.quote_time ? new Date(m.quote_time).toLocaleString() : 'unknown'}. A page refresh does not refresh these quotes.</div>}
            <div style={muted}>Annualized premium yield assumes repeated identical premiums; it is not an expected return. LEAP intent matches use the standing intent horizon, which may exceed the main desk’s 365-day scan.</div>
          </div>
        )
      })}
    </section>
  )
}
