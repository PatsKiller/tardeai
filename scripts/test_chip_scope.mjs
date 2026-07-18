// Defense v4 WS-BOARD acceptance — chip-scope unit test (plain node, runs in npm build).
import { rankWithinScope, boardCallout } from '../apps/command-center-v3/src/lib/chipScope.mjs'
import assert from 'node:assert'

// 1. ranks computed within the rendered scope only
const rows = [
  { name: 'A', value: 10, prevValue: 2 },
  { name: 'B', value: 8, prevValue: 12 },
  { name: 'C', value: -18, prevValue: -25 },
  { name: 'D', value: -20, prevValue: 4 },
]
const ranked = rankWithinScope(rows)
assert.equal(ranked[0].name, 'A')
assert.equal(ranked[0].delta, 2)          // prev scope ranks: B=1, D=2, A=3 → now #1 = ▲2
assert.equal(ranked.find(r => r.name === 'C').prevRank, 4)
console.log('✓ ranks scoped to rendered list')

// 2. a new entrant (no prev value) is flagged, never given a phantom delta
const withNew = rankWithinScope([...rows, { name: 'E', value: 9, prevValue: null }])
const e = withNew.find(r => r.name === 'E')
assert.equal(e.isNew, true)
assert.equal(e.delta, null)
console.log('✓ new-to-list entrant flagged, no phantom delta')

// 3. callout: a deeply negative group climbing ranks is NEVER "strongest rotation" —
//    the improvement line goes to a positive gainer; the breakdown line to the worst loser
const line = boardCallout(ranked, 'M', 'Q')
assert.ok(line.includes('A:'), 'positive climber owns the rotation callout: ' + line)
assert.ok(line.includes('D:') && line.includes('breakdown'), 'worst loser owns the breakdown callout: ' + line)
assert.ok(!line.match(/C:.*strongest rotation/), 'negative climber must not be celebrated')
// D was #2 on prev in scope → the breakdown line names where it came from
assert.ok(line.includes('was #2'), 'prior rank named on the breakdown: ' + line)
console.log('✓ callout: improvement vs deterioration separated correctly')

console.log('ALL CHIP-SCOPE TESTS PASS')
