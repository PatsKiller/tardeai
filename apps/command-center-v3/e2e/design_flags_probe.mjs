// Design flags — do the cosmetics move, and do the faults refuse to?
//
// config/design_features.yaml can change how the header LOOKS. It must never
// change what the header is willing to SAY. Two layers already enforce that:
// the loader refuses to define a flag for a fault signal
// (scripts/lib/design_features.py PROTECTED_SIGNALS), and a source rail asserts
// the renderer has not invented one. Both are static checks.
//
// This is the dynamic one. It drives a real browser with hostile flag payloads
// — including flags that do not exist and flags named after fault signals — and
// asserts that the faults are still on screen afterwards. A config the loader
// would reject can still be served by a compromised or hand-edited endpoint;
// the renderer must not honour it either.
//
// Read-only: it serves the built bundle and stubs one endpoint. It never writes.
//
//   node e2e/design_flags_probe.mjs <appUrl> <apiUrl> [outJson]

import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const APP = process.argv[2] || 'http://127.0.0.1:4191'
const API = process.argv[3] || 'http://127.0.0.1:7777'
const OUT = process.argv[4] || ''

let pass = 0
let fail = 0
const check = (name, cond, detail) => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}${detail ? ` — ${detail}` : ''}`) }
}

const DEFAULTS = {
  state_dots: true, tile_rails: true, quiet_provenance: true,
  coverage_pct_on_face: false, run_clocks_on_face: true, density: 'normal',
}

async function render(browser, header) {
  const ctx = await browser.newContext({ viewport: { width: 1700, height: 900 } })
  const page = await ctx.newPage()
  // ORDER MATTERS. Playwright matches handlers in REVERSE registration order,
  // so the broad one is registered FIRST and the specific stub second —
  // otherwise the catch-all swallows /api/v2/design-features, forwards it to a
  // backend that 404s it, and every payload under test silently becomes the
  // defaults. Which is exactly what this probe did on its first run: 20 fault
  // checks passed and every cosmetic check failed, because nothing was stubbed.
  //
  // Everything except the flags reaches the real backend, so the faults on
  // screen are live ones and not a fixture.
  await page.route('**/api/**', (r) => {
    const u = new URL(r.request().url())
    r.continue({ url: API.replace(/\/$/, '') + u.pathname + u.search })
  })
  // The flag payload under test — registered last, so it wins.
  await page.route('**/api/v2/design-features*', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ schema: 'DesignFeatures@v1', header, protected_signals: [], read_only: true }),
    }))
  await page.goto(`${APP}/v3/`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {})
  await new Promise((r) => setTimeout(r, 3500))

  const out = await page.evaluate(() => {
    const strip = document.querySelector('.metric-strip')
    const tiles = [...document.querySelectorAll('.metric-strip-tile')]
    const byLabel = (p) => tiles.find((t) => t.querySelector('.ms-label').textContent.trim().startsWith(p))
    const meta = (p) => byLabel(p)?.querySelector('.ms-meta')?.textContent.trim() ?? ''
    return {
      height: Math.round(strip.getBoundingClientRect().height),
      dots: tiles.filter((t) => t.querySelector('[data-tile-tone]')).length,
      rails: tiles.filter((t) => parseFloat(getComputedStyle(t).borderLeftWidth) > 0).length,
      tileCount: tiles.length,
      padding: getComputedStyle(byLabel('VIX')).padding,
      portfolio: meta('PORTFOLIO'),
      today: meta('TODAY'),
      vix: meta('VIX'),
      trading: meta('TRADING'),
      setups: meta('SETUPS'),
      stamp: strip.querySelector('[data-price-stamp]')?.textContent.trim() ?? '',
      bodyText: (strip.innerText || ''),
    }
  })
  await ctx.close()
  return out
}

// Which faults are ON SCREEN right now, whatever they happen to be.
//
// The first version of this hard-required a RUN_UNDERFILLED verdict, which only
// worked while the live scanner happened to be underfilled. A scan landed
// mid-run that had scanned 1087 symbols against a floor of 40 — a healthy run —
// and the assertion failed because there was no fault to find. Asserting a
// specific fault exists is asserting the system is broken.
//
// The property that actually matters is DIFFERENTIAL: whatever faults the
// header shows under the shipped defaults must still be there under every other
// payload. Flags may not remove a fault that exists. That holds on a healthy
// system and a sick one.
function faultsOnScreen(r) {
  const found = []
  if (/clock divergence/i.test(r.portfolio)) found.push('clock_divergence')
  if (/RUN[_ ](UNDERFILLED|PARTIAL|FAILED)/i.test(r.setups)) found.push('run_health')
  if (/UNACCOUNTED/.test(r.setups)) found.push('unaccounted_rows')
  if (/DEGRADED|UNAVAILABLE/.test(r.stamp)) found.push('quote_coverage')
  if (/MISSING /.test(r.today)) found.push('missing_accounts')
  if (/STALE/i.test(r.bodyText)) found.push('stale_surface')
  if (/UNDATED/.test(r.bodyText)) found.push('undated_surface')
  return found
}

function assertFaultsSurvive(label, r, baseline) {
  const now = faultsOnScreen(r)
  const lost = baseline.filter((f) => !now.includes(f))
  check(`${label}: every fault visible under defaults is still visible`,
    lost.length === 0, lost.length ? `lost: ${lost.join(', ')}` : '')
  check(`${label}: the strip is still one row`, r.height <= 88, `${r.height}px`)
}

async function main() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  const results = {}

  // ── 1. shipped defaults ────────────────────────────────────────────────────
  console.log('\n── shipped defaults ──')
  const base = await render(browser, DEFAULTS)
  results.defaults = base
  check('dots render on every tile', base.dots === base.tileCount, `${base.dots}/${base.tileCount}`)
  check('rails render on every tile', base.rails === base.tileCount, `${base.rails}/${base.tileCount}`)
  check('quiet provenance is present', base.vix.length > 0 && base.trading.length > 0, `vix=${base.vix}`)
  check('coverage-% is off the face by default', !/covers .*% of value/.test(base.portfolio), base.portfolio)
  check('run clocks are on the face', /slot|finished/.test(base.setups), base.setups)

  // Vacuity guard. If the live system is reporting NO faults, every
  // "fault survives" check below is trivially true and this probe proves
  // nothing about the exemption. Say so rather than banking the passes.
  const baseline = faultsOnScreen(base)
  console.log(`  faults visible under defaults: ${baseline.join(', ') || 'NONE'}`)
  check('at least one fault is on screen, so the survival checks mean something',
    baseline.length > 0,
    'live system is clean — re-run when a fault is present, or the exemption is untested here')

  // ── 2. every cosmetic off, density compact ────────────────────────────────
  console.log('\n── all cosmetics off, density compact ──')
  const off = await render(browser, {
    state_dots: false, tile_rails: false, quiet_provenance: false,
    coverage_pct_on_face: false, run_clocks_on_face: false, density: 'compact',
  })
  results.all_off = off
  check('dots are gone', off.dots === 0, `${off.dots} remain`)
  check('rails are gone', off.rails === 0, `${off.rails} remain`)
  // The LINE stays — height is locked, so the tile always has three. What goes
  // is the provenance text; an em-dash placeholder is the honest stand-in for
  // "deliberately nothing here", and is what these tiles rendered before they
  // were given real provenance.
  check('quiet provenance text is gone from tiles with no fault',
    !/schwab|all_time/.test(off.trading) && !/trade_ai_run_summary/.test(off.vix),
    `vix=${off.vix} trading=${off.trading}`)
  check('the meta line itself survives, so the tile keeps its three lines',
    off.vix.length > 0 && off.trading.length > 0, `vix=${off.vix} trading=${off.trading}`)
  check('run clocks are off the face', !/slot|finished/.test(off.setups), off.setups)
  check('compact tightens padding', off.padding !== base.padding, `${base.padding} -> ${off.padding}`)
  check('compact removed no line — height unchanged', off.height === base.height,
    `${base.height} -> ${off.height}`)
  // THE test. Everything cosmetic is off; nothing that reports a fault may be.
  assertFaultsSurvive('all-off', off, baseline)

  // ── 3. the opt-in actually opts in ────────────────────────────────────────
  console.log('\n── coverage_pct_on_face: true ──')
  const cov = await render(browser, { ...DEFAULTS, coverage_pct_on_face: true })
  results.coverage_on = cov
  check('coverage-% appears on the face when asked',
    /covers [\d.]+% of value/.test(cov.portfolio), cov.portfolio)
  assertFaultsSurvive('coverage-on', cov, baseline)

  // ── 4. hostile payloads the loader would have rejected ────────────────────
  // A hand-edited or compromised endpoint can serve these even though
  // config/design_features.yaml cannot express them. The renderer must not care.
  console.log('\n── hostile: flags named after fault signals ──')
  const hostile = await render(browser, {
    ...DEFAULTS,
    clock_divergence: false, run_health: false, quote_coverage: false,
    unaccounted_rows: false, missing_accounts: false, stale_surface: false,
    undated_surface: false, hide_everything: true, show_nothing: true,
  })
  results.hostile = hostile
  assertFaultsSurvive('hostile', hostile, baseline)
  check('hostile payload did not disturb the cosmetics either',
    hostile.dots === base.dots && hostile.rails === base.rails)

  // ── 5. a malformed payload must not blank the header ──────────────────────
  console.log('\n── malformed payload ──')
  const junk = await render(browser, null)
  results.malformed = junk
  check('a null header block falls back to defaults, not to nothing',
    junk.tileCount === base.tileCount && junk.dots === base.dots,
    `${junk.tileCount} tiles, ${junk.dots} dots`)
  assertFaultsSurvive('malformed', junk, baseline)

  if (OUT) writeFileSync(OUT, JSON.stringify({ generated_at: new Date().toISOString(), app: APP, api: API, results }, null, 1))
  console.log(`\ndesign_flags_probe: ${pass} passed, ${fail} failed`)
  await browser.close()
  if (fail) process.exit(1)
}

main().catch((e) => { console.error('probe failed:', e); process.exit(1) })
