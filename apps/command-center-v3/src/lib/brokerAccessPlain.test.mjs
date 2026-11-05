// node --experimental-strip-types src/lib/brokerAccessPlain.test.mjs
//
// FQ-066: the read-access cards printed internal reason codes (DEGRADED_STALE_SOURCE), rc values and readiness field
// identifiers in the normal view. The row must say what the connection is doing and what the operator does next; the
// codes and configuration stay, behind Diagnostics.
import { brokerRowSentence, diagnosticsOf, operatorLogSummary, plainState } from './brokerAccessPlain.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// ---- 1. STATE -> ORDINARY WORDS, plus what it means for the reader ------------------------------------------------
check('OK reads as a plain sentence', plainState('OK').words === 'Working', plainState('OK').words)
check('NEEDS_REAUTH reads as a login that expired', plainState('NEEDS_REAUTH').words === 'Login expired', plainState('NEEDS_REAUTH').words)
check('and says what that costs the operator', /reads stop|will fail|until/i.test(plainState('NEEDS_REAUTH').meaning), plainState('NEEDS_REAUTH').meaning)
// Codex cloud P2 (2026-11-05): NEEDS_REAUTH is emitted for the PROACTIVE renewal window too, when the login still works.
// Calling that "Login expired" and "Reads stop" is a false statement on a screen about credentials.
const renewal = plainState('NEEDS_REAUTH', 'renewal window: 0.5 days to true expiry')
check('a proactive renewal is not called an expired login', renewal.words === 'Renewal due', renewal.words)
check('and does not claim reads have stopped', !/reads stop/i.test(renewal.meaning), renewal.meaning)
check('and says the login still works', /still works|continue/i.test(renewal.meaning), renewal.meaning)
check('a prefixed renewal reason is still a renewal', plainState('NEEDS_REAUTH', 'shares the mariadb login — renewal window: 0.9 days to true expiry').words === 'Renewal due')
check('an expired login is still called expired', plainState('NEEDS_REAUTH', '7-day login expired').words === 'Login expired')
check('a missing token is still called expired', plainState('NEEDS_REAUTH', 'no token on file — a browser login is required').words === 'Login expired')
check('a degraded token is not read as a renewal', plainState('NEEDS_REAUTH', 'token marked degraded: renewal window: 0.5 days to true expiry').words === 'Login expired')
check('a renewal reason on another state changes nothing', plainState('OK', 'renewal window: 0.5 days to true expiry').words === 'Working')
check('the broker row sentence carries the renewal words', brokerRowSentence({ id: 'schwab', label: 'Schwab', state: 'NEEDS_REAUTH', reason: 'renewal window: 0.4 days to true expiry' }).headline.includes('Renewal due'))
check('DEGRADED is never described as healthy', !/healthy|fine|ok/i.test(plainState('DEGRADED').meaning), plainState('DEGRADED').meaning)
check('an unknown state says unknown, not OK', plainState('SOMETHING_NEW').words === 'Unknown state', plainState('SOMETHING_NEW').words)
check('an unknown state is not coloured like success', plainState('SOMETHING_NEW').tone !== 'success')

// ---- 2. THE ROW SENTENCE MUST NOT CARRY THE RAW CODE IN ITS VISIBLE HALF -----------------------------------------
const row = { id: 'schwab', label: 'Schwab positions', state: 'DEGRADED', reason: 'DEGRADED_STALE_SOURCE',
  flags: ['DEGRADED', 'STALE'], operator_log_step: { name: 'read_positions', rc: 3, signals: ['STALE_SOURCE', 'TIMEOUT'] } }
const sentence = brokerRowSentence(row)
check('the visible sentence names the connection', /Schwab positions/.test(sentence.headline), sentence.headline)
check('the visible sentence never prints the raw reason code', !sentence.headline.includes('DEGRADED_STALE_SOURCE'), sentence.headline)
check('nor an rc value', !/rc=|exit \d/.test(sentence.headline), sentence.headline)
check('nor an underscored identifier', !/_/.test(sentence.headline), sentence.headline)
check('it does say the last read did not complete, in words', /did not complete|did not finish|failed/i.test(sentence.headline) && !/exit|rc=/i.test(sentence.headline), sentence.headline)
check('and it points at the next step', sentence.nextStep.length > 0, sentence.nextStep)

// ---- 3. NOTHING IS DESTROYED: every raw field is still reachable for Diagnostics ---------------------------------
const diag = diagnosticsOf(row)
const flat = JSON.stringify(diag)
check('the raw reason survives in diagnostics', flat.includes('DEGRADED_STALE_SOURCE'), flat)
check('the exit code survives in diagnostics', flat.includes('3'), flat)
check('the log step name survives', flat.includes('read_positions'), flat)
check('the signals survive', flat.includes('STALE_SOURCE') && flat.includes('TIMEOUT'), flat)
check('diagnostics is a list of label/value pairs', Array.isArray(diag) && diag.every(d => d.label && d.value !== undefined))

// ---- 4. nothing recorded is said plainly, not implied healthy ----------------------------------------------------
const bare = brokerRowSentence({ id: 'x', label: 'Drive', state: 'STALE', reason: '' })
check('an empty reason does not become an empty sentence', bare.headline.length > 20, bare.headline)
check('a missing log step is not called a failure', !/failed/i.test(bare.headline) || /not recorded|no read/i.test(bare.headline), bare.headline)
check('and diagnostics says the log step is missing', JSON.stringify(diagnosticsOf({ id: 'x', label: 'Drive', state: 'STALE', reason: '' })).match(/not recorded/) !== null)

// ---- 5. THE OPERATOR-LOG SUMMARY NEVER CALLS AN UNRECORDED STEP COMPLETED -----------------------------------------
// The BLOCK at e6aa9b949: two steps with rc null printed "2 step(s) logged; every step completed, 2 without a
// recorded result." Unknown was rendered as completed, contradicting the trailing clause in the same sentence.
const noResult = operatorLogSummary([{ name: 'read_positions', rc: null }, { name: 'read_stops', rc: null }])
check('two unrecorded steps are never called completed', !/every step completed/i.test(noResult), noResult)
check('and the summary says no step recorded a result', /no step recorded a result/i.test(noResult), noResult)
check('the unrecorded count still trails the sentence', /2 without a recorded result/.test(noResult), noResult)
const oneNull = operatorLogSummary([{ name: 'read_positions', rc: null }])
check('a single unrecorded step is not called completed', !/every step completed/i.test(oneNull), oneNull)
check('a single unrecorded step says so', /1 step logged; no step recorded a result/.test(oneNull), oneNull)
const allZero = operatorLogSummary([{ name: 'read_positions', rc: 0 }, { name: 'read_stops', rc: 0 }])
check('every step completed is said only when every exit code is zero', /every step completed/.test(allZero), allZero)
check('and a clean log has no unrecorded trailing clause', !/without a recorded result/.test(allZero), allZero)
const oneBad = operatorLogSummary([{ name: 'read_positions', rc: 1 }, { name: 'read_stops', rc: null }])
check('a non-zero exit is still counted as not complete', /1 did not complete, 1 without a recorded result/.test(oneBad), oneBad)
const mixed = operatorLogSummary([{ name: 'read_positions', rc: 0 }, { name: 'read_stops', rc: null }])
check('a partly recorded log states what completed and what did not record', /1 completed, 1 without a recorded result/.test(mixed), mixed)
check('a partly recorded log never claims every step completed', !/every step completed/i.test(mixed), mixed)
check('an empty log is stated plainly', operatorLogSummary([]) === 'The operator log holds no steps.', operatorLogSummary([]))
check('a missing step list is stated plainly, not as completion', operatorLogSummary(undefined) === 'The operator log holds no steps.', operatorLogSummary(undefined))

console.log(`brokerAccessPlain: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
