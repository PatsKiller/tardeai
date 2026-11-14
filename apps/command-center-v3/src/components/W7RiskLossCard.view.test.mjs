/**
 * OBS-R1 + OBS-R2 (operator, live Chrome 2026-11-14): Risk › Exposure's loss card said
 * "Loss if every resting stop fills $14,793 · 0 active, 8 pending activation · active stops only Not available"
 * — a hypothetical resting-order scenario and the active-stop figure spliced into one line, the scenario summed
 * over the HELD quantity instead of the quantity the broker order COVERS, and "pending activation" named with no
 * broker order state behind it. And "Positions · Nov 14, 11:00 ET · Stops · last broker read Nov 13, 8:55 PM ET"
 * gave two clocks with no statement of whether they describe the same book.
 *
 * This test pins the page half: two separate figures, the covered-quantity basis stated, the broker order state
 * named, and a reconciliation status on the clocks. Synthetic fixtures only (public repo) in the live
 * /api/v2/cio/pages shape: no real accounts, symbols or values.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8').replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
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

globalThis.fetch = () => { throw new Error('Network forbidden in synthetic Risk rendering tests') }
const { W7RiskExposure } = await import(compile(join(app, 'src/components/W7RiskPanels.tsx')))

const PENDING = '2031-03-07T14:55:00Z'   // the broker order read (older than the positions snapshot)
const POS_AT = '2031-03-07T16:00:00Z'     // the positions snapshot, 1 h 5 m later
const row = (o) => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', shares: 100.7963,
  price: 425.76, market_value: 42915.03, stop_price: 406.94, stop_source: 'broker_resting', stop_state: 'pending_activation',
  stop_qty: 100, stop_captured_at: PENDING, counted: true, stop_category: 'pending_activation', ...o })
/** The live shape: 0 active, 8 pending activation (11 counted positions), no active-stop figure. */
const payload = (o = {}) => ({
  positions: {
    as_of: POS_AT, position_count: 11,
    rows: [row({}), row({ symbol: 'PFE', account_id: 'acct-1', shares: 1000, price: 28.89, stop_price: 26.68, market_value: 28890 })],
    stop_breakdown: { active: { count: 0 }, pending_activation: { count: 8 }, filled: { count: 1 }, unknown: { count: 2 },
      planned: { count: 0 }, none: { count: 0 } },
    loss_at_stop_usd: null,
    loss_at_resting_stops_usd: 14777.52,
    resting_heat_pct: 12.3,
    unprotected_counted_value_usd: 5535,
    resting_loss_coverage: {
      basis: 'covered quantity of each resting broker order (min(held, order qty))',
      shortfalls: [{ symbol: 'V', account_id: 'acct-1', held: 100.7963, covered: 100, shortfall: 0.7963 }],
      qty_not_published: [],
    },
    ...(o.positions || {}),
  },
  stops: {
    as_of: PENDING, last_broker_read_label: 'Mar 7, 9:55 AM ET', position_count: 11,
    unprotected_count: 3,
    pending_broker_states: [{ status: 'AWAITING_STOP_CONDITION', count: 8 }],
    ...(o.stops || {}),
  },
})
const render = (data) => renderToStaticMarkup(React.createElement(MemoryRouter, null,
  React.createElement(W7RiskExposure, { data, onDrill: () => {} })))
const testid = (html, id) => {
  const m = html.match(new RegExp(`data-testid="${id}"([^>]*)>([\\s\\S]*?)<\\/`))
  return m ? { attrs: m[1], text: m[2].replace(/<[^>]+>/g, '') } : null
}
const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
let failed = 0
const check = (name, fn) => { try { fn() } catch (e) { failed++; console.error(`FAIL ${name}: ${e.message}`) } }

const html = render(payload())

check('the hypothetical scenario and the active figure are two separate figures', () => {
  const loss = testid(html, 'risk-kpi-loss')
  assert.ok(loss, 'the resting-stop scenario keeps its own line')
  assert.match(html, /Loss if every resting stop fills/)
  assert.doesNotMatch(html, /active stops only/, 'the spliced "active stops only" sentence is gone')
  const active = testid(html, 'risk-kpi-active-stops')
  assert.ok(active, 'the active-stop figure has its own card')
  assert.match(html, /Loss at active stops/)
})

check('the scenario is labelled hypothetical and keeps the covered-quantity value', () => {
  const loss = testid(html, 'risk-kpi-loss')
  assert.match(loss.text, /hypothetical/)
  assert.match(loss.text, /all 8 resting stops fill at their stop prices/)
  assert.match(html, /\$14,778/, 'the scenario is the covered-basis sum ($14,777.52 → $14,778)')
})

check('the scenario states the covered quantity against the held quantity', () => {
  const loss = testid(html, 'risk-kpi-loss')
  assert.match(loss.text, /covered quantity basis/)
  assert.match(loss.text, /V 100 of 100\.7963 held covered/)
})

check('the active figure says Not available is not $0, and explains pending activation from the broker state', () => {
  const active = testid(html, 'risk-kpi-active-stops')
  assert.match(active.text, /0 armed stops/)
  assert.match(active.text, /Not available is not \$0/)
  assert.match(active.text, /8 resting stops are pending activation/)
  assert.match(active.text, /broker state AWAITING_STOP_CONDITION/)
  assert.match(active.text, /live at the broker and not yet active/)
  assert.match(active.text, /scenario above, not to an active-stop figure/)
})

check('the counts are untouched by the new figures', () => {
  const bd = testid(html, 'risk-stop-breakdown')
  assert.match(bd.text, /8 broker resting · pending activation/)
  assert.match(bd.text, /1 broker stop filled · awaiting holdings sync/)
  assert.match(bd.text, /2 broker stop · state not recorded/)
  assert.match(bd.text, /of 11 counted positions/)
})

check('the two clocks carry an unreconciled status naming the stop read, with the reason', () => {
  const rec = html.match(/data-testid="risk-stops-reconciliation"([^>]*)>([\s\S]*?)<\/span>/)
  assert.ok(rec, 'the clocks line draws a reconciliation status')
  assert.match(rec[1], /data-reconciliation="unreconciled"/)
  const body = rec[2].replace(/<[^>]+>/g, '')
  assert.match(body, /Unreconciled since Mar 7, 9:55 AM ET/)
  assert.match(body, /1\.1 h older than the positions snapshot/)
  assert.match(body, /opened, closed or resized after that read/)
})

check('clocks read at the same time are reconciled', () => {
  const same = render(payload({ stops: { as_of: POS_AT } }))
  assert.match(same, /data-reconciliation="reconciled"/)
  assert.match(text(same), /Reconciled — the broker order read is at or after the positions snapshot/)
})

check('a missing stop clock is reconciliation unknown, never reconciled', () => {
  const none = render(payload({ stops: { as_of: null, last_broker_read_label: null } }))
  assert.match(none, /data-reconciliation="unknown"/)
  assert.match(text(none), /no broker stop read is published/)
})

check('no resting scenario is published as Not available, not a fabricated $0', () => {
  const none = render(payload({ positions: { loss_at_resting_stops_usd: null, resting_heat_pct: null, resting_loss_coverage: null } }))
  assert.match(text(none), /Loss if every resting stop fills Not available/)
  assert.doesNotMatch(text(none), /Loss if every resting stop fills \$0/)
})

if (failed) { console.error(`W7RiskLossCard.view.test.mjs: ${failed} failed`); process.exit(1) }
console.log('W7RiskLossCard.view.test.mjs: ok')
