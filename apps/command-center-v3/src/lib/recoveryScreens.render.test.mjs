// node --experimental-strip-types src/lib/recoveryScreens.render.test.mjs
// Recovery & re-entry (piece D, mockup approved 2026-11-06): RENDERS the real Home section and Risk → Recovery list
// with synthetic projections and asserts the operator-visible contract — the quote carries its observation time, the
// four actions render disabled "not wired yet", unavailable never reads as zero, and a changed case asks for a review.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {} }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
      let target = resolve(dirname(path), spec)
      const isFile = (p) => existsSync(p) && statSync(p).isFile()
      if (!isFile(target)) target = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx'].map(s => target + s).find(isFile)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      return `from ${JSON.stringify(compile(target))}`
    })
  }).join('\n')
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { RecoveryHomeSection, RecoveryListView } = await import(compile(join(app, 'src/components/recovery/RecoveryViews.tsx')))
const { recoveryProjection, reviewGate } = await import(compile(join(app, 'src/lib/recoveryCases.ts')))

const CASE = {
  case_key: 'DEMO::synthetic_ira::c1', symbol: 'DEMO', account: 'synthetic_ira', state: 'RECOVERING', state_since: '2026-11-02T21:00:00+00:00',
  materiality_tier: 'T1', realized_pnl: -1200, case_version: 'v1', updated_at: '2026-11-06T14:00:00+00:00', as_of: '2026-11-06T14:00:00+00:00',
  source: 'synthetic', exits: [{ date: '2026-10-30', price: 50 }], pending_operator_decision: true, plan: null, gaps: [], operator_decision: 'none',
  eligibility: [{ account: 'synthetic_ira', eligible: true, eligible_from: null, reason: 'Waiting for the recorded account-policy decision.', answered: false }],
  quote: { price: 52.5, observed_at: '2026-11-06T14:55:00+00:00', source: 'synthetic' },
}
const OTHER = { ...CASE, case_key: 'ALT::synthetic_taxable::c2', symbol: 'ALT', materiality_tier: 'T3', state: 'WATCHING' }
const body = (cases) => ({ items: [], recovery_cases: { state: 'ok', count: cases.length, generated_at: '2026-11-06T15:00:00+00:00', cases, actions: { wired: false, endpoint: null, reason: 'No server endpoint validates recovery-case actions yet.' } } })
const wrap = (el) => renderToStaticMarkup(React.createElement(MemoryRouter, null, el))
const fresh = (c) => reviewGate(undefined, c)

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const actions = ['create_reentry_plan', 'watch', 'close_case', 'snooze']

// Home, answered read with an open T1 case.
const p = recoveryProjection(body([CASE, OTHER]))
const home = wrap(React.createElement(RecoveryHomeSection, { projection: p, lastGood: null, sourceUnavailable: false, gate: fresh, onReview() {} }))
check(home.includes('data-testid="home-recovery-card"'), 'Home does not render the high-impact case')
check(home.includes('DEMO') && !home.includes('ALT'), 'Home must show only the T1 case')
check(/Quote observed Nov 6, 9:55 AM EST · synthetic/.test(home), 'the quote is not labelled with its observation time')
check(home.includes('$52.50') && home.includes('$50.00'), 'quote and confirmed exit not rendered')
for (const a of actions) {
  const m = home.match(new RegExp(`<button[^>]*data-action="${a}"[^>]*>`))
  check(m && /disabled=""/.test(m[0]), `${a} must render disabled`)
}
check((home.match(/not wired yet/g) || []).length >= 4, 'each action must say "not wired yet"')
check(home.includes('Eligibility pending'), 'pending eligibility is not shown')
check(!/\$0\b|>0</.test(home.replace(/\$0\.\d/g, '')), 'no zero should appear for a value that was not published')

// Home, unavailable now but with the last answered case: keeps context, says unavailable, quote dash.
const down = recoveryProjection({ items: [], recovery_cases: { state: 'unavailable', reason: 'recovery case store not reachable', count: null, cases: [], actions: { wired: false } } })
const homeDown = wrap(React.createElement(RecoveryHomeSection, { projection: down, lastGood: p, sourceUnavailable: true, gate: fresh, onReview() {} }))
check(homeDown.includes('data-testid="recovery-unavailable"') && homeDown.includes('recovery case store not reachable'), 'unavailable case context not rendered')
check(homeDown.includes('Quote source unavailable'), 'an unavailable source must not show the old quote as current')
// Home, unavailable with nothing remembered: an explicit unavailable line, never zero.
const homeNone = wrap(React.createElement(RecoveryHomeSection, { projection: down, lastGood: null, sourceUnavailable: true, gate: fresh, onReview() {} }))
check(homeNone.includes('home-recovery-unavailable') && homeNone.includes('unavailable, not zero'), 'Home must say unavailable, not zero')
// Home, answered with no T1 case: nothing.
check(wrap(React.createElement(RecoveryHomeSection, { projection: recoveryProjection(body([OTHER])), lastGood: null, sourceUnavailable: false, gate: fresh, onReview() {} })) === '', 'no T1 case → no Home card')

// Changed case: banner + review button.
const changed = wrap(React.createElement(RecoveryHomeSection, { projection: p, lastGood: null, sourceUnavailable: false, gate: () => 'changed', onReview() {} }))
check(changed.includes('This case changed') && changed.includes('recovery-review-latest') && changed.includes('Review updated case'), 'a changed case must ask for a fresh review')

// Risk → Recovery list.
const list = wrap(React.createElement(RecoveryListView, { projection: p, sourceUnavailable: false, selectedKey: CASE.case_key, onSelect() {}, gate: fresh, onReview() {}, legacyCount: 0 }))
check((list.match(/data-testid="recovery-row"/g) || []).length === 2, 'both cases listed')
check(list.indexOf('DEMO') < list.indexOf('ALT'), 'T1 sorts first')
check(list.includes('data-testid="recovery-detail"') && list.includes('data-case-key="DEMO::synthetic_ira::c1"'), 'selected case detail missing')
const listDown = wrap(React.createElement(RecoveryListView, { projection: down, sourceUnavailable: true, selectedKey: null, onSelect() {}, gate: fresh, onReview() {}, legacyCount: null }))
check((listDown.match(/>Unavailable</g) || []).length === 3, 'KPI counts must read Unavailable when the read failed')
check(listDown.includes('recovery-list-unavailable'), 'list unavailable notice missing')

// No order/sizing vocabulary leaks into the screens.
for (const html of [home, list]) check(!/place order|buy now|position size|shares to buy/i.test(html), 'order or sizing language rendered')

if (failed) { console.error(`recoveryScreens.render: ${failed} failure(s)`); process.exit(1) }
console.log('recoveryScreens.render: ok')
