/** Watch redesign (Gate 3 mockup, 2026-10-22). Every API request is fulfilled locally from the captured fixture;
 *  the test records every non-GET and fails on any write other than the three existing operator flows it drives. */
import { expect, test, type Page } from '@playwright/test'
import { FIXTURE } from '../src/fixtures/watchProspects.fixture'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v3/data-broker/watch-prospects' ? FIXTURE.prospects
      : url.pathname === '/api/v2/watch/alerts/list' ? FIXTURE.alerts
        : url.pathname === '/api/v2/proposal-accounts' ? { ok: true, data: { accounts: [] } }
          : url.pathname.endsWith('/review-request') ? { ok: true, data: { ok: true, already_open: false } }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('Prospects (now the third Watch tab): interim label, chips, five lanes, one row per prospect', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/watch?tab=prospects')
  await expect(page).toHaveURL(/tab=prospects/)
  const root = page.getByTestId('watch-prospects')
  await expect(root).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('watch-interim')).toHaveText('interim — CIO prospect store not live')
  await expect(page.getByTestId('watch-chip-conflicts')).toContainText('shown, not hidden')
  await expect(page.getByTestId('watch-chip-holdings')).toContainText('positions_store.positions_current')

  for (const [id, n] of [['actionable', 5], ['forming', 90], ['reentry', 19], ['manage', 20], ['expired', 67]] as const) {
    await expect(page.getByTestId(`watch-lane-${id}`)).toContainText(String(n))
  }
  // Actionable is the default lane: CACI (re-entry desk READY) leads with Propose.
  const rows = page.getByTestId('watch-row')
  await expect(rows).toHaveCount(5)
  await expect(rows.first()).toHaveAttribute('data-symbol', 'CACI')
  await expect(rows.first().getByTestId('watch-step')).toHaveText('Propose')

  // Manage: NAVN shows both conflicts and Protect first → Open Trades.
  await page.getByTestId('watch-lane-manage').click()
  await expect(page).toHaveURL(/lane=manage/)
  const navn = page.locator('[data-testid="watch-row"][data-symbol="NAVN"]')
  await expect(navn.getByTestId('watch-blocking-reason')).toHaveCount(1)
  await expect(navn.getByTestId('watch-blocking-reason')).toContainText('Not actionable:')
  await expect(navn.getByTestId('watch-step')).toHaveText('Protect first')
  await expect(navn.getByTestId('watch-step')).toHaveAttribute('data-href', /\/v3\/trading\?tab=Open\+Trades&symbol=NAVN/)
  await expect(page.locator('[data-testid="watch-row"][data-lane="manage"]')).toHaveCount(8)
  await expect(page.getByTestId('watch-overflow')).toContainText('12 more below the 8-row cap')

  // Detail: components, conflicts with both sides, same record everywhere.
  await navn.getByRole('button', { name: 'NAVN', exact: true }).click()
  const detail = page.getByTestId('watch-detail')
  await expect(detail).toContainText('Conviction 88')
  await expect(page.getByTestId('watch-components')).toContainText('Risk/Reward')
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('SELL')
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('positions_store.positions_current')
  await expect(page.getByTestId('watch-detail-conflict')).toHaveCount(2)
  await expect(page.getByTestId('watch-same-record')).toContainText('not joined (interim)')
  await expect(page.getByTestId('watch-same-record')).toContainText('#1 · 88 · WATCH')
  await page.getByTestId('watch-ask-cio').click()
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('CIO review queued.')

  // Drawers: alerts tied/orphaned, expired, how this page works.
  await page.getByTestId('watch-drawer-alerts').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-alerts')).toContainText('16 armed → 8 belong to a prospect · 8 orphaned')
  await expect(page.getByTestId('watch-drawer-alerts-body')).toContainText('QCOM price')
  await expect(page.getByTestId('watch-orphan-alert')).toHaveCount(8)
  await page.getByTestId('watch-drawer-expired').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-expired-body')).toContainText('CVS')
  await page.getByTestId('watch-drawer-how').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-how-body')).toContainText('never silently resolved')

  expect(writes).toEqual(['POST /api/v3/opportunities/NAVN/review-request'])
})

test('Propose opens the existing propose form; Set alert opens the existing alert form', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/watch?tab=prospects&lane=actionable')
  const caci = page.locator('[data-testid="watch-row"][data-symbol="CACI"]')
  await caci.getByTestId('watch-step').click()
  await expect(page.getByText('Propose entry')).toBeVisible()
  await expect(page.getByText('CACI').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await page.goto('/v3/watch?tab=prospects&lane=reentry')
  const kbr = page.locator('[data-testid="watch-row"][data-symbol="KBR"]')
  await kbr.getByTestId('watch-step').click()
  const modal = page.getByTestId('reentry-alert-arm-modal')
  await expect(modal).toBeVisible()
  await expect(modal.locator('input[type="number"]').first()).toHaveValue('36.80')
  expect(writes).toEqual([])
})

test('Classic view keeps the old Intelligence page for one release', async ({ page }) => {
  await mockApi(page, [])
  await page.goto('/v3/watch?tab=prospects')
  await page.getByTestId('watch-tab-intelligence').click()
  await expect(page).toHaveURL(/tab=intelligence/)
  await expect(page.getByTestId('watch-tab-intelligence')).toHaveText('Classic view')
  await expect(page.getByTestId('watch-prospects')).toHaveCount(0)
})

for (const width of [1440, 412, 390]) {
  test(`canonical Watch readiness and factor provenance at ${width}px`, async ({ browser }, info) => {
    // Compose synthetic source data through the production Python adapter, so the browser
    // regression covers the actual ordering defect rather than a manually corrected response.
    const sourceRoot = process.env.WATCH_CONSISTENCY_SOURCE_ROOT || path.resolve('../..')
    const result = spawnSync(process.env.WATCH_CONSISTENCY_PYTHON || 'python3', ['-c', `
import json,sys
sys.path.insert(0,'scripts')
from scripts.lib.site_payload_reads import canonical_rows
clock='2026-10-27T20:30:00Z'
row={
 'symbol':'ZZQA','company':'Fictional Instruments','security_guid':'synthetic-guid','identity_status':'CONFIRMED',
 'lane':'actionable','stage':'actionable','why':'Review re-entry now','summary':'Source setup conviction 79.',
 'conviction':79,'conviction_source':'cio_opportunity_projection','conviction_as_of':clock,'conviction_stale':False,
 'conviction_components':[{'key':'technical','label':'Technical','value':70}],'conviction_missing':[],
 'stance':'RE_ENTER','conflicts':[],'whats_missing':[],
 'next_action':{'kind':'propose','label':'Propose','reason':'Source setup ready'},
 'next_trigger':{'label':'Recorded source zone','inside':False},'levels_ref':{},
 'price':100,'price_as_of':clock,'rsi':50,'held':False,'surfaces':[],
 'evidence_at':clock,'expires_at':None,'stale':False,
 'mine':True,'starred':True,'membership':[],'position_state':'never_held',
 'conflict_section':{'headline':None,'findings':[],'gap':{'reason':'synthetic producer unavailable'}},
 'review_state':{'status':'blocked','label':'Blocked: waiting for stored evidence','open':True,
                 'request_id':'rr_synthetic','next_run':'Synthetic scheduled run'},
}
truth={'stance':'BUY_SETUP','conviction':71,'as_of':clock,'stale':False,'conflicts':[]}
print(json.dumps(canonical_rows([row],resolver=lambda *a,**kw:truth,projection={})[0]))
`], { cwd: sourceRoot, encoding: 'utf8' })
    expect(result.status, result.stderr || result.error?.message).toBe(0)
    const composed = JSON.parse(result.stdout)
    const baseURL = String(info.project.use.baseURL)
    const origin = new URL(baseURL).origin
    const context = await browser.newContext({ baseURL, viewport: { width, height: 915 }, hasTouch: width < 821 })
    const page = await context.newPage()
    const writes: string[] = [], external: string[] = [], errors: string[] = []
    await page.clock.install({ time: new Date('2026-10-27T21:30:00Z') })
    page.on('pageerror', error => errors.push(String(error)))
    await page.routeWebSocket('**/*', ws => ws.close())
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url())
      if (url.origin !== origin) { external.push(url.href); return route.abort() }
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (req.method() !== 'GET') { writes.push(req.method() + ' ' + url.pathname); return route.abort() }
      const body = url.pathname === '/api/v3/data-broker/watch-curation'
        ? url.searchParams.get('review_status') === '1'
          ? { ok: true, rows: { ZZQA: composed.review_state } }
          : { ok: true, data: { my_watchlist: { rows: [composed], total: 1, starred: 1, kinds: {},
            pagination: { total: 1, offset: 0, limit: 25, has_more: false } } } }
        : url.pathname === '/api/v2/watch/alerts/list' ? { ok: true, data: { alerts: [] } } : { ok: true, data: {} }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    try {
      await page.goto('/v3/watch')
      const row = page.getByTestId('watch-row').filter({ has: page.getByRole('button', { name: 'ZZQA', exact: true }) })
      await expect(row).toHaveAttribute('data-lane', 'forming')
      await expect(row.locator('.watch-card-setup')).toContainText('CIO review required')
      await expect(row.locator('.watch-card-setup').getByText('Actionable', { exact: true })).toHaveCount(0)
      await expect(row.getByTestId('watch-step')).toContainText('Ask the CIO')
      await row.getByRole('button', { name: 'ZZQA', exact: true }).click()
      const detail = page.getByTestId('watch-detail')
      await expect(detail.getByTestId('watch-canonical-conviction')).toContainText('CIO conviction 71')
      await expect(detail.getByTestId('watch-factor-heading')).toHaveText('Source factor scores · source conviction 79')
      await expect(detail).toContainText('Source setup context: Source setup conviction 79.')
      await expect(detail.getByTestId('watch-review-state')).toContainText('Blocked: waiting for stored evidence')
      const output = process.env.WATCH_CONSISTENCY_PROOF_DIR || info.outputPath('consistency-proof')
      fs.mkdirSync(output, { recursive: true })
      await page.screenshot({ path: path.join(output, `watch-consistency-detail-${width}.png`), fullPage: width >= 821 })
      if (width < 821) {
        const sheet = page.getByRole('dialog', { name: 'ZZQA · watch record' })
        const box = await sheet.boundingBox()
        expect(box && box.y <= 1 && box.height >= 900).toBe(true)
        const back = sheet.getByRole('button', { name: '← Back', exact: true })
        const target = await back.boundingBox()
        expect(target && target.width >= 44 && target.height >= 44).toBe(true)
        await back.tap()
        await expect(sheet).toHaveCount(0)
      }
      await page.screenshot({ path: path.join(output, `watch-consistency-${width}.png`), fullPage: true })
      expect(writes).toEqual([])
      expect(external).toEqual([])
      expect(errors).toEqual([])
    } finally { await context.close() }
  })
}
