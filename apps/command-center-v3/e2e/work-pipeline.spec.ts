/** Coordination → Work pipeline (operator 2026-10-23): the default Coordination tab, one row per work item with
 *  stage cells, filters in the URL, presets, the Queued section and the Tier 1 action buttons. Every API request is
 *  fulfilled locally from the captured fixture (no live server); every POST is recorded and checked.
 *  Screenshots at 1440 and 412 px go to $WORK_PIPELINE_SHOTS (default: test-results/). */
import { expect, test, type Page } from '@playwright/test'
import { WORK_PIPELINE_FIXTURE as FIX } from '../src/fixtures/workPipeline.fixture'

type Post = { path: string; body: { command?: string; params?: Record<string, unknown>; idempotency_key?: string; actor?: string } }
const SHOTS = process.env.WORK_PIPELINE_SHOTS || 'test-results'

async function mockApi(page: Page, posts: Post[], seen: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    seen.push(`${req.method()} ${url.pathname}${url.search}`)
    if (req.method() !== 'GET') {
      const body = JSON.parse(req.postData() || '{}')
      posts.push({ path: url.pathname, body })
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, command: body.command, actor: 'tailnet:operator', result: {} }) })
    }
    const body = url.pathname === '/api/v2/coordination/pipeline' ? { ok: true, data: FIX }
      : url.pathname === '/api/v2/coordination/claims' && url.searchParams.get('worklog')
        ? { ok: true, data: { found: true, text: `# Worklog — ${url.searchParams.get('worklog')}\n\n## Plan\n\n- [x] merge #1999 into batch` } }
        : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

const STALE_CLAIM = FIX.items!.find(i => i.kind === 'claim' && i.actions?.available.includes('release_stale_claim'))!
const card = (page: Page, id: string) => page.locator(`[data-testid="pipeline-item"][data-item-id="${id}"]`)

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-23T17:45:00Z'))
})

test('Work pipeline is the default Coordination tab: strip, stage cells, who/what/when/where/how, next step', async ({ page }) => {
  const posts: Post[] = []; const seen: string[] = []
  await mockApi(page, posts, seen)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('coordination-tab-pipeline')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('coordination-tab-agents')).toHaveText('Files held')
  await expect(page.getByTestId('strip-needs-me')).toContainText(String(FIX.summary!.needs_me))
  await expect(page.getByTestId('strip-in_batch')).toContainText(String(FIX.summary!.counts.in_batch))
  // the operator's complaint: a green PR not in a batch is AMBER "waiting for batch", never stale
  const waiting = card(page, 'PR-2005')
  await expect(waiting).toHaveAttribute('data-rag', 'amber')
  await expect(waiting.locator('[data-stage="in_batch"]')).toContainText('waiting for batch')
  await expect(waiting.locator('[data-stage="ci"]')).toHaveAttribute('data-rag', 'green')
  await expect(waiting).not.toContainText('stale')
  const merge = card(page, 'PR-1997')
  await expect(merge.getByTestId('next')).toContainText('OPERATOR')
  await expect(merge.getByTestId('command-text')).toHaveText(/^gh pr merge 1997 --merge --match-head-commit [0-9a-f]{40}$/)
  await expect(merge.getByTestId('link-ci')).toHaveAttribute('href', /\/pull\/1997\/checks$/)
  await expect(card(page, 'PR-2016').getByTestId('next')).toContainText('contract review')
  await expect(page.getByTestId('queued-tasks').getByTestId('queued-card')).not.toHaveCount(0)
  await expect(page.getByTestId('queued-operator')).toContainText('OPERATOR')
  // finished (released + verified) hidden by default
  await expect(card(page, 'PR-2002')).toHaveCount(0)
  await page.screenshot({ path: `${SHOTS}/work-pipeline-1440.png` })
  await page.setViewportSize({ width: 1440, height: 3600 })
  await page.screenshot({ path: `${SHOTS}/work-pipeline-1440-full.png` })
  expect(posts).toEqual([])
  expect(seen.filter(s => !s.startsWith('GET '))).toEqual([])
})

test('filters and presets live in the URL; finished toggle; worklog drawer', async ({ page }) => {
  const posts: Post[] = []; const seen: string[] = []
  await mockApi(page, posts, seen)
  await page.goto('/v3/coordination?preset=needs-me')
  await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
  const items = page.getByTestId('pipeline-item')
  await expect(items.first()).toBeVisible()
  for (const owner of await items.evaluateAll(els => els.map(e => e.getAttribute('data-owner')))) expect(owner).toBe('operator')
  await page.getByTestId('preset-red').click()
  await expect(page).toHaveURL(/preset=red/)
  for (const rag of await items.evaluateAll(els => els.map(e => e.getAttribute('data-rag')))) expect(rag).toBe('red')
  await page.getByTestId('filter-clear').click()
  await page.getByTestId('filter-q').fill('memory')
  await expect(page).toHaveURL(/q=memory/)
  await page.getByTestId('filter-batch').selectOption('none')
  await expect(page).toHaveURL(/batch=none/)
  await page.getByTestId('filter-clear').click()
  await page.getByTestId('preset-live-today').click()
  await expect(card(page, 'PR-2002')).toBeVisible()
  await page.getByTestId('filter-clear').click()
  await page.getByTestId('filter-finished').check()
  await expect(page).toHaveURL(/finished=1/)
  await expect(card(page, 'PR-2002')).toBeVisible()
  await card(page, 'PR-2018').getByTestId('link-worklog').click()
  await expect(page.getByTestId('worklog-drawer')).toContainText('merge #1999 into batch')
  expect(posts).toEqual([])
})

test('Tier 1 actions post typed commands to one endpoint with an idempotency key and no actor', async ({ page }) => {
  const posts: Post[] = []; const seen: string[] = []
  await mockApi(page, posts, seen)
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
  await card(page, 'PR-2005').getByTestId('act-batch-add').click()
  await expect(card(page, 'PR-2005').getByTestId('action-result')).toContainText('batch_add: done')
  const stale = card(page, STALE_CLAIM.id)
  await stale.getByTestId('act-release-stale').click()
  await stale.getByTestId('composer-submit').click()
  const two = card(page, 'PR-2016')
  await two.getByTestId('act-note').click()
  await two.getByTestId('composer-text').fill('contract review first, then CI')
  await two.getByTestId('composer-submit').click()
  await two.getByTestId('act-hold').click()
  await two.getByTestId('composer-submit').click()
  await page.getByTestId('preset-queued').click()
  const task = card(page, 'T-20261023-fc7872')
  await task.getByTestId('act-priority').selectOption('1')
  await task.getByTestId('act-split').click()
  await task.getByTestId('composer-text').fill('bound reads | scripts/api_v2.py | tests\nwatchdog | scripts/portfolio_server_watchdog.sh')
  await task.getByTestId('composer-submit').click()
  await page.getByTestId('new-task').click()
  await page.getByTestId('new-task-title').fill('OPERATOR: review #2016 contract')
  await page.getByTestId('new-task-areas').fill('config/operator_evidence_contract.json')
  await page.getByTestId('new-task-submit').click()
  await expect.poll(() => posts.length).toBe(7)
  expect(posts.every(p => p.path === '/api/v2/coordination/commands')).toBe(true)
  expect(posts.map(p => p.body.command)).toEqual(['batch_add', 'release_stale_claim', 'note', 'hold', 'set_priority', 'task_split', 'task_add'])
  expect(posts[0].body.params).toEqual({ pr: 2005 })
  expect(posts[1].body.params).toEqual({ claim_id: STALE_CLAIM.actions!.stale_claims[0] })
  expect(posts[2].body.params).toEqual({ item: 'PR-2016', text: 'contract review first, then CI' })
  expect(posts[4].body.params).toEqual({ task_id: 'T-20261023-fc7872', priority: 1 })
  expect((posts[5].body.params?.parts as unknown[]).length).toBe(2)
  const keys = posts.map(p => p.body.idempotency_key)
  expect(new Set(keys).size).toBe(7)
  for (const p of posts) { expect(p.body.actor).toBeUndefined(); expect(String(p.body.idempotency_key)).toMatch(/^wp-[A-Za-z0-9_.:-]{6,}$/) }
})

test('copy command writes the exact command client-side, no server write', async ({ page, context }) => {
  const posts: Post[] = []; const seen: string[] = []
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await mockApi(page, posts, seen)
  await page.goto('/v3/coordination?preset=needs-me')
  await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
  const merge = card(page, 'PR-1997')
  await merge.getByTestId('copy-command').click()
  await expect(merge.getByTestId('copy-command')).toHaveText('Copied')
  const clip = await page.evaluate(() => navigator.clipboard.readText())
  expect(clip).toMatch(/^gh pr merge 1997 --merge --match-head-commit [0-9a-f]{40}$/)
  expect(posts).toEqual([])
})

test('phone width 412: no horizontal scroll, cards stack', async ({ page }) => {
  const posts: Post[] = []; const seen: string[] = []
  await mockApi(page, posts, seen)
  await page.setViewportSize({ width: 412, height: 915 })
  await page.goto('/v3/coordination')
  await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
  await expect(card(page, 'PR-2005')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: `${SHOTS}/work-pipeline-412.png` })
  await page.setViewportSize({ width: 412, height: 3200 })
  await page.screenshot({ path: `${SHOTS}/work-pipeline-412-full.png` })
  await page.getByTestId('preset-needs-me').click()
  await page.screenshot({ path: `${SHOTS}/work-pipeline-412-needs-me.png` })
})
