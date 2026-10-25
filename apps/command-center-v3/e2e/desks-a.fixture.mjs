/** Boards 1–4 desks: actual pages, pinned projections, intercepted GET-only origin, phone tap proof. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { build } from 'esbuild'
import { chromium, expect } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const input = path.join(app, 'e2e/fixtures/desksA.fixture.json')
const fixture = JSON.parse(fs.readFileSync(input, 'utf8'))
const output = process.argv[2]
assert(output, 'Pass an explicit evidence directory')
const ORIGIN = 'http://desks-a-fixture.test'
const entry = `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';
import ReEntryDesk from './src/pages/desks/ReEntryDesk';import StrategyDesk from './src/pages/desks/StrategyDesk';import DefenseDesk from './src/pages/desks/DefenseDesk';import AgentsDesk from './src/pages/desks/AgentsDesk';
import './src/styles/tokens.css';import './src/index.css';
createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Routes>
<Route path="/portfolio/re-entry" element={<ReEntryDesk/>}/><Route path="/strategy" element={<StrategyDesk onDrill={()=>{}}/>}/>
<Route path="/defense" element={<DefenseDesk/>}/><Route path="/agents" element={<AgentsDesk onDrill={()=>{}}/>}/>
<Route path="*" element={<main data-testid="fixture-destination"><h1>Fixture destination</h1></main>}/></Routes></BrowserRouter>);`
const bundle = await build({ metafile: true, stdin: { contents: entry, resolveDir: app, sourcefile: 'desks-a-fixture.tsx', loader: 'tsx' }, bundle: true, write: false, outfile: 'fixture.js', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const files = [...Object.keys(bundle.metafile.inputs).map(p => path.resolve(app, p)).filter(p => p.startsWith(path.join(app, 'src') + path.sep)), input, fileURLToPath(import.meta.url)]
const hashes = Object.fromEntries(files.map(p => [p, hash(p)]))
const testedSource = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: app, encoding: 'utf8' }).trim(), patch_sha256: crypto.createHash('sha256').update(execFileSync('git', ['diff', 'HEAD'], { cwd: app })).digest('hex'), file_sha256: hashes }
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
fs.mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const receipts = []
try {
  for (const [width, height] of [[1440, 1000], [412, 915], [390, 844]]) {
    const phone = width < 820
    const context = await browser.newContext({ viewport: { width, height }, isMobile: phone, hasTouch: phone })
    const page = await context.newPage(), traffic = { reads: [], mutations: [], external: [], errors: [] }, flows = []
    page.on('pageerror', e => traffic.errors.push(String(e)))
    await page.clock.install({ time: new Date(fixture.clock) })
    await page.routeWebSocket('**/*', ws => { traffic.external.push(ws.url()); ws.close() })
    let state = 'fresh'
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== ORIGIN) { traffic.external.push(url.origin + url.pathname); return route.abort() }
      if (request.method() !== 'GET') { traffic.mutations.push(request.method() + ' ' + url.pathname); return route.abort() }
      if (request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:12px;min-width:0}*{box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      traffic.reads.push(url.pathname)
      const desk = url.pathname.match(/^\/api\/v2\/desks\/([a-z]+)$/)?.[1]
      if (desk) {
        if (state === 'unavailable') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'FixtureUnavailable' }) })
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: fixture.projections[desk] }) })
      }
      if (url.pathname === '/api/v2/desk-sources') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: fixture.desk_sources }) })
      // Retained legacy panels (Backtests, Legacy analytics) read other routes: answer an empty fixture.
      return route.fulfill({ contentType: 'application/json', body: '{}' })
    })
    const tap = async locator => {
      await locator.scrollIntoViewIfNeeded()
      await expect(locator).toBeInViewport()
      const box = await locator.boundingBox()
      assert(box && box.height >= 44, `Tap target under 44px: ${await locator.textContent()} height=${box?.height}`)
      if (phone) await locator.tap(); else await locator.click()
    }
    const noScroll = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Horizontal page scroll at ${width}: ${page.url()}`)
    // Detail sheets are fixed overlays: capture the viewport the operator sees, not a stitched full page.
    const shot = async (board, stateName) => { await noScroll(); const sheetOpen = await page.getByRole('dialog').count(); await page.screenshot({ path: path.join(output, `impl-${board}-${stateName}-${width}.png`), fullPage: !sheetOpen, animations: 'disabled' }) }
    const tabTo = async (title, label) => {
      await tap(page.getByRole('navigation', { name: `${title} views` }).getByRole('button', { name: label, exact: true }))
      await expect(page.getByRole('navigation', { name: `${title} views` }).getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true')
    }
    const openSheet = async (trigger, title) => {
      await tap(trigger)
      const sheet = page.getByRole('dialog', { name: title })
      await expect(sheet).toBeInViewport()
      if (phone) { const box = await sheet.boundingBox(); assert(box && box.y === 0 && box.x === 0 && Math.round(box.width) === width && Math.round(box.height) === height, `Sheet is not full screen at ${width}`) }
      assert(await sheet.evaluate(el => el.contains(document.activeElement)), 'Focus must move into detail')
      return sheet
    }
    const back = async sheet => { await tap(sheet.getByRole('button', { name: '← Back' })); await expect(page.getByRole('dialog')).toHaveCount(0) }

    // Board 1 · Re-Entry
    await page.goto(`${ORIGIN}/v3/portfolio/re-entry`)
    const ready = page.getByTestId('desk-panel-ready')
    await expect(ready).toContainText('ALFA · zone $10.00–$11.50')
    await expect(ready).not.toContainText('OLDY')
    await expect(ready).toContainText('1 packet older than 48 h is hidden here and kept in history.')
    await expect(page.getByRole('region', { name: 'Source clocks' })).toContainText('Writer RETIRED')
    await shot('1', 'ready-now')
    let sheet = await openSheet(ready.getByRole('button', { name: /ALFA · zone/ }), 'ALFA · BUY_READY')
    await expect(sheet).toContainText('ADD · conviction 71')
    await shot('1', 'packet-detail')
    await back(sheet)
    await page.goto(`${ORIGIN}/v3/portfolio/re-entry?tab=ready-now&detail=ready:pkt-ALFA`)
    sheet = page.getByRole('dialog', { name: 'ALFA · BUY_READY' })
    await expect(sheet).toBeVisible()
    await page.goBack()
    await page.goto(`${ORIGIN}/v3/portfolio/re-entry`)
    await tabTo('Re-Entry', 'Exits review')
    assert.equal(new URL(page.url()).searchParams.get('tab'), 'exits-review')
    await expect(page.getByTestId('desk-panel-workbench')).toContainText('GAMA sold')
    await shot('1', 'exits-review')
    sheet = await openSheet(page.getByTestId('desk-panel-workbench').getByRole('button', { name: /GAMA sold/ }), /GAMA · exit/)
    await expect(sheet).toContainText('not measured')
    await back(sheet)
    await tabTo('Re-Entry', 'Ready now')
    await tap(page.getByTestId('desk-panel-owned').getByRole('link', { name: /Look-through & sectors/ }))
    await expect(page.getByTestId('fixture-destination')).toBeVisible()
    assert.equal(new URL(page.url()).pathname, '/v3/portfolio')
    await page.goto(`${ORIGIN}/v3/portfolio/re-entry?symbol=ALFA`)
    await expect(page.getByTestId('fixture-destination')).toBeVisible()
    assert.equal(new URL(page.url()).pathname, '/v3/portfolio/re-entry/classic')
    flows.push('re-entry: ready-now detail sheet + Back, deep-linked detail, exits tab + detail, owner link, symbol deep link → classic')

    // Board 2 · Strategy (?tab=planner deep link from Risk)
    await page.goto(`${ORIGIN}/v3/strategy?tab=planner`)
    await expect(page.getByRole('navigation', { name: 'Strategy views' }).getByRole('button', { name: 'Planner', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('desk-panel-planner')).toContainText('Classic planner')
    await shot('2', 'planner')
    await tabTo('Strategy', 'Leaderboard')
    const board = page.getByTestId('desk-panel-leaderboard')
    await expect(board).toContainText('fixture breakout · win 58.3% · 12 trades')
    await expect(page.getByTestId('desk-panel-readiness')).toContainText('157 / 2,000')
    await shot('2', 'leaderboard')
    sheet = await openSheet(board.getByRole('button', { name: /fixture breakout/ }), 'fixture breakout · rank 1')
    await expect(sheet).toContainText('Closed paper trades')
    await back(sheet)
    await tabTo('Strategy', 'Backtests')
    await expect(page.getByTestId('desk-panel-backtests')).toContainText('Backtest results on file')
    await expect(page.getByTestId('strategy-backtest-detail')).toBeVisible()
    await shot('2', 'backtests')
    flows.push('strategy: ?tab=planner, leaderboard detail + Back, backtests home with retained panels')

    // Board 3 · Defense
    await page.goto(`${ORIGIN}/v3/defense`)
    await expect(page.getByTestId('desk-panel-act')).toContainText('Fixture regime')
    await shot('3', 'where-to-act')
    await tabTo('Defense', 'Your book')
    const book = page.getByTestId('desk-panel-book')
    await expect(book).toContainText('Hedged share of book')
    await expect(book).toContainText('not measured')
    sheet = await openSheet(book.getByRole('button', { name: /ALFA · Fixture IRA/ }), 'ALFA · Fixture IRA')
    await expect(sheet).toContainText('pending activation')
    await shot('3', 'book-detail')
    await back(sheet)
    await tabTo('Defense', 'Hedges & short side')
    await expect(page.getByTestId('desk-panel-options')).toContainText('options-lifecycle-run is PAUSED')
    await expect(page.getByTestId('desk-panel-cash')).toContainText('No job writes this file')
    await shot('3', 'hedges-gaps')
    await tabTo('Defense', 'Where to act')
    await tap(page.getByTestId('desk-panel-act').getByRole('link', { name: /Sector momentum & leaders/ }))
    assert.equal(new URL(page.url()).pathname, '/v3/watch')
    flows.push('defense: book detail + Back, paused/no-writer gaps, sectors link to Watch')

    // Board 4 · Agents (?tab=workflow resolves to Legacy analytics → Workflow)
    await page.goto(`${ORIGIN}/v3/agents?tab=workflow`)
    await expect(page.getByRole('navigation', { name: 'Agents views' }).getByRole('button', { name: 'Legacy analytics', exact: true })).toHaveAttribute('aria-pressed', 'true')
    assert.equal(new URL(page.url()).searchParams.get('tab'), 'legacy-analytics')
    await expect(page.getByTestId('agents-legacy')).toBeVisible()
    await shot('4', 'legacy-workflow')
    await tabTo('Agents', 'Runtime')
    const timeline = page.getByTestId('desk-panel-timeline')
    await expect(timeline).toContainText('steph · review')
    await shot('4', 'runtime')
    sheet = await openSheet(timeline.getByRole('button', { name: /steph · review/ }), 'steph run steph-bbb')
    await expect(sheet).toContainText('PROVIDER_BLOCKED: fixture')
    await shot('4', 'run-detail')
    await back(sheet)
    // Gate-B placeholder runs are "no model by design" (neutral); a real model error stays red.
    const GATE_B = 'No model by design (Gate-B: reasoning goes through the CIO governed bridge)'
    const valueColor = async name => timeline.getByRole('button', { name }).locator('span').last().evaluate(el => getComputedStyle(el).color)
    const red = await page.getByTestId('desk-panel-runtime').getByText('Failed (24 h)').locator('xpath=..').locator('span').last().evaluate(el => getComputedStyle(el).color)
    assert.equal(await valueColor(/steph · review/), red, 'A real model error must render red')
    for (const name of [/alex · wake event bus/, /morgan · wake event bus/, /No model by design/]) assert.notEqual(await valueColor(name), red, `Gate-B run must not render red: ${name}`)
    await expect(timeline.getByRole('note')).toHaveText('1 of the 3 newest runs recorded a model error.')
    sheet = await openSheet(timeline.getByRole('button', { name: /alex · wake event bus/ }), 'alex run alex-aaa')
    await expect(sheet).toContainText(GATE_B)
    await expect(sheet).not.toContainText('Model error')
    await back(sheet)
    const decisionsBox = page.getByRole('region', { name: 'Decisions for you' })
    await expect(decisionsBox).toContainText('1 recent agent run recorded a model error')
    await expect(decisionsBox).toContainText('The choice is to pause or slow these timers, or to wire these agents to the CIO governed bridge.')
    sheet = await openSheet(decisionsBox.getByRole('link', { name: 'tradeai-agent-runtime@{alex,morgan} timers: 2 runs in the last 24 h, no model by design' }), GATE_B)
    assert.equal(new URL(page.url()).searchParams.get('detail'), 'timeline:run-gate-b')
    await expect(sheet).toContainText('Provider contacted')
    await expect(sheet).toContainText('alex · last 24 h')
    await shot('4', 'gate-b-detail')
    await back(sheet)
    await page.goto(`${ORIGIN}/v3/agents?tab=evidence`)
    await expect(page.getByRole('navigation', { name: 'Agents views' }).getByRole('button', { name: 'Learning', exact: true })).toHaveAttribute('aria-pressed', 'true')
    flows.push('agents: workflow alias, runtime run detail + Back, Gate-B runs neutral vs real error red, Gate-B decision link → sheet + Back, evidence merged into learning')

    state = 'unavailable'
    for (const [board, url, title] of [['1', '/v3/portfolio/re-entry', 'Re-Entry'], ['2', '/v3/strategy', 'Strategy'], ['3', '/v3/defense', 'Defense'], ['4', '/v3/agents', 'Agents']]) {
      await page.goto(ORIGIN + url)
      await expect(page.getByText(`${title} unavailable`, { exact: true })).toBeVisible()
      await shot(board, 'unavailable')
    }
    state = 'fresh'
    assert.deepEqual({ ...traffic, reads: [] }, { reads: [], mutations: [], external: [], errors: [] })
    receipts.push({ width, height, flows, reads: [...new Set(traffic.reads)].sort() })
    await context.close()
  }
} finally { await browser.close() }
for (const [p, digest] of Object.entries(hashes)) assert.equal(hash(p), digest, `Source changed during proof: ${p}`)
fs.writeFileSync(path.join(output, 'desks-a-mobile-receipts.json'), JSON.stringify({ fixture: true, clock: fixture.clock, tested_source: testedSource, cases: receipts }, null, 2) + '\n')
console.log(`Desks A actual page proof: ${receipts.length} viewports; tap/back/sheet/deep-link/no-scroll/no-mutation checks passed`)
