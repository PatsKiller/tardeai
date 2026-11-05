// FQ-112 (PR 2641) — the reviewer's F1: the note's SENTENCE was tested, but whether the page renders it was not.
// Deleting RiskHub's `note:` prop left the old suite green, so this renders the real page with the real component
// tree and asserts the note the operator reads. Mutation-checked: with the `note:` prop removed this file fails.
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
const { MemoryRouter } = require('react-router-dom')

// SSR has no browser globals; the page reads matchMedia at render time.
if (typeof globalThis.window === 'undefined') {
  globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) }
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    .replace(
      /import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__riskFixture',
    )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { default: RiskHub } = await import(compile(join(app, 'src/pages/RiskHub.tsx')))

const AS_OF = '2026-11-04T11:30:03-05:00'
function render(positions) {
  globalThis.__riskFixture = {
    data: { positions, portfolio: {}, stops: {}, regime: {}, approvals: {}, cio_status: {}, capital: {}, do_now: {}, sectors: {} },
    error: null, loading: false, stale: false, transport: 'OK',
  }
  return renderToStaticMarkup(
    React.createElement(MemoryRouter, { initialEntries: ['/risk'] }, React.createElement(RiskHub, { onDrill() {} })),
  )
}

const fails = []
const check = (ok, message) => { if (!ok) fails.push(message) }

// 1. A dated positions snapshot puts the note on screen, in the source-clocks row.
const markup = render({ as_of: AS_OF })
const noteMatch = markup.match(/data-testid="desk-source-note"[^>]*>(.*?)<\/div>/s)
check(Boolean(noteMatch), 'no desk-source-note element is rendered for a dated positions snapshot')
const noteText = (noteMatch?.[1] ?? '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
check(/schwab-position-sync/.test(noteText), `the note never reached the screen: ${JSON.stringify(noteText)}`)
check(/snaptrade-sync/.test(noteText), 'the rendered note does not name the second configured lane')
check(/11:30/.test(noteText), 'the rendered note does not carry the snapshot time')
check(/positions/.test(noteText), 'the rendered note does not say which clock it describes')

// 2. A control: with NO positions clock the page still explains the source, but says the clock is unrecorded
//    instead of inventing or reusing a time.
const blank = render({})
const blankMatch = blank.match(/data-testid="desk-source-note"[^>]*>(.*?)<\/div>/s)
check(Boolean(blankMatch), 'the source row explains itself even with no positions clock')
const blankText = (blankMatch?.[1] ?? '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
check(/no recorded clock/.test(blankText), `an undated snapshot must say the clock is unrecorded: ${JSON.stringify(blankText)}`)
check(!/11:30/.test(blankText), 'an undated snapshot must not carry a time')

if (fails.length) {
  console.error(`riskDeskSourceNote: ${fails.length} failure(s)\n  - ${fails.join('\n  - ')}`)
  process.exit(1)
}
console.log('riskDeskSourceNote: ok — the positions note is rendered by the Risk page, and only when there is a clock')
