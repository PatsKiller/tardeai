import { test, expect, type Locator } from '@playwright/test'
import { build } from 'esbuild'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Rulebook → Policy versions: the version in force, a PROPOSED version from an open PR, the full-screen sheet, the
// confirm step and "Approve version X". Every request is intercepted; only the fixture approve POST is answered.
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const bundle = await build({ entryPoints: [path.join(app, 'e2e/policy-versions.fixture.tsx')], bundle: true, write: false,
  outfile: 'policy-versions.js', define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const ORIGIN = 'http://policy-versions-fixture.test'
const at = '2032-04-12T13:00:00Z'
const HEAD = 'b'.repeat(40)
const TOKEN = `APPROVE_AGENTS_POLICY_20_4_0 2120 ${HEAD}`
const policy = { source_sha: 'a'.repeat(40), document_sha: 'd'.repeat(64), sections: ['28 · Operations'], counts: { ENFORCED: 0, TESTED: 0, 'WRITTEN-only': 1, VIOLATED: 0 },
  rules: [{ id: 'rule_1', section: '28 · Operations', text: 'Read every change.', plain: null, status: 'WRITTEN-only', reason: null, evidence: {} }],
  total_rules: 1, section_total: 1, offset: 0, positions: [], audit: { state: 'NOT_MEASURED', last_audit: null } }
const pendingRow = (read: number, decision: unknown = null) => ({ id: 'policy:2120', pr: 2120, title: 'AGENTS.md 20.4.0 PROPOSED — hands-off delivery for the train systems', proposed_by: 'PatsKiller',
  created_at: at, version: '20.4.0', status: 'PROPOSED', row_status: 'PROPOSED', classification: 'MINOR', awaits_token: true, head_sha: HEAD, document_sha: 'e'.repeat(64),
  changes: 4, sensitive_sections: [], token: TOKEN, decision, earlier_head_decisions: 0, review: { started: read > 0, read, total: 4, expired: false }, can_approve: !decision })
const versions = (read: number, decision: unknown = null) => ({ current: { version: '20.3.0', status: 'ACTIVE', effective_date: '2032-04-01', supersedes: '20.2.0', row_status: 'ACTIVE',
  source_sha: 'a'.repeat(40), consistent: true, errors: [] }, pending: [pendingRow(read, decision)], pending_count: 1, known_pending_count: 1, complete: true, gaps: [], as_of: at,
  operator: true, github_write_path: null, approval_rule: 'x' })

test.use({ hasTouch: true })
test.setTimeout(60_000)
for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`Policy versions: list → full-screen sheet → confirm → approve (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const posts: { path: string; body: unknown }[] = [], forbidden: string[] = [], errors: string[] = []
    let state: { read: number; decision: unknown } = { read: 0, decision: null }
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== ORIGIN) { forbidden.push(request.method() + ' ' + url.origin); return route.abort() }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      if (request.method() === 'POST' && url.pathname === '/api/v2/governance/policy/versions/approve') {
        const body = request.postDataJSON(); posts.push({ path: url.pathname, body })
        const decision = { event: 'DECIDED', decision: 'APPROVE', actor: 'tailnet:operator@example.test', at, policy_token: TOKEN, effect: 'RECORD_ONLY' }
        state = { read: 4, decision: { ...decision, effect: 'RECORDED_AWAITING_RELAY', relay: 'The coordinator relays this exact token to PR #2120.' } }
        return route.fulfill({ json: { ok: true, data: { decision, effect: 'RECORDED_AWAITING_RELAY', relay: 'The coordinator relays this exact token to PR #2120.' } } })
      }
      if (request.method() !== 'GET') { forbidden.push(request.method() + ' ' + url.pathname); return route.fulfill({ status: 403, json: { ok: false, error: 'fixture: no writes' } }) }
      if (url.pathname === '/api/v2/governance/policy/versions') return route.fulfill({ json: { ok: true, data: versions(state.read, state.decision) } })
      if (url.pathname === '/api/v2/governance/policy') return route.fulfill({ json: { ok: true, data: policy } })
      return route.fulfill({ status: 404, json: { ok: false, error: 'fixture: not mocked' } })
    })
    const tap = async (target: Locator) => {
      await target.scrollIntoViewIfNeeded()
      const box = (await target.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      expect(box.y).toBeGreaterThanOrEqual(0); expect(box.y + box.height).toBeLessThanOrEqual(height + 1)
      await target.tap()
    }
    const noOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

    // Unread: the approve button is shown but disabled, and the reader link is the way forward.
    await page.goto(ORIGIN + '/policy')
    const panel = page.getByTestId('policy-versions')
    await expect(panel.getByTestId('policy-version-current')).toContainText('20.3.0')
    await expect(panel.getByTestId('policy-version-current')).toContainText('ACTIVE')
    const row = panel.getByTestId('policy-version-row')
    await expect(row).toContainText('Version 20.4.0'); await expect(row).toContainText('PR #2120')
    await noOverflow()
    await page.screenshot({ path: testInfo.outputPath(`policy-versions-list-${width}.png`), fullPage: true })
    await tap(row)
    await expect(page).toHaveURL(/\/policy\?version=2120$/)
    let sheet = page.getByRole('dialog', { name: 'Version 20.4.0' })
    await expect(sheet).toBeInViewport()
    expect((await sheet.boundingBox())!.width).toBeGreaterThanOrEqual(width - 1)
    await expect(sheet.getByTestId('policy-version-approve')).toBeDisabled()
    await expect(sheet.getByTestId('policy-version-approve')).toContainText('read every change first')
    await expect(sheet.getByRole('link', { name: 'Read the changes' })).toHaveAttribute('href', '/approvals/policy%3A2120')
    await tap(sheet.getByText('Exact head and token'))
    await expect(sheet.getByTestId('policy-version-token')).toHaveText(TOKEN)
    await noOverflow()
    await tap(sheet.getByRole('button', { name: '← Back to Rulebook' }))
    await expect(page).toHaveURL(/\/policy$/)

    // Every change read (in the reader): approve → confirm → recorded, awaiting relay.
    state = { read: 4, decision: null }
    await page.goto(ORIGIN + '/policy?version=2120')
    sheet = page.getByRole('dialog', { name: 'Version 20.4.0' })
    await expect(sheet.getByTestId('policy-version-read')).toHaveText('4 of 4')
    await tap(sheet.getByTestId('policy-version-approve'))
    const confirm = sheet.getByTestId('policy-version-confirm')
    await expect(confirm).toContainText(TOKEN)
    await page.screenshot({ path: testInfo.outputPath(`policy-versions-confirm-${width}.png`) })
    await tap(confirm.getByRole('button', { name: 'Cancel' }))
    expect(posts).toEqual([])
    await tap(sheet.getByTestId('policy-version-approve'))
    await tap(sheet.getByRole('button', { name: 'Yes, approve version 20.4.0' }))
    await expect(sheet.getByTestId('policy-version-decided')).toContainText('Version 20.4.0 approved')
    await expect(sheet.getByTestId('policy-version-decided')).toContainText('PR #2120')
    await noOverflow()
    await page.screenshot({ path: testInfo.outputPath(`policy-versions-approved-${width}.png`) })
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toMatchObject({ pr: 2120, head_sha: HEAD, version: '20.4.0', token: TOKEN })
    expect(forbidden).toEqual([]); expect(errors).toEqual([])
  })
}
