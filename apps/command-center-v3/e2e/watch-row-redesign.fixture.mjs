// Actual WatchMyList/cards/handlers + real pure server sort/filter/facet code; no server/provider/DB.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { build } from 'esbuild'
import { chromium, expect } from '@playwright/test'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), repo = path.resolve(app, '../..')
const out = process.argv[2]
assert(out, 'explicit screenshot/receipt directory required')
fs.mkdirSync(out, { recursive: true })
const clock = '2026-10-24T14:00:00Z', observed = '2026-10-23T19:45:00Z'
const cases = ['held', 'formerly-held', 'never-held', 'conflict', 'no-catalyst', 'missing-level', 'missing-price']
function makeRow(kind, i) {
  const symbol = ['FATN', 'ANET', 'SMCI', 'DXCM', 'NCAT', 'NLEV', 'NPRC'][i]
  const fact = value => ({ value, source: 'symbol_profiles:fixture', observed_at: observed, clock_kind: 'source_observation' })
  const field = { as_of: null, source: 'watchlist_symbol_master', source_label: 'Watch symbol master', stale: null,
    freshness: 'UNKNOWN', as_of_basis: 'not exposed by source', reason: 'Level observation time unavailable.' }
  const position = kind === 'held' ? 'held' : kind === 'never-held' ? 'never_held' : 'formerly_held'
  const r = { symbol, security_guid: `fixture-guid-${symbol}`, company: 'Legacy company name must not replace CIO facts',
    company_facts: { schema: 'CIOCompanyFacts@v1', security_guid: `fixture-guid-${symbol}`, status: 'CURRENT',
      company: fact(`${symbol} Fixture Instruments Inc.`), description: fact('Builds precision instruments for industrial quality testing.'),
      sector: fact('Technology'), industry: fact('Scientific & Technical Instruments'),
      catalyst: { status: 'CURRENT', headline: 'Fixture company publication', published_at: '2026-10-23T12:00:00Z',
        observed_at: observed, source: 'news_articles:fixture', feed: 'Company publication', url: 'https://example.invalid/fixture-publication', factual_verification_status: 'SOURCE_DECLARED' } },
    market_facts: { schema: 'WatchMarketFacts@v1', evaluated_at: clock, price: { value: 10, as_of: observed,
      source: 'data_broker.latest_quote:schwab', source_label: 'Stored quote · schwab', stale: true, freshness: 'STALE', reason: 'Price observation is stale.' },
      support: { ...field, value: 9, compatibility: 'BELOW_OR_AT_PRICE' }, resistance: { ...field, value: 11, compatibility: 'ABOVE_OR_AT_PRICE' } },
    lane: position === 'held' ? 'manage' : position === 'never_held' ? 'forming' : 'reentry', stage: position === 'held' ? 'held_review' : 're_entry',
    why: position === 'held' ? 'Managing an existing position' : position === 'never_held' ? 'Watching the setup develop' : 'Sold; near your re-entry level',
    summary: 'Synthetic fixture. Existing stored facts only; advisory actions only.', conviction: [85, 77, 68, 79, 72, 55, null][i],
    conviction_components: [], conviction_missing: [], conviction_stale: false, conviction_source: 'fixture', conviction_as_of: observed,
    stance: kind === 'missing-price' ? null : position === 'held' ? 'HOLD' : position === 'never_held' ? 'WATCH' : 'RE_ENTER',
    conflicts: [], whats_missing: [], next_trigger: { label: 'Zone $9.50–$10.50', level_ref: 10, inside: true, distance_pct: 0, observed_by: 'fixture' },
    next_action: { kind: 'set_alert', label: 'Set alert', reason: 'Advisory notification only' }, surfaces: [],
    price: 10, price_as_of: observed, levels_ref: { entry_low_ref: 9.5, entry_high_ref: 10.5, support_ref: 9, resistance_ref: 11 },
    mine: true, starred: true, membership: [], position_state: position, held: position === 'held',
    held_accounts: position === 'held' ? ['schwab_rollover_ira', 'schwab_taxable'] : [],
    held_account_labels: position === 'held' ? ['Schwab Rollover IRA', 'Schwab Individual'] : [],
    last_sell_at: position === 'formerly_held' ? '2026-10-22T14:00:00Z' : null,
    last_sell_account: position === 'formerly_held' ? 'schwab_rollover_ira' : null,
    last_sell_account_label: position === 'formerly_held' ? 'Schwab Rollover IRA' : null,
    last_round_trip: null, reentry: null, evidence_at: observed, expires_at: null, stale: false }
  if (kind === 'conflict') {
    r.conflicts = [{ kind: 'stance', summary: 'Desk disagreement retained in record', a: { value: 'RE_ENTER' }, b: { value: 'WAIT' } },
      { kind: 'trade_ai_block', summary: 'Trade AI deterministic check fails', a: { value: 'RE_ENTER' }, b: { value: 'DETERMINISTIC_FAIL' } }]
    r.next_action = { kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'Two existing sources disagree' }
    r.trade_ai_state = 'DETERMINISTIC_FAIL'; r.whats_missing = ['Fundamental factor not scored']
  }
  if (kind === 'held') r.next_action = { kind: 'open_position', label: 'Open position', href: `/v3/trading?tab=open-trades&symbol=${symbol}`, reason: 'Existing position navigation only' }
  if (kind === 'no-catalyst') r.company_facts.catalyst = { status: 'MISSING', headline: null, missing_reason: 'no_current_dated_catalyst' }
  if (kind === 'missing-level') r.market_facts.support = { ...field, value: null, source: null, source_label: 'No reference', reason: 'No stored support reference.' }
  if (kind === 'missing-price') {
    r.market_facts.price = { value: null, as_of: null, source: null, source_label: 'No quote', stale: true, freshness: 'MISSING', reason: 'Stored quote is missing.' }
    r.market_facts.support.compatibility = 'UNKNOWN'; r.market_facts.resistance.compatibility = 'UNKNOWN'
    r.price = null; r.price_as_of = null
  }
  return r
}
const rows = cases.map(makeRow)
const python = `import json,sys; from datetime import datetime; sys.path.insert(0,'scripts')
from lib.data_broker import watch_position_facts as p
d=json.load(sys.stdin); rows=d['rows']; q=d['q']; now=datetime.fromisoformat('${clock.replace('Z', '+00:00')}')
active=p.active_filters(q); kept=[r for r in rows if p.passes(r,active,now=now)]
if q.get('sort') in p.SORTS: kept.sort(key=lambda r:(*p.sort_key(q['sort'],r,r.get('conviction')),r['symbol']))
print(json.dumps({'ok':True,'my_watchlist':{'rows':kept,'count':len(kept),'unfiltered_count':len(rows),'starred':sum(bool(r.get('starred')) for r in kept),'sources':{},'position_filters':p.FILTERS,'position_facets':p.facet_counts(rows,now=now,filters=active),'filters':active}}))`
function server(source, search) {
  return JSON.parse(execFileSync(process.env.WATCH_FIXTURE_PYTHON || 'python3', ['-c', python], {
    cwd: repo, input: JSON.stringify({ rows: source, q: Object.fromEntries(search) }), encoding: 'utf8',
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  }))
}
const bundled = await build({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';
  import {BrowserRouter} from 'react-router-dom';import WatchMyList from './src/pages/WatchMyList';
  import './src/index.css';import {TYPE} from './src/lib/designTokens';createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><main className="cc-terminal-ui"
    style={{padding:20,background:'var(--bg-0)',color:'var(--text-0)',minHeight:'100vh'}}><h1 style={{fontSize:TYPE.lg+2,fontWeight:600}}>Watch › My Watchlist</h1><WatchMyList/></main></BrowserRouter>);`,
  resolveDir: app, sourcefile: 'watch-row-fixture.tsx', loader: 'tsx' }, bundle: true, write: false, outfile: 'fixture.js',
  jsx: 'automatic', platform: 'browser', define: { 'process.env.NODE_ENV': '"production"' } })
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text, css = bundled.outputFiles.find(f => f.path.endsWith('.css')).text
const html = `<html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`
const browser = await chromium.launch({ args: ['--no-sandbox'] })
const receipts = []
async function fixture(width, source) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, serviceWorkers: 'block' }), page = await context.newPage()
  await page.clock.setFixedTime(new Date(clock))
  const traffic = { queries: [], external: [], mutations: [], unexpected: [], errors: [] }
  page.on('pageerror', e => traffic.errors.push(e.message))
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (u.origin !== 'http://watch-redesign-fixture.test') { traffic.external.push(req.url()); return route.abort() }
    if (req.method() !== 'GET') { traffic.mutations.push(req.method() + ' ' + u.pathname); return route.abort() }
    if (u.pathname === '/v3/watch') return route.fulfill({ contentType: 'text/html', body: html })
    if (u.pathname === '/api/v3/data-broker/watch-curation') {
      traffic.queries.push(Object.fromEntries(u.searchParams))
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(server(source, u.searchParams)) })
    }
    if (u.pathname === '/api/v2/watch/alerts/list') return route.fulfill({ contentType: 'application/json', body: '{"alerts":[]}' })
    traffic.unexpected.push(u.pathname); return route.abort()
  })
  await page.goto('http://watch-redesign-fixture.test/v3/watch')
  await expect(page.getByTestId('mine-row')).toHaveCount(source.length)
  return { context, page, traffic }
}
function clean(traffic) { assert.deepEqual({ ...traffic, queries: [] }, { queries: [], external: [], mutations: [], unexpected: [], errors: [] }) }
try {
  for (const width of [1440, 412]) for (let i = 0; i < cases.length; i++) {
    const kind = cases[i], { context, page, traffic } = await fixture(width, [rows[i]])
    const card = page.getByTestId('watch-row')
    await expect(card).toContainText(`${rows[i].symbol} Fixture Instruments Inc.`)
    await expect(card).not.toContainText('Legacy company name')
    if (kind === 'held') { await expect(card).toContainText('Schwab Rollover IRA'); await expect(card).toContainText('Schwab Individual') }
    if (kind === 'formerly-held') await expect(card).toContainText('Schwab Rollover IRA')
    if (kind === 'never-held') await expect(card.getByTestId('watch-card-ownership')).toHaveCount(0)
    if (kind === 'conflict') {
      await expect(card.getByTestId('watch-blocking-reason')).toHaveCount(1)
      await expect(card.getByTestId('watch-blocking-reason')).toContainText('Trade AI deterministic check fails')
      await card.getByTitle(`Open the ${rows[i].symbol} record`, { exact: true }).click()
      await expect(page.getByTestId('watch-detail-conflicts')).toContainText('Desk disagreement retained in record')
      await page.getByRole('button', { name: 'Close record', exact: true }).click()
    }
    await expect(card.locator('.watch-company-label')).toHaveText('CATALYST')
    await expect(card.getByTestId('watch-company-catalyst')).not.toContainText('Source claim')
    if (kind === 'no-catalyst') await expect(card.getByTestId('watch-company-catalyst')).toContainText('None on file')
    if (kind === 'missing-level') { await expect(card.getByTestId('watch-market-support')).toContainText('—'); await expect(card.locator('.watch-card-price-marker')).toHaveCount(0) }
    if (kind === 'missing-price') { await expect(card.getByTestId('watch-market-price').locator('[data-state]')).toHaveText('Missing'); await expect(card).toContainText('n/a'); await expect(card).toContainText('no stance') }
    if (width === 412) {
      const buttons = await card.locator('button:visible').evaluateAll(els => els.map(e => e.getBoundingClientRect().height))
      assert(buttons.every(h => h >= 44), JSON.stringify(buttons))
      await expect(card.locator('.watch-card-phone-price')).toBeVisible()
    } else {
      const grid = await card.evaluate(e => ({ columns: getComputedStyle(e).gridTemplateColumns, gap: getComputedStyle(e).columnGap }))
      assert.match(grid.columns, /^300px .* 380px 150px 150px$/); assert.equal(grid.gap, '20px')
    }
    const more = card.getByRole('button', { name: 'More actions', exact: true })
    await more.click(); await expect(more).toHaveAttribute('aria-expanded', 'true')
    await expect(card.getByRole('button', { name: 'Set alert', exact: true }).last()).toBeVisible()
    if (width === 412) {
      const buttons = await card.locator('button:visible').evaluateAll(els => els.map(e => ({ h: e.getBoundingClientRect().height, w: e.getBoundingClientRect().width })))
      assert(buttons.every(b => b.h >= 44 && b.w >= 44), JSON.stringify(buttons))
    }
    await page.keyboard.press('Escape'); await expect(more).toHaveAttribute('aria-expanded', 'false'); await expect(more).toBeFocused()
    await more.evaluate(e => e.blur())
    const geometry = await card.evaluate(e => ({ client: e.clientWidth, scroll: e.scrollWidth, document: document.documentElement.scrollWidth, viewport: innerWidth }))
    assert(geometry.scroll <= geometry.client + 1 && geometry.document <= geometry.viewport + 1, JSON.stringify(geometry))
    const contrast = await card.evaluate(card => {
      const rgba = value => { const n = value.match(/[\d.]+/g)?.map(Number) || [0, 0, 0]; return [n[0], n[1], n[2], n[3] ?? 1] }
      const blend = (front, back) => front.slice(0, 3).map((v, i) => v * front[3] + back[i] * (1 - front[3]))
      const luminance = values => values.map(v => { const c = v / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4 }).reduce((a, v, i) => a + v * [.2126, .7152, .0722][i], 0)
      const rows = [], walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        const node = walker.currentNode, el = node.parentElement
        if (!node.textContent.trim() || !el || el.closest('[hidden], [aria-hidden="true"], button:disabled') || !el.getBoundingClientRect().height || getComputedStyle(el).display === 'none') continue
        let ancestor = el, stack = []
        while (ancestor) { stack.unshift(rgba(getComputedStyle(ancestor).backgroundColor)); ancestor = ancestor.parentElement }
        const bg = stack.reduce((b, f) => blend(f, b), [255, 255, 255]), fg = blend(rgba(getComputedStyle(el).color), bg)
        const l = [luminance(bg), luminance(fg)].sort((a, b) => b - a)
        rows.push({ text: node.textContent.trim(), ratio: (l[0] + .05) / (l[1] + .05) })
      }
      return rows
    })
    assert(contrast.every(row => row.ratio >= 4.5), JSON.stringify(contrast.filter(row => row.ratio < 4.5)))
    clean(traffic)
    await page.screenshot({ path: path.join(out, `impl-${kind}-${width}.png`), fullPage: true, animations: 'disabled' })
    receipts.push({ kind, width, geometry, contrast, input: rows[i], displayed: await card.innerText(), traffic })
    if (kind === 'held') { await card.getByTestId('watch-step').click(); await expect(page).toHaveURL(/\/v3\/trading\?tab=open-trades&symbol=FATN$/); clean(traffic) }
    await context.close()
  }
  for (const width of [1440, 412]) {
    const { context, page, traffic } = await fixture(width, rows)
    const filter = page.getByTestId('mine-position-filters')
    if (width === 1440) {
      await page.getByTestId('watch-sort-conviction').click(); await expect(page).toHaveURL(/psort=conviction_desc/)
      await page.getByTestId('watch-sort-conviction').click(); await expect(page).toHaveURL(/psort=conviction_asc/)
      await page.getByTestId('watch-sort-conviction').click(); assert(!new URL(page.url()).searchParams.has('psort'))
      await page.getByTestId('watch-sort-setup').click(); await expect(page).toHaveURL(/psort=setup/)
      await page.getByTestId('watch-sort-setup').click(); assert(!new URL(page.url()).searchParams.has('psort'))
    }
    await filter.getByRole('button', { name: /^Position filters/ }).click()
    await filter.locator('[data-filter="conv"][data-opt="70"]').click()
    await expect(page).toHaveURL(/conv=70/); await expect(page.getByTestId('mine-row')).toHaveCount(4)
    await expect(page.getByTestId('watch-my-list')).toContainText('4 of 7')
    await filter.getByRole('combobox').selectOption('conviction_desc')
    await expect(page).toHaveURL(/psort=conviction_desc/)
    await filter.locator('[data-filter="stance"][data-opt="RE-ENTER"]').click()
    await expect(page.getByTestId('mine-row')).toHaveCount(3)
    assert(traffic.queries.some(q => q.conv === '70' && q.stance === 'RE-ENTER' && q.sort === 'conviction_desc'))
    await filter.getByRole('button', { name: 'Clear filters', exact: true }).click()
    await expect(page.getByTestId('mine-row')).toHaveCount(7)
    assert(!['conv', 'stance', 'stage', 'psort'].some(k => new URL(page.url()).searchParams.has(k)))
    clean(traffic); receipts.push({ interaction: true, width, traffic })
    await context.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(out, 'impl-receipts.json'), JSON.stringify({ fixture: true, clock, cases: receipts }, null, 2) + '\n')
console.log(`Watch redesign:14 state screenshots +2 server-backed URL interaction cases passed; ${out}`)
