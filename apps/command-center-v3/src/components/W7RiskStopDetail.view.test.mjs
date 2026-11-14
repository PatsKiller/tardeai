/**
 * R5b #1 (2026-11-14, SEV-3 cross-page): Risk › Exposure's stop-detail sheet read "Planned level · no resting order ·
 * State None · Observed Apr 18, 8:00 PM EDT" with no freshness verdict, while Portfolio read the same position as
 * UNKNOWN ("stop read 210 d old, limit 3 d"). The sheet now draws the SAME rule Portfolio applies — the shared
 * stopReadFreshness() in lib/portfolioV002 over the same read clock and the same limit — and never recomputes either.
 * Synthetic fixtures only (public repo) in the live /api/v2/cio/pages row shape: no protection verdict, a stop-read
 * clock, the stop state, and the projection's own stop_evidence mark.
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
const { W7StopDetail } = await import(compile(join(app, 'src/components/W7RiskPanels.tsx')))

const NOW = Date.parse('2031-03-07T15:00:00Z')      // Friday 10:00 ET — session open, 15 m limit
const CLOSED = Date.parse('2031-03-08T15:00:00Z')   // Saturday — off-hours, 72 h limit
/** The live cio/pages row shape: protection/protection_state null, stop fields + stop_evidence published. */
const row = (o) => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', shares: 40, price: 63.66,
  market_value: 5194.74, price_as_of: '2031-03-07T14:55:00Z', stop_price: 63.66, stop_qty: null, stop_state: 'none',
  stop_source: 'planned', stop_captured_at: '2031-02-25T00:00:00Z', protection: null, protection_state: null, counted: true,
  stop_evidence: { stale: true, age_hours: 255, as_of: '2031-02-25T00:00:00Z' }, ...o })
const render = (selected, nowMs = NOW) => renderToStaticMarkup(React.createElement(MemoryRouter, null,
  React.createElement(W7StopDetail, { selected, nowMs })))
const freshness = (html) => {
  const m = html.match(/data-testid="risk-sheet-freshness"([^>]*)>([^<]*)</)
  assert.ok(m, 'the sheet draws a stop-read freshness line')
  return { attrs: m[1], text: m[2] }
}

const results = []
function check(name, fn) { try { fn(); results.push({ name, passed: true }) } catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) } }

check('R5b #1: a stale planned level reads UNKNOWN with the age and the limit, not "Observed Apr 18" alone', () => {
  const html = render(row({ symbol: 'AMANX' }))
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="stale"/)
  assert.match(f.attrs, /data-served-stale="true"/)
  assert.match(f.attrs, /data-agrees="true"/)
  assert.match(f.text, /UNKNOWN · the stop read is \d+ d old \(session limit 15 m\)/)
  assert.match(f.text, /the served state is last known, not a current read/)
  assert.match(f.text, /R2, the rule Portfolio applies/, 'the line names the shared rule')
  // The served facts are still there: the sheet adds a verdict, it does not replace the broker read.
  assert.match(html, /Planned level/)
  assert.match(html, /Observed/)
})

check('R5b #1: the off-hours limit is 72 h and a fresh read says so without alarm', () => {
  const html = render(row({ stop_captured_at: '2031-03-07T02:00:00Z', stop_evidence: { stale: false, as_of: '2031-03-07T02:00:00Z' } }), CLOSED)
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="fresh"/)
  assert.equal(f.text, 'fresh · read 37 h ago · off-hours limit 3 d')
  assert.match(html, /not a separate Risk calculation/)
})

check('R5b #1: the same read is stale inside the session (15 m) and fresh after the close (72 h)', () => {
  const r = row({ stop_captured_at: '2031-03-07T02:00:00Z', stop_evidence: { stale: null, as_of: '2031-03-07T02:00:00Z' } })
  assert.match(freshness(render(r, NOW)).text, /session limit 15 m/)
  assert.match(freshness(render(r, CLOSED)).attrs, /data-freshness="fresh"/)
})

check('R5b #1: a row with no stop-read clock says the age is not measured (never fresh)', () => {
  const html = render(row({ stop_captured_at: null, stop_evidence: { stale: true } }))
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="unpublished"/)
  assert.match(f.text, /no stop-read time is published/)
  assert.match(f.text, /served stop evidence marks it stale/)
  assert.doesNotMatch(f.text, /^fresh/)
})

check('R5b #1: a read time later than the clock cannot be trusted', () => {
  const html = render(row({ stop_captured_at: '2031-03-07T15:10:00Z', stop_evidence: null }))
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="invalid"/)
  assert.match(f.text, /later than the clock; the read cannot be trusted/)
})

check('R5b #1: an active broker stop with a fresh read stays an ordinary fresh observation', () => {
  const html = render(row({ stop_state: 'active', stop_source: 'broker_resting', stop_price: 90,
    stop_captured_at: '2031-03-07T14:55:00Z', stop_evidence: { stale: false } }))
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="fresh"/)
  assert.match(f.text, /^fresh · read 5 m ago · session limit 15 m$/)
  assert.doesNotMatch(f.text, /UNKNOWN/)
})

check('R5b #1: when the served mark and the shared rule disagree, both are shown and neither is chosen', () => {
  const html = render(row({ stop_captured_at: '2031-03-07T02:00:00Z', stop_evidence: { stale: true } }), CLOSED)
  const f = freshness(html)
  assert.match(f.attrs, /data-freshness="fresh"/)
  assert.match(f.attrs, /data-served-stale="true"/)
  assert.match(f.attrs, /data-agrees="false"/)
  assert.match(f.text, /the served stop evidence marks it stale — the two marks disagree/)
})

console.log(JSON.stringify({ results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }, null, 2))
if (results.some(x => !x.passed)) process.exit(1)
