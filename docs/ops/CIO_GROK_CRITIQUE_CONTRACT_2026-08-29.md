# Grok critique call site — contract (2026-08-29)

The missing lane. `research_quality.critique()` is a deterministic lint;
`ResearchNeedDecision@v2` routes VALID artifacts to `grok_critique`; the Grok
OAuth proxy is up on 8645. Nothing connected them. This specifies the join
before it is built.

## Scope

Critique **one existing VALID artifact**. It does not research, does not
attach, does not escalate, and does not mint a plan.

## Input

| field | source |
|---|---|
| `artifact` | the existing VALID research result |
| `plan_id` | the plan the artifact belongs to |
| `research_id` | the research stream that produced it |
| `question_ids` | carried forward from the gate's template block |

## Output — JSON, exactly

```json
{
  "verdict": "VALID | PARTIAL | REJECT",
  "reasons": ["..."],
  "execution_language": false,
  "attachable": true
}
```

Anything else — prose outside the object, a missing verdict, a verdict not in
the enum — is treated as `PARTIAL` with reason `unparseable_response`, never as
`VALID`. A critique that cannot be read is not a pass.

## Prompt

The curated `grok_critique` template already in `cio_research_templates.build()`.
No free-form prompt is constructed at the call site — that module is the single
place gate prompts are defined, and duplicating one here would let the two drift.

## Transport

`scripts/llm_lane.generate(lane="grok", process_id=..., response_json=True)` —
the existing harness. **No new HTTP client.** It already owns the proxy URL
(`HERMES_XAI_PROXY_URL`, default `http://127.0.0.1:8645/v1/chat/completions`),
retries, and the consumption gate.

## Cost

Ledgered through the consumption gate via `process_id`.

Chosen: **`maria_research_critique`** (category `CIO`, mode `automated`).
`hermes_external_research` is also registered and the brief permits it, but its
display name is *"Hermes External Research (DeepSeek)"* — booking a Grok
critique against a DeepSeek-named research process would make the ledger read
wrong at exactly the moment someone is auditing spend. The critique-shaped CIO
process is the honest home.

Lane billing is `free_oauth`, so `cost_usd` is expected to be `0.0`. It is still
recorded, and still capped: a free lane that silently becomes metered must not
slip through because nobody was counting.

## Retry

| outcome | retryable |
|---|---|
| `truncated` / unparseable | **once** |
| `execution_language` | **never** |
| transport error | once |
| `cost_cap` | never — skip until `next_eligible_at` |

`execution_language` is not a transient failure. Retrying it is asking the same
question until a different answer arrives.

## Boundaries

- **Does not attach.** The function returns a verdict; the caller applies the
  existing attach rules. Attaching inside the critique would make the reviewer
  the approver.
- **Does not escalate.** A `REJECT` does not buy Flash/Pro/OpenAI.
- **Live only behind `--backend live`.** Default stays the deterministic lint,
  so dry runs, stub runs and every existing test path are unchanged.
- **One call.** No fan-out, no second opinion, no tie-break.

## Failure posture

Any exception, unreachable proxy, or unparseable body yields a `PARTIAL`
verdict with `attachable: false`. The artifact stays unattached and the plan
stays where it was. Failing closed here costs a re-run; failing open would
attach unreviewed research.
