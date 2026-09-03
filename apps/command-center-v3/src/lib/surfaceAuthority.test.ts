// Pure-logic tests for surfaceAuthority.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/surfaceAuthority.test.ts
//
// Proves the page never decides what it is showing. Every path that is not an
// explicit server LIVE_GOVERNED verdict resolves to a banner, and a compiled
// fixture is never allowed to stand in for a failed live read.
import {
  surfaceVerdict,
  fixtureMayRenderAsLive,
  LIVE_GOVERNED,
  PREVIEW_FIXTURE,
  FROZEN_SNAPSHOT,
  UNAVAILABLE,
  UNKNOWN,
  type SurfaceAuthority,
} from './surfaceAuthority.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const R = '/v3/control-plane/agents'

function authority(mode: string, extra: Record<string, unknown> = {}): SurfaceAuthority {
  return {
    schema: 'ControlPlaneSurfaceAuthority@v1',
    decided_by: 'server',
    surfaces: [{
      route: R,
      tranche: 'r22',
      data_mode: mode,
      reason: `server said ${mode}`,
      banner_required: mode !== LIVE_GOVERNED,
      banner_dismissible: false,
      live_domain: 'agents',
      bundled_fixture: { bundled: true, path: 'pages/control-plane/r22/mocks/agents.json' },
      ...extra,
    }],
  }
}

// ── the server's verdict is the verdict ──────────────────────────────────────
{
  const live = surfaceVerdict(authority(LIVE_GOVERNED), R)
  check('LIVE_GOVERNED is live', live.isLive === true)
  check('LIVE_GOVERNED needs no banner', live.bannerRequired === false)
  check('LIVE_GOVERNED keeps the server reason', live.reason === 'server said LIVE_GOVERNED')

  for (const m of [PREVIEW_FIXTURE, FROZEN_SNAPSHOT, UNAVAILABLE, UNKNOWN]) {
    const v = surfaceVerdict(authority(m), R)
    check(`${m} is not live`, v.isLive === false)
    check(`${m} requires a banner`, v.bannerRequired === true)
    check(`${m} banner is undismissable`, v.dismissible === false)
    check(`${m} label names the mode`, v.label.length > 0 && v.label !== 'LIVE')
  }
}

// ── the failure modes all fall to UNKNOWN + banner, never to LIVE ────────────
{
  const noPayload = surfaceVerdict(null, R)
  check('missing authority is UNKNOWN', noPayload.mode === UNKNOWN)
  check('missing authority is not live', noPayload.isLive === false)
  check('missing authority still banners', noPayload.bannerRequired === true)

  const unavailable = surfaceVerdict({ status: 'UNAVAILABLE', reason: 'ImportError: boom' }, R)
  check('UNAVAILABLE endpoint is UNKNOWN', unavailable.mode === UNKNOWN)
  check('UNAVAILABLE endpoint surfaces the server reason', unavailable.reason === 'ImportError: boom')

  const noRow = surfaceVerdict({ surfaces: [] }, R)
  check('a route with no row is UNKNOWN', noRow.mode === UNKNOWN)
  check('a route with no row names itself in the reason', noRow.reason.includes(R))

  const garbage = surfaceVerdict(authority('TOTALLY_MADE_UP'), R)
  check('an unrecognised mode is UNKNOWN, not trusted', garbage.mode === UNKNOWN)
  check('an unrecognised mode is not live', garbage.isLive === false)

  const notAList = surfaceVerdict({ surfaces: undefined } as unknown as SurfaceAuthority, R)
  check('a malformed surfaces field is UNKNOWN', notAList.mode === UNKNOWN)
}

// ── the fixture is visible, and it is never the data ─────────────────────────
{
  const v = surfaceVerdict(authority(PREVIEW_FIXTURE), R)
  check('the bundled fixture is disclosed', v.fixtureBundled === true)
  check('the fixture path is named', v.fixturePath === 'pages/control-plane/r22/mocks/agents.json')
  check('a fixture may never render as live', fixtureMayRenderAsLive() === false)

  // The defect this replaces: a live read fails, and the page quietly renders the
  // fixture that is already compiled in. The verdict for a failed read is
  // UNAVAILABLE/UNKNOWN with a banner — the fixture is disclosed, never promoted.
  const failed = surfaceVerdict(authority(UNAVAILABLE), R)
  check('a failed live read does not become live via the fixture', failed.isLive === false)
  check('a failed live read still discloses the fixture', failed.fixtureBundled === true)
}

// ── a page cannot self-declare ───────────────────────────────────────────────
{
  const v = surfaceVerdict(authority(LIVE_GOVERNED), '/v3/control-plane/audit')
  check('asking for a different route does not inherit another route verdict', v.mode === UNKNOWN)
  check('a mismatched route is not live', v.isLive === false)
}

console.log(`\nsurfaceAuthority: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
