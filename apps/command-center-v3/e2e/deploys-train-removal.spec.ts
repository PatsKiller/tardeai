/** Operator-directed removal of the retired release train (2026-10-27): Home → Deploys (latest deploy receipt + deploy
 *  STOP), Releases & schedules without the Release train tab / windows / queue, Ops → Controls without Pause / Run now.
 *  Synthetic fixtures only; every /api request is intercepted and no write leaves the page. */
import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import { deploysFixture, homeFixtures } from './fixtures/homeDoNow.fixture'
declare const process: { env: Record<string, string | undefined> }
test.use({ hasTouch: true })

const at = '2031-03-10T15:00:00Z'
const jobs = { schema: 'JobsHealth@v1', as_of: at, offset: 0, limit: 50, has_more: false, total: 0, incident_count: 0,
  summary: { due_today: 0, succeeded: 0, failed: 0, missed: 0, paused: 0, retired: 0 },
  monitor: { observed_at: at, status: 'OK', cause: null, notification: { delivered: false, status: 'NOT_REQUESTED' } }, coverage_gaps: [], rows: [] }
const opsState = {
  policy: { state: 'ACTIVE' }, store: { state: 'OK' }, operator: { identity: 'fixture' }, factors: {},
  kinds: [
    { kind: 'deploy.stop', label: 'Deploys: STOP (hold host promote)', direction: 'safe', supported: true, reason: null, executor: 'cc', tab: 'jobs' },
    { kind: 'deploy.resume', label: 'Deploys: resume (clear the deploy STOP)', direction: 'risky', supported: true, reason: null, executor: 'applier', tab: 'jobs' },
    { kind: 'kill_switch.engage', label: 'Kill switch: engage', direction: 'safe', supported: true, reason: null, executor: 'applier', tab: 'jobs' },
  ],
  jobs: { state: 'OK', rows: [] }, n8n: { state: 'OK', rows: [] }, settings: { state: 'OK', rows: [] }, grants: { state: 'OK', active: [] },
  data_approvals: { state: 'OK', rows: [] }, deploy: { state: 'OK', reason: null, mode: 'RUNNING', epoch: 4, latch: 'ABSENT' },
  passkeys: [], audit: { state: 'OK', rows: [] }, requests: [],
}

async function opsFixtures(page: Page) {
  const writes: string[] = []
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') { writes.push(url.pathname); return route.abort() }
    if (url.pathname === '/api/v2/jobs-health') return route.fulfill({ status: 200, json: { ok: true, data: jobs } })
    if (url.pathname === '/api/v2/ops/controls/state' || url.pathname === '/api/v2/ops/controls') return route.fulfill({ status: 200, json: { ok: true, data: opsState, ...opsState } })
    if (url.pathname === '/api/v2/ops/releases-schedules') return route.fulfill({ status: 200, json: { ok: true, data: {
      schema: 'ReleasesSchedules@v1', generated_at: at, status: 'OK', kpis: [],
      serving: { value: { sha: 'f'.repeat(40), short_sha: 'fffffffff', release_name: 'fixture', since: at, since_basis: 'x', pins_agree: true, pins: {}, deploy_receipt: null }, as_of: at, freshness: 'OK', source: 'fixture', reason: null },
      // LQ-20261107-1794: the deployment log. Synthetic only (the repository is PUBLIC): invented ticket ids and
      // subjects, no ticker, holding, account or path. Every truth state on the current row, plus one zero-LQ row.
      deployment_log: { value: { since: '2026-11-03', generated_at: at, current_release: 'fixture-live',
        summary: { deploys: 2, rollbacks: 1, lq_items: 4, verified: 1, not_remeasured: 3 },
        truth_rule: 'VERIFIED only when the outcome was re-measured on live', deployments_total: 2, shown: 2, truncated: false,
        deployments: [
          { activated_at: at, activated_et: 'Tue 11-10 10:54 ET', kind: 'deploy', rollback: false, release: 'fixture-live',
            sha: 'f'.repeat(12), short_sha: 'fffffffff', previous_release: 'prev-live', previous_sha: 'e'.repeat(12),
            commit_count: 1, commits: ['LQ-9001: synthetic subject'], commits_shown: 1,
            items: [
              { lq: 'LQ-9001', title: 'synthetic verified fix', owner: 'agent-example', truth: { state: 'VERIFIED', text: 're-measured on live' } },
              { lq: 'LQ-9002', title: 'synthetic unmeasured fix', owner: 'agent-example', truth: { state: 'NOT_REMEASURED', text: 'not re-measured on live' } },
              { lq: 'LQ-9003', title: 'synthetic untracked fix', owner: 'agent-example', truth: { state: 'UNTRACKED', text: 'no outcome recorded' } },
              { lq: 'LQ-9004', title: 'synthetic unrecognised-state fix', owner: 'agent-example', truth: { state: 'verified', text: 'a lowercase state is not VERIFIED' } },
            ], is_current: true },
          { activated_at: '2026-11-09T13:20:18-05:00', activated_et: 'Mon 11-09 13:20 ET', kind: 'rollback/reactivate', rollback: true,
            release: 'prev-live', sha: 'e'.repeat(12), short_sha: 'eeeeeeeee', previous_release: 'fixture-live', previous_sha: 'f'.repeat(12),
            commit_count: 2, commits: ['synthetic subject one', 'synthetic subject two'], commits_shown: 2, items: [], is_current: false },
        ] }, as_of: at, freshness: 'OK', source: 'fixture:deployment_log', reason: null },
      stop: { state: 'ABSENT', effective_stop: false } } } })
    return route.fulfill({ status: 200, json: {} })
  })
  return writes
}

for (const width of [1440, 412, 390]) {
  const height = width === 1440 ? 1000 : width === 412 ? 915 : 844
  const shot = async (page: Page, name: string) => {
    if (process.env.TRAIN_REMOVAL_PROOF_DIR) await page.screenshot({ path: path.join(process.env.TRAIN_REMOVAL_PROOF_DIR, `${name}-${width}.png`), fullPage: true })
  }

  test(`Home Deploys line + drawer with deploy STOP ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
    const writes = await homeFixtures(page)
    await page.goto('/v3/')
    const pulse = page.getByTestId('home-pulse')
    await expect(pulse).toContainText('Deploys')
    await expect(pulse).toContainText('STOP clear · last verified · main fffffffff')
    await expect(page.getByTestId('home-do-now-page')).not.toContainText(/release train|Deploy hold|Run now/i)
    const shortcut = page.getByTestId('home-deploys-stop-shortcut')
    await expect(shortcut).toHaveText('STOP deploys…')
    if (width < 820) await shortcut.tap(); else await shortcut.click()
    const host = width < 820 ? page.getByRole('dialog', { name: 'Deploys' }) : page.getByTestId('home-drawer-deploys')
    const panel = host.getByTestId('deploys-panel')
    await expect(panel).toBeVisible()
    await expect(panel.getByTestId('deploys-last')).toContainText('verified')
    await expect(panel.getByTestId('deploys-recent').locator('li')).toHaveCount(2)
    const stop = panel.getByTestId('deploy-stop-button')
    await expect(stop).toHaveText('STOP DEPLOYS')
    expect((await stop.boundingBox())!.height).toBeGreaterThanOrEqual(width < 820 ? 40 : 1)
    if (width < 820) await stop.tap(); else await stop.click()
    await expect(panel.getByTestId('deploy-stop-confirm')).toBeVisible()
    await shot(page, 'home-deploys')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    expect(writes).toEqual([]); expect(errors).toEqual([])
  })

  test(`Releases & schedules has no Release train tab ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
    const writes = await opsFixtures(page)
    await page.goto('/v3/system/releases')
    await expect(page.getByTestId('releases-schedules')).toBeVisible()
    await expect(page.getByTestId('rs-tab-deploys')).toHaveText('Deploys')
    await expect(page.getByTestId('rs-tab-deploys')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId('rs-tab-train')).toHaveCount(0)
    await expect(page.getByTestId('rs-windows')).toHaveCount(0)
    await expect(page.getByTestId('rs-queue')).toHaveCount(0)
    await expect(page.getByTestId('rs-kpi-next_window')).toHaveCount(0)
    await expect(page.getByTestId('releases-schedules')).not.toContainText(/release train|Run now/i)
    // LQ-20261107-1794: the deployment log leads the Deploys tab, visible without opening "Details for engineers".
    const log = page.getByTestId('rs-deployment-log')
    await expect(log).toBeVisible()
    await expect(log).toContainText('Deployment log (since 2026-11-03)')
    await expect(log).toContainText('2 deploys')
    const rows = log.getByTestId('rs-deploy-row')
    await expect(rows).toHaveCount(2)
    await expect(rows.first()).toContainText('LIVE now')
    await expect(rows.first()).toContainText('VERIFIED')
    await expect(rows.first()).toContainText('NOT RE-MEASURED')
    // NO FALSE POSITIVE: four items are carried and the list prints three; exactly one may read VERIFIED, and the
    // item whose state is a lowercase 'verified' must not be the one.
    await expect(rows.first().getByText('VERIFIED', { exact: true })).toHaveCount(1)
    await expect(rows.first()).toContainText('NOT RE-MEASURED')
    await expect(rows.first()).toContainText('+1 more')
    // The truth's own words are on the chip for a pointer, and in full on the sheet.
    await expect(rows.first().getByTitle('re-measured on live', { exact: true })).toHaveCount(1)
    // A zero-LQ row shows its commits instead, and a rollback is flagged.
    await expect(rows.nth(1)).toContainText('ROLLBACK')
    await expect(rows.nth(1)).toContainText('2 commits')
    // Tap → full-screen detail sheet, with every fix, the truth texts, and the commit subjects behind a disclosure.
    if (width < 820) await rows.first().tap(); else await rows.first().click()
    const sheet = page.getByRole('dialog', { name: /Deployment · fffffffff/ })
    await expect(sheet).toBeVisible()
    await expect(sheet).toContainText('What it fixed')
    await expect(sheet).toContainText('UNKNOWN (verified)')
    await expect(sheet).toContainText('a lowercase state is not VERIFIED')
    await expect(sheet.getByText('VERIFIED', { exact: true })).toHaveCount(1)
    await shot(page, 'releases-deployment-sheet')
    await sheet.getByTestId('detail-close').click()
    await expect(sheet).toHaveCount(0)
    if (width < 820) await rows.nth(1).tap(); else await rows.nth(1).click()
    const sheet2 = page.getByRole('dialog', { name: /Deployment · eeeeeeeee/ })
    await expect(sheet2).toBeVisible()
    await expect(sheet2).toContainText('This deployment\'s record carries no tracked LQ item.')
    await expect(sheet2.locator('li').first()).toBeHidden()   // collapsed, as the row said
    await sheet2.getByText(/Show the 2 subjects/).click()
    await expect(sheet2.locator('li')).toHaveCount(2)
    await expect(sheet2.locator('li').first()).toBeVisible()
    await sheet2.getByTestId('detail-close').click()
    await expect(sheet2).toHaveCount(0)
    for (const t of ['n8n', 'jobs', 'deploys']) {
      const tab = page.getByTestId(`rs-tab-${t}`)
      if (width < 820) { expect((await tab.boundingBox())!.height).toBeGreaterThanOrEqual(44); await tab.tap() } else await tab.click()
      await expect(tab).toHaveAttribute('aria-selected', 'true')
    }
    await shot(page, 'releases')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    expect(writes).toEqual([]); expect(errors).toEqual([])
  })

  test(`Ops Controls Deploys row has STOP + Resume only ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
    const writes = await opsFixtures(page)
    await page.goto('/v3/system/ops-controls?tab=jobs')
    const explainer = page.getByTestId('ops-deploys-explainer')
    await expect(explainer).toBeVisible()
    const table = page.getByRole('table', { name: 'Deploys and kill switch' })
    await expect(table).toBeVisible()
    await expect(table).toContainText('Deploys')
    await expect(table.getByRole('button', { name: 'STOP', exact: true })).toBeVisible()
    await expect(table.getByRole('button', { name: 'Resume (passkey)', exact: true })).toBeVisible()
    await expect(table.getByRole('button', { name: 'Pause', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Run now/ })).toHaveCount(0)
    await expect(page.getByTestId('ops-release-train-explainer')).toHaveCount(0)
    await shot(page, 'ops-controls')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    expect(writes).toEqual([]); expect(errors).toEqual([])
  })
}

test('deploys fixture is synthetic and train-free', () => {
  expect(JSON.stringify(deploysFixture())).not.toMatch(/train/i)
})
