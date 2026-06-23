import { brokerOf } from '../lib/brokerThesis'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const BLUE = '#60a5fa'
const GREEN = '#22c55e'
const PURPLE = '#a855f7'

export type BrokerAccount = {
  account_key: string
  display_name?: string
  broker?: string
  auto_eligible?: boolean
  execution_mode?: string
  execution_label?: string
  activity?: {
    cash?: number
    cash_available?: number
    open_trades?: number
    max_concurrent_positions?: number
    slots_used_today?: number
    max_new_positions_per_day?: number
    daily_limit_reached?: boolean
  }
}

type Props = {
  accounts: BrokerAccount[]
  value: string
  onChange: (accountKey: string) => void
  disabled?: boolean
  compact?: boolean
}

const SCHWAB = { color: BLUE, bg: 'rgba(96,165,250,.12)', border: 'rgba(96,165,250,.35)' }
const FIDELITY = { color: PURPLE, bg: 'rgba(168,85,247,.12)', border: 'rgba(168,85,247,.35)' }

export default function BrokerAccountPicker({ accounts, value, onChange, disabled, compact }: Props) {
  const schwab = accounts.filter(a => brokerOf(a.account_key) === 'Schwab')
  const fidelity = accounts.filter(a => brokerOf(a.account_key) === 'Fidelity')
  const selected = accounts.find(a => a.account_key === value)

  const renderOption = (a: BrokerAccount) => {
    const b = brokerOf(a.account_key)
    const theme = b === 'Fidelity' ? FIDELITY : SCHWAB
    const mode = a.auto_eligible ? 'Auto + Manual' : 'Manual only'
    return (
      <option key={a.account_key} value={a.account_key}>
        {b} · {a.display_name || a.account_key} ({mode})
      </option>
    )
  }

  return (
    <div style={{
      padding: compact ? '8px 10px' : '10px 12px',
      borderRadius: 10,
      background: 'rgba(15,23,42,.55)',
      border: '1px solid var(--border)',
    }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 8 }}>
        Destination account
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {schwab.length > 0 && (
          <span style={{ fontSize: 8.5, fontWeight: 800, padding: '3px 8px', borderRadius: 5, color: SCHWAB.color, background: SCHWAB.bg, border: `1px solid ${SCHWAB.border}` }}>
            Schwab — API auto (2FA) or manual
          </span>
        )}
        {fidelity.length > 0 && (
          <span style={{ fontSize: 8.5, fontWeight: 800, padding: '3px 8px', borderRadius: 5, color: FIDELITY.color, background: FIDELITY.bg, border: `1px solid ${FIDELITY.border}` }}>
            Fidelity — FA manual only
          </span>
        )}
      </div>

      <select
        disabled={disabled}
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: '100%', fontSize: 12, fontWeight: 700, padding: '8px 10px', borderRadius: 8,
          border: `1px solid ${selected ? (brokerOf(value) === 'Fidelity' ? FIDELITY.border : SCHWAB.border) : 'rgba(148,163,184,.3)'}`,
          background: 'rgba(2,6,23,.55)', color: TEXT0, cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        {!value && <option value="">— select account —</option>}
        {schwab.length > 0 && <optgroup label="Schwab accounts">{schwab.map(renderOption)}</optgroup>}
        {fidelity.length > 0 && <optgroup label="Fidelity accounts">{fidelity.map(renderOption)}</optgroup>}
      </select>

      {selected?.activity && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 8, fontSize: 9.5, color: MUTED }}>
          <span>Cash <b style={{ color: GREEN, fontFamily: 'monospace' }}>
            {fmtCash(selected.activity.cash ?? selected.activity.cash_available)}
          </b></span>
          <span>Open <b style={{ color: TEXT0 }}>{selected.activity.open_trades ?? '—'}</b>
            {selected.activity.max_concurrent_positions != null ? ` / ${selected.activity.max_concurrent_positions}` : ''}
          </span>
          <span>New today <b style={{ color: selected.activity.daily_limit_reached ? '#ef4444' : TEXT0 }}>
            {selected.activity.slots_used_today ?? 0}
            {selected.activity.max_new_positions_per_day != null ? ` / ${selected.activity.max_new_positions_per_day}` : ''}
          </b></span>
        </div>
      )}
    </div>
  )
}

function fmtCash(n?: number | null) {
  if (n == null) return '—'
  return n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${Math.round(n)}`
}