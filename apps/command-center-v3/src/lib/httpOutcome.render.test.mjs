// node --experimental-strip-types --import ./src/lib/tsxRegister.mjs src/lib/httpOutcome.render.test.mjs
//
// BOARD row 35 — the 403 that lied. `classifyStatus` used to hardcode "this operator is not permitted this
// surface" for ANY 403, so a missing Tailscale identity and a real permission denial rendered identically.
//
// This test RENDERS the notice component from a real 403 classification, so deleting the code-specific branch
// changes what the operator would read and turns this red. Testing the helper alone would not.
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

const { classifyStatus } = await import('./httpOutcome.ts')
const { OutcomeNotice } = await import('../components/OutcomeNotice.tsx')

let pass = 0, fail = 0
const check = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) }
}
const render = (outcome) => renderToStaticMarkup(React.createElement(OutcomeNotice, { outcome }))
const NOW = Date.parse('2026-11-04T11:30:00Z')

// The two 403s the status line cannot tell apart
const identity = classifyStatus(403, null, NOW, 'AGENT_CALLER_REFUSED')
const denial = classifyStatus(403, null, NOW, null)
const denialOther = classifyStatus(403, null, NOW, 'SOME_OTHER_REFUSAL')

check('an identity refusal is classified as IDENTITY_REQUIRED', identity.kind === 'IDENTITY_REQUIRED', identity.kind)
check('a permission denial stays FORBIDDEN', denial.kind === 'FORBIDDEN', denial.kind)
check('an unrecognised 403 code stays FORBIDDEN', denialOther.kind === 'FORBIDDEN', denialOther.kind)

const identityHtml = render(identity)
const denialHtml = render(denial)
check('the identity refusal RENDERS the Tailscale sign-in', /Tailscale/.test(identityHtml), identityHtml)
check('the identity refusal does NOT render "not permitted"', !/not permitted/.test(identityHtml), identityHtml)
check('the permission denial RENDERS "not permitted"', /not permitted/.test(denialHtml), denialHtml)
check('the permission denial does NOT mention Tailscale', !/Tailscale/.test(denialHtml), denialHtml)
check('the two 403s are visibly DIFFERENT sentences', identityHtml !== denialHtml)
check('the identity state carries its own machine marker',
  /data-outcome="IDENTITY_REQUIRED"/.test(identityHtml) && /data-outcome="FORBIDDEN"/.test(denialHtml))
check('an identity refusal is actionable: it names the remedy', /sign in/i.test(identityHtml))
check('the refusal does not claim the identity was absent', !/identity was not presented/i.test(identityHtml), identityHtml)
check('it says a signed-in caller may still be refused (the agent case)', /already signed in/i.test(identityHtml), identityHtml)
check('it explains that the connection was not accepted rather than blaming sign-in', /connection is not accepted for operator access/i.test(identityHtml), identityHtml)

// A 401 keeps its own meaning, and 200/404 are unchanged by this mapping
check('401 is still UNAUTHORIZED', classifyStatus(401, null, NOW, 'AGENT_CALLER_REFUSED').kind === 'UNAUTHORIZED')
check('404 is still CLIENT_ERROR', classifyStatus(404, null, NOW, 'AGENT_CALLER_REFUSED').kind === 'CLIENT_ERROR')

console.log(`httpOutcome.render: ${pass} passed, ${fail} failed`)
process.exit(fail > 0 ? 1 : 0)
