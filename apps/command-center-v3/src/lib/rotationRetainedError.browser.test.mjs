// Hermetic actual-hook/view integration: only fetch is fake; no server or live API.
// Run: node src/lib/rotationRetainedError.browser.test.mjs [repo-root] [result.json]
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
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
      import React, { act } from 'react'
      import { createRoot } from 'react-dom/client'
      import View from './src/components/intelligence/IntelligenceRotationTab'
      window.IS_REACT_ACT_ENVIRONMENT = true
      const root = createRoot(document.getElementById('root'))
      window.mountRotation = () => act(async () => root.render(<View onDrill={() => { window.drills++ }} />))
      window.refetchRotation = async () => {
        await act(async () => window.dispatchEvent(new Event('cc-v3-api-recover')))
        // Refetch starts a new effect. Flush its async fetch settlement as well.
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
      }
      window.unmountRotation = () => act(async () => root.unmount())
    `,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  jsx: 'automatic',
  platform: 'browser',
  define: { 'process.env.NODE_ENV': '"test"' },
})

const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const scenario of ['cached 503', '304 revalidation', '200 recovery', '401 terminal', '403 terminal']) {
    const page = await browser.newPage({ serviceWorkers: 'block' })
    const pageErrors = []
    const externalRequests = []
    page.on('pageerror', error => pageErrors.push(error.message))
    // Any accidental network request is refused and also fails the test.
    await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
    try {
      await page.setContent('<div id="root"></div>')
      await page.evaluate(() => {
        window.calls = []
        window.drills = 0
        window.nextStatus = 200
        window.fixtureTime = new Date().toISOString()
        window.currentSymbol = 'AAA'
        window.fetch = async (_url, options) => {
          const status = window.nextStatus
          window.calls.push({ status, etag: options?.headers?.['If-None-Match'] ?? null })
          if (status === 304) return new Response(null, { status })
          const at = window.fixtureTime
          const summary = {
            ok: true, summary: { trim_review: 99 },
            top_rotation_ideas: [{ from_symbol: window.currentSymbol, to_symbol: 'BBB', action_class: 'ROTATE_REVIEW' }],
            publication: {
              schema: 'RotationPublication@v1', status: 'READY', reasons: [], checked_at: at,
              input_sha256: 'a'.repeat(64), source_as_of: at, cache_generated_at: at, producer_ok: true,
              source_as_of_basis: 'oldest_required_position_or_account_timestamp',
              coverage: { required_positions: 1, dated_positions: 1, accounts: 1, dated_accounts: 1 },
              accounts: [{ account_key: 'fixture', state: 'LIVE', source_as_of: at }],
            },
          }
          return new Response(JSON.stringify(status === 200 ? summary : { retry_after_sec: 60 }), {
            status, headers: { 'Content-Type': 'application/json', ETag: '"fixture-summary"' },
          })
        }
      })
      await page.addScriptTag({ content: bundle.outputFiles[0].text })
      await page.evaluate(() => window.mountRotation())
      assert.match(await page.locator('body').innerText(), /AAA/, 'initial real-hook 200 must show advisory')
      const status = scenario.startsWith('401') ? 401 : scenario.startsWith('403') ? 403 : scenario === '304 revalidation' ? 304 : 503
      await page.evaluate(value => { window.nextStatus = value }, status)
      await page.evaluate(() => window.refetchRotation())
      let text = await page.locator('body').innerText()
      const fixtureTime = await page.evaluate(() => window.fixtureTime)
      if (status === 304) {
        assert.match(text, /AAA/, 'valid 304 must retain valid advice')
        const calls = await page.evaluate(() => window.calls)
        assert.equal(calls[1].etag, '"fixture-summary"', '304 control must use actual hook ETag revalidation')
      } else {
        assert.match(text, /Rotation advisory (UNAVAILABLE|STALE)/, 'failed refresh must withhold retained advice')
        assert.doesNotMatch(text, /AAA|BBB|Trim review/i, 'retained advice and drill actions must be absent')
        assert.equal(await page.getByText('99', { exact: true }).count(), 0, 'retained advisory counter must be absent')
        assert.match(text, /Source as of:/)
        assert.ok(text.includes(fixtureTime), 'last-good source/generated/checked time must remain visible')
        assert.equal(await page.locator('a').count(), 0, 'held view must not expose the advisory desk action')
      }
      if (scenario === '200 recovery') {
        await page.evaluate(() => { window.nextStatus = 200; window.currentSymbol = 'CCC' })
        await page.evaluate(() => window.refetchRotation())
        text = await page.locator('body').innerText()
        assert.match(text, /CCC/, 'fresh successful fetch must restore current advisory')
        assert.doesNotMatch(text, /AAA|Rotation advisory UNAVAILABLE|Rotation advisory STALE/)
      }
      if (status === 401 || status === 403) {
        // A focus event revalidates display age; it cannot clear a terminal auth answer.
        const before = await page.evaluate(() => window.calls.length)
        await page.evaluate(() => window.dispatchEvent(new Event('focus')))
        assert.equal(await page.evaluate(() => window.calls.length), before)
        assert.doesNotMatch(await page.locator('body').innerText(), /AAA|Trim review/)
      }
      await page.evaluate(() => window.unmountRotation())
      assert.deepEqual(pageErrors, [], 'actual hook/view must not throw in the browser')
      assert.deepEqual(externalRequests, [], 'all fetches must stay in the fake boundary')
      results.push({ scenario, passed: true, calls: await page.evaluate(() => window.calls) })
    } catch (error) {
      results.push({ scenario, passed: false, error: error.name, assertion: error.message,
        text: await page.locator('body').innerText(), calls: await page.evaluate(() => window.calls) })
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}
const result = { source_root: root, actual_hook: true, live_requests: false, results,
  passed: results.filter(row => row.passed).length, failed: results.filter(row => !row.passed).length }
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n')
console.log(JSON.stringify(result, null, 2))
process.exitCode = result.failed ? 1 : 0
