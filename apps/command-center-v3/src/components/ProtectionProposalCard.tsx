import { fmt$ } from '../lib/format'
import ProposalSourceBadges from './ProposalSourceBadges'
import ProposalStrategyBadge from './ProposalStrategyBadge'
import { desk, sectionLabel } from '../lib/proposalDeskTheme'

const MUTED = desk.textDim
const TEXT0 = desk.text
const GREEN = desk.green

const ACTION_LABEL: Record<string, string> = {
  MOVE_STOP_TO_BREAKEVEN: 'Breakeven stop',
  MOVE_STOP_TO_PROFIT_LOCK: 'Profit-lock stop',
  ADD_FIXED_TAKE_PROFIT: 'Add take-profit',
  CONVERT_TO_TRAILING_STOP: 'Trailing stop',
  KEEP_CURRENT_STOP: 'Keep current',
}

const DISP_META: Record<string, { label: string; tip: string }> = {
  paper_auto_apply: {
    label: 'ATM auto-apply',
    tip: 'Automated account — ATM will auto-apply this guarded stop-up on the next cycle.',
  },
  advisory: {
    label: 'Advisory',
    tip: 'Action not in the auto-apply allowlist — stays advisory until operator acts.',
  },
  operator_approval: {
    label: 'Operator approval',
    tip: 'Real account — requires operator approval and 2FA downstream.',
  },
}

type Props = { proposal: any }

export default function ProtectionProposalCard({ proposal: p }: Props) {
  const action = String(p.action || '').toUpperCase()
  const label = ACTION_LABEL[action] || action.replace(/_/g, ' ').toLowerCase()
  const disp = DISP_META[String(p.atm_disposition || '')] || {
    label: 'Protection',
    tip: 'ATM-governed protection adjustment.',
  }
  const acct = p.account_display || p.account || '—'
  const pid = p.protection_id ?? (p.id < 0 ? -p.id : p.id)
  const trailMeta = p.evidence_refs?.trail ?? p.trail_meta
  const trailPct = trailMeta?.trail_percent

  return (
    <div style={{
      background: desk.bg,
      border: `1px solid ${desk.border}`,
      borderRadius: desk.radiusXl,
      padding: '12px 14px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 15, fontWeight: 800, color: TEXT0, fontFamily: desk.mono }}>{p.symbol}</span>
            <ProposalSourceBadges proposal={p} size="sm" showRoutingLane />
            <ProposalStrategyBadge proposal={p} size="sm" />
            <span title={disp.tip} style={{
              fontSize: 9, padding: '2px 8px', borderRadius: desk.radius,
              background: desk.bgInset, color: desk.textMuted, border: `1px solid ${desk.borderSubtle}`, cursor: 'help',
            }}>
              {disp.label}
            </span>
          </div>
          <div style={{ fontSize: 10, color: MUTED, marginTop: 4, fontFamily: desk.mono }}>
            #{pid} · {label} · {acct}
          </div>
        </div>
        <span style={{ fontSize: 9, color: MUTED }}>{String(p.created_at || '').slice(0, 16)}</span>
      </div>

      <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
        {p.current_stop != null && (
          <span style={{ color: MUTED }}>
            Stop: {fmt$(p.current_stop, 2)}
            {p.proposed_stop != null && p.proposed_stop !== p.current_stop && (
              <> → <span style={{ color: GREEN, fontWeight: 700 }}>{fmt$(p.proposed_stop, 2)}</span></>
            )}
          </span>
        )}
        {p.entry_price != null && (
          <span style={{ color: MUTED }}>Entry: {fmt$(p.entry_price, 2)}</span>
        )}
        {p.shares != null && (
          <span style={{ color: MUTED }}>{p.shares} sh</span>
        )}
        {action === 'CONVERT_TO_TRAILING_STOP' && trailPct != null && (
          <span title={trailMeta?.reason || 'Hybrid trail: max(family base %, ATR×family mult)'} style={{ color: desk.textMuted, cursor: 'help' }}>
            Trail {trailPct}% · {trailMeta?.trail_family || '—'} · R≥{trailMeta?.r_threshold ?? '—'}
          </span>
        )}
      </div>

      <div style={{ marginTop: 8, fontSize: 9, color: MUTED, lineHeight: 1.45 }}>
        <span style={sectionLabel}>ATM</span> No broker route · auto-apply gated by <code style={{ fontSize: 9 }}>PROTECTION_ATM_AUTO_APPLY_PAPER</code>
      </div>
    </div>
  )
}