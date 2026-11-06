// Provenance class at the point of DISPLAY (AGENTS.md §9.5) — CX2 of the #2519 review.
//
// The selector can carry a provenance class and the operator still see nothing: the panel is what is on
// screen. This RENDERS the real RotationDescriptivePanel from the page (not a grep of the source) and
// asserts, for every block the selector emits, that the block's own container prints that block's
// class and label beside its title. Removing the badge from the page turns this red while the selector
// suite stays green.
//
//   node --experimental-strip-types src/lib/rotationDescriptive.view.test.mjs
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

// The server renderer warns once per useLayoutEffect in our dependency tree; expected under SSR and not
// an assertion failure. Drop exactly that warning, keep everything else.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

globalThis.window = globalThis.window ?? {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  innerWidth: 1400, scrollTo() {},
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, { compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (statSync(target).isDirectory()) target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { RotationDescriptivePanel } = await import(compile(join(app, 'src/pages/RotationIntelligence.tsx')))
const { rotationDescriptive } = await import(compile(join(app, 'src/lib/rotationDescriptive.ts')))

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

const at = '2026-11-05T00:00:00Z'
const full = {
  generated_at: at, portfolio_total: 1000000,
  sector_overweights: [{ theme: 'Materials', pct: 12.4, target: 10, excess_dollars: 21000 }],
  sector_underweights: [{ theme: 'Staples', pct: 4.1, floor: 6, gap_pct: -1.9 }],
  degraded_holdings: [{ symbol: 'XYZ' }],
  market_research: {
    available: true, computed_at: at, quote_as_of: at, freshness: 'FRESH',
    sectors: [{ name: 'Materials', etf: 'XLB', return_1m: 1, return_3m: 2, return_6m: 3, rs_raw: 1.1, rs_score: 61, data_quality: 1, quality_status: 'OK' }],
    industries: [{ sector: 'Materials', industries: [{ name: 'Chemicals', return_1m: 1, return_3m: 2, return_6m: 3, rs_raw: 1.1, rs_score: 61, data_quality: 1 }] }],
  },
}

/** Slice the rendered markup to one block's own container, so a badge elsewhere cannot satisfy it. */
function blockHtml(html, key, nextKey) {
  const start = html.indexOf(`data-testid="rotation-descriptive-${key}"`)
  if (start < 0) return ''
  const end = nextKey ? html.indexOf(`data-testid="rotation-descriptive-${nextKey}"`, start) : html.length
  return html.slice(start, end < 0 ? html.length : end)
}

function assertEveryBlockShowsItsProvenance(label, data) {
  const expected = rotationDescriptive(data)
  const html = renderToStaticMarkup(React.createElement(RotationDescriptivePanel, { data }))
  const badges = (html.match(/-provenance"/g) ?? []).length
  check(`${label}: every block is rendered`, expected.blocks.length > 0 && expected.blocks.every(b => html.includes(`data-testid="rotation-descriptive-${b.key}"`)), expected.blocks.map(b => b.key))
  check(`${label}: one provenance badge per block`, badges === expected.blocks.length, `${badges} badges for ${expected.blocks.length} blocks`)
  expected.blocks.forEach((b, i) => {
    const own = blockHtml(html, b.key, expected.blocks[i + 1]?.key)
    check(`${label}: block ${b.key} prints its class and label`, own.includes(`>${b.provenance.class} · ${b.provenance.label}<`), own.slice(0, 240))
    check(`${label}: block ${b.key} badge sits beside its title`, own.includes(b.title) && own.indexOf(b.title) >= 0 && own.indexOf(b.title) < own.indexOf(`rotation-descriptive-${b.key}-provenance`), own.slice(0, 240))
  })
  return { expected, html }
}

const { expected: fullExpected } = assertEveryBlockShowsItsProvenance('full', full)
check('full: the five blocks are overweight/underweight/degraded/market-sectors/market-industries',
  fullExpected.blocks.map(b => b.key).join(',') === 'overweight,underweight,degraded,market-sectors,market-industries',
  fullExpected.blocks.map(b => b.key))
check('full: sector exposure is labelled deterministic on screen', /D · deterministic/.test(renderToStaticMarkup(React.createElement(RotationDescriptivePanel, { data: full }))))
check('full: market projection is labelled snapshot-derived on screen', /S · snapshot-derived/.test(renderToStaticMarkup(React.createElement(RotationDescriptivePanel, { data: full }))))

// The panel exists precisely for the withheld case — provenance must survive it.
const withheld = {
  generated_at: at, portfolio_total: 1000000,
  sector_overweights: [], sector_underweights: [], degraded_holdings: [],
  publication: { status: 'STALE', reasons: ['stale_source_clock'] },
}
const { html: withheldHtml } = assertEveryBlockShowsItsProvenance('withheld', withheld)
check('withheld: the blocks still say the evidence is withheld', /withheld/i.test(withheldHtml), withheldHtml.slice(0, 400))

// A summary that is not there at all emits no blocks, so no badge is invented for one.
const noSummaryHtml = renderToStaticMarkup(React.createElement(RotationDescriptivePanel, { data: null }))
check('no summary: no block and no provenance badge is invented', (noSummaryHtml.match(/-provenance"/g) ?? []).length === 0, noSummaryHtml.slice(0, 240))

const out = { schema: 'RotationDescriptiveProvenanceView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0
