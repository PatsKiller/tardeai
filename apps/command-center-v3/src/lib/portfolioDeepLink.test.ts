// Portfolio hub deep links. Synthetic values only.
//   node --experimental-strip-types src/lib/portfolioDeepLink.test.ts
import { PORTFOLIO_TABS, portfolioTabRedirect, resolvePortfolioTab } from './portfolioDeepLink.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

t('Redeploy is no longer a hub tab (jobs v002: it is a link to the /redeploy desk)', () => {
  eq((PORTFOLIO_TABS as readonly string[]).includes('Redeploy'), false)
  eq(resolvePortfolioTab('Redeploy'), 'Holdings')
})
t('old ?tab=Redeploy links redirect to the desk, any case', () => {
  eq(portfolioTabRedirect('Redeploy'), '/redeploy')
  eq(portfolioTabRedirect('redeploy'), '/redeploy')
  eq(portfolioTabRedirect(' REDEPLOY '), '/redeploy')
})
t('live tabs and absent params do not redirect', () => {
  eq(portfolioTabRedirect('Holdings'), null)
  eq(portfolioTabRedirect('Stop Management'), null)
  eq(portfolioTabRedirect(null), null)
  eq(portfolioTabRedirect(''), null)
})
t('known tabs still resolve, case-insensitive', () => {
  eq(resolvePortfolioTab('stop management'), 'Stop Management')
  eq(resolvePortfolioTab('Tax'), 'Tax')
  eq(resolvePortfolioTab(undefined), 'Holdings')
})
console.log(`portfolioDeepLink: ${n} passed`)
