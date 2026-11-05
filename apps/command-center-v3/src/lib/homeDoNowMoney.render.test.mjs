// node --experimental-strip-types src/lib/homeDoNowMoney.render.test.mjs
// FQ-087 (cx-openai-3 block): the money qualifier lived only on HomeClassic, which is NOT the default route
// (HomeHub renders HomeDoNow unless ?view=classic). This renders the DEFAULT page and asserts the qualifier
// is visible on it for a retained transport, and absent when the transport is clean and the data is fresh.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))

// Unfiltered this file writes ~501 MB of stderr per run: each SSR "useLayoutEffect does nothing on the server"
// warning embeds a multi-megabyte data: module URL, and this page renders enough components to emit dozens of them.
// It is in the build line, so every npm run build would pay that. Same filter as retirement.metric.view.test.mjs:19.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  location: { pathname: '/', search: '' },
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  source = source.replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (path: string): any => (globalThis as any).__homeFixture(path)')
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

const now = new Date().toISOString()
const overview = {
  portfolio_value: 1253532.64, today_change: -1499.89, today_pct: -0.12, position_count: 31,
  last_repriced: now,
  observation: { envelopes: { holdings: { observed_at: now, freshness: { status: 'FRESH', observed_at_utc: now } } } },
}
globalThis.__homeFixture = (path) => {
  if (String(path) === '/api/v2/overview') {
    return { data: overview, loading: false, stale: false, error: null, transport: globalThis.__transport ?? 'OK', refetch: () => {} }
  }
  return { data: null, loading: false, stale: false, error: null, transport: 'OK', refetch: () => {} }
}

const { default: HomeDoNow } = await import(compile(join(app, 'src/pages/HomeDoNow.tsx')))
const { positionsFreshness } = await import(compile(join(app, 'src/lib/homeDoNow.ts')))
const render = (transport) => {
  globalThis.__transport = transport
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(HomeDoNow, {})))
}

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const retained = render('RETAINED')
check(/home-money-qualifier/.test(retained), 'the DEFAULT Home page renders no money qualifier at all')
check(/last known value|not refreshed/i.test(retained), 'the retained transport does not say the value is last-known')
check(/1,253,5/.test(retained), 'the portfolio value itself is missing from the default page')

const clean = render('OK')
check(!/home-money-qualifier/.test(clean), 'a clean, fresh transport is still being flagged on the default page')

// The pure function takes the transport as an input now, so a retained refresh is stale by construction.
const retainedPos = positionsFreshness(overview, Date.now(), 'RETAINED')
check(retainedPos.stale === true, 'positionsFreshness ignores a retained transport')
check(retainedPos.qualifier !== null, 'positionsFreshness returns no qualifier for a retained transport')
check(/did not complete cleanly/i.test(retainedPos.tip), 'the positions tip does not say the refresh failed')
const cleanPos = positionsFreshness(overview, Date.now(), 'OK')
check(cleanPos.stale === false, 'a clean, fresh positions read is called stale')
check(cleanPos.qualifier === null, 'a clean, fresh positions read carries a qualifier')

if (failed) { console.error(`homeDoNowMoney.render: ${failed} failure(s)`); process.exit(1) }
console.log('homeDoNowMoney.render: ok')
