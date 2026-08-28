# P9.1 — where does the model call go?

**Answer: there is no model call.** `CIO_RUN_MODEL_CALL_RECORDED` is a receipt for
inference that never happens, and the "synthesis" it accompanies is deterministic.

READ ONLY. Nothing was fixed. `[VERIFIED]` = command run against live state, output
quoted. `[CODE]` = read from source in `9783395a-main-exact-phase2-20260828-082142`.

## Why this is a fourth answer

The brief offered three possibilities, and all three presuppose that a model is called:
output reaches the product but not Telegram; output persisted and read by nothing;
output not persisted at all. None applies. The synthesis output **is** persisted, **is**
read widely, and **does** reach the operator — it simply is not model output.

---

## The four questions

### 1. What prompt was sent, and what selected its inputs?

**No prompt exists.** `[CODE]`

The production path is `cio_wake_dispatch_entrypoint.py:107`, which constructs the worker
with `synthesis_fn=build_investment_product_synthesis_fn()`. That function is eleven
lines `[CODE cio_investment_product.py:1090-1106]`:

```python
def fn(run, snapshot, specialist_result, hermes_result):
    product = persist_product(build_product(root=root, env=env))
    product["run_id"] = (run or {}).get("run_id")
    product["snapshot_ref"] = (snapshot or {}).get("snapshot_id")
    product["specialist_count"] = len((specialist_result or {}).get("artifacts") or [])
    product["hermes_present"] = bool(hermes_result)
    product["opportunity_queue"] = {...}
    return product
```

`build_product` is the deterministic investment-product builder. The module contains no
inference client: grepping it for `llm|call_model|ollama|openai|anthropic|inference|
prompt|completion` returns exactly one hit, `research_prompt_context.latest_delta` — a
context reader, not a call `[VERIFIED]`.

### 2. What came back — is the response persisted, and where?

**There is no response.** The deterministic product is persisted, to
`data/cio/cio_investment_brief.json` plus the `cio_investment_briefs.jsonl` history, by
`cio_investment_product.persist_product` `[CODE]`.

What the run store records instead is a receipt whose payload contains no content at all
`[VERIFIED]`:

```json
{
  "call_ref": "synthesis-cio-synth-8b5e7d1433914db4",
  "cost_usd": 0.001,
  "run_id":  "07fc6e44-056a-4170-a0e2-7cc8efcf2df3"
}
```

No prompt, no response, no model name, no token counts. Searching every persistent-state
store for that `call_ref` returns three files — `cio_runs.jsonl`,
`cio_workflow_lineage.jsonl`, `outcome_checkpoints.jsonl` — all lineage. **No content
store contains it** `[VERIFIED]`.

### 3. What consumes the response? Name every reader.

The deterministic product is consumed by, at minimum `[CODE]`:

| reader | what it takes |
|--------|---------------|
| `cio_operator_product.build_operator_product` | the whole brief — 25 sections of the Command Center view |
| `cio_run_worker._emit_notifications` | `result["summary"]` → the run-complete Telegram body |
| `aegis_evening_packet._cio_product` | `cio.desk`, `cio.reentry`, `cio.operator_product` |
| `cio_command_center` | home surface, labelled `canonical_cio_source` |
| reentry / opportunity desks | `reentry_book`, `opportunity_book` |

So the answer to "read by nothing" is emphatically no. It is read by everything.

### 4. Does any operator-facing surface contain any part of it?

**Yes — all of it.** Every surface in the P9.0 census is downstream of this product. The
finding is not that the judgment is discarded; it is that there is no judgment to
discard.

---

## The receipt, precisely

`cio_run_worker._cio_synthesis` has three branches `[CODE :858-951]`:

1. **Timer-fired no-change.** Returns `"llm_dispatch": False` and records **no** model
   call. Comment: *"Timer-fired no-change: do not invoke a model."* This branch is
   honest.
2. **`if self._synthesis_fn:`** — calls the injected function, then unconditionally:
   ```python
   self._call_count += 1
   self._cost_accrued += 0.001
   self.run_store.record_model_call(self._run_id, f"synthesis-{artifact_id}", 0.001, ...)
   ```
   This is the production branch, and the injected function performs no inference.
3. **Fallback** — builds a dict literal whose `summary` is
   `f"CIO synthesis for run {run_id}"`, then records a model call the same way.

Branches 2 and 3 record a model call. Neither calls a model.

The codebase already knows the right convention. `cio_gate_measurement_bridge.py:129`
documents a deterministic path as *"zero model calls: `model_calls: 0, cost_usd: 0.0`.
Deterministic = no hallucination possible."* `[CODE]` The run worker does the opposite for
the same kind of work.

### The accounting `[VERIFIED]`

```
42 MODEL_CALL_RECORDED receipts
total recorded cost  $0.042
distinct cost values [0.001]      <- a hardcoded literal, not a measurement
```

Every receipt carries the identical hardcoded figure. No consumer reads this cost, so
nothing downstream is currently wrong because of it — but the ledger is fictional, and a
spend report built on it later would be too.

---

## Why this matters more than the money

$0.042 is nothing. The damage is evidential.

`MODEL_CALL_RECORDED` in the completed-run stage sequence is the **single strongest
signal in the system that judgment is being exercised.** It is what made the brief
reasonably conclude a model is being called during synthesis. It is false.

This resolves the tension the brief identified — *"the notification body is a
deterministic template; both cannot be the whole story"* — in the direction that costs
the most: the template is the whole story, and the stage event is the misleading part.
It also explains P9.0's headline count of **A = 0** without contradiction.

---

## Consequence for the gated work

The brief gates producers for `AGENT_COMMITMENT` and `CASE_SUMMARY` on this answer, and
the answer inverts the expected sizing.

> *"If P9.1 finds the model output is already produced and discarded, wiring those types
> is a different and much smaller job."*

It is not produced. **Nothing in the CIO run path generates judgment at all**, so those
producers have no source to draw from. Wiring them is therefore the **larger** job, not
the smaller one: it requires deciding what generates a commitment or a case summary, not
merely routing something that already exists.

## Recommended, not done

Nothing here was fixed, per the brief. Two candidates, both small, both operator's call:

1. **Stop recording a model call when none is made.** Either drop the
   `record_model_call` from branches 2 and 3, or record `model_calls: 0, cost_usd: 0.0`
   as `cio_gate_measurement_bridge` already does. Cost: a few lines. This is the honest
   minimum.
2. **If inference is wanted in synthesis**, that is new capability and belongs in
   scoping, not in a defect list.
