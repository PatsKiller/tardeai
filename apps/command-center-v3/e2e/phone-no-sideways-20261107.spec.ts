/** No page scrolls sideways at 412 px (LQ-20261107-525).
 *
 *  The defect: six routes were wider than a phone. Two shapes caused it, and both are layout, not content:
 *    - a `display:grid` page wrapper with no explicit track size: its implicit `auto` track takes the
 *      widest child's MAX-content (a wide table, a payload <pre>), so every panel on the page grows to
 *      that width and the document scrolls (control-plane audit / maturity / learning, 1642 / 1292 / 836);
 *    - a sentence rendered with no wrap opportunity: a row grid track sized to 448 px on Ops → Incidents
 *      (blocked reason), a nowrap ladder sub-line on Defense → Classic, seven seat pills on one
 *      inline-flex line, and a banner quoting the server's own long token on Ops → Controls.
 *
 *  Every assertion is the operator-visible one: `document.scrollingElement.scrollWidth === innerWidth`.
 *  Harness 1 serves the built app from `dist/` at a fake origin with every /api/ GET stubbed — no server,
 *  no live data, no writes. Harness 2 bundles the two defense components on their own, because the
 *  classic page needs a whole defense envelope to reach them and the components are where the bug is.
 *
 *   npm run build && npx playwright test e2e/phone-no-sideways-20261107.spec.ts --project=chromium --workers=1
 */
import { expect, test, type Page } from '@playwright/test'
import { build } from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(app, 'dist')
const ORIGIN = 'http://phone-no-sideways-20261107.invalid'
const NOW = '2026-11-07T23:30:00Z'
const PHONE = { width: 412, height: 915 }
/** One unbroken run, the way a commit sha, a receipt ref or a tool's own sentence arrives. */
const LONG_TOKEN = `ev-${'a1b2c3d4e5f6'.repeat(20)}`

/** The collections the three control-plane pages render as FieldTables. Every field is populated with the
 *  unbroken token so each table's max-content exceeds the phone width: on the old grid wrapper that is
 *  exactly what widened the page. */
const controlPlaneItem = {
  // audit (claimRow)
  claim_id: LONG_TOKEN, claim: LONG_TOKEN, implementation_ref: LONG_TOKEN, test_ref: LONG_TOKEN,
  evidence_ref: LONG_TOKEN, limitations: LONG_TOKEN, reproduction_command: LONG_TOKEN,
  section: 'architecture',
  // learning (itemRow) — a known kind so it lands in a real table, not the "other kinds" bucket
  item_id: LONG_TOKEN, kind: 'lesson', status: LONG_TOKEN, score: 1,
  proof_refs: LONG_TOKEN, limiting_factor: LONG_TOKEN, next_proof: LONG_TOKEN,
  // maturity (MATURITY_RENDER_FIELDS)
  dimension: LONG_TOKEN,
}

function envelope(items: unknown[]) {
  return {
    ok: true, as_of: NOW, source_sha: 'e'.repeat(40), freshness: 'FRESH', data_quality: 'AVAILABLE',
    evidence_class: 'PRODUCTION', data: { items, pagination: { limit: 50, offset: 0, total: items.length } },
  }
}

const incidents = {
  schema: 'IncidentsWire@v1', ledger_present: true, generated_at: NOW,
  summary: { counts: { open: 0, fixing: 0, blocked: 1, fixed: 0, closed: 0 }, unresolved: 1, oldest_unresolved_id: 'INC-fixture-blocked', oldest_unresolved_age_min: 12 },
  incidents: [{
    schema: 'IncidentRecord@v1', id: 'INC-fixture-blocked', opened_at: '2026-11-07T19:00:00Z', updated_at: NOW,
    status: 'blocked', source: { kind: 'lane', lane: 'market-open' },
    title: 'Four pipeline alerts caused by supervisor budgets and owners',
    where: 'supervisor', severity: 'P1', owner: 'codex',
    evidence: [], attempts: [], fix_refs: [], notes: [],
    // the ledger quotes the tool's own words verbatim; one unbroken run held the row's grid track at 448 px live
    blocked_reason: `Reviewed code live at ${LONG_TOKEN}`,
    handoff: 'Operator: restart the lane with the documented procedure',
    closed_at: null, acknowledged: null,
  }],
  watchers_as_of: NOW, supervisor_as_of: NOW,
}

const controlsState = {
  policy: { state: 'ACTIVE', required: '19.0.0' }, operator: 'operator', as_of: NOW,
  store: { state: 'NOT_MIGRATED', missing_tables: [LONG_TOKEN], reason: `migration did not apply: ${LONG_TOKEN}` },
  applier: { state: 'OK' }, factors: { webauthn_library: 'present', hmac_key: 'present' },
  sudo_window: { state: 'CLOSED' },
  settings: { state: 'OK', rows: [] }, jobs: { state: 'OK', rows: [] }, n8n: { state: 'OK', rows: [] },
  grants: { state: 'OK', active: [] }, data_approvals: { state: 'OK', rows: [] }, audit: { state: 'OK', rows: [] },
  deploy: { state: 'OK' }, passkeys: { state: 'OK' }, requests: { state: 'OK' },
  kinds: [], // a list, not a section: opsControls.ts:126 does `(state?.kinds || []).find(...)`
}

async function serveApp(page: Page) {
  const writes: string[] = []
  await page.routeWebSocket('**/*', ws => { writes.push('WS ' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (u.origin !== ORIGIN || req.method() !== 'GET') { writes.push(`${req.method()} ${u.origin}${u.pathname}`); return route.abort() }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname.startsWith('/api/v3/control-plane/')) return json(envelope([controlPlaneItem]))
    if (u.pathname === '/api/v2/ops/incidents') return json({ ok: true, data: incidents })
    if (u.pathname === '/api/v2/ops/controls/state') return json({ ok: true, data: controlsState })
    if (u.pathname.startsWith('/api/')) return json({ ok: false, error: 'fixture_unavailable' }, 503)
    const rel = u.pathname.replace(/^\/v3\/?/, ''), file = path.join(dist, rel)
    if (rel && file.startsWith(dist + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file })
    return route.fulfill({ path: path.join(dist, 'index.html') })
  })
  return writes
}

/** The operator's question, in pixels: does the document fit the screen, or is content off the right edge? */
async function sideways(page: Page) {
  return page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
}

for (const [route, testId, label] of [
  ['/v3/control-plane/audit', 'audit-readiness', 'Control plane → Audit'],
  ['/v3/control-plane/maturity', 'maturity-dimensions', 'Control plane → Maturity'],
  ['/v3/control-plane/learning', 'learning-kind-lesson', 'Control plane → Learning'],
] as const) {
  test(`412 px: ${label} does not scroll sideways`, async ({ page }) => {
    await page.setViewportSize(PHONE)
    const writes = await serveApp(page)
    await page.goto(ORIGIN + route)
    // the table has to be on screen before its width means anything
    await expect(page.getByTestId(testId)).toBeVisible()
    await expect(page.locator('table').first()).toBeVisible()
    expect(await sideways(page), `${label} scrollWidth - innerWidth at 412 px`).toBeLessThanOrEqual(0)
    expect(writes, 'no request left the fake origin').toEqual([])
  })
}

test('412 px: Ops → Incidents does not scroll sideways', async ({ page }) => {
  await page.setViewportSize(PHONE)
  const writes = await serveApp(page)
  await page.goto(ORIGIN + '/v3/ops/incidents')
  await expect(page.getByTestId('incident-headline-INC-fixture-blocked')).toBeVisible()
  // the blocked reason is the sentence that widened the row: it must still be there, wrapped
  await expect(page.getByText('Reviewed code live at')).toBeVisible()
  const over = await sideways(page)
  expect(over, 'Incidents scrollWidth - innerWidth at 412 px').toBeLessThanOrEqual(0)
  expect(writes, 'no request left the fake origin').toEqual([])
})

test('412 px: Ops → Controls does not scroll sideways', async ({ page }) => {
  await page.setViewportSize(PHONE)
  const writes = await serveApp(page)
  await page.goto(ORIGIN + '/v3/system/ops-controls')
  await expect(page.getByTestId('ops-controls')).toBeVisible()
  await expect(page.getByText('Missing tables:')).toBeVisible()
  const over = await sideways(page)
  expect(over, 'Ops Controls scrollWidth - innerWidth at 412 px').toBeLessThanOrEqual(0)
  expect(writes, 'no request left the fake origin').toEqual([])
})

/** Defense components at their real phone column width (344 px inside main's 20 px padding). */
test.describe('defense components in a phone card column', () => {
  let js = '', css = ''
  test.beforeAll(async () => {
    const b = await build({
      stdin: {
        contents: `import React from 'react';import{createRoot}from'react-dom/client';
          import LadderTrack from'./src/components/defense/LadderTrack';
          import{OversightPills}from'./src/components/defense/RecommendationsRail';
          import'./src/styles/tokens.css';import'./src/index.css';
          const fired='x'.repeat(44); // the component slices fired_by at 44: the widest a real cause can be
          createRoot(document.getElementById('root')).render(<main className="app-main" style={{padding:20}}>
            <div id="card" style={{width:344}}>
              <div data-testid="ladder"><LadderTrack ladder={{t1_fraction:33,t1_status:'advised',tranches:[
                {tranche:'T2',status:'fired',fired_at:'2026-11-06T15:00:00Z',fired_by:fired,triggers:[]},
                {tranche:'T3',status:'armed',triggers:[{type:'price_below',level:100,label:'close < $100'}]}]}} price={110} /></div>
              <div data-testid="pills"><OversightPills cardId="card-fixture" factorsN={12} oversight={null} /></div>
            </div></main>);`,
        resolveDir: app, loader: 'tsx', sourcefile: 'phone-no-sideways.tsx',
      },
      bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic',
      define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent',
    })
    js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
    css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
  })

  for (const [id, what] of [['ladder', 'LadderTrack'], ['pills', 'OversightPills']] as const) {
    test(`${what} keeps its own width at 412 px`, async ({ page }) => {
      await page.setViewportSize(PHONE)
      await page.route('**/*', async route => {
        const u = new URL(route.request().url())
        if (u.origin !== ORIGIN) return route.abort()
        if (u.pathname.startsWith('/api/')) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"error":"fixture_unavailable"}' })
        return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg0);color:var(--text0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      })
      await page.goto(ORIGIN + '/')
      await expect(page.getByTestId(id)).toBeVisible()
      expect(await sideways(page), `${what} pushed the document past 412 px`).toBeLessThanOrEqual(0)
      // and it must not spill out of the card it lives in, even when the document happens to fit
      const spill = await page.evaluate(() => {
        const card = document.getElementById('card')!
        const right = card.getBoundingClientRect().right
        const worst = [...card.querySelectorAll('*')].reduce((m, n) => Math.max(m, n.getBoundingClientRect().right), 0)
        return Math.round(worst - right)
      })
      expect(spill, `${what} spills past the card's right edge`).toBeLessThanOrEqual(0)
    })
  }
})
