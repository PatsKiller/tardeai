#!/usr/bin/env node
/**
 * Run every app test file, discovered rather than named.
 *
 * Why (2026-11-05): `package.json`'s `build` script carried ONE line with ~100 explicit `node … .test.ts` commands. Four open PRs
 * each appended their own test to that same line, so every merge re-conflicted the other three and every rebase voided the reviews
 * that had just been filed. The registrations are not the problem; naming them on one line is. Discovery removes the shared line
 * from the merge path entirely: a new test file under `src/` runs because it exists, and no PR touches `package.json` to add one.
 *
 * The set that runs is exactly the set that ran before, plus nothing: files that exist but were never in the build chain are listed
 * in `scripts/tests.dormant.json` with a reason, so this runner cannot silently turn a dormant test into a red build — and cannot
 * silently drop one either. Removing an entry from that list is how a dormant test gets wired, deliberately.
 *
 * Usage: node scripts/run-tests.mjs [--list] [--filter <substring>]
 */
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { checkSetAt } from './check-test-set.mjs'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const DORMANT = join(app, 'scripts', 'tests.dormant.json')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, out)
    else if (/\.test\.(ts|mjs)$/.test(name)) out.push(relative(app, full))
  }
  return out
}

function dormant() {
  if (!existsSync(DORMANT)) return {}
  const doc = JSON.parse(readFileSync(DORMANT, 'utf8'))
  return doc.files || {}
}

const args = process.argv.slice(2)
const filterAt = args.indexOf('--filter')
const filter = filterAt >= 0 ? args[filterAt + 1] : null
const listOnly = args.includes('--list')

const skip = dormant()
const discovered = walk(join(app, 'src')).sort()
const run = discovered.filter(f => !(f in skip) && (!filter || f.includes(filter)))
const skipped = discovered.filter(f => f in skip)

if (listOnly) {
  console.log(JSON.stringify({ run, dormant: skipped }, null, 2))
  process.exit(0)
}

// The set gate runs before any suite: a `*.test.*` file that exists but is in neither list is a test nobody runs and
// nobody has decided to skip (cc9's block on #2686 — discovery walked src/ only, so a file elsewhere was invisible).
// Asserting the SET rather than a count is what lets a legitimate new test under src/ pass untouched.
const setResult = checkSetAt(app)
if (setResult.uncovered.length || setResult.dangling.length) {
  for (const f of setResult.uncovered) console.error(`  ✗ not run and not dormant: ${f}`)
  for (const f of setResult.dangling) console.error(`  ✗ dormant entry with no file: ${f}`)
  console.error(`run-tests: test-set gate failed — ${setResult.uncovered.length} uncovered, ${setResult.dangling.length} dangling`)
  process.exit(1)
}

const failures = []
const started = Date.now()
for (const file of run) {
  const proc = spawnSync(process.execPath, ['--experimental-strip-types', file], {
    cwd: app, encoding: 'utf8', timeout: 300_000,
    // A suite whose SSR warnings exceed spawnSync's default 1 MB buffer is KILLED and reported as a failure with
    // status null (jobsScheduler.render emits ~1.5 MB of useLayoutEffect warnings while its assertions pass).
    maxBuffer: 64 * 1024 * 1024,
  })
  if (proc.status !== 0) {
    failures.push({ file, status: proc.status, stderr: (proc.stderr || '').trim().split('\n').slice(-12).join('\n') })
    console.error(`\n✗ ${file}`)
    console.error(proc.stderr || proc.stdout)
  }
}

const elapsed = ((Date.now() - started) / 1000).toFixed(1)
console.log(`run-tests: ${run.length} file(s) run, ${skipped.length} dormant, ${failures.length} failed in ${elapsed}s`)
if (failures.length) {
  for (const f of failures) console.error(`  FAILED ${f.file} (exit ${f.status})`)
  process.exit(1)
}
