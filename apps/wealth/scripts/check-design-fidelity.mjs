// Design fidelity gate for the v02 port (lead GO 2026-11-14T2313Z: v02 is the specification).
// Fails, never warns:
//  1. src/shell/v02.css, minus its one header comment line, must equal the reference <style> body
//     byte for byte (lines 4-10 of the reference file). Additions belong in a separate stylesheet.
//  2. The reference file in the tree must carry the approved sha256.
//  3. No hex colour literal in src/shell or src/components outside v02.css (use var(--token)).
//  4. The shell polls nothing: no setInterval / setTimeout / refetchInterval under src/shell.
//  5. Every <table> under src/ sits inside a .table-wrap scroll container. v02 gives table
//     min-width:720px and nowrap cells, so a table with no scroll container widens the whole
//     document at narrow viewports (measured 2026-11-15: 412px viewport, scrollWidth 1731).
//     Parsed as JSX with the TypeScript AST, so formatting cannot fool it.
import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import ts from 'typescript'
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const repo = path.resolve(root, '../..')
const REF = 'docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v02.html'
const REF_SHA = '23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa'
const fail = []
const refPath = path.join(repo, REF)
if (!fs.existsSync(refPath)) fail.push(`reference missing: ${REF}`)
else {
  const buf = fs.readFileSync(refPath)
  const sha = crypto.createHash('sha256').update(buf).digest('hex')
  if (sha !== REF_SHA) fail.push(`reference sha256 ${sha} != approved ${REF_SHA}`)
  const ref = buf.toString('utf8').split('\n')
  const want = ref.slice(3, 10).join('\n')
  const css = fs.readFileSync(path.join(root, 'src/shell/v02.css'), 'utf8').split('\n')
  if (!css[0].startsWith('/*')) fail.push('v02.css must start with its one-line header comment')
  const got = css.slice(1).join('\n').replace(/\n$/, '')
  if (got !== want) {
    const a = got.split('\n'), b = want.split('\n')
    const i = a.findIndex((l, k) => l !== b[k])
    fail.push(`v02.css drifted from reference <style> (first differing css line ${i + 2})`)
  }
}
const walk = (d, out = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p, out) : out.push(p) } return out }
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
for (const dir of ['src/shell', 'src/components']) {
  for (const f of walk(path.join(root, dir))) {
    const rel = path.relative(root, f)
    if (rel === 'src/shell/v02.css' || !/\.(tsx?|css)$/.test(f)) continue
    const body = strip(fs.readFileSync(f, 'utf8'))
    const hex = body.match(/#[0-9a-fA-F]{3,8}\b/g)
    if (hex) fail.push(`${rel}: hex colour literal ${hex.join(', ')} (use a v02 var(--token))`)
    if (dir === 'src/shell' && /\b(setInterval|setTimeout|refetchInterval)\b/.test(body)) fail.push(`${rel}: shell must not poll or schedule reads`)
  }
}
// Rule 5: a <table> is contained only if a non-table ancestor JSX element carries a literal
// className token `table-wrap` — the class v02 defines as `overflow:auto`. The class on the table
// itself does not count: that is the element whose width is the problem.
const TABLE_PARTS = new Set(['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption'])
const wrapClassOf = open => {
  for (const a of open.attributes?.properties ?? []) {
    if (!ts.isJsxAttribute(a) || a.name.getText() !== 'className' || !a.initializer) continue
    if (ts.isStringLiteral(a.initializer)) return a.initializer.text
    if (ts.isJsxExpression(a.initializer) && a.initializer.expression && ts.isStringLiteral(a.initializer.expression)) {
      return a.initializer.expression.text
    }
  }
  return null
}
const insideWrap = node => {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isJsxElement(p) || ts.isJsxSelfClosingElement(p)) {
      const open = ts.isJsxElement(p) ? p.openingElement : p
      if (TABLE_PARTS.has(open.tagName.getText())) continue
      const cls = wrapClassOf(open)
      if (cls !== null && /(^|\s)table-wrap(\s|$)/.test(cls)) return true
    }
  }
  return false
}
for (const f of walk(path.join(root, 'src'))) {
  if (!/\.tsx$/.test(f)) continue
  const sf = ts.createSourceFile(f, fs.readFileSync(f, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const seen = []
  const visit = node => {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const open = ts.isJsxElement(node) ? node.openingElement : node
      if (open.tagName.getText(sf) === 'table' && !insideWrap(node)) {
        seen.push(sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1)
      }
    }
    node.forEachChild(visit)
  }
  visit(sf)
  for (const line of seen) {
    fail.push(`${path.relative(root, f)}:${line}: <table> is not inside a .table-wrap scroll container ` +
      `(v02 table min-width 720px + nowrap cells would widen the page at narrow viewports)`)
  }
}
if (fail.length) { console.error('check-design-fidelity FAIL\n- ' + fail.join('\n- ')); process.exit(1) }
console.log('check-design-fidelity PASS (v02.css == reference <style>, sha ok, no stray hex, no shell timers, ' +
  'every table in a .table-wrap)')
