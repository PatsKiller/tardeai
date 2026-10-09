# Guardrail Audit B: code and runtime enforcement (2026-10-09)

**Scope.** Guardrails enforced in code and at runtime: what each one prevents, where it is enforced, and whether it still holds (a) on the n8n run and model_job paths and (b) for an n8n *Agent* (an LLM inside n8n with tool calls) calling the governed bridge as an OpenAI-compatible endpoint. A sibling agent covers config files. This audit changed nothing and printed no secret values. Env files were read for variable **names** only.

**Tree.** Read-only detached worktree `/home/johnclaw/tradeai-wt-guardB-20261009` at `origin/main` **a9fa8b89b** (2026-10-09 08:38 ET, merge of #1543). Every file:line below refers to that SHA unless it is marked *installed* (host runtime state).

**Paths assessed.**
- **n8n run:** n8n → relay `172.19.0.1:18092` (`scripts/n8n_run_relay.py`) → gateway `127.0.0.1:18091` `coordination/run` (`scripts/lib/n8n_coordination_gateway.py:_run`) → ledger `runs` row → executor (`scripts/n8n_run_executor.py`) runs the lane's existing script.
- **n8n model_job:** a dispatch-key caller sends gateway `model_job` (`n8n_coordination_gateway.py:361`) → `scripts/lib/n8n_model_job.py` → bridge `127.0.0.1:8766` (`scripts/lib/cio_governed_model_bridge.py`) with caller `n8n_model_job`.
- **n8n Agent (hypothetical):** n8n's OpenAI chat-model node calls the bridge's `/v1/chat/completions` directly, with free-text messages and tool definitions.

**Runtime facts used throughout** (observed 2026-10-09):
- Listeners: `127.0.0.1:7777`, `127.0.0.1:8766` (bridge), `127.0.0.1:18091` (gateway), `127.0.0.1:5678` (n8n UI), `172.19.0.1:18092` (relay). The n8n container (`m8m-n8n`) is on docker network `m8m-n8n_lab`. Today **the only host service n8n can reach is the relay**. The bridge is unreachable from n8n.
- `/run/user/1000/tradeai/env` (loaded by every unit, including the executor) defines `TRADEAI_N8N_GATEWAY_HMAC_KEY`, `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N`, `TRADEAI_N8N_RELAY_BEARER` and `LLM_GLOBAL_DAILY_USD_CAP`. It does **not** define `LLM_DEFER_OFFPEAK`.
- The crontab sets `LLM_DEFER_OFFPEAK=1` globally (crontab line 9). The installed executor unit has no such `Environment=` line (`~/.config/systemd/user/tradeai-n8n-run-executor.service:18-21`).
- Repo `core.hooksPath` = `.githooks`, set in the primary tree.

Legend: **Kind** T = technical (code refuses), P = procedural (CI or hook, bypassable or pre-merge only), Pol = policy text only. **n8n path** and **n8n Agent** take YES, NO or PARTIAL. N/A means the rail has no surface on that path.

---

## A. Hard rails: MBI_BEHAVIOR, broker, orders, stops

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path (run / model_job) | n8n Agent via bridge |
|---|---|---|---|---|---|---|
| 1 | `BehaviorWriteRefused` in cognition (`apply_cognition`, `apply_belief`) | Cognition or memory carrying size, qty, order, stop, limit, weight or trade fields (MBI_BEHAVIOR=0) | `scripts/lib/cio_instrument_record.py:375-378` (fields), `:381`, `:420-423`, `:534-536` | T | PARTIAL: holds only if a lane persists through these functions. None of the 14 allowlisted lanes is shown to (NOT VERIFIED per lane). model_job output does not reach this code. | NO: the bridge returns raw completions and has no behaviour-field scan of output (`cio_governed_model_bridge.py:1253-1714` has no such step) |
| 2 | `intelligence_client.commit` behaviour scan | Memory commits naming behaviour fields | `scripts/lib/intelligence_client.py:108`, `:909-911` | T | PARTIAL: same as #1 | NO: same as #1 |
| 3 | `assert_no_behavior_writes` (L2 results) | L2 memory results carrying writable portfolio fields | `scripts/lib/memory_grounding.py:694-710` | T | PARTIAL: same as #1 | NO |
| 4 | `execution_guard.authorize/require`: single fail-closed broker gate (canary, protective or options envelope, then standing unlock, pilot caps, per-trade 2FA; default `BROKER_DISABLED`) | Any broker submit or cancel outside the committed envelope and without 2FA | `scripts/brokers/execution_guard.py:204-301`, `:304-307` | T | YES: it sits inside the transport, so any lane reaching `place_order` passes through it. No allowlisted lane is broker-facing (`config/n8n_run_allowlist.json`, 14 lanes). | YES: no network or code path from the bridge or n8n to the transport. n8n reaches only the relay; 2FA codes go to the operator. |
| 5 | Per-trade 2FA approval check, single-use consume | An order with no unexpired confirmed approval | `scripts/brokers/approval_service.py:522-539`, `:542` | T | YES | YES |
| 6 | Schwab `place_order` preconditions: api_write_enabled, intent account match, execution readiness, evidence revalidation, options advisory lock, idempotency fence | Unarmed, mismatched, stale or duplicate live orders | `scripts/schwab_transport.py:95-97`, `:101-135`, `:160-175` | T | YES | YES |
| 7 | `replace_order` fenced (always raises) | Native PUT replace | `scripts/schwab_transport.py:587-589` | T | YES | YES |
| 8 | Protective-stop envelope | Out-of-envelope protective stops | `scripts/brokers/protective_stop_policy.py:22` `ENABLED=True`, `:30` **`GATES_REMOVED=True` (pass-through)** | T, **weakened** | PARTIAL: only 2FA (#5) still bites | PARTIAL: same |
| 9 | Ratchet-only stops | Lowering a live stop | `scripts/alpaca_stop_manager.py:515`; `scripts/fidelity_monitored_stop.py:59` | T | YES if the lane runs. Not allowlisted today. | YES: no path |
| 10 | `validate_schwab_write_policy` and `test_no_broker_write_bypass` (static) | A write path that skips the guard; a reachable replace path | `scripts/validate_schwab_write_policy.py:48-60`; CI `.github/workflows/release-readiness.yml:40,43`, `provider-cost-ci.yml:30-31` | P | PARTIAL: protects shipped code, not runtime | PARTIAL: same |
| 11 | Gateway `FORBIDDEN_ROUTE_TOKENS` (broker, order, 2fa, approve, grant, promote, telegram, send, sql, postgres, …) | n8n naming a financial, outbound or SQL route | `scripts/lib/n8n_coordination_gateway.py:64-96`, `:226-240`, `:260-262` | T | YES | NO: the bridge has no route, tool-name or tool-argument filter. Tools pass through to the provider (`cio_governed_model_bridge.py:1810-1811` → `:1523-1528` → `RealProvider` `:1072-1075`). |

## B. Telegram send chokepoint

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 12 | `telegram_alert.send_telegram`: enable flag, router suppression, comms-gateway ownership, ledger publish | Alert storms, unrouted or unledgered operator messages | `scripts/telegram_alert.py:612-730`, `:36`, `:237-249` (router), `:332` (gateway owns) | T | run: YES, because lanes are existing scripts that use the chokepoint. model_job: N/A, since the receipt hard-codes `outbound/mutation = "blocked"` (`n8n_coordination_gateway.py:395-396`). | NO: a Telegram or email node or tool inside n8n sends with n8n's own credential, and nothing on the host intercepts it |
| 13 | Chokepoint static ratchet (`check_telegram_chokepoint.py`) | New direct Bot-API senders | `scripts/check_telegram_chokepoint.py:1-33`, `:209-268`; scan dirs `:45` (`scripts`, `apps`, `tests`); CI gate `scripts/run_cio_hardening_ci.py:1341-1343` | P | YES for repo code. NO for n8n workflow JSON, which is not scanned. | NO |

## C. LLM caps, reservation and deferral

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 14 | Global daily USD cap at the bridge | Host-wide paid overspend | `cio_governed_model_bridge.py:240`, `:1390-1394` (cap must exist), `:1409-1419`; *installed* drop-in `cio-governed-bridge.service.d/99-llm-global-cap.conf` | T | YES (model_job) | YES: any bridge call is capped |
| 15 | Per-process daily USD cap and request soft cap, reserved under an advisory lock | One lane eating the budget | `scripts/lib/llm_consumption.py:547-600` (check), `:794-860` (reserve; `:848` process, `:853` global) | T | YES | PARTIAL: billed to whichever process the claimed caller maps to (#22). An agent loop makes N reservations against that one process cap, and its spend is attributed to someone else's lane. |
| 16 | Reservation, settlement and provider request journal (replay block) | Unsettled spend; double dispatch of the same request id | `cio_governed_model_bridge.py:1423-1488`, `:1596-1640` | T | YES | PARTIAL: **the streaming path makes a second, unreserved provider call** (`:1895-1921`; see GAP H1) |
| 17 | `validate_paid_cap_config(require_global=True)` | A paid call with missing or zero caps | `cio_governed_model_bridge.py:1390-1394`; `scripts/lib/consumption_run_manual.py:210` | T | YES | YES |
| 18 | `provider_cost.budget.ensure_budget_allows_call` (non-bridge paths) | Direct provider calls without a global cap | `scripts/lib/provider_cost/budget.py:43-100` | T | YES for lanes that use it | N/A |
| 19 | Off-peak deferral (`lib/llm_deferral`) | Paying DeepSeek peak prices for non-urgent work | `scripts/lib/llm_consumption.py:1128-1160`; `scripts/lib/llm_deferral.py:69` (`LLM_DEFER_OFFPEAK`), `:95`, `:220` | T, **env-armed** | **NO.** Run: the executor env lacks `LLM_DEFER_OFFPEAK=1`, which cron gets from crontab line 9, so a lane moved from cron to n8n silently loses deferral. model_job: the bridge has no deferral (0 occurrences of "defer" in `cio_governed_model_bridge.py`). | NO |
| 20 | Bridge circuit breaker, `MAX_INFLIGHT=4`, upstream deadline | Provider fault storms; thread exhaustion | `cio_governed_model_bridge.py:185-199`, `:1323-1329`, `:1836-1840` | T | YES | YES |
| 21 | Server-side model policy: client model ignored, legacy ids rejected, policy allowlist, unknown routing policy refused | Caller choosing model or provider | `cio_governed_model_bridge.py:1307-1316`, `:1350-1384`, `:1816-1823` | T | YES | YES |

## D. Bridge caller identity

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 22 | `CALLER_PROCESS_MAP` and `CALLER_TASK_PROCESS_MAP` resolution | Callers relabelling themselves; client-chosen process | `cio_governed_model_bridge.py:54-89`, `:291-302`, `:1749-1760` | T, but **identity is an unauthenticated header** (`X-TradeAI-Agent`, `:50`) | YES for model_job: the header and task type are set server-side (`n8n_model_job.py:393-394`, task type from `PROCESS_TASK_TYPE` `:41-44`, gateway check `n8n_coordination_gateway.py:389-390`) | **NO**: the n8n node would set `X-TradeAI-Agent` itself and could claim `alex`, `advisory_desk` or any other caller. Only a loopback bind protects the bridge today (`:1943-1944`). |
| 23 | Client `process_id` rejected | Process injection through the body | `cio_governed_model_bridge.py:1826-1832` (literal `alex_cio_synthesis` passes but is ignored) | T | YES | YES, but moot given #22 |
| 24 | Ring 2 memory-context requirement (`X-TradeAI-Context-Id`) | Research-class calls without MemoryContext | `cio_governed_model_bridge.py:1765-1788` (any non-428 exception is swallowed, `:1787-1788`) | T, fail-open | PARTIAL | PARTIAL |

## E. §2A egress and prompt sanitisation

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 25 | §2A single egress sanitiser (`sanitise_for_external`) | Credentials, account ids, PII and position dollars reaching an external provider | **Does not exist.** `AGENTS.md:283-322` ("No such function exists today … Proposed, not built"); no definition anywhere in the repo | Pol | PARTIAL: model_job is template-only (#27), but the **artifact body is sent unscanned** (`n8n_model_job.py:269`, `:275`) from `data/runtime` or `data/cio` (`:26`) | **NO**: free-text `messages` go verbatim to the provider (`cio_governed_model_bridge.py:1801-1805` → `:1523`) |
| 26 | Gateway `_reject_secret_material` (key names and value regex) | Secrets in job or run fields | `n8n_coordination_gateway.py:97-114`, `:683-691`, applied at `:323-326` (run) and `:378` (job) | T | YES for request fields only, not artifact content | NO |
| 27 | Server-side prompt templates (`N8nPromptTemplate@v1`): placeholder whitelist, template-to-process binding, no raw prompt field | n8n supplying prompt text | `n8n_model_job.py:48-51`, `:103-139`, `:254-283`; gateway job field set `n8n_coordination_gateway.py:353-358` | T | YES | NO |
| 28 | Artifact resolution: allowlisted stores, no `..`, size cap, sha256 match | Arbitrary file reads into a prompt | `n8n_model_job.py:26-27`, `:197-212` | T | YES | NO |
| 29 | Log sanitisation (prompt and response hashed in the call log) | Prompt content landing in logs | `cio_governed_model_bridge.py:791`, `:1677-1690` | T | YES | YES |

## F. Output schema validation

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 30 | model_job output checks: JSON parse, structural schema, `forbidden_keys`, `governance_pass`, process_mismatch, `no_cost_receipt` | Off-contract or action-bearing model output; uncosted calls | `n8n_model_job.py:330-352` (`:344` validate, `:347` forbidden keys, `:352` cost receipt); schemas `config/schemas/n8n_model_job_outputs.json` | T | YES | **NO**: the bridge passes `response_format` through and returns the raw completion, including `tool_calls` (`cio_governed_model_bridge.py:1812`, RealProvider `:1082-1083`) |
| 31 | `gate_and_generate(output_schema_id=…)` | Non-JSON answers | `llm_consumption.py:1059`, `:1308`: **JSON mode only, no schema validation** | T, partial | PARTIAL | N/A |

## G. One writer per store, scheduling exclusivity

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 32 | `check_data_source_authority` (WRITER_COUNT_ROSE, undeclared or unapproved source) | Second writers or new providers | `scripts/check_data_source_authority.py:26-31`, `:199-283`; CI tests `run_cio_hardening_ci.py:725,734` | P | YES: same scripts, same writers | PARTIAL: writes made by n8n nodes (n8n's own DB, HTTP nodes) are outside the scan |
| 33 | Lane host-conflict classifier (CRON_PRESENT / TIMER_ENABLED while scheduler is n8n) | Double scheduling of a lane | `scripts/lib/n8n_lane_host_conflict.py:12-17`, `:74`; CI `run_cio_hardening_ci.py:3507` | P | YES | N/A |
| 34 | Coordination ledger: single-transaction writes (`BEGIN IMMEDIATE`), run idempotency | Duplicate runs; racing writers | `scripts/lib/n8n_coordination_ledger.py:208`, `:337`, `:408-425`, `:508-520`; gateway `_run` `n8n_coordination_gateway.py:309-349` | T | YES | NO: no ledger on the bridge path |

## H. Guard and grant system, git hooks

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 35 | Cursor guard hooks (shell, read, write classifiers; secret and gate deny; grants ledger) and `bin/guard` | Agent DB writes, cron, push, service or secret access without a grant | `.cursor/hooks.json` (paths hard-coded to `/home/johnclaw/tradeai-wt-cursor-guardrails`); `.cursor/hooks/guard-lib.sh:35-49`; `guard-shell.sh:68-100`; `bin/guard:87-131` | T for the Cursor agent only | NO: n8n never passes through an IDE hook | NO |
| 36 | pre-push remote sync gate (authorization flag or guard grant, push budget) | Unauthorized pushes | `.githooks/pre-push:15-112`; `scripts/lib/guard_push_auth.py:87` | P (local; `--no-verify` bypasses) | N/A (n8n does not push) | N/A |
| 37 | Secrets scan, pre-commit and pre-push | Credentials committed | `.githooks/pre-commit:6`; `.githooks/pre-push:120-125` (**`TRADEAI_SKIP_SECRETS_SCAN=1` bypass**); **no secret scan in any `.github/workflows/*.yml`** (grep) | P | NO for n8n workflow exports (`scripts/n8n_export_workflows.py`): scanned only locally, if committed | NO |

## I. CI gates

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 38 | `run_cio_hardening_ci.py` `GATES` (328 entries), including the n8n packs | Regressions in governed code, including gateway, relay, executor and model_job tests | `scripts/run_cio_hardening_ci.py:25-3631` (n8n `:3452-3534`); workflow `.github/workflows/cio-production-hardening-ci.yml:79-81`, `:254` | P | YES for host code. NO for workflow JSON or prompts edited in the n8n UI. | NO: agent prompt and tool configuration live in n8n's DB |
| 39 | Dark-contract guard | New uncalled versioned schemas | `cio-production-hardening-ci.yml:91` → `scripts/check_dark_contracts.py` | P | YES (code) | NO |
| 40 | Host-path ratchet | Live-host paths in tests | `cio-production-hardening-ci.yml:118` → `scripts/check_test_host_paths.py` | P | YES (code) | NO |
| 41 | Line-ending churn | MIXED/CRLF churn | `cio-production-hardening-ci.yml:103` → `scripts/check_line_endings.py` | P | YES (code) | NO |
| 42 | docs/INDEX drift | Docs index out of date | `run_cio_hardening_ci.py:4031-4039` | P | YES (code) | NO |

## J. Locks and market gate

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 43 | `safe_flock.sh` | Concurrent runs of one lane | `scripts/safe_flock.sh:74-104`: PID file plus `kill -0`, **check-then-write is not atomic**. Executor wraps every lane with it (`n8n_run_executor.py:135-143`). | T | YES (same lock as cron) | N/A |
| 44 | `market_day_gate.sh` | Weekend and holiday runs | `scripts/market_day_gate.sh:25-50`: **fails open** on any check error. Executor inserts it only when `market_gate=true` (`n8n_run_executor.py:140`); 0 of 14 lanes set it. | T | PARTIAL | N/A |

## K. systemd unit limits

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 45 | MemoryMax and CPUQuota | Runaway processes | gateway `config/systemd/user/tradeai-n8n-coordination-gateway.service:29-30` (256M, 20%); relay `tradeai-n8n-run-relay.service:34-35` (128M, 10%); executor `tradeai-n8n-run-executor.service:26` (1G, **no CPUQuota**); bridge repo unit `cio-governed-bridge.service:32` (768M), installed via `90-memory.conf`, no CPUQuota | T | PARTIAL: lanes run as executor children inside **one shared 1G cgroup**, unlike cron's per-job scope. That is a behaviour change on cutover. | PARTIAL: bridge 768M plus `MAX_INFLIGHT=4`, no CPU limit |

## L. n8n coordination gateway

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 46 | HMAC claim (exact field set, v=1, project allowlist, lifetime ≤300s, skew 5s, `compare_digest`, key rotation) | Forged or long-lived claims | `n8n_coordination_gateway.py:63`, `:115-116`, `:612-669` | T | YES | NO |
| 47 | Nonce replay (atomic read-then-consume; durable ledger store) | Replay | `n8n_coordination_gateway.py:671-680`; `n8n_coordination_ledger.py:408-425` | T | YES | NO |
| 48 | Scopes (read and run are disjoint; relay key has run+read; dispatch key read only; relay id never falls back to the default key) | Read caller running lanes; run caller transitioning events | `n8n_coordination_gateway.py:28-35`, `:177-210`, `:277-286`, `:636-645` | T | YES | NO |
| 49 | Typed refusal enum | Untyped or ambiguous failures | `n8n_coordination_gateway.py:141-153`, `:714-717` | T | YES | NO |
| 50 | Bind guard (127.0.0.1 only, key required, origin SHA required, blocked ports), 64 KiB body cap | Exposure; unauthenticated bind | `scripts/n8n_coordination_gateway.py:54`, `:72-84`, `:255`, `:315-319` | T | YES | NO |
| 51 | Event state machine (`EDGES`) and stale-origin-SHA check | Illegal transitions; events from an old release | `n8n_coordination_gateway.py:129-140`, `:144`, `:576-606` | T | YES | NO |
| 52 | Run-lane allowlist and mode check at request time | Unlisted lanes | `n8n_coordination_gateway.py:327-331`; loaded once at serve (`scripts/n8n_coordination_gateway.py:324-325`) | T | YES | NO |

## M. Relay

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 53 | Bearer auth (`compare_digest`, previous-bearer rotation, ≥32-byte secrets) | Unauthenticated run requests | `scripts/n8n_run_relay.py:41-47`, `:90-106`, `:245-259` | T | YES | NO |
| 54 | Bind guard (127.0.0.1, or 172.16-31.x.1 docker gateway only; port ≥1024, not blocked) | Exposure beyond the docker bridge | `n8n_run_relay.py:71-87` | T | YES | NO |
| 55 | Live-lanes flag (`TRADEAI_N8N_RELAY_LIVE_LANES`) | `mode=live` on lanes not explicitly enabled | `n8n_run_relay.py:44`, `:200`, `:290-291` | T | YES | NO |
| 56 | 1 KiB body cap, lane allowlist, run-id shape; relay mints its own claim (n8n never holds the HMAC key) | Oversized or forged requests | `n8n_run_relay.py:46`, `:276-310` | T | YES | NO |

## N. Executor

| # | Guardrail | Prevents | Enforcement point | Kind | n8n path | n8n Agent |
|---|---|---|---|---|---|---|
| 57 | Allowlist validation at execution (malformed entries dropped; missing lane gives RUN_REFUSED) | Running unlisted commands | `scripts/n8n_run_executor.py:76-121`, `:201-207`; **loaded once at start** (`:346`), not re-read per run | T | PARTIAL: a lane removed from the file keeps running until a restart | NO |
| 58 | Lock and timeout wrapper (`safe_flock`/`flock -n`, `timeout -k 30`, executor deadline) | Overlap with cron; hung lanes | `n8n_run_executor.py:128-143`, `:213-233` | T | YES | NO |
| 59 | RunReceipt@v1 (ledger row plus file; exit code, lock skip, timeout, output-signal mtime, code SHA) | Silent success or failure | `n8n_run_executor.py:57`, `:179-199`, `:259`, `:294-301` | T | YES | NO |

**Row count: 59.**

---

## Counts

| | YES | PARTIAL | NO | N/A |
|---|---|---|---|---|
| n8n path (run / model_job) | 44 | 11 | 3 | 1 |
| n8n Agent via bridge | 11 | 7 | 35 | 6 |

Counted by the leading verdict in each row. Mixed cells such as #12 are counted by their first verdict.

The n8n path column is dominated by YES. The executor runs existing scripts, so their in-process rails come along, and the gateway, relay and executor add their own. For an n8n Agent, almost every n8n-specific rail is NO. Those rails live on the gateway or in model_job, and an Agent would bypass both. The bridge on its own keeps only cost and model-policy rails, plus broker safety, which holds because there is no network path to it.

## GAPS

**High**
- **H1. Bridge streaming makes a second, unreserved provider call.** `do_POST` runs `execute_governed_call` (reserves, calls, settles) and then, for `stream=true` in canary mode, `_send_stream` calls `provider.generate` again (`cio_governed_model_bridge.py:1867-1869`, `:1918-1921`). There is no reservation, settlement, journal or cost event. An n8n chat-model node that streams would double-bill outside the caps. **Fix:** in `_send_stream`, re-emit the already-governed `result` as SSE and never call the provider.
- **H2. Bridge caller identity is a self-asserted header.** `X-TradeAI-Agent` is matched against a name map with no secret (`:50`, `:1749-1760`). Any process that can reach the port can claim any caller and spend that caller's budget. **Fix:** per-caller HMAC or bearer keys (as the gateway does at `n8n_coordination_gateway.py:168-210`), with the caller derived from the key, never the header.
- **H3. No §2A egress filter exists anywhere.** `AGENTS.md:316-322` says it is not built. model_job forwards artifact bodies unscanned (`n8n_model_job.py:269`, `:275`), and the bridge forwards any free text. **Fix:** build `sanitise_for_external()` inside `execute_governed_call` before Step 7 (`:1492`). It should cover account-id, credential and PII patterns plus position-dollar fields, refuse with a typed code, and carry a test that a forbidden field cannot pass.
- **H4. The bridge passes client `tools` and `tool_choice` to the provider and returns `tool_calls` unvalidated** (`:1810-1811`, RealProvider `:1072-1075`). With an n8n Agent, n8n would execute whatever tool the model names. **Fix:** per-process tool allowlist in the registry; refuse unknown tool names at the bridge; strip `tool_calls` whose name or arguments fail an allowlist and schema check.

**Medium**
- **M1. Off-peak deferral is lost on cutover.** The executor env lacks `LLM_DEFER_OFFPEAK=1`, which cron gets from crontab line 9 (installed executor unit `:18-21`), and the bridge has no deferral at all. **Fix:** add `Environment=LLM_DEFER_OFFPEAK=1` (plus the other crontab-global vars) to the executor unit, and add a crontab-env parity test to the n8n readiness gate.
- **M2. Executor passes its full env to every lane** (`n8n_run_executor.py:337`, `:216`). The runtime env holds the gateway dispatch key, the relay run-scope key and the relay bearer. **Fix:** strip `TRADEAI_N8N_*` keys from the child env, or allowlist the child env.
- **M3. No server-side output validation on the bridge.** Only model_job validates (`n8n_model_job.py:344-352`). **Fix:** a per-process `output_schema_id` in the registry, validated in `execute_governed_call` after Step 8 with `forbidden_keys` and a behaviour-field scan (reuse `_scan_behavior`, `intelligence_client.py:~895`).
- **M4. Protective-stop envelope is a pass-through** (`protective_stop_policy.py:30` `GATES_REMOVED=True`). 2FA is the only remaining rail. **Fix:** operator decision whether to restore the envelope. Record it in the risk register either way.
- **M5. No CI secret scan; local hook has an env bypass** (`.githooks/pre-push:120`, no secret-scan step in workflows). n8n workflow exports are a new leak vector. **Fix:** add a `check_no_secrets.py --tree` step to `cio-production-hardening-ci.yml`, and a credential-field scan to `n8n_export_workflows.py`.
- **M6. Telegram chokepoint does not cover n8n.** An n8n Telegram or email node is invisible to `send_telegram` and to the ratchet (`check_telegram_chokepoint.py:45`). **Fix:** refuse n8n credentials of type Telegram, SMTP or Gmail in the n8n readiness or export check, and route n8n alerts through a gateway event that host code delivers.
- **M7. Executor lanes share one 1G cgroup with no CPUQuota** (`tradeai-n8n-run-executor.service:26`). One heavy lane can OOM-kill the executor and stall every n8n lane. **Fix:** spawn each lane through `systemd-run --user --scope -p MemoryMax=… -p CPUQuota=…`, with per-lane limits in the allowlist.

**Low**
- **L1.** Executor and gateway load the allowlist once (`n8n_run_executor.py:346`, `scripts/n8n_coordination_gateway.py:324-325`). **Fix:** re-read per claim, or compare the file's mtime and SHA before each execute.
- **L2.** `safe_flock.sh` check-then-write is not atomic (`:74-96`). **Fix:** wrap the PID logic in `flock -n` on the lock file.
- **L3.** `market_day_gate.sh` fails open on errors (`:25-50`), and no n8n lane sets `market_gate`. **Fix:** fail closed for market-gated lanes, and declare `market_gate` explicitly per lane.
- **L4.** The Ring 2 check on the bridge swallows non-428 exceptions (`:1787-1788`). **Fix:** record the miss on the call log instead of `pass`.
- **L5.** Cursor guard hooks are pinned to one worktree path (`.cursor/hooks.json`) and do not cover Claude Code or n8n. **Fix:** document the coverage, or add the equivalent Claude Code hooks (config, out of scope here).

**Gaps by severity: High 4, Medium 7, Low 5 (16 total).**

---

## What the bridge would need to expose an OpenAI-compatible endpoint to an n8n Agent without losing any of the above

1. **Network and caller identity.** Add a separate listener on the docker gateway address (as the relay does, `n8n_run_relay.py:71-87`). Keep `start_server`'s loopback guard (`cio_governed_model_bridge.py:1943-1944`) for the existing port. Authenticate with a per-caller secret (`Authorization: Bearer`, `compare_digest`, rotation overlap) that maps to **one** registered process such as `n8n_agent_<name>`. Never read `X-TradeAI-Agent` or `X-TradeAI-Task-Type` on that listener (fixes H2).
2. **Template-only prompts or free text.** The safest option keeps §23.4's "template id is the only prompt input" (`AGENTS.md:3955-3968`): accept `template_id` plus `artifact_ref` and render server-side with `n8n_model_job.build_messages`. Allowing free text needs an AGENTS §17 operator decision, and **must** first pass every message through the H3 `sanitise_for_external()`, with a hard input-size cap and a refusal (never redaction) on a forbidden-field hit.
3. **Caps.** Keep Steps 5-6 (`:1388-1453`) unchanged. Add a dedicated registry row with a small `daily_cost_cap_usd` and `daily_soft_cap`, a per-conversation turn cap (an Agent loops), a clamp on `max_tokens`, and off-peak deferral or refusal (M1). Fix H1 first, or reject `stream=true` on this listener.
4. **Schema validation.** Require `response_format` json_schema bound server-side to the process (`output_schema_id` from the registry, never from the client). Validate with `n8n_model_job.validate` and `forbidden_keys`, plus a behaviour-field scan (MBI_BEHAVIOR=0), before returning. Fail with a typed refusal.
5. **Egress filter.** Run the same sanitiser on outbound content and on tool-call arguments. Credentials, account ids and PII never leave in either direction, and position dollars stay out until the operator decides §2A.
6. **Tool-call restrictions.** Keep a per-process tool allowlist in the registry. Refuse requests whose `tools` contain names outside it. Strip or refuse response `tool_calls` with unknown names or schema-invalid arguments. Never allow tools whose names hit `FORBIDDEN_ROUTE_TOKENS` (`n8n_coordination_gateway.py:64-96`). Pair this with n8n-side policy that the Agent's only HTTP tool targets are the relay and gateway (no Telegram, email or HTTP-to-host nodes), and keep 2FA and execution_guard as the unconditional backstop for anything financial.
7. **Receipts and audit.** Write a ledger row per Agent turn (caller, process, reservation_id, schema id, tool names, sanitiser verdict), as RunReceipt@v1 and N8nModelJobReceipt@v1 do, so the Agent path is as auditable as the run and model_job paths.

*NOT VERIFIED:* whether any of the 14 allowlisted lanes calls the MBI rails (#1-3); whether n8n's chat-model node streams by default (it decides whether H1 triggers); how `config/llm_process_registry.json` caps the two `n8n_*` processes (config, left to the sibling audit).
