/**
 * PR-015: the Risk › Exposure KPI "Stops filled / crossed" is an execution observation, not a bare count.
 * Two different measured queues (broker fills awaiting holdings sync, quote crossings awaiting a fill) are named,
 * each with the through-time of the broker read that produced them; with no execution read published the zero is
 * UNKNOWN, never proof that nothing filled. Synthetic fixtures only (public repo) — no broker or live state is read.
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

const SSR_LAYOUT_WARNING = 'Warning: useLayoutEffect does nothing on the server, because its effect cannot ' +
  "be encoded into the server renderer's output format. This will lead " +
  'to a mismatch between the initial, non-hydrated UI and the intended ' +
  'UI. To avoid this, useLayoutEffect should only be used in ' +
  'components that render exclusively on the client. ' +
  'See https://reactjs.org/link/uselayouteffect-ssr for common fixes.'
const __origConsoleError = console.error
console.error = (...args) => {
  if (args[0] === SSR_LAYOUT_WARNING || args[0] === SSR_LAYOUT_WARNING + '%s') return
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

const { MemoryRouter } = require('react-router-dom')
globalThis.fetch = () => { throw new Error('Network forbidden in synthetic Risk rendering tests') }
const { W7RiskExposure } = await import(compile(join(app, 'src/components/W7RiskPanels.tsx')))

const AT = '2031-03-07T14:59:00Z'
const p = (o) => ({ account_id: 'acct-1', account_label: 'Broker A ··01', shares: 100, price: 100, market_value: 10000,
  stop_price: 90, stop_qty: 100, stop_state: 'active', stop_source: 'broker_resting', stop_captured_at: AT, counted: true, ...o })
const data = (stops, rows = [p({ symbol: 'AAA' })]) => ({
  positions: { rows, as_of: AT, loss_at_stop_usd: 1000, portfolio_heat_pct: 1.2 },
  stops: { as_of: AT, position_count: rows.length, ...stops },
})
const render = (d) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(W7RiskExposure, { data: d, onDrill: () => {} })))
const kpi = (html) => {
  const m = html.match(/data-testid="risk-kpi-awaiting">([^<]*)</)
  assert.ok(m, 'the Stops filled / crossed KPI is drawn')
  return m[1]
}

const results = []
function check(name, fn) { try { fn(); results.push({ name, passed: true }) } catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) } }

check('PR-015: no published execution read makes the zero UNKNOWN, never "0 filled"', () => {
  const h = render(data({}))
  assert.match(h, /Stops filled \/ crossed/, 'the KPI names both queues')
  assert.equal(kpi(h), 'UNKNOWN')
  assert.match(h, /no execution read is published, so a zero here is UNKNOWN, not proof that nothing filled/)
})

check('PR-015: a watermark with empty queues reads 0 and names the through-time', () => {
  const h = render(data({ last_broker_read_label: 'Fri 10:04 AM ET' }))
  assert.equal(kpi(h), '0')
  assert.match(h, /No fill recorded and no stop crossed through the last broker read Fri 10:04 AM ET/)
  assert.match(h, /A quote crossing without a broker fill is not a fill/)
})

check('PR-015: a fill and a crossing are counted together and named with the through-time', () => {
  const fills = [p({ symbol: 'FILLX', stop_state: 'filled' })]
  const crossed = [p({ symbol: 'CROSSX' })]
  const h = render(data({ last_broker_read_label: 'Fri 10:04 AM ET', filled_awaiting_sync: fills, awaiting_fill: crossed }, [...fills, ...crossed]))
  assert.equal(kpi(h), '2')
  assert.match(h, /1 recorded fill awaiting holdings sync · 1 quote crossing \(FILLX, CROSSX\)/)
  assert.match(h, /through the last broker read Fri 10:04 AM ET/)
  assert.match(h, /A crossing is not a fill, and a fill is not yet a holdings change/)
})

check('PR-015: an unreadable stops block is UNKNOWN, not a clean book', () => {
  const h = render({ positions: { rows: [p({ symbol: 'AAA' })], as_of: AT }, stops: null })
  assert.equal(kpi(h), 'UNKNOWN')
})

// PR-012: a price is an observation with its own clock. The book's `positions.as_of` is not each row's quote time.
const ago = (ms) => new Date(Date.now() - ms).toISOString()

check('PR-012: with no per-row quote clock the panel says so instead of letting each row inherit the book clock', () => {
  const h = render(data({ last_broker_read_label: 'Fri 10:04 AM ET' }))
  assert.match(h, /data-testid="risk-quote-absent"/, 'the absence is named above the table')
  assert.match(h, /the positions clock is the book’s, not each row’s/)
  assert.doesNotMatch(h, /data-testid="risk-quote-state"/, 'no row prints an age it does not have')
  assert.doesNotMatch(h, /risk-quote-qualified/, 'nothing is qualified as stale without a clock to qualify it')
})

check('PR-012: an aged quote marks the row stale and qualifies the figures derived from it', () => {
  const h = render(data({ last_broker_read_label: 'Fri 10:04 AM ET' }, [p({ symbol: 'AGED', price_as_of: ago(3 * 60 * 60_000) })]))
  assert.match(h, /data-testid="risk-quote-state" data-quote-state="stale"[^>]*>stale 3h ago</)
  assert.match(h, /data-testid="risk-quote-qualified">Distance to stop and loss at stop rest on a quote that is not current: AGED · quote 3h ago · stale/)
  assert.match(h, /The figures are as observed, not refreshed/)
  assert.doesNotMatch(h, /quote time not published/, 'a published clock is not reported as missing')
})

check('PR-012: a fresh quote is not marked, and a quote from the future is refused rather than aged', () => {
  const fresh = render(data({ last_broker_read_label: 'Fri 10:04 AM ET' }, [p({ symbol: 'NEW', price_as_of: ago(60_000) })]))
  assert.doesNotMatch(fresh, /data-testid="risk-quote-state"/, 'a current quote needs no chip')
  assert.doesNotMatch(fresh, /risk-quote-qualified/)
  const future = render(data({ last_broker_read_label: 'Fri 10:04 AM ET' }, [p({ symbol: 'FUTR', price_as_of: new Date(Date.now() + 3600_000).toISOString() })]))
  assert.match(future, /data-quote-state="future"[^>]*>needs review</)
  assert.match(future, /FUTR · quote time needs review/)
})

// R5c (b6, operator 11:06 ET): Risk dates its book from the SAME accessor Portfolio calls, over the cio/pages
// shape (`positions.as_of`). The literal below is asserted verbatim over the holdings shape in
// PortfolioV002.view.test.mjs block 22 — two payload shapes, two components, one sentence.
check('R5c: the book is dated from the shared snapshot accessor, not a Risk-local clock', () => {
  const h = render(data({}))
  assert.match(h, /data-testid="snapshot-line">snapshot id not published · positions read Fri 9:59 AM ET · all accounts \(1\)</)
  // The account scope names what the read drew: Risk has no filter, so two accounts is the whole book.
  const two = render(data({}, [p({ symbol: 'AAA', account_id: 'acct-1' }), p({ symbol: 'BBB', account_id: 'acct-2' })]))
  assert.match(two, /all accounts \(2\)/)
  // No published position clock is named, never replaced with the stops clock or "now".
  const noClock = render({ positions: { rows: [p({ symbol: 'AAA' })] }, stops: { as_of: AT } })
  assert.match(noClock, /positions read clock not published/)
})

console.log(JSON.stringify({ results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }, null, 2))
if (results.some(x => !x.passed)) process.exit(1)
