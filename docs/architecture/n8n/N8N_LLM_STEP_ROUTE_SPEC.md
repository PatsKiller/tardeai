# n8n → LLM step route — specification and proof list

```
Status:      SPECIFIED route (P); bridge op and OAuth adapters EXIST (E). Audit DD17 (P2, Known). Answers open question Q1.
as_of:       2026-10-15 (runtime facts measured ~13:03Z: bridge /health, ss -ltn)
Audit:       independent due diligence 2026-10-15 (pinned e355be188) §12 "OAuth adapters now exist"
Policy:      AGENTS.md §23.23 "LLM steps", §23.4; decision D8 (N8N_DECISION_LEDGER.md)
Owner:       bridge owner + action owner (ROLES to confirm)
```

## 1. Correction (audit §12): the OAuth adapters exist

`scripts/lib/bridge_oauth_transport.py` implements the Grok (`xai-oauth`, `127.0.0.1:8645`) and ChatGPT
(`openai-codex`, `127.0.0.1:8646`) transports for the governed bridge. They are opt-in through
`CIO_BRIDGE_OAUTH_TRANSPORTS` (comma list). The audit's source-only review called runtime enablement unmeasured;
measured here on 2026-10-15 13:03Z: bridge `/health` `transports = [chatgpt, deepseek, grok]`, both proxies LISTEN on
loopback only. No document should repeat the earlier "missing adapter" claim. What is still missing is **n8n's reach**
to `/v1/llm_step` (the bridge listens on loopback; no relay route), enforced caller authentication, the host-side
action re-check and deferral enforcement.

## 2. Decision proposed for Q1: a relay route, not a bridge token in n8n

`POST /llm_step` on the relay (D2: one door), forwarded to the bridge as scope `llm_step` (a new gateway scope that
opens exactly this one operation). n8n holds no bridge key; the relay presents the bridge caller key
`TRADEAI_BRIDGE_CALLER_KEY_N8N_RELAY` (host-rendered, ≥ 32 chars) so the bridge sees a **verified** caller. Rejected:
a scoped bridge token stored in n8n (a second credential in the container; violates C5 "one credential").

Request body (exact keys, ≤ 1024 B, unknown/duplicate keys refused): `process_id`, `template_id`, `facts` (object,
bounded), `run_id`, `execution_id`, `budget` (optional, may only narrow the registry row). Never: a model, provider,
key or prompt text. Response: `LlmStepResult@v1` (decision from the closed schema enum, `audit_ref`, typed refusal).

## 3. Preconditions before the route is added

1. Bridge caller auth `enforce` for caller `n8n_relay` (threat model §5 row 2), and invalid-mode fallback changed to
   `enforce` (today an invalid `TRADEAI_BRIDGE_CALLER_AUTH` value falls back to `report`).
2. Host action re-check: the decision is an enum value from `config/schemas/n8n_llm_step_outputs.json`; the consumer
   of the decision re-validates it against the registered action set and the current state before any effect.
3. Deferral enforcement: off-peak deferral (§14) applies to `llm_step` exactly as to other paid calls.
4. C1–C3 measured true (AGENTS §23.23 "Controls before new powers").

## 4. Proof list (existing tests marked E; required new tests marked P)

| # | Property | Test | Status |
|---|---|---|---|
| L1 | provider order grok → chatgpt → deepseek for n8n rows | `tests/test_bridge_oauth_llm_step_20261014.py::test_walk_order_is_grok_then_chatgpt_then_deepseek` | E |
| L2 | 401/403 is an auth failure distinct from serving failure | `::test_auth_failure_is_distinct_from_serving_failure` | E |
| L3 | 429 Retry-After honoured | `::test_429_retry_after_holds_grok_until_it_elapses` | E |
| L4 | pinned-model mismatch is a serving failure | `::test_chatgpt_pinned_model_mismatch_is_a_serving_failure` | E |
| L5 | invalid output refused | `::test_llm_step_refuses_schema_invalid_output` | E |
| L6 | total route deadline shared | `::test_total_deadline_is_shared_across_routes` | E |
| L7 | every route failing is typed and unbilled | `::test_every_route_failing_is_typed_and_unbilled` | E |
| L8 | prompt injection in facts cannot change the action set | `::test_prompt_injection_in_facts_cannot_change_the_action_set` | E |
| L9 | budget cannot widen the registry row | `::test_llm_step_budget_cannot_widen_the_row` | E |
| L10 | proxies loopback-only | `::test_proxy_url_env_names_and_loopback_only` | E |
| L11 | relay `POST /llm_step` exact keys; model/provider/key fields refused | new relay test | P |
| L12 | unverified caller → 401 before reservation (enforce) | new bridge test on `n8n_relay` caller | P |
| L13 | consumer refuses a decision outside the current action set (action re-check) | new consumer test | P |
| L14 | spend reservation released on refusal; placeholder usage is not measured zero | new bridge test | P |
| L15 | policy refusal never becomes provider-fallback authority | new bridge test | P |
| L16 | one live receipt: n8n execution → `LlmStepAudit@v1` row joined by `run_id`/`execution_id` | runtime evidence | P |

## 5. Residual

The OAuth proxies on loopback can be called directly by any uid-`johnclaw` process, bypassing the bridge's caps and
audit (threat model RR9). Closure: proxy-side caller check or a socket only the bridge principal can open, after the
uid split.
