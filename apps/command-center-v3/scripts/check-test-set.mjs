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
const TEST_FILE = /\.test\.(ts|mjs|js|tsx|jsx)$/

function walk(dir, out = [], base = app) {
  let entries
  try { entries = readdirSync(dir) } catch { return out }
  for (const name of entries) {
    if (SKIP_DIRS.has(name)) continue
    const full = join(dir, name)
    let st
    try { st = statSync(full) } catch { continue }
    if (st.isDirectory()) walk(full, out, base)
    else if (TEST_FILE.test(name)) out.push(relative(base, full))
  }
  return out
}

/** The runner's own two lists: what it executes, and what the dormant file explains. */
export function runnerLists() {
  const dormantPath = join(app, 'scripts', 'tests.dormant.json')
  const doc = existsSync(dormantPath) ? JSON.parse(readFileSync(dormantPath, 'utf8')) : {}
  const dormant = Object.keys(doc.files || {})
  const listFile = join(app, 'scripts', 'run-tests.mjs')
  // Executed = what the runner discovers under src/ minus the dormant set. Importing run-tests.mjs would run it, so the
  // same two rules are applied here; if the runner's discovery changes, this must change with it (the test pins both).
  const srcDir = join(app, 'src')
  const discovered = walk(srcDir).map(p => p.split('\\').join('/'))
  const dormantSet = new Set(dormant)
  const run = discovered.filter(f => !dormantSet.has(f))
  return { run, dormant, discovered, listFile, dormantPath }
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
  const dormant = Object.keys(doc.files || {})
  const srcDir = join(root, 'src')
  const discovered = walk(srcDir, [], root).map(p => p.split('\\').join('/'))
  const dormantSet = new Set(dormant)
  const run = discovered.filter(f => !dormantSet.has(f))
  const all = walk(root, [], root).map(p => p.split('\\').join('/'))
  return checkSet({ run, dormant, all })
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
  if (result.uncovered.length || result.dangling.length) {
    console.error('check-test-set: add the file to src/ so the runner discovers it, or list it in scripts/tests.dormant.json with a reason.')
    process.exit(1)
  }
  console.log(`check-test-set: ${result.covered}/${result.total} test file(s) accounted for (run or dormant)`)
}
