// OBS-B2-4e (Sprint 8H-2): a Portfolio ?tab= deep link must open the view it names. /v3/portfolio forwards legacy
// ?tab= links to /v3/portfolio-classic unchanged; the classic page matched case-sensitively, so ?tab=returns opened
// Holdings. This pins the resolver, the forward and the classic page's use of the resolver.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { PORTFOLIO_TABS, resolvePortfolioTab, resolvePortfolioTabParam } from './portfolioTabs.ts'
import { legacyPortfolioRedirect } from './portfolioDeepLink.ts'

const src = dirname(fileURLToPath(import.meta.url))

// 1. Exact canonical names resolve to themselves (the links the app emits today).
for (const t of PORTFOLIO_TABS) assert.equal(resolvePortfolioTab(t), t)

// 2. Case, space, hyphen, underscore and URL-decoded variants resolve to the named view, not Holdings.
const cases: [string, string][] = [
  ['returns', 'Returns'], ['RETURNS', 'Returns'], ['look-through', 'Look-through'], ['lookthrough', 'Look-through'],
  ['Look_Through', 'Look-through'], ['look through', 'Look-through'], ['stop management', 'Stop Management'],
  ['Stop_Management', 'Stop Management'], ['stop-management', 'Stop Management'], ['allocation', 'Allocation'],
  ['tax', 'Tax'], ['  Dividends ', 'Dividends'], [decodeURIComponent('Stop%20Management'), 'Stop Management'],
]
for (const [raw, want] of cases) {
  const r = resolvePortfolioTabParam(raw)
  assert.deepEqual(r, { tab: want, known: true }, `?tab=${raw}`)
}

// 3. Explicit aliases.
assert.equal(resolvePortfolioTab('stops'), 'Stop Management')
assert.equal(resolvePortfolioTab('lookthru'), 'Look-through')

// 4. No tab is Holdings and known; an unrecognised tab is Holdings but NOT known (the page says so).
assert.deepEqual(resolvePortfolioTabParam(null), { tab: 'Holdings', known: true })
assert.deepEqual(resolvePortfolioTabParam(''), { tab: 'Holdings', known: true })
assert.deepEqual(resolvePortfolioTabParam('nonsense'), { tab: 'Holdings', known: false })
// Mutant guard: a resolver that only lower-cases (no separator folding) fails here.
assert.equal(resolvePortfolioTab('LOOK_THROUGH'), 'Look-through')

// 5. Route: /v3/portfolio forwards ?tab= to /v3/portfolio-classic with the search string intact. Since OBS-P2 the
// forward is the tested lib/portfolioDeepLink contract, so pin its behaviour for ?tab= and the page's use of it.
assert.equal(legacyPortfolioRedirect('?tab=returns'), '/portfolio-classic?tab=returns')
assert.equal(legacyPortfolioRedirect('?tab=Stop%20Management&symbol=X'), '/portfolio-classic?tab=Stop%20Management&symbol=X')
assert.equal(legacyPortfolioRedirect('?symbol=X'), null)
const v002 = readFileSync(join(src, '../pages/PortfolioV002.tsx'), 'utf8')
assert.match(v002, /const legacyTo = legacyPortfolioRedirect\(location\.search\)/)
assert.match(v002, /if \(legacyTo\) return <Navigate to=\{legacyTo\} replace \/>/)

// 6. The classic page resolves with the shared resolver and states an unknown tab instead of silently swapping it.
const hub = readFileSync(join(src, '../pages/PortfolioHub.tsx'), 'utf8')
assert.match(hub, /const resolveTab = resolvePortfolioTab\n/)
assert.match(hub, /const TABS = PORTFOLIO_TABS\n/)
assert.ok(!/\(TABS as readonly string\[\]\)\.includes\(t\)/.test(hub), 'the exact-case matcher is gone')
assert.match(hub, /data-testid="portfolio-tab-unknown"/)

console.log('portfolioTabs: 6 sections passed')
