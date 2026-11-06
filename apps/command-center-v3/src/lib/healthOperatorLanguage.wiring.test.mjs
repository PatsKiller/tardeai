// FQ-035 wiring: the Health page must print the words and keep the raw key reachable.
// The pure function is covered in operatorLanguage.test.ts; this pins the CALL SITE, because a helper nobody
// calls fixes nothing. Plain .mjs on purpose: the app's tsconfig has no Node types, so reading a source file
// from a .ts test fails tsc (the same reason reportCardText.test.mjs is .mjs).
//
//   node --experimental-strip-types src/lib/healthOperatorLanguage.wiring.test.mjs
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const hub = readFileSync(join(HERE, '../pages/HealthHub.tsx'), 'utf8')
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(/componentLabel\(a\.component\)/.test(hub), 'HealthHub does not render the humanised component label')
check(/title=\{a\.component\}/.test(hub), 'HealthHub does not keep the raw component key in the title')
check(!/>\{a\.component\}</.test(hub), 'HealthHub still prints the raw component key on the face')
check(/sentenceIdentifiers\(f\.why\)/.test(hub), 'HealthHub does not humanise the finding why line')
check(/title=\{f\.why \|\| ''\}/.test(hub), 'HealthHub drops the raw why sentence instead of keeping it in the title')

// The WHO row is the one that was spelled out and lost its raw pair (cc-deepseek-5 at 81c5d5f83): the visible
// text became labels and `title` went missing with it, so `health_agent → repair_agent` was no longer recoverable
// anywhere on the page. Every other wording PR tonight kept the raw value in the title; this pins the same rule
// for the row that broke it.
check(/const whoRaw =/.test(hub), 'the WHO row builds no raw detected_by → handled_by pair')
check(/title=\{whoRaw\}/.test(hub), 'the WHO row does not keep its raw pair in the title')

if (failed) { console.error(`healthOperatorLanguage wiring: ${failed} failure(s)`); process.exit(1) }
console.log('healthOperatorLanguage wiring: ok')
