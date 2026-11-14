// LQ-20261113-3076 (trace A07): the CIO card's Book row names its account counts; the narrower
// "with positions" count is never printed as plain "accounts".
//   node --experimental-strip-types src/lib/cioCardAccounts.test.ts
// Synthetic card bodies only.
import { bookAccountsText } from './cioCard.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}${got === undefined ? '' : ` — got ${JSON.stringify(got)}`}`) }
}
const DEF = 'an account is in the book when … cash rows included'

{
  const a = bookAccountsText({ accounts: 5, accounts_with_positions: 4, cash_only_accounts: ['syn_cash'], accounts_unnamed_rows: 0, accounts_definition: DEF })
  check('both counts named', a.text === '5 accounts (4 with positions)', a.text)
  check('definition in the title', (a.title ?? '').startsWith(DEF), a.title)
  check('cash-only account named in the title', (a.title ?? '').includes('Cash only: Syn Cash'), a.title)
}
{
  const a = bookAccountsText({ accounts: 3, accounts_with_positions: 3, cash_only_accounts: [], accounts_definition: DEF })
  check('equal counts print once', a.text === '3 accounts', a.text)
  const one = bookAccountsText({ accounts: 1, accounts_with_positions: 1, accounts_definition: DEF })
  check('singular', one.text === '1 account', one.text)
}
{
  const legacy = bookAccountsText({ accounts: 4 })
  check('a legacy card (no definition) is not printed as plain "accounts"', legacy.text === '4 accounts with positions (all-accounts count unknown)', legacy.text)
  check('legacy title says what the number is', (legacy.title ?? '').includes('non-cash position'), legacy.title)
  const fromServer = bookAccountsText({ accounts: null, accounts_with_positions: 4, accounts_definition: 'accounts holding a non-cash position (a brief written before LQ-3076 …)' })
  check('server-marked legacy brief: unknown total', fromServer.text === '4 accounts with positions (all-accounts count unknown)', fromServer.text)
}
{
  const a = bookAccountsText({ accounts: 5, accounts_with_positions: 4, accounts_unnamed_rows: 2, accounts_definition: DEF })
  check('unnamed rows are said', a.text === '5 accounts (4 with positions) · 2 rows with no account', a.text)
  check('nothing known -> no text', bookAccountsText({ accounts_definition: DEF }).text === null)
  check('no book -> no text', bookAccountsText(null).text === null)
}

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
