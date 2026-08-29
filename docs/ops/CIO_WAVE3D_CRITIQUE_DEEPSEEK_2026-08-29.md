# Wave 3D-critique on DeepSeek — **both live lanes are blocked, for opposite reasons**

    vendor HTTP calls   0        cost_usd  0.00
    attached            NO       telegram_sent  false
    provider_cost delta 0        research_call_accounting delta 0

You chose `deepseek-v4-flash` via `hermes_external_research` to avoid a policy
change. Policy did allow it — and the call still could not be made, for a
different reason that only surfaced by trying.

## What happened

    process_id  hermes_external_research
    lane        deepseek-v4-flash
    should_call allow: True          <- policy is fine
    result      COST_CAP_EXCEEDED: global cap
    verdict     PARTIAL · attachable false · cost 0.00 · vendor HTTP 0

The cap is not *exceeded*. It is **unconfigured**, and the code fails closed on
an unconfigured cost configuration — which `llm_lane` documents in its own
docstring: *"Without this, DeepSeek fail-closes COST_CONFIGURATION_INVALID:
LLM_GLOBAL_DAILY_USD_CAP required."*

Evidence it is not a real breach: **$0.0000 spent today, 0 events.**

## The deeper finding: DeepSeek is not configured on this host

    .env                                    absent (worktree, CURRENT, $HOME, releases root)
    LLM_GLOBAL_DAILY_USD_CAP in unit env    not set
    DEEPSEEK_API_KEY anywhere               not present
    config/broker_credentials.env           0 matching keys

There is no DeepSeek credential. The lane is authorised by policy and
unusable in fact.

## So both routes are blocked, for opposite reasons

| lane | policy | credentials | live call |
|---|---|---|---|
| `grok` (OAuth proxy 8645) | **refused** — no research/critique process lists it | **fine** — free_oauth, keyless, proxy returns 200 | blocked by policy |
| `deepseek-v4-flash` | **allowed** on `hermes_external_research` | **absent** — no key, no global cap | blocked by configuration |

The one lane that works needs a policy decision; the one policy allows needs a
credential and a spend cap. Neither is mine to grant.

## What I did not do

- did not add `grok` to any process `allowed_lanes`
- did not set `LLM_GLOBAL_DAILY_USD_CAP`
- did not add a DeepSeek key
- did not attach anything

Each would be a spend or vendor-exposure decision wearing a config change.

## A real bug the attempt exposed

The refusal came back as `["transport_error", "COST_CAP_EXCEEDED: global cap"]`
and my code marked it **`retryable: True`** — because the gate reports refusals
as free text inside the exception message, so the literal `cost_cap` set lookup
missed it.

The contract says cost_cap is never retryable. Retrying a budget stop is asking
the same question until a different answer arrives. Fixed: refusals are matched
on markers (`cost_cap`, `cost_configuration_invalid`, `policy_not_allowed`,
`process_not_registered`, `manual_mode`, `execution_language`) and are never
retryable; a genuine `ConnectionError` still retries once. Five tests pin it.

Worth noting this only surfaced because the call was actually attempted against
the real gate. A mocked-only test suite would have kept reporting green.

## To close the loop — pick one

1. **Authorise grok** — `maria_research_critique.allowed_lanes += ["grok"]`.
   Free (`free_oauth`), no key needed, proxy already up. Cost: xAI sees research
   artifact text.
2. **Configure DeepSeek** — supply `DEEPSEEK_API_KEY` and
   `LLM_GLOBAL_DAILY_USD_CAP`. Real metered spend, no new vendor exposure
   beyond what the process already assumes.

(1) is one line and costs nothing but data exposure. (2) costs money but needs
no policy widening. The call site is lane-agnostic — either is a one-argument
change, no code edit.

## State

Lane built and merged. Default pairing is the policy-permitted
`deepseek-v4-flash` + `hermes_external_research`; grok constants retained for
the day that lane is authorised. `research_quality.critique()` still returns
the deterministic lint by default — asserted byte-identical.

28 lane tests, all mocked. `/v3/cio` 200, `telegram_sent` false, cash
$630,784.82, `cio_run` `DETERMINISTIC_PRODUCT`. 3E not started.
