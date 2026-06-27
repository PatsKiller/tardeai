import { fmt$ } from '../lib/format'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a78bfa'

const ACTION_LABEL: Record<string, string> = {
  MOVE_STOP_TO_BREAKEVEN: 'Breakeven stop',
  MOVE_STOP_TO_PROFIT_LOCK: 'Profit-lock stop',
  ADD_FIXED_TAKE_PROFIT: 'Add take-profit',
  CONVERT_TO_TRAILING_STOP: 'Trailing stop',
  KEEP_CURRENT_STOP: 'Keep current',
}

const DISP_META: Record<string, { label: string; color: string; tip: string }> = {
  paper_auto_apply: {
    label: 'ATM auto-apply',
    color: GREEN,
    tip: 'Automated account — ATM will auto-apply this guarded stop-up on the next cycle.',
  },
  advisory: {
    label: 'Advisory',
    color: AMBER,
    tip: 'Action not in the auto-apply allowlist — stays advisory until operator acts.',
  },
  operator_approval: {
    label: 'Operator approval',
    color: BLUE,
    tip: 'Real account — requires operator approval and 2FA downstream.',
  },
}

type Props = { proposal: any }

export default function ProtectionProposalCard({ proposal: p }: Props) {
  const action = String(p.action || '').toUpperCase()
  const label = ACTION_LABEL[action] || action.replace(/_/g, ' ').toLowerCase()
  const disp = DISP_META[String(p.atm_disposition || '')] || {
    label: 'Protection',
    color: PURPLE,
    tip: 'ATM-governed protection adjustment.',
  }
  const acct = p.account_display || p.account || '—'
  const pid = p.protection_id ?? (p.id < 0 ? -p.id : p.id)

  return (
    <div style={{
      background: 'var(--bg1)',
      border: '1px solid rgba(168,85,247,.35)',
      borderRadius: 12,
      padding: 14,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 16, fontWeight: 800, color: TEXT0, fontFamily: 'monospace' }}>{p.symbol}</span>
            <span title="Stop/take-profit adjustment for an open position — not a new entry." style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(168,85,247,.15)', color: PURPLE, cursor: 'help' }}>
              PROTECTION
            </span>
            <span title={disp.tip} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: `${disp.color}18`, color: disp.color, cursor: 'help' }}>
              {disp.label}
            </span>
          </div>
          <div style={{ fontSize: 11, color: MUTED, marginTop: 4 }}>
            #{pid} · {label} · {acct}
          </div>
        </div>
        <span style={{ fontSize: 9, color: MUTED }}>{String(p.created_at || '').slice(0, 16)}</span>
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
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
      </div>

      <div style={{ marginTop: 10, fontSize: 9, color: MUTED }}>
        ATM-governed · no broker route / cloud oversight · auto-apply gated by <code style={{ fontSize: 9 }}>PROTECTION_ATM_AUTO_APPLY_PAPER</code>
      </div>
    </div>
  )
}