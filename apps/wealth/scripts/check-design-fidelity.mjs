// Design fidelity gate for the v02 port (lead GO 2026-11-14T2313Z: v02 is the specification).
// Fails, never warns:
//  1. src/shell/v02.css, minus its one header comment line, must equal the reference <style> body
//     byte for byte (lines 4-10 of the reference file). Additions belong in a separate stylesheet.
//  2. The reference file in the tree must carry the approved sha256.
//  3. No hex colour literal in src/shell or src/components outside the two reference-locked sheets
//     (v02.css, v04.css) — use var(--token).
//  4. The shell polls nothing: no setInterval / setTimeout / refetchInterval under src/shell.
//  5. Every <table> under src/ sits inside a .table-wrap scroll container. v02 gives table
//     min-width:720px and nowrap cells, so a table with no scroll container widens the whole
//     document at narrow viewports (measured 2026-11-15: 412px viewport, scrollWidth 1731).
//     Parsed as JSX with the TypeScript AST, so formatting cannot fool it.
//  6. src/shell/v04.css, minus its one header comment line, must equal the v04 reference <style> body
//     byte for byte (the approved fidelity target, sha256 1f8f87bb…). The v04 body must also remain a
//     strict superset of the v02 body, rule by rule: that is what lets v04.css load after v02.css
//     without moving a single shared declaration, and the claim is checked rather than assumed.
//  7. The evidence table — the table of PROSE under the caption "Fields with no producer on this
//     read…" — carries the reference's own `matrix` class. v02/v04 already ship
//     `.matrix td{white-space:normal;vertical-align:top;text-align:left}`; without the class the cells
//     inherit the shell's nowrap and the table sets its own 1133 px minimum inside a 992 px wrap at
//     1280 (the live gate that rolled candidate 2 back, 2026-11-15T05:07Z). Measurement does not pin
//     this: a tidy of the className passes every other check, so the class is asserted here, keyed by
//     the caption's text.
//  8. The declared-clock ledger's withheld-datum line is built by `ledgerLine`, and the <dd> under the
//     "Declared clocks" heading CALLS it. The name is resolved through the page's own import binding
//     (an aliased or missing import fails closed, naming what it saw), never trusted by spelling, and
//     the <dd> may not build the sentence inline: cc-deepseek-3's rev-6 verdict (F1) found that deleting
//     the fragment left the shell suite and this gate green. A helper-only test pins the sentence, not
//     the call site — the same shape as the M-B mutant pinned at 815652ac9.
import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import ts from 'typescript'
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const repo = path.resolve(root, '../..')
const REF = 'docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v02.html'
const REF_SHA = '23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa'
const REF4 = 'docs/wealth/design-reference/TradeAI_Wealth_Management_Mockups_v04.html'
const REF4_SHA = '1f8f87bb8db411acfb79eca53fccd4d147de800e7e2782f7d6a7fab817f6f68d'
const fail = []
let v02Body = null
const refPath = path.join(repo, REF)
if (!fs.existsSync(refPath)) fail.push(`reference missing: ${REF}`)
else {
  const buf = fs.readFileSync(refPath)
  const sha = crypto.createHash('sha256').update(buf).digest('hex')
  if (sha !== REF_SHA) fail.push(`reference sha256 ${sha} != approved ${REF_SHA}`)
  const ref = buf.toString('utf8').split('\n')
  const want = ref.slice(3, 10).join('\n')
  v02Body = want
  const css = fs.readFileSync(path.join(root, 'src/shell/v02.css'), 'utf8').split('\n')
  if (!css[0].startsWith('/*')) fail.push('v02.css must start with its one-line header comment')
  const got = css.slice(1).join('\n').replace(/\n$/, '')
  if (got !== want) {
    const a = got.split('\n'), b = want.split('\n')
    const i = a.findIndex((l, k) => l !== b[k])
    fail.push(`v02.css drifted from reference <style> (first differing css line ${i + 2})`)
  }
}
// Rule 6: v04 is the approved fidelity target. Its sheet is the reference's own <style> body (the
// reference has one blank line before </style>; the sheet does not), and it must still contain every
// v02 rule verbatim — the property that makes loading it after v02.css a no-op for shared selectors.
const ref4Path = path.join(repo, REF4)
if (!fs.existsSync(ref4Path)) fail.push(`reference missing: ${REF4}`)
else {
  const buf = fs.readFileSync(ref4Path)
  const sha = crypto.createHash('sha256').update(buf).digest('hex')
  if (sha !== REF4_SHA) fail.push(`v04 reference sha256 ${sha} != approved ${REF4_SHA}`)
  const ref = buf.toString('utf8').split('\n')
  const want = ref.slice(3, 21).join('\n')
  const css = fs.readFileSync(path.join(root, 'src/shell/v04.css'), 'utf8').split('\n')
  if (!css[0].startsWith('/*')) fail.push('v04.css must start with its one-line header comment')
  const got = css.slice(1).join('\n').replace(/\n$/, '')
  if (got !== want) {
    const a = got.split('\n'), b = want.split('\n')
    const i = a.findIndex((l, k) => l !== b[k])
    fail.push(`v04.css drifted from reference <style> (first differing css line ${i + 2})`)
  }
  if (v02Body !== null) {
    const missing = v02Body.split('}').map(r => r.trim()).filter(Boolean).filter(r => !want.includes(r))
    if (missing.length) {
      fail.push(`v04 body is not a superset of v02: ${missing.length} rule(s) absent (first: ${missing[0].slice(0, 80)})`)
    }
  }
}
const walk = (d, out = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p, out) : out.push(p) } return out }
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
for (const dir of ['src/shell', 'src/components']) {
  for (const f of walk(path.join(root, dir))) {
    const rel = path.relative(root, f)
    if (rel === 'src/shell/v02.css' || rel === 'src/shell/v04.css' || !/\.(tsx?|css)$/.test(f)) continue
    const body = strip(fs.readFileSync(f, 'utf8'))
    const hex = body.match(/#[0-9a-fA-F]{3,8}\b/g)
    if (hex) fail.push(`${rel}: hex colour literal ${hex.join(', ')} (use a v02/v04 var(--token))`)
    // Operator Home-v2 mandate explicitly refreshes the lightweight operating header only.
    // All other shell modules retain the no-polling rule; the exception may not originate heavy readers.
    if (dir === 'src/shell' && /\b(setInterval|setTimeout|refetchInterval)\b/.test(body)) {
      if (rel !== 'src/shell/OperatingHeader.tsx') fail.push(`${rel}: shell must not poll or schedule reads`)
      else {
        const reads = [...body.matchAll(/client\.get(?:<[^>]*>)?\(\s*['"]([^'"]+)/g)].map(m => m[1])
        if (reads.length !== 1 || reads[0] !== '/api/v2/wealth/operating-header') fail.push(`${rel}: only the approved lightweight operating-header read may poll`)
        if (!/from:\s*['"]shell['"]/.test(body) || !body.includes('next.pollAfterSeconds*1000')) fail.push(`${rel}: header polling must use the shell reader guard and server session cadence`)
      }
    }
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
// Rule 7: the evidence table is the one table of prose on the page, and it must keep the `matrix`
// class (see the header note). Keyed by the caption text on purpose: if the caption is reworded the
// rule fails rather than silently stopping to pin anything, so the change has to be made deliberately.
const EVIDENCE_CAPTION = 'Fields with no producer on this read'
let evidenceTables = 0
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
      if (open.tagName.getText(sf) === 'table' && node.getText(sf).includes(EVIDENCE_CAPTION)) {
        evidenceTables += 1
        const cls = wrapClassOf(open)
        if (cls === null || !/(^|\s)matrix(\s|$)/.test(cls)) {
          const at = sf.getLineAndCharacterOfPosition(open.getStart(sf)).line + 1
          fail.push(`${path.relative(root, f)}:${at}: the evidence table (caption "${EVIDENCE_CAPTION}…") ` +
            `must carry the reference's \`matrix\` class — without it its prose cells inherit the nowrap ` +
            `shell rule and the table overflows a 992 px wrap at 1280`)
        }
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
if (evidenceTables === 0) {
  fail.push(`rule 7: no table carries the caption "${EVIDENCE_CAPTION}…", so the matrix pin would cover ` +
    `nothing. If the table was renamed or removed, update this rule deliberately rather than dropping it.`)
}
// Rule 8: the withheld-datum ledger line is a call to `ledgerLine`, resolved through the import binding.
const CLOCKS_HEADING = 'Declared clocks'
let clockLedgerPins = 0
for (const f of walk(path.join(root, 'src'))) {
  if (!/\.tsx$/.test(f)) continue
  const rel = path.relative(root, f)
  const sf0 = ts.createSourceFile(f, fs.readFileSync(f, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const lineOf = n => sf0.getLineAndCharacterOfPosition(n.getStart(sf0)).line + 1
  const headings = []
  const findHeadings = node => {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(sf0) === 'h4') {
      const text = node.children.filter(c => ts.isJsxText(c)).map(c => c.getText(sf0)).join('').trim()
      if (text === CLOCKS_HEADING) headings.push(node)
    }
    node.forEachChild(findHeadings)
  }
  findHeadings(sf0)
  if (headings.length === 0) continue
  if (headings.length > 1) {
    fail.push(`${rel}: ${headings.length} "${CLOCKS_HEADING}" headings — rule 8 cannot tell which ledger it pins`)
    continue
  }
  const h4 = headings[0]
  const h4Line = lineOf(h4)
  const siblings = h4.parent.children ?? []
  let dl = null
  for (let k = siblings.indexOf(h4) + 1; k < siblings.length && !dl; k++) {
    const kid = siblings[k]
    if (ts.isJsxElement(kid)) dl = kid.openingElement.tagName.getText(sf0) === 'dl' ? kid : 'blocked'
    else if (ts.isJsxSelfClosingElement(kid)) dl = 'blocked'
  }
  if (dl === null || dl === 'blocked') {
    fail.push(`${rel}:${h4Line}: no <dl> directly follows the "${CLOCKS_HEADING}" heading — rule 8 pins the ` +
      `ledger line there and fails closed rather than pinning nothing`)
    continue
  }
  const dds = []
  const findDds = node => {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(sf0) === 'dd') dds.push(node)
    node.forEachChild(findDds)
  }
  findDds(dl)
  if (dds.length === 0) {
    fail.push(`${rel}:${h4Line}: the "${CLOCKS_HEADING}" <dl> holds no <dd> — rule 8 would pin nothing`)
    continue
  }
  // Counted here, not after the checks: a ledger found but broken must not ALSO report as a missing ledger,
  // which would send the reader looking for a renamed heading that is right there.
  clockLedgerPins += 1
  // Resolve `ledgerLine` through the page's import binding. An alias is refused, not followed: the rule's
  // whole point is that a rename of the call site is a change to review, not a spelling the gate absorbs.
  const importers = []
  let local = null
  for (const st of sf0.statements) {
    if (!ts.isImportDeclaration(st) || !st.importClause?.namedBindings) continue
    const spec = st.moduleSpecifier.getText(sf0).replace(/^['"]|['"]$/g, '')
    if (!/(^|\/)clockLedger(\.ts)?$/.test(spec)) continue
    const bindings = st.importClause.namedBindings
    if (ts.isNamespaceImport(bindings)) {
      fail.push(`${rel}: clockLedger is imported as a namespace (${bindings.name.getText(sf0)}); rule 8 ` +
        `resolves the ledger's binding and cannot follow a namespace member`)
      continue
    }
    for (const el of bindings.elements) {
      if ((el.propertyName ?? el.name).getText(sf0) !== 'ledgerLine') continue
      importers.push(lineOf(el))
      if (el.propertyName) {
        fail.push(`${rel}:${lineOf(el)}: ledgerLine is imported under the alias \`${el.name.getText(sf0)}\`; ` +
          `rule 8 resolves the import binding, so an alias fails closed rather than being guessed at`)
      } else local = el.name.getText(sf0)
    }
  }
  if (importers.length === 0) {
    fail.push(`${rel}: no \`ledgerLine\` import from clockLedger — the "${CLOCKS_HEADING}" ledger line must ` +
      `be built by that function, not by the page`)
    continue
  }
  if (local === null) continue
  for (const dd of dds) {
    const at = lineOf(dd)
    const exprs = dd.children.filter(c => ts.isJsxExpression(c) && c.expression)
    let calls = 0
    for (const e of exprs) {
      const text = e.getText(sf0)
      if (/withheldAsOf/.test(text) || /last stop read/.test(text)) {
        fail.push(`${rel}:${at}: the declared-clock <dd> builds the withheld line inline (reads ` +
          `\`withheldAsOf\` or prints "last stop read"); it must be \`{${local}(…)}\` so both of its ` +
          `conditions stay testable in one place`)
      }
      const countCalls = n => {
        if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.getText(sf0) === local) calls += 1
        n.forEachChild(countCalls)
      }
      countCalls(e.expression)
    }
    if (calls !== 1) {
      fail.push(`${rel}:${at}: the declared-clock <dd> must call \`${local}\` exactly once (found ${calls}) — ` +
        `without the call the withheld datum's line has no test that fails when it is lost (rev-6 F1)`)
    }
  }
}
if (clockLedgerPins === 0) {
  fail.push(`rule 8: no "${CLOCKS_HEADING}" heading with a following <dl> under src/ — the ledger-line pin ` +
    `would cover nothing. If the heading was renamed or removed, update this rule deliberately.`)
}
if (fail.length) { console.error('check-design-fidelity FAIL\n- ' + fail.join('\n- ')); process.exit(1) }
console.log('check-design-fidelity PASS (v02.css == reference <style>, v04.css == reference <style> and a superset of ' +
  'v02, both shas ok, no stray hex, no shell timers, every table in a .table-wrap, the evidence table `matrix`, ' +
  'the declared-clock ledger calls `ledgerLine`)')
