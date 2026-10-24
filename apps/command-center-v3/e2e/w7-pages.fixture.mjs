/** Actual W7 pages, pinned synthetic responses, intercepted GET-only origin. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { build } from 'esbuild'
import { chromium, expect } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const input = path.join(app, 'e2e/fixtures/w7Pages.fixture.json')
const fixture = JSON.parse(fs.readFileSync(input, 'utf8'))
const output = process.argv[2]
assert(output, 'Pass an explicit evidence directory')
const bundle = await build({ metafile: true, stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';import HomeHub from './src/pages/HomeHub';import RiskHub from './src/pages/RiskHub';import PortfolioHub from './src/pages/PortfolioHub';import CioHub from './src/pages/CioHub';import './src/styles/tokens.css';import './src/index.css';createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Routes><Route path="/" element={<HomeHub onDrill={()=>{}}/>}/><Route path="/risk" element={<RiskHub onDrill={()=>{}}/>}/><Route path="/portfolio" element={<PortfolioHub onDrill={()=>{}}/>}/><Route path="/cio" element={<CioHub onDrill={()=>{}}/>}/><Route path="*" element={<main data-testid="fixture-destination"><h1>Fixture destination</h1></main>}/></Routes></BrowserRouter>);`, resolveDir: app, sourcefile: 'w7-fixture.tsx', loader: 'tsx' }, bundle: true, write: false, outfile: 'fixture.js', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files = [...Object.keys(bundle.metafile.inputs).map(p => path.resolve(app, p)).filter(p => p.startsWith(path.join(app, 'src') + path.sep)), input, fileURLToPath(import.meta.url)]
const hashes = Object.fromEntries(files.map(p => [p, hash(p)]))
const testedSource = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: app, encoding: 'utf8' }).trim(), patch_sha256: crypto.createHash('sha256').update(execFileSync('git', ['diff', 'HEAD'], { cwd: app })).digest('hex'), file_sha256: hashes }
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
fs.mkdirSync(output, { recursive: true })
if (process.argv.includes('--bundle-check')) {
  fs.writeFileSync(path.join(output, 'w7-fixture-bundle-check.json'), JSON.stringify({ browser_executed: false, tested_source: testedSource, js_bytes: js.length, css_bytes: css.length }, null, 2) + '\n')
  console.log('W7 actual-page fixture bundle compiled; browser tap proof NOT EXECUTED')
  process.exit(0)
}
const browser = await chromium.launch({ headless: true })
const receipts = []
try {
  for (const [width, height] of [[1440, 1000], [412, 915], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height }, isMobile: width < 820, hasTouch: width < 820 })
    const page = await context.newPage(), traffic = { reads: [], mutations: [], external: [], errors: [] }, flows = []
    page.on('pageerror', e => traffic.errors.push(String(e)))
    await page.clock.install({ time: new Date(fixture.clock) })
    await page.routeWebSocket('**/*', ws => { traffic.external.push(ws.url()); ws.close() })
    let state = 'fresh'
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== 'http://w7-fixture.test') { traffic.external.push(url.origin + url.pathname); return route.abort() }
      if (request.method() !== 'GET') { traffic.mutations.push(request.method() + ' ' + url.pathname); return route.abort() }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:12px;min-width:0}*{box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      traffic.reads.push(url.pathname)
      const payload = url.pathname === '/api/v2/cio/pages' ? fixture[state === 'gap' ? 'gap' : 'payload'] : fixture.responses[url.pathname] || {}
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) })
    })
    const tap = async locator => {
      await locator.scrollIntoViewIfNeeded()
      await expect(locator).toBeInViewport()
      const box = await locator.boundingBox()
      assert(box && box.height >= 44, `Tap target under 44px: ${await locator.textContent()} height=${box?.height}`)
      if (width < 820) await locator.tap(); else await locator.click()
    }
    const noScroll = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Horizontal page scroll at ${width}: ${page.url()}`)
    const shot = async (board, stateName) => { await noScroll(); await page.screenshot({ path: path.join(output, `impl-${board}-${stateName}-${width}.png`), fullPage: true, animations: 'disabled' }) }
    const assertSheet = async title => {
      const sheet = page.getByRole('dialog', { name: title })
      await expect(sheet).toBeInViewport()
      if (width < 820) { const box = await sheet.boundingBox(); assert(box && box.y === 0 && box.x === 0 && Math.round(box.width) === width && Math.round(box.height) === height) }
      assert(await sheet.evaluate(el => el.contains(document.activeElement)), 'Focus must move into detail')
      return sheet
    }
    await page.goto('http://w7-fixture.test/v3/')
    await expect(page.getByTestId('home-do-now')).toContainText('Review pending stop activation')
    await expect(page.getByTestId('home-hub')).not.toContainText('Portfolio value')
    await shot('14', 'actions-protection')
    await tap(page.getByRole('link', { name: 'Review stop →', exact: true }))
    const riskSheet = await assertSheet('ALFA · stop details')
    await expect(riskSheet).toContainText('Pending activation')
    await expect(riskSheet).toContainText('Fixture IRA')
    await shot('15', 'pending-stop-detail')
    await tap(riskSheet.getByRole('button', { name: 'Back', exact: false }))
    await expect(page.getByRole('dialog')).toHaveCount(0)
    flows.push('home primary action opens risk deep-link detail; sheet Back closes')
    const risk = page.getByTestId('risk-hub')
    await tap(risk.getByRole('button', { name: 'Review SYNF →' }))
    await assertSheet('SYNF · stop details')
    await page.goBack()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await tap(page.getByRole('tab', { name: 'Concentration', exact: true }))
    await expect(risk).toContainText('Max single name 9%')
    await expect(page.getByRole('heading', { name: 'Concentration', exact: true })).toBeInViewport()
    assert.equal(new URL(page.url()).searchParams.get('tab'), 'concentration')
    await shot('15', 'concentration')
    await tap(page.getByRole('tab', { name: 'Regime', exact: true }))
    await expect(risk).toContainText('Fixture regime')
    await shot('15', 'regime')
    flows.push('risk position tap/fullscreen/browser Back; tabs preserve URL')
    await page.goto('http://w7-fixture.test/v3/portfolio?tab=Look-through')
    const lt = page.getByTestId('lookthrough-panel')
    await expect(lt).toContainText('56.25%')
    await expect(lt).toContainText('$28,000')
    await expect(lt).not.toContainText('I cannot provide investment advice')
    await shot('12', 'industries-coverage')
    await tap(lt.getByRole('button', { name: /Software/ }))
    const industrySheet = await assertSheet('Software')
    await expect(industrySheet).toContainText('ALFA')
    await shot('12', 'industry-detail')
    await tap(industrySheet.getByRole('button', { name: 'Back', exact: false }))
    await tap(page.getByLabel('Look-through account'))
    await page.getByLabel('Look-through account').selectOption('fixture_manual')
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('lookthrough-coverage')).toContainText('Fixture manual account')
    await expect(page.getByTestId('lookthrough-coverage')).toContainText('$8,000')
    await shot('12', 'account-gap')
    await tap(page.getByLabel('Look-through account'))
    await page.getByLabel('Look-through account').selectOption('')
    await page.keyboard.press('Escape')
    await tap(lt.getByRole('button', { name: /^ALFA / }))
    const underlyingSheet = await assertSheet('ALFA · underlying holdings')
    await expect(underlyingSheet).toContainText('Fixture IRA')
    await tap(underlyingSheet.getByRole('link', { name: 'Review positions →' }))
    await expect(page.getByTestId('lookthrough-panel')).toHaveCount(0)
    await expect(page.getByTestId('holdings-panel')).toBeInViewport()
    flows.push('lookthrough industry/stock detail, Back, account filter, primary position link')
    await page.goto('http://w7-fixture.test/v3/portfolio?tab=Allocation')
    await expect(page.getByTestId('allocation-sector-summary')).toBeVisible()
    await expect(page.getByTestId('allocation-sector-summary')).not.toContainText('Top underlying stocks')
    await tap(page.getByRole('link', { name: /Industries, coverage, themes/ }))
    await expect(page.getByTestId('lookthrough-panel')).toBeVisible()
    flows.push('allocation summary links to single lookthrough home')
    await page.goto('http://w7-fixture.test/v3/cio?tab=overview')
    await expect(page.getByTestId('cio-single-status')).toContainText('7 settled fixture completions')
    await shot('17', 'single-status')
    await tap(page.getByRole('tab', { name: 'Capital & Policy', exact: true }))
    await expect(page.getByTestId('cio-cash-waterfall')).toBeInViewport()
    await expect(page.getByTestId('cio-cash-waterfall')).toContainText('$3,000')
    await expect(page.getByTestId('cio-cash-waterfall')).toContainText('9%')
    await expect(page.getByTestId('cio-cash-waterfall')).toContainText('14%')
    await shot('17', 'cash-policy')
    flows.push('CIO overview/capital tabs show one status and independent cap/alert')
    state = 'gap'
    await page.goto('http://w7-fixture.test/v3/')
    await expect(page.getByTestId('home-hub')).toContainText('Fixture CIO record unavailable')
    await shot('14', 'unavailable')
    await page.goto('http://w7-fixture.test/v3/risk?tab=exposure')
    await expect(page.getByTestId('risk-positions')).toContainText('Fixture CIO record unavailable')
    await shot('15', 'unavailable')
    assert.deepEqual({ ...traffic, reads: [] }, { reads: [], mutations: [], external: [], errors: [] })
    receipts.push({ width, height, flows, traffic })
    await context.close()
  }
} finally { await browser.close() }
for (const [p, digest] of Object.entries(hashes)) assert.equal(hash(p), digest, `Source changed during proof: ${p}`)
fs.writeFileSync(path.join(output, 'w7-mobile-receipts.json'), JSON.stringify({ fixture: true, clock: fixture.clock, tested_source: testedSource, cases: receipts }, null, 2) + '\n')
console.log(`W7 actual page proof: ${receipts.length} viewports, tap/back/filter/primary-action/viewport/no-scroll checks passed`)
