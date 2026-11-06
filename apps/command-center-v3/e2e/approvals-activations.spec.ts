/** Approvals › Activations: reconciled packets at 412/390/1440. Synthetic fixtures only. No production calls, no writes.
 *
 *   npm run build && npm run preview -- --port 4193 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4193 npx playwright test e2e/approvals-activations.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

test.use({ hasTouch: true })

const row = (id: string, title: string, proposed_by: string, created_at: string | null, extra: Record<string, unknown> = {}) => ({
  id, kind: 'ACTIVATE', title, proposed_by, created_at, source: 'design_registry', governed_href: '/coordination?tab=work',
  decision_mode: 'GOVERNED_PATH', requires_governed_action: true, related_sources: [], source_refs: [], pr: null,
  document_sha: 'a'.repeat(64), version: id.replace('design:', ''), ...extra,
})

function queue() {
  return {
    items: [row('design:fixture-waiting-20320101', 'Fixture packet: switch the widget on', 'vendor/agent-x (claim)', '2032-01-01T12:00:00Z',
      { reconcile: { state: 'WAITING', evidence: ['lane fixture-lane: state NEVER_SCHEDULED (needs ACTIVE)'], reason: 'Waiting: lane fixture-lane: state NEVER_SCHEDULED (needs ACTIVE).' } })],
    resolved: [
      row('design:fixture-live-20311230', 'Fixture packet already applied', 'platform', '2031-12-30T12:00:00Z',
        { reconcile: { state: 'LIVE', evidence: ['lane fixture-live ACTIVE on n8n'], reason: 'Already live: lane fixture-live ACTIVE on n8n.', note: 'Fixture note.' } }),
      row('design:fixture-old-policy-20311229', 'Fixture policy package', 'unknown — the packet README names no owner, and no claim or commit trailer names an agent', null,
        { reconcile: { state: 'SUPERSEDED', evidence: [], reason: 'Superseded: the package was built on AGENTS.md 9.0.0.' } }),
    ],
    pending_count: 1, known_pending_count: 1, complete: true, gaps: [], as_of: '2032-01-02T12:00:00Z', recent: [], filtered_count: 1, offset: 0,
  }
}

async function stub(page: Page) {
  const writes: string[] = []
  await page.clock.setFixedTime(new Date('2032-01-03T12:00:00Z'))
  await page.route('**/api/**', route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${path}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/api/v2/governance/approvals') return json({ ok: true, data: queue() })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`Activations: humane titles, proposer, age; resolved behind a toggle ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await stub(page)
    await page.goto('/v3/approvals?tab=ACTIVATE')
    const waiting = page.locator('[aria-label="Waiting approvals"] .queue-row')
    await expect(waiting).toHaveCount(1)
    await expect(waiting.first()).toContainText('Fixture packet: switch the widget on')
    await expect(waiting.first()).toContainText('vendor/agent-x (claim)')
    await expect(waiting.first()).toContainText('2 d')
    await expect(page.getByText('Proposer not recorded')).toHaveCount(0)
    await expect(page.getByText('Fixture packet already applied')).toHaveCount(0)
    const toggle = page.getByTestId('approvals-resolved-toggle')
    await expect(toggle).toHaveText(/Show resolved activations \(2\)/)
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    if (width < 821) await toggle.tap(); else await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const resolved = page.getByTestId('approvals-resolved-row')
    await expect(resolved).toHaveCount(2)
    await expect(resolved.nth(0)).toContainText('Already live')
    await expect(resolved.nth(0)).toContainText('Already live: lane fixture-live ACTIVE on n8n.')
    await expect(resolved.nth(0)).toContainText('Fixture note.')
    await expect(resolved.nth(0)).toContainText('Proposed by platform')
    await expect(resolved.nth(1)).toContainText('Superseded')
    await expect(resolved.nth(1)).toContainText('unknown — the packet README names no owner')
    await expect(resolved.nth(1)).toContainText('date unknown')
    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(1)
    if (width < 821) await toggle.tap(); else await toggle.click()
    await expect(resolved).toHaveCount(0)
    expect(writes).toEqual([])
  })
}
