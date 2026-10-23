// AccountChip — which account a row belongs to (operator 2026-10-23: "two SpaceX and two different
// accounts" / "just a name, not the account numbers"). Prints the account NAME only, never a number.
import { accountName, accountsBadge } from '../lib/accountLabels'
import { accountBrand } from '../lib/holdingsRowModel'

export function AccountChip({ account, label, compact }: { account?: string | null; label?: string | null; compact?: boolean }) {
  const name = accountName(account ?? '', label)
  const brand = accountBrand(String(account ?? name))
  return (
    <span
      data-testid="account-chip"
      title={`Account: ${name}`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, maxWidth: '100%', minWidth: 0,
        padding: compact ? '0 6px' : '1px 7px', borderRadius: 999, verticalAlign: 'middle',
        background: brand.bg, border: `1px solid ${brand.color}55`,
        fontSize: compact ? 10 : 11, fontWeight: 600, lineHeight: '16px', color: 'var(--text1)',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}
    >
      {name}
    </span>
  )
}

export function AccountsBadge({ n }: { n: number }) {
  return (
    <span
      data-testid="accounts-badge"
      title={`Held in ${accountsBadge(n)}`}
      style={{
        display: 'inline-flex', alignItems: 'center', padding: '0 6px', borderRadius: 999,
        fontSize: 10, fontWeight: 700, lineHeight: '16px', whiteSpace: 'nowrap',
        color: 'var(--text0)', border: '1px solid var(--border2, var(--border))', background: 'var(--bg2)',
      }}
    >
      {accountsBadge(n)}
    </span>
  )
}
