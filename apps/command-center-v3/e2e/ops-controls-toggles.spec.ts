/** Ops → Controls · Toggles (2026-10-25). Operator, verbatim: "this should have just been a toggle to turn on/off on
 *  the control ops." Mobile first (operator on a phone ~90%): at 412 and 390 px a tap on a switch opens the governed
 *  flow as a full-screen sheet (preview → typed phrase → passkey → approve → APPLIED), the test-send button asks
 *  for confirmation before anything is sent, and every tap target is at least 44 px. Fixture + mocked routes only;
 *  the WebAuthn authenticator is a stub; nothing reaches a server. */
import { expect, test, type Page } from '@playwright/test'

const SHOTS = process.env.OPS_TOGGLES_SHOTS || 'test-results'
const RID = 'opsreq_' + '2'.repeat(20)
type Call = { method: string; path: string; body: Record<string, unknown> | null }

const KINDS = ['setting.set', 'setting.unset', 'n8n_live_list.add', 'n8n_live_list.remove'].map(kind => ({
  kind, label: kind, direction: 'risky', executor: 'applier', tab: 'flags', supported: true, reason: null, fresh_passkey: false,
}))
const DOMAINS = ['msg.fi.google.com', 'vtext.com', 'tmomail.net', 'txt.att.net']
const STATE = {
  ok: true, schema: 'OpsControlsState@v1', as_of: '2026-10-25T18:30:00Z', operator: 'tailnet:john@jwwhiting.com',
  policy: { state: 'ACTIVE', required: '19.0.0', detail: '19.0.0 ACTIVE' }, store: { state: 'OK' },
  applier: { state: 'OK', heartbeat_at: '2026-10-25T18:29:58Z', age_s: 2 },
  factors: { webauthn_library: 'available', hmac_key: 'present', totp: 'enrolled', passkeys_active: 1 },
  kinds: KINDS,
  jobs: { state: 'OK', rows: [] },
  n8n: { state: 'OK', live_list_path: '/home/op/.config/tradeai/n8n-live-lanes.env', live_lanes: ['registry-truth'], rows: [
    { lane_id: 'registry-truth', stage: 'live', on_live_list: true, scheduler_kind: 'n8n' },
    { lane_id: 'cio-prospect-shadow', stage: 'canary', on_live_list: false, scheduler_kind: 'n8n' },
    { lane_id: 'conflict-resolver', stage: 'shadow', on_live_list: false, scheduler_kind: 'n8n' },
  ] },
  settings: { state: 'OK', history: [], projection: { state: 'ABSENT', path: '/x/operator_settings_env.json', drift: [] }, rows: [
    { key: 'comms.sms.enabled', label: 'Text-message alerts (SMS) on', type: 'bool', default: false, overridden: false, current: null,
      env_key: 'ENABLE_SMS', group: 'sms', wired: true, effective: { value: false, source: 'default' } },
    { key: 'comms.sms.operator_email', label: 'Text-message address', type: 'string', overridden: false, current: null, env_key: 'OPERATOR_SMS_EMAIL',
      validator: 'sms_gateway_email', allowed_domains: DOMAINS, masked: true, wired: true, effective: { value: '••••••4567@msg.fi.google.com', source: 'environment' } },
    { key: 'comms.gateway_mode', label: 'Gateway mode', type: 'enum', choices: ['OFF', 'CANARY', 'ACTIVE'], default: 'OFF', overridden: false,
      env_key: 'COMMS_GATEWAY_MODE', wired: true, warning: 'applies to every process that resolves the gateway mode', effective: { value: 'OFF', source: 'default' } },
  ] },
  toggles: { state: 'OK', channels: { sms: true, email: true }, cooldown_s: 60, last_test: {},
    notifier: { state: 'OK', as_of: '2026-10-25T18:25:00Z', run_mode: 'live', email_mirror: { config: 'ok', sent: 0, failed: 3, would: 0 }, gateway_modes_seen: ['OFF'] } },
  grants: { state: 'OK', tiers: [], active: [] }, data_approvals: { state: 'OK', rows: [] },
  release_train: { state: 'OK', mode: 'RUNNING' }, passkeys: [{ credential_id8: 'Y3JlZAAA', credential_id: 'Y3JlZA', name: 'Pixel' }],
  audit: { state: 'OK', rows: [] }, requests: [], sudo_window: { state: 'INERT', reason: 'off', window: null },
}

async function mock(page: Page, calls: Call[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    const body = req.method() === 'GET' ? null : JSON.parse(req.postData() || '{}')
    if (req.method() !== 'GET') calls.push({ method: req.method(), path: url.pathname, body })
    const created = calls.find(c => c.path === '/api/v2/ops/controls/requests')?.body as { kind?: string; params?: Record<string, unknown> } | undefined
    const phrase = created?.kind?.startsWith('n8n') ? `ADD LIVE ${created?.params?.lane_id} 2026-10-25` : `SET ${created?.params?.key} 2026-10-25`
    const reqObj = (status: string, extra = {}) => ({ request_id: RID, kind: created?.kind, params: created?.params, phrase, status, direction: 'risky', executor: 'applier',
      preview: { summary: `dry run of ${created?.kind}`, diff: ['- off', '+ on'], warnings: ['replaces ENABLE_SMS from the environment (.env)'] }, ...extra })
    const p = url.pathname
    const reply = p === '/api/v2/ops/controls/state' ? STATE
      : p === '/api/v2/ops/controls/requests' ? { ok: true, request: reqObj('AWAITING_STEP_UP') }
        : p.endsWith('/step-up/options') ? { ok: true, options: { challenge: 'AAAAAAAAAAAAAAAAAAAAAA', allowCredentials: [{ id: 'Y3JlZA', type: 'public-key' }], userVerification: 'required' } }
          : p.endsWith('/step-up/verify') ? { ok: true, step_up_token: 'tok-1' }
            : p.endsWith('/approve') ? { ok: true, request: reqObj('APPROVED') }
              : p === `/api/v2/ops/controls/requests/${RID}` ? { ok: true, request: reqObj('APPLIED', { result: { outcome: 'APPLIED', detail: 'projection written' } }) }
                : p === '/api/v2/ops/controls/test-send' ? { ok: true, result: { channel: body?.channel, test_id: 'opstest_1', at: '2026-10-25T18:31:00Z', delivered: false, gateway_mode: 'OFF', error: 'delivery_blocked_mode' } }
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

async function minTarget(page: Page, testId: string) {
  const box = await page.getByTestId(testId).boundingBox()
  expect(box, testId).not.toBeNull()
  expect(box!.height, `${testId} height`).toBeGreaterThanOrEqual(44)
  expect(box!.width, `${testId} width`).toBeGreaterThanOrEqual(44)
}

/** Full-screen sheet on a phone: the panel fills the overlay (the overlay is the viewport less a desktop scrollbar). */
async function fullScreen(page: Page, sheet: ReturnType<Page['getByTestId']>, width: number) {
  const overlay = await sheet.boundingBox()
  const panel = await sheet.locator('.ops-sheet-panel').boundingBox()
  expect(Math.round(panel!.width)).toBe(Math.round(overlay!.width))
  expect(panel!.width).toBeGreaterThanOrEqual(width - 16)
  expect(Math.round(panel!.height)).toBeGreaterThanOrEqual(Math.round(overlay!.height) - 1)
}

async function approveInSheet(page: Page, width: number, phrase: string) {
  const sheet = page.getByTestId('ops-controls-modal')
  await expect(sheet).toBeVisible()
  await fullScreen(page, sheet, width)
  await sheet.getByRole('button', { name: 'Next: authenticate' }).click()
  await expect(sheet.getByTestId('ops-controls-phrase')).toHaveText(phrase)
  const approve = sheet.getByRole('button', { name: 'Use passkey and approve' })
  await expect(approve).toBeDisabled()
  await sheet.getByTestId('ops-controls-phrase-input').fill(phrase)
  const ab = await approve.boundingBox()
  expect(ab!.height).toBeGreaterThanOrEqual(44)
  await approve.click()
  await expect(sheet.getByTestId('ops-controls-result')).toContainText('Applied', { timeout: 10_000 })
}

for (const width of [412, 390]) {
  test.describe(`toggles at ${width}px`, () => {
    test.beforeEach(async ({ page }) => {
      await page.clock.setFixedTime(new Date('2026-10-25T18:30:00Z'))
      await page.setViewportSize({ width, height: 860 })
      await stubAuthenticator(page)
    })

    test(`SMS switch → confirm sheet → APPLIED (${width})`, async ({ page }) => {
      const calls: Call[] = []
      await mock(page, calls)
      await page.goto('/v3/system/ops-controls?tab=toggles')
      await expect(page.getByTestId('toggle-card-sms')).toBeVisible({ timeout: 60_000 })
      for (const id of ['toggle-sms', 'toggle-sms-address-edit', 'toggle-sms-test', 'toggle-gateway-CANARY', 'toggle-email-test', 'toggle-lane-cio-prospect-shadow']) await minTarget(page, id)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await expect(page.getByTestId('toggle-sms')).toHaveAttribute('aria-checked', 'false')
      await expect(page.getByTestId('toggle-sms-readiness')).toContainText('Gateway mode is OFF')
      await page.getByTestId('ops-toggles').screenshot({ path: `${SHOTS}/ops-toggles-${width}.png` })
      await page.getByTestId('toggle-sms').click()
      await approveInSheet(page, width, 'SET comms.sms.enabled 2026-10-25')
      await page.screenshot({ path: `${SHOTS}/ops-toggles-sheet-${width}.png` })
      const posts = calls.map(c => c.path)
      expect(posts.slice(0, 4)).toEqual([
        '/api/v2/ops/controls/requests',
        `/api/v2/ops/controls/requests/${RID}/step-up/options`,
        `/api/v2/ops/controls/requests/${RID}/step-up/verify`,
        `/api/v2/ops/controls/requests/${RID}/approve`,
      ])
      expect(calls[0].body).toMatchObject({ kind: 'setting.set', params: { key: 'comms.sms.enabled', value: true } })
      expect(calls[0].body?.actor).toBeUndefined()
    })

    test(`gateway mode and lane switches use the governed kinds (${width})`, async ({ page }) => {
      const calls: Call[] = []
      await mock(page, calls)
      await page.goto('/v3/system/ops-controls?tab=toggles')
      await expect(page.getByTestId('toggle-gateway-evidence')).toContainText('failed 3', { timeout: 60_000 })
      await expect(page.getByTestId('toggle-gateway-OFF')).toBeDisabled()
      await page.getByTestId('toggle-lane-search').fill('cio-pro')
      await expect(page.getByTestId('toggle-lane-row')).toHaveCount(1)
      await page.getByTestId('toggle-lane-cio-prospect-shadow').click()
      await approveInSheet(page, width, 'ADD LIVE cio-prospect-shadow 2026-10-25')
      expect(calls[0].body).toMatchObject({ kind: 'n8n_live_list.add', params: { lane_id: 'cio-prospect-shadow' } })
    })

    test(`test text needs confirmation; nothing is sent before it (${width})`, async ({ page }) => {
      const calls: Call[] = []
      await mock(page, calls)
      await page.goto('/v3/system/ops-controls?tab=toggles')
      await page.getByTestId('toggle-sms-test').click({ timeout: 60_000 })
      const sheet = page.getByTestId('ops-test-send-sheet')
      await expect(sheet).toBeVisible()
      await expect(sheet).toContainText('••••••4567@msg.fi.google.com')
      expect(calls.filter(c => c.path.endsWith('/test-send'))).toHaveLength(0)
      await fullScreen(page, sheet, width)
      await minTarget(page, 'ops-test-send-confirm')
      await sheet.getByRole('button', { name: 'Cancel' }).click()
      await expect(sheet).toBeHidden()
      expect(calls.filter(c => c.path.endsWith('/test-send'))).toHaveLength(0)
      await page.getByTestId('toggle-sms-test').click()
      await page.getByTestId('ops-test-send-confirm').click()
      await expect(page.getByTestId('ops-test-send-result')).toContainText('Not sent: delivery_blocked_mode (gateway mode OFF)')
      const sends = calls.filter(c => c.path.endsWith('/test-send'))
      expect(sends).toHaveLength(1)
      expect(sends[0].body).toMatchObject({ channel: 'sms', confirm: true })
      await page.screenshot({ path: `${SHOTS}/ops-toggles-test-send-${width}.png` })
    })

    test(`text address is validated before a preview can start (${width})`, async ({ page }) => {
      const calls: Call[] = []
      await mock(page, calls)
      await page.goto('/v3/system/ops-controls?tab=toggles')
      await page.getByTestId('toggle-sms-address-edit').click({ timeout: 60_000 })
      const save = page.getByTestId('toggle-sms-address-save')
      await page.getByTestId('toggle-sms-address-input').fill('555-123-4567@gmail.com')
      await expect(save).toBeDisabled()
      await page.getByTestId('toggle-sms-address-input').fill('5551234567@VTEXT.com')
      await expect(save).toBeEnabled()
      await save.click()
      await expect(page.getByTestId('ops-controls-modal')).toBeVisible()
      expect(calls[0].body).toMatchObject({ kind: 'setting.set', params: { key: 'comms.sms.operator_email', value: '5551234567@vtext.com' } })
    })
  })
}
