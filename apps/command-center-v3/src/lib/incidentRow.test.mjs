// node --experimental-strip-types src/lib/incidentRow.test.mjs
//
// FQ-045 / FQ-046. The titles below are COPIED FROM THE AUDIT'S OWN PHONE CAPTURE
// (audit/page-audit-20261104T0011Z/pass3-inspection/ops_incidents-phone390-y1300.png), so the test fails if the page
// stops handling the strings that were actually reported, not a tidy version of them.
import { nextActionOf, plainTitle, plainWords, priorityOf, rowModel } from './incidentRow.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const CAPTURED = [
  'lane coverage-stall unhealthy: research_up_thesis_flat:deepseek_ok, 24h=58,thesis_sustained=11,canary_coverage=20',
  'lane drive-sync unhealthy: DEGRADED_STALE_SOURCE',
  'test_run_discovery_shadow: first fails locally: reads live_industry_novelty_coming instead of an isolated default',
  'main red: test_agents_25_10_exclusions_still_name_these_classes_and_blocks_after_AGENTS_md_25_0_0 (#2236) renamed the 25.10 heading',
  'expected service off: DISABLED:tradeai-iris-taxonomy-timer',
  'expected service off: MISSING:tradeai-phone-status-service',
  'health tick step pipeline-watchdog broken (rc=1)',
  'Anthropic credit cap hit: CREDIT_PROCESS_CAP x7 in 60 min',
  'Disk at99.7percent used; approved cleanup remains unapplied',
]

const tokens = (s) => new Set(String(s).toLowerCase().match(/[a-z0-9]+/g) ?? [])

// ---- 1. NO WORD IS DROPPED: every token of the ledger title survives in the headline or in the lifted detail -------
for (const t of CAPTURED) {
  const { headline, rawDetail } = plainTitle(t)
  const have = tokens(`${headline} ${rawDetail ?? ''}`)
  const missing = [...tokens(t)].filter(w => !have.has(w))
  check(`nothing invented, nothing dropped: ${t.slice(0, 46)}…`, missing.length === 0, missing.join(','))
}

// ---- 2. THE IDENTIFIER NOISE IS GONE FROM THE ROW --------------------------------------------------------------
check('an underscore lane name is spelled out', !plainTitle(CAPTURED[0]).headline.includes('_'))
check('it reads as a sentence', /^Lane coverage-stall unhealthy: research up thesis flat/.test(plainTitle(CAPTURED[0]).headline), plainTitle(CAPTURED[0]).headline)
// the lifted detail stays VERBATIM: it is what the operator would paste into a terminal
check('the measurement tail is lifted, not deleted', plainTitle(CAPTURED[0]).rawDetail === '24h=58, thesis_sustained=11, canary_coverage=20', plainTitle(CAPTURED[0]).rawDetail)
check('an ALL_CAPS code is spelled out', plainTitle(CAPTURED[1]).headline === 'Lane drive-sync unhealthy: degraded stale source', plainTitle(CAPTURED[1]).headline)
check('a test path is spelled out', !/_/.test(plainTitle(CAPTURED[2]).headline), plainTitle(CAPTURED[2]).headline)
check('a raw parenthetical leaves the sentence', plainTitle(CAPTURED[6]).headline === 'Health tick step pipeline-watchdog broken', plainTitle(CAPTURED[6]).headline)
check('but is kept for the detail', plainTitle(CAPTURED[6]).rawDetail === 'rc=1', plainTitle(CAPTURED[6]).rawDetail)
check('a service marker becomes a word', /disabled — tradeai-iris-taxonomy-timer/.test(plainTitle(CAPTURED[4]).headline), plainTitle(CAPTURED[4]).headline)

// ---- 3. A TITLE THAT ALREADY SPEAKS ENGLISH IS NOT "TRANSLATED" --------------------------------------------------
const PLAIN = 'Native PR approval callback lacks synchronous head verification'
const p = plainTitle(PLAIN)
check('a plain title is returned untouched', p.headline === PLAIN, p.headline)
check('and is not duplicated into a raw copy', p.raw === null && p.rawDetail === null)

// ---- 4. THE RAW TITLE IS KEPT WHENEVER SOMETHING CHANGED ---------------------------------------------------------
const changedTitle = plainTitle(CAPTURED[1])
check('the ledger title is preserved verbatim for the detail', changedTitle.raw === CAPTURED[1], changedTitle.raw)

// ---- 5. PRIORITY IS THE LEDGER'S OWN CODE, NOT A GLOSS ------------------------------------------------------------
check('P1 is the highest tone', priorityOf({ severity: 'P1' }).tone === 'danger')
check('P2 is the warning tone', priorityOf({ severity: 'P2' }).code === 'P2' && priorityOf({ severity: 'P2' }).tone === 'warning')
check('an unrecorded priority says so', priorityOf({}).code === 'Not recorded' && priorityOf({}).tone === 'neutral')

// ---- 6. NEXT ACTION IS DERIVED FROM FIELDS ------------------------------------------------------------------------
const base = { schema: 'IncidentRecord@v1', id: 'X', opened_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
  source: { kind: 'watcher', watcher: 'lane_health' }, title: 't', evidence: [], attempts: [], fix_refs: [] }
check('a blocked incident quotes its own handoff',
  nextActionOf({ ...base, status: 'blocked', handoff: 'restart the lane' }) === 'Needs a person. Next: restart the lane')
check('a blocked incident with no handoff says there is none',
  nextActionOf({ ...base, status: 'blocked' }) === 'Needs a person, and no next step is recorded.')
check('an open incident names an owner when it has one',
  nextActionOf({ ...base, status: 'open', owner: 'cc-deepseek-4' }) === 'Nobody is working on it yet. Owner: cc-deepseek-4.')
check('a fixing incident says who is on it', nextActionOf({ ...base, status: 'fixing', owner: 'a3f' }) === 'Being fixed. Owner: a3f.')
check('a closed incident says why', nextActionOf({ ...base, status: 'closed', resolution: 'not_reproducible' }) === "Closed as won't fix — not reproducible.")
const unknown = nextActionOf({ ...base, status: 'quarantined' })
check('an unknown status is reported as unknown, not as someone else\'s meaning', /does not know \(quarantined\)/.test(unknown), unknown)

// ---- 7. THE ROW MODEL ---------------------------------------------------------------------------------------------
const row = rowModel({ ...base, status: 'blocked', severity: 'P1', title: CAPTURED[1], handoff: 're-auth the drive lane' },
  { age: '5 d 4 h', source: 'watcher · lane_health' })
check('the row carries a plain headline', row.headline === 'Lane drive-sync unhealthy: degraded stale source', row.headline)
check('the row carries the priority', row.priority.code === 'P1')
check('the row carries the next action', row.nextAction === 'Needs a person. Next: re-auth the drive lane', row.nextAction)
check('the row meta has no identifier underscores', !row.meta.includes('_'), row.meta)


// ---- cx-openai-4's two findings at 52e815c12 (R1 qualification, R2 phone age) -------------------------------------
const QUAL = plainTitle('Data service healthy (NOT VERIFIED)')
check('R1: a qualification stays in the sentence', /NOT VERIFIED/.test(QUAL.headline), QUAL.headline)
check('R1: and is not treated as machine detail', !/NOT VERIFIED/.test(QUAL.rawDetail ?? ''), String(QUAL.rawDetail))
const UNV = plainTitle('Feed reachable (UNVERIFIED)')
check('R1: UNVERIFIED is a qualification too', /UNVERIFIED/.test(UNV.headline), UNV.headline)
check('R1: an assignment in brackets still moves to the detail', (plainTitle('Disk check ran (rc=1)').rawDetail ?? '') === 'rc=1')
const compactRow = rowModel({ ...base, status: 'open', title: 't' }, { age: '1 h 30 min', source: 'watcher · lane_health' })
check('R2: the row model carries the age on its own', compactRow.age === '1 h 30 min', compactRow.age)

// the phone branch of the page must render the age, not drop the whole meta line
import { readFileSync } from 'node:fs'
const pageSrc = readFileSync(new URL('../pages/OpsIncidents.tsx', import.meta.url), 'utf8')
check('R2: the phone branch renders the age', /sheet\.mobile[\s\S]{0,120}m\.age/.test(pageSrc), 'no m.age in the mobile branch')

console.log(`incidentRow: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
