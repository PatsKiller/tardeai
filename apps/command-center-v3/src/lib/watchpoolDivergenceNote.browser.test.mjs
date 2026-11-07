// LQ-20261107-250 — the watchpool desk row at phone width, rendered from the REAL page.
//
// The audited defect was a sentence, and the audit that found it walked the page on a phone. This renders
// WatchpoolHub itself (esbuild, hermetic fixtures, no server) at 412 px first and then 390 px, and asserts:
//   * a row whose Street view exists but whose internal direction is missing says THAT — the sentence the
//     old component showed ("no professional-analyst view is attached") was false for 930 of 1,200 names;
//   * a row with no Street coverage keeps the coverage sentence, and the two are told apart by
//     `data-divergence-reason`;
//   * the row's verdict comes from the LIVE pills map, so a stored-at-insert 'unavailable' no longer keeps
//     the wrong chip/explanation when the read model now says 'aligned';
//   * nothing overflows the phone: the note stays inside its row, and the page does not scroll sideways.
//
// No network: every fetch is answered from the fixture below and anything else is refused and fails the run.
// Run: node src/lib/watchpoolDivergenceNote.browser.test.mjs [repo-root] [result.json]
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), '../../../..'))
const app = join(root, 'apps/command-center-v3')
const require = createRequire(join(app, 'package.json'))
const { build } = require('esbuild')
const { chromium } = require('@playwright/test')

const bundle = await build({
  stdin: {
    contents: `
      import React from 'react'
      import { createRoot } from 'react-dom/client'
      import { BrowserRouter } from 'react-router-dom'
      import WatchpoolHub from './src/pages/WatchpoolHub'
      window.mountWatchpool = () => createRoot(document.getElementById('root'))
        .render(<BrowserRouter><WatchpoolHub onDrill={() => {}} embedded /></BrowserRouter>)
    `,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  jsx: 'automatic',
  platform: 'browser',
  // In CI the app's own node_modules is here. A worktree without `npm ci` can point NODE_PATH at a
  // checkout that has them; the run stays read-only either way.
  nodePaths: [join(app, 'node_modules'), ...(process.env.NODE_PATH || '').split(':').filter(Boolean)],
  define: { 'process.env.NODE_ENV': '"production"' },
})

// Two reasons and one stale stored verdict. Symbols and labels are synthetic.
const row = (symbol, extra = {}) => ({
  hit_id: `${symbol}-1`, directive_id: 41, label: `Fixture ${symbol}`, symbol,
  surfaced_by: 'cio', divergence: 'unavailable', promotion_status: 'STAGED_FOR_REVIEW',
  hit_reason: 'fixture', surfaced_at: '2026-11-07T14:00:00Z', ...extra,
})
const directives = {
  directive_count: 3,
  directives: [],
  recent_hits: [],
  desk_suggestions: [
    row('AAA'),                                     // Street view exists, internal direction missing
    row('BBB'),                                     // no Street coverage at all
    row('CCC', { divergence: 'unavailable' }),      // stored stale; the live map now says aligned
  ],
}
const pills = {
  updated_at: '2026-11-07T16:22:23Z',
  count: 2,
  map: {
    AAA: { rec: 'buy', n: 12, street: 'bullish', internal: null, divergence: 'unavailable', has: true },
    BBB: { rec: null, n: null, street: null, internal: null, divergence: 'unavailable', has: false },
    CCC: { rec: 'buy', n: 8, street: 'bullish', internal: 'bullish', divergence: 'aligned', has: true },
  },
}
const FIXTURES = {
  '/api/v2/watch-directives': directives,
  '/api/v2/pro-analyst/pills': pills,
  // The page's other reads, empty and well-formed: they are not what this suite is about.
  '/api/v2/watchpool': { rows: [], count: 0 },
  '/api/v2/watch/two-way-curation': {},
  '/api/v2/watch/directives/merge-plan': {},
  '/api/v2/screener-finds/candidates': {},
}

const results = []
const browser = await chromium.launch({ headless: true })
try {
  for (const [width, height] of [[412, 915], [390, 844]]) {
    const scenario = `desk suggestion reasons at ${width}px`
    const page = await browser.newPage({ viewport: { width, height }, isMobile: true, hasTouch: true })
    const pageErrors = []
    const externalRequests = []
    try {
      page.on('pageerror', error => pageErrors.push(error.message))
      // Any real network request is refused and also fails the run; the page's fetches are answered below.
      await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
      await page.setContent('<!doctype html><html data-theme="dark"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
        '<body style="margin:0"><div id="root" style="padding:8px"></div></body></html>')
      await page.evaluate(fixtures => {
        window.__externalReads = []
        window.fetch = async (url) => {
          const pathname = new URL(String(url), 'http://watchpool-fixture.test').pathname
          const body = fixtures[pathname]
          if (body === undefined) {
            window.__externalReads.push(pathname)
            throw new Error(`fixture boundary: no answer for ${pathname}`)
          }
          return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }
      }, FIXTURES)
      await page.addStyleTag({ content: readFileSync(join(app, 'src/styles/tokens.css'), 'utf8') })
      await page.addScriptTag({ content: bundle.outputFiles[0].text })
      await page.evaluate(() => window.mountWatchpool())
      await page.waitForSelector('[data-desk-suggestion] [data-testid="wp-promote-unavailable"]', { timeout: 15_000 })
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="wp-promote-unavailable"]').length === 2,
        null, { timeout: 10_000 })

      const notes = page.locator('[data-testid="wp-promote-unavailable"]')
      assert.equal(await notes.count(), 2, 'only the two unavailable rows explain anything')

      // The dominant case says the INTERNAL side is missing, and does not claim there is no view.
      const internal = page.locator('[data-divergence-reason="no_internal_direction"]')
      assert.equal(await internal.count(), 1)
      assert.match(await internal.innerText(), /the Street view exists.*system's own directional read is missing/s)
      assert.doesNotMatch(await internal.innerText(), /no professional-analyst view is attached/)

      // The uncovered name keeps the coverage sentence.
      const coverage = page.locator('[data-divergence-reason="no_professional_coverage"]')
      assert.equal(await coverage.count(), 1)
      assert.match(await coverage.innerText(), /no professional-analyst view is attached/)

      // The stale stored 'unavailable' on CCC is replaced by the live pill verdict: no sentence at all.
      const cccRow = page.locator('[data-desk-suggestion]').filter({ hasText: 'Fixture CCC' })
      assert.equal(await cccRow.locator('[data-testid="wp-promote-unavailable"]').count(), 0,
        'the row kept an explanation the live read model no longer supports')
      assert.match(await cccRow.innerText(), /aligned/i, 'the live pill verdict must replace the stored one')
      assert.doesNotMatch(await cccRow.innerText(), /unavailable/i, 'the stored-at-insert verdict is still on screen')

      // Neither explanation is allowed to disable Promote.
      assert.equal(await page.getByRole('button', { name: 'Promote', exact: true }).first().isDisabled(), false)

      // Phone layout: the note owns a line inside its row, and the page does not scroll sideways.
      for (const note of [internal, coverage]) {
        const fits = await note.evaluate(el => {
          const rowEl = el.closest('[data-desk-suggestion]')
          const n = el.getBoundingClientRect(), r = rowEl.getBoundingClientRect()
          return {
            insideRow: n.left >= r.left - 1 && n.right <= r.right + 1,
            ownsLine: n.width > r.width * 0.5,
            noPageScroll: document.documentElement.scrollWidth <= window.innerWidth,
          }
        })
        assert.ok(fits.insideRow, 'the explanation overflows its desk row')
        assert.ok(fits.ownsLine, 'the explanation did not take its own line on a phone')
        assert.ok(fits.noPageScroll, 'the page scrolls sideways at phone width')
      }

      assert.deepEqual(pageErrors, [], 'the page must not throw in the browser')
      assert.deepEqual(externalRequests, [], 'every read must stay inside the fixture boundary')
      results.push({ scenario, passed: true })
    } catch (error) {
      results.push({ scenario, passed: false, error: error.name, assertion: error.message,
        page_errors: pageErrors, text: await page.locator('body').innerText().catch(() => '') })
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}

const result = { source_root: root, actual_page: 'WatchpoolHub', live_requests: false, results,
  passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n')
console.log(JSON.stringify(result, null, 2))
process.exitCode = result.failed ? 1 : 0
