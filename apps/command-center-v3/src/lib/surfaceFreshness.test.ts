// Pure-logic tests for surfaceFreshness.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/surfaceFreshness.test.ts
import {
  parseTimestamp,
  tradeAiSurfaceFreshness,
  overviewSurfaceFreshness,
  WI_SYNOPSIS_PROVENANCE,
} from './surfaceFreshness.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const now = new Date('2026-08-31T16:50:00Z')

// ---- parseTimestamp ----
check('ISO Z parses', !!parseTimestamp('2026-08-28T04:06:13.794823Z', now.getTime()))
check('date-only parses', !!parseTimestamp('2026-08-28', now.getTime()))
check('null → null', parseTimestamp(null) == null)
check('garbage → null', parseTimestamp('not-a-date') == null)

// ---- tradeAi: live fresh ----
{
  const f = tradeAiSurfaceFreshness({
    stale: false,
    cached_at: '2026-08-31T16:40:00Z',
    cache_age_sec: 600,
    go_count: 3,
    wait_count: 2,
    avoid_count: 10,
    ticker_count: 15,
    current_run_scanned: 15,
    run_date: '2026-08-31',
  }, now)
  check('fresh scan not stale', f.stale === false)
  check('fresh has no surfaceLabel', f.surfaceLabel == null)
}

// ---- tradeAi: API TTL stale (600s) must NOT paint chrome STALE when data exists ----
{
  const f = tradeAiSurfaceFreshness({
    stale: true, // API warm-cache TTL only (~10m)
    cached_at: '2026-08-31T16:29:00Z',
    cache_age_sec: 21 * 60,
    go_count: 1,
    wait_count: 7,
    avoid_count: 30,
    ticker_count: 38,
    current_run_scanned: 38,
    run_date: '2026-08-31',
    run_health_status: 'RUN_UNDERFILLED',
  }, now)
  check('TTL-stale populated scan is not chrome STALE', f.stale === false)
  check('TTL-stale populated has no surfaceLabel', f.surfaceLabel == null)
}

// ---- tradeAi: empty + API stale (bisect case) ----
{
  const f = tradeAiSurfaceFreshness({
    stale: true,
    cached_at: '2026-08-28T04:06:13.794823Z',
    cache_age_sec: 304750,
    go_count: 0,
    wait_count: 0,
    avoid_count: 0,
    ticker_count: 0,
    current_run_scanned: 0,
    // session heal lies "today"
    run_date: '2026-08-31',
    run_label: '1000',
  }, now)
  check('empty stale cache is stale despite today run_date', f.stale === true)
  check('surfaceLabel starts with STALE', !!f.surfaceLabel && f.surfaceLabel.startsWith('STALE'))
  check('reason mentions empty or cache', /empty|cache/i.test(f.reason || ''))
  check('asOf is cached_at', f.asOf === '2026-08-28T04:06:13.794823Z')
  check('ageHours ~84h', f.ageHours != null && f.ageHours > 80 && f.ageHours < 90)
}

// ---- tradeAi: prior session run_date ----
{
  const f = tradeAiSurfaceFreshness({
    stale: false,
    go_count: 5,
    wait_count: 1,
    ticker_count: 20,
    current_run_scanned: 20,
    run_date: '2026-08-29',
    cached_at: '2026-08-29T18:00:00Z',
    cache_age_sec: 48 * 3600,
  }, now)
  check('prior run_date is stale', f.stale === true)
}

// ---- overview: the PORTFOLIO chip dates the DATA, not the loader run ----
// as_of is written `= today` by portfolio_loader: it records WHEN THE LOADER RAN.
// On 2026-09-01 it read 2026-08-29 while the Schwab rows carried 08-31 and the
// moomoo/alpaca CASH rows carried 08-03/04 -- older than 28 of 30 rows and newer
// than the other 2. The chip showed "3.4d" and described nothing in the payload.
{
  const live = overviewSurfaceFreshness({
    as_of: '2026-08-31T12:00:00Z',
    data_as_of: '2026-08-31',
    data_as_of_account: 'schwab_taxable',
    pricing: { last_repriced: '2026-08-31T12:45:00Z' },
  }, now)
  check('overview fresh data -> not stale', live.stale === false)
  check('overview fresh reports dataAsOf', live.dataAsOf === '2026-08-31')

  // THE REGRESSION: loader ran recently, data is a month old.
  const real = overviewSurfaceFreshness({
    as_of: '2026-08-29',                 // loader ran 3 days ago
    data_as_of: '2026-08-03',            // oldest contributing row: 29 days
    data_as_of_account: 'moomoo_taxable_live',
    pricing: { last_repriced: '2026-09-01T16:00:00Z' },  // prices fresh today
  }, now)
  check('stale data beats a recent loader run', real.stale === true)
  check('age is dated from data_as_of, not as_of',
    real.ageHours != null && real.ageHours > 24 * 20)
  check('chip names the account that owns the stale row',
    !!real.reason && real.reason.includes('moomoo_taxable_live'))
  check('chip reports data_as_of as its asOf', real.asOf === '2026-08-03')

  // MUTATION: point the chip back at as_of. The 2026-08-29 loader date is ~3.4d,
  // which is under no plausible month-scale threshold -- so a chip reading as_of
  // cannot produce this age, and this check fails if the binding regresses.
  const asOfAge = (now.getTime() - Date.parse('2026-08-29')) / 3_600_000
  check('mutation: as_of would under-report the age by weeks',
    asOfAge < 24 * 10 && real.ageHours! > 24 * 20)

  // Missing clock is UNDATED -- never "today", never silent.
  const undated = overviewSurfaceFreshness({
    as_of: '2026-09-01T12:00:00Z',
    pricing: { last_repriced: '2026-09-01T12:00:00Z' },
  }, now)
  check('no data_as_of -> UNDATED, not fresh', undated.stale === true)
  check('UNDATED says so', !!undated.reason && undated.reason.includes('UNDATED'))
  check('UNDATED does not invent an age', undated.ageHours === null)
  check('UNDATED does not invent a date', undated.dataAsOf === null)
}

// ---- WI provenance (not a second model) ----
check('WI dataSource is decision_projection', WI_SYNOPSIS_PROVENANCE.dataSource === 'decision_projection')
check('WI liveClaim false', WI_SYNOPSIS_PROVENANCE.liveClaim === false)
check('WI spine false', WI_SYNOPSIS_PROVENANCE.spine === false)
check('WI surfaceNote mentions InstrumentRecord', /InstrumentRecord/.test(WI_SYNOPSIS_PROVENANCE.surfaceNote))

console.log(`\nsurfaceFreshness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
