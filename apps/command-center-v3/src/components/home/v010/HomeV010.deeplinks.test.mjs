// LQ-20261107-2992b: priority deep links, Watch/Details blocks, '+N more gates', blocks_trading tri-state. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const lib = await import(compile(join(app, 'src/lib/homeV010.ts')))
const { default: View } = await import(compile(join(app, 'src/components/home', 'v010', 'HomeV010View.tsx')))
const { buildModel, readOnce, API } = lib

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const fail = (source, state = 'UNKNOWN') => ({ state, data: null, error: 'HTTP 503', at: AT, source })
const dest = await import(compile(join(app, 'src/lib/homeDestinations.ts')))
const { prioritiesView } = await import(compile(join(app, 'src/lib/homePriorities.ts')))
const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const gate = (id, state, extra = {}) => ({ id, label: id, required: true, state, source_id: `src_${id}`, as_of: '2031-03-07T14:50:00Z', age_s: 600, threshold_s: 900, reason: state === 'OK' ? null : 'synthetic', needs_backend: false, ...extra })
const wire = gates => ({ schema: 'HomeStatus@v1', verdict: 'NO', trade_ready: { verdict: 'NO', cause: 'synthetic', computed_at: '2031-03-07T14:59:30Z' }, gates, blockers: [], unknown_inputs: [] })
const model = gates => buildModel({ ...CLEAR, status: ok(API.status, wire(gates)) }, NOW)
const render = (m, priorities) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model: m, nowIso: new Date(NOW).toISOString(), onOpenWhy() {}, onOpenDiag() {}, priorities })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }
const count = (h, re) => (h.match(re) || []).length
const prio = items => prioritiesView({ state: 'OK', data: { state: 'OK', items, count: items.length }, error: null, at: AT, source: 'p' })
const item = (kind, id) => ({ id, kind, title: `t-${id}`, why: 'w', rank: 1 })

await test('each priority kind links to its real page', () => {
  assert.equal(dest.priorityDestination('INCIDENT').to, '/ops/incidents')
  assert.equal(dest.priorityDestination('APPROVALS').to, '/approvals')
  assert.equal(dest.priorityDestination('STOP').to, '/home-classic')
  assert.equal(dest.priorityDestination('MYSTERY'), null)
  assert.equal(dest.priorityDestination(null), null)
})
await test('every destination is a route that exists in App.tsx', () => {
  const app_ = readFileSync(join(app, 'src/App.tsx'), 'utf8')
  const routes = new Set([...app_.matchAll(/<Route path="([^"]+)"/g)].map(m => '/' + m[1]))
  for (const d of dest.DETAILS) assert.ok(routes.has(dest.routeOf(d.to)), d.to)
  for (const k of ['INCIDENT', 'APPROVALS', 'STOP']) assert.ok(routes.has(dest.routeOf(dest.priorityDestination(k).to)), k)
  for (const [k, d] of Object.entries(dest.LINKS)) assert.ok(routes.has(dest.routeOf(d.to)), `${k}: ${d.to}`)
  for (const links of Object.values(dest.ROW_LINKS)) for (const d of links) assert.ok(routes.has(dest.routeOf(d.to)), d.to)
})
await test('priority rows render a link, and an unknown kind says no destination (not a guessed link)', () => {
  const h = render(model([gate('p0', 'OK')]), prio([item('INCIDENT', 'a'), item('APPROVALS', 'b'), item('ZZZ', 'c')]))
  assert.equal(count(h, /data-testid="prio-link"/g), 2)
  assert.match(h, /href="\/ops\/incidents"/); assert.match(h, /href="\/approvals"/)
  assert.equal(count(h, /data-testid="prio-nolink"/g), 1)
  // Item 7: the ranking is the server's; the Do-now queue that draws the same items is one click away.
  assert.match(h, /<a[^>]*data-testid="prio-donow-link"[^>]*>/)
  assert.match((h.match(/<a[^>]*data-testid="prio-donow-link"[^>]*>/) || [''])[0], /href="\/home-classic"/)
})
await test('Watch block is an honest NEEDS BACKEND with the real Watch link; Details lists every destination', () => {
  const h = render(model([gate('p0', 'OK')]))
  const w = h.slice(h.indexOf('id="card-watch"'), h.indexOf('id="card-details"'))
  assert.match(w, /UNKNOWN — Home reads no watch-item source/); assert.doesNotMatch(w, /NEEDS BACKEND|No source yet/); assert.match(w, /href="\/watch"/)
  assert.doesNotMatch(text(w), /\d+ (items?|symbols?)/)
  assert.equal(count(h, /data-testid="details-link"/g), dest.DETAILS.length)
  assert.match(h, /href="\/home-classic"/)
})
const many = k => Array.from({ length: k }, (_, i) => gate(`g${i}`, 'OK'))
await test('+N more gates: 8 OK gates -> 5 shown and "+3 more gates"; toggle target present', () => {
  const h = render(model(many(8)))
  assert.equal(count(h, /data-testid="gate-row"/g), 5)
  assert.match(text(h), /\+3 more gates/)
})
await test('+N more gates never hides a non-OK gate', () => {
  const g = many(8); g[6] = gate('g6', 'STALE'); g[7] = gate('g7', 'UNKNOWN')
  const h = render(model(g))
  assert.equal(count(h, /data-testid="gate-row"/g), 7)
  assert.match(h, /id="gate-g6"/); assert.match(h, /id="gate-g7"/)
  assert.match(text(h), /\+1 more gates/)
})
await test('5 or fewer gates -> no overflow control; all-bad list -> no hiding', () => {
  assert.doesNotMatch(render(model(many(5))), /gates-more/)
  const bad = Array.from({ length: 8 }, (_, i) => gate(`b${i}`, 'WARN'))
  const h = render(model(bad)); assert.equal(count(h, /data-testid="gate-row"/g), 8); assert.doesNotMatch(h, /gates-more/)
})
await test('blocks_trading null/absent renders "classification pending (UNKNOWN)", never non-blocking', () => {
  const h = render(model([gate('a', 'WARN'), gate('b', 'WARN', { blocks_trading: null }), gate('c', 'WARN', { blocks_trading: false }), gate('d', 'WARN', { blocks_trading: true })]))
  assert.equal(count(h, /classification pending \(UNKNOWN\)/g), 2)
  assert.equal(count(h, /does not block trading/g), 1); assert.equal(count(h, /blocks trading/g), 1)
  assert.equal(dest.blocksText(undefined), 'classification pending (UNKNOWN)')
})
// ── CAMPAIGN-8H Home item 7: the links the operator asked to be one click away ───────────────────────────────
const inc = (over = {}) => ({
  incident_id: 1, alert_type: 'position_unprotected', category: 'Unprotected Position', priority: 'P1',
  symbol: 'AAA', account_label: 'acct_alpha', first_seen_at: AT, last_seen_at: AT, failed_checks: 1,
  cause: 'synthetic', stale_condition: false, ttl_h: 24, ...over,
})
const modelWith = (items, gates = [gate('g', 'OK')]) => buildModel({
  ...CLEAR,
  incidents: ok(API.incidents, { state: 'OK', items, counts: { P0: 0, P1: items.length }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  status: ok(API.status, wire(gates)),
}, NOW)
await test('item 7: the status card carries Open Health, the gates card names its source, and each row links its page', () => {
  const h = render(model([gate('g', 'OK')]))
  assert.match(h, /data-testid="open-health"[^>]*href="\/health"|href="\/health"[^>]*data-testid="open-health"/)
  assert.match(h, /data-testid="gates-health-link"[^>]*href="\/health"|href="\/health"[^>]*data-testid="gates-health-link"/)
  const portfolioRow = h.slice(h.indexOf('id="row-portfolio"'), h.indexOf('id="row-orders"'))
  assert.match(portfolioRow, /href="\/portfolio"/); assert.match(portfolioRow, /href="\/portfolio\?tab=Returns"/)
  const stopRow = h.slice(h.indexOf('id="row-orders"'), h.indexOf('id="row-schedulers"'))
  assert.match(stopRow, /href="\/portfolio\?tab=Stop Management"/)
})
await test('item 7: the Watch block links News and Opportunities, not just Watch', () => {
  const h = render(model([gate('g', 'OK')]))
  const w = h.slice(h.indexOf('id="card-watch"'), h.indexOf('id="card-details"'))
  assert.match(w, /href="\/research-intelligence\?tab=news"/)
  assert.match(w, /href="\/trading\?tab=Trade AI"/)
})
await test('item 7 C1: each P1 account expander carries the value the Portfolio hub MATCHES, not the label it prints', async () => {
  const pd = await import(compile(join(app, 'src/lib/portfolioDeepLink.ts')))
  const h = render(modelWith([inc({ symbol: 'AAA', account_label: 'Schwab Rollover IRA' }),
    inc({ incident_id: 2, symbol: 'BBB', account_label: 'Schwab Roth IRA' }),
    inc({ incident_id: 3, symbol: 'CCC', account_label: 'Schwab Individual' }),
    inc({ incident_id: 4, symbol: 'DDD', account_label: null }),
    inc({ incident_id: 5, symbol: 'EEE', account_label: 'acct_alpha' })]))
  const links = [...h.matchAll(/<a[^>]*data-testid="account-link"[^>]*href="([^"]+)"/g)].map(m => m[1])
  const accts = links.map(to => new URLSearchParams(to.split('?')[1]).get('acct'))
  // A configured account expands; the synthetic "account unknown" bucket and an unconfigured label draw text only —
  // a filter the hub cannot match prints "No holdings match this filter", which would be a false fact about the book.
  assert.equal(links.length, 3, links.join(' | '))
  assert.deepEqual([...accts].sort(), ['schwab_rollover_ira', 'schwab_roth', 'schwab_taxable'])
  assert.ok(!accts.includes('Schwab Roth IRA'), 'the display name is not the hub filter vocabulary')
  // Landing: the hub compares `?acct=` by exact equality against the holdings row's own `account` (PortfolioHub.tsx:333).
  // The fixture is the STORE's vocabulary, taken from the writer + its Python pin, never from this emitter:
  // scripts/schwab_position_sync.py:1169 `_HOLDINGS_ACCT = {"schwab_roth_ira": "schwab_roth"}` writes every other
  // key unchanged, and tests/test_holdings_db_first_20261106.py:331-345 pins the set
  // {schwab_roth, schwab_rollover_ira, schwab_taxable} (+ alpaca_taxable_live). Built from the code's own output
  // instead, the fixture would only prove the code matches itself (review -5, r2 M2).
  const holdings = [{ account: 'schwab_rollover_ira', symbol: 'AAA' }, { account: 'schwab_roth', symbol: 'BBB' },
    { account: 'schwab_taxable', symbol: 'CCC' }, { symbol: 'ZZZ' }]
  for (const a of accts) {
    assert.equal(holdings.filter(row => (row.account ?? 'unknown') === a).length, 1, `${a} must match exactly one holdings row`)
  }
  // Still a parseable hub deep link, and the buckets are never folded together.
  for (const to of links) {
    const q = new URLSearchParams(to.split('?')[1])
    assert.equal(pd.parsePortfolioDeepLink(q).acct, q.get('acct'), to)
  }
  assert.equal(text(h).includes('P1 by account: Schwab Rollover IRA 1 · Schwab Roth IRA 1 · Schwab Individual 1 · account unknown 1 · acct_alpha 1'), true)
})
await test('item 7 C1: the pure seam is label -> hub key; anything that names no configured account is null', () => {
  assert.equal(dest.destinationForAccount('Schwab Roth IRA').to, '/portfolio?acct=schwab_roth')
  assert.equal(dest.destinationForAccount(' Schwab Rollover IRA ').to, '/portfolio?acct=schwab_rollover_ira')
  assert.equal(dest.destinationForAccount('Schwab Individual').to, '/portfolio?acct=schwab_taxable')
  assert.equal(dest.destinationForAccount('schwab roth ira').to, '/portfolio?acct=schwab_roth', 'case/space tolerant')
  assert.equal(dest.destinationForAccount('Fidelity Rollover IRA').to, '/portfolio?acct=fidelity_rollover_ira')
  assert.equal(dest.destinationForAccount('account unknown'), null)
  assert.equal(dest.destinationForAccount('acct_alpha'), null)
  assert.equal(dest.destinationForAccount('Unlabelled account'), null)
  assert.equal(dest.destinationForAccount(''), null)
  assert.equal(dest.destinationForAccount(null), null)
  assert.equal(dest.accountLink('Schwab Roth IRA').to, '/portfolio?acct=schwab_roth', 'the view name keeps the contract')
})
await test('item 7: the Portfolio targets are the ones the hub parses (no dead tab, no unparsed param)', async () => {
  const pd = await import(compile(join(app, 'src/lib/portfolioDeepLink.ts')))
  assert.equal(pd.resolvePortfolioTab(new URLSearchParams(dest.LINKS.returns.to.split('?')[1]).get('tab')), 'Returns')
  assert.equal(pd.resolvePortfolioTab(new URLSearchParams(dest.LINKS.stopRead.to.split('?')[1]).get('tab')), 'Stop Management')
  assert.equal(dest.accountLink(''), null, 'an account with no label is not a link')
})
await test('item 7: Back to Home is an anchor to an id the page actually has', () => {
  const h = render(model([gate('g', 'OK')]))
  const href = (h.match(/<a[^>]*data-testid="back-to-top"[^>]*>/) || [''])[0].match(/href="([^"]+)"/)?.[1]
  assert.ok(href, 'the footer carries a Back to Home link')
  assert.ok(h.includes(`id="${href.slice(1)}"`), `${href} must name an id in the page`)
})
console.log(`HomeV010.deeplinks: ${n} passed`)
