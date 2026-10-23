// Pure-logic tests for accountLabels.ts (account name on every row, operator 2026-10-23).
//   node --experimental-strip-types src/lib/accountLabels.test.ts
import {
  ACCOUNT_NAMES, UNLABELLED, accountName, accountsBadge, groupBySymbol, looksLikeAccountNumber,
  multiAccountSymbols, rowAccountName,
} from './accountLabels.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('accountLabels')
check('rollover name', accountName('schwab_rollover_ira') === 'Schwab Rollover IRA')
check('taxable name is "Schwab Individual"', accountName('schwab_taxable') === 'Schwab Individual')
check('holdings alias schwab_roth → Schwab Roth IRA', accountName('schwab_roth') === 'Schwab Roth IRA')
check('paper name', accountName('tradeai_automated') === 'Alpaca Paper')
check('every configured name is digit-free', Object.values(ACCOUNT_NAMES).every(n => !/\d/.test(n)))
check('names are unique', new Set(Object.values(ACCOUNT_NAMES)).size === Object.values(ACCOUNT_NAMES).length)
check('a raw account number is never echoed', accountName('12345678') === UNLABELLED)
check('a masked number is never echoed', accountName('...258') === UNLABELLED && looksLikeAccountNumber('··1234'))
check('a server label with a masked number is ignored', accountName('schwab_taxable', 'Schwab ··469') === 'Schwab Individual')
check('a digit-free server label wins', accountName('x_acct', 'My Account') === 'My Account')
check('unknown key is title-cased', accountName('fidelity_roth_ira') === 'Fidelity Roth IRA')
check('empty → unlabelled', accountName('') === UNLABELLED && rowAccountName({}) === UNLABELLED)
check('row with account_id', rowAccountName({ account_id: 'schwab_rollover_ira' }) === 'Schwab Rollover IRA')
check('row with account', rowAccountName({ account: 'schwab_taxable' }) === 'Schwab Individual')

// SPCX in two accounts (live book 2026-10-23: 200 sh Schwab Individual + 700 sh Schwab Rollover IRA)
const rows = [
  { symbol: 'SPCX', account: 'schwab_rollover_ira', day_change: 1488 },
  { symbol: 'SCHD', account: 'schwab_rollover_ira', day_change: -850 },
  { symbol: 'SPCX', account: 'schwab_taxable', day_change: 507 },
  { symbol: 'XLB', account: 'schwab_rollover_ira', day_change: -141 },
]
const groups = groupBySymbol(rows, r => r.symbol)
const spcx = groups.find(g => g.sym === 'SPCX')!
check('SPCX grouped with two labelled parts', spcx.multi && spcx.parts.length === 2)
check('SPCX parts keep both names', spcx.parts.map(p => p.label).join('|') === 'Schwab Rollover IRA|Schwab Individual')
check('single-account symbol not multi', groups.find(g => g.sym === 'SCHD')!.multi === false)
check('multiAccountSymbols finds SPCX only', [...multiAccountSymbols(rows).keys()].join() === 'SPCX')
check('badge text', accountsBadge(2) === '2 accounts' && accountsBadge(1) === '1 account')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
