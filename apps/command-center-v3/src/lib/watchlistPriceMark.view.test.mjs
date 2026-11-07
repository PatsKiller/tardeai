// LQ-20261107-273: a kept price carries ITS OWN as-of, and a failed lookup is its own visible fact.
//
// The defect: an enrichment sweep that could not price a symbol kept the last good price (LQ-56) but still moved
// last_enriched_at, and api_v2 derives the card's price_as_of from last_enriched_at — so the card presented an older
// price with the timestamp of the attempt that failed to replace it. These tests render the REAL card (React server
// rendering over a fixture payload) and assert what it says, not what its source contains: a card that carries the
// right strings inside a branch nobody reaches would still fail here.
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

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

const memory = new Map()
function compile(path) {
  if (memory.has(path)) return memory.get(path)
  let source = readFileSync(path, 'utf8').replace(/import\s+['"][^'"]+\.css['"];?/g, '')
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
  memory.set(path, url)
  return url
}

if (typeof globalThis.window === 'undefined') globalThis.window = globalThis
if (typeof globalThis.matchMedia !== 'function') {
  globalThis.matchMedia = () => ({
    matches: false, media: '', addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent() { return false },
  })
  globalThis.window.matchMedia = globalThis.matchMedia
}

const { priceMark } = await import(compile(join(app, 'src/lib/watchlistCardV4.ts')))
const { default: WatchlistCardV4 } = await import(compile(join(app, 'src/components/WatchlistCardV4.tsx')))

const failures = []
const ok = (cond, message) => { if (!cond) failures.push(message) }
const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&#x2014;/g, '—').replace(/\s+/g, ' ')
const tag = (html, id) => (html.match(new RegExp(`<[^>]*data-testid="${id}"[^>]*>`)) || [''])[0]

// ── the derivation, on the four row shapes the sweep can now write ─────────────
const observedAt = '2026-11-06T15:04:00Z'     // when the price that is displayed was actually taken
const failedAt = '2026-11-07T16:32:52Z'       // the attempt that could not replace it (the old "price_as_of")

{
  const m = priceMark({ price: 19.09, price_source: 'enrichment', price_as_of: failedAt,
    price_observed_at: observedAt, price_observed_source: 'finviz', price_lookup_failed_at: failedAt })
  ok(m.asOf === observedAt, 'a failing lookup must date the KEPT price from its own observation, not the attempt')
  ok(m.source === 'finviz', 'the kept price must name the rung that supplied it')
  ok(m.lookupFailing === true, 'a recorded failed lookup must be reported as failing')
  ok(m.failedAt === failedAt, 'the failure time must be kept separately for the card to report')
  ok(m.ageUnknown === false, 'an observed price has a known age')
}
{
  const m = priceMark({ price: 19.09, price_source: 'enrichment', price_as_of: failedAt, price_lookup_failed_at: failedAt })
  ok(m.asOf === null, 'a kept price with no recorded observation must not borrow the attempt time')
  ok(m.ageUnknown === true, 'unknown age must be stated as unknown, never guessed')
  ok(m.lookupFailing === true, 'a recorded failed lookup must be reported as failing')
}
{
  const m = priceMark({ price: 391.16, price_as_of: '2026-11-07T20:59:00Z', price_source: 'market_quotes' })
  ok(m.live === true && m.lookupFailing === false, 'a live quote is not a kept stale price')
  ok(m.asOf === '2026-11-07T20:59:00Z', 'a live quote keeps the quote time as its as-of')
}
{
  const legacy = priceMark({ price: 19.09, price_source: 'enrichment', price_as_of: failedAt })
  ok(legacy.asOf === failedAt && legacy.lookupFailing === false && legacy.ageUnknown === false,
    'a row written before the capture columns existed keeps the old behaviour (no regression to blank)')
}

// ── what the card actually renders ────────────────────────────────────────────
const baseItem = {
  symbol: 'CXMT', company: 'Fixture Memory Corp', price: 19.09, change_pct: -1.2,
  last_enriched_at: failedAt, price_source: 'enrichment', price_as_of: failedAt,
  setup_advisory: 'RSI 44 · band mid · price stale (last good price kept)',
  rsi: 44, trend: 'neutral', score: 55, watch_score_kind: 'technical', status: 'active',
}

function renderCard(it) {
  const props = {
    it, llms: [], paMap: {}, ensOpen: false, isStarred: false,
    onDrill() {}, onToggleStar() {}, onRefresh() {}, onToggleEns() {},
  }
  return renderToStaticMarkup(React.createElement(WatchlistCardV4, props))
}

{
  const html = renderCard({ ...baseItem, price_observed_at: observedAt,
    price_observed_source: 'finviz', price_lookup_failed_at: failedAt })
  ok(html.includes('data-testid="wlc-price-lookup-failed"'),
    'a failing price lookup must be visible on the card, not only in the advisory text')
  ok(text(html).includes('price stale · lookup failing'), 'the failing chip must say what it is')
  const title = tag(html, 'wlc-price').match(/title="([^"]*)"/)?.[1] ?? ''
  ok(title.includes(new Date(observedAt).toLocaleTimeString()),
    `the price tooltip must carry the price's OWN observation time, got: ${title}`)
  ok(!title.includes(new Date(failedAt).toLocaleTimeString()),
    `the price tooltip dated the price by the failed attempt, got: ${title}`)
}

{
  const html = renderCard({ ...baseItem, price_lookup_failed_at: failedAt })
  ok(html.includes('data-testid="wlc-price-lookup-failed"'), 'an unobserved kept price must still say the lookup is failing')
  const title = tag(html, 'wlc-price').match(/title="([^"]*)"/)?.[1] ?? ''
  ok(title.includes('no recorded time'), `a price of unknown age must say so, got: ${title}`)
  ok(!title.includes('as of '),
    `an unobserved price must not be presented as observed at any time, got: ${title}`)
  // The failure time may be reported as the FAILURE's time (it is a separate fact); it must never become the price's.
  ok(title.includes('the latest lookup failed'),
    `the failure must be attributed to the lookup, not the price, got: ${title}`)
  const chipTitle = tag(html, 'wlc-price-lookup-failed').match(/title="([^"]*)"/)?.[1] ?? ''
  ok(chipTitle.includes('its own time was not recorded'), `the chip must not invent an age, got: ${chipTitle}`)
}

{
  const html = renderCard({ ...baseItem, price: 391.16, price_source: 'market_quotes',
    price_as_of: new Date().toISOString(), price_lookup_failed_at: null })
  ok(!html.includes('data-testid="wlc-price-lookup-failed"'),
    'a live quote that succeeded must not carry the failing chip')
}

// ── the sweep is the only writer of these columns ─────────────────────────────
function sourceFiles(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...sourceFiles(p))
    else if (/\.(py|ts|tsx|mjs|js)$/.test(name) && !/\.test\.|\.spec\./.test(name)) out.push(p)
  }
  return out
}
const root = resolve(app, '../..')
const writers = sourceFiles(join(root, 'scripts')).filter(p => {
  const src = readFileSync(p, 'utf8')
  return /UPDATE\s+watchlist_items/i.test(src) && /price_observed_at|price_lookup_failed_at/.test(src)
}).map(p => p.slice(root.length + 1))
ok(JSON.stringify(writers) === JSON.stringify(['scripts/watchlist_enrichment_sweep.py']),
  `these files both UPDATE watchlist_items and write the price-capture columns: ${writers.join(', ')}`)

if (failures.length) {
  console.error('LQ-20261107-273 price as-of FAILED:\n  - ' + failures.join('\n  - '))
  process.exit(1)
}
console.log('LQ-20261107-273 ok: the kept price carries its own as-of and a failed lookup is visible')
