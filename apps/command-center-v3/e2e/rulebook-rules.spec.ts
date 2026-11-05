/** Rulebook rule model at 412/390/1440. Synthetic fixtures only. No production calls, no writes.
 *
 *   npm run build && npm run preview -- --port 4192 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4192 npx playwright test e2e/rulebook-rules.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

test.use({ hasTouch: true })

const SHA = 'f'.repeat(40)

function policy(measured: boolean) {
  const rules = [
    { id: 'rule_a', section: '0 · Fixture rules', subsection: null, number: '1', text: '**Never fixture-delete.** Archive the `fixture` instead.', plain: 'Keep records.', status: 'WRITTEN-only', reason: measured ? 'No evidence for this document version' : 'Audit not run', evidence: {} },
    { id: 'rule_b', section: '0 · Fixture rules', subsection: '0.1 Sub-heading', number: null, text: 'See [the guide](https://example.test/guide) first.\n- a nested point', plain: null, status: 'WRITTEN-only', reason: 'Audit not run', evidence: {} },
    { id: 'rule_c', section: '1 · Prose section', subsection: null, number: null, text: 'Propose and stop.', plain: null, status: 'WRITTEN-only', reason: 'Audit not run', evidence: {} },
  ]
  return {
    source_sha: SHA, document_sha: 'd'.repeat(64), sections: ['0 · Fixture rules', '1 · Prose section'],
    section_counts: { '0 · Fixture rules': 2, '1 · Prose section': 1 }, section_status: measured ? { '0 · Fixture rules': 'TESTED', '1 · Prose section': 'WRITTEN-only' } : {},
    rules, total_rules: 3, section_total: 3, offset: 0, positions: [],
    counts: measured ? { RULES: 3, ENFORCED: 0, TESTED: 1, 'WRITTEN-only': 2, VIOLATED: 0 } : { RULES: 3, ENFORCED: null, TESTED: null, 'WRITTEN-only': 3, VIOLATED: null },
    counts_measured: measured,
    audit: measured
      ? { state: 'PARTIAL', last_audit: '2032-01-04T01:00:00Z', last_run: null, reason: null }
      : { state: 'NOT_MEASURED', last_audit: null, last_run: '2032-01-03T01:00:00Z', reason: 'The last enforcement audit run does not match the served policy version, so its results are not shown.' },
  }
}

async function stub(page: Page, measured: boolean) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${path}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/api/v2/governance/policy') return json({ ok: true, data: policy(measured) })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`Rulebook shows rules as text, grouped by section, audit not run ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await stub(page, false)
    await page.goto('/v3/policy')
    await expect(page.getByTestId('rulebook-rule')).toHaveCount(3)
    await expect(page.getByTestId('rulebook-section-heading')).toHaveText(['0 · Fixture rules', '1 · Prose section'])
    const first = page.getByTestId('rulebook-rule-text').first()
    await expect(first).toHaveText('Never fixture-delete. Archive the fixture instead.')
    await expect(first.locator('strong')).toHaveText('Never fixture-delete.')
    await expect(first.locator('code')).toHaveText('fixture')
    const second = page.getByTestId('rulebook-rule-text').nth(1)
    await expect(second.getByRole('link', { name: 'the guide' })).toHaveAttribute('href', 'https://example.test/guide')
    await expect(second.locator('li')).toHaveText('a nested point')
    const body = await page.locator('article[aria-label="Policy rules"]').innerText()
    expect(body).not.toMatch(/\*\*|`|\]\(/)
    for (const key of ['ENFORCED', 'TESTED', 'VIOLATED']) await expect(page.getByTestId(`rulebook-count-${key}`)).toContainText('Audit not run')
    await expect(page.getByTestId('rulebook-count-RULES')).toContainText('3')
    await expect(page.getByTestId('rulebook-audit-gap')).toContainText('does not match the served policy version')
    await expect(page.getByTestId('rulebook-audit-gap')).toContainText('Last run')
    await expect(page.getByTestId('rulebook-last-audit')).toContainText('Not run')
    await expect(page.getByLabel('Rulebook section').locator('option')).toHaveText(['All sections', '0 · Fixture rules (2)', '1 · Prose section (1)'])
    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(1)
    if (width < 821) {
      const agree = page.getByTestId('rulebook-rule').first().getByRole('button', { name: 'Agree', exact: true })
      expect((await agree.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await agree.tap()
      const sheet = page.getByRole('dialog', { name: 'Rule response' })
      await expect(sheet).toBeVisible()
      await expect(sheet).toContainText('Never fixture-delete. Archive the fixture instead.')
      await expect(sheet).not.toContainText('**')
      await sheet.getByRole('button', { name: '← Back to Rulebook' }).tap()
      await expect(sheet).toHaveCount(0)
    }
    expect(writes).toEqual([])
  })

  test(`Rulebook shows measured counts once the audit binds the version ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await stub(page, true)
    await page.goto('/v3/policy')
    await expect(page.getByTestId('rulebook-count-TESTED')).toContainText('1')
    await expect(page.getByTestId('rulebook-count-ENFORCED')).toContainText('0')
    await expect(page.getByTestId('rulebook-audit-gap')).toHaveCount(0)
    await expect(page.getByTestId('rulebook-last-audit')).not.toContainText('Not run')
    await expect(page.getByLabel('Rulebook section').locator('option').nth(1)).toHaveText('✓ 0 · Fixture rules (2)')
  })
}
