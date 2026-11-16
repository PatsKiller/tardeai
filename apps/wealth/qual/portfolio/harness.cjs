'use strict'
// Fake-host harness: serves a built dist and the synthetic endpoints through page.route; nothing leaves the process.
const fs = require('fs')
const path = require('path')
const { ENDPOINTS, headerBody } = require('./fixtures.cjs')

const HOST = 'wealth.test'
const WIDTHS = [390, 412, 760, 1280, 1440]
const TYPES = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png', '.ico': 'image/x-icon' }
const delay = ms => new Promise(r => setTimeout(r, ms))

// behave[path] = (hitNumber, url) => 'ok' | '500' | 'hang' | 'nonjson' | { kind, delay }
function newController() {
  return { behave: {}, hits: {}, external: [], nonGet: [], unfixtured: [], failed: [], finished: {}, errors: [], consoleErrors: [], fixtureNow: Date.now(), pollAfterS: 60 }
}

async function attach(page, dist, ctl) {
  page.on('pageerror', e => ctl.errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') ctl.consoleErrors.push(m.text().slice(0, 200)) })
  page.on('requestfailed', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) ctl.failed.push(u.pathname) })
  page.on('requestfinished', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) ctl.finished[u.pathname] = (ctl.finished[u.pathname] || 0) + 1 })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (u.hostname !== HOST) { ctl.external.push(req.method() + ' ' + req.url().slice(0, 120)); return route.abort() }
    if (req.method() !== 'GET') { ctl.nonGet.push(req.method() + ' ' + u.pathname); return route.fulfill({ status: 405, body: '' }) }
    if (u.pathname.startsWith('/api/')) {
      const p = u.pathname
      ctl.hits[p] = (ctl.hits[p] || 0) + 1
      const build = ENDPOINTS[p]
      if (!build) { ctl.unfixtured.push(p); return route.fulfill({ status: 404, json: { ok: false } }) }
      let b = ctl.behave[p] ? ctl.behave[p](ctl.hits[p], u) : 'ok'
      if (typeof b === 'string') b = { kind: b, delay: 0 }
      if (b.delay) await delay(b.delay)
      try {
        if (b.kind === 'hang') return new Promise(() => {})
        if (b.kind === '500') return await route.fulfill({ status: 500, json: { ok: false, error: 'synthetic failure' } })
        if (b.kind === 'nonjson') return await route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>gateway page, not json</body></html>' })
        const body = p === '/api/v2/wealth/operating-header' ? headerBody(Date.now(), ctl.pollAfterS) : build(Date.now())
        return await route.fulfill({ json: body })
      } catch { return }
    }
    let f = u.pathname.replace(/^\/wealth\//, '')
    if (!f || !path.extname(f)) f = 'index.html'
    const p = path.join(dist, f)
    if (!p.startsWith(dist)) return route.fulfill({ status: 403, body: '' })
    return fs.existsSync(p)
      ? route.fulfill({ body: fs.readFileSync(p), contentType: TYPES[path.extname(p)] || 'application/octet-stream' })
      : route.fulfill({ status: 404, body: '' })
  })
}

const url = p => `http://${HOST}${p}`
const bodyText = page => page.evaluate(() => document.body.innerText)
const mainText = page => page.evaluate(() => (document.querySelector('main') || document.body).innerText)
const has = (text, needles) => needles.filter(n => !text.includes(n))

// Wait until all needles are visible in the page text (the page left LOADING and shows data), or time out.
async function waitText(page, needles, timeout = 12000) {
  try {
    await page.waitForFunction(ns => { const t = document.body.innerText; return ns.every(n => t.includes(n)) }, needles, { timeout })
    return true
  } catch { return false }
}

// Single-page-app navigation: click a real nav link when present (so the router and in-flight reads behave as for a
// person), otherwise push the history entry.
async function spaGo(page, to) {
  const link = page.locator(`a[href="${to}"]`).first()
  if ((await link.count()) && (await link.isVisible().catch(() => false))) { await link.click().catch(() => {}); return }
  await page.evaluate(p => { history.pushState({}, '', p); window.dispatchEvent(new PopStateEvent('popstate')) }, to)
}

module.exports = { HOST, WIDTHS, newController, attach, url, bodyText, mainText, has, waitText, spaGo, delay }
