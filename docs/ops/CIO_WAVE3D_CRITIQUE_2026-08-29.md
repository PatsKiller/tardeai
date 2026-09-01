# CIO Wave 3D-critique — lane built, one call attempted, **refused by policy**

Status:      HISTORICAL
as_of:       2026-08-29T13:44:50-04:00
Measured at: efcc51365 / not measured

    call site        BUILT and proven to fail closed
    live call        attempted, refused before reaching the proxy
    vendor HTTP      0     provider_cost events delta  0
    cost_usd         0.00  attached  NO   telegram_sent  false

## What was built

`scripts/lib/cio_grok_critique.py`, to the contract in
`CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md`.

- **No new HTTP client.** Reuses `llm_lane.generate(lane="grok",
  process_id=..., response_json=True)`, which already owns the proxy URL,
  retries and the consumption gate.
- **No new prompt.** Uses the curated `grok_critique` template already in
  `cio_research_templates`.
- **Default unchanged.** `research_quality.critique()` still returns the
  deterministic lint; the live path exists only behind an explicit
  `backend="live"`. A test asserts the lint output is byte-identical to before.
- **Never attaches, never escalates.** Returns a verdict; the caller applies
  existing attach rules.

## Step 3 — dry and stub, on the real artifact

Peek unchanged: SPCX and ARKX both `grok_critique`.

Stub critique of SPCX's real completed artifact (`res_557cfaab8c34`):

    verdict VALID · reasons [] · source_count 1 · no network

## Step 4 — the live call was refused

    process_id  maria_research_critique
    lane        grok
    result      POLICY_NOT_ALLOWED
    verdict     PARTIAL · attachable false · retryable true
    cost_usd    0.00 · vendor HTTP 0

**No research or critique process permits the `grok` lane.** Every candidate is
restricted to DeepSeek:

| process | allowed_lanes | mode |
|---|---|---|
| `maria_research_critique` | `fast`, `deepseek-v4-flash` | automated |
| `hermes_external_research` | `fast`, `deepseek-flash`, `deepseek-v4-flash` | automated |
| `advisory_desk_opinion` | `fast`, `deepseek-v4-flash` | automated |
| `guardian_risk_critique` | `fast`, `deepseek-v4-flash` | manual |

39 of the 58 registered processes *do* allow `grok` — but none of the
research/critique ones. The only grok-permitted critique-adjacent process is
`grok_execution_review`, which is manual mode and semantically an execution
review; booking a research critique against it would make the ledger read
wrong at exactly the moment someone is auditing spend.

**This is the correct behaviour, not a bug.** The gate refused a lane the
process is not authorised to spend on, and the critique failed closed:
`attachable: false`, nothing attached, the plan untouched.

## What it would take — your call, not mine

One line, in the process registry:

    maria_research_critique.allowed_lanes += ["grok"]

I did not make it. The pins say no cap raise, and while a lane allowlist is not
literally a cap, widening which providers a process may call is the same class
of decision: it changes where spend can occur and **which vendor sees the
artifact contents**. That is yours to authorise.

Two honest alternatives:

1. **Authorise the lane** — add `grok` to `maria_research_critique`. Billing is
   `free_oauth`, so metered spend does not change; what changes is that xAI
   sees research artifact text.
2. **Critique on DeepSeek instead** — `hermes_external_research` already permits
   `deepseek-v4-flash`. The call site is lane-agnostic; only the default
   constant would change. No policy edit needed, and the contract holds.

Recommend (2) if the goal is to close the loop today: it needs no policy
change, and the ladder's critique step is about *whether the artifact is
attachable*, not about which vendor forms the opinion.

## Verification

21 lane tests (all mocked, no network), 90 green across the research/critique
surface. Notably tested: a model claiming `attachable: true` alongside
`execution_language: true` is **overruled** to REJECT; locally-detected
execution language spends **zero** calls; unparseable bodies are PARTIAL, never
VALID; transport errors fail closed.

## Pins

Notify off, INTERDICT on, `telegram_sent` false, MBI 0, ROTATE advisory-only,
no cap raise, no policy widened, no R1 widen, no Flash enqueued, no escalation.
3E not started.
