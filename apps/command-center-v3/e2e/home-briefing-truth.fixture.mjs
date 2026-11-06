/** Actual Home component, synthetic saved prose and component health only. No live server or provider is reachable. */
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const app = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(path.join(app, 'package.json'))
const { build } = require('esbuild'), { chromium } = require('playwright')
const output = process.env.HOME_BRIEFING_FIXTURE_OUTPUT
if (!output) throw new Error('Set HOME_BRIEFING_FIXTURE_OUTPUT to an owned scratch directory')
fs.mkdirSync(output, { recursive: true })
const contents = `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';import HomeDoNow from './src/pages/HomeDoNow';import{OpportunityModalProvider}from'./src/components/opportunity/OpportunityContext';import './src/styles/tokens.css';import './src/index.css';createRoot(document.getElementById('root')).render(<BrowserRouter><OpportunityModalProvider><main className="app-main" style={{padding:16}}><HomeDoNow/></main></OpportunityModalProvider></BrowserRouter>);`
const bundle = await build({ stdin: { contents, resolveDir: app, sourcefile: 'home-briefing-truth.tsx', loader: 'tsx' }, jsx: 'automatic', platform: 'browser', bundle: true, write: false, outfile: 'proof.js', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const at = '2026-11-02T20:00:00Z'
const prose = 'Synthetic saved analysis remains unchanged. This sentence describes its historical generation snapshot.'
const morningProse = 'Synthetic morning analysis is independently timestamped and remains exactly as stored in this fixture.'
const samples = [
  { name: 'old', section: { content: prose, generated_at: '2026-10-30T18:00:00Z' }, expected: 'Generated Oct 30, 2026 14:00 ET · 3 d ago', datetime: '2026-10-30T18:00:00Z' },
  { name: 'same-session', section: { content: prose, generated_at: '2026-11-02 19:30:00+00:00' }, expected: 'Generated Nov 2, 2026 14:30 ET · 30 min ago', datetime: '2026-11-02T19:30:00+00:00' },
  { name: 'missing', section: { content: prose }, expected: 'Generation time unknown · not recorded for this section' },
  { name: 'malformed', section: { content: prose, generated_at: '2026-02-30T18:00:00Z' }, expected: 'Generation time unknown · recorded time is invalid' },
  { name: 'unzoned', section: { content: prose, generated_at: '2026-11-02 19:30:00' }, expected: 'Generation time unknown · a valid time and time zone are required' },
  { name: 'future', section: { content: prose, generated_at: '2026-11-02T20:00:02Z' }, expected: 'Generated Nov 2, 2026 15:00 ET · time is in the future', datetime: '2026-11-02T20:00:02Z' },
  { name: 'legacy-prose', section: prose, expected: 'Generation time unknown · not recorded for this section' },
]
const browser = await chromium.launch({ headless: true }), cases = []
try {
  for (const width of [1440, 390]) {
    for (const sample of samples) {
      const page = await browser.newPage({ viewport: { width, height: width === 390 ? 844 : 1000 } })
      await page.clock.setFixedTime(new Date(at))
      const external = [], mutations = [], errors = [], reads = []
      page.on('pageerror', e => errors.push(String(e)))
      await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url())
        if (req.method() !== 'GET') { mutations.push(req.method() + ' ' + url.pathname); return route.abort() }
        if (url.origin !== 'http://home-briefing-fixture.test') { external.push(url.origin + url.pathname); return route.abort() }
        if (url.pathname === '/fixture') return route.fulfill({ contentType: 'text/html', body: `<html data-theme="dark"><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
        reads.push(url.pathname)
        if (url.pathname === '/api/v2/command') return route.fulfill({ json: { as_of: at, llm_intelligence: { portfolio_risk: sample.section, morning_synthesis: { content: morningProse, generated_at: '2026-11-02T18:00:00Z' } }, agent_health: [], top_news: [] } })
        if (url.pathname === '/api/v2/system/platform-health') return route.fulfill({ json: { schema: 'PlatformHealth@v1', status: 'OK', as_of: at, items: [{ id: 'synthetic-healthy', label: 'Synthetic healthy component', group: 'services', status: 'OK', value: 'Synthetic probe', as_of: at }, { id: 'synthetic-critical', label: 'Synthetic critical component', group: 'services', status: 'CRIT', value: 'Synthetic probe', as_of: at }] } })
        if (url.pathname === '/api/v2/home/do-now') return route.fulfill({ json: { schema: 'HomeDoNow@v1', as_of: at, all_sources_answered: true, sources: {}, items: [], numbers: {}, rolled_up: {} } })
        if (url.pathname === '/api/v2/cio/pages') return route.fulfill({ json: { ok: true, data: { positions: { rows: [], as_of: at }, stops: { unprotected_count: 0, last_broker_read_at: at, stale: false } } } })
        if (url.pathname === '/api/v2/overview') return route.fulfill({ json: { as_of: at, pipeline_status: 'Synthetic', observation: { envelopes: { holdings: { observed_at: at, freshness: { status: 'FRESH' } } } } } })
        if (url.pathname === '/api/v2/market-risk/latest') return route.fulfill({ json: { status: 'not_evaluated', state: 'not_evaluated' } })
        return route.fulfill({ json: {} })
      })
      await page.goto('http://home-briefing-fixture.test/fixture')
      const drawer = page.getByTestId('home-drawer-briefing'), clock = page.getByTestId('home-briefing-clock')
      await clock.waitFor()
      assert.equal(await clock.innerText(), sample.expected)
      assert.equal(await clock.getAttribute('datetime'), sample.datetime ?? null)
      const collapsed = await page.getByTestId('home-briefing-summary').innerText()
      assert.ok(collapsed.includes('Saved portfolio risk analysis'))
      assert.ok(collapsed.includes('historical snapshot'))
      assert.ok(collapsed.includes(prose), 'Saved preview must preserve the original prose')
      assert.ok(!collapsed.includes('Generated Nov 2, 2026 15:00 ET · just now'), 'A fresh command response must never date the saved section')
      const scope = await page.getByTestId('home-health-population-scope').innerText()
      assert.ok(scope.includes('component checks') && scope.includes('Header Health counts critical and warning findings') && scope.includes('different populations'))
      const pulse = await page.getByTestId('home-pulse').innerText()
      assert.ok(pulse.includes('Platform component checks') && pulse.includes('1 CRIT · 1 OK'))
      assert.equal(await page.getByTestId('home-pulse').getByRole('link', { name: 'Health findings ›', exact: true }).getAttribute('href'), '/health')
      assert.equal(await page.getByTestId('home-briefing-historical-note').count(), 0, 'Briefing body remains unmounted while collapsed')
      if (['old', 'future', 'missing'].includes(sample.name)) await page.screenshot({ path: path.join(output, `${sample.name}-collapsed-${width}.png`), fullPage: true })
      await drawer.getByRole('button', { name: /AI briefing/ }).click()
      const note = page.getByTestId('home-briefing-historical-note')
      await note.waitFor()
      assert.ok((await note.innerText()).includes('figures and text do not update when live totals change'))
      const sectionClocks = await page.getByTestId('home-briefing-section-clocks').innerText()
      assert.ok(sectionClocks.includes('Portfolio risk · ' + sample.expected))
      assert.ok(sectionClocks.includes('Morning synthesis · Generated Nov 2, 2026 13:00 ET · 2 h ago'))
      assert.ok(sectionClocks.includes(prose) && sectionClocks.includes(morningProse), 'Expanded prose must remain unchanged')
      assert.equal(reads.filter(p => p === '/api/v2/command').length, 1, 'Expanding a saved briefing must not regenerate or refetch it')
      assert.ok(reads.includes('/api/v2/system/platform-health'))
      assert.ok(!reads.includes('/api/v2/health'), 'Home must not fetch/merge the different header findings population')
      assert.deepEqual(external, []);assert.deepEqual(mutations, []);assert.deepEqual(errors, [])
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow')
      if (['old', 'future', 'missing'].includes(sample.name)) await page.screenshot({ path: path.join(output, `${sample.name}-${width}.png`), fullPage: true })
      cases.push({ width, case: sample.name, synthetic: true, generated_at: sample.section?.generated_at ?? null, clock: sample.expected, api_reads: [...new Set(reads)], external_requests: 0, mutating_requests: 0, browser_errors: [] })
      await page.close()
    }
  }
} finally { await browser.close() }
const source = ['src/pages/HomeDoNow.tsx', 'src/lib/homeDoNow.ts', 'src/lib/homeDoNow.test.ts', 'e2e/home-briefing-truth.fixture.mjs'].map(relative => ({ path: relative, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(app, relative))).digest('hex') }))
const receipt = { schema: 'HomeBriefingTruthFixture@v1', as_of: new Date().toISOString(), source_commit_before_checkpoint: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: app, encoding: 'utf8' }).trim(), synthetic_clock: at, source, cases }
fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx' })
console.log(JSON.stringify({ schema: receipt.schema, cases: cases.length, widths: [1440, 390], external_requests: 0, mutating_requests: 0, browser_errors: 0, receipt: path.join(output, 'receipt.json') }))
