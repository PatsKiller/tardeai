// Actual Home component/hook regression, synthetic deferred reads, no HTTP server or live data.
// node apps/wealth/tests/home-read-lifecycle.browser.mjs --out <evidence-directory>
// --source-root and --dependencies-root allow independent qualification of another isolated checkout.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const ownRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
function option(name, fallback) {
  const index = process.argv.indexOf(name)
  if (index < 0) return fallback
  assert(process.argv[index + 1] && !process.argv[index + 1].startsWith('--'), `${name} requires a path`)
  return path.resolve(process.argv[index + 1])
}
const sourceRoot = option('--source-root', ownRoot)
const dependenciesRoot = option('--dependencies-root', path.join(ownRoot, 'apps/command-center-v3'))
const out = option('--out', null)
assert(out, '--out evidence directory required')
const require = createRequire(path.join(dependenciesRoot, 'package.json'))
const { build } = require('esbuild')
const { chromium } = require('@playwright/test')
const app = path.join(sourceRoot, 'apps/wealth')
const endpoint = '/api/v2/wealth/home-v2'
const origin = 'http://home-lifecycle.invalid'
const checks = []
const failures = []
const stamp = '2040-01-01T00:00:00Z'
const nextStamp = '2040-01-02T00:00:00Z'
const synthetic = (label, clock = stamp) => ({
  schema: 'WealthHome@v2', today: { movers: { available: true, clock, source: 'Synthetic producer',
    rows: [{ label, clock, facts: [{ label: 'Move', value: '+1%', state: 'green', clock }] }] } },
})
const entry = `import React from 'react';import{createRoot}from'react-dom/client';
import{MemoryRouter}from'react-router-dom';import{useReadsControl,HomeLive}from'./src/pages/home/HomeLive';
import{homeV2Model}from'./src/pages/home/homeV2Adapter';import{DrawerProvider}from'./src/components/Drawer';
import{OperatingHeaderProvider}from'./src/shell/OperatingHeader';
const root=createRoot(document.getElementById('root'));
function Probe({seconds,path}){const c=useReadsControl({dashboard:path},seconds);window.reads=c.reads;
window.retry=c.retry;window.loading=c.loading;window.model=homeV2Model(c.reads.dashboard??null);
return <pre id="probe">{JSON.stringify(c.reads)}</pre>}
window.boot=x=>root.render(x.kind==='home'?<MemoryRouter><DrawerProvider><OperatingHeaderProvider>
<HomeLive view={x.view||'today'}/></OperatingHeaderProvider></DrawerProvider></MemoryRouter>:
<Probe seconds={x.seconds} path={x.path}/>);window.unmount=()=>root.unmount();`
const bundled = await build({
  stdin: { contents: entry, loader: 'tsx', resolveDir: app, sourcefile: 'home-read-lifecycle.fixture.tsx' },
  nodePaths: [path.join(dependenciesRoot, 'node_modules')], bundle: true, write: false,
  platform: 'browser', format: 'iife', jsx: 'automatic', loader: { '.css': 'empty' },
  define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent',
})
const bundle = bundled.outputFiles[0].text
const browser = await chromium.launch({ headless: true })
async function fresh() {
  const page = await browser.newPage()
  page.setDefaultTimeout(5000)
  page.setDefaultNavigationTimeout(5000)
  await page.clock.install()
  const escaped = []
  page.on('request', request => {
    if (![origin + '/', origin + '/bundle.js'].includes(request.url())) escaped.push(request.url())
  })
  await page.route('**/*', route => {
    if (route.request().method() !== 'GET') return route.abort()
    if (route.request().url() === origin + '/') return route.fulfill({ contentType: 'text/html', body: '<div id="root"></div><script src="/bundle.js"></script>' })
    if (route.request().url() === origin + '/bundle.js') return route.fulfill({ contentType: 'text/javascript', body: bundle })
    return route.abort()
  })
  await page.addInitScript(() => {
    window.requests = []
    window.violations = 0
    window.ignoreAbort = false
    window.fetch = (input, init = {}) => {
      const value = String(input)
      const url = new URL(value, location.origin)
      const allowed = ['/api/v2/wealth/home-v2', '/api/v2/wealth/operating-header', '/api/v2/home/cio-card']
      if (url.origin !== location.origin || !allowed.includes(url.pathname) || (init.method || 'GET') !== 'GET') {
        window.violations++
        return Promise.reject(new Error('Unexpected fixture read refused'))
      }
      return new Promise((resolve, reject) => {
        const entry = { path: value, aborted: false, settled: false, resolve: (body, status = 200) => {
          entry.settled = true
          resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
        } }
        window.requests.push(entry)
        init.signal?.addEventListener('abort', () => {
          entry.aborted = true
          if (!window.ignoreAbort) reject(new DOMException('Intentional fixture cancellation', 'AbortError'))
        }, { once: true })
      })
    }
    window.respond = (index, body, status) => window.requests[index].resolve(body, status)
  })
  await page.goto(origin + '/')
  await page.waitForFunction(() => !!window.boot)
  page.fixtureEscaped = escaped
  return page
}
async function check(id, value) {
  assert(value, id)
  checks.push(id)
}
async function scenario(name, run) {
  let page
  try {
    page = await fresh()
    await run(page)
    await check(name + ': only admitted synthetic GETs', await page.evaluate(() => window.violations === 0) && page.fixtureEscaped.length === 0)
  } catch (error) {
    failures.push({ scenario: name, error: String(error.message) })
  } finally {
    if (page) await page.close()
  }
}
async function bootProbe(page, seconds = 60, suffix = '') {
  await page.evaluate(({ path, seconds }) => window.boot({ kind: 'probe', path, seconds }), { path: endpoint + suffix, seconds })
}
async function respond(page, index, body, status = 200) {
  await page.evaluate(({ index, body, status }) => window.respond(index, body, status), { index, body, status })
}
async function bootHome(page) {
  await page.evaluate(() => window.boot({ kind: 'home' }))
  await page.waitForFunction(() => window.requests.length === 2)
  return page.evaluate(() => ({
    home: window.requests.findIndex(r => r.path.endsWith('home-v2')),
    header: window.requests.findIndex(r => r.path.includes('operating-header')),
  }))
}
try {
  await scenario('retiming and last good', async page => {
    await bootProbe(page, 300)
    await page.waitForFunction(() => window.requests.length === 1)
    await bootProbe(page, 60)
    await page.waitForTimeout(20)
    await check('300 to 60 does not abort or duplicate initial read', await page.evaluate(() => window.requests.length === 1 && !window.requests[0].aborted))
    await respond(page, 0, synthetic('FIRST'))
    await page.waitForFunction(() => window.reads.dashboard?.ok === true)
    await page.clock.runFor(60001)
    await page.waitForFunction(() => window.requests.length === 2)
    await respond(page, 1, {}, 503)
    await page.waitForFunction(() => window.reads.dashboard?.status === 503)
    await check('failed refresh retains own source clock with neutral semantics', await page.evaluate(stamp => window.model.today.movers.rows[0].clock === stamp && window.model.today.movers.rows[0].state === 'grey' && window.model.today.movers.state === 'amber' && window.model.error === 'HTTP 503', stamp))
    await page.clock.runFor(60001)
    await page.waitForFunction(() => window.requests.length === 3)
    await respond(page, 2, synthetic('RECOVERED', nextStamp))
    await page.waitForFunction(() => window.model.today.movers?.rows?.[0]?.label === 'RECOVERED')
    await check('successful refresh recovers with new own source clock', await page.evaluate(stamp => window.model.error === null && window.model.today.movers.rows[0].clock === stamp, nextStamp))
    await page.evaluate(() => window.unmount())
    await page.clock.runFor(120001)
    await check('unmount cancels future polls', await page.evaluate(() => window.requests.length === 3))
  })
  await scenario('out of order and cancellation', async page => {
    await bootProbe(page, 60, '?fixture=old')
    await page.waitForFunction(() => window.requests.length === 1)
    await page.evaluate(() => { window.ignoreAbort = true })
    await bootProbe(page, 60, '?fixture=new')
    await page.waitForFunction(() => window.requests.length === 2)
    await respond(page, 1, synthetic('NEW PATH', nextStamp))
    await page.waitForFunction(() => window.model.today.movers?.rows?.[0]?.label === 'NEW PATH')
    await respond(page, 0, synthetic('ABANDONED'))
    await page.waitForTimeout(20)
    await check('abandoned late path cannot replace current view', await page.evaluate(() => window.model.today.movers.rows[0].label === 'NEW PATH'))
    await bootProbe(page, 60, '?fixture=old')
    await page.waitForFunction(() => window.requests.length === 3)
    await respond(page, 2, {}, 503)
    await page.waitForFunction(() => window.reads.dashboard?.status === 503)
    await check('abandoned transport cannot poison retained cache', await page.evaluate(() => window.reads.dashboard.lastGood === null))
  })
  await scenario('real header drawers and tab changes', async page => {
    const ids = await bootHome(page)
    await respond(page, ids.header, { schema: 'WealthOperatingHeader@v1', poll_after_s: 60, session: { key: 'premarket' }, cells: {} })
    await page.waitForTimeout(20)
    await check('real provider settlement leaves slow Home request alive', await page.evaluate(i => !window.requests[i].aborted, ids.home))
    await page.getByRole('button', { name: 'CIO context', exact: true }).click()
    await page.waitForFunction(() => window.requests.some(r => r.path === '/api/v2/home/cio-card'))
    await page.getByRole('button', { name: 'Close detail', exact: true }).click()
    await check('CIO drawer cancellation affects only its own read', await page.evaluate(i => !window.requests[i].aborted && window.requests.find(r => r.path === '/api/v2/home/cio-card').aborted, ids.home))
    await page.getByRole('button', { name: 'Sources & clocks', exact: true }).click()
    await page.getByRole('button', { name: 'Close detail', exact: true }).click()
    await check('source drawer leaves slow Home request alive', await page.evaluate(i => !window.requests[i].aborted, ids.home))
    await respond(page, ids.home, synthetic('ACTUAL COLD LOAD'))
    await page.getByText('ACTUAL COLD LOAD', { exact: true }).waitFor()
    for (const view of ['outlook', 'needs', 'today']) {
      await page.evaluate(view => window.boot({ kind: 'home', view }), view)
      await page.locator(`[data-home-view="${view}"]`).waitFor()
    }
    await check('all three tab mounts reuse one dashboard read', await page.evaluate(() => window.requests.filter(r => r.path.endsWith('home-v2')).length === 1))
  })
  await scenario('first load Retry and recovery', async page => {
    const ids = await bootHome(page)
    await respond(page, ids.home, {}, 503)
    await page.getByText(/Home stored read failed/).waitFor()
    const copy = await page.locator('#root').innerText()
    await check('first failure truthfully says no earlier snapshot', copy.includes('No earlier Home read succeeded') && !copy.includes('Retained values below are the last successful read'))
    const retry = page.getByRole('button', { name: 'Retry', exact: true })
    await retry.click()
    await page.waitForFunction(() => window.requests.filter(r => r.path.endsWith('home-v2')).length === 2)
    await check('Retry disables while refresh is pending', await page.getByRole('button', { name: 'Retrying…', exact: true }).isDisabled())
    await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent === 'Retrying…'); b.click(); b.click() })
    await check('repeated disabled Retry does not duplicate a request', await page.evaluate(() => window.requests.filter(r => r.path.endsWith('home-v2')).length === 2))
    const pending = await page.evaluate(() => window.requests.findIndex((r, i) => i > 1 && r.path.endsWith('home-v2')))
    await respond(page, pending, {}, 503)
    await page.getByRole('button', { name: 'Retry', exact: true }).waitFor()
    await check('failed Retry stays truthful and permits a later Retry', (await page.locator('#root').innerText()).includes('No earlier Home read succeeded'))
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await page.waitForFunction(() => window.requests.filter(r => r.path.endsWith('home-v2')).length === 3)
    const recovered = await page.evaluate(() => window.requests.findLastIndex(r => r.path.endsWith('home-v2')))
    await respond(page, recovered, synthetic('RETRY SUCCESS'))
    await page.getByText('RETRY SUCCESS', { exact: true }).waitFor()
    await check('Retry success removes failure and retry copy', (await page.getByText(/Home stored read failed/).count()) === 0)
  })
  await scenario('refresh failure copy and retained retry', async page => {
    const ids = await bootHome(page)
    await respond(page, ids.home, synthetic('RETAINED'))
    await page.getByText('RETAINED', { exact: true }).waitFor()
    await page.clock.runFor(300001)
    const pending = await page.evaluate(() => window.requests.findIndex((r, i) => i !== window.requests.findIndex(r => r.path.endsWith('home-v2')) && r.path.endsWith('home-v2')))
    assert(pending >= 0, 'Home scheduled refresh reached the fixture')
    await respond(page, pending, {}, 503)
    await page.getByText(/Home stored read failed/).waitFor()
    await check('genuine failed refresh visibly retains previous own observation', (await page.locator('#root').innerText()).includes('Retained values below are the last successful read') && (await page.getByText('RETAINED', { exact: true }).count()) === 1)
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    const recovery = await page.evaluate(() => window.requests.length - 1)
    await respond(page, recovery, synthetic('FRESH AFTER FAILURE', nextStamp))
    await page.getByText('FRESH AFTER FAILURE', { exact: true }).waitFor()
    await check('retained failure recovers without stale error banner', (await page.getByText(/Home stored read failed/).count()) === 0)
  })
  await scenario('timeout and unmount', async page => {
    await bootProbe(page)
    await page.waitForFunction(() => window.requests.length === 1)
    await page.clock.runFor(8001)
    await page.waitForFunction(() => window.reads.dashboard?.timedOut === true)
    await check('genuine first-read timeout has error and no invented last good', await page.evaluate(() => window.reads.dashboard.data === null && window.reads.dashboard.lastGood === null && /timed out after 8000 ms/.test(window.reads.dashboard.error)))
    await page.evaluate(() => { window.retry(); window.retry() })
    await page.waitForFunction(() => window.requests.length === 2)
    await check('synchronous hook Retry calls share one pending refresh', await page.evaluate(() => window.requests.length === 2))
    await page.evaluate(() => window.unmount())
    await check('unmount aborts pending page request', await page.evaluate(() => window.requests[1].aborted))
    await page.clock.runFor(120001)
    await check('unmounted page never retries itself', await page.evaluate(() => window.requests.length === 2))
  })
} finally {
  await browser.close()
  fs.mkdirSync(out, { recursive: true })
  fs.writeFileSync(path.join(out, 'home-read-lifecycle.json'), JSON.stringify({
    schema: 'HomeReadLifecycleBrowserFixture@v1', as_of: new Date().toISOString(),
    synthetic_only: true, live_requests: 0, scenarios: 6, checks, failures,
  }, null, 2) + '\n')
}
console.log(`Home lifecycle fixture: ${checks.length} checks passed; ${failures.length} scenarios failed; live requests 0`)
for (const failure of failures) console.error(failure.scenario + ': ' + failure.error)
assert.equal(failures.length, 0, 'Home lifecycle browser regression failed; see synthetic receipt')
