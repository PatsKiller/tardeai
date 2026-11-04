// FQ-036 wiring: the health score and the Unprotected gauge must explain their own scope.
//
// Measured live 2026-11-04 11:29 ET: risk_protection = 85 (green at the 85 threshold) while 19 of 29 positions had
// no stop, so the page showed a green Risk protection card beside a red Unprotected gauge with nothing saying why
// both can be true. The words that fix that are static JSX, so — as with FQ-035 — the call site needs a guard or a
// later edit can drop them with every unit test green.
//
//   node --experimental-strip-types src/lib/riskScoreScope.wiring.test.mjs
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const strip = readFileSync(join(HERE, '../components/risk/RiskHealthStrip.tsx'), 'utf8')
const hub = readFileSync(join(HERE, '../pages/HealthHub.tsx'), 'utf8')
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// The scope line is rendered, is findable by its test id, and says the two things that resolve the ambiguity.
check(/data-testid="risk-health-scope"/.test(strip), 'the scope line is not rendered under the gauges')
check(/does not count whether a\s+position has a stop/i.test(strip) || /does not count whether a position has a stop/i.test(strip),
  'the scope line does not say the score ignores stop coverage')
check(/Unprotected/i.test(strip) && /not part of the score/i.test(strip),
  'the scope line does not place Unprotected outside the score')

// The category help used to claim the opposite; it must not come back.
check(!/Unprotected open positions, stops in alert state/.test(hub),
  'the Risk Protection help still claims it counts unprotected positions')
check(/Whether each position has a stop is not scored here/.test(hub),
  'the Risk Protection help does not say stop coverage is not scored')

// Mobile: the gauges must not force a min-width the phone cannot honour (the sibling FQ-037 fix).
check(/minmax\(min\(120px, 100%\), 1fr\)/.test(strip), 'the gauge grid lost its phone-safe minimum')

if (failed) { console.error(`riskScoreScope wiring: ${failed} failure(s)`); process.exit(1) }
console.log('riskScoreScope wiring: ok')
