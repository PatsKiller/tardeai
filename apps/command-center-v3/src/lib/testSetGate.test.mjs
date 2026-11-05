// The set gate must fail when a test file is neither run nor dormant — otherwise it is decoration.
//
// cc9's measured block on #2686: the dormant list claimed it "cannot silently drop one either", and it could. Discovery
// walked `src/` only, so a `*.test.*` file anywhere else was in neither list and nothing read the set.
//
// This test is the mutation in permanent form: inject a universe containing a stray test file that is in neither list and
// require `checkSet` to name it. The first case runs the real tree, so the gate is also checked against reality and not
// only against a fixture I wrote to agree with it.
import assert from 'node:assert/strict'
import { checkSet, checkSetAt } from '../../scripts/check-test-set.mjs'

// 1. The real tree: every test file is accounted for, and the accounting is not vacuous.
const real = checkSetAt(new URL('../..', import.meta.url).pathname)
assert.equal(real.uncovered.length, 0, `stray test file(s): ${real.uncovered.join(', ')}`)
assert.equal(real.dangling.length, 0, `dormant entry with no file: ${real.dangling.join(', ')}`)
assert.ok(real.total > 50, `expected the app to contain real test files, found ${real.total}`)
assert.equal(real.covered, real.total, 'covered count must equal the total or the gate is not looking')

// 2. A stray file — in the universe, in neither list — must be reported. This is the mutation.
const universe = ['src/lib/a.test.ts', 'src/lib/b.test.mjs', 'scripts/hidden.test.mjs']
const strayed = checkSet({ run: ['src/lib/a.test.ts'], dormant: ['src/lib/b.test.mjs'], all: universe })
assert.deepEqual(strayed.uncovered, ['scripts/hidden.test.mjs'], 'a test file in neither list must be named')
assert.equal(strayed.covered, 2)

// 3. Adding it to the dormant list clears it — the repair path works.
const repaired = checkSet({
  run: ['src/lib/a.test.ts'],
  dormant: ['src/lib/b.test.mjs', 'scripts/hidden.test.mjs'],
  all: universe,
})
assert.deepEqual(repaired.uncovered, [])
assert.equal(repaired.covered, 3)

// 4. A dormant entry naming a file that no longer exists is also a failure: a list that grows stale stops meaning
//    anything, and a stale entry is how a real test gets quietly removed from the run later.
const stale = checkSet({ run: ['src/lib/a.test.ts'], dormant: ['src/lib/gone.test.ts'], all: ['src/lib/a.test.ts'] })
assert.deepEqual(stale.dangling, ['src/lib/gone.test.ts'], 'a dormant entry with no file must be named')

// 5. THE PREDICATE IS TOTAL (codex's block at c8c346c35). A test file whose extension the runner cannot execute is
//    still a test: `foo.test.cjs` matched neither the old walk (/\.test\.(ts|mjs|js|tsx|jsx)$/) nor the gate, so a
//    failing one exited 0 because nothing ran it and nothing noticed. Any *.test.* extension must be accounted for.
const exotic = ['src/lib/a.test.ts', 'src/lib/c.test.cjs', 'src/lib/d.test.mts']
const withExotic = checkSet({ run: ['src/lib/a.test.ts'], dormant: [], all: exotic })
assert.deepEqual(withExotic.uncovered, ['src/lib/c.test.cjs', 'src/lib/d.test.mts'],
  'an extension the runner cannot execute must still be run-or-dormant, not invisible')
const resolved = checkSet({ run: ['src/lib/a.test.ts'], dormant: ['src/lib/c.test.cjs', 'src/lib/d.test.mts'], all: exotic })
assert.deepEqual(resolved.uncovered, [], 'classifying them clears the gate')

console.log('testSetGate: stray files, stale dormant entries, and unexecutable extensions are all refused')
