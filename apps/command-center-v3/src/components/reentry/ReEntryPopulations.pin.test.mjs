// node --experimental-strip-types src/components/reentry/ReEntryPopulations.pin.test.mjs
//
// OBS-B2-4d (lead 11:24 ET; DR-R02): four counts on the re-entry page, four populations. The strings are pinned in
// src/lib/reentryReadiness.test.mjs; THIS file pins the WIRING of those helpers into the three surfaces. It exists
// because a helper can be perfect and still not be called: a mutant that deletes the call, or drops the field that
// makes the count honest (the window basis, the older population, the filter's matching count), leaves every string
// test green and the page showing exactly what it showed before. Each check below names the component edit it kills.
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const src = (p) => readFileSync(join(root, 'src', p), 'utf8')

let failed = 0
function check(ok, msg, detail = '') { if (!ok) { failed += 1; console.error(`FAIL ${msg}${detail ? ` — ${detail}` : ''}`) } }

// ---- 1. the entry-alert lane names both packet populations, in packets and symbols --------------------------------
const lane = src('components/reentry/EntryAlertsLane.tsx')
check(/packetPopulations\(\{\s*count:\s*data\.count,\s*rows,\s*stale:\s*data\.stale,\s*max_age_h:\s*data\.max_age_h,\s*max_age_basis:\s*data\.max_age_basis\s*\}\)/.test(lane),
  'the lane passes the current count, the rows, the older population, the window AND its basis to packetPopulations')
check(!/older than \$\{data\.max_age_h\}h hidden/.test(lane),
  'the bare "N older than Xh hidden" string is gone (it named neither the unit nor the population)')
check(!/\$\{readinessSummary\(counts, rows\.length\)\}\s*\}?/.test(lane.split('const summary')[1].split('return')[0]) ||
  /packetPopulations/.test(lane.split('const summary')[1].split('return')[0]),
  'the collapsed summary carries the population line, not the readiness counts alone')

// ---- 2. the resistance board names its universe rule, clock and filter separately --------------------------------
const board = src('components/reentry/ReEntryResistanceBoard.tsx')
check(/resistancePopulation\(\{\s*symbol_count:\s*payload\.symbol_count,\s*symbols,\s*generated_at:\s*payload\.generated_at,\s*matching:\s*query\.trim\(\)\s*\?\s*rows\.length\s*:\s*null\s*\}\)/.test(board),
  'the board passes its universe size, the payload symbols, its clock and the filter match count to resistancePopulation')
check(!/payload\?\.symbol_count \?\? rows\.length\} symbols/.test(board),
  'the bare "N symbols" header is gone (it fell back to the filtered row count and read as the universe)')
check(/error \? 'resistance universe not available' : 'waiting for the resistance cache'/.test(board),
  'an unfetched cache states its state instead of printing a count')

// ---- 3. the ledger surface names its population and the resistance one beside it --------------------------------
const intel = src('components/reentry/ReEntryCurrentIntelligence.tsx')
check(/populationLegend\(\{[\s\S]{0,400}ledger:\s*\{\s*symbol_count:\s*rows\.length,\s*generated_at:\s*evidence\.generatedAt/.test(intel),
  'the ledger legend counts the rows it shows and dates them by the evidence cache that generated them')
// OBS-B2-4d F1 (-5, 21:34Z): the clock must be the population's. The decision desk stamps computed_at per request,
// so that source dated a 23.9 h-old population with the moment of the read.
check(!/ledger:\s*\{\s*symbol_count:\s*rows\.length,\s*generated_at:\s*unwrap\(reentryDesk\.data\)\?\.computed_at/.test(intel),
  'the ledger legend never dates the exit population with the decision desk read clock')
check(/resistance:\s*\{[\s\S]{0,220}symbol_count:\s*prefValue\(resistancePref\.data\)\?\.symbol_count[\s\S]{0,220}generated_at:\s*prefValue\(resistancePref\.data\)\?\.generated_at/.test(intel),
  'and the resistance population beside it, from the same pref the board reads')
check(/data-testid="reentry-population-legend"/.test(intel), 'the legend is rendered, not merely computed')

// ---- 4. no surface recomputes a financial figure to make its counts agree ---------------------------------------
for (const [name, text] of [['EntryAlertsLane', lane], ['ReEntryResistanceBoard', board]]) {
  check(!/\*\s*100|\.toFixed\(2\)\s*\+|sum\(/.test(text), `${name} does not derive figures to reconcile counts`)
}

if (failed) { console.error(`ReEntryPopulations.pin: ${failed} failure(s)`); process.exit(1) }
console.log('ReEntryPopulations.pin: ok')
