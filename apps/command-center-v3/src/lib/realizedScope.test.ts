// node --experimental-strip-types src/lib/realizedScope.test.ts
// Realized tile scope. Synthetic figures only. No node:assert (tsc has no @types/node).
function fail(msg: string): never { throw new Error(msg) }
const assert = {
  equal(a: unknown, b: unknown, m?: string) { if (a !== b) fail(m ?? `expected ${JSON.stringify(a)} === ${JSON.stringify(b)}`) },
}
import { realizedScope, realizedScopeNote } from './realizedScope.ts'

const fmt = (n: number) => `$${n}`

const priced = realizedScope({ priced_realized: 40, realized_pnl: 40, unpriced_count: 3, unpriced_proceeds: 15.5 })
assert.equal(priced.priced, 40, 'priced total is the priced figure')
assert.equal(priced.count, 3)
assert.equal(priced.proceeds, 15.5)
assert.equal(priced.priced, 40, 'unknown-basis proceeds are not added into the priced total')
assert.equal(
  realizedScopeNote(priced, fmt),
  'priced sells only · $15.5 of proceeds have no cost basis',
)

const unknown = realizedScope({ priced_realized: 40, unpriced_count: null, unpriced_proceeds: null })
assert.equal(realizedScopeNote(unknown, fmt), 'priced sells only · unpriced proceeds not reported')

const none = realizedScope({ priced_realized: 40, unpriced_count: 0, unpriced_proceeds: 0 })
assert.equal(realizedScopeNote(none, fmt), 'priced sells only')

const legacy = realizedScope({ realized_pnl: 12, realized_excluded_basis_unknown: { count: 2, proceeds: 9 } })
assert.equal(legacy.priced, 12)
assert.equal(realizedScopeNote(legacy, fmt), 'priced sells only · $9 of proceeds have no cost basis')

const namedUnknownWins = realizedScope({
  realized_pnl: 12,
  unpriced_count: null,
  unpriced_proceeds: null,
  realized_excluded_basis_unknown: { count: 2, proceeds: 9 },
})
assert.equal(realizedScopeNote(namedUnknownWins, fmt), 'priced sells only · unpriced proceeds not reported')

console.log('realizedScope: ok')
