# Governed bridge: enabling the Grok and ChatGPT OAuth transports

Operator packet, 2026-10-14. Branch `n8nfab/bridge-oauth-llm-step-20261014`.

## What changes when this is enabled

The routing policy (`config/llm_routing_policy.json`) already lists Grok OAuth, then ChatGPT OAuth, then DeepSeek
for the three `n8n_*` rows (`transport_failover: true`). Before this branch, the bridge could only reach DeepSeek,
so every call skipped to the fallback. With this branch:

- The bridge can reach the two local OAuth proxies that already run on the host:
  - `grok-oauth-proxy.service` on 127.0.0.1:8645
  - `chatgpt-oauth-proxy.service` on 127.0.0.1:8646, serving `gpt-6.1-sol` through drop-in `50-model-20261014.conf`
- The bridge tries the lanes in the policy's order. A 429 holds that provider until its Retry-After. A breaker for
  each provider opens after 3 consecutive failures, or after a single auth failure, and stays open for 300 s. All
  attempts in a call share the row's 150 s budget.
- Every lane considered gets a `BridgeRouteReceipt@v1` in `_tradeai.route_receipts`. Each receipt records the
  provider, model, latency, outcome, cost (or `"unknown"`) and `auth_failure`.
- `POST /v1/llm_step` exists. It is the bounded judgment step that n8n calls (AGENTS.md §23.23), and it writes one
  `LlmStepAudit@v1` row per call to `data/runtime/llm_step_audit.jsonl`.

The change is limited in three ways:

- **OAuth lanes serve only rows that opt in.** Rows with `transport_failover: true` can use them. Every other
  Grok-primary row, such as `portfolio_ai_analyst`, still gets `provider_not_configured`.
- **The registry must also allow the lane.** An OAuth lane is used only when the process registry row lists it in
  `allowed_lanes`:

  | Process | `allowed_lanes` includes Grok and ChatGPT | Route when enabled |
  |---|---|---|
  | `n8n_lane_failure_diagnosis` | yes | Grok, then ChatGPT, then DeepSeek |
  | `n8n_material_digest_draft` | no (`deepseek_only`) | DeepSeek; receipts say `registry_lane_not_allowed` |
  | `n8n_ops_summary_draft` | no (`deepseek_only`) | DeepSeek; receipts say `registry_lane_not_allowed` |

  Moving the digest and ops-summary rows to OAuth-first is a separate registry change for you to decide.
- **Nothing changes until you set the env.** With `CIO_BRIDGE_OAUTH_TRANSPORTS` unset, the bridge behaves as it did
  before (DeepSeek only).

## Names (no values are secret)

| Name | Where | Meaning |
|---|---|---|
| `CIO_BRIDGE_OAUTH_TRANSPORTS` | bridge unit env | Comma list: `grok`, `chatgpt`. Unset or empty means DeepSeek only. |
| `HERMES_XAI_PROXY_URL` | bridge unit env (optional) | Grok proxy chat-completions URL. Default `http://127.0.0.1:8645/v1/chat/completions`. Loopback only. |
| `CHATGPT_PROXY_URL` | bridge unit env (optional) | ChatGPT proxy base URL. Default `http://127.0.0.1:8646`. Loopback only. |
| `CIO_BRIDGE_GROK_MODEL` | bridge unit env (optional) | Pins the Grok model. Unset means the proxy's default (`GROK_PROXY_MODEL`). |
| `CIO_BRIDGE_CHATGPT_MODEL` | bridge unit env (optional) | Pins the ChatGPT model. When set, the reply must name it, or the attempt is recorded as `model_mismatch`. |
| `CIO_BRIDGE_PROVIDER_CIRCUIT_ERRORS` | bridge unit env (optional) | Breaker threshold. Default 3. |
| `CIO_BRIDGE_PROVIDER_CIRCUIT_COOLDOWN_SEC` | bridge unit env (optional) | Breaker cooldown. Default 300. |
| `CIO_BRIDGE_DEFAULT_RETRY_AFTER_S` | bridge unit env (optional) | Hold applied to a 429 that has no Retry-After. Default 60. |
| `TRADEAI_LLM_STEP_AUDIT` | bridge unit env (optional) | Audit JSONL path. Default `data/runtime/llm_step_audit.jsonl` under the served release. |

The OAuth sessions stay with Hermes behind the proxies, and the bridge holds no OAuth credential. The re-login
commands are the ones the proxies already print:

- Grok: `hermes auth add xai-oauth --type oauth`
- ChatGPT: `hermes auth add openai-codex --type oauth`

## Activation (operator)

1. **Merge, then promote.** The bridge runs from `.../portfolio-server/CURRENT`, so the code reaches it only after
   merge and promote. The promote restarts `cio-governed-bridge.service`. Confirm the served SHA before step 2.

2. **Confirm both proxies are ready.** This is read-only:

   ```
   curl -s http://127.0.0.1:8645/health
   curl -s http://127.0.0.1:8646/health
   ```

   Each needs `"authenticated": true` and `"token_expired": false`.

3. **Dry-run the probe.** It prints the request and sends nothing:

   ```
   python scripts/bridge_llm_step_probe.py --expect grok
   ```

4. **Add the drop-in.** This needs a config-write grant that names this PR and SHA:

   ```
   # ~/.config/systemd/user/cio-governed-bridge.service.d/60-oauth-transports-20261014.conf
   [Service]
   Environment=CIO_BRIDGE_OAUTH_TRANSPORTS=grok,chatgpt
   Environment=CIO_BRIDGE_CHATGPT_MODEL=gpt-6.1-sol
   ```

   Then reload and restart the bridge:

   ```
   systemctl --user daemon-reload
   systemctl --user restart cio-governed-bridge.service
   curl -s http://127.0.0.1:8766/health
   ```

   In the `/health` response, `transports` must be `["chatgpt","deepseek","grok"]` and `provider_circuits` must
   be `{}`.

## Verification: one receipt per route (operator-run)

Each probe makes one `llm_step` call for `n8n_lane_failure_diagnosis` with a synthetic facts pack. It exits 0 only
when the expected provider served, and it prints the receipts and the audit row path. Run the three probes in this
order.

1. **Grok.** Uses the drop-in above.

   ```
   python scripts/bridge_llm_step_probe.py --expect grok --send
   ```

   Expected receipts: `[grok ok]`. Cost is `"unknown"` (free OAuth).

2. **ChatGPT.** Set the drop-in to `Environment=CIO_BRIDGE_OAUTH_TRANSPORTS=chatgpt`, then run `daemon-reload` and
   restart the bridge.

   ```
   python scripts/bridge_llm_step_probe.py --expect chatgpt --send
   ```

   Expected receipts: `[grok no_transport, chatgpt ok]`, and the model is `gpt-6.1-sol`.

3. **DeepSeek.** Set the drop-in to `Environment=CIO_BRIDGE_OAUTH_TRANSPORTS=`, then run `daemon-reload` and
   restart the bridge.

   ```
   python scripts/bridge_llm_step_probe.py --expect deepseek --send
   ```

   Expected receipts: `[deepseek ok]`, with a measured `cost_usd`. This is one paid Flash call, inside the $0.05
   per-call ceiling.

4. **Restore the final drop-in** (`grok,chatgpt`), then run `daemon-reload` and restart the bridge.

5. **Read the evidence.** There should be three new rows in `data/runtime/llm_step_audit.jsonl` under the served
   release. Their `run_id` values are `probe-grok-*`, `probe-chatgpt-*` and `probe-deepseek-*`. Each row carries
   `prompt_sha256`, `response_sha256`, `route_receipts` and `decision.action_id == "suggest_only"`.

If a probe fails, its receipt shows the cause:

- `auth_failure`: the proxy's Hermes session ended. Re-login with the command above.
- `rate_limited` or `retry_after_pending`: the free quota is exhausted. It heals by waiting for the Retry-After.
- `serving_failure`: the proxy or the upstream returned an error. Check the proxy unit's log.
- `no_transport`: the env var was not read. Check the drop-in and `systemctl --user show cio-governed-bridge -p Environment`.

## Rollback

1. Remove the drop-in, or set `Environment=CIO_BRIDGE_OAUTH_TRANSPORTS=` in it.
2. Run `systemctl --user daemon-reload` and `systemctl --user restart cio-governed-bridge.service`.
3. Check that `/health` shows `transports` as `["deepseek"]`.

The bridge is then DeepSeek-only again, which is the behaviour before this branch. No data migration is involved.
The audit JSONL stays where it is; archive it rather than deleting it. Code rollback is the normal release rollback
to the previous SHA.
