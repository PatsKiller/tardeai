// FQ-076: disabled filters and an unknown next-review time must EXPLAIN themselves in text the operator
// can actually see — proved by rendering the page, not by finding strings in its source.
//
// cc-deepseek-3 RECHECK BLOCK on #2606 (2026-11-05T14:35Z), F1: the first version of this file read
// `WatchIntelligenceUnified.tsx` with readFileSync and ran regexes over the source text. It would pass
// equally on a page whose condition never renders the span, or whose fallback lives in a branch the
// operator never reaches — the FQ-132 class. This file renders the real page (React server rendering, a
// fixture payload) and asserts the words it prints, plus the disabled controls themselves.
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

// Server rendering emits one `useLayoutEffect does nothing on the server` warning per component, and each
// stack line embeds a multi-megabyte `data:` module URL; the FQ-075 render test documents the same flood.
// Drop exactly that warning, keep everything else.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  // The component reads the API through this hook; a render test supplies the payload instead.
  let source = readFileSync(path, 'utf8')
    .replace(/import\s+['"][^'"]+\.css['"];?/g, '')
    .replace(
      /import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__watchlistFixture',
    )
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

// Unified pulls MobileDetailSheet which calls matchMedia at useState init — stub before import.
if (typeof globalThis.window === 'undefined') {
  globalThis.window = globalThis
}
if (typeof globalThis.matchMedia !== 'function') {
  globalThis.matchMedia = () => ({
    matches: false,
    media: '',
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() { return false },
  })
  globalThis.window.matchMedia = globalThis.matchMedia
}

const { default: Unified } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

// One card, and the three next-review fields are all absent — the state the operator sees for a name
// whose generic projection is absent. Individual NOT_SCHEDULED reasons do not establish a card-wide negative.
const card = {
  symbol: 'BBB', company: 'Fixture Watch Corp', street_rating: 'BUY', trade_ai_state: 'READY',
  quote_freshness: 'AFTER_HOURS_CURRENT', review_freshness: 'STALE',
  cio_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  maria_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  last: 12.34, day_change_pct: 0.5,
}
globalThis.__watchlistFixture = {
  data: { cards: [card], items: [{ card }], summary: {}, views: { top_ideas: {} }, projections: {} },
  loading: false,
  error: null,
}

const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Unified)))
const text = html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&#x2014;/g, '—').replace(/\s+/g, ' ')

// cx-openai-5 F1 at 35c32e7d0: absence of the three flat next-review fields is not evidence that nothing is scheduled. A
// deferred decision leaves them null while the producer still knows the review is deferred — the page must not convert
// missing projection data into a claim about the schedule. No NOT_SCHEDULED reason on this card, so the honest line is
// "not provided".
const deferredCard = {
  symbol: 'ZZZ', company: 'Deferred Co', street_rating: 'BUY', trade_ai_state: 'WAIT',
  quote_freshness: 'CURRENT', review_freshness: 'CURRENT',
  cio_review: { status: 'COST_DEFERRED', reason_code: 'COST_DEFERRED' },
  maria_review: { status: 'NOT_RUN', reason_code: 'NOT_SCHEDULED' },
  last: 4.2, day_change_pct: 0.1,
}
globalThis.__watchlistFixture = {
  data: { cards: [deferredCard], items: [{ card: deferredCard }], summary: {}, views: { top_ideas: {} }, projections: {} },
  loading: false,
  error: null,
}
const deferredHtml = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Unified)))
const deferredText = deferredHtml.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&#x2014;/g, '—').replace(/\s+/g, ' ')

const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

// 1. the reason for the four disabled filters is VISIBLE on the page, not only in a title tooltip a
// phone never shows — and it is attached to the element that is actually rendered.
ok(html.includes('data-testid="filters-unavailable-reason"'),
  'the visible filters-unavailable reason element is not in the rendered page')
ok(text.includes('Four filters are off until the broker provider lands'),
  'the four-filter reason is not in the rendered text')
ok(text.includes('catalyst and earnings windows, relative-strength band and valuation band'),
  'the reason does not name the four filters the operator loses')

// 2. exactly the four controls the sentence names carry the typed-unavailable reason and are disabled. The
// page also disables four OTHER selects (saved list, CIO view, provider, model) — but those are unavailable
// because this fixture's payload carries no data, and each says so in its own label; the sentence is about
// the typed gap that no payload can fill. Coupling the two sets keeps them honest (cc-deepseek-3 F3).
const NAMED = ['catalyst_window', 'earnings_window', 'relative_strength_band', 'valuation_band']
const filterControls = [...html.matchAll(/<select\b[^>]*\bdata-filter="([a-z_]+)"[^>]*>/g)]
const byName = new Map(filterControls.map(([tag, name]) => [name, tag]))
for (const name of NAMED) {
  const tag = byName.get(name) ?? ''
  ok(Boolean(tag), `${name} is named by the sentence but is not rendered`)
  ok(/\bdisabled\b/.test(tag), `the ${name} control renders ENABLED while the page says it is off`)
  ok(/typed unavailable until broker provider lands/.test(tag),
    `the ${name} control does not carry the typed-unavailable reason the sentence describes`)
}
const typedUnavailable = filterControls
  .filter(([tag]) => /typed unavailable until broker provider lands/.test(tag))
  .map(([, name]) => name).sort()
ok(JSON.stringify(typedUnavailable) === JSON.stringify([...NAMED].sort()),
  `the page marks [${typedUnavailable.join(', ')}] as typed-unavailable, but the sentence names four: catalyst and earnings windows, relative-strength band and valuation band`)

// 3. an unknown next-review time renders the sentence, never a bare dash.
ok(text.includes('not provided — the producer has not reported a review time for this name'),
  'absent flat fields must stay neutral even when individual reviewers are NOT_SCHEDULED')
ok(!/Next review: *—/.test(text),
  'the next-review line fell back to a bare dash instead of saying why')

// 3b. cx-openai-5 F1: the SAME three absent fields on a card whose review is DEFERRED must not claim "not scheduled".
ok(deferredText.includes('not provided — the producer has not reported a review time for this name'),
  'a card with no NOT_SCHEDULED reason did not render the neutral not-provided line')
ok(!deferredText.includes('not scheduled — no review time has been set for this name'),
  'missing projection data was converted into the claim that nothing is scheduled')


// F1 residual (cx-openai-2/cx-openai-5 at 46542b1c): _compose_card keeps reviewer display evidence while
// its decision projection may leave all flat review fields null. These fields mirror enrich_review_display's ABI;
// the author-side controls separately regenerate the complete cards with the actual Python formatter/composer.
const nextAt = '2026-11-06T14:00:00Z'
const scheduledMaria = { status: 'NOT_RUN', reason_code: 'SCHEDULED', display: {
  label: 'MARIA REVIEW: SCHEDULED', reason: 'SCHEDULED', next_review: nextAt,
  next_policy_window: nextAt, next_execution_at: nextAt, execution_status: 'QUEUED',
} }
const deferredMaria = { status: 'NOT_RUN', reason_code: 'COST_DEFERRED', display: {
  label: 'MARIA REVIEW: DEFERRED', reason: 'COST_DEFERRED', next_policy_window: nextAt,
} }
const nextReviewCases = [
  { name: 'CIO default negative with executable Maria', value: { ...card, maria_review: scheduledMaria },
    line: 'not provided — the producer has not reported a review time for this name', mariaLabel: 'MARIA REVIEW: SCHEDULED' },
  { name: 'CIO default negative with deferred Maria', value: { ...card, maria_review: deferredMaria },
    line: 'not provided — the producer has not reported a review time for this name', mariaLabel: 'MARIA REVIEW: DEFERRED' },
  { name: 'explicit flat time', value: { ...card, maria_review: scheduledMaria, next_review_at: nextAt }, line: nextAt },
  { name: 'explicit flat condition', value: { ...card, next_review_condition: 'After new earnings evidence' },
    line: 'After new earnings evidence' },
  { name: 'legacy flat time', value: { ...card, next_review_time: nextAt }, line: nextAt },
  { name: 'producer-projected generic negative', value: { ...card,
      next_review_condition: 'not scheduled — no review time has been set for this name' },
    line: 'not scheduled — no review time has been set for this name' },
]
for (const test of nextReviewCases) {
  const value = test.value
  globalThis.__watchlistFixture = { data: { cards: [value], items: [{ card: value }], summary: {},
    views: { top_ideas: {} }, projections: {} }, loading: false, error: null }
  const rendered = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Unified)))
  const content = rendered.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  ok(content.includes('Next review: ' + test.line), `${test.name}: wrong generic next-review line`)
  if (test.mariaLabel) ok(content.includes(test.mariaLabel), `${test.name}: native reviewer evidence disappeared`)
}

// 4. the retirement is enforced, not just stated: the live surface is Unified, not the shadow board.
function sourceFiles(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...sourceFiles(p))
    else if (/\.(ts|tsx|mjs|js)$/.test(name) && !/\.test\.|\.spec\./.test(name)) out.push(p)
  }
  return out
}
const importers = sourceFiles(join(app, 'src'))
  .filter(p => !p.endsWith('WatchlistIntelligenceBoard.tsx'))
  .filter(p => /WatchlistIntelligenceBoard/.test(readFileSync(p, 'utf8')))
ok(importers.length === 0,
  `the retired shadow board is imported by ${importers.map(p => p.slice(app.length + 1)).join(', ')}`)

if (failures.length) {
  console.error('FQ-076 FAILED:\n  - ' + failures.join('\n  - '))
  console.error('rendered text: ' + text.slice(0, 900))
  process.exit(1)
}
console.log('FQ-076 ok: disabled filters and generic next-review evidence render honestly')
