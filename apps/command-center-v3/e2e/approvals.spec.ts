import { test, expect, type Locator } from '@playwright/test'
import { build } from 'esbuild'
import fs from 'node:fs'
import crypto from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const bundle = await build({ entryPoints: [path.join(app, 'e2e/approvals.fixture.tsx')], bundle: true, write: false,
  metafile: true, outfile: 'approvals.js', define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const files = Object.keys(bundle.metafile!.inputs).map(f => path.resolve(app, f)).filter(f => f.startsWith(path.join(app, 'src') + path.sep))
const sourceHashes = Object.fromEntries(files.map(f => [path.relative(app, f), crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')]))
const sourceSha = 'a'.repeat(40), documentSha = 'b'.repeat(64)
const text = '# 28 · Operations\n\nEvery page names its source.\n\nChanges need an operator review.'
const changes = ['Every page names its source.', 'Changes need an operator review.'].map((after, index) => ({
  id: `change_${index}`, section: '28 · Operations', before: '', after, after_offset: text.indexOf(after), kind: 'added',
  plain: index ? 'You review changes before they take effect.' : 'Each page tells you where its facts came from.', reason: 'Synthetic fixture requirement. '.repeat(24),
}))
const fixtureDocument = { text, base_text: '# 28 · Operations', source_sha: sourceSha, version: '20.2.0', document_sha: documentSha,
  source_verified: true, changes, sections: ['28 · Operations'], prechecks: { sensitive_sections: [], removed_blocks: 0, weakens_rules: 'NOT_ASSESSED', policy_tests: { state: 'UNKNOWN' } } }
const items = [
  { id: 'policy:42', title: 'Policy review fixture', kind: 'POLICY', proposed_by: 'Fixture author', created_at: '2032-04-12T13:00:00Z', source: 'fixture', document: fixtureDocument, pr: 42, decision_mode: 'RECORD', governed_href: null },
  { id: 'activation:7', title: 'Activation review fixture', kind: 'ACTIVATE', proposed_by: 'Fixture author', created_at: null, source: 'fixture', document: fixtureDocument, decision_mode: 'GOVERNED_PATH', governed_href: '/system/ops-controls' },
]
test.use({ hasTouch: true })
test.setTimeout(90_000)
for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1100 }]) {
  test(`boards 19-21 actual tap flows and visible result ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    await page.clock.install({ time: new Date('2032-04-12T14:00:00Z') })
    const requests: string[] = [], forbidden: string[] = [], errors: string[] = [], read = new Set<string>()
    let approvedReadMarkers: string[] = []
    const decisions: unknown[] = [], feedback: unknown[] = [], questions: Record<string, unknown>[] = []
    page.on('pageerror', error => errors.push(error.message))
    const tap = async (target: Locator) => {
      // A filter tap refetches the queue and re-renders its rows; re-resolve until the target is stable on screen.
      await expect(async () => {
        await target.scrollIntoViewIfNeeded()
        const box = await target.boundingBox()
        expect(box).not.toBeNull(); expect(box!.height).toBeGreaterThanOrEqual(44)
        expect(box!.y).toBeGreaterThanOrEqual(0); expect(box!.y + box!.height).toBeLessThanOrEqual(height + 1)
      }).toPass({ timeout: 10_000 })
      if (width <= 820) await target.tap(); else await target.click()
    }
    const visible = async (target: Locator) => {
      await expect(target).toBeVisible()
      const box = await target.boundingBox()
      expect(box).not.toBeNull(); expect(box!.y).toBeGreaterThanOrEqual(0); expect(box!.y + box!.height).toBeLessThanOrEqual(height + 1)
    }
    const screenshot = async (board: number, state: string) => {
      const name = `impl-${board}-${state}-${width}.png`
      await page.screenshot({ path: process.env.DESK_SHOTS_DIR ? path.join(process.env.DESK_SHOTS_DIR, name) : testInfo.outputPath(name), fullPage: true })
    }
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== 'http://w11-approvals-fixture.test') { forbidden.push(request.method() + ' ' + url.origin + url.pathname); return route.abort() }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      requests.push(request.method() + ' ' + url.pathname)
      const respond = (data: unknown) => route.fulfill({ json: { ok: true, data } })
      if (url.pathname === '/api/v2/governance/approvals' && request.method() === 'GET') {
        const kind = url.searchParams.get('kind')
        const rows = items.filter(item => !kind || item.kind === kind).map(({ document: d, ...item }) => ({ ...item, document_sha: d.document_sha, version: d.version }))
        return respond({ items: rows, pending_count: 2, known_pending_count: 2, complete: true, gaps: [], as_of: '2032-04-12T14:00:00Z', recent: decisions, filtered_count: rows.length, offset: 0 })
      }
      if (url.pathname === '/api/v2/governance/policy' && request.method() === 'GET') {
        const chapter = url.searchParams.get('section') || ''
        const documentView = url.searchParams.get('view') === 'document'
        const rules = [
          { id: 'rule_0', section: '0 · Rules', text: 'MBI_BEHAVIOR = 0.', plain: 'Agents never size or order.', status: 'WRITTEN-only', reason: 'Audit not run', evidence: {} },
          { id: 'rule_1', section: '28 · Operations', text: 'An agent may propose a change. The operator decides.', plain: 'You make decisions; agents prepare proposals.', status: 'WRITTEN-only', reason: 'Audit not run', evidence: {} },
        ]
        const selected = chapter ? rules.filter(r => r.section.includes(chapter.replace(/\+/g, ' ')) || r.section.startsWith(chapter.split('·')[0].trim())) : rules
        // Document view returns the full Rulebook; section filter still scopes when present.
        const shown = documentView ? (chapter ? selected : rules) : selected.slice(0, 40)
        return respond({ source_sha: sourceSha, document_sha: documentSha, policy_version: '24.0.0', last_reviewed: '2032-04-12T14:00:00Z',
          sections: ['0 · Rules', '28 · Operations'], section_counts: { '0 · Rules': 1, '28 · Operations': 1 },
          rules: shown, counts: { RULES: 2, ENFORCED: null, TESTED: null, 'WRITTEN-only': 2, VIOLATED: null },
          counts_measured: false, total_rules: 2, section_total: shown.length, offset: 0, view: documentView ? 'document' : 'paged', positions: feedback,
          audit: { state: 'NOT_MEASURED', last_audit: null, reason: 'The enforcement audit has not run against this policy version.' } })
      }
      // The reader encodes ids (policy:42 -> policy%3A42) exactly as the server receives them; the API decodes.
      const item = items.find(item => decodeURIComponent(url.pathname) === '/api/v2/governance/approvals/' + item.id)
      if (item && request.method() === 'GET') return respond(item)
      if (request.method() === 'POST') {
        const body = request.postDataJSON()
        if (url.pathname.endsWith('/open')) { expect(body.document_sha).toBe(documentSha); read.clear(); return respond({ review_id: 'fixture-review' }) }
        if (url.pathname.endsWith('/read')) { expect(body.document_sha).toBe(documentSha); if (body.phase === 'read') read.add(body.change_id); return respond(body) }
        if (url.pathname.endsWith('/decide')) {
          expect(body.document_sha).toBe(documentSha); expect(body.review_id).toBe('fixture-review')
          if (body.decision === 'APPROVE') { expect(read.size).toBe(changes.length); approvedReadMarkers = [...read] }
          const result = { ...body, actor: 'tailnet:operator@example.test', at: '2032-04-12T14:01:00Z', item_id: 'policy:42' }
          decisions.push(result); return respond(result)
        }
        if (url.pathname === '/api/v2/governance/policy/feedback') { feedback.push(body); return respond(body) }
        if (url.pathname === '/api/v2/cio/ask') { questions.push(body); return respond({ thread_id: 'thr_fixture' }) }
      }
      forbidden.push(request.method() + ' ' + url.pathname); return route.abort()
    })
    await page.goto('http://w11-approvals-fixture.test/approvals')
    await expect(page.getByRole('heading', { name: 'Approvals Center', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await screenshot(19, 'waiting')
    await tap(page.getByRole('button', { name: 'Policy', exact: true }))
    await expect(page.getByText('Activation review fixture', { exact: true })).toHaveCount(0)
    await tap(page.getByRole('link', { name: 'Read & decide', exact: true }))
    await visible(page.getByRole('heading', { name: 'Policy review fixture', exact: true }))
    const approve = page.getByRole('button', { name: /^Approve/ })
    await expect(approve).toBeDisabled()
    await tap(page.getByRole('button', { name: 'Start reading', exact: true }))
    for (const change of changes) {
      await page.locator(`[data-read-target="${change.id}"]`).scrollIntoViewIfNeeded()
      await page.clock.runFor(3400)
      await expect(page.locator(`[data-change-id="${change.id}"]`).getByRole('heading')).toContainText('Read')
    }
    await expect(approve).toBeEnabled()
    await tap(page.getByRole('button', { name: 'Whole document, highlighted', exact: true }))
    await expect(page.getByRole('heading', { name: 'Whole document, highlighted', exact: true })).toBeVisible()
    await tap(page.getByRole('button', { name: 'Side by side', exact: true }))
    await expect(page.getByRole('heading', { name: 'Before', exact: true })).toBeVisible()
    await tap(page.getByRole('button', { name: 'Changes only', exact: true }))
    await screenshot(20, 'read')
    await tap(approve)
    await visible(page.getByText('Decision recorded', { exact: true }))
    expect(decisions).toHaveLength(1)
    await screenshot(20, 'decided')
    await tap(page.getByRole('link', { name: 'Return to approvals', exact: true }))
    await tap(page.getByRole('button', { name: 'Policy', exact: true }))
    await tap(page.getByRole('link', { name: 'Read & decide', exact: true }))
    await tap(page.getByRole('button', { name: 'Start reading', exact: true }))
    await page.getByLabel('Decision comment').fill('Please explain the proposed source rule.')
    await tap(page.getByRole('button', { name: 'Request changes', exact: true }))
    await visible(page.getByText('Decision recorded', { exact: true }))
    await tap(page.getByRole('link', { name: 'Return to approvals', exact: true }))
    await tap(page.getByRole('button', { name: 'Policy', exact: true }))
    await tap(page.getByRole('link', { name: 'Read & decide', exact: true }))
    await tap(page.getByRole('button', { name: 'Start reading', exact: true }))
    await tap(page.getByRole('button', { name: 'Reject', exact: true }))
    await visible(page.getByText('Decision recorded', { exact: true }))
    expect(decisions).toHaveLength(3)
    await tap(page.getByRole('link', { name: 'Return to approvals', exact: true }))
    await tap(page.getByRole('button', { name: 'Policy', exact: true }))
    await tap(page.getByRole('link', { name: 'Read & decide', exact: true }))
    await page.getByLabel('Question about this change').fill('Why is this change needed?')
    await tap(page.getByRole('button', { name: 'Ask the CIO with this section', exact: true }))
    await visible(page.getByRole('heading', { name: 'Question sent to the CIO', exact: true }))
    expect(questions[0].question).toContain(documentSha)
    await page.goBack()
    await tap(page.getByRole('link', { name: 'Back to approvals', exact: false }))
    await tap(page.getByRole('button', { name: 'Activations', exact: true }))
    await tap(page.getByRole('link', { name: 'Read & decide', exact: true }))
    await tap(page.getByRole('link', { name: 'Continue to operator controls', exact: true }))
    await visible(page.getByRole('heading', { name: 'Existing operator controls', exact: true }))
    await page.goBack()
    await visible(page.getByRole('heading', { name: 'Activation review fixture', exact: true }))
    await tap(page.getByRole('link', { name: 'Back to approvals', exact: false }))
    await tap(page.getByRole('link', { name: 'Open Rulebook', exact: true }))
    await visible(page.getByTestId('rulebook-document'))
    await tap(page.getByTestId('rulebook-chapter').filter({ hasText: '28 · Operations' }))
    await expect(page).toHaveURL(/section=28/)
    await tap(page.getByTestId('rulebook-section').filter({ hasText: '28 · Operations' }).getByRole('button', { name: 'Propose a change', exact: true }))
    await page.getByLabel('Rule response comment').fill('Please clarify this operator-review rule.')
    await tap(page.getByRole('button', { name: 'Propose change in Approvals', exact: true }))
    await visible(page.getByRole('status').filter({ hasText: 'Your proposed change is now in Approvals.' }))
    await screenshot(21, 'proposal')
    await tap(page.getByTestId('rulebook-add-section'))
    await page.getByLabel('New section title').fill('29 · Observability standards')
    await page.getByLabel('Rule response comment').fill('Add a chapter for observability SLOs and receipts.')
    await tap(page.getByRole('button', { name: 'Propose section in Approvals', exact: true }))
    await visible(page.getByRole('status').filter({ hasText: 'Proposed new section is now in Approvals.' }))
    expect(feedback.some((row: { action?: string }) => row.action === 'add_section')).toBe(true)
    await tap(page.getByTestId('rulebook-section').filter({ hasText: '28 · Operations' }).getByRole('button', { name: 'Ask about this section', exact: true }))
    await page.getByLabel('Rule response comment').fill('What counts as a reviewed proposal?')
    await tap(page.getByRole('button', { name: 'Ask the CIO with this section', exact: true }))
    await visible(page.getByRole('heading', { name: 'Question sent to the CIO', exact: true }))
    expect(questions[1].question).toContain(documentSha)
    expect(questions[1].question).toContain('An agent may propose a change.')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(forbidden).toEqual([]); expect(errors).toEqual([])
    fs.writeFileSync(testInfo.outputPath(`viewport-proof-${width}.json`), JSON.stringify({ width, height, sourceHashes, requests,
      forbidden, errors, decisions: decisions.length, feedback: feedback.length, questions: questions.length,
      readMarkers: approvedReadMarkers, proof: 'Real browser taps, viewport bounds, actual W11 components; synthetic intercepted APIs only.' }, null, 2))
  })
}
