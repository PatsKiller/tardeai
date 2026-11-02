/** Isolated actual-component proof. No server, production data, external request or mutation is reachable. */
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
const output = process.env.HEALTH_INCIDENTS_FIXTURE_OUTPUT
if (!output) throw new Error('Set HEALTH_INCIDENTS_FIXTURE_OUTPUT to an owned scratch directory')
fs.mkdirSync(output, { recursive: true })
const contents = `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';import HealthHub from './src/pages/HealthHub';import OpsIncidents from './src/pages/OpsIncidents';import{TOKENS}from './src/lib/designTokens';import './src/styles/tokens.css';import './src/index.css';const incident=location.search.includes('incident');createRoot(document.getElementById('root')).render(<BrowserRouter><main className="app-main" style={{padding:16}}>{incident?<OpsIncidents/>:<HealthHub/>}<span data-testid="tone-success" style={{color:TOKENS.success}}/><span data-testid="tone-warning" style={{color:TOKENS.warning}}/><span data-testid="tone-danger" style={{color:TOKENS.danger}}/><span data-testid="tone-unknown" style={{color:TOKENS.text[2]}}/></main></BrowserRouter>);`
const bundle = await build({ stdin: { contents, resolveDir: app, sourcefile: 'health-incidents-truth.tsx', loader: 'tsx' }, bundle: true, write: false, outfile: 'proof.js', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const at = '2032-04-12T16:30:00Z'
const base = { schema: 'IncidentRecord@v1', opened_at: '2032-04-12T14:30:00Z', updated_at: at, source: { kind: 'watcher', watcher: 'synthetic' }, evidence: ['Synthetic receipt only'], attempts: [], fix_refs: [], notes: [], acknowledged: null }
const incidents = [
  { ...base, id: 'synthetic-low', status: 'open', severity: 'P3', owner: ' ', title: 'Synthetic low priority', escalations: [{ at }] },
  { ...base, id: 'synthetic-critical', status: 'blocked', severity: 'P0', owner: 'fixture-owner', title: 'Synthetic critical incident', blocked_reason: 'Synthetic dependency', handoff: 'Review synthetic receipt', escalations: [{ at, delivered: false }] },
  { ...base, id: 'synthetic-delivered', status: 'open', severity: 'P1', title: 'Synthetic confirmed delivery', escalations: [{ at, delivered: true }] },
  { ...base, id: 'synthetic-mixed', status: 'open', severity: 'P2', title: 'Synthetic mixed delivery', escalations: [{ at, delivered: true }, { at, delivered: false }] },
  { ...base, id: 'synthetic-history', status: 'closed', severity: 'P0', title: 'Synthetic closed history', closed_at: at },
]
const healthCases = [
  { name: 'missing', health: { status: 'unknown' }, risk: {}, proposals: {}, values: ['Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown'], healthTone: 'unknown' },
  { name: 'partial', health: { overall_score: 90, status: 'healthy' }, risk: { portfolio_heat_pct: 0 }, proposals: {}, values: ['0.0%', '90', 'Unknown', 'Unknown', 'Unknown'], healthTone: 'success' },
  { name: 'healthy', health: { overall_score: 90, status: 'healthy' }, values: ['0.0%', '90', '0', '0', '0'], healthTone: 'success' },
  { name: 'degraded', health: { overall_score: 70, status: 'degraded' }, values: ['0.0%', '70', '0', '0', '0'], healthTone: 'warning' },
  { name: 'unhealthy', health: { overall_score: 0, status: 'unhealthy' }, values: ['0.0%', '0', '0', '0', '0'], healthTone: 'danger' },
  { name: 'nonfinite', health: { overall_score: null, status: 'unknown' }, risk: { portfolio_heat_pct: '0', positions: null }, proposals: { broker: { stale_count: '0' }, options: { needs_action: null } }, values: ['Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown'], healthTone: 'unknown' },
  { name: 'risk-threshold', health: { overall_score: 90, status: 'healthy' }, risk: { portfolio_heat_pct: 6, positions: [] }, values: ['6.0%', '90', '0', '0', '0'], healthTone: 'success', heatTone: 'danger' },
]
const browser = await chromium.launch({ headless: true }), cases = []
try {
  for (const width of [1440, 390]) {
    for (const sample of [...healthCases, { name: 'incident' }]) {
      const page = await browser.newPage({ viewport: { width, height: width === 390 ? 844 : 1000 } })
      const external = [], mutations = [], errors = [], reads = []
      page.on('pageerror', e => errors.push(String(e)))
      await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url())
        if (req.method() !== 'GET') { mutations.push(req.method() + ' ' + url.pathname); return route.abort() }
        if (url.origin !== 'http://health-incidents-fixture.test') { external.push(url.origin + url.pathname); return route.abort() }
        if (url.pathname === '/fixture') return route.fulfill({ contentType: 'text/html', body: `<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
        reads.push(url.pathname)
        if (url.pathname === '/api/v2/health') return route.fulfill({ json: { captured_at: at, findings: [], counts: { critical: 0, warning: 0 }, category_scores: {}, ...sample.health } })
        if (url.pathname === '/api/v2/risk') return route.fulfill({ json: sample.risk ?? { portfolio_heat_pct: 0, positions: [] } })
        if (url.pathname === '/api/v2/health/proposals') return route.fulfill({ json: sample.proposals ?? { broker: { stale_count: 0 }, options: { needs_action: 0 } } })
        if (url.pathname === '/api/v2/ops/incidents') return route.fulfill({ json: { schema: 'IncidentsView@v1', as_of: at, ledger_present: true, summary: { counts: { open: 3, fixing: 0, blocked: 1, fixed: 0, closed: 1 } }, incidents, watchers_as_of: at, supervisor_as_of: at } })
        if (url.pathname.startsWith('/api/v2/ops/incidents/')) return route.fulfill({ json: { incident: incidents.find(i => url.pathname.endsWith('/' + i.id)), events: [] } })
        return route.fulfill({ json: {} })
      })
      await page.goto('http://health-incidents-fixture.test/fixture?' + sample.name)
      let result
      if (sample.name !== 'incident') {
        await page.waitForFunction(values => JSON.stringify([...document.querySelectorAll('[data-testid="risk-gauge-value"]')].map(el => el.textContent)) === JSON.stringify(values), sample.values)
        result = await page.evaluate(() => {
          const color = testid => getComputedStyle(document.querySelector(`[data-testid="${testid}"]`)).color
          return { values: [...document.querySelectorAll('[data-testid="risk-gauge-value"]')].map(el => ({ text: el.textContent, color: getComputedStyle(el).color })), tones: Object.fromEntries(['success', 'warning', 'danger', 'unknown'].map(t => [t, color('tone-' + t)])) }
        })
        assert.equal(result.values[1].color, result.tones[sample.healthTone])
        for (const value of result.values.filter(v => v.text === 'Unknown')) assert.equal(value.color, result.tones.unknown)
        if (sample.heatTone) assert.equal(result.values[0].color, result.tones[sample.heatTone])
        if (sample.name === 'healthy') for (const value of result.values) assert.equal(value.color, result.tones.success)
      } else {
        const first = page.locator('[data-testid^="incident-row-"]').first()
        await first.waitFor()
        assert.equal(await first.getAttribute('data-testid'), 'incident-row-synthetic-critical')
        const list = await first.innerText();for (const text of ['P0', 'fixture-owner', 'Synthetic dependency', 'Review synthetic receipt']) assert.ok(list.includes(text), text)
        assert.ok((await page.getByTestId('incident-row-synthetic-delivered').innerText()).includes('Owner: Unassigned'))
        assert.ok((await page.getByTestId('incident-row-synthetic-low').innerText()).includes('Owner: Unassigned'))
        for (const [id, label] of [['synthetic-critical', 'Escalation delivery unconfirmed (1 attempt)'], ['synthetic-delivered', '1 of 1 escalation deliveries confirmed'], ['synthetic-mixed', '1 of 2 escalation deliveries confirmed'], ['synthetic-low', 'Escalation delivery unconfirmed (1 attempt)']]) {
          await page.getByTestId('incident-row-' + id).click()
          await page.getByTestId('incident-detail').getByText(label, { exact: true }).waitFor()
          assert.equal(await page.getByText('P1 sent', { exact: true }).count(), 0)
          if (width === 390) await page.getByRole('button', { name: '← Back', exact: true }).click()
        }
        if (width !== 390) await page.getByRole('button', { name: 'Close', exact: true }).click()
        await page.getByTestId('incident-filter-all').click()
        await page.getByTestId('incident-row-synthetic-history').waitFor()
        result = { critical_first: true, severity_owner_blocker_visible: true, typed_delivery_verified: true, history_retained: true }
      }
      assert.deepEqual(external, []);assert.deepEqual(mutations, []);assert.deepEqual(errors, [])
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow')
      if (['missing', 'healthy', 'incident'].includes(sample.name)) await page.screenshot({ path: path.join(output, `${sample.name}-${width}.png`), fullPage: true })
      cases.push({ width, case: sample.name, synthetic: true, external_requests: 0, mutating_requests: 0, browser_errors: [], api_reads: [...new Set(reads)], result })
      await page.close()
    }
  }
} finally { await browser.close() }
const source = ['src/pages/HealthHub.tsx', 'src/components/risk/RiskHealthStrip.tsx', 'src/components/risk/RiskGauge.tsx', 'src/pages/OpsIncidents.tsx', 'src/lib/incidents.ts', 'src/lib/incidents.test.ts', 'e2e/health-incidents-truth.fixture.mjs'].map(relative => ({ path: relative, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(app, relative))).digest('hex') }))
const receipt = { schema: 'HealthIncidentsTruthFixture@v1', as_of: new Date().toISOString(), source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: app, encoding: 'utf8' }).trim(), synthetic_clock: at, source, cases }
fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx' })
console.log(JSON.stringify({ schema: receipt.schema, cases: cases.length, widths: [1440, 390], external_requests: 0, mutating_requests: 0, browser_errors: 0, receipt: path.join(output, 'receipt.json') }))
