# AI routing architecture — governed bridge (n8n program W4, 2026-10-08)

**Status:** DRAFT
as_of: 2026-10-08T16:00:00Z
**Owner:** `scripts/lib/cio_governed_model_bridge.py`
**Schema:** `LlmRoutingPolicy@v1` in `config/llm_routing_policy.json`

n8n may name a registered process, a versioned template id, and a routing-policy name. The bridge resolves the model. n8n does not name a model, a provider, or a raw prompt, and it does not hold a provider key.

## Model selection

`resolve_model_policy` loads `config/llm_routing_policy.json` and caches it by path, mtime, and size. The default policy id is `default`. A caller selects another policy with the header `X-TradeAI-Routing-Policy` (the same constant the model-job client forwards). A missing or blank header selects `default`. An unknown name is refused with `error.code = unknown_routing_policy` (HTTP 400) before Ring 2, before reservation, and before any provider call. A direct `execute_governed_call(..., routing_policy=...)` uses the same check.

The policy has one row for every id in `config/llm_process_registry.json` `processes`. Each row names `primary`, `secondary`, and `fallback` lanes as `{provider, policy}`. The lane policy name is one of `PRO`, `FAST`, `PRO_THINK`, `FAST_THINK`. Those names are the same `requested_policy` values the bridge returned before this file existed: the nineteen processes that had a hard-coded map keep that name, and every other registered process uses its registry `deepseek_default_policy` when that name is one of the four, otherwise `FAST`. `POLICY_RESOLUTION` still maps the name onto the DeepSeek model id, thinking flag, and display name. The lane's `provider` overwrites the provider field. An id that is not in the registry still returns `None` from `resolve_model_policy` (`UNKNOWN_PROCESS` on the execute path).

`model_chooser.apply` still runs as a shadow observation inside `resolve_model_policy`. A disagreement is a receipt. It does not change the lane.

## Responsibilities

| actor | owns | does not own |
|---|---|---|
| n8n | process id, template id, routing-policy name, schedule | model, provider, prompt text, provider key, memory |
| governed bridge | policy load, health gate, per-provider semaphore, receipt, provider call | scheduler install, n8n credentials |
| `config/llm_process_registry.json` | process registration, lane policy, daily request and dollar caps | which lane is healthy right now |
| `scripts/check_llm_provider_health.py` | `data/runtime/llm_provider_health.json` | the routing decision |
| balance snapshot | `data/runtime/deepseek_balance_history.jsonl` | a live balance HTTP call from the bridge |

The bridge reads those two receipts from disk. It does not call the health script, the balance URL, or a provider to decide health. A missing or unreadable receipt is `unknown`, not healthy and not a refusal by itself.

## Routing framework

`select_governed_lane` walks the row:

1. `health_gate` false: choose `primary` (`reason = health_gate_off`).
2. Primary exists and its provider is not `unhealthy`: choose `primary`. `primary_healthy` when the receipt says healthy, `health_unknown_routed` when the receipt is missing or does not indict the provider. The lane still routes. The reason records that the choice was not a measured healthy receipt.
3. Otherwise secondary, then fallback, only when that lane's provider is explicitly `healthy` (`failover_secondary`, `failover_fallback`).
4. Otherwise refuse `lane_unhealthy` (HTTP 503) before the cost cap, the reservation, and `provider.generate`.

A provider is `unhealthy` when the health file is present and an unrecovered finding names that provider (lane string contains the provider name) with severity `CRITICAL` or kind `BILLING` or `AUTH`, or, for DeepSeek, the last balance row has `is_available` false or `total_balance` <= 0. Explicit `healthy` requires the health file to be present, `worst_severity` in `OK` / `WARN` / `CRITICAL`, and no such indictment.

`deepseek_only` rows name DeepSeek on every lane. An unhealthy DeepSeek receipt therefore refuses `lane_unhealthy` and does not call DeepSeek. Failover to grok or chatgpt exists only on rows whose secondary or fallback names that provider, and only when that provider's receipt is healthy.

Canary mode (`CIO_BRIDGE_MODE=canary`) still uses `RealProvider`, which speaks DeepSeek only. If the chosen lane's provider is not `deepseek`, the bridge returns `provider_not_configured` (HTTP 503) after the allowlist check and before reservation. Mock mode (the default, and the tests) uses `MockProvider` under that provider's semaphore and does not open a provider socket.

The global `_INFLIGHT_SLOTS` bound stays. It is not the per-provider limit.

## Prompt architecture

Prompt text for an n8n model job is a template id in `config/n8n_prompt_templates.json` (`N8nPromptTemplateSet@v1`, each template `N8nPromptTemplate@v1`). `scripts/lib/n8n_model_job.py` renders the template on the host. The bridge logs a hash of the message list, not the prompt. Routing receipts carry status words only: no prompt, no key, no filesystem path, no balance amount.

## Memory strategy

n8n holds no memory. An `n8n_*` process is read-only advisory. This path does not write an InstrumentRecord, a belief, a lesson, or a memory store. Unknown routing policies are refused before Ring 2, so a bad policy name cannot be turned into a memory-context demand. A known policy still passes through the bridge's existing Ring 2 check for research-class callers.

## Vector retrieval

Deferred. Embedding storage and pgvector stay in `docs/implementation/n8n-parallel/15-pgvector-migration-decision-20261008.md`. Lane selection does not query embeddings.

## Response validation

Model-job JSON is checked against `config/schemas/n8n_model_job_outputs.json` (`N8nModelJobOutputSchemas@v1`) by `scripts/lib/n8n_model_job.py`. The two schemas are `material_change_digest_draft/v1` and `ops_summary_draft/v1`. `recommendation` is the enum `NONE`. Forbidden keys include `buy`, `sell`, `size`, and `order`. A failed validation is a typed refusal, not a second model call from n8n.

## Fallback hierarchy

`primary` → `secondary` → `fallback` → `lane_unhealthy`.

Failover moves only to a lane whose provider is explicitly healthy. Unknown health stays on the primary. It is not a failover and it is not a refusal. Every gated lane unhealthy, or no usable lane, is `lane_unhealthy` and the provider is not called.

## Cost and latency controls

Two caps already apply, and this policy does not add a third refusal: the process row in `config/llm_process_registry.json` (`daily_soft_cap`, `daily_cost_cap_usd`) and `LLM_GLOBAL_DAILY_USD_CAP` ($2.00 of actual spend). Each routing row copies the registry dollar cap into `cost_ceiling_usd` (or 2.0 when the registry value is not numeric) and sets `latency_budget_ms` to 150000, matching the bridge upstream deadline of 150 seconds. Those two numbers are echoed on the resolved policy. The existing cap check and the upstream deadline remain the enforcement.

`provider_concurrency` on the policy is the per-provider `BoundedSemaphore` size. The default policy sets deepseek 6, grok 2, chatgpt 2. An unlisted provider gets one slot. The size is read from the loaded policy. The semaphore is acquired only around `provider.generate` and released in `finally` when the call raises, so one slow provider cannot hold another provider's slots and a raised call cannot leak a slot.

## Receipts

Every bridge response, success and refusal, includes `routing_decision`. The stream path resolves the policy again before it writes the HTTP status line. When that second resolve is not a usable lane, the response is the same typed JSON the non-stream path returns (`error.code`, `error.status`, and `routing_decision`) with `Content-Type: application/json`. It does not open `text/event-stream`.

```text
{policy_id, lane_chosen, reason, health_snapshot}
```

`health_snapshot` is status words: `provider_health` and `deepseek_balance` are `present`, `missing`, `unreadable`, or `not_read`; `lanes` maps each provider on the row to `healthy`, `unhealthy`, or `unknown`.

After a reservation succeeds, the same `reservation_id` is written onto `routing_decision` and onto `_tradeai`. The provider-cost attribution context for that call receives that id (`lib.provider_cost.context.cost_attribution`). RealProvider's `_emit_bridge_cost` emits inside that context, so the cost event and the routing decision share one reservation id. Mock mode does not emit a provider-cost event; the attribution context still carries the id.
