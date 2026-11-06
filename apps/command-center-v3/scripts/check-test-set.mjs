#!/usr/bin/env node
/**
 * Every test file in this app is either RUN or EXPLICITLY DORMANT — and nothing else.
 *
 * Why (2026-11-05, cc9's measured block on #2686): run-tests.mjs states that the dormant list "cannot silently turn a
 * dormant test into a red build — and cannot silently drop one either." The second half was false. Discovery walked
 * `src/` only, so a `*.test.*` file created anywhere else in the app was in neither list: never run, never dormant,
 * and no gate read the set. Marking a live test dormant also silently removed it from the run with nothing to notice.
 *
 * This asserts the SET, not a count. A legitimate new test under `src/` is discovered automatically and passes. A test
 * file that exists but is in neither list fails, whatever its location in the app. Dormant entries naming a file that
 * no longer exists also fail, because a list that grows stale stops meaning anything.
 *
 * Exit 0 when the set is exactly covered; exit 1 with one line per uncovered or dangling path.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Directories that are not source: dependencies, build output, and the e2e suite, which Playwright owns and the
// node runner has never executed. Listed explicitly so a new sibling directory is discovered rather than ignored.
const SKIP_DIRS = new Set(['node_modules', 'dist', 'build', '.vite', 'coverage', 'e2e', 'e2e-live'])

// THE PREDICATE, stated once and total (codex's block at c8c346c35, 2026-11-05):
//   a file IS a test iff its name matches /\.test\.[^.]+$/ — ANY extension, ANY directory.
//   the runner EXECUTES only /\.test\.(ts|mjs|cjs|js|tsx|jsx)$/ under src/.
// The gap between those two sets is the defect this gate exists to close. It used to match only the five executable
// extensions, so `foo.test.cjs` (or .cts/.mts) was invisible to the walker AND to the gate: a failing one exited 0
// because nothing ever ran and nothing ever noticed. Now every *.test.* file must be run or explicitly dormant, and a
// file the runner cannot execute is a build failure until someone decides about it.
// `cjs` was added here (2026-11-05, PR #2643 merge) so a CommonJS suite an open PR ships
// (`portfolioProspectusTruth.view.test.cjs`, 63 rendered checks) is actually executed instead of failing the set gate;
// it was already named explicitly in that PR's build line before main replaced the line with this runner.
export const ANY_TEST = /\.test\.[^.]+$/
export const RUNNABLE = /\.test\.(ts|mjs|cjs|js|tsx|jsx)$/

function walk(dir, out = [], base = app, predicate = ANY_TEST) {
  // R3 (codex): an unreadable directory is an ERROR, never an empty set. `catch { return out }` made a permission
  // failure look like "no tests here" — the same silence-is-a-pass class that shipped the PII binary-skip bug. A
  // check that cannot read a thing must never report it clean.
  let entries
  try {
    entries = readdirSync(dir)
  } catch (err) {
    throw new Error(`check-test-set: cannot read directory ${dir} (${err.code || err.message}) — an unreadable inventory is not an empty one`)
  }
  for (const name of entries) {
    if (SKIP_DIRS.has(name)) continue
    const full = join(dir, name)
    let st
    try {
      st = statSync(full)
    } catch (err) {
      throw new Error(`check-test-set: cannot stat ${full} (${err.code || err.message}) — refusing to skip an entry it cannot read`)
    }
    if (st.isDirectory()) walk(full, out, base, predicate)
    else if (predicate.test(name)) out.push(relative(base, full))
  }
  return out
}

/** R2 (codex): a dormant entry must carry BOTH a reason and an explicit attribution. A bare string is a default,
 *  not a decision — moving an ACTIVE test into dormant is how a running test stops running without anyone noticing
 *  it. `justified_by` is the thing a reviewer has to add; it cannot be inferred, and the gate refuses without it. */
export function loadDormant(doc) {
  const files = (doc && doc.files) || {}
  const paths = []
  const unjustified = []
  for (const [path, entry] of Object.entries(files)) {
    paths.push(path)
    const reason = typeof entry === 'string' ? entry : entry && entry.reason
    const by = entry && typeof entry === 'object' ? entry.justified_by : undefined
    if (!reason || !by) unjustified.push(path)
  }
  return { paths, unjustified }
}

// R2, second half (cc9's measured block at 3d54f8d4d): reason + justified_by is a comment, not an authorization.
// An author who copies the object shape can move a LIVE test to dormant in one file and the build stays green —
// measured at fbd798c8c: accountLabels.test.ts (running a minute earlier) declared dormant with both fields ->
// "107 file(s) run, 14 dormant, 0 failed", rc 0. So the SET of dormant paths is pinned in a second, checked file.
// A path not in that baseline is unauthorized and fails, whatever its justification text says. Authorizing a new
// dormant test is then a deliberate two-file diff a reviewer sees, not a default.
const BASELINE = join('scripts', 'tests.dormant.baseline.json')

/** The authorized dormant set. Missing/unreadable baseline is an ERROR (fail closed, R3's rule): silence here
 *  would re-authorize every dormant entry by default, which is the defect this file exists to prevent. */
export function loadBaseline(root) {
  const baselinePath = join(root || app, BASELINE)
  if (!existsSync(baselinePath)) {
    throw new Error(`check-test-set: missing dormant baseline ${baselinePath} — a dormant entry is authorized only by this file`)
  }
  let doc
  try {
    doc = JSON.parse(readFileSync(baselinePath, 'utf8'))
  } catch (err) {
    throw new Error(`check-test-set: cannot read dormant baseline ${baselinePath} (${err.code || err.message}) — refusing to authorize anything`)
  }
  const files = doc && doc.files
  if (!Array.isArray(files)) {
    throw new Error(`check-test-set: dormant baseline ${baselinePath} has no "files" array — refusing to authorize anything`)
  }
  return files.map(f => f.split('\\').join('/'))
}

/** Dormant paths not pinned in the baseline: a new dormant entry fails by default. */
export function checkAuthorized(dormant, baseline) {
  const allowed = new Set(baseline)
  const unauthorized = dormant.filter(f => !allowed.has(f)).sort()
  return { unauthorized }
}

/** The runner's own two lists: what it executes, and what the dormant file explains. */
export function runnerLists() {
  const dormantPath = join(app, 'scripts', 'tests.dormant.json')
  const doc = existsSync(dormantPath) ? JSON.parse(readFileSync(dormantPath, 'utf8')) : {}
  const { paths: dormant, unjustified } = loadDormant(doc)
  const listFile = join(app, 'scripts', 'run-tests.mjs')
  // Executed = what the runner actually runs: under src/, an extension it can execute, minus the dormant set.
  const srcDir = join(app, 'src')
  const discovered = walk(srcDir, [], app, RUNNABLE).map(p => p.split('\\').join('/'))
  const dormantSet = new Set(dormant)
  const run = discovered.filter(f => !dormantSet.has(f))
  const { unauthorized } = checkAuthorized(dormant, loadBaseline(app))
  return { run, dormant, discovered, listFile, dormantPath, unauthorized }
}

export function checkSet({ run, dormant, all }) {
  const covered = new Set([...run, ...dormant])
  const uncovered = all.filter(f => !covered.has(f)).sort()
  const dangling = [...dormant].filter(f => !all.includes(f)).sort()
  return { uncovered, dangling, total: all.length, covered: all.filter(f => covered.has(f)).length }
}

export function checkSetAt(root) {
  const dormantPath = join(root, 'scripts', 'tests.dormant.json')
  const doc = existsSync(dormantPath) ? JSON.parse(readFileSync(dormantPath, 'utf8')) : {}
  const { paths: dormant, unjustified } = loadDormant(doc)
  const srcDir = join(root, 'src')
  // run = what the runner can actually execute; all = every file that IS a test by the total predicate above.
  const discovered = walk(srcDir, [], root, RUNNABLE).map(p => p.split('\\').join('/'))
  const dormantSet = new Set(dormant)
  const run = discovered.filter(f => !dormantSet.has(f))
  const all = walk(root, [], root, ANY_TEST).map(p => p.split('\\').join('/'))
  const { unauthorized } = checkAuthorized(dormant, loadBaseline(root))
  return { ...checkSet({ run, dormant, all }), unjustified, unauthorized }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isMain) {
  const result = checkSetAt(app)
  if (result.uncovered.length) {
    console.error('check-test-set: test file(s) neither run nor dormant:')
    for (const f of result.uncovered) console.error(`  ✗ ${f}`)
  }
  if (result.dangling.length) {
    console.error('check-test-set: dormant entry names a file that does not exist:')
    for (const f of result.dangling) console.error(`  ✗ ${f}`)
  }
  for (const f of result.unjustified || []) {
    console.error(`  \u2717 dormant without justification (needs reason + justified_by): ${f}`)
  }
  for (const f of result.unauthorized || []) {
    console.error(`  \u2717 dormant but not authorized by scripts/tests.dormant.baseline.json: ${f}`)
  }
  if (result.uncovered.length || result.dangling.length || (result.unjustified || []).length || (result.unauthorized || []).length) {
    console.error('check-test-set: add the file to src/ so the runner discovers it, or list it in scripts/tests.dormant.json with BOTH a reason and a justified_by attribution \u2014 and authorize it in scripts/tests.dormant.baseline.json. A new dormant entry fails by default.')
    process.exit(1)
  }
  console.log(`check-test-set: ${result.covered}/${result.total} test file(s) accounted for (run or dormant)`)
}
