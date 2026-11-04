// node src/lib/advisoryClocks.view.test.mjs
// FQ-003 (/advisory F): the same named input must not read CURRENT in the compact stamp and STALE in
// the dependency clock. The two are different facts — the stamp is the newest watch QUOTE joined into
// the cards; the dependency clock is the newest watch REVIEW completion — so the page must name each
// one for what it measures and say which governs the advice.
//
// This renders the real page with a fixture where the two disagree (CURRENT vs STALE) and asserts the
// rendered words, not the source: a test that only greps the file would pass on a commented-out label.
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

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  // The page's only data source is useApi; give it the fixture directly.
  source = source.replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__advisoryFixture')
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

const FIXTURE = {
  ok: true,
  as_of: '2026-11-04T14:28:27+00:00',
  desk_computed_at: '2026-11-04T14:28:27+00:00',
  desk_cache_age_seconds: 7,
  desk_freshness_state: 'CURRENT',
  desk_freshness_scope: 'DESK_COMPOSITION_ONLY',
  timestamps: {
    facts: '2026-11-04T14:28:27+00:00', facts_freshness: 'CURRENT',
    watch: '2026-11-04T14:00:04+00:00', watch_freshness: 'CURRENT',
    reentry: '2026-11-04T14:28:04+00:00', reentry_freshness: 'CURRENT',
    senses: '2026-11-04T00:45:00+00:00', senses_freshness: 'CURRENT',
    memory: '2026-11-04T14:19:24+00:00', memory_freshness: 'CURRENT',
    flash: '2026-08-19T23:39:35+00:00', flash_freshness: 'EXPIRED',
    synthesis: '2026-11-04T09:15:00+00:00', synthesis_freshness: 'CURRENT',
  },
  dependency_clocks: {
    advisory_synthesis: { name: 'advisory_synthesis', freshness: 'CURRENT', age_seconds: 600, stale_after_seconds: 345600, source_as_of: '2026-11-04T09:15:00+00:00' },
    watch_intelligence: { name: 'watch_intelligence', label: 'watch intelligence', freshness: 'STALE', age_seconds: 5422043, stale_after_seconds: 345600, source_as_of: '2026-09-02T20:21:21+00:00', producer: 'watch_review_workers (CIO/Maria reviews)', source_ref: 'watch_intelligence.reviews.*.completed_at' },
    technicals: { name: 'technicals', freshness: 'FRESH', age_seconds: 100, stale_after_seconds: 345600, source_as_of: '2026-11-04T14:00:00+00:00' },
  },
  dependency_refresh: { synthesis_as_of: '2026-11-04T09:15:00+00:00', older_than_synthesis: [{ label: 'watch intelligence' }], unknown_clock: [], not_refreshed_by_run_now: [] },
  desk_health: { dimensions: { WATCH_INTELLIGENCE_FRESHNESS: 'CURRENT' } },
  timestamps_note: null,
  price_clock: { freshness: 'CURRENT', as_of: '2026-11-04 09:59:00 ET' },
  rows: [], row_count: 0, by_class: {}, metadata: {}, portfolio_analytics: {}, performance: {},
  banners: [], desk_sources: {}, verdict_counts: {}, synthesis: '',
}

globalThis.__advisoryFixture = { data: FIXTURE, loading: false, error: null, refetch: () => {} }
const { default: Page } = await import(compile(join(app, 'src/pages/AdvisoryDeskHub.tsx')))
const html = renderToStaticMarkup(React.createElement(Page, {}))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// 1. The compact stamp must name the fact it shows: quotes, not reviews.
check(/WATCH QUOTES/.test(html), 'the compact watch stamp is not labelled WATCH QUOTES (it shows the newest quote joined)')
// 2. The dependency clock must name its fact: reviews.
check(/WATCH REVIEWS/.test(html), 'the watch dependency clock is not labelled WATCH REVIEWS (it measures the newest review completion)')
// 3. And the old collision must be gone: one label must not be a substring of the other's idea.
check(!/WATCH INTEL<\/div>/.test(html), 'the compact stamp still says WATCH INTEL, which reads as the same input as the review clock')
// 4. The page must say only what the fields prove: a producer's data time, not proof of consumption.
check(/own data time/i.test(html), 'the page does not say the clock is the producer\'s own data time')
check(!/actually consumed|what the advice consumed/i.test(html),
  'the page still claims the clock records what the advice consumed — the clock is a producer time, not consumption')
check(/review evidence/i.test(html), 'the page does not say where to look for what an earlier synthesis used')

if (failed) { console.error(`advisoryClocks.view: ${failed} failure(s)`); process.exit(1) }
console.log('advisoryClocks.view: ok')
