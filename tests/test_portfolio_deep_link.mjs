/**
 * Portfolio deep-link contract (WP-A) — deterministic Node checks.
 * Run: node tests/test_portfolio_deep_link.mjs
 */
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'apps/command-center-v3/src/lib/portfolioDeepLink.ts')
const HUB = join(ROOT, 'apps/command-center-v3/src/pages/PortfolioHub.tsx')
const HEALTH = join(ROOT, 'apps/command-center-v3/src/components/PortfolioDeskHealth.tsx')

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg)
    process.exitCode = 1
  } else {
    console.log('ok:', msg)
  }
}

// Static contract checks (no TS runtime required)
const src = readFileSync(SRC, 'utf8')
const hub = readFileSync(HUB, 'utf8')
const health = readFileSync(HEALTH, 'utf8')

assert(src.includes('parsePortfolioDeepLink'), 'parser export present')
assert(src.includes('pickHoldingForDeepLink'), 'picker export present')
assert(src.includes('symbol'), 'symbol param in contract')
assert(src.includes('drawerTab'), 'drawerTab param in contract')
assert(hub.includes('parsePortfolioDeepLink'), 'PortfolioHub consumes deep-link parser')
assert(hub.includes('pickHoldingForDeepLink'), 'PortfolioHub focuses deep-linked holding')
assert(hub.includes('PortfolioDeskHealth'), 'desk health strip mounted')
assert(hub.includes('selectSig'), 'signal filter URL-synced via selectSig')
assert(hub.includes('<Link to="/rotation"'), 'rotation uses React Router Link')
assert(hub.includes('isCashHolding'), 'cash boundary at row context')
assert(hub.includes("fv: cash ? undefined"), 'cash skips Finviz strip join')
assert(hub.includes('Advanced / legacy'), 'Fidelity sync under Advanced disclosure')
assert(health.includes('portfolio-desk-health'), 'desk health testid')
assert(health.includes('desk-health-reload-ui'), 'reload UI control')
assert(health.includes('build-meta.json'), 'build-meta provenance fetch')
assert(health.includes('Broker stops'), 'stop-truth SLA chip text')

// Inline mini-tests of pure logic (reimplemented mirror of TS for node)
function resolveTab(raw) {
  const TABS = ['Holdings', 'Allocation', 'Look-through', 'Returns', 'Dividends', 'Forecast', 'Tax', 'Redeploy', 'Stop Management']
  if (!raw) return 'Holdings'
  const t = String(raw).trim().replace(/\+/g, ' ')
  if (TABS.includes(t)) return t
  return TABS.find(x => x.toLowerCase() === t.toLowerCase()) || 'Holdings'
}
function pick(holdings, symbol, account) {
  if (!symbol) return null
  const matches = holdings.filter(h => String(h.symbol).toUpperCase() === symbol.toUpperCase())
  if (account) {
    const ex = matches.find(h => h.account === account)
    if (ex) return ex
  }
  const nonCash = matches.filter(h => !h.is_cash)
  const pool = nonCash.length ? nonCash : matches
  return pool.sort((a, b) => (b.market_value || 0) - (a.market_value || 0))[0] || null
}

assert(resolveTab('Stop Management') === 'Stop Management', 'resolve Stop Management tab')
assert(resolveTab('stop management') === 'Stop Management', 'case-insensitive tab')
assert(resolveTab(null) === 'Holdings', 'default Holdings')

const sample = [
  { symbol: 'V', account: 'schwab_rollover_ira', market_value: 70_000, is_cash: false },
  { symbol: 'V', account: 'schwab_roth', market_value: 40_000, is_cash: false },
  { symbol: 'CASH', account: 'schwab_rollover_ira', market_value: 500_000, is_cash: true },
]
const vRoth = pick(sample, 'V', 'schwab_roth')
assert(vRoth?.account === 'schwab_roth', 'exact account wins for V')
const vAny = pick(sample, 'V', null)
assert(vAny?.account === 'schwab_rollover_ira', 'largest MV when account omitted')
const cash = pick(sample, 'CASH', null)
assert(cash?.is_cash === true, 'cash pick still works when only cash matches')

if (process.exitCode) {
  console.error('\nportfolio deep-link checks failed')
  process.exit(1)
}
console.log('\nAll portfolio deep-link / desk-health static checks passed')
