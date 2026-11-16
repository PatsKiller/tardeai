'use strict'
// Portfolio browser acceptance suite.
//   node qual/portfolio/run.cjs --dist <built dist dir> [--out <dir>] [--only holdings,income] [--widths 390,1280] [--skip-lifecycle]
// Needs Playwright: NODE_PATH=<repo>/node_modules (see the runner note in the READY file). No network: the built dist
// and every endpoint are served through page.route on a fake host. Writes <out>/results.json and <out>/shots/*.png.
// Exit code: 0 all assertions pass, 1 any failure, 2 usage/harness error.
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')
const F = require('./fixtures.cjs')
const { ROUTES, KNOWN_WEALTH_ROUTES, NOT_BUILT_TEXT } = require('./routes.cjs')
const H = require('./harness.cjs')

const args = process.argv.slice(2)
const arg = (n, d = null) => { const i = args.indexOf('--' + n); return i < 0 ? d : (args[i + 1] ?? true) }
const dist = arg('dist') && path.resolve(arg('dist'))
if (!dist || !fs.existsSync(path.join(dist, 'index.html'))) { console.error('usage: run.cjs --dist <dir containing index.html> [--out dir]'); process.exit(2) }
const out = path.resolve(arg('out', path.join(process.env.TMPDIR || process.cwd(), 'qual-portfolio-out')))
const only = arg('only') ? String(arg('only')).split(',') : null
const widths = arg('widths') ? String(arg('widths')).split(',').map(Number) : H.WIDTHS
fs.mkdirSync(path.join(out, 'shots'), { recursive: true })

const results = []
const add = (route, width, assertion, pass, detail = '') => { results.push({ route, width, assertion, pass: !!pass, detail: String(detail).slice(0, 400) }); return !!pass }
const expect = F.expectations()
const live = ROUTES.filter(r => r.status === 'built' && (!only || only.includes(r.id)))
const allRoutes = ROUTES.filter(r => !only || only.includes(r.id))

async function open(browser, width, setup) {
  const ctl = H.newController(); if (setup) setup(ctl)
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  await H.attach(page, dist, ctl)
  return { page, ctl }
}

async function common(page, ctl, route, width, tag = '') {
  const n = a => route.id + (tag ? ':' + tag : '') && a
  const m = await page.evaluate(() => ({
    iw: window.innerWidth, sw: document.documentElement.scrollWidth, bsw: document.body.scrollWidth,
    h1: document.querySelectorAll('h1').length, mainH1: document.querySelectorAll('main h1').length, mainH2: document.querySelectorAll('main h2').length,
    text: document.body.innerText,
    attrs: [...document.querySelectorAll('[aria-label],[title],[alt]')].map(e => (e.getAttribute('aria-label') || '') + ' ' + (e.getAttribute('title') || '') + ' ' + (e.getAttribute('alt') || '')).join(' | '),
  }))
  const t = tag ? '[' + tag + '] ' : ''
  add(route.id, width, t + 'viewport-width-measured', m.iw === width, `innerWidth=${m.iw}`)
  add(route.id, width, t + 'no-lateral-scroll', m.sw <= m.iw && m.bsw <= m.iw, `scrollWidth=${m.sw} body=${m.bsw} innerWidth=${m.iw}`)
  add(route.id, width, t + 'exactly-one-h1', m.h1 === 1, `h1=${m.h1}`)
  add(route.id, width, t + 'page-heading-is-h2', m.mainH2 >= 1, `main h2=${m.mainH2}`)
  const rk = m.text.match(F.RAW_KEY_RE)
  add(route.id, width, t + 'no-raw-account-keys-visible', !rk, rk ? 'visible: ' + rk[0] : '')
  const ra = m.attrs.match(F.RAW_KEY_RE)
  add(route.id, width, t + 'no-raw-account-keys-in-accessible-names', !ra, ra ? 'attr: ' + ra[0] : '')
  add(route.id, width, t + 'no-page-errors', ctl.errors.length === 0, ctl.errors.slice(0, 2).join(' || '))
  add(route.id, width, t + 'no-request-outside-fake-host', ctl.external.length === 0, ctl.external.slice(0, 3).join(' || '))
  add(route.id, width, t + 'get-only', ctl.nonGet.length === 0, ctl.nonGet.slice(0, 3).join(' || '))
  add(route.id, width, t + 'no-unfixtured-api-read', ctl.unfixtured.length === 0, [...new Set(ctl.unfixtured)].join(', '))
  return m
}

async function goReady(page, route, pathAndQuery, timeout = 12000) {
  await page.goto(H.url(pathAndQuery || route.path), { waitUntil: 'domcontentloaded' })
  return H.waitText(page, route.ready || [], timeout)
}

// ---------------------------------------------------------------- per route x width
async function perRouteWidth(browser, route, width) {
  const { page, ctl } = await open(browser, width)
  if (route.status === 'not-built') {
    await page.goto(H.url(route.path), { waitUntil: 'domcontentloaded' })
    const ok = await H.waitText(page, ['Not built yet'], 8000)
    const main = await H.mainText(page)
    add(route.id, width, 'states-not-built-truthfully', ok && NOT_BUILT_TEXT.test(main), main.slice(0, 120).replace(/\s+/g, ' '))
    add(route.id, width, 'no-figures-or-tables-while-not-built', !/\$\s?\d/.test(main) && (await page.locator('main table').count()) === 0, 'main shows a $ figure or a table')
    await common(page, ctl, route, width)
    await page.screenshot({ path: path.join(out, 'shots', `${route.id}-${width}.png`), fullPage: true })
    await page.close(); return
  }
  if (!route.ready || !route.populated) { add(route.id, width, 'built-route-has-expectation', false, 'status built but ready/populated not declared in routes.cjs'); await page.close(); return }
  const ready = await goReady(page, route)
  const main = await H.mainText(page)
  add(route.id, width, 'leaves-loading-and-shows-data', ready, ready ? '' : 'missing: ' + H.has(await H.bodyText(page), route.ready).join(', ') + ' | main: ' + main.slice(0, 160).replace(/\s+/g, ' '))
  const text = await H.bodyText(page)
  const miss = H.has(text, route.populated)
  add(route.id, width, 'visible-populated-data', miss.length === 0, miss.length ? 'not visible: ' + miss.join(', ') : '')
  add(route.id, width, 'reads-were-requested', route.reads.every(p => (ctl.hits[p] || 0) >= 1), JSON.stringify(ctl.hits))
  await common(page, ctl, route, width)
  await page.screenshot({ path: path.join(out, 'shots', `${route.id}-${width}.png`), fullPage: true })
  const fn = INTERACTIONS[route.id]
  if (fn) await fn(browser, route, width)
  await page.close()
}

// ---------------------------------------------------------------- interactions
const countOf = async page => {
  const t = await H.mainText(page); const m = t.match(/Positions · (\d+) filtered account rows/); return m ? Number(m[1]) : null
}
function parseCsv(s) {
  const rows = []; let row = [], f = '', q = false
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (q) { if (c === '"' && s[i + 1] === '"') { f += '"'; i++ } else if (c === '"') q = false; else f += c }
    else if (c === '"') q = true
    else if (c === ',') { row.push(f); f = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && s[i + 1] === '\n') i++; row.push(f); rows.push(row); row = []; f = '' }
    else f += c
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row) }
  return rows
}
async function downloadCsv(page) {
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 8000 }), page.getByRole('button', { name: 'Export CSV' }).click()])
  const p = await dl.path(); return { name: dl.suggestedFilename(), rows: parseCsv(fs.readFileSync(p, 'utf8')) }
}

const INTERACTIONS = {
  async holdings(browser, route, width) {
    const R = 'holdings'
    const { page, ctl } = await open(browser, width)
    const tag = s => s
    await goReady(page, route)
    // Collapsed default and the disclosure.
    let t = await H.mainText(page)
    const tbl = async () => (await page.locator('main table').allInnerTexts()).join('\n')
    add(R, width, 'default-collapses-small-rows', !(await tbl()).includes('QZSA') && (await page.locator('tr[data-group="small"]').count()) === 1, 'QZSA visible by default or no small group')
    add(R, width, 'disclosure-states-collapsed-rows', /collapsed/i.test(await page.locator('.hv-disclosure').innerText().catch(() => '')), '')
    // Show all.
    await page.locator('.hv-disclosure button').click(); await page.waitForTimeout(150)
    t = await H.mainText(page)
    add(R, width, 'show-all-reveals-every-collapsed-row', t.includes('QZSA') && t.includes('QZSL') && t.includes('QZCASH') && page.url().includes('hv_show=all'), 'url=' + page.url().slice(-40))
    // Search reveal.
    await goReady(page, route, route.path + '?hv_query=qzsc')
    t = await H.mainText(page)
    add(R, width, 'search-reveals-collapsed-match', t.includes('QZSC') && !t.includes('QZSA'), '')
    // Mixed badge on the multi-account parent.
    await goReady(page, route)
    const mixed = await page.locator('tr[data-group="security-QZBIG"] .hv-mixed').innerText().catch(() => '')
    add(R, width, 'mixed-protection-badge-with-counts', /Mixed/.test(mixed) && /\d/.test(mixed), mixed)
    // Protection filter classes + legacy PROTECTED.
    for (const [cls, n] of Object.entries(expect.byProtection)) {
      if (cls === 'n/a') continue
      await goReady(page, route, `${route.path}?hv_protection=${cls}`)
      const c = await countOf(page)
      add(R, width, `protection-filter-${cls}`, c === n, `shown ${c} expected ${n}`)
    }
    await goReady(page, route, `${route.path}?hv_protection=PROTECTED`)
    const legacy = await countOf(page)
    add(R, width, 'legacy-PROTECTED-means-active-only', legacy === expect.byProtection.active, `shown ${legacy} expected ${expect.byProtection.active}`)
    // Protection select drives the filter.
    await goReady(page, route)
    await page.getByLabel('Protection', { exact: true }).selectOption('pending'); await page.waitForTimeout(150)
    add(R, width, 'protection-select-filters', (await countOf(page)) === expect.byProtection.pending, `shown ${await countOf(page)}`)
    // Account scope.
    await goReady(page, route)
    await page.getByLabel('Holdings account').selectOption(F.ACCOUNTS.roth.key); await page.waitForTimeout(200)
    t = await H.mainText(page)
    add(R, width, 'account-scope-filter', (await countOf(page)) === expect.rothRows && !(await page.locator('main table').allInnerTexts()).join(' ').includes('Synthetic Taxable'), `shown ${await countOf(page)} expected ${expect.rothRows}`)
    // CSV export under the account filter, then unfiltered.
    const shown = await countOf(page)
    const csv = await downloadCsv(page).catch(e => ({ err: String(e) }))
    add(R, width, 'csv-export-captured', !!csv.rows, csv.err || csv.name)
    if (csv.rows) {
      add(R, width, 'csv-header-row', JSON.stringify(csv.rows[0].slice(0, 6)) === JSON.stringify(F.HOLDINGS_COLUMNS), csv.rows[0].slice(0, 6).join(' | '))
      const body = csv.rows.slice(1).filter(r => r.length > 1)
      add(R, width, 'csv-rows-match-visible-filtered-rows', body.length === shown, `csv ${body.length} visible ${shown}`)
      add(R, width, 'csv-no-raw-account-keys', !F.RAW_KEY_RE.test(csv.rows.map(r => r.join(',')).join('\n')), '')
    }
    await goReady(page, route)
    const all = await downloadCsv(page).catch(() => null)
    add(R, width, 'csv-unfiltered-row-count', !!all && all.rows.slice(1).filter(r => r.length > 1).length === (await countOf(page)) && (await countOf(page)) === expect.rows, `visible ${await countOf(page)} fixture ${expect.rows}`)
    // Row drawer: open, Escape, focus return.
    await goReady(page, route)
    await page.getByRole('button', { name: 'Expand QZBIG' }).click()
    const origin = page.locator('tr.hv-child button.hv-link').first()
    await origin.evaluate(e => { e.dataset.qaOrigin = '1' }); await origin.click()
    const dlg = page.locator('[role="dialog"]')
    add(R, width, 'drawer-opens', await dlg.isVisible().catch(() => false), '')
    const dText = await dlg.innerText().catch(() => '')
    add(R, width, 'drawer-shows-row-and-no-raw-keys', /QZBIG/.test(dText) && !F.RAW_KEY_RE.test(dText), dText.slice(0, 80).replace(/\s+/g, ' '))
    await common(page, ctl, route, width, 'drawer-open')
    await page.keyboard.press('Escape'); await page.waitForTimeout(150)
    add(R, width, 'drawer-escape-closes', (await dlg.count()) === 0, '')
    add(R, width, 'drawer-focus-returns-to-origin', await page.evaluate(() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.qaOrigin === '1'), '')
    // The expanded view still has no lateral scroll.
    await common(page, ctl, route, width, 'after-interactions')
    await page.close()
  },

  async fundamentals(browser, route, width) {
    const R = 'fundamentals'
    const { page } = await open(browser, width)
    await goReady(page, route)
    let t = await H.mainText(page)
    const ft = (await page.locator('main table').allInnerTexts()).join('\n')
    add(R, width, 'default-collapses-small-and-cash', !ft.includes('QZSA') && !ft.includes('QZCASH'), '')
    add(R, width, 'disclosure-present', /collapsed/i.test(await page.locator('.fv-disclosure').innerText().catch(() => '')), '')
    await page.locator('.fv-disclosure button').first().click().catch(() => {}); await page.waitForTimeout(200)
    t = await H.mainText(page)
    add(R, width, 'show-all-reveals-collapsed-rows', t.includes('QZSA') && t.includes('QZSL') && t.includes('QZCASH') && page.url().includes('fv_show=all'), 'url=' + page.url().slice(-40))
    await goReady(page, route)
    await page.getByLabel('Find holding').fill('qzsc'); await page.waitForTimeout(250)
    t = await H.mainText(page)
    add(R, width, 'search-reveals-collapsed-match', t.includes('QZSC') && !t.includes('QZSA'), '')
    await goReady(page, route)
    await page.getByRole('button', { name: 'Risk & ownership' }).click(); await page.waitForTimeout(150)
    t = await H.mainText(page)
    add(R, width, 'ownership-over-100-shown-not-clamped', /112\.4/.test(t), 'inst ownership 112.4 not visible')
    await page.close()
  },

  async allocation(browser, route, width) {
    const R = 'allocation'
    const { page } = await open(browser, width)
    await goReady(page, route)
    const m = async () => { const t = await H.mainText(page); const x = t.match(/(\d+) matching rows/); return x ? Number(x[1]) : null }
    const before = await m()
    const sleeves = page.locator('button[aria-label^="Filter sleeve:"]')
    add(R, width, 'sleeve-buttons-present', (await sleeves.count()) >= 2, `n=${await sleeves.count()}`)
    await sleeves.nth(1).click().catch(() => {}); await page.waitForTimeout(250)
    const drilled = await m()
    add(R, width, 'drill-narrows-selected-view', before !== null && drilled !== null && drilled < before, `before ${before} after ${drilled}`)
    await common(page, H.newController(), route, width, 'drilled').catch(() => {})
    await page.getByRole('button', { name: 'Reset filters' }).click(); await page.waitForTimeout(250)
    add(R, width, 'reset-restores-full-view', (await m()) === before, `after reset ${await m()} expected ${before}`)
    await page.close()
  },

  async income(browser, route, width) {
    const R = 'income'
    const { page, ctl } = await open(browser, width)
    await goReady(page, route)
    const t = await H.mainText(page)
    await page.getByRole('button', { name: 'Forecast evidence' }).click()
    const ev = page.locator('[role="dialog"]')
    const evText = await ev.innerText().catch(() => '')
    const rec = evText.match(/Twelve projected months[^\n]*/)
    add(R, width, 'reconciliation-line-shown', !!rec && /annual less not-placed/.test(rec[0]) && /difference/.test(rec[0]) && /per-month rounding/.test(rec[0]), rec ? rec[0] : 'not found in evidence drawer')
    await page.keyboard.press('Escape'); await page.waitForTimeout(150)
    add(R, width, 'unplaced-payer-named', /not placed[^\n]*QZUNPL/.test(t), '')
    add(R, width, 'registry-names-shown-derived-label-becomes-stable-ref', /Synthetic Taxable/.test(t) && /acct-[0-9a-f]{8}/.test(t) && !/SYN_OTHER/i.test(t), '')
    await page.getByRole('button', { name: 'Review income thesis' }).click()
    const dlg = page.locator('[role="dialog"]')
    add(R, width, 'thesis-drawer-opens', await dlg.isVisible().catch(() => false), '')
    await common(page, ctl, route, width, 'drawer-open')
    await page.keyboard.press('Escape'); await page.waitForTimeout(150)
    add(R, width, 'thesis-drawer-escape-closes', (await dlg.count()) === 0, '')
    const detail = page.getByRole('button', { name: 'Read forecast' })
    if (await detail.count()) {
      await detail.first().click().catch(() => {}); await page.waitForTimeout(150)
      add(R, width, 'payer-drawer-opens', await dlg.isVisible().catch(() => false), '')
      await page.keyboard.press('Escape')
    } else add(R, width, 'payer-drawer-opens', false, 'no payer detail button found')
    await page.close()
  },

  async performance(browser, route, width) {
    const R = 'performance'
    const { page } = await open(browser, width)
    await goReady(page, route)
    const t = await H.mainText(page)
    const cov = t.match(/\d+ accounts? with performance rows[^\n]*/)
    add(R, width, 'account-coverage-names-missing-account', !!cov && /Synthetic NoPerf/.test(cov[0]) && /unknown, not zero/i.test(cov[0]), cov ? cov[0].slice(0, 200) : 'coverage line absent')
    const accts = await page.locator('[data-performance-account]').count()
    add(R, width, 'account-panels-listed', accts === 2, `panels ${accts}`)
    add(R, width, 'household-residual-labelled-not-account-profit', /Household only; not individual account profit|household/i.test(t), '')
    await page.close()
  },
}

// ---------------------------------------------------------------- links
async function linkCheck(browser) {
  const seen = new Set()
  for (const route of live) {
    const { page } = await open(browser, 1280)
    await goReady(page, route)
    const hrefs = await page.evaluate(() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')))
    await page.close()
    for (const h of hrefs) {
      if (!h || h.startsWith('#') || /^(mailto:|javascript:)/.test(h)) continue
      const u = new URL(h, 'http://wealth.test' + route.path)
      if (u.hostname !== 'wealth.test') { add(route.id, 1280, 'link-internal-only:' + h.slice(0, 60), false, 'external link ' + h); continue }
      const p = u.pathname.replace(/\/$/, '') || '/'
      if (!p.startsWith('/wealth')) { add(route.id, 1280, 'link-classic-site:' + p, true, 'points outside /wealth (classic); not followed'); continue }
      const key = p; if (seen.has(key)) continue; seen.add(key)
      const known = KNOWN_WEALTH_ROUTES.map(x => x.replace(/\/$/, '')).includes(p) || /^\/wealth\/[a-z-]+\/[a-z-]+$/.test(p)
      const { page: q, ctl } = await open(browser, 1280)
      await q.goto(H.url(p), { waitUntil: 'domcontentloaded' }); await q.waitForTimeout(700)
      const t = await H.bodyText(q)
      add(route.id, 1280, 'link-resolves-to-known-wealth-route:' + p, known && !/Unknown Wealth (route|address)/i.test(t), known ? t.slice(0, 80).replace(/\s+/g, ' ') : 'not in the known-route list')
      await q.close()
    }
  }
}

// ---------------------------------------------------------------- lifecycle
const LOADING = () => {
  const m = document.querySelector('main'); if (!m) return true
  const t = m.innerText
  return !!m.querySelector('[aria-busy="true"]') || /^\s*(Reading|Loading)\b/i.test(t) || t.trim().length < 20
}
const HONEST = /(could not be read|read failed|last available|last good|not current|failed|unavailable|unknown|not served|timed out|non-JSON|HTTP \d{3}|\d+ ?(s|min|h) old)/i
async function settle(page, timeout) {
  try { await page.waitForFunction(() => { const m = document.querySelector('main'); if (!m) return false
    const t = m.innerText; return !(m.querySelector('[aria-busy="true"]') || /^\s*(Reading|Loading)\b/i.test(t) || t.trim().length < 20) }, null, { timeout }); return true } catch { return false }
}

async function honestWait(page, timeout) {
  try { await page.waitForFunction(src => new RegExp(src, 'i').test(document.querySelector('main')?.innerText || ''), HONEST.source, { timeout }); return true } catch { return false }
}

async function lifecycle(browser) {
  for (const width of [390, 1280]) {
    for (const route of live) {
      const reads = route.reads
      // P1 race: header settles first, the page read is still in flight.
      {
        const { page, ctl } = await open(browser, width, c => { for (const p of reads) c.behave[p] = () => ({ kind: 'ok', delay: 700 }); c.behave['/api/v2/wealth/operating-header'] = () => ({ kind: 'ok', delay: 60 }) })
        const ok = await goReady(page, route, route.path, 15000)
        const aborted = ctl.failed.filter(p => reads.includes(p))
        add(route.id, width, 'p1-cold-load-header-before-page-read', ok && aborted.length === 0 && reads.every(p => (ctl.finished[p] || 0) >= 1), `ready=${ok} aborted=${aborted.join(',')} finished=${JSON.stringify(ctl.finished)}`)
        await page.close()
      }
      // 500 then recovery by refresh.
      {
        const { page, ctl } = await open(browser, width, c => { for (const p of reads) c.behave[p] = () => '500' })
        await page.goto(H.url(route.path), { waitUntil: 'domcontentloaded' })
        const left = await settle(page, 14000)
        const main = await H.mainText(page)
        add(route.id, width, 'http500-leaves-loading-with-honest-error', left && HONEST.test(main) && !main.includes('QZ'), `left=${left} main=${main.slice(0, 140).replace(/\s+/g, ' ')}`)
        add(route.id, width, 'http500-no-page-errors', ctl.errors.length === 0, ctl.errors.join('||'))
        for (const p of reads) ctl.behave[p] = () => 'ok'
        await page.reload({ waitUntil: 'domcontentloaded' })
        const rec = await H.waitText(page, route.ready, 12000)
        add(route.id, width, 'http500-then-refresh-recovers', rec, rec ? '' : 'still not populated after refresh')
        await page.close()
      }
      // non-JSON 200.
      {
        const { page, ctl } = await open(browser, width, c => { for (const p of reads) c.behave[p] = () => 'nonjson' })
        await page.goto(H.url(route.path), { waitUntil: 'domcontentloaded' })
        const left = await settle(page, 14000)
        const main = await H.mainText(page)
        add(route.id, width, 'nonjson-200-leaves-loading-with-honest-error', left && HONEST.test(main), `left=${left} main=${main.slice(0, 140).replace(/\s+/g, ' ')}`)
        add(route.id, width, 'nonjson-200-no-page-errors', ctl.errors.length === 0, ctl.errors.join('||'))
        await page.close()
      }
      // Last-good with age: a read succeeds, the route is left and re-entered while the read fails.
      if (width === 1280) {
        const { page, ctl } = await open(browser, width)
        const other = live.find(r => r.id !== route.id && r.reads.every(p => !route.reads.includes(p))) || live.find(r => r.id !== route.id)
        const ok = await goReady(page, route)
        await H.spaGo(page, other.path); await H.waitText(page, other.ready, 12000)
        for (const p of reads) ctl.behave[p] = () => '500'
        await H.spaGo(page, route.path); await page.waitForTimeout(600)
        const left = await settle(page, 14000)
        const main = await H.mainText(page)
        add(route.id, width, 'failed-refresh-shows-last-good-with-age-or-honest-error', ok && left && HONEST.test(main), `left=${left} main=${main.slice(0, 160).replace(/\s+/g, ' ')}`)
        await page.close()
      }
    }
    // Timeout (heavy readers wait 8 s): all routes in parallel, one width.
    if (width === 390) await Promise.all(live.map(async route => {
      const { page, ctl } = await open(browser, width, c => { for (const p of route.reads) c.behave[p] = () => 'hang' })
      await page.goto(H.url(route.path), { waitUntil: 'domcontentloaded' })
      const left = await honestWait(page, 25000)
      const main = await H.mainText(page)
      add(route.id, width, 'timeout-leaves-loading-with-honest-error', left && HONEST.test(main), `left=${left} main=${main.slice(0, 140).replace(/\s+/g, ' ')}`)
      add(route.id, width, 'timeout-no-page-errors', ctl.errors.length === 0, ctl.errors.join('||'))
      await page.close()
    }))
  }
  // Navigation between routes while reads are in flight.
  for (const width of [390, 1280]) {
    const { page, ctl } = await open(browser, width, c => { c.behave = Object.fromEntries(Object.keys(F.ENDPOINTS).filter(p => !p.includes('operating-header')).map(p => [p, () => ({ kind: 'ok', delay: 1500 })])) })
    const seq = live.map(r => r.path)
    await page.goto(H.url(seq[0]), { waitUntil: 'domcontentloaded' })
    for (const p of seq.slice(1)) { await page.waitForTimeout(250); await H.spaGo(page, p) }
    const last = live[live.length - 1]
    const ok = await H.waitText(page, last.ready, 15000)
    add('navigation', width, 'nav-while-reads-in-flight-final-page-populated', ok && page.url().endsWith(last.path), `url=${page.url()} ready=${ok}`)
    add('navigation', width, 'nav-while-reads-in-flight-no-errors', ctl.errors.length === 0 && ctl.external.length === 0 && ctl.nonGet.length === 0, ctl.errors.join('||'))
    await H.spaGo(page, live[0].path)
    add('navigation', width, 'nav-back-to-first-route-populated', await H.waitText(page, live[0].ready, 15000), '')
    await page.close()
  }
  // Browser back / forward.
  for (const width of [390, 1280]) {
    const { page, ctl } = await open(browser, width)
    const a = live[0], b = live[2] || live[1], c = live[3] || live[1]
    await goReady(page, a)
    await H.spaGo(page, b.path); await H.waitText(page, b.ready, 12000)
    await H.spaGo(page, c.path); await H.waitText(page, c.ready, 12000)
    const step = async (name, route, fn) => { await fn(); const ok = await H.waitText(page, route.ready, 12000); add('history', width, name, ok && page.url().endsWith(route.path), `url=${page.url()} populated=${ok}`) }
    await step('back-1-populated', b, () => page.goBack())
    await step('back-2-populated', a, () => page.goBack())
    await step('forward-1-populated', b, () => page.goForward())
    add('history', width, 'history-no-errors', ctl.errors.length === 0 && ctl.external.length === 0 && ctl.nonGet.length === 0, ctl.errors.join('||'))
    await page.close()
  }
}

;(async () => {
  const browser = await chromium.launch()
  const started = Date.now()
  try {
    // Worker pool across (route, width).
    const jobs = []
    for (const r of allRoutes) for (const w of widths) jobs.push([r, w])
    let i = 0
    await Promise.all(Array.from({ length: 3 }, async () => { while (i < jobs.length) { const [r, w] = jobs[i++]; await perRouteWidth(browser, r, w).catch(e => add(r.id, w, 'harness-error', false, String(e).slice(0, 300))) } }))
    await linkCheck(browser).catch(e => add('links', 0, 'harness-error', false, String(e).slice(0, 300)))
    if (!args.includes('--skip-lifecycle')) await lifecycle(browser).catch(e => add('lifecycle', 0, 'harness-error', false, String(e).slice(0, 300)))
  } finally { await browser.close() }
  const failed = results.filter(r => !r.pass)
  const summary = { dist, widths, cases: results.length, passed: results.length - failed.length, failed: failed.length, seconds: Math.round((Date.now() - started) / 1000), routesNotBuilt: ROUTES.filter(r => r.status === 'not-built').map(r => r.id) }
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ summary, results }, null, 1))
  const byA = {}
  for (const f of failed) { const k = f.route + ' | ' + f.assertion; (byA[k] = byA[k] || []).push(f.width) }
  console.log(JSON.stringify(summary))
  for (const [k, w] of Object.entries(byA)) console.log('FAIL', k, 'widths', [...new Set(w)].join(','))
  process.exit(failed.length ? 1 : 0)
})().catch(e => { console.error(e); process.exit(2) })
