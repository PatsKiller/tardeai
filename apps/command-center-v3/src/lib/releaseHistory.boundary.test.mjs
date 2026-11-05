// node --experimental-strip-types src/lib/releaseHistory.boundary.test.mjs
//
// FQ-069 + FQ-070 boundary: a release card must read at phone width, must never print the served SHA, the SHA basis, the
// receipt or the raw verify reason on the reading line, and must keep all of them inside its diagnostics disclosure.
//
// This test RENDERS the card. It used to grep the page's source, and the cloud review of 2026-11-05 (P1) proved what that
// was worth: against an entirely commented-out copy of the page the old file still reported 8 passed, because a comment
// holds the same strings as code. Every assertion below reads markup produced by react-dom/server from the real component.
//
// Hermetic: no network, no server, synthetic rows only.
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

// Compiled modules go to real files, never data: URLs: a data: URL re-encodes the whole import graph at every level and
// turns one React warning into a megabyte-long log line in the CI shard.
const memo = new Map()
const moduleDir = mkdtempSync(join(tmpdir(), 'release-history-card-'))
process.on('exit', () => { try { rmSync(moduleDir, { recursive: true, force: true }) } catch {} })
let seq = 0

function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, removeComments: true },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    const base = resolve(dirname(path), spec)
    let target = [base, `${base}.ts`, `${base}.tsx`, `${base}.js`, `${base}.mjs`].find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (statSync(target).isDirectory()) target = ['.ts', '.tsx', '.js'].map(s => join(target, `index${s}`)).find(existsSync)
    return `from ${JSON.stringify(compile(target))}`
  })
  const file = join(moduleDir, `m-${seq++}.mjs`)
  writeFileSync(file, js)
  const url = pathToFileURL(file).href
  memo.set(path, url)
  return url
}

const { ReleaseHistoryCard } = await import(compile(resolve(app, 'src/lib/releaseHistoryCard.tsx')))

let pass = 0, fail = 0
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) }
}
const render = row => renderToStaticMarkup(React.createElement(ReleaseHistoryCard, { r: row, when: 'Nov 4 05:00 ET' }))

// A row whose every secret-looking field is distinctive, so "is it on the card" is answerable by substring.
const base = {
  receipt: 'receipt-9f2c1b', mode: 'promote', at: '2026-11-04T10:00:00Z', sha: 'abcdef1234567890abcdef1234567890abcdef12',
  short_sha: 'abcdef123456', sha_basis: 'pinned-import', release_name: 'Release Forty Eight', serving: false,
  prs: [2601, 2602], prs_reason: null, verify: { ok: true, health: 'ok', rolled_back: false, readback_errors: [] },
  verify_reason: 'readback matched',
}
const okRow = { ...base }
const failedRow = { ...base, verify: { ok: false, health: 'bad', rolled_back: false, readback_errors: [] }, verify_reason: 'readback mismatch on /health' }
const rollbackRow = { ...base, mode: 'rollback', verify: { ok: true, health: 'ok', rolled_back: true, readback_errors: [] }, verify_reason: null }

const okHtml = render(okRow)
const failedHtml = render(failedRow)
const rollbackHtml = render(rollbackRow)

// ── it renders at all, and from the row it was given ────────────────────────────────────────────────────────────────
check('the card renders markup', okHtml.length > 0)
check('the release name is on the card', okHtml.includes('Release Forty Eight'), okHtml.slice(0, 160))
check('a different row renders different words', render({ ...okRow, release_name: 'Another Release' }).includes('Another Release'))
check('the verdict is a label from the structured kind', okHtml.includes('VERIFIED') && failedHtml.includes('NOT VERIFIED'))
check('the PRs are named', okHtml.includes('PR 2601') && okHtml.includes('PR 2602'))

// ── the disclosure is the only place the raw identifiers may appear ──────────────────────────────────────────────────
const split = html => { const i = html.indexOf('<details'); return i < 0 ? [html, ''] : [html.slice(0, i), html.slice(i)] }
const [visible, hidden] = split(failedHtml)
for (const [label, needle] of [
  ['served SHA', 'abcdef1234567890abcdef1234567890abcdef12'],
  ['short SHA', 'abcdef123456'],
  ['SHA basis', 'pinned-import'],
  ['receipt', 'receipt-9f2c1b'],
]) {
  check(`${label} is not on the reading line`, !visible.includes(needle))
  check(`${label} is inside Diagnostics`, hidden.includes(needle))
}
check('the card has a Diagnostics disclosure', failedHtml.includes('rs-release-diagnostics') && failedHtml.includes('Diagnostics'))

// ── a failed release says why, and does not read as fine ─────────────────────────────────────────────────────────────
check('a failed release names its reason', visible.includes('readback mismatch on /health'))
check('a failed release is not called verified', !visible.includes('>VERIFIED<') && visible.includes('NOT VERIFIED'))
check('a rollback is labelled ROLLBACK', rollbackHtml.includes('ROLLBACK'))

// ── the page must render THIS card: a rendering test proves nothing if the page stops using the component ────────────
const pageSrc = readFileSync(new URL('../pages/ReleasesSchedules.tsx', import.meta.url), 'utf8')
check('the page imports and renders the card this test renders',
  /import \{ ReleaseHistoryCard \} from '\.\.\/lib\/releaseHistoryCard'/.test(pageSrc) && /<ReleaseHistoryCard\b/.test(pageSrc))

// ── width: the card's own content may not be nowrap (819 px on a 390 px phone was the original defect) ──────────────
// The ONE allowed exception is the verdict pill: a two-word label is meant to stay on one line, and the design-token Chip
// owns that. Everything else — the purpose, the when line, the blocker, the next action, every diagnostic value — wraps.
const nowrapOccurrences = (okHtml.match(/nowrap/gi) ?? []).length
const nowrapPill = (okHtml.match(/<span[^>]*white-space:nowrap[^>]*>[^<]*<\/span>/) ?? [''])[0]
check('the only nowrap is the verdict pill, and it wraps the verdict label', nowrapOccurrences === 1 && nowrapPill.includes('VERIFIED'),
  `${nowrapOccurrences} occurrence(s); pill=${nowrapPill.slice(0, 120)}`)
check('the card is not a table', !/<table/i.test(okHtml) && !/<tr/i.test(okHtml))

console.log(`releaseHistory.boundary: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
