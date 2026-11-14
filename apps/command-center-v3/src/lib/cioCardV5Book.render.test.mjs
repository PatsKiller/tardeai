// LQ-20261113-3076 (trace A07): RENDERS the real CioCardV5 Book row and asserts the account counts are named:
// "5 accounts (4 with positions)", never the narrower count as plain "accounts". Synthetic card bodies only.
//   node src/lib/cioCardV5Book.render.test.mjs
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
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { pathname: '/', search: '', href: 'http://synthetic.invalid/' } }

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

const { default: CioCardV5 } = await import(compile(join(app, 'src/components/home/CioCardV5.tsx')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const prov = { source_id: 'synthetic:brief', as_of: '2026-01-05T21:00:00Z' }
const render = (book) => renderToStaticMarkup(React.createElement(CioCardV5, { card: { book: { ...prov, ...book } }, adviceOk: true, nowMs: Date.parse('2026-01-05T21:30:00Z') }))
const bookRow = (html) => { const i = html.indexOf('data-testid="cio5-row-book"'); return i < 0 ? '' : html.slice(i, html.indexOf('</div></div>', i)) }
const text = (html) => html.replace(/<[^>]+>/g, '')

const DEF = 'an account is in the book when ... cash rows included'
const cur = bookRow(render({ positions: 4, accounts: 5, accounts_with_positions: 4, cash_only_accounts: ['syn_cash'], accounts_unnamed_rows: 0, accounts_definition: DEF, cash: 900 }))
check(cur !== '', 'Book row not rendered')
check(text(cur).includes('4 positions · 5 accounts (4 with positions) · $900 cash'), `both counts not named: ${text(cur)}`)
check(/data-testid="cio5-book-accounts"[^>]*title="[^"]*cash rows included[^"]*Cash only: Syn Cash/.test(cur), 'definition and cash-only name not in the title')

const legacy = bookRow(render({ positions: 4, accounts: 4, cash: 900 }))
check(text(legacy).includes('4 accounts with positions (all-accounts count unknown)'), `a legacy card printed the narrower count as plain accounts: ${text(legacy)}`)
check(!/4 positions · 4 accounts ·/.test(text(legacy)), 'legacy: plain "4 accounts" must not render')

const same = bookRow(render({ positions: 3, accounts: 3, accounts_with_positions: 3, cash_only_accounts: [], accounts_definition: DEF, cash: 10 }))
check(text(same).includes('3 positions · 3 accounts · $10 cash'), `equal counts: ${text(same)}`)

if (failed) { console.error(`cioCardV5Book.render: ${failed} failure(s)`); process.exit(1) }
console.log('cioCardV5Book.render: ok')
