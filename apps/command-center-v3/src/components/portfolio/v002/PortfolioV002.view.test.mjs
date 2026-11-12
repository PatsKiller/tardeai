// Portfolio v002 (design/pages/portfolio/v002, operator-approved 2026-11-11) — what the page draws.
// Pins: UNKNOWN rows never read NO STOP; a failed/timed-out read shows TIMED OUT / UNKNOWN and "P0 ?", never "0 P0";
// gates are NEEDS BACKEND, never "0 open"; a fully protected book collapses Action·Protection to CLEAR.
// Synthetic fixtures only (public repo). Same harness as the Home v010 view test.
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

const lib = await import(compile(join(app, 'src/lib/portfolioV002.ts')))
const { default: View } = await import(compile(join(app, 'src/components/portfolio/v002/PortfolioV002View.tsx')))
const { positionsFrom, protectionModel, p0Items, statusRows, API } = lib

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const fail = (source, state = 'UNKNOWN') => ({ state, data: null, error: 'HTTP 503', at: AT, source })
const row = o => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', broker: 'broker_a', shares: 10, market_value: 1000,
  price: 100, price_as_of: AT, protection_state: 'PROTECTED', protection: { state: 'PROTECTED', source: 'stop store', as_of: AT, counted: true },
  stop_price: 90, ...o })
const wire = rows => ({ holdings: rows, total_value: 9999, today_change: 5, positions_as_of: AT, valuation_as_of: AT, quote_as_of: AT,
  position_counts: { agree: true } })
const noop = () => {}

function render(holdings, incidents = ok(API.incidents, { counts: { P0: 0, P1: 0 }, served_at: AT })) {
  const positions = holdings.state === 'OK' ? positionsFrom(holdings.data) : []
  const prot = protectionModel(holdings, positions)
  const props = { holdings, positions, prot, p0: p0Items(holdings, prot), status: statusRows(holdings, incidents, positions, NOW),
    nowIso: new Date(NOW).toISOString(), filter: 'all', account: 'all', showAll: false, showAllAction: false,
    onFilter: noop, onAccount: noop, onShowAll: noop, onShowAllAction: noop, onOpenWhy: noop, onOpenDiag: noop, onOpenAudit: noop, onOpenPosition: noop }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(View, props)))
}
const chipP0 = html => (html.match(/data-testid="chip-p0">([^<]*)</) || [])[1]
const section = (html, id) => { const i = html.indexOf(`data-testid="${id}"`); assert.ok(i >= 0, `missing ${id}`); return html.slice(i, html.indexOf('</section>', i)) }

// 1. UNKNOWN rows render UNKNOWN with their cause; only a GAP row reads NO STOP.
const gapHtml = render(ok(API.holdings, wire([
  row({ symbol: 'UNK', market_value: 5000, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null }),
  row({ symbol: 'GAPX', market_value: 2000, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null }),
  row({ symbol: 'SAFE', market_value: 3000 }),
])))
const protect = section(gapHtml, 'card-protect')
const rowsHtml = protect.split('data-testid="prot-row"').slice(1)
const unkRow = rowsHtml.find(r => r.includes('UNK<') || r.includes('>UNK'))
const gapRow = rowsHtml.find(r => r.includes('GAPX'))
assert.ok(unkRow && gapRow, 'both non-protected rows listed')
assert.doesNotMatch(unkRow, /NO STOP/); assert.match(unkRow, /UNKNOWN/); assert.match(unkRow, /No Stop Read/)
assert.match(gapRow, /NO STOP/)
assert.equal(chipP0(gapHtml), '1 P0')
assert.match(section(gapHtml, 'card-gates'), /NEEDS BACKEND/); assert.doesNotMatch(section(gapHtml, 'card-gates'), /\b0 open\b/)
assert.match(gapHtml, /Retired/)

// 2. A timed-out holdings read: TIMED OUT, P0 unknown, no value, no CLEAR.
const toHtml = render(fail(API.holdings, 'TIMED OUT'))
assert.match(toHtml, /TIMED OUT/); assert.equal(chipP0(toHtml), 'P0 ?')
assert.match(toHtml, /value UNKNOWN/); assert.doesNotMatch(toHtml, />CLEAR</)

// 3. A failed (non-timeout) read is UNKNOWN, never CLEAR.
const failHtml = render(fail(API.holdings))
assert.match(section(failHtml, 'card-protect'), /UNKNOWN/); assert.doesNotMatch(failHtml, />CLEAR</)

// 4. Every counted row protected: Action·Protection collapses to CLEAR, 0 P0.
const okHtml = render(ok(API.holdings, wire([row({ symbol: 'ONE' }), row({ symbol: 'TWO', stop_state: 'pending_activation' })])))
assert.match(okHtml, />CLEAR</); assert.equal(chipP0(okHtml), '0 P0'); assert.doesNotMatch(okHtml, /NO STOP/)

// F5: the CLEAR line names the brokers it covered, not "N of N brokers".
assert.doesNotMatch(okHtml, /(\d+) of \1 brokers/); assert.match(okHtml, /1 broker with counted positions/)

// 5. LQ-2460 F1 (REVIEW-2448): an unpriced GAP (counted:false, no value) is a GAP row and a P0, never CLEAR.
const unpricedHtml = render(ok(API.holdings, wire([row({ symbol: 'SAFE' }),
  row({ symbol: 'NOPX', market_value: null, price: null, protection_state: 'GAP', protection: { state: 'GAP', counted: false }, stop_price: null })])))
assert.doesNotMatch(unpricedHtml, />CLEAR</); assert.equal(chipP0(unpricedHtml), '1 P0')
assert.match(section(unpricedHtml, 'card-protect').split('data-testid="prot-row"').find(r => r.includes('NOPX')) || '', /NO STOP/)

// 6. LQ-2460 F2: a cash-only book (zero counted positions, count not confirmed) is UNKNOWN, never CLEAR.
const cashHtml = render(ok(API.holdings, wire([row({ symbol: 'CASH', is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })])))
assert.doesNotMatch(cashHtml, />CLEAR</); assert.match(cashHtml, /Protection: UNKNOWN/)
assert.match(section(cashHtml, 'card-protect'), /Protection UNKNOWN: No counted position, and the position count does not confirm zero/)

console.log('PortfolioV002.view.test.mjs: ok')
