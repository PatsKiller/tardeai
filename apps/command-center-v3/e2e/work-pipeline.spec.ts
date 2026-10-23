/** Coordination → Work pipeline (operator 2026-10-23): the default Coordination tab, one row per work item with
 *  stage cells, filters in the URL, presets, the Queued section and the Tier 1 action buttons. Every API request is
 *  fulfilled locally from the captured fixture (no live server); every POST is recorded and checked.
 *  Screenshots at 1440 and 412 px go to $WORK_PIPELINE_SHOTS (default: test-results/). */
import { expect, test, type Page } from '@playwright/test'
import { WORK_PIPELINE_FIXTURE as FIX } from '../src/fixtures/workPipeline.fixture'
import { PLAYBOOK_FIXTURE, WP_PIPELINE_FIXTURE as WPF, WP_TASK_DETAILS } from '../src/fixtures/workBoardStructure.fixture'

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

// ---------------------------------------------------------------------------------------------------------------------
// Work-package structure (operator 2026-10-23: "structure: problem, definition of done, agent prompt, operator commands,
// and proof of completion" ... "the above should be part of the board"). Fixture: the real board after the handoff
// import (src/fixtures/workBoardStructure.fixture.ts). Every request is fulfilled locally; POSTs are recorded.

const WP05 = 'DSN-20261023-handoff-v3-P2-T05'
const WP07 = 'DSN-20261023-handoff-v3-P2-T07'

async function mockWp(page: Page, posts: Post[], seen: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    seen.push(`${req.method()} ${url.pathname}${url.search}`)
    if (req.method() !== 'GET') {
      const body = JSON.parse(req.postData() || '{}')
      posts.push({ path: url.pathname, body })
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, command: body.command, result: {} }) })
    }
    const id = url.searchParams.get('id') || ''
    const body = url.pathname === '/api/v2/coordination/pipeline' ? { ok: true, data: WPF }
      : url.pathname === '/api/v2/coordination/task' ? (WP_TASK_DETAILS[id] ? { ok: true, data: WP_TASK_DETAILS[id] } : { ok: false, error: 'TaskError' })
        : url.pathname === '/api/v2/coordination/playbook' ? { ok: true, data: PLAYBOOK_FIXTURE }
          : url.pathname === '/api/v2/coordination/handoff-export' ? { ok: true, data: { markdown: '# Trade AI: complete ordered work plan (generated from the board)\n\n### WP-05 Create the GitHub App config (D2)\n', filename: 'HANDOFF_ORDERED_WORK_20261023.md', bytes: 120, work_packages: 41, truncated: false } }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test.describe('work-package structure', () => {
  test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(new Date('2026-10-23T21:45:00Z'))
  })

  test('rows show WP id and stage; Stage filter shows the stage intro; drawer has the five sections and copies B0 + prompt', async ({ page, context }) => {
    const posts: Post[] = []; const seen: string[] = []
    await mockWp(page, posts, seen)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/v3/coordination?wp=Stage%202')
    await expect(page.getByTestId('work-pipeline')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('filter-wp')).toHaveValue('Stage 2')
    await expect(page.getByTestId('stage-intro')).toContainText("What we're building.")
    const row = card(page, WP07)
    await expect(row.getByTestId('wp-id')).toHaveText('WP-07')
    await expect(row.getByTestId('wp-stage')).toHaveText('Stage 2')
    await expect(page.locator('[data-testid="pipeline-item"] [data-testid="wp-stage"]').first()).toHaveText('Stage 2')
    await page.screenshot({ path: `${SHOTS}/wpboard-stage2-1440.png` })
    await row.getByTestId('open-detail').click()
    const drawer = page.getByTestId('task-drawer')
    await expect(drawer).toBeVisible()
    for (const k of ['problem', 'definition_of_done', 'agent_prompt', 'operator_commands', 'proof']) await expect(drawer.getByTestId(`section-${k}`)).toBeVisible()
    await expect(drawer.getByTestId('section-problem')).toContainText('shadow has never produced a report')
    await expect(drawer.getByTestId('prompt-preamble-note')).toContainText('B0 preamble')
    await drawer.getByTestId('copy-prompt').click()
    await expect(drawer.getByTestId('copy-prompt')).toHaveText('Copied')
    const clip = await page.evaluate(() => navigator.clipboard.readText())
    expect(clip.startsWith('You are a coding agent working on Trade AI')).toBeTruthy()
    expect(clip).toContain('Never `pkill -f`.')
    expect(clip.indexOf('Never `pkill -f`.')).toBeLessThan(clip.indexOf('train-shadow-tick'))
    await page.screenshot({ path: `${SHOTS}/wpboard-drawer-1440.png` })
    expect(seen.some(s => s.startsWith(`GET /api/v2/coordination/task?id=${WP07}`))).toBeTruthy()
    expect(seen.filter(s => !s.startsWith('GET '))).toEqual([])
  })

  test('operator package: Copy commands copies the code, Mark done needs proof evidence', async ({ page, context }) => {
    const posts: Post[] = []; const seen: string[] = []
    await mockWp(page, posts, seen)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/v3/coordination?wp=WP-05')
    await expect(card(page, WP05)).toBeVisible({ timeout: 60_000 })
    await card(page, WP05).getByTestId('act-task-done').click() // a proof exists: opens the drawer instead of posting
    const drawer = page.getByTestId('task-drawer')
    await expect(drawer.getByTestId('section-operator_commands')).toContainText('release_train_github_app_config.py')
    await drawer.getByTestId('copy-operator').click()
    const clip = await page.evaluate(() => navigator.clipboard.readText())
    expect(clip.split('\n')[0]).toBe('cd ~/trade-ai-releases/portfolio-server/CURRENT')
    expect(clip).not.toContain('```')
    await expect(drawer.getByTestId('proof-evidence')).toContainText('No evidence yet')
    await expect(drawer.getByTestId('drawer-task-done')).toBeDisabled()
    expect(posts).toEqual([])
    await drawer.getByTestId('evidence-text').fill('wrote github-app.json; stat 600 johnclaw')
    await drawer.getByTestId('drawer-task-done').click()
    await expect.poll(() => posts.length).toBe(1)
    expect(posts[0].body.command).toBe('task_done')
    expect(posts[0].body.params).toEqual({ task_id: WP05, summary: 'wrote github-app.json; stat 600 johnclaw' })
  })

  test('Next up groups the first ready work package per owner; Playbook tab renders with anchors; Export handoff downloads', async ({ page }) => {
    const posts: Post[] = []; const seen: string[] = []
    await mockWp(page, posts, seen)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/v3/coordination?preset=next-up')
    const up = page.getByTestId('next-up')
    await expect(up).toBeVisible({ timeout: 60_000 })
    await expect(up.getByTestId('next-up-AGENT').getByTestId('queued-card').first()).toContainText('WP-01')
    await expect(up.getByTestId('next-up-OPERATOR')).toBeVisible()
    await expect(up.getByTestId('next-up-BOTH')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/wpboard-next-up-1440.png` })
    const dl = page.waitForEvent('download')
    await page.getByTestId('export-handoff').first().click()
    const file = await dl
    expect(file.suggestedFilename()).toBe('HANDOFF_ORDERED_WORK_20261023.md')
    await expect(page.getByTestId('export-handoff-result').first()).toContainText('41 work packages')
    await page.getByTestId('coordination-tab-playbook').click()
    await expect(page.getByTestId('playbook')).toBeVisible()
    await expect(page.getByTestId('playbook-toc')).toContainText('A3. Rules (never skip)')
    const b0 = page.locator('[data-testid="playbook-section"][data-section-id^="b0-standard-agent-preamble"]')
    await expect(b0).toContainText('Never `pkill -f`.'.replace(/`/g, ''))
    await expect(page.locator('#a3-rules-never-skip')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/wpboard-playbook-1440.png` })
    expect(seen.filter(s => !s.startsWith('GET '))).toEqual([])
  })

  test('412 px: drawer, Next up and Playbook fit the phone width', async ({ page }) => {
    const posts: Post[] = []; const seen: string[] = []
    await mockWp(page, posts, seen)
    await page.setViewportSize({ width: 412, height: 915 })
    await page.goto('/v3/coordination?preset=next-up')
    await expect(page.getByTestId('next-up')).toBeVisible({ timeout: 60_000 })
    const noHScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)
    expect(await noHScroll()).toBeTruthy()
    await page.screenshot({ path: `${SHOTS}/wpboard-next-up-412.png` })
    await page.getByTestId('next-up').getByTestId('queued-open-detail').first().click()
    await expect(page.getByTestId('task-drawer')).toBeVisible()
    const box = await page.getByTestId('task-drawer').boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(413)
    expect(await page.getByTestId('task-drawer').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBeTruthy() // content wraps, no sideways scroll
    await page.screenshot({ path: `${SHOTS}/wpboard-drawer-412.png` })
    await page.getByTestId('task-drawer-close').click()
    await page.getByTestId('coordination-tab-playbook').click()
    await expect(page.getByTestId('playbook-section').first()).toBeVisible()
    expect(await noHScroll()).toBeTruthy()
    await page.screenshot({ path: `${SHOTS}/wpboard-playbook-412.png` })
  })
})
