// node src/lib/vixTile.boundary.test.mjs
//
// FQ-086 boundary: the VIX tile must never colour a number the reading does not certify as current.
//
// This used to be a SOURCE-PATTERN assertion: it accepted the text `!vixReading.current ... text3` in
// MetricStrip.tsx, so the causal mutation `!vixReading.current && false ? text3 : valueColour` kept it green
// while every non-current VIX rendered in the confident value colour (review cx-openai-3 F4 on PR #2654).
// The behavioural claim is now observed in the REAL rendered component: the tile is mounted through the same
// transpile-and-render harness the sibling .view.test.mjs files use, and the rendered value colour, attention
// membership and visible explanation are asserted for stale / future / undated readings under BOTH
// quiet_provenance settings. Only registration and import placement remain static checks.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// One SSR warning per component, each stack line a multi-megabyte data: URL. Expected on the server; drop it only.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const { MemoryRouter } = require('react-router-dom')

globalThis.window = globalThis.window ?? {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  innerWidth: 1400, scrollTo() {}, location: { search: '' },
  localStorage: { getItem: () => null, setItem: () => {} },
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    .replace(/import \{([^}]*)\} from (['"][^'"]+['"])/g, (whole, names, spec) => {
      const list = names.split(',').map(s => s.trim()).filter(Boolean)
      const kept = list.filter(n => n !== 'useApi' && n !== 'useGovernance')
      const stubs = []
      if (list.includes('useApi')) stubs.push('const useApi = (...a: any[]): any => (globalThis as any).__apiFixture(String(a[0] ?? ""), a[2])')
      if (list.includes('useGovernance')) stubs.push('const useGovernance = (...a: any[]): any => (globalThis as any).__govFixture(...a)')
      const imp = kept.length ? `import { ${kept.join(', ')} } from ${spec}` : ''
      return [imp, ...stubs].filter(Boolean).join('\n')
    })
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, { compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, removeComments: true } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (existsSync(target) && statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture dependency index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { default: MetricStrip } = await import(compile(join(app, 'src/components/MetricStrip.tsx')))

const NOW = Date.now()
const ago = (h) => new Date(NOW - h * 3600_000).toISOString()

let quietProvenance = true
let tradeAi = null
globalThis.__apiFixture = (url) => {
  if (String(url).includes('/api/v2/design-features')) {
    return { data: { header: { quiet_provenance: quietProvenance } }, loading: false, error: null }
  }
  if (String(url).includes('/api/v2/trade-ai')) return { data: tradeAi, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const render = () => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(MetricStrip, { onDrill: () => {} })))

// The rendered VIX tile, located by its own label. Everything below reads the DOM output, not the source.
function vixChunk(markup) {
  const parts = markup.split('class="metric-strip-tile"').slice(1)
  return parts.find(p => />VIX(?:<span|<)/.test(p.slice(0, 1400))) || ''
}
const tileValueStyle = (chunk) => /<div class="ms-value" style="([^"]*)"/.exec(chunk)?.[1] ?? ''
const tileValue = (chunk) => /<div class="ms-value"[^>]*>([^<]*)<\/div>/.exec(chunk)?.[1] ?? ''
const tileMeta = (chunk) => /<div class="ms-meta"[^>]*>([^<]*)<\/div>/.exec(chunk)?.[1] ?? ''
const tileLabel = (chunk) => (/<div class="ms-label"[^>]*>([\s\S]*?)<\/div>/.exec(chunk)?.[1] ?? '').replace(/<[^>]+>/g, '')
const attention = (markup) => /title="Needs attention: ([^"]*)"/.exec(markup)?.[1] ?? ''

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

function renderReading(reading, flag) {
  quietProvenance = flag
  tradeAi = reading
  const markup = render()
  const chunk = vixChunk(markup)
  return { markup, chunk, style: tileValueStyle(chunk), value: tileValue(chunk), meta: tileMeta(chunk), label: tileLabel(chunk), attention: attention(markup) }
}

const scanner = { vix_source: 'trade_ai_run_summary', run_label: '1730' }

// ── Fresh: the one state allowed a value colour. It stays quiet under both flags. ────────────────────────────
for (const flag of [true, false]) {
  const r = renderReading({ ...scanner, vix: 17.4, vix_observation_time: ago(0.25) }, flag)
  check(`fresh (quiet_provenance=${flag}) keeps the value colour, not the non-current grey`,
    /color:#22c55e/.test(r.style) && !r.style.includes('var(--text3)'), r.style)
  check(`fresh (quiet_provenance=${flag}) does not enter the attention list`, !/VIX/.test(r.attention), r.attention)
  check(`fresh (quiet_provenance=${flag}) keeps its number`, r.value === '17.4', r.value)
  check(`fresh (quiet_provenance=${flag}) shows no stale marker`, !/STALE/.test(r.label), r.label)
}
{
  const r = renderReading({ ...scanner, vix: 17.4, vix_observation_time: ago(0.25) }, true)
  check('fresh operator words are humanised on the face, never the raw source token',
    /scanner/.test(r.meta) && !/trade_ai_run_summary/.test(r.meta), r.meta)
}
{
  const r = renderReading({ ...scanner, vix: 17.4, vix_observation_time: ago(0.25) }, false)
  check('fresh stays quiet when quiet provenance is off (the note is withheld, as before)', r.meta === '—', r.meta)
}
{
  // The other value `_vix_observation` returns (scripts/api_v2.py): it must be words on the face too.
  const r = renderReading({ vix: 17.4, vix_source: 'market_regime_indicators.vix_close', vix_observation_time: ago(0.25) }, true)
  check('the regime-feed source reads as operator words on the face, never the raw token',
    /regime feed/.test(r.meta) && !/market_regime_indicators/.test(r.meta), r.meta)
}
{
  const r = renderReading({ vix: 17.4, vix_source: 'market_regime_indicators.vix_close', vix_observation_time: ago(48) }, false)
  check('a non-current regime-feed reading keeps its explanation and never the raw source token',
    /regime feed/.test(r.meta) && !/market_regime_indicators/.test(r.meta) && /past the 36 h limit — not current/.test(r.meta), r.meta)
}

// ── Non-current: the decisive guarantee. Grey value, joined to attention, explanation visible under BOTH flags. ─
const faults = [
  { name: 'stale 48h', reading: { ...scanner, vix: 17.4, vix_observation_time: ago(48) }, say: /past the 36 h limit — not current/ },
  { name: 'future +1h', reading: { ...scanner, vix: 17.4, vix_observation_time: new Date(NOW + 3600_000).toISOString() }, say: /observation time is in the future/ },
  { name: 'undated', reading: { ...scanner, vix: 17.4, vix_observation_time: null }, say: /observation time not recorded/ },
]
for (const fault of faults) {
  for (const flag of [true, false]) {
    const r = renderReading(fault.reading, flag)
    check(`${fault.name} (quiet_provenance=${flag}) renders the number in the non-current grey`,
      /color:var\(--text3\)/.test(r.style), r.style)
    check(`${fault.name} (quiet_provenance=${flag}) is in the accessible attention list`,
      /VIX/.test(r.attention), r.attention)
    check(`${fault.name} (quiet_provenance=${flag}) keeps its explanation on the face`,
      fault.say.test(r.meta), r.meta)
    check(`${fault.name} (quiet_provenance=${flag}) keeps the number and never the raw source token`,
      r.value === '17.4' && !/trade_ai_run_summary/.test(r.meta), `${r.value} :: ${r.meta}`)
  }
}

// ── Static checks that are genuinely static: model import and tile registration/placement. ───────────────────
const src = readFileSync(join(app, 'src/components/MetricStrip.tsx'), 'utf8')
check('the model is imported, not re-implemented', /import \{ vixFreshness \} from '\.\.\/lib\/vixFreshness'/.test(src))
const i = src.indexOf("label: 'VIX'")
const j = src.indexOf("label: 'SETUPS", i)
check('the VIX tile is registered between REGIME and SETUPS', i > 0 && j > i)
check('the old unconditioned colour rule is gone', !/color: vix == null \? 'var\(--text3\)' : vix >= 25/.test(src))

const out = { schema: 'VixTileBoundaryRender@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0
