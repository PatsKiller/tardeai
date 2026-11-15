// Design fidelity gate for the v02 port (lead GO 2026-11-14T2313Z: v02 is the specification).
// Fails, never warns:
//  1. src/shell/v02.css, minus its one header comment line, must equal the reference <style> body
//     byte for byte (lines 4-10 of the reference file). Additions belong in a separate stylesheet.
//  2. The reference file in the tree must carry the approved sha256.
//  3. No hex colour literal in src/shell or src/components outside v02.css (use var(--token)).
//  4. The shell polls nothing: no setInterval / setTimeout / refetchInterval under src/shell.
import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
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
if (fail.length) { console.error('check-design-fidelity FAIL\n- ' + fail.join('\n- ')); process.exit(1) }
console.log('check-design-fidelity PASS (v02.css == reference <style>, sha ok, no stray hex, no shell timers)')
