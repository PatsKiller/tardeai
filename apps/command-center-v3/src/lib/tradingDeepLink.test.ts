// Pure-logic tests for tradingDeepLink.ts. Runnable with Node 22 type-stripping:
//   node apps/command-center-v3/src/lib/tradingDeepLink.test.ts
import {
  legacyTradingRedirect,
  parseTradingDeepLink,
  resolveTradingTab,
  tradingTabSearchParams,
  TRADING_TABS,
} from './tradingDeepLink.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('tradingDeepLink')

check('default tab Trade AI', resolveTradingTab(null) === 'Trade AI')
check('alias Manual ToS → Proposals', resolveTradingTab('Manual ToS') === 'Proposals')
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
  const prev = new URLSearchParams('tab=Proposals&proposal=1&symbol=TSLA&pq_source=pullback_macd&pq_held=1')
  const next = tradingTabSearchParams(prev, 'Open Trades')
  check('tab synced', next.get('tab') === 'Open Trades')
  check('proposal cleared off Proposals', next.get('proposal') === null)
  check('symbol kept for Open Trades', next.get('symbol') === 'TSLA')
  check('pq_* cleared leaving Proposals', next.get('pq_source') === null && next.get('pq_held') === null)
}

{
  const p = parseTradingDeepLink(new URLSearchParams('tab=Proposals&pq_kind=protection&pq_rr=live_2&pq_view=expired&pq_held=1&pq_page=2'))
  check('pq kind', p.pq.kind === 'protection')
  check('pq rr', p.pq.rr === 'live_2')
  check('pq view expired', p.pq.view === 'expired')
  check('pq held', p.pq.held === true)
  check('pq page', p.pq.page === 2)
}

{
  const prev = new URLSearchParams('tab=Broker Orders&intent=i1')
  const next = tradingTabSearchParams(prev, 'Trade AI')
  check('intent cleared', next.get('intent') === null)
}

// ── Tabs 8 → 4 (operator-approved 2026-10-22) ──
check('four visible tabs', TRADING_TABS.join('|') === 'Trade AI|Options|Open Trades|Proposals')
{
  const d = parseTradingDeepLink(new URLSearchParams('tab=Entry+Desk&symbol=abc'))
  check('Entry Desk → Proposals', d.tab === 'Proposals')
  check('Entry Desk → section path-a', d.section === 'path-a')
  check('Entry Desk keeps symbol', d.symbol === 'ABC')
}
{
  const d = parseTradingDeepLink(new URLSearchParams('tab=Manual%20ToS'))
  check('Manual%20ToS → Proposals path-a', d.tab === 'Proposals' && d.section === 'path-a')
}
{
  const d = parseTradingDeepLink(new URLSearchParams('tab=Broker+Recon'))
  check('Broker Recon → Open Trades', d.tab === 'Open Trades')
  check('Broker Recon → recon drawer', d.drawer === 'recon')
}
{
  const d = parseTradingDeepLink(new URLSearchParams('tab=Schwab+Accounts'))
  check('Schwab Accounts → Broker Orders desk', d.tab === 'Broker Orders' && d.section === 'schwab-accounts')
}
{
  const d = parseTradingDeepLink(new URLSearchParams('tab=Broker%20Orders&intent=abc'))
  check('Broker Orders desk still reachable from approval links', d.tab === 'Broker Orders' && d.intent === 'abc')
}
check('Scalp leaves the hub with its symbol', legacyTradingRedirect(new URLSearchParams('tab=Scalp&symbol=adv')) === '/active-trader?tab=Scalp&symbol=ADV')
check('Scalp root', legacyTradingRedirect(new URLSearchParams('tab=Scalp')) === '/active-trader?tab=Scalp')
check('ATM Controls → System Broker Access', legacyTradingRedirect(new URLSearchParams('tab=ATM+Controls')) === '/system/broker-access#automation-controls')
check('Execution → Journal', legacyTradingRedirect(new URLSearchParams('tab=Execution')) === '/journal')
check('in-hub tabs never redirect', legacyTradingRedirect(new URLSearchParams('tab=Open+Trades')) === null
  && legacyTradingRedirect(new URLSearchParams('tab=Entry+Desk')) === null
  && legacyTradingRedirect(new URLSearchParams('')) === null)
check('unknown tab → Trade AI', resolveTradingTab('Nope') === 'Trade AI')
{
  const next = tradingTabSearchParams(new URLSearchParams('tab=Proposals&section=path-a&symbol=X'), 'Open Trades')
  check('section dropped leaving Proposals', next.get('section') === null && next.get('symbol') === 'X')
  const back = tradingTabSearchParams(new URLSearchParams('tab=Open+Trades&drawer=recon'), 'Trade AI')
  check('drawer dropped leaving Open Trades', back.get('drawer') === null)
}
{
  // Options lifecycle desk (2026-10-22): symbol filters the desk; the classic view param stays on Options only.
  const opt = tradingTabSearchParams(new URLSearchParams('tab=Open+Trades&symbol=SPCX'), 'Options')
  check('symbol kept for the Options desk', opt.get('symbol') === 'SPCX')
  const away = tradingTabSearchParams(new URLSearchParams('tab=Options&view=classic&otab=Lifecycle'), 'Open Trades')
  check('classic view + otab dropped leaving Options', away.get('view') === null && away.get('otab') === null)
  const stay = tradingTabSearchParams(new URLSearchParams('tab=Options&view=classic&otab=Lifecycle'), 'Options')
  check('classic view kept on Options', stay.get('view') === 'classic' && stay.get('otab') === 'Lifecycle')
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
