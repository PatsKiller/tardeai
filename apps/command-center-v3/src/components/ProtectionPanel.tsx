import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'
import ProposalSourceBadges from './ProposalSourceBadges'
import ProposalStrategyBadge from './ProposalStrategyBadge'

interface Props { onDrill: (ctx: DrillContext) => void }

const ACTION_COLOR: Record<string, string> = {
  MOVE_STOP_TO_BREAKEVEN: '#f59e0b',
  MOVE_STOP_TO_PROFIT_LOCK: '#22c55e',
  ADD_FIXED_TAKE_PROFIT: '#06b6d4',
  CONVERT_TO_TRAILING_STOP: '#a855f7',
  KEEP_CURRENT_STOP: 'var(--text3)',
}

const ACTION_LABEL: Record<string, string> = {
  MOVE_STOP_TO_BREAKEVEN: 'Breakeven',
  MOVE_STOP_TO_PROFIT_LOCK: 'Profit Lock',
  ADD_FIXED_TAKE_PROFIT: 'Add Take-Profit',
  CONVERT_TO_TRAILING_STOP: 'Trailing Stop',
  KEEP_CURRENT_STOP: 'Keep Current',
}

const ACTION_TIP: Record<string, string> = {
  MOVE_STOP_TO_BREAKEVEN: 'Raise the stop to your entry price — removes downside risk; from here the trade can\'t lose.',
  MOVE_STOP_TO_PROFIT_LOCK: 'Raise the stop above entry to lock in part of the open gain, while leaving room to run.',
  ADD_FIXED_TAKE_PROFIT: 'Set a take-profit target so gains are realized automatically if price reaches it.',
  CONVERT_TO_TRAILING_STOP: 'Switch to a stop that follows price up, locking in more as the trade gains.',
  KEEP_CURRENT_STOP: 'No change recommended — current protection is appropriate.',
}

export default function ProtectionPanel({ onDrill }: Props) {
  const { data: proposals } = useApi<any>('/api/v2/atm/protection-adjustment-proposals', 60_000)
  const { data: coverage } = useApi<any>('/api/v2/atm/protection-coverage', 60_000)

  if (!proposals) return null

  const trades = proposals.trades ?? []
  const totalCandidates = proposals.proposal_count ?? 0
  const hasCandidates = totalCandidates > 0

  // Coverage KPIs
  const cov = coverage ?? {}

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <div>
          <span title="Stop/take-profit adjustments for open positions. ATM-governed — guarded stop-ups on the automated account auto-apply on the ATM cycle." style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', cursor: 'help' }}>Protection Advisory ⓘ</span>
          <span title="ATM governs disposition: auto-apply (guarded stop-ups), advisory, or operator approval for real accounts." style={{ marginLeft: 8, fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(34,197,94,.1)', color: '#22c55e', cursor: 'help' }}>
            ATM-GOVERNED
          </span>
          <span title="Automated (Alpaca) account — not live Schwab/Fidelity. Real accounts require operator + 2FA." style={{ marginLeft: 6, fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(96,165,250,.1)', color: '#60a5fa', cursor: 'help' }}>
            AUTOMATED
          </span>
        </div>
        <span title="Total adjustment options across the positions evaluated." style={{ fontSize: 9, color: 'var(--text3)', cursor: 'help' }}>{totalCandidates} proposals across {trades.length} positions ⓘ</span>
      </div>

      {/* Coverage strip */}
      {coverage && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 14, fontSize: 10 }}>
          <span title="Open positions that have a protective stop active at the broker." style={{ color: '#22c55e', cursor: 'help' }}>Protected: {cov.protected_at_broker ?? 0}/{cov.total_open_positions ?? 0} ⓘ</span>
          <span title="Open positions with no take-profit target set." style={{ color: cov.take_profit_missing > 0 ? '#f59e0b' : 'var(--text3)', cursor: 'help' }}>TP missing: {cov.take_profit_missing ?? 0} ⓘ</span>
          <span title="Positions up significantly but with no profit protection (stop still ≤ entry) — gains at risk of giving back." style={{ color: cov.large_gain_no_profit_protection > 0 ? '#ef4444' : 'var(--text3)', cursor: 'help' }}>Large gain unprotected: {cov.large_gain_no_profit_protection ?? 0} ⓘ</span>
          <span title="Positions using a trailing stop that follows price up." style={{ color: 'var(--text3)', cursor: 'help' }}>Trailing: {cov.trailing_active ?? 0} ⓘ</span>
        </div>
      )}

      {!hasCandidates ? (
        <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No protection adjustment candidates</div>
      ) : (
        <div>
          {trades.map((t: any) => {
            const candidates = (t.candidates ?? []).filter((c: any) => c.action !== 'KEEP_CURRENT_STOP')
            if (candidates.length === 0) return null
            return (
              <div key={t.symbol} style={{ marginBottom: 10, padding: '8px 10px', background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                    <ProposalSourceBadges proposal={{ ...t, proposal_kind: 'protection', origin: 'protection' }} size="sm" showRoutingLane />
                    <ProposalStrategyBadge proposal={t} size="sm" />
                  </div>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{candidates.length} options</span>
                </div>
                {candidates.map((c: any, i: number) => {
                  const color = ACTION_COLOR[c.action] ?? 'var(--text3)'
                  const label = ACTION_LABEL[c.action] ?? c.action?.replace(/_/g, ' ')
                  const hasStopChange = c.proposed_stop != null && c.proposed_stop !== c.current_stop
                  const hasTpChange = c.proposed_take_profit != null && c.proposed_take_profit !== c.current_take_profit
                  return (
                    <div key={i}
                      onClick={() => onDrill({
                        title: `${c.symbol} — ${label}`,
                        subtitle: `Proposal #${c.id}`,
                        endpoint: '/api/v2/atm/protection-adjustment-proposals',
                        rows: [c],
                        subjectType: 'position', subjectKey: c.symbol,
                      })}
                      style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '5px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                        fontSize: 10,
                      }}
                    >
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span title={ACTION_TIP[c.action] ?? ''} style={{ fontWeight: 600, color, fontSize: 10, cursor: 'help', borderBottom: '1px dotted ' + color }}>{label}</span>
                        {hasStopChange && (
                          <span style={{ color: 'var(--text2)' }}>
                            stop: {fmt$(c.current_stop, 2)} → <span style={{ color }}>{fmt$(c.proposed_stop, 2)}</span>
                          </span>
                        )}
                        {hasTpChange && (
                          <span style={{ color: 'var(--text2)' }}>
                            TP: {c.current_take_profit ? fmt$(c.current_take_profit, 2) : 'none'} → <span style={{ color: '#06b6d4' }}>{fmt$(c.proposed_take_profit, 2)}</span>
                          </span>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 9 }}>
                        {c.profit_locked_after > 0 && c.profit_locked_after !== c.profit_locked_before && (
                          <span style={{ color: '#22c55e' }}>locks ${c.profit_locked_after?.toFixed(0)}</span>
                        )}
                        {c.downside_protection_improvement > 0 && (
                          <span style={{ color: '#f59e0b' }}>+{c.downside_protection_improvement?.toFixed(0)}% protection</span>
                        )}
                        <span style={{ color: 'var(--text3)' }}>drill</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      )}

      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8, display: 'flex', justifyContent: 'space-between' }}>
        <span>Source: /api/v2/atm/protection-adjustment-proposals + /protection-coverage</span>
        <span>Read-only panel · execution via ATM cycle · auto-apply gated by PROTECTION_ATM_AUTO_APPLY_PAPER</span>
      </div>
    </div>
  )
}
