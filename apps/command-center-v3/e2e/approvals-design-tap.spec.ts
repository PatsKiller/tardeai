// Lost design approval 2026-10-31: two phone taps on Approve recorded nothing and said nothing.
// A design-registry design is decided only on its work-pipeline card (passkey + typed words), so the reader shows
// that link on the first phone screen; a RECORD item's Approve tap before reading explains why, and posts nothing.
import { test, expect } from '@playwright/test'
import { build } from 'esbuild'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const bundle = await build({ entryPoints: [path.join(app, 'e2e/approvals.fixture.tsx')], bundle: true, write: false,
  outfile: 'approvals.js', define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const ORIGIN = 'http://design-tap-fixture.test'
const text = '---\nid: DSN-20320412-demo-ui\nstatus: PROPOSED\n---'
const lines = text.split('\n')
const doc = { text, base_text: '', source_sha: 'a'.repeat(40), version: 'DSN-20320412-demo-ui', document_sha: 'b'.repeat(64),
  source_verified: false, sections: ['Document'],
  changes: lines.map((after, i) => ({ id: `change_${i}`, section: 'Document', before: '', after, after_offset: text.indexOf(after), kind: 'added' })),
  prechecks: { sensitive_sections: [], removed_blocks: 0, weakens_rules: 'NOT_ASSESSED', policy_tests: { state: 'UNKNOWN' } } }
const items = [
  { id: 'design:DSN-20320412-demo-ui', title: 'Demo design', kind: 'DESIGN', proposed_by: 'Fixture agent', created_at: null,
    source: 'design_registry', document: doc, decision_mode: 'GOVERNED_PATH', governed_href: '/coordination?design=DSN-20320412-demo-ui' },
  { id: 'policy:42', title: 'Policy fixture', kind: 'POLICY', proposed_by: 'Fixture agent', created_at: null, source: 'fixture',
    document: doc, pr: 42, decision_mode: 'RECORD', governed_href: null },
]

test.use({ hasTouch: true })
for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`design approve tap is never a silent no-op ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const posts: string[] = []
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== ORIGIN) return route.abort()
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      if (request.method() !== 'GET') { posts.push(request.method() + ' ' + url.pathname); return route.fulfill({ status: 409, json: { ok: false, error: 'UNEXPECTED' } }) }
      const item = items.find(i => decodeURIComponent(url.pathname) === '/api/v2/governance/approvals/' + i.id)
      return item ? route.fulfill({ json: { ok: true, data: item } }) : route.fulfill({ status: 404, json: { ok: false, error: 'NOT_FOUND' } })
    })

    // Design: the governed link is on the first screen, before any reading, and opens the design's pipeline card.
    await page.goto(`${ORIGIN}/approvals/${encodeURIComponent('design:DSN-20320412-demo-ui')}`)
    const link = page.getByTestId('governed-decision-link').first()
    await expect(link).toHaveText('Approve this design with your passkey →')
    const box = (await link.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)
    expect(box.y + box.height).toBeLessThanOrEqual(height)
    await expect(page.getByTestId('governed-decision')).toContainText('nothing on this page records it')
    await expect(page.getByTestId('approve-button')).toHaveCount(0)
    await link.tap()
    await expect(page).toHaveURL(`${ORIGIN}/coordination?design=DSN-20320412-demo-ui`)
    await expect(page.getByRole('heading', { name: 'Work pipeline' })).toBeVisible()

    // RECORD item: Approve before reading says why, visibly, and sends nothing.
    await page.goto(`${ORIGIN}/approvals/${encodeURIComponent('policy:42')}`)
    const approve = page.getByTestId('approve-button')
    await approve.scrollIntoViewIfNeeded()
    await approve.tap()
    const alert = page.getByRole('alert')
    await expect(alert).toHaveText('Approval not recorded: tap "Start reading" first, then read every highlighted change.')
    await expect(alert).toBeInViewport()
    expect(posts).toEqual([])
  })
}
