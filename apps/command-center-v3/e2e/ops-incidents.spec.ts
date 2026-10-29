import { test, expect } from '@playwright/test'
import path from 'node:path'
test.use({ hasTouch: true })

// Ops → Incidents (2026-10-27). Synthetic fixture incidents only — every /api request is intercepted and live :7777
// traffic fails the test. Phone (412/390): row tap opens the full-screen sheet, Back returns to the list; desktop
// (1440): side panel. The only POSTs are the operator's Acknowledge / Close as won't fix.
const now = Date.now()
const iso = (minAgo: number) => new Date(now - minAgo * 60000).toISOString()
const open = { schema: 'IncidentRecord@v1', id: 'INC-261027-kmpqrs', opened_at: iso(95), updated_at: iso(20), status: 'blocked',
  source: { kind: 'watcher', watcher: 'deploy_failures', job: 'deploy-on-main' }, title: 'Fixture deploy poller failing on main',
  where: 'fixture/deploy_on_main_poll.py', severity: 'P1', owner: '', evidence: ['receipt:fixture/receipt.json'],
  attempts: [{ at: iso(30), actor: 'incident_supervisor', action: 'deploy_on_main_dry_run', result: 'rc=0', ok: true, provider: 'anthropic', rationale: 'Fixture rationale.' }],
  fix_refs: [], blocked_reason: 'needs_operator: fixture grant missing', handoff: 'operator: issue the fixture grant', escalations: [{ at: iso(25), delivered: true }],
  acknowledged: null, resolution: null, closed_at: null, notes: [] }
const fixing = { ...open, id: 'INC-261027-tvwxyz', status: 'fixing', title: 'Fixture health tick step broken', opened_at: iso(12),
  blocked_reason: null, handoff: null, escalations: [], source: { kind: 'watcher', watcher: 'health_tick', job: 'fixture-step' } }
const fixed = { ...open, id: 'INC-261026-ghjkmn', status: 'fixed', title: 'Fixture comms alerts suppressed', opened_at: iso(1500), closed_at: iso(600),
  updated_at: iso(600), resolution: 'fixed', blocked_reason: null, handoff: null, escalations: [], attempts: [], fix_refs: [{ kind: 'pr', ref: '1' }],
  source: { kind: 'deploy', job: 'comms-editor' } }
const list = { schema: 'OpsIncidentsView@v1', ledger_present: true, generated_at: iso(1), watchers_as_of: iso(2), supervisor_as_of: iso(4),
  summary: { counts: { open: 0, fixing: 1, fixed: 1, blocked: 1, closed: 0 }, unresolved: 1, oldest_unresolved_id: open.id, oldest_unresolved_age_min: 95 },
  incidents: [open, fixing, fixed] }

for (const width of [1440, 412, 390]) {
  test(`ops incidents ${width}`, async ({ page }) => {
    const height = width === 412 ? 915 : width === 390 ? 844 : 1000
    await page.setViewportSize({ width, height })
    const posts: { path: string; body: unknown }[] = []
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.port === '7777') throw new Error('Live API traffic is forbidden')
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (route.request().method() === 'POST') {
        posts.push({ path: url.pathname, body: route.request().postDataJSON() })
        return route.fulfill({ status: 200, json: { ok: true, data: { incident: { ...open, acknowledged: { at: iso(0), actor: 'op' } } } } })
      }
      if (url.pathname === '/api/v2/ops/incidents') return route.fulfill({ status: 200, json: { ok: true, data: list } })
      const m = /^\/api\/v2\/ops\/incidents\/(INC-[^/]+)$/.exec(url.pathname)
      if (m) {
        const inc = list.incidents.find(i => i.id === decodeURIComponent(m[1]))
        return inc ? route.fulfill({ status: 200, json: { ok: true, data: { incident: inc, events: [{ kind: 'open' }, { kind: 'block' }] } } })
          : route.fulfill({ status: 404, json: { ok: false, error: 'NOT_FOUND' } })
      }
      return route.fulfill({ status: 200, json: { ok: true, data: {} } })
    })
    await page.goto('/v3/ops/incidents')
    const root = page.getByTestId('ops-incidents')
    await expect(root).toBeVisible()
    await expect(page.getByTestId('ops-frame-incidents')).toBeVisible()
    await expect(page.getByTestId('incident-count-blocked')).toContainText('1')
    // Active filter: blocked + fixing; fixed hidden until "Fixed"/"All".
    const row = page.getByTestId(`incident-row-${open.id}`)
    await expect(row).toContainText('Blocked — needs a person')
    await expect(row).toContainText('1 h 35 min')
    await expect(page.getByTestId(`incident-row-${fixed.id}`)).toHaveCount(0)
    const allBtn = page.getByTestId('incident-filter-all')
    expect((await allBtn.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await allBtn.tap()
    await expect(page.getByTestId(`incident-row-${fixed.id}`)).toContainText('PR #1')
    expect((await row.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await row.tap()
    const detail = page.getByTestId('incident-detail')
    await expect(detail).toBeVisible()
    await expect(detail).toContainText('operator: issue the fixture grant')
    await expect(detail.getByTestId('incident-attempts')).toContainText('deploy_on_main_dry_run')
    if (width < 800) {
      const sheet = page.getByRole('dialog')
      await expect(sheet).toBeInViewport()
      expect((await sheet.boundingBox())?.height).toBe(height)
    }
    const ack = detail.getByTestId('incident-ack')
    expect((await ack.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    await ack.tap()
    await expect.poll(() => posts.length).toBe(1)
    expect(posts[0].path).toBe(`/api/v2/ops/incidents/${open.id}/ack`)
    await detail.getByTestId('incident-close-start').tap()
    const confirm = detail.getByTestId('incident-close-confirm')
    await expect(confirm).toBeDisabled()
    await detail.getByTestId('incident-close-comment').fill('fixture: superseded')
    await confirm.tap()
    await expect.poll(() => posts.length).toBe(2)
    expect(posts[1].path).toBe(`/api/v2/ops/incidents/${open.id}/close`)
    expect((posts[1].body as { comment: string }).comment).toBe('fixture: superseded')
    if (process.env.INCIDENTS_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.INCIDENTS_SCREENSHOT_DIR, `incidents-detail-${width}.png`), fullPage: true })
    if (width < 800) {
      await page.goBack()
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await expect(row).toBeInViewport()
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    expect(errors).toEqual([])
  })
}
