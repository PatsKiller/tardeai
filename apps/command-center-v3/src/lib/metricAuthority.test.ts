/**
 * LQ-20261107-1837 (C4): one authority per metric.
 *
 * These tests pin the authority module that every CC v3 surface now reads the three trust-debt numbers through:
 *   market-risk score      MarketRiskSnapshot@v1   /api/v2/market-risk/latest
 *   portfolio heat         cio_truth.resolve       /api/v2/cio/pages  positions.portfolio_heat_pct
 *   unprotected positions  cio_truth.resolve       /api/v2/cio/pages  stops.unprotected_count
 *
 * Synthetic fixtures only; nothing here calls a route. The behaviour these pin is the divergence the audit
 * measured: two surfaces printing the same name from two calculations, and one metric printed at two precisions.
 */
import {
  CIO_PAGES_API, MARKET_RISK_API, METRIC_AUTHORITY, heatFact, heatText, marketRiskFact, scoreText,
  unprotectedFact, unprotectedFromRisk,
} from './metricAuthority.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}

// The audit's live shape: the engine snapshot carried 44.1813, Home's card printed 44.2 from it, the banner printed 44.
check('market-risk score: ONE precision, so 44.1813 is 44.2 on every surface', scoreText(44.1813) === '44.2', scoreText(44.1813))
check('market-risk score: a whole score still keeps its decimal', scoreText(44) === '44.0', scoreText(44))
check('market-risk score: unmeasured is a dash, never 0', scoreText(null) === '—' && scoreText(undefined) === '—' && scoreText(Number.NaN) === '—')
check('portfolio heat: ONE precision (Risk printed 1.27% where Home and Health printed 1.3%)', heatText(1.2738) === '1.3%', heatText(1.2738))
check('portfolio heat: unmeasured is a dash, never 0.0%', heatText(null) === '—' && heatText(undefined) === '—')

const snapshot = { schema: 'MarketRiskSnapshot@v1', state: 'evaluated', tier: 'yellow', score: 44.1813, as_of: '2026-11-10T20:55:00Z' }
const fact = marketRiskFact(snapshot)
check('market-risk fact reads tier, score and as_of from the snapshot', fact.tier === 'YELLOW' && fact.score === 44.1813 && fact.asOf === '2026-11-10T20:55:00Z')
check('market-risk fact: an absent snapshot says NOT_EVALUATED, never a guess', marketRiskFact(null).tier === 'NOT_EVALUATED' && marketRiskFact(null).score === null)

// cio_truth's positions/stops blocks, at the audit's live shape: heat 1.438, 4 counted unprotected rows.
const cio = {
  positions: { portfolio_heat_pct: 1.438, as_of: '2026-11-10T20:54:00Z', source: 'cio_truth',
    loss_basis: 'loss to observed active stops; unprotected downside is not bounded',
    unprotected_counted_value_usd: 49_089.02, unprotected_value_usd: 49_563.67, unprotected_residual_value_usd: 474.65 },
  stops: { unprotected_count: 4, as_of: '2026-11-10T20:54:00Z', source: 'cio_truth' },
}
const heat = heatFact(cio)
check('heat fact reads positions.portfolio_heat_pct, not a legacy risk_management number',
  heat.pct === 1.438 && heat.asOf === '2026-11-10T20:54:00Z' && heat.basis === 'loss to observed active stops; unprotected downside is not bounded')
const unprot = unprotectedFact(cio)
check('unprotected fact reads stops.unprotected_count', unprot.count === 4, unprot.count)
check('unprotected fact pairs the count with the value over the SAME rows',
  unprot.valueUsd === 49_089.02, unprot.valueUsd)
// The wide total holds the sub-$100 residuals the count excludes; it must never sit beside the counted count.
const noSplit = { positions: { unprotected_value_usd: 120 }, stops: { unprotected_count: 3 } }
check('unprotected fact: an older payload without the split still shows its value', unprotectedFact(noSplit).valueUsd === 120)
const nullSplit = { positions: { unprotected_counted_value_usd: null, unprotected_value_usd: 120 }, stops: { unprotected_count: 3 } }
check('unprotected fact: a counted split that failed to compute never falls back to the wide sum',
  unprotectedFact(nullSplit).valueUsd === null, unprotectedFact(nullSplit).valueUsd)
check('unprotected fact: an absent count is null, never 0', unprotectedFact({}).count === null)

// /api/v2/risk serves the same cio_truth projection under `stop_health`; both routes must resolve the same count.
const risk = { stop_health: { unprotected_count: 4, active_count: 6, pending_count: 2, filled_count: 0 }, truth: { as_of: '2026-11-10T20:54:00Z' } }
const fromRisk = unprotectedFromRisk(risk)
check('the Risk route and the CIO pages route resolve the SAME count', fromRisk.count === unprot.count, `${fromRisk.count} vs ${unprot.count}`)
check('the Risk route carries the projection as_of', fromRisk.asOf === '2026-11-10T20:54:00Z')
check('the Risk route with no stop_health block is unknown, never 0', unprotectedFromRisk({}).count === null)

// The authority table is the one place a reviewer reads the endpoint and field for each number.
check('authority table names the endpoint and field for all three metrics',
  METRIC_AUTHORITY.marketRiskScore.endpoint === MARKET_RISK_API
  && METRIC_AUTHORITY.portfolioHeat.endpoint === CIO_PAGES_API
  && METRIC_AUTHORITY.unprotectedPositions.endpoint === CIO_PAGES_API
  && METRIC_AUTHORITY.portfolioHeat.fields === 'positions.portfolio_heat_pct'
  && METRIC_AUTHORITY.unprotectedPositions.fields === 'stops.unprotected_count')

console.log(`metricAuthority: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
