// Operator budget-intent control — phone acceptance fixture for the real component.
// Renders the actual BudgetIntentControl at 390 and 412 against mocked governance routes and proves the action path:
// the button exists only when the backend says a decision is available; preview writes nothing; a changed measurement
// refuses the write; the POST bodies carry no measured fields; every target is at least 44 px.
//   node e2e/budget-intent.fixture.mjs <outdir>
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })

const SHA = 'a'.repeat(64), OTHER = 'b'.repeat(64)
const TOMORROW = new Date(Date.now() + 24 * 3600 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import BudgetIntentControl from './src/components/home/BudgetIntentControl';
      import './src/index.css';
      const ROW = (over: any) => ({ key: 'demo_taxable', label: 'demo taxable', current: 21000, budget: 15000, unit: 'usd',
        clearsWhen: 'below 15000', breach: true, scopeId: 'account:demo', sourceAsOf: '2026-11-02T20:00:00Z',
        sourceSha: 'a'.repeat(64), presentationSha: 'b'.repeat(64), operatorDecision: 'available',
        decisionRemediation: null, decision: { active: false, intentionalUntil: null, actor: null, receipt: null, history: 0 },
        state: 'measured', asOf: '2026-11-02T20:00:00Z', source: 'market_risk_budgets', ageSeconds: null,
        reason: null, remediation: null, ...over });
      const params = new URLSearchParams(location.search);
      const variant = params.get('v') || 'available';
      const row = variant === 'unavailable'
        ? ROW({ operatorDecision: 'unavailable', decisionRemediation: 'pending reviewed route (pending_route)' })
        : ROW({});
      createRoot(document.getElementById('root')!).render(React.createElement(BudgetIntentControl, { row, onRecorded: () => { (window as any).recorded = ((window as any).recorded || 0) + 1 } }));`,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true, write: false, outdir: path.join(app, 'e2e/.intent-build'), format: 'esm', platform: 'browser', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent',
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const cssText = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const html = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${cssText}</style><body style="margin:0;padding:12px;background:#0b0d10;color:#e8e8e8;font:14px system-ui"><div id="root"></div><script type="module">${js.replace(/<\/script/gi, '<\\/script')}</script>`

async function run(page, width, variant, plan) {
  const seen = { gets: 0, posts: [], forbidden: [], dropped: false, lastWrite: null }
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
    if (url.pathname === '/api/v2/governance/budget-presentation') {
      seen.gets++
      const binding = plan.basisSha === 'changed' ? (seen.gets > 1 ? OTHER : SHA) : (plan.basisSha || SHA)
      const history = seen.lastWrite ? [{ request_id: seen.lastWrite.request_id, scope_id: 'account:demo', budget: 'demo_taxable',
        source_binding: { as_of: '2026-11-02T20:00:00Z', sha256: SHA }, intentional_until: seen.lastWrite.intentional_until,
        hash_self: 'c'.repeat(64), active: false }] : []
      if (plan.getUnavailable) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'SOURCE_UNAVAILABLE',
        data: { current: null, budget_presentation_decisions: { complete: false, items: [], history } } }) })
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: {
        current: plan.noBasis ? null : { source_binding: { as_of: '2026-11-02T20:00:00Z', sha256: binding }, breached: plan.breached !== false, snapshot_as_of: '2026-11-02T20:00:00Z' },
        budget_presentation_decisions: { complete: true, items: history, history } } }) })
    }
    if (url.pathname === '/api/v2/governance/budget-presentation/decide') {
      const body = JSON.parse(req.postData() || '{}')
      seen.posts.push(body)
      for (const bad of ['actor', 'actual', 'limit', 'breached', 'breach']) if (bad in body) seen.forbidden.push(bad)
      if (plan.refuse) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ ok: false, error: plan.refuse }) })
      if (plan.dropFirstWrite && body.dry_run !== true && !seen.dropped) { seen.dropped = true; return route.abort('failed') }
      if (body.dry_run !== true) seen.lastWrite = body
      if (plan.appendThenStatus && body.dry_run !== true) {
        if (plan.appendThenStatus === 'malformed') return route.fulfill({ status: 200, contentType: 'text/html', body: '<html>proxy error</html>' })
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'SOURCE_UNAVAILABLE' }) })
      }
      if (body.dry_run === true) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: {
        dry_run: true, written: false, would_append: {}, would_replay: false, store_approved: plan.storeApproved !== false } }) })
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: {
        actor: 'tailnet:operator', intentional_until: body.intentional_until, hash_self: 'c'.repeat(64) } }) })
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"ok":false}' })
  })
  await page.goto(`http://127.0.0.1:7811/?v=${variant}`)
  return seen
}

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const server = (await import('node:http')).createServer((_req, res) => { res.writeHead(404); res.end() })
await new Promise(r => server.listen(7811, '127.0.0.1', r))
const results = []
try {
  for (const width of [390, 412]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 3, serviceWorkers: 'block' })
    const page = await ctx.newPage()
    const errors = []
    page.on('pageerror', e => errors.push(String(e.message || e)))

    // A. available: preview writes nothing, then a confirm records it.
    const seen = await run(page, width, 'available', {})
    const open = page.getByTestId('v7-intent-open')
    assert.equal(await open.count(), 1, `open control missing at ${width}`)
    assert.ok((await open.boundingBox()).height >= 44, `open target under 44px at ${width}`)
    await open.click()
    await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
    await page.getByTestId('v7-intent-comment').fill('review needed')
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-preview-panel').waitFor()
    const previewText = await page.getByTestId('v7-intent-preview-panel').innerText()
    assert.match(previewText, /nothing written/i, `preview must say nothing was written at ${width}`)
    assert.equal(seen.posts.length, 1, `preview must be exactly one POST at ${width}`)
    assert.equal(seen.posts[0].dry_run, true, `preview must be dry_run at ${width}`)
    await page.getByTestId('v7-intent-confirm').click()
    await page.getByTestId('v7-intent-done').waitFor()
    const done = await page.getByTestId('v7-intent-done').innerText()
    assert.match(done, /intent recorded/i, `confirmation not shown at ${width}`)
    assert.equal(seen.posts.length, 2, `confirm must be a second POST at ${width}`)
    assert.ok(!('dry_run' in seen.posts[1]), `the real write must not carry dry_run at ${width}`)
    assert.equal(seen.posts[1].request_id, seen.posts[0].request_id, `the write must reuse the previewed request id at ${width}`)
    assert.deepEqual(seen.forbidden, [], `a measured field was sent at ${width}`)
    assert.equal(await page.evaluate(() => window.recorded), 1, 'the card must be asked to refresh')
    await page.screenshot({ path: path.join(out, `intent-done-${width}@3x.png`), fullPage: true })

    // B. unavailable: no control at all.
    await page.unroute('**/*')
    await run(page, width, 'unavailable', {})
    assert.equal(await page.getByTestId('v7-intent-open').count(), 0, `an unavailable decision must offer nothing at ${width}`)

    // C. the measurement changes between preview and confirm: the write is refused and never sent.
    await page.unroute('**/*')
    const seenC = await run(page, width, 'available', { basisSha: 'changed' })
    await page.getByTestId('v7-intent-open').click()
    await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-preview-panel').waitFor()
    const postsBefore = seenC.posts.length
    await page.getByTestId('v7-intent-confirm').click()
    await page.getByTestId('v7-intent-error').waitFor()
    assert.match(await page.getByTestId('v7-intent-error').innerText(), /measurement changed/i, `source change not explained at ${width}`)
    assert.equal(seenC.posts.length, postsBefore, `a changed measurement must not be written at ${width}`)
    assert.equal(await page.evaluate(() => window.recorded), undefined, 'nothing recorded after a source change')

    // D. the store is not approved: the preview says so and the write is not implied.
    await page.unroute('**/*')
    await run(page, width, 'available', { storeApproved: false })
    await page.getByTestId('v7-intent-open').click()
    await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-preview-panel').waitFor()
    assert.match(await page.getByTestId('v7-intent-preview-panel').innerText(), /NOT approved/i, `unapproved store not disclosed at ${width}`)

    // E. a past expiry is refused before any request is made.
    await page.unroute('**/*')
    const seenE = await run(page, width, 'available', {})
    await page.getByTestId('v7-intent-open').click()
    await page.getByTestId('v7-intent-until').fill('2020-01-01T00:00')
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-error').waitFor()
    assert.match(await page.getByTestId('v7-intent-error').innerText(), /future/i, `past expiry not refused at ${width}`)
    assert.equal(seenE.gets + seenE.posts.length, 0, `a past expiry must not reach the network at ${width}`)

    // F. the reply to the real write is lost: the outcome is unknown, and the retry reuses the same request id.
    await page.unroute('**/*')
    const seenF = await run(page, width, 'available', { dropFirstWrite: true })
    await page.getByTestId('v7-intent-open').click()
    await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-preview-panel').waitFor()
    await page.getByTestId('v7-intent-confirm').click()
    await page.getByTestId('v7-intent-error').waitFor()
    assert.match(await page.getByTestId('v7-intent-error').innerText(), /outcome is unknown/i, `a dropped reply must not claim nothing was written at ${width}`)
    assert.equal(await page.getByTestId('v7-intent-confirm').count(), 1, 'the preview must survive so the retry is the same request')
    await page.getByTestId('v7-intent-confirm').click()
    await page.getByTestId('v7-intent-done').waitFor()
    const ids = seenF.posts.filter(b => b.dry_run !== true).map(b => b.request_id)
    assert.ok(ids.length >= 2 && new Set(ids).size === 1, `the retry must reuse the previewed request id at ${width}: ${JSON.stringify(ids)}`)
    assert.deepEqual(seenF.forbidden, [], `a measured field was sent after a retry at ${width}`)

    // G. the append happened, then the answer failed: history resolves it, and nothing claims "nothing was written".
    for (const [label, mode] of [['503 after append', 'unavailable'], ['malformed 2xx', 'malformed']]) {
      await page.unroute('**/*')
      const seenG = await run(page, width, 'available', { appendThenStatus: mode })
      await page.getByTestId('v7-intent-open').click()
      await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
      await page.getByTestId('v7-intent-preview').click()
      await page.getByTestId('v7-intent-preview-panel').waitFor()
      await page.getByTestId('v7-intent-confirm').click()
      await page.getByTestId('v7-intent-done').waitFor()
      const text = await page.getByTestId('v7-intent-done').innerText()
      assert.match(text, /intent recorded/i, `${label}: a reconciled record must be shown at ${width}`)
      assert.match(text, /an earlier request/i, `${label}: the record must be the reconciled earlier request, not a fresh write at ${width}`)
      assert.ok(!/nothing was written/i.test(await page.locator('body').innerText()), `${label}: must not claim nothing was written at ${width}`)
      assert.equal(seenG.posts.filter(p => p.dry_run !== true).length, 1, `${label}: exactly one real write at ${width}`)
    }

    // H. the source itself is unavailable: the history is still shown and recording is off.
    await page.unroute('**/*')
    await run(page, width, 'available', { getUnavailable: true })
    await page.getByTestId('v7-intent-open').click()
    await page.getByTestId('v7-intent-until').fill(TOMORROW.slice(0, 16))
    await page.getByTestId('v7-intent-preview').click()
    await page.getByTestId('v7-intent-source-unavailable').waitFor()
    assert.match(await page.getByTestId('v7-intent-source-unavailable').innerText(), /recording is off/i, `unavailable source not disclosed at ${width}`)
    assert.equal(await page.getByTestId('v7-intent-preview-panel').count(), 0, `no preview may be offered without a current basis at ${width}`)

    assert.deepEqual(errors, [], `page errors at ${width}`)
    results.push({ width, ok: true })
    await ctx.close()
  }
} finally { await browser.close(); server.close() }
fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ results }, null, 2))
for (const r of results) console.log(`  [PASS] ${r.width}: preview writes nothing, confirm records, source change refused, unapproved store disclosed, past expiry offline`)
console.log('budget-intent: 2/2')
