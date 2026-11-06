// node --experimental-strip-types src/lib/entryDeskCollapse.render.test.mjs
// codex B1 (2026-11-04): the collapsed shortlist still rendered the exit ladder, activity line, diligence
// strip and technical action, contradicting the Show-details label. This RENDERS the real component and
// asserts their absence while collapsed, and their presence once expanded — the content boundary itself,
// not a source grep.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {} }
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: () => Promise.resolve() } }, configurable: true })

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

const ROW = {
  id: 1, symbol: 'ADBE', source: 'WATCHLIST', entryPrice: 500, stop: 470, entryType: 'LIMIT',
  qty: 10, account: 'ANY', targets: [{ price: 540 }], protective: false, generated: false,
  diligence: { synthesis: 'ADD', actionable: true },
}
const TECH = { technical_grade: 'B', action: 'Momentum intact above the 50-day.' }

const { default: EntryDeskRow } = await import(compile(join(app, 'src/components/EntryDeskRow.tsx')))

function render(expanded) {
  return renderToStaticMarkup(React.createElement(EntryDeskRow, {
    r: ROW, state: 'READY', hit: undefined, account: null, streetTarget: null, tech: TECH,
    accounts: ['ANY'], accountMap: {}, onSetField() {}, onCopyMsg() {}, onPromote() {},
    promoteBusy: false, focused: false, expanded, onToggle() {},
  }))
}

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const collapsed = render(false)
const open = render(true)

// The shortlist keeps what the operator scans.
check(/ADBE/.test(collapsed), 'the symbol is missing from the collapsed row')
check(/stop/.test(collapsed), 'the stop line is missing from the collapsed row')

// The long detail sections are behind the disclosure.
for (const [needle, name] of [['Exit ladder', 'exit ladder'], ['No matching Schwab activity', 'activity line'],
                              ['Tech action', 'technical action'], ['CIO synthesis (portfolio mandate)', 'diligence strip']]) {
  check(!collapsed.includes(needle), `the collapsed row still renders the ${name}`)
  check(open.includes(needle), `the expanded row does not render the ${name}`)
}

if (failed) { console.error(`entryDeskCollapse.render: ${failed} failure(s)`); process.exit(1) }
console.log('entryDeskCollapse.render: ok')
