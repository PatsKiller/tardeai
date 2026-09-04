// The treemap emitted NaN rect geometry.
//
// /v3 logged 50 console errors on every load — "<rect> attribute width: Expected length,
// NaN" and the same for height, 25 rows x 2 attributes. The inner squarify call passes
// Math.max(0, groupHeight - HEADER), so any group rect shorter than the 13px header
// arrived with height 0; area became 0, every normalised size became 0, and
// thick = sum / along evaluated 0/0.
//
//   node apps/command-center-v3/src/lib/bookTreemapLayout.test.ts
import { squarify } from './bookTreemapLayout.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const items = Array.from({ length: 25 }, (_, i) => ({ size: i + 1, payload: { i } }))
const finite = (rs: any[]) => rs.every(r =>
  Number.isFinite(r.x) && Number.isFinite(r.y) && Number.isFinite(r.w) && Number.isFinite(r.h))

console.log('BookTreemap squarify: geometry is always finite')

// The exact production case: a group thinner than its own header.
check('zero height emits no rects', squarify(items, 0, 0, 560, 0).length === 0)
check('zero width emits no rects', squarify(items, 0, 0, 0, 340).length === 0)
check('negative height emits no rects', squarify(items, 0, 0, 560, -5).length === 0)
check('NaN height emits no rects', squarify(items, 0, 0, 560, NaN).length === 0)
check('Infinity width emits no rects', squarify(items, 0, 0, Infinity, 340).length === 0)

const normal = squarify(items, 0, 0, 560, 340)
check('a normal box still lays out every item', normal.length === items.length)
check('a normal box is entirely finite', finite(normal))
check('a normal box has no negative dimensions', normal.every(r => r.w >= 0 && r.h >= 0))

check('all-zero sizes emit no rects', squarify(items.map(i => ({ ...i, size: 0 })), 0, 0, 560, 340).length === 0)
check('a NaN size is dropped, not laid out',
  finite(squarify([{ size: NaN, payload: {} }, { size: 10, payload: {} }], 0, 0, 100, 100)))
check('an empty item list is fine', squarify([], 0, 0, 560, 340).length === 0)

// A one-pixel-tall strip is the shape that produced the original NaN.
const sliver = squarify(items, 0, 0, 560, 1)
check('a one-pixel strip is finite', finite(sliver))

console.log(`\nBookTreemap squarify: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
