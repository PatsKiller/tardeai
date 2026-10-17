// Pure-logic tests for stepUp.ts. Runnable with Node type-stripping:
//   node --experimental-strip-types apps/command-center-v3/src/lib/stepUp.test.ts
import { stepUpChallenge, sanitizeCode, codeComplete, submitStepUp, STEP_UP_ENDPOINT } from './stepUp.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const active = { ok: false, auth: 'step_up', step_up_action: 'schwab_reauth', error: 'step-up required — enter your authenticator code',
  step_up: { available: true, endpoint: STEP_UP_ENDPOINT } }
const disabled = { ok: false, auth: 'step_up', step_up_action: 'schwab_reauth', error: 'step-up required — TOTP unlock not yet enabled' }

check('active challenge recognised', stepUpChallenge(403, active)?.action === 'schwab_reauth')
check('disabled refusal is NOT a prompt (no step_up key)', stepUpChallenge(403, disabled) === null)
check('service listener refusal is NOT a prompt', stepUpChallenge(403, { ...active, step_up: { available: false } }) === null)
check('non-403 ignored', stepUpChallenge(401, active) === null && stepUpChallenge(200, active) === null)
check('csrf refusal ignored', stepUpChallenge(403, { ...active, auth: 'csrf' }) === null)
check('foreign endpoint never followed', stepUpChallenge(403, { ...active, step_up: { available: true, endpoint: 'https://evil.example/x' } })?.endpoint === STEP_UP_ENDPOINT)
check('sanitize keeps 6 digits', sanitizeCode(' 12a3-45 678') === '123456')
check('complete only at 6 digits', codeComplete('123456') && !codeComplete('12345') && !codeComplete('12345a'))

const calls: any[] = []
const fakeFetch = (async (url: string, init: any) => {
  calls.push([url, JSON.parse(init.body)])
  return { ok: true, status: 200, json: async () => ({ ok: true, unlocked_until: 123 }) }
}) as any
const res = await submitStepUp({ action: 'schwab_reauth', endpoint: STEP_UP_ENDPOINT }, '123456', fakeFetch)
check('submit posts action + code to the endpoint', res.ok && calls[0][0] === STEP_UP_ENDPOINT && calls[0][1].code === '123456' && calls[0][1].action === 'schwab_reauth')
const short = await submitStepUp({ action: 'schwab_reauth', endpoint: STEP_UP_ENDPOINT }, '123', fakeFetch)
check('short code never sent', !short.ok && calls.length === 1)
const badFetch = (async () => ({ ok: false, status: 429, json: async () => ({ ok: false, error: 'locked', locked_until: 9 }) })) as any
const bad = await submitStepUp({ action: 'schwab_reauth', endpoint: STEP_UP_ENDPOINT }, '654321', badFetch)
check('lockout surfaced', !bad.ok && bad.error === 'locked' && bad.locked_until === 9)

console.log(`stepUp: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
