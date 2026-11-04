// node --experimental-strip-types src/lib/vixTile.boundary.test.mjs
//
// FQ-086 boundary: the VIX tile must never colour a number the reading does not certify as current.
import { readFileSync } from 'node:fs'
let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const src = readFileSync(new URL('../components/MetricStrip.tsx', import.meta.url), 'utf8')
const i = src.indexOf("label: 'VIX'")
const j = src.indexOf("label: 'SETUPS", i)
const tile = src.slice(i, j)
check('the tile reads its value from the freshness model', /vixReading\.value/.test(tile))
check('the colour is gated on the reading being current', /!vixReading\.current[^]*text3/.test(tile))
check('the note is the model sentence', /vixReading\.label/.test(tile))
check('the old unconditioned colour rule is gone', !/color: vix == null \? 'var\(--text3\)' : vix >= 25/.test(tile), tile.slice(0, 160))
check('the model is imported, not re-implemented', /import \{ vixFreshness \} from '\.\.\/lib\/vixFreshness'/.test(src))
console.log(`vixTile.boundary: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
