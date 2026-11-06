// node --experimental-strip-types src/lib/entryAlertsLane.render.test.mjs
// cc-deepseek-9's block on #2646: the packet state must be RENDERED, not implied. The lane passed `title` to a Chip
// that drops `title` whenever `guideKey` is set, so an unrecognised state rendered only "Unrecognised state" and the
// raw value appeared nowhere on the page. These checks drive the real component and read the markup it produces.
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync, statSync } from 'node:fs'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const cache = new Map()
/** The file a relative specifier means, before anything is executed. Extension-less and directory imports are the
 *  reason a stub keyed by the path a component WRITES (`'../primitives'`) never matched: the loader resolved it to
 *  `…/primitives/index.ts` and called the real module (cc-deepseek-4's zero-card harness). */
function resolveFile(base) {
  for (const cand of [base + '.ts', base + '.tsx', base + '.js', base]) {
    try { if (statSync(cand).isFile()) return cand } catch { /* not this one */ }
  }
  for (const cand of [join(base, 'index.ts'), join(base, 'index.tsx')]) {
    try { if (statSync(cand).isFile()) return cand } catch { /* not this one */ }
  }
  return null
}
function load(path, extra = {}) {
  if (cache.has(path)) return cache.get(path)
  const source = readFileSync(path, 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true } }).outputText
  const module = { exports: {} }
  cache.set(path, module.exports)
  const localRequire = (name) => {
    if (name in extra) return extra[name]
    if (name.endsWith('.css')) return {}
    if (name.startsWith('.')) {
      const base = join(dirname(path), name)
      const file = resolveFile(base)
      // A stub may be keyed by the specifier as written, by the resolved path without its extension, or by the file.
      for (const key of [base, file]) if (key && key in extra) return extra[key]
      if (!file) throw new Error(`cannot resolve ${name} from ${path}`)
      return load(file, extra)
    }
    return require(name)
  }
  new Function('require', 'module', 'exports', '__filename', js)(localRequire, module, module.exports, path)
  return module.exports
}

const ROW = (state, account = 'AcctA') => ({
  symbol: 'SYN', account, state, zone: { position: 'above', distance_pct: 1.2 },
  cio_verdict: {}, cio_review: {}, options_alt: {}, desk: { status: 'ok' },
  entry_low: 10, entry_high: 11, stop: 9, target: 14, price: 10.5,
})

const packets = { data: { rows: [ROW('SOMETHING_NEW'), ROW('SOMETHING_NEW', 'AcctB')] }, loading: false, error: null, refetch() {} }
// The real Collapsible keeps its body behind a useState toggle; in SSR that would hide every card and the checks
// would pass vacuously. Render its children directly — this is a presentation shell, not the behaviour under test.
const primitives = load(resolve(app, 'src/components/primitives/index.ts'), {})
const OpenCollapsible = ({ children, title, summary, count }) =>
  React.createElement('section', { 'data-t': title, 'data-count': count }, React.createElement('div', null, summary), children)
const lane = load(resolve(app, 'src/components/reentry/EntryAlertsLane.tsx'), {
  [resolve(app, 'src/components/primitives')]: { ...primitives, Collapsible: OpenCollapsible },
  [resolve(app, 'src/hooks/useApi')]: { useApi: () => packets },
})

const markup = renderToStaticMarkup(React.createElement(lane.EntryAlertsLane || lane.default))

check('the lane renders at all', markup.length > 0, 'nothing rendered')
check('an unrecognised state still says it is unrecognised', markup.includes('Unrecognised state'), markup.slice(0, 200))
check('and the RAW state value is rendered, not only implied by a title attribute',
  markup.includes('SOMETHING_NEW'), 'the raw packet state appears nowhere in the output')
check('one card per packet row', (markup.match(/entry-alert-card/g) || []).length === 2,
  `cards: ${(markup.match(/entry-alert-card/g) || []).length}`)

// The React KEY cannot be pinned by markup: `react-dom/server` renders duplicate-key children without warning (measured
// here — zero warnings with two children keyed 'SYN'), so a markup check passes whether or not the key carries the
// account. Pinning it at the source, and saying so, beats an assertion that cannot fail (the exact habit this PR's
// subject keeps producing). FQ-096: two accounts may hold one symbol, and a symbol-only key makes React reuse the
// first account's card for the second.
const laneSource = readFileSync(resolve(app, 'src/components/reentry/EntryAlertsLane.tsx'), 'utf8')
const keyLine = laneSource.split('\n').find((ln) => ln.includes('<AlertCard') && ln.includes('key=')) || ''
check('the card key carries the account (source; markup cannot prove a key)',
  keyLine.includes('account'), `the AlertCard key does not name the account: ${keyLine.trim()}`)

console.log(`entryAlertsLane.render: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
