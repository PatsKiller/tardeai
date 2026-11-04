// node --experimental-strip-types src/lib/reportOpsLink.render.test.mjs
// P2595-R1 (codex whole-head BLOCK at c654385eb8): the never-run card's "Open Ops → Jobs" was a raw
// <a href="/ops/jobs">. The app mounts under basename="/v3", so that href left the app and landed on
// /ops/jobs at the host root. This test RENDERS the real component inside MemoryRouter with
// basename="/v3" and asserts the actual destination, not the source text: removing the link, or going
// back to a plain anchor, fails it.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, open() {},
}

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

// The live shape: a report family that has never been generated, so the never-run line renders.
const CATALOG = {
  types: [{
    key: 'daily-dashboard', title: 'Daily dashboard', cadence: 'daily', status: 'never-generated',
    generator: 'system_rollup_snapshot.py (20:40 nightly)', count: null, last_generated_at: null, age_hours: null,
    history: [], artifacts: {},
  }],
}

const { default: ReportLibrary } = await import(compile(join(app, 'src/components/reports/ReportLibrary.tsx')))
const html = renderToStaticMarkup(
  React.createElement(MemoryRouter, { basename: '/v3', initialEntries: ['/v3/reports'] },
    React.createElement(ReportLibrary, { catalog: CATALOG })),
)

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// 1. The never-run line renders, so the link we assert exists on screen at all.
const line = html.match(/<div[^>]*data-testid="report-never-run"[\s\S]*?<\/div>/)
check(!!line, 'the never-run explanation is not rendered')

// 2. The destination includes the app basename. This is the finding: href="/ops/jobs" is outside /v3.
const anchor = (line && line[0].match(/<a[^>]*href="([^"]+)"[^>]*>\s*Open Ops[^<]*<\/a>/)) || null
check(!!anchor, 'there is no Open Ops link inside the never-run line')
check(!!anchor && anchor[1] === '/v3/ops/jobs',
  `the Open Ops destination is ${anchor ? anchor[1] : '(none)'}; it must include the /v3 basename`)
check(!/<a[^>]*href="\/ops\/jobs"/.test(html), 'a raw root-relative /ops/jobs href is still rendered')

if (failed) { console.error(`reportOpsLink.render: ${failed} failure(s)`); process.exit(1) }
console.log('reportOpsLink.render: ok')
