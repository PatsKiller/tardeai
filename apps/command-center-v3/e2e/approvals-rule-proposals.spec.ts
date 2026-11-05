import { test, expect, type Locator } from '@playwright/test'
import { build } from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Batch 35: pending AI rule proposals appear in the Approvals Center queue and open the proposal sheet on the
// Conflict rules page (the only place they are decided). Every request is intercepted; no POST leaves the browser.
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const bundle = await build({ entryPoints: [path.join(app, 'e2e/approvals-rule-proposals.fixture.tsx')], bundle: true, write: false,
  outfile: 'approvals-rule-proposals.js', define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const VIEW = JSON.parse(fs.readFileSync(path.join(app, 'e2e/fixtures/conflict-rulebook-view.json'), 'utf8'))
const ORIGIN = 'http://w11-approvals-fixture.test'
const at = '2032-04-12T13:00:00Z'
const proposal = {
  schema: 'RuleProposal@v1', proposal_id: 'rp-fixture-1', status: 'PENDING', revision: 7, signature: 'ups-fixture-a',
  summary: "Advisory desk says 'HEDGE', which no vocabulary rule maps (R8)", plain_rule: 'Treat HEDGE from the advisory desk as the same stance as HOLD.',
  tier: 'T4', never_auto: false, proposed_resolution: [], risks: ['May hide a real reduce signal'], test_cases: [{ expected: { kind: 'AGREEMENT' } }],
  model: { provider: 'grok', model_id: 'fixture-model', mock: false }, created_at: at, decision: null,
}
// Exactly what operator_approvals_api's conflict_rule_proposals source projects for that proposal (queue card form).
const queueItems = [
  { id: 'rule-proposal:rp-fixture-1', kind: 'CONFLICT', title: `Proposed conflict rule: ${proposal.summary}`, proposed_by: 'AI rule proposer (grok)',
    created_at: at, source: 'conflict_rule_proposals', pr: null, governed_href: '/conflicts/rules?proposal=rp-fixture-1', decision_mode: 'GOVERNED_PATH',
    requires_governed_action: true, related_sources: [], document_sha: 'c'.repeat(64), version: 'revision 7 · T4' },
  { id: 'conflict:abc', kind: 'CONFLICT', title: 'Desk and CIO disagree on FIXT', proposed_by: 'conflict engine', created_at: at, source: 'conflicts', pr: null,
    governed_href: '/watch?conflict=k', decision_mode: 'GOVERNED_PATH', requires_governed_action: true, related_sources: [], document_sha: 'd'.repeat(64), version: '1' },
]

test.use({ hasTouch: true })
test.setTimeout(60_000)
for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`AI rule proposal: Approvals queue → proposal sheet → ← Back (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const posts: string[] = [], forbidden: string[] = [], errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== ORIGIN) { forbidden.push(request.method() + ' ' + url.origin); return route.abort() }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      if (request.method() !== 'GET') { posts.push(request.method() + ' ' + url.pathname); return route.fulfill({ status: 403, json: { ok: false, error: 'fixture: no writes' } }) }
      if (url.pathname === '/api/v2/governance/approvals') {
        const kind = url.searchParams.get('kind'), rows = queueItems.filter(item => !kind || item.kind === kind)
        return route.fulfill({ json: { ok: true, data: { items: rows, pending_count: 2, known_pending_count: 2, complete: true, gaps: [], as_of: at, recent: [], filtered_count: rows.length, offset: 0 } } })
      }
      if (url.pathname === '/api/v3/conflicts/rulebook') return route.fulfill({ json: { ok: true, data: VIEW } })
      if (url.pathname === '/api/v3/conflicts/proposals') return route.fulfill({ json: { ok: true, data: { schema: 'RuleProposalCollection@v1', proposals: [proposal], total: 1, offset: 0,
        counts: { pending: 1, approved: 0, rejected: 0, unmatched_awaiting_ai: 0 }, unmatched: [], decisions_enabled: false } } })
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

    await page.goto(ORIGIN + '/approvals')
    await expect(page.getByRole('heading', { name: 'Approvals Center', exact: true })).toBeVisible()
    await tap(page.getByRole('button', { name: 'Conflicts', exact: true }))
    const row = page.locator('.queue-row').filter({ hasText: 'Proposed conflict rule' })
    await expect(row.locator('.badge')).toHaveText('AI rule proposal')
    await expect(row).toContainText('AI rule proposer (grok)')
    await expect(row).toContainText('revision 7 · T4')
    // An ordinary conflict keeps the existing reader link; only the proposal deep-links to its sheet.
    await expect(page.locator('.queue-row').filter({ hasText: 'Desk and CIO disagree' }).getByRole('link', { name: 'Read & decide' })).toBeVisible()
    await noOverflow()
    await page.screenshot({ path: testInfo.outputPath(`approvals-rule-proposal-queue-${width}.png`), fullPage: true })

    await tap(row.getByRole('link', { name: 'Review proposal →' }))
    await expect(page).toHaveURL(/\/conflicts\/rules\?proposal=rp-fixture-1$/)
    const sheet = page.getByRole('dialog', { name: 'Proposed rule' })
    await expect(sheet).toBeInViewport()
    expect((await sheet.boundingBox())!.width).toBeGreaterThanOrEqual(width - 1)
    await expect(sheet.getByTestId('cr-proposal-detail')).toContainText(proposal.plain_rule)
    // Decisions stay on this page and are still gated by activation; nothing is decided from the queue.
    await expect(sheet.getByTestId('cr-decisions-disabled')).toBeVisible()
    const choices = sheet.getByRole('radio')
    expect(await choices.count()).toBeGreaterThanOrEqual(3)
    for (const choice of await choices.all()) await expect(choice).toBeDisabled()
    await noOverflow()
    await page.screenshot({ path: testInfo.outputPath(`approvals-rule-proposal-sheet-${width}.png`) })

    await tap(sheet.getByRole('button', { name: '← Back' }))
    await expect(page).toHaveURL(/\/approvals(\?tab=CONFLICT)?$/)
    await expect(page.getByRole('heading', { name: 'Approvals Center', exact: true })).toBeVisible()
    await expect(page.locator('.queue-row').filter({ hasText: 'Proposed conflict rule' })).toBeVisible()
    await noOverflow()
    expect(posts).toEqual([]); expect(forbidden).toEqual([]); expect(errors).toEqual([])
  })
}
