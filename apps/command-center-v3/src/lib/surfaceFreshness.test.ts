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

// ---- overview ----
{
  const live = overviewSurfaceFreshness({
    as_of: '2026-08-31T12:00:00Z',
    pricing: { last_repriced: '2026-08-31T12:45:00Z' },
  }, now)
  check('overview same-day not stale', live.stale === false)

  const old = overviewSurfaceFreshness({
    as_of: '2026-08-29T00:00:00Z',
    pricing: { last_repriced: '2026-08-29T00:00:00Z' },
  }, now)
  check('overview >36h is stale', old.stale === true)
  check('overview uses oldest contributor', old.ageHours != null && old.ageHours > 36)
  check('overview surfaceLabel visible', !!old.surfaceLabel && old.surfaceLabel.includes('STALE'))
}

// ---- WI provenance (not a second model) ----
check('WI dataSource is decision_projection', WI_SYNOPSIS_PROVENANCE.dataSource === 'decision_projection')
check('WI liveClaim false', WI_SYNOPSIS_PROVENANCE.liveClaim === false)
check('WI spine false', WI_SYNOPSIS_PROVENANCE.spine === false)
check('WI surfaceNote mentions InstrumentRecord', /InstrumentRecord/.test(WI_SYNOPSIS_PROVENANCE.surfaceNote))

console.log(`\nsurfaceFreshness: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
