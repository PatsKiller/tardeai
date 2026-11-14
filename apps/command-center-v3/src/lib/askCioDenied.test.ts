// Ask the CIO / My questions — the refusal model (campaign Home item 6). Pure; runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/askCioDenied.test.ts
//
// The claim: a 401/403 names WHAT refused it. The code is the server's own, or none at all — the model never invents
// one from the status. A generic error is not a denial. The recovery sentence describes an operator action, not a poll.
import { askDenialView, refusalLabel, ASK_REFUSAL_TEXT } from './askCioDenied.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ── a refusal is a denial; an ordinary error is not ──────────────────────────
{
  for (const auth of ['OK', null, undefined] as const) {
    const v = askDenialView({ authState: auth, errorCode: 'AGENT_CALLER_REFUSED', error: 'server error (HTTP 500) — retrying' })
    check(`${String(auth)} is not a denial, even with a code present`, v.denied === false)
    check(`${String(auth)} keeps no code on a non-denial`, v.code === null)
    check(`${String(auth)} has no HTTP status on a non-denial`, v.httpStatus === null)
  }
  check('null input is not a denial', askDenialView(null).denied === false)
}

// ── 403: the server's code and sentence, never a guessed one ─────────────────
{
  const v = askDenialView({ authState: 'FORBIDDEN', errorCode: 'AGENT_CALLER_REFUSED', errorDetail: 'Ask the CIO answers only the operator’s tailnet identity', error: 'forbidden — …' })
  check('403 is a denial', v.denied === true)
  check('403 reports HTTP 403', v.httpStatus === 403)
  check('the server code is kept', v.code === 'AGENT_CALLER_REFUSED')
  check('the server sentence beats the default', v.detail === 'Ask the CIO answers only the operator’s tailnet identity')
  check('the label is the typed code, not the status', refusalLabel(v) === 'AGENT_CALLER_REFUSED')
  check('polling stopped is said', /Polling stopped/.test(v.recovery))
  check('the retry is an operator button', v.retryLabel === 'Try again')

  const bare = askDenialView({ authState: 'FORBIDDEN' })
  check('a body with no code leaves code null (never invented)', bare.code === null)
  check('a code-less refusal is labelled by its HTTP status', refusalLabel(bare) === 'HTTP 403')
  check('a code-less refusal still says the server refused', /refused/.test(bare.detail))
  check('a code-less refusal still has a recovery', bare.recovery.length > 0)

  const known = askDenialView({ authState: 'FORBIDDEN', errorCode: 'CSRF_REFUSED' })
  check('a known code gets its sentence', known.detail === ASK_REFUSAL_TEXT.CSRF_REFUSED)
  const unknown = askDenialView({ authState: 'FORBIDDEN', errorCode: 'SOMETHING_NEW', error: 'forbidden — this operator is not permitted this surface' })
  check('an unknown code is still shown as the code', refusalLabel(unknown) === 'SOMETHING_NEW')
  check('an unknown code falls back to the transport sentence', unknown.detail === 'forbidden — this operator is not permitted this surface')

  const noisy = askDenialView({ authState: 'FORBIDDEN', errorCode: 'refused' })
  check('a non-code string is not echoed as a code', noisy.code === null)
  check('a non-code string still labels as HTTP 403', refusalLabel(noisy) === 'HTTP 403')
}

// ── 401: sign in first ───────────────────────────────────────────────────────
{
  const v = askDenialView({ authState: 'UNAUTHORIZED', errorCode: 'NOT_AUTHENTICATED', error: 'not authorized — sign in' })
  check('401 is a denial', v.denied === true)
  check('401 reports HTTP 401', v.httpStatus === 401)
  check('401 is titled as a sign-in', /Sign-in/.test(v.title))
  check('401 recovery names signing in', /[Ss]ign in/.test(v.recovery))
  check('401 keeps the server code', v.code === 'NOT_AUTHENTICATED')
}

// ── the input is not mutated, and output objects are not shared ─────────────
{
  const input = { authState: 'FORBIDDEN' as const, errorCode: 'CSRF_REFUSED', errorDetail: '', error: '' }
  const before = JSON.stringify(input)
  const a = askDenialView(input)
  const b = askDenialView({ authState: 'OK' })
  check('the caller’s object is untouched', JSON.stringify(input) === before)
  check('two refusals do not share one object', askDenialView(input) !== askDenialView(input))
  check('a non-denial does not leak a previous refusal', b.denied === false && refusalLabel(b) === 'not measured')
}

console.log(`\naskCioDenied: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
