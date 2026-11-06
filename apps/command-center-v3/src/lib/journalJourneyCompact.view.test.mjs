// node --experimental-strip-types src/lib/journalJourneyCompact.view.test.mjs
// FQ-042: on a phone the journal journey list renders DATED SUMMARIES with details on demand,
// and nothing is removed — the full row still exists behind the toggle.
//
// This test RENDERS the real compact Row (the page component is transpiled with the project's
// TypeScript and mounted with react-dom/server), so it observes the label a phone actually shows.
// It fails if a timestamp loses its minutes or a date-only value loses its provenance — the
// 2026-11-05 BLOCK, where `etShort(...).slice(0, 10)` rendered "11-05 10:3" and "11-05 · da".
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const app = resolve(here, '../..')
const pagePath = join(app, 'src', 'pages', 'TradeJourney.tsx')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

// Transpile the page and its relative imports to importable data URLs. The Row under test fetches
// nothing and uses no router hook, so those module dependencies are stubbed; styles are irrelevant
// to the rendered text and there is no stylesheet pipeline in node.
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.css['"]\s*;?\s*$/gm, '')
    .replace(/import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__journeyFixture')
    .replace(/import \{ Link, useLocation, useNavigate, useSearchParams \} from ['"][^'"]+['"]/,
      'const Link = (p: any) => null as any; const useLocation = () => ({ state: null } as any);'
      + ' const useNavigate = () => ((..._a: any[]) => undefined) as any;'
      + ' const useSearchParams = () => [new URLSearchParams(), (() => undefined) as any] as any;')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
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

const { Row } = await import(compile(pagePath))
if (typeof Row !== 'function') {
  console.error('FQ-042 FAILED:\n  - the page does not export the compact Row for rendering')
  process.exit(1)
}

// One synthetic journey — the projection's real shape — with the entry date under test.
const journey = at => ({
  trade_id: 'rt:a|NAVN|2026-10-19', symbol: 'NAVN', company: 'Navan', account: 'a', account_label: 'Acct 231',
  status: 'open', fill_qty: 10,
  entry: { price_ref: 12.5, at, source: 'schwab', at_basis: null },
  exit: null, mark: { price_ref: 13.25, at: '2026-11-05T15:39:00Z' },
  pl: { amount: 7.5, pct: 6, basis: 'unrealized', note: null },
  hold_days: 3,
  origin: {
    kind: 'internal', label: 'Home #4 · conviction 86', surface: 'Home', surface_href: null,
    rank_at_entry: 4, conviction_at_entry: 86, stance_at_entry: 'BUY_READY', cio_entry_state: null,
    cio_entry_state_at: null, issued_at: null, rec_id: null, rec_source: null, link_confidence: null,
    plan: null, evidence: [], link_status: 'linked',
  },
  exit_cause: { kind: 'open', label: 'Open', detail: 'Open position', confirmed: true, level_ref: null, raises: 0 },
  stop_path: [], timeline: [],
  review: { facts: [], metrics: {}, advisory: null },
  re_entry: { conditions: [] }, conflicts: [], conviction_now: 86, stance_now: 'BUY_READY',
  rank_now: 4, stage: 'held', chart: null,
})

const render = j => renderToStaticMarkup(React.createElement(Row, { j, selected: false, onSelect() {}, compact: true }))
const summaryText = markup => {
  const m = markup.match(/<summary[^>]*>([\s\S]*?)<\/summary>/)
  if (!m) throw new Error('the compact row rendered no <summary>')
  return m[1].replace(/<[^>]*>/g, '') // text content only (strips tags and the <!-- --> text separators)
}

const failures = []
const ok = (name, fn) => { try { fn() } catch (e) { failures.push(`${name}: ${e.message}`) } }

// A real ET timestamp renders with its minutes intact.
ok('timestamp', () => {
  const text = summaryText(render(journey('2026-11-05T15:39:00Z')))
  assert.match(text, /11-05 10:39/, `an intact ET timestamp must render; got ${JSON.stringify(text)}`)
  assert.doesNotMatch(text, /\d{2}-\d{2} \d{2}:\d(?!\d)/, 'a timestamp must not end at a truncated minute')
})

// A date-only value renders intact AND keeps its provenance marker.
ok('date-only', () => {
  const text = summaryText(render(journey('2026-11-05')))
  assert.match(text, /11-05 · date only/, `date-only provenance must render intact; got ${JSON.stringify(text)}`)
})

// A missing date is stated explicitly, not silently blank or sliced.
ok('missing-date', () => {
  const text = summaryText(render(journey(null)))
  assert.match(text, /date unavailable/, `a missing date must be stated; got ${JSON.stringify(text)}`)
})

// The primary action stays unique per row, and the full row is still behind the toggle.
ok('primary-action', () => {
  const markup = render(journey('2026-11-05T15:39:00Z'))
  const primary = markup.match(/data-testid="tj-open-journey"/g) || []
  assert.equal(primary.length, 1, 'exactly one node per journey must answer to tj-open-journey')
  assert.match(markup, /data-testid="tj-open-journey-full"/, 'the full row keeps its separately identified action')
  assert.match(markup, /data-testid="tj-row-full"/, 'the full row is preserved behind the toggle')
})

// Source guard: the compact summary renders the intact label and never slices a formatter.
ok('no-slice', () => {
  const src = readFileSync(pagePath, 'utf8')
  const summary = (src.match(/<summary[\s\S]*?<\/summary>/) || [''])[0]
  assert.match(summary, /compactWhenLabel\(j\.entry\.at\)/, 'the compact summary must render the intact when-label')
  assert.doesNotMatch(summary, /\.slice\(/, 'the compact summary must not slice a formatted label')
})

if (failures.length) { console.error('FQ-042 FAILED:\n  - ' + failures.join('\n  - ')); process.exit(1) }
console.log('FQ-042 ok: the compact Row renders an intact ET timestamp, intact date-only provenance and an explicit missing date; one primary action; full row preserved')
