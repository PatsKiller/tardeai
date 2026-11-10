// LQ-20261107-1837 wiring: the CALL SITES, not the helpers. `metricAuthority.test.ts` pins what the module
// answers; this pins that every surface asks it, because a helper nobody calls fixes nothing. Each check
// corresponds to one row of the audit's G7 table and would fail on the tree before this fix.
//
// Plain .mjs on purpose: the app's tsconfig has no Node types, so reading a source file from a .ts test
// fails tsc (the same reason healthOperatorLanguage.wiring.test.mjs is .mjs).
//
//   node --experimental-strip-types src/lib/metricAuthority.wiring.test.mjs
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../../..')
const read = rel => readFileSync(join(ROOT, rel), 'utf8')
const app = rel => read(`apps/command-center-v3/src/${rel}`)
/** Comments explain a fix; they must not make a "still does X" check pass. Strip them before asserting. */
const codeOnly = src => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// ── portfolio heat: Home, Health and Risk read positions.portfolio_heat_pct, none recomputes ──────────────
const homeDoNowLib = app('lib/homeDoNow.ts')
check(/heatFact\(pages\)/.test(homeDoNowLib), 'Home does not take heat from cio_truth through heatFact')
const homeDoNow = app('pages/HomeDoNow.tsx')
check(/heatText\(n\.heatPct\)/.test(homeDoNow), 'the Home heat tile does not print through heatText (one precision)')
const w7 = app('components/W7RiskPanels.tsx')
check(/heatWhy\(summary\.portfolio_heat_pct/.test(w7), 'the Risk exposure KPI does not print heat through heatWhy')
check(!/pctWhy\(summary\.portfolio_heat_pct/.test(w7), 'the Risk exposure KPI still prints heat at its own precision')
const strip = app('components/reports/MorningCommandStrip.tsx')
check(/heatText\(opts\.heatPct\)/.test(strip), 'the morning strip still formats heat itself')

// ── unprotected positions: one count, no re-count of positions[] ─────────────────────────────────────────
const healthHub = app('pages/HealthHub.tsx')
check(/unprotectedFromRisk\(riskData\)\.count/.test(healthHub), 'Health does not read stop_health.unprotected_count')
check(!/has_stop/.test(codeOnly(healthHub)), 'Health still re-counts positions[].has_stop (the second calculation)')
const reportsHub = app('pages/ReportsHub.tsx')
check(/unprotectedFromRisk\(risk\)\.count/.test(reportsHub), 'Reports does not read stop_health.unprotected_count')
check(!/!p\.stop_price && !p\.triggered/.test(reportsHub), 'Reports still re-counts positions without a stop')
check(/unprotectedFact\(data\)/.test(w7), 'the Risk exposure KPI does not read stops.unprotected_count')
check(!/n\('none'\) \+ n\('planned'\)/.test(w7), 'the Risk exposure KPI still re-adds none + planned')

// ── market-risk score: one field, one precision, and no hardcoded tier ───────────────────────────────────
const marketRisk = codeOnly(app('lib/marketRisk.ts'))
check(/scoreText\(mr\.score\)/.test(marketRisk), 'the compact fact line does not print the score through scoreText')
check(!/String\(Math\.round\(mr\.score\)\)/.test(marketRisk), 'the summary still rounds the score on its own')
check(/score: mr\.score != null \? scoreText\(mr\.score\) : null/.test(marketRisk), 'the summary model does not take the shared precision')
const banner = app('components/home/MarketRiskBanner.tsx')
check(!/Math\.round\(mr\.score\)/.test(codeOnly(banner)), 'the banner still rounds the score for display')
check(/scoreText\(mr\.score\)/.test(banner), 'the banner does not print the score through scoreText')
const summary = app('components/home/MarketRiskSummary.tsx')
check(!/>YELLOW</.test(summary), 'the YELLOW card still hardcodes its tier instead of the engine field')
check(/\{mr\.tier\}/.test(summary), 'the YELLOW card does not render the engine tier')
const desk = codeOnly(read('scripts/lib/desks_a.py'))
// The authority is the MarketRiskSnapshot@v1; the defense projection embeds a frozen copy of tier/score.
check(/tier_label = mr_snap\.get\("tier"\) or etier\.get\("tier"\)/.test(desk), 'the Defense desk still prefers the frozen projection tier')
check(/tier_score = mr_snap\.get\("score"\) if mr_snap\.get\("score"\) is not None else etier\.get\("score"\)/.test(desk),
  'the Defense desk still prefers the frozen projection score')
check(/f"\{tier_label\} \{tier_score:\.1f\}"/.test(desk), 'the Defense desk does not print the score at the one shared precision')
const defenseDesk = app('pages/desks/DefenseDesk.tsx')
check(/marketRiskFact\(marketRisk\.data\)/.test(defenseDesk), 'the Defense page does not pass the live market-risk fact to the engine view')
check(/unprotectedFact\(cio\.data\)/.test(defenseDesk), 'the Defense page does not pass the live unprotected fact to the engine view')
const engine = app('components/defense/engine/DefenseEngine.tsx')
check(/scoreText\(score\)/.test(engine), 'the Defense engine hero does not print the score through scoreText')

if (failed) { console.error(`metricAuthority wiring: ${failed} failure(s)`); process.exit(1) }
console.log('metricAuthority wiring: ok')
