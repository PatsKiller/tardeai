// Mounted-behaviour contract for the shell's SurfaceState publisher (BOARD row 36, rule 7; finding P1 from
// codex-cloud, 2026-11-05). The old assertion read App.tsx as TEXT and matched regexes; it could pass while the real
// provider/hook/consumer were disconnected. This test mounts the REAL SurfaceStateProvider, the REAL
// useReportSurfaceState hook and the REAL BuildMarker footer in Chromium, lets the effect run, and observes the
// published report in the footer's DOM (data-surface-loaded and the qualifier text).
//
// It uses the repo's existing effect-capable harness (esbuild + Playwright Chromium, same as
// rotationRetainedError.browser.test.mjs) and runs in the existing Chromium-installing workflow
// .github/workflows/cio-truth-gates-ui-validation.yml. No new app dependency.
//
// Run: node src/lib/surfaceStatePublish.browser.test.mjs [repo-root] [result.json]
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
      import { SurfaceStateProvider, useReportSurfaceState } from './src/components/SurfaceGap'
      import { BuildMarker } from './src/components/BuildMarker'
      import { deriveSurfaceState } from './src/lib/surfaceState'

      window.IS_REACT_ACT_ENVIRONMENT = true
      const root = createRoot(document.getElementById('root'))
      const shape = { what: 'agents page' }
      const readingFor = (kind) => kind === 'ready'
        ? { data: { rows: [{ id: 'fixture' }] } }
        : kind === 'loading' ? { data: null, loading: true } : { data: null, error: 'HTTP 503' }

      // A page the shell would mount: it calls the REAL hook, which publishes to the REAL provider.
      function Page({ kind }) {
        window.pageRenders = (window.pageRenders || 0) + 1
        useReportSurfaceState('Agents page', deriveSurfaceState(readingFor(kind), shape))
        return null
      }
      function Harness({ kind, withPage }) {
        return <SurfaceStateProvider>
          {withPage ? <Page kind={kind} /> : null}
          <BuildMarker />
        </SurfaceStateProvider>
      }
      window.mountHarness = (kind, withPage = true) => act(async () => root.render(<Harness kind={kind} withPage={withPage} />))
      // The footer renders its surface qualifier on the SAME branch (production: the served artifact matches the
      // bundle). Flush the footer's own metadata read so that branch is reached before a scenario is observed.
      window.flushHarness = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
      window.unmountHarness = () => act(async () => root.unmount())
    `,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  jsx: 'automatic',
  platform: 'browser',
  define: {
    'process.env.NODE_ENV': '"test"',
    // The footer only prints the surface qualifier when compareServedBuild() says SAME, so the test bundle must carry
    // a real (fixture) identity just as the deployed bundle does.
    __ANALYST_UI_VERSION__: '"test-ui"',
    __BUILD_DATE__: '"2030-01-01T00:00:00Z"',
    __CC_BUNDLE_SOURCE_SHA__: '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
  },
  // Stylesheets are a build-time concern; they must not stop this bundle from being produced.
  loader: { '.css': 'empty' },
})

const browser = await chromium.launch({ headless: true })
const results = []
try {
  const page = await browser.newPage({ serviceWorkers: 'block' })
  const pageErrors = []
  const externalRequests = []
  page.on('pageerror', error => pageErrors.push(error.message))
  // Any real network request is refused and recorded; the footer's own build-meta read is expected to fail closed.
  await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
  await page.setContent('<div id="root"></div>')
  // The footer's build-identity read: the served artifact matches this (fixture) bundle, so the footer takes the SAME
  // branch and renders the surface qualifier. Stubbed, so no live request is made.
  await page.evaluate(() => {
    window.fetch = async () => new Response(JSON.stringify({ ui_version: 'test-ui', git_sha: 'a'.repeat(40) }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  })
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.evaluate(() => { window.pageRenders = 0 })

  const footer = () => page.locator('[data-testid="cc-loaded-build"]')
  const footerState = async () => ({
    loaded: await footer().getAttribute('data-surface-loaded'),
    text: await footer().innerText(),
  })

  const scenarios = [
    { name: 'loading publishes dataLoaded=false and says the page is still loading', kind: 'loading', withPage: true,
      assert: ({ loaded, text }) => {
        assert.equal(loaded, 'false', 'loading must publish dataLoaded=false to the footer')
        assert.match(text, /Agents page is still loading/, 'footer must name the loading surface')
        assert.doesNotMatch(text, /Agents page data did not load/, 'a loading page is not a failure')
      } },
    { name: 'ready publishes dataLoaded=true and drops the qualifier', kind: 'ready', withPage: true,
      assert: ({ loaded, text }) => {
        assert.equal(loaded, 'true', 'a rendered surface must publish dataLoaded=true to the footer')
        assert.doesNotMatch(text, /Agents page is still loading|Agents page data did not load/, 'no qualifier when data rendered')
      } },
    { name: 'unavailable publishes dataLoaded=false and names the failure', kind: 'unavailable', withPage: true,
      assert: ({ loaded, text }) => {
        assert.equal(loaded, 'false', 'a failed surface must publish dataLoaded=false to the footer')
        assert.match(text, /Agents page data did not load/, 'footer must say the data did not load')
        assert.doesNotMatch(text, /still loading/, 'a failed read is not still loading')
      } },
    { name: 'unmounting the page clears its own slot (unknown, no qualifier)', kind: 'ready', withPage: false,
      assert: ({ loaded, text }) => {
        assert.equal(loaded, 'unknown', 'the outgoing page must clear the slot it owns')
        assert.doesNotMatch(text, /Agents page (is still loading|data did not load)/, 'a cleared slot carries no qualifier')
      } },
  ]

  for (const scenario of scenarios) {
    try {
      // Second entry clears + mounts in one act; a repeat publish of identical content must not loop.
      const before = await page.evaluate(() => window.pageRenders)
      await page.evaluate(({ kind, withPage }) => window.mountHarness(kind, withPage), { kind: scenario.kind, withPage: scenario.withPage })
      await page.evaluate(() => window.flushHarness())
      await page.waitForTimeout(50)
      const observed = await footerState()
      scenario.assert(observed)
      const renders = await page.evaluate(() => window.pageRenders)
      // A stable publisher + identity-preserving reducer: an unchanged report settles instead of re-rendering forever
      // (the 255,468-render /agents loop this split exists to prevent). One render for the mount and one for the
      // published state are expected; a loop would be hundreds.
      assert.ok(renders - before <= 5, `publishing must settle without a render loop (rendered ${renders - before} times)`)
      results.push({ scenario: scenario.name, passed: true, ...observed, renders: renders - before })
    } catch (error) {
      results.push({ scenario: scenario.name, passed: false, error: error.name, assertion: error.message, text: await footer().innerText() })
    }
  }

  await page.evaluate(() => window.unmountHarness())
  try {
    assert.deepEqual(pageErrors, [], 'the mounted shell wiring must not throw')
    assert.deepEqual(externalRequests, [], 'the test must stay inside its own page')
  } catch (error) {
    results.push({ scenario: 'page health', passed: false, error: error.name, assertion: error.message })
  }
  await page.close()
} finally {
  await browser.close()
}

const result = {
  source_root: root,
  mounted: ['SurfaceStateProvider', 'useReportSurfaceState', 'BuildMarker'],
  source_text_assertions: false,
  live_requests: false,
  results,
  passed: results.filter(row => row.passed).length,
  failed: results.filter(row => !row.passed).length,
}
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n')
console.log(JSON.stringify(result, null, 2))
process.exitCode = result.failed ? 1 : 0
