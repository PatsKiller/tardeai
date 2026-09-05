// Pure-logic tests for setupRunSummary.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/setupRunSummary.test.ts
//
// Proves the client re-derives GO+WAIT+NOGO == classified_count and
// classified+excluded+unclassified == scanned_count on every render, never
// trusting the wire's `count_integrity` string. A reconciliation failure
// renders PARTIAL / COUNT_MISMATCH / DATA_UNAVAILABLE, never an
// authoritative-looking number.
import {
  setupIntegrity,
  renderSetupCounts,
  RECONCILED,
  COUNT_MISMATCH,
  PARTIAL,
  DATA_UNAVAILABLE,
  type SetupRunSummary,
} from './setupRunSummary.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// A fully-reconciled run: 2 GO + 1 WAIT + 24 NOGO = 27 classified,
// 27 + 3 excluded + 2 unclassified = 32 scanned.
function good(): SetupRunSummary {
  return {
    contract_version: 'SetupRunSummary@v1',
    run_id: 'R-2026-09-03',
    run_timestamp: '2026-09-03T14:30:00Z',
    scanned_count: 32,
    classified_count: 27,
    go_count: 2,
    wait_count: 1,
    nogo_count: 24,
    excluded_count: 3,
    unclassified_count: 2,
    count_integrity: 'RECONCILED',
  }
}

// ── reconciliation ───────────────────────────────────────────────────────────
{
  check('null summary → DATA_UNAVAILABLE', setupIntegrity(null) === DATA_UNAVAILABLE)
  check('undefined summary → DATA_UNAVAILABLE', setupIntegrity(undefined) === DATA_UNAVAILABLE)

  check('fully reconciled summary → RECONCILED', setupIntegrity(good()) === RECONCILED)

  // Negative control: GO+WAIT+NOGO != classified_count is caught regardless of
  // what count_integrity claims.
  const brokenTriple: SetupRunSummary = { ...good(), go_count: 3, count_integrity: 'RECONCILED' }
  check('GO+WAIT+NOGO != classified → COUNT_MISMATCH even if wire says RECONCILED',
    setupIntegrity(brokenTriple) === COUNT_MISMATCH)

  // Negative control: classified+excluded+unclassified != scanned_count.
  const brokenScan: SetupRunSummary = { ...good(), excluded_count: 0 }
  check('classified+excluded+unclassified != scanned → COUNT_MISMATCH',
    setupIntegrity(brokenScan) === COUNT_MISMATCH)

  // Missing classified_count: cannot prove the partition → PARTIAL (or the
  // residual server verdict), never RECONCILED.
  const noClassified: SetupRunSummary = { ...good(), classified_count: null }
  check('missing classified_count is never RECONCILED',
    setupIntegrity(noClassified) !== RECONCILED)
  check('missing classified_count surfaces a residual verdict',
    setupIntegrity({ ...noClassified, count_integrity: 'PARTIAL' }) === PARTIAL)

  // Missing scanned_count: the population cannot be reconciled → DATA_UNAVAILABLE.
  const noScanned: SetupRunSummary = { ...good(), scanned_count: null }
  check('missing scanned_count → DATA_UNAVAILABLE', setupIntegrity(noScanned) === DATA_UNAVAILABLE)

  // A residual server verdict (two scanned contracts disagreeing) survives the
  // count-level reconciliation and is surfaced, not hidden.
  const residual: SetupRunSummary = { ...good(), count_integrity: 'PARTIAL' }
  check('residual server verdict is surfaced', setupIntegrity(residual) === PARTIAL)
}

// ── rendering ────────────────────────────────────────────────────────────────
{
  const r = renderSetupCounts(good(), {})
  check('counts partition the three labels',
    r.counts === '2 GO · 1 WAIT · 24 NOGO')
  // This expected '27 classified / 32 scanned · 3 excluded' against a fixture
  // carrying unclassified_count: 2 -- the assertion encoded the very omission
  // the live header shipped, where 12 MANUAL_REVIEW rows vanished out of
  // "48 classified / 60 scanned / 0 excluded". Every non-zero class is named.
  check('population names every non-zero class, omitting none',
    r.population === '27 classified / 32 scanned · 3 excluded · 2 unclassified')
  check('a fully accounted run shows no UNACCOUNTED marker',
    !r.population.includes('UNACCOUNTED') && r.unaccounted === 0)
  check('reconciled render is not degraded', r.degraded === false)
  check('go>0 marks the strip green', r.goPositive === true)
  check('run id is carried', r.runId === 'R-2026-09-03')
  check('run timestamp is carried', r.runTimestamp === '2026-09-03T14:30:00Z')
}

// ── negative control: a mismatched run must render degraded, never a clean number
{
  const bad = renderSetupCounts({ ...good(), go_count: 3 }, {})
  check('mismatched run renders degraded', bad.degraded === true)
  check('mismatched run carries the integrity verdict', bad.integrity === COUNT_MISMATCH)
  // goPositive only means "go > 0"; the amber override is `degraded`, and a
  // mismatched run must be degraded so the strip can never light green on it.
  check('mismatched run is degraded first, so go>0 cannot light green',
    bad.degraded === true && bad.goPositive === true)
}

// ── no-data and stale rendering ──────────────────────────────────────────────
{
  const none = renderSetupCounts(null, {})
  check('no summary renders an explicit pre-run label', none.counts === '— before first run')
  check('no summary has no population', none.population === '')
  check('no summary is degraded', none.degraded === true)

  const stale = renderSetupCounts(good(), { stale: true, staleLabel: 'STALE · 2026-09-02' })
  check('stale render uses the stale label verbatim', stale.counts === 'STALE · 2026-09-02')
  check('stale render is degraded', stale.degraded === true)
  check('stale render is never goPositive', stale.goPositive === false)

  // GO == 0 must never light the strip green.
  const zeroGo = renderSetupCounts({ ...good(), go_count: 0, wait_count: 3 }, {})
  check('zero-GO run is not goPositive', zeroGo.goPositive === false)
}

console.log(`\nsetupRunSummary: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

// ── the operator's 2026-09-04 run, rendered ──────────────────────────────────
// 48 classified / 60 scanned / 0 excluded left 12 rows with no name on screen.
{
  const captured: SetupRunSummary = {
    contract_version: 'SetupRunSummary@v1',
    run_id: '2026-09-04::0900',
    run_label: '0900',
    run_date: '2026-09-04',
    run_timestamp: '2026-09-04T09:52:47',
    scanned_count: 60,
    classified_count: 48,
    go_count: 0,
    wait_count: 1,
    nogo_count: 47,
    review_count: 12,
    excluded_count: 0,
    error_count: 0,
    unclassified_count: 0,
    accounted_count: 60,
    unaccounted_count: 0,
    count_integrity: 'RECONCILED',
  }
  const r = renderSetupCounts(captured, {})
  check('the 12 escalations are named on the tile',
    r.population.includes('12 manual review'))
  check('the escalations are not folded into NOGO',
    r.counts === '0 GO · 1 WAIT · 47 NOGO')
  check('nothing is left for the reader to subtract',
    r.unaccounted === 0 && !r.population.includes('UNACCOUNTED'))
  check('a fully accounted, reconciled run is not degraded', r.degraded === false)
  check('the run id survives to the tile', r.runId === '2026-09-04::0900')

  // Negative control: drop the review class back into the void and the renderer
  // must SAY so rather than quietly printing 48 of 60 again.
  const unnamed: SetupRunSummary = {
    ...captured, review_count: 0, accounted_count: 48, unaccounted_count: 12,
  }
  const u = renderSetupCounts(unnamed, {})
  check('unaccounted rows are stated, never silently dropped',
    u.population.includes('12 UNACCOUNTED'))
  check('an unaccounted run is degraded regardless of the wire verdict',
    u.degraded === true)
  check('unaccounted count is exposed to callers', u.unaccounted === 12)
}

// ── run health is not count reconciliation (2026-09-05) ──────────────────────
// The live 2026-09-04::1730 run was RECONCILED and RUN_UNDERFILLED at once:
// 21 = 12 classified + 9 manual review, nothing unaccounted, while the run had
// scanned 21 symbols against a health floor of 40. The tile painted green
// because only reconciliation was rendered.
{
  const underfilled: SetupRunSummary = {
    contract_version: 'SetupRunSummary@v1',
    run_id: '2026-09-04::1730', run_label: '1730', run_date: '2026-09-04',
    run_timestamp: '2026-09-04T21:22:44',
    scanned_count: 21, classified_count: 12,
    go_count: 1, wait_count: 1, nogo_count: 10,
    review_count: 9, excluded_count: 0, error_count: 0, unclassified_count: 0,
    accounted_count: 21, unaccounted_count: 0,
    count_integrity: 'RECONCILED',
    freshness_status: 'RUN_UNDERFILLED', quality: 'DEGRADED',
  }
  const r = renderSetupCounts(underfilled, {})
  check('a reconciled run can still be an unhealthy one', r.integrity === RECONCILED && r.healthDegraded === true)
  check('reconciliation stays false-negative-free: degraded is about the tally only', r.degraded === false)
  check('the raw producer status is carried, not re-derived', r.runHealthStatus === 'RUN_UNDERFILLED')
  check('the health tier matches the classifier the Trading panel uses', r.runHealth === 'underfilled')

  // Negative control the other way: a healthy run whose tally does NOT add up
  // must still be degraded. Neither signal may mask the other.
  const mismatched: SetupRunSummary = {
    ...underfilled, freshness_status: 'RUN_HEALTHY', quality: 'OK',
    review_count: 0, accounted_count: 12, unaccounted_count: 9,
  }
  const m = renderSetupCounts(mismatched, {})
  check('a healthy run with an unaccounted tally is still degraded', m.degraded === true)
  check('a healthy run is not health-degraded', m.healthDegraded === false)
  check('the two verdicts are independent', m.degraded !== m.healthDegraded)

  // Health must survive the early-return branches, or a stale surface silently
  // forgets that the last run it saw was underfilled.
  const staleRender = renderSetupCounts(underfilled, { stale: true, staleLabel: 'STALE' })
  check('a stale surface still reports the run health it last saw',
    staleRender.healthDegraded === true && staleRender.runHealthStatus === 'RUN_UNDERFILLED')

  const missing = renderSetupCounts(null, {})
  check('an absent summary reports unknown health, never healthy',
    missing.runHealth === 'unknown' && missing.healthDegraded === false && missing.runHealthStatus === null)
}

