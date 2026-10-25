/** Ask the CIO (Phases 8–11). Every API request is fulfilled locally from src/fixtures/askCio.fixture.ts; the test
 *  records every non-GET and fails on any write other than the ask / follow-up / untrack flows it drives. */
import { expect, test, type Page } from '@playwright/test'
import { ASK_RESPONSE, LIST, THREAD } from '../src/fixtures/askCio.fixture'

async function mockApi(page: Page, writes: { path: string; body: unknown }[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push({ path: `${req.method()} ${url.pathname}`, body: req.postDataJSON() })
    const body = url.pathname === '/api/v2/cio/ask' ? ASK_RESPONSE
      : url.pathname === '/api/v2/cio/asks' ? LIST
        : url.pathname === '/api/v2/cio/asks/tracked' ? { ok: true, data: { tracked: [
          { thread_id: THREAD.thread_id, key: THREAD.entities[0].key, symbol: 'TSLA', name: 'Tesla', kind: 'security' },
          { thread_id: 'thr_1111111111111111', key: 'ent_x', symbol: null, name: 'Skydance', kind: 'private_entity' }] } }
        : url.pathname === `/api/v2/cio/asks/${THREAD.thread_id}` ? { ok: true, data: { thread: THREAD } }
          : url.pathname.endsWith('/untrack') ? { ok: true, data: { ok: true } }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('the ask bar is on every page, ⌘K focuses it, and the answer opens inline with its thread', async ({ page }) => {
  const writes: { path: string; body: unknown }[] = []
  await mockApi(page, writes)
  for (const path of ['/v3/', '/v3/watch', '/v3/system']) {
    await page.goto(path)
    await expect(page.getByTestId('ask-cio-bar')).toBeVisible({ timeout: 60_000 })
  }
  await page.goto('/v3/')
  await page.getByTestId('ask-cio-bar').waitFor({ timeout: 60_000 })
  // tracked names are flagged in the header on every page (Home here; Watch above)
  await expect(page.getByTestId('ask-cio-tracked')).toContainText('TSLA')
  await expect(page.getByTestId('ask-cio-tracked')).toContainText('Skydance (private)')
  await page.keyboard.press('Control+k')
  await expect(page.getByTestId('ask-cio-input')).toBeFocused()
  await page.keyboard.type('100 or 1,000 TSLA given the SpaceX merger talk?')
  await page.getByTestId('ask-cio-submit').click()
  const ans = page.getByTestId('ask-cio-answer-text')
  await expect(ans).toContainText('Sizing context — the quantities you named')
  await expect(ans).toContainText('Tracking: TSLA → My Watchlist')
  expect(writes).toHaveLength(1)
  expect(writes[0].path).toBe('POST /api/v2/cio/ask')
  expect(writes[0].body).toMatchObject({ question: '100 or 1,000 TSLA given the SpaceX merger talk?', depth: 'quick' })
  await page.getByTestId('ask-cio-open-thread').click()
  await expect(page).toHaveURL(new RegExp(`/v3/cio/questions/${THREAD.thread_id}$`))
})

test('My questions: list, thread with versions, re-answer, sizing context, follow-up and untrack', async ({ page }) => {
  const writes: { path: string; body: unknown }[] = []
  await mockApi(page, writes)
  await page.goto(`/v3/cio/questions/${THREAD.thread_id}`)
  await expect(page.getByTestId('my-questions-list')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId(`q-${THREAD.thread_id}`)).toContainText('Updated on new information')
  await expect(page.getByTestId('q-thr_1111111111111111')).toContainText('Skydance (private)')
  const thread = page.getByTestId('ask-thread')
  await expect(thread.getByTestId('turn-ask')).toContainText('v2 · Deep research capped')
  await expect(thread.getByTestId('turn-follow_up')).toContainText('Telegram')
  await expect(thread.getByTestId('what-changed')).toContainText('TSLA filed 8-K')
  await thread.getByTestId('turn-ask').getByRole('button', { name: /earlier versions/ }).click()
  await expect(thread.getByTestId('sizing-context')).toContainText('1,000 TSLA: ≈ $250,000 · 25.0% of portfolio · over the 12% limit')
  await expect(thread.getByTestId('ask-tracking')).toContainText('SpaceX (private) · tracked')

  await page.getByTestId('ask-follow-up').fill('what would change your view?')
  await page.getByTestId('ask-follow-up-send').click()
  await page.getByTestId('untrack-TSLA').click()
  await expect.poll(() => writes.map(w => w.path)).toEqual([
    'POST /api/v2/cio/ask', `POST /api/v2/cio/asks/${THREAD.thread_id}/untrack`,
  ])
  expect(writes[0].body).toMatchObject({ question: 'what would change your view?', thread_id: THREAD.thread_id })
  expect(writes[1].body).toEqual({ entity_key: '11111111-2222-4333-8444-555555555555' })
})
