/** Caption under the Home Accounts table (LQ-20261113-3056, review 3054 F1/F2/F4): how many accounts are listed, how many
 *  have no value, and the true rounding bound. Its own component so a render test can pin it. */
import { TOKENS, TYPE } from '../../lib/designTokens'
import { accountsCaption } from '../../lib/homeDoNow'

const label = { fontSize: TYPE.xs, color: TOKENS.text[2], textTransform: 'uppercase' as const, letterSpacing: '0.06em' }

export function AccountsCaption({ rows }: { rows: { key: string; value?: number | null; oneRead?: boolean }[] }) {
  const text = accountsCaption(rows)
  if (!text) return null
  return <div data-testid="home-accounts-caption" style={{ ...label, textAlign: 'left', marginTop: 4 }}>{text}</div>
}
