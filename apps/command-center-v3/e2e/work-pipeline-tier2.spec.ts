/** Work pipeline Tier 2 (operator 2026-10-23, "both"): risky acts are Ops → Controls requests — create, a fresh
 *  passkey assertion + the exact typed phrase, approve; the host applier executes. Fixture + mocked routes only; the
 *  WebAuthn authenticator is a stub. Proves the order of calls, that the phrase gates the confirm button, that a
 *  disabled (unratified) act cannot be started, and that no Tier 1 endpoint is used for it. */
import { expect, test, type Page } from '@playwright/test'
import { WORK_PIPELINE_FIXTURE as FIX } from '../src/fixtures/workPipeline.fixture'

const SHOTS = process.env.WORK_PIPELINE_SHOTS || 'test-results'
const RID = 'opsreq_' + '1'.repeat(20)
type Call = { method: string; path: string; body: Record<string, unknown> | null }

const DESIGN = FIX.items!.find(i => (i.actions?.tier2 || []).some(a => a.kind === 'pipeline.approve_design' && a.enabled))!
const MERGE = FIX.items!.find(i => (i.actions?.tier2 || []).some(a => a.kind === 'pipeline.merge_pr'))

async function mock(page: Page, calls: Call[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const body = req.method() === 'GET' ? null : JSON.parse(req.postData() || '{}')
    if (req.method() !== 'GET') calls.push({ method: req.method(), path: url.pathname, body })
    const phrase = `APPROVE DESIGN ${DESIGN.id} 2026-10-23`
    const reply = url.pathname === '/api/v2/coordination/pipeline' ? { ok: true, data: FIX }
      : url.pathname === '/api/v2/ops/controls/requests' ? { ok: true, request: { request_id: RID, kind: body?.kind, phrase, status: 'AWAITING_STEP_UP', direction: 'risky', preview: { summary: `record the operator's approval of ${DESIGN.id}` } } }
        : url.pathname.endsWith('/step-up/options') ? { ok: true, options: { challenge: 'AAAAAAAAAAAAAAAAAAAAAA', allowCredentials: [{ id: 'Y3JlZA', type: 'public-key' }], userVerification: 'required' } }
          : url.pathname.endsWith('/step-up/verify') ? { ok: true, step_up_token: 'tok-1' }
            : url.pathname.endsWith('/approve') ? { ok: true, request: { request_id: RID, kind: 'pipeline.approve_design', status: 'APPROVED', direction: 'risky' } }
              : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(reply) })
  })
}

async function stubAuthenticator(page: Page) {
  await page.addInitScript(() => {
    const buf = (s: string) => new TextEncoder().encode(s).buffer
    Object.defineProperty(navigator, 'credentials', {
      configurable: true,
      value: {
        get: async () => ({
          id: 'Y3JlZA', rawId: buf('cred'), type: 'public-key', authenticatorAttachment: 'platform',
          response: { clientDataJSON: buf('{"type":"webauthn.get"}'), authenticatorData: buf('ad'), signature: buf('sig'), userHandle: buf('u') },
          getClientExtensionResults: () => ({}),
        }),
      },
    })
  })
}

test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date('2026-10-23T18:15:00Z')) })

test('approve a design: create → typed phrase gates confirm → passkey → approve; nothing else is called', async ({ page }) => {
  const calls: Call[] = []
  await stubAuthenticator(page)
  await mock(page, calls)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/v3/coordination?q=${encodeURIComponent(DESIGN.id)}`)
  const card = page.locator(`[data-testid="pipeline-item"][data-item-id="${DESIGN.id}"]`)
  await expect(card).toBeVisible({ timeout: 60_000 })
  await card.locator('[data-testid="tier2-button"][data-kind="pipeline.approve_design"]').click()
  const dlg = page.getByTestId('tier2-dialog')
  await expect(dlg.getByTestId('tier2-create')).toBeDisabled()
  await dlg.getByTestId('tier2-words').fill('Approved: go ahead with batches B-D')
  await dlg.getByTestId('tier2-create').click()
  await expect(dlg.getByTestId('tier2-phrase')).toHaveText(`APPROVE DESIGN ${DESIGN.id} 2026-10-23`)
  await dlg.getByTestId('tier2-typed').fill('APPROVE DESIGN wrong 2026-10-23')
  await expect(dlg.getByTestId('tier2-confirm')).toBeDisabled()
  await dlg.getByTestId('tier2-typed').fill(`APPROVE DESIGN ${DESIGN.id} 2026-10-23`)
  await page.screenshot({ path: `${SHOTS}/work-pipeline-tier2-dialog-1440.png` })
  await dlg.getByTestId('tier2-confirm').click()
  await expect(dlg.getByTestId('tier2-result')).toContainText('APPROVED')
  expect(calls.map(c => c.path)).toEqual([
    '/api/v2/ops/controls/requests',
    `/api/v2/ops/controls/requests/${RID}/step-up/options`,
    `/api/v2/ops/controls/requests/${RID}/step-up/verify`,
    `/api/v2/ops/controls/requests/${RID}/approve`,
  ])
  expect(calls[0].body).toMatchObject({ kind: 'pipeline.approve_design', params: { design_id: DESIGN.id, words: 'Approved: go ahead with batches B-D' } })
  expect(calls[0].body?.actor).toBeUndefined()
  expect(calls[2].body).toMatchObject({ phrase: `APPROVE DESIGN ${DESIGN.id} 2026-10-23` })
  expect((calls[2].body?.credential as { rawId?: string })?.rawId).toBeTruthy()
  expect(calls[3].body).toEqual({ step_up_token: 'tok-1' })
})

test('without an authenticator the act stops before approve', async ({ page }) => {
  const calls: Call[] = []
  await page.addInitScript(() => { Object.defineProperty(navigator, 'credentials', { configurable: true, value: undefined }) })
  await mock(page, calls)
  await page.goto(`/v3/coordination?q=${encodeURIComponent(DESIGN.id)}`)
  const card = page.locator(`[data-testid="pipeline-item"][data-item-id="${DESIGN.id}"]`)
  await card.locator('[data-testid="tier2-button"][data-kind="pipeline.approve_design"]').click({ timeout: 60_000 })
  const dlg = page.getByTestId('tier2-dialog')
  await dlg.getByTestId('tier2-words').fill('approve it')
  await dlg.getByTestId('tier2-create').click()
  await dlg.getByTestId('tier2-typed').fill(`APPROVE DESIGN ${DESIGN.id} 2026-10-23`)
  await dlg.getByTestId('tier2-confirm').click()
  await expect(dlg.getByTestId('tier2-result')).toContainText('WEBAUTHN_UNAVAILABLE')
  expect(calls.some(c => c.path.endsWith('/approve'))).toBe(false)
})

test('unratified acts (merge, release) are shown disabled with the reason and cannot start', async ({ page }) => {
  const calls: Call[] = []
  await mock(page, calls)
  await page.goto('/v3/coordination')
  const release = page.getByTestId('release-now').getByTestId('tier2-button')
  await expect(release).toBeVisible({ timeout: 60_000 })
  await expect(release).toBeDisabled()
  await expect(release).toHaveAttribute('title', /AGENTS\.md clause/)
  if (MERGE) {
    await page.goto(`/v3/coordination?q=${encodeURIComponent(MERGE.id.replace('PR-', ''))}`)
    const btn = page.locator(`[data-testid="pipeline-item"][data-item-id="${MERGE.id}"] [data-kind="pipeline.merge_pr"]`)
    await expect(btn).toBeDisabled()
    await expect(btn).toContainText('(off)')
  }
  expect(calls).toEqual([])
})
