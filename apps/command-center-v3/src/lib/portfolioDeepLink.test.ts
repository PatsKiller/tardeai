// Portfolio hub deep links. Synthetic values only.
//   node --experimental-strip-types src/lib/portfolioDeepLink.test.ts
import {
  LEGACY_PORTFOLIO_PARAMS, PORTFOLIO_CLASSIC_PATH, PORTFOLIO_TABS, legacyPortfolioRedirect, portfolioTabRedirect,
  resolvePortfolioTab,
} from './portfolioDeepLink.ts'
declare const process: {
  exit(code?: number): never
  getBuiltinModule(id: 'node:fs'): { readFileSync(p: URL, enc: 'utf8'): string }
}
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
// ── OBS-P2a / OBS-P2b: the legacy hub hrefs ───────────────────────────────────────────────────────────
// Live surfaces still emit classic hrefs. Allocation and the Look-through desk both emit
// `/portfolio?tab=Look-through`; Home and HomeDoNow emit `/portfolio?tab=Returns`. v002 owns that path and
// implements NEITHER tab, so without this redirect the click renders the Holdings page under a tab label it
// never honoured — a page that contradicts the link that opened it. The redirect must carry the WHOLE query
// string to the classic hub, which still implements every tab. Source: FINDINGS.csv OBS-P2a / OBS-P2b.

t('P2a: the Allocation/Look-through legacy href lands on the classic hub with its tab', () => {
  eq(legacyPortfolioRedirect('?tab=Look-through'), '/portfolio-classic?tab=Look-through', 'P2a')
})
t('P2b: the Returns legacy href lands on the classic hub with its tab', () => {
  eq(legacyPortfolioRedirect('?tab=Returns'), '/portfolio-classic?tab=Returns', 'P2b')
})
t('the legacy handoff keeps every param, in order, encoded as it arrived', () => {
  eq(legacyPortfolioRedirect('?tab=Stop%20Management&symbol=NVDA'), '/portfolio-classic?tab=Stop%20Management&symbol=NVDA')
  eq(legacyPortfolioRedirect('?acct=schwab_roth&sig=Hold'), '/portfolio-classic?acct=schwab_roth&sig=Hold')
})
t('each classic-only param redirects on its own (tab/drawer/drawerTab/sig/acct)', () => {
  eq([...LEGACY_PORTFOLIO_PARAMS], ['tab', 'drawer', 'drawerTab', 'sig', 'acct'])
  for (const k of LEGACY_PORTFOLIO_PARAMS) eq(legacyPortfolioRedirect(`?${k}=x`), `/portfolio-classic?${k}=x`, k)
})
t('v002-owned links are NOT redirected (symbol focus, bare path, unknown params)', () => {
  eq(legacyPortfolioRedirect('?symbol=NVDA'), null)
  eq(legacyPortfolioRedirect(''), null)
  eq(legacyPortfolioRedirect('?'), null)
  eq(legacyPortfolioRedirect(null), null)
  eq(legacyPortfolioRedirect(undefined), null)
  eq(legacyPortfolioRedirect('?foo=1'), null)
})
t('the redirect target is a path App.tsx actually declares', () => {
  eq(PORTFOLIO_CLASSIC_PATH, '/portfolio-classic')
  const app = process.getBuiltinModule('node:fs').readFileSync(new URL('../App.tsx', import.meta.url), 'utf8')
  eq(app.includes(`path="${PORTFOLIO_CLASSIC_PATH.slice(1)}"`), true, 'classic route declared in App.tsx')
})
console.log(`portfolioDeepLink: ${n} passed`)
