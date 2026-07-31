// Pure-logic tests for tradingDeepLink.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/tradingDeepLink.test.ts
import {
  parseTradingDeepLink,
  resolveTradingTab,
  tradingTabSearchParams,
} from './tradingDeepLink.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('tradingDeepLink')

check('default tab Trade AI', resolveTradingTab(null) === 'Trade AI')
check('alias Manual ToS', resolveTradingTab('Manual ToS') === 'Entry Desk')
check('alias Broker Proposals', resolveTradingTab('Broker Proposals') === 'Proposals')
check('plus encoded Open+Trades', resolveTradingTab('Open+Trades') === 'Open Trades')
check('proposal without tab → Proposals', resolveTradingTab(null, true) === 'Proposals')

{
  const p = new URLSearchParams('tab=Broker+Orders&intent=abc')
  const d = parseTradingDeepLink(p)
  check('parse Broker Orders', d.tab === 'Broker Orders')
  check('parse intent', d.intent === 'abc')
}

{
  const p = new URLSearchParams('proposal=99&symbol=xlv')
  const d = parseTradingDeepLink(p)
  check('proposal implies Proposals', d.tab === 'Proposals')
  check('symbol upper', d.symbol === 'XLV')
  check('proposal id', d.proposal === '99')
}

{
  const p = new URLSearchParams('intent=xyz')
  const d = parseTradingDeepLink(p)
  check('intent alone → Broker Orders', d.tab === 'Broker Orders')
}

{
  const prev = new URLSearchParams('tab=Proposals&proposal=1&symbol=TSLA')
  const next = tradingTabSearchParams(prev, 'Open Trades')
  check('tab synced', next.get('tab') === 'Open Trades')
  check('proposal cleared off Proposals', next.get('proposal') === null)
  check('symbol kept for Open Trades', next.get('symbol') === 'TSLA')
}

{
  const prev = new URLSearchParams('tab=Broker Orders&intent=i1')
  const next = tradingTabSearchParams(prev, 'Trade AI')
  check('intent cleared', next.get('intent') === null)
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
