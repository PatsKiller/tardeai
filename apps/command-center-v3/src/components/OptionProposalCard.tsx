import { fmt$, fmtNum } from '../lib/format'
import { plainEnglishProposal, proposalRiskFlags, strikeDistance, strategyGuide } from '../lib/optionsNovice'
import { RiskFlagChips, StrikeDistanceBar, WhatIfBox } from './OptionsNovicePanel'

const BLUE = '#60a5fa'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const PURPLE = '#a855f7'
const MUTED = 'var(--text3)'
const TEXT0 = 'var(--text0)'
const TEXT1 = 'var(--text1)'
const TEXT2 = 'var(--text2)'

const STRAT_LABEL: Record<string, string> = {
  covered_call: 'Covered Call',
  cash_secured_put: 'Cash-Secured Put',
  long_call: 'Long Call',
  credit_spread: 'Credit Spread',
  protective_put: 'Protective Put',
}

const SEV = (s?: string) => {
  const v = (s || '').toLowerCase()
  if (/crit|urgent|danger/.test(v)) return { c: RED, bg: 'rgba(239,68,68,.13)', label: 'CRITICAL' }
  if (/warn|caution/.test(v)) return { c: AMBER, bg: 'rgba(245,158,11,.13)', label: 'WARNING' }
  if (/pos|ok|good/.test(v)) return { c: GREEN, bg: 'rgba(34,197,94,.13)', label: 'POSITIVE' }
  return { c: BLUE, bg: 'rgba(96,165,250,.13)', label: 'INFO' }
}

const TIPS = {
  spot: 'Current underlying price from Schwab chain or technical snapshot.',
  strike: 'Option strike price for this contract.',
  expiry: 'Expiration date — after this the option expires or is assigned.',
  dte: 'Days to expiration — theta decay accelerates in the final 2 weeks.',
  premium: 'Estimated mid price per contract (×100 shares). See data-source badge.',
  totalCredit: 'Total credit if filled: premium × 100 × contracts.',
  maxProfit: 'Best-case profit if the trade works as modeled.',
  maxLoss: 'Stock downside if price falls to $0 (you still own the shares). Premium reduces this slightly.',
  upsideCap: 'If assigned, you sell shares at this strike — gains above strike are forgone.',
  breakeven: 'Underlying price where P&L crosses zero at expiration.',
  rr: 'Risk/reward: max profit ÷ max loss (higher is better for defined-risk trades).',
  ev: 'Expected value ≈ total credit × POP% — probabilistic edge.',
  pop: 'Probability of profit at expiration (OTM for short premium, ITM edge for long).',
  ivRank: 'IV rank vs 52-week range — higher usually means richer premiums.',
  contracts: 'Contracts sized to shares held (CC) or risk budget.',
  account: 'Account that holds the underlying or will fund the trade.',
  edge: 'Composite quality score from POP, IV rank, R:R, and conviction. Gate ≥62.',
  delta: 'Option delta — approximate $ move per $1 underlying move.',
  oi: 'Open interest — liquidity; thin OI can mean wider fills.',
}

function fmtExpiry(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

function fmtMoneyish(v: number | string | null | undefined): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  return fmt$(v, v < 10 ? 2 : 0)
}

const metricBox = {
  background: 'rgba(2,6,23,.32)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '7px 8px',
} as const

function Metric({ label, value, color = TEXT0, tip }: { label: string; value: React.ReactNode; color?: string; tip?: string }) {
  return (
    <div style={metricBox} title={tip}>
      <div style={{ fontSize: 8, color: MUTED, textTransform: 'uppercase', fontWeight: 800, letterSpacing: '.04em' }}>{label}</div>
      <div style={{ fontSize: 12.5, color, fontWeight: 850, marginTop: 2, cursor: tip ? 'help' : undefined }}>{value}</div>
    </div>
  )
}

export type OptionProposal = {
  id: string
  strategy: string
  symbol: string
  strike: number
  expiration?: string
  dte?: number
  premium?: number
  premium_total?: number
  pop_pct?: number
  edge_score?: number
  iv_rank?: number
  max_profit?: number | string
  max_loss?: number | string
  stock_downside_risk?: number
  upside_cap?: string
  max_loss_note?: string
  upside_cap_note?: string
  aegis_note?: string
  aegis_verdict?: string
  intent_sleeve?: boolean
  breakeven?: number
  risk_reward?: number
  expected_value?: number
  reasoning?: string
  recommended_action?: string
  action_buttons?: { action: string; label: string }[]
  severity?: string
  underlying_price?: number
  contracts?: number
  account?: string
  broker?: string
  execution_mode?: string
  execution_label?: string
  auto_eligible?: boolean
  data_source?: string
  execution_note?: string
  delta?: number
  oi?: number
  side?: string
  option_type?: string
  short_strike?: number
  long_strike?: number
  desk_tier?: string
  enterprise?: { live_eligible?: boolean; blocks?: string[]; tier?: string }
}

const EXEC_ACTIONS = new Set(['sell_covered_call', 'sell_put', 'buy_put', 'buy_call', 'sell_credit_spread'])

export default function OptionProposalCard({
  proposal: p,
  armed,
  novice,
  onAction,
  onDrill,
  onManualLog,
  reviewBar,
}: {
  proposal: OptionProposal
  armed?: boolean
  novice?: boolean
  onAction: (action: string, id: string) => void
  onDrill?: () => void
  onManualLog?: () => void
  reviewBar?: React.ReactNode
}) {
  const sv = SEV(p.severity || (p.edge_score && p.edge_score >= 75 ? 'positive' : 'info'))
  const strat = STRAT_LABEL[p.strategy] || p.strategy.replace(/_/g, ' ')
  const edge = p.edge_score != null ? Math.round(p.edge_score) : null
  const ds = p.data_source === 'schwab_chain' ? { label: 'Schwab chain', c: GREEN } : p.data_source === 'bs_estimate' ? { label: 'BS estimate', c: AMBER } : null
  const isCredit = (p.side || '').toUpperCase() === 'SELL' || p.strategy === 'covered_call' || p.strategy === 'cash_secured_put' || p.strategy === 'credit_spread'
  const guide = strategyGuide(p.strategy)
  const dist = strikeDistance(p)
  const risks = novice ? proposalRiskFlags(p) : []
  const stockRisk = p.stock_downside_risk ?? (
    p.strategy === 'covered_call' && p.underlying_price && p.contracts
      ? Math.round(p.underlying_price * p.contracts * 100 - (p.premium_total ?? 0))
      : typeof p.max_loss === 'number' ? p.max_loss : null
  )

  const btnStyle = (action: string): React.CSSProperties => {
    if (action === 'hold') return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }
    if (action === 'review_chain') return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: `1px solid ${BLUE}55`, background: 'transparent', color: BLUE, cursor: 'pointer' }
    if (EXEC_ACTIONS.has(action)) {
      const manualOnly = p.execution_mode === 'manual' || p.broker === 'fidelity' || !p.auto_eligible
      const locked = !armed && !manualOnly
      return { fontSize: 10, fontWeight: 800, padding: '6px 14px', borderRadius: 6, border: 'none', background: locked ? 'var(--bg2)' : isCredit ? GREEN : BLUE, color: locked ? MUTED : '#0f172a', cursor: locked ? 'not-allowed' : 'pointer', opacity: locked ? 0.75 : 1 }
    }
    return { fontSize: 10, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: TEXT1, cursor: 'pointer' }
  }

  return (
    <div
      onClick={onDrill}
      style={{
        background: 'var(--bg1)',
        border: '1px solid var(--border)',
        borderLeft: `4px solid ${sv.c}`,
        borderRadius: 11,
        padding: '14px 15px',
        cursor: onDrill ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 8.5, fontWeight: 900, padding: '1px 6px', borderRadius: 4, color: sv.c, background: sv.bg }}>{sv.label}</span>
            <span title={guide.oneLiner} style={{ fontSize: 9, color: MUTED, cursor: 'help' }}>{guide.emoji} {strat}</span>
            <span style={{ fontSize: 12, fontWeight: 900, color: BLUE, fontFamily: 'monospace' }}>{p.symbol}</span>
            {ds && <span title={ds.label === 'BS estimate' ? 'Premium estimated via Black-Scholes — confirm on chain before sizing.' : 'Live bid/ask mid from Schwab option chain.'} style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: ds.c, background: `${ds.c}18`, border: `1px solid ${ds.c}44` }}>{ds.label}</span>}
            {p.intent_sleeve && <span title="Portfolio intent covered-call sleeve (V/SCHD/LMT) — relaxed edge floor 52 vs 62" style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: PURPLE, background: 'rgba(168,85,247,.15)', border: '1px solid rgba(168,85,247,.35)' }}>income sleeve</span>}
            {edge != null && <span title={TIPS.edge} style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: edge >= 72 ? GREEN : edge >= 50 ? AMBER : RED, background: 'var(--bg2)' }}>edge {edge}</span>}
            {p.execution_label && (
              <span title="Execution path for this proposal" style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, color: p.execution_mode === 'manual' ? PURPLE : AMBER, background: p.execution_mode === 'manual' ? 'rgba(168,85,247,.15)' : 'rgba(245,158,11,.15)', border: `1px solid ${p.execution_mode === 'manual' ? 'rgba(168,85,247,.35)' : 'rgba(245,158,11,.35)'}` }}>
                {p.execution_label}
              </span>
            )}
          </div>
          <div style={{ fontSize: 14, fontWeight: 850, color: TEXT0, marginTop: 6, lineHeight: 1.3 }}>
            {p.symbol}{' '}
            {p.short_strike && p.long_strike
              ? `$${fmtNum(p.short_strike, 0)}/$${fmtNum(p.long_strike, 0)} spread`
              : `$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)}`}{' '}
            · {p.dte ?? '—'} DTE
            {p.desk_tier && <span style={{ marginLeft: 6, fontSize: 9, color: p.desk_tier === 'A' ? GREEN : p.desk_tier === 'B' ? BLUE : MUTED }}>Tier {p.desk_tier}</span>}
            <span style={{ fontSize: 11, fontWeight: 500, color: MUTED, marginLeft: 8 }}>{fmtExpiry(p.expiration)}</span>
          </div>
        </div>
        {p.account && (
          <span title={TIPS.account} style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: 'var(--bg2)', color: TEXT2, whiteSpace: 'nowrap', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {p.account.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {novice && (
        <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.22)', fontSize: 10.5, color: TEXT2, lineHeight: 1.5 }}>
          <b style={{ color: BLUE }}>In plain English:</b> {plainEnglishProposal(p)}
        </div>
      )}

      {novice && dist && p.underlying_price && (
        <div title={dist.label}>
          <div style={{ fontSize: 9, color: MUTED, marginTop: 8 }}>{dist.label}</div>
          <StrikeDistanceBar spot={p.underlying_price} strike={p.strike} side={dist.side} />
        </div>
      )}

      {novice && <RiskFlagChips flags={risks} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 7, marginTop: 11 }}>
        <Metric label="Spot" value={`$${fmtNum(p.underlying_price, 2)}`} tip={TIPS.spot} />
        <Metric label="Strike" value={`$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)}`} tip={TIPS.strike} />
        <Metric label="Premium" value={p.premium != null ? fmt$(p.premium, 2) : '—'} color={GREEN} tip={TIPS.premium} />
        <Metric label="Total credit" value={fmt$(p.premium_total)} color={GREEN} tip={TIPS.totalCredit} />
        <Metric label="POP" value={p.pop_pct != null ? `${p.pop_pct.toFixed(1)}%` : '—'} color={p.pop_pct != null && p.pop_pct >= 60 ? GREEN : AMBER} tip={TIPS.pop} />
        <Metric label="R:R" value={p.risk_reward != null ? `${p.risk_reward.toFixed(2)}` : '—'} color={p.risk_reward != null && p.risk_reward >= 0.3 ? GREEN : TEXT1} tip={TIPS.rr} />
        <Metric label="Breakeven" value={p.breakeven != null ? `$${fmtNum(p.breakeven, 2)}` : '—'} tip={TIPS.breakeven} />
        <Metric label="EV" value={fmt$(p.expected_value)} color={PURPLE} tip={TIPS.ev} />
        <Metric label="Max profit" value={fmtMoneyish(p.max_profit)} color={GREEN} tip={TIPS.maxProfit} />
        {p.strategy === 'covered_call' ? (
          <>
            <Metric label="Stock risk" value={fmt$(stockRisk)} color={RED} tip={p.max_loss_note || TIPS.maxLoss} />
            <Metric label="Upside cap" value={p.upside_cap ?? `$${fmtNum(p.strike, p.strike < 50 ? 2 : 0)} if assigned`} color={AMBER} tip={p.upside_cap_note || TIPS.upsideCap} />
          </>
        ) : (
          <Metric label="Max loss" value={fmtMoneyish(p.max_loss)} color={RED} tip={TIPS.maxLoss} />
        )}
        <Metric label="IV rank" value={p.iv_rank != null ? `${p.iv_rank}%` : '—'} tip={TIPS.ivRank} />
        <Metric label="Contracts" value={p.contracts ?? '—'} tip={TIPS.contracts} />
        {p.delta != null && <Metric label="Delta" value={p.delta.toFixed(2)} tip={TIPS.delta} />}
        {p.oi != null && <Metric label="OI" value={fmtNum(p.oi, 0)} tip={TIPS.oi} />}
      </div>

      {novice && <WhatIfBox strategy={p.strategy} symbol={p.symbol} />}

      {reviewBar}

      {p.reasoning && (
        <div style={{ fontSize: 11, color: TEXT2, marginTop: 10, lineHeight: 1.45, borderTop: reviewBar ? undefined : '1px solid var(--border-subtle)', paddingTop: reviewBar ? 0 : 9 }}>
          {novice && <span style={{ fontSize: 9, fontWeight: 800, color: MUTED, display: 'block', marginBottom: 4 }}>ENGINE NOTES</span>}
          {p.reasoning.replace(/\s*·\s*Aegis:[^·]+/g, '').replace(/\s*Aegis:[^·]+/g, '').trim() || p.reasoning}
        </div>
      )}

      {p.execution_note && (
        <div title="Live execution path status" style={{ fontSize: 9.5, color: MUTED, marginTop: 8, fontStyle: 'italic', lineHeight: 1.4 }}>
          {p.execution_note}
        </div>
      )}

      <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, paddingTop: 9, borderTop: '1px solid var(--border-subtle)' }}>
        {(p.action_buttons || []).map((b, i) => {
          const manualOnly = p.execution_mode === 'manual' || p.broker === 'fidelity' || !p.auto_eligible
          const execLocked = EXEC_ACTIONS.has(b.action) && !armed && !manualOnly
          return (
            <button
              key={`${b.action}-${i}`}
              type="button"
              title={execLocked ? 'Execution locked — run options_pilot_arm.py --approve on server' : manualOnly && EXEC_ACTIONS.has(b.action) ? 'Manual execution at broker — use Executed manually to log' : undefined}
              disabled={execLocked}
              onClick={() => onAction(b.action, p.id)}
              style={btnStyle(b.action)}
            >
              {b.label}{b.action !== 'hold' ? ' →' : ''}
            </button>
          )
        })}
        {onManualLog && (
          <button type="button" onClick={onManualLog} style={{ fontSize: 10, fontWeight: 800, padding: '6px 12px', borderRadius: 6, border: `1px solid ${BLUE}55`, background: 'rgba(96,165,250,.12)', color: BLUE, cursor: 'pointer' }}>
            Executed manually
          </button>
        )}
      </div>
    </div>
  )
}