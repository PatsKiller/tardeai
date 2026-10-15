# n8n automation fabric — threat model

```
Status:      PROPOSED (informational; AGENTS.md is normative). Closes the "no threat model" part of audit DD02.
as_of:       2026-10-15 (runtime facts measured 2026-10-15 ~13:03Z on ms01-openclaw, names and modes only)
Basis:       N8N_REFERENCE_ARCHITECTURE.md §4-§6, §9 (planes, B1-B5, routes, controls)
Audit:       independent due diligence 2026-10-15 (pinned e355be188), §2, §4, §11 and DD01/DD02/DD08/DD11/DD13/DD17
Owner:       platform security (ROLE to confirm); Chief Architect: Agent A
Companions:  AUDIT_20261015_FINDINGS.md (tracker), N8N_DECISION_LEDGER.md (D1-D9),
             ENV_ENFORCE_READINESS_20261015.md (executor env measurement), N8N_HITL_CONTRACT_SPEC.md,
             N8N_LLM_STEP_ROUTE_SPEC.md
```

**Status markers.** **(E)** exists in code and, where stated, is measured on the host on 2026-10-15. **(P)** proposed,
not built. **(R)** exists in **report** (log-only) mode: it measures, it does not confine.

**The one-line conclusion.** The fabric's controls are sound against an *honest-but-buggy* n8n workflow and an
*outside* network attacker. They are **not** confinement against a compromised component running as host uid
`johnclaw` (1000): every host service, every lane and the relay/gateway/executor share that uid, so any of them can
read the HMAC keys, the rendered env file, the checkout `.env`, the coordination ledger and the allowlist, and can
`systemctl --user` the others. Report-mode controls (§5) record that exposure; they do not reduce it. This is the
audit's DD02 finding and it is accepted here as the top residual risk.

---

## 1. Scope and method

STRIDE (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege) is
applied per trust boundary B1–B5 of the reference architecture §5. Each threat names the mitigation that exists (E),
the one that is proposed (P), or that it is report-only (R), and the residual risk with an owner role. Owners are
**roles to confirm**, not invented names (audit §14, §17 last paragraph).

Out of scope: the broker execution subsystem itself (AGENTS.md §0 rule 2, §22) except as a target the fabric must
never reach, the NYC DOF instance (§24.4), and physical/host-OS compromise (DD12 covers host loss).

## 2. Assets

| # | Asset | Where | Why it matters | Confidentiality / integrity / availability |
|---|---|---|---|---|
| A1 | Broker authority (orders, stops, account reach, 2FA/TOTP, broker credentials) | broker subsystem, env names `ALPACA_*`/`SCHWAB_*`/… | money; §0 rules 1-2 | C, I |
| A2 | Coordination HMAC keys (dispatch key, relay run-scope key, `_PREVIOUS` overlaps) and relay bearer | executor/gateway/relay unit env (`%t/tradeai/env`, `n8n-gateway.env`) | forge run requests and intents | C |
| A3 | Run allowlist, lane registry, effect-key config, comms routes, retry policy | `config/*.json` in the served/dev tree | define what may run and how | I |
| A4 | Coordination ledger (runs, run_outcomes, comms_intents, dead_letters, breakers, effect_claims) | `persistent-state/data/governance/n8n_coordination_ledger.sqlite` | the audit of record; effect exactly-once | I, A |
| A5 | Receipts and lane outputs | `data/runtime/n8n_runs/`, `<lane>_last.json`, `trade_ai` tables | output truth (D9) | I |
| A6 | Operator delivery channel (Telegram bot token, caps, quiet hours) | comms gateway, `send_telegram` | P0/P1 pages; spam/suppression | C, I, A |
| A7 | LLM provider credentials and spend | governed bridge `:8766`, OAuth transports `:8645`/`:8646` | cost; prompt-injection blast radius | C, A |
| A8 | `trade_ai` Postgres and its credentials (`DB_*`) | host | business truth | C, I |
| A9 | n8n's own Postgres + encryption key + the one credential `tradeai-run-relay` | `m8m-n8n-db`, container | flow state; a workflow-UI edit is a control-plane change | C, I |
| A10 | Service management (systemd user units, drop-ins, crontab) and the guard ledger | host uid `johnclaw` | who can change all of the above | I |
| A11 | Command Center `:7777` (service listener) and its serve-proxy listener | `portfolio_server.py`, `config/cc_auth.yaml` | privileged operator surface; stop routes | I, A |

## 3. Adversaries and trusted actors

| Id | Actor | Capability assumed | Trusted for |
|---|---|---|---|
| T0 | Operator (FIDO2 key, Telegram session) | everything; §17 decisions | authority (trusted) |
| T1 | Trusted deployment (release/promote under guard grant) | writes served tree, unit drop-ins | deploying reviewed code (trusted, audited) |
| X1 | **Compromised n8n container** (malicious workflow, compromised n8n release/community node, UI editor abuse, n8n RCE) | arbitrary code as container uid `node` (numeric uid **1000**, measured), holds the relay bearer, network to `172.19.0.1:18092` | nothing beyond flow |
| X2 | **Compromised or buggy local agent / lane process running as uid `johnclaw`** (an agent session, a lane with a dependency compromise, a prompt-injected LLM-driven lane) | everything uid 1000 can do on the host: read every env file and `.env`, HMAC keys, ledger; edit config; `systemctl --user` | nothing |
| X3 | Prompt injection via ingested content (news, social, research, filings) reaching an LLM step | controls model output text | nothing |
| X4 | Tailnet peer / network attacker | reach tailnet-exposed ports (CC via `tailscale serve`) | nothing |
| X5 | Malicious or mistaken edit to a control file in git (allowlist, routes, effect config) | a PR | nothing until reviewed |
| X6 | Supply chain (n8n image, Python deps, OAuth proxies) | code inside a trusted process | nothing |

## 4. STRIDE per trust boundary

### B1 — n8n → relay (`172.19.0.1:18092`, bearer)

| STRIDE | Threat | Mitigation | Status | Residual (owner role) |
|---|---|---|---|---|
| S | X1 or any docker-bridge peer presents the bearer | bearer + `_PREVIOUS` rotation; relay binds the docker bridge only (measured LISTEN `172.19.0.1:18092`) | (E) | bearer is a single shared credential; any container on that bridge network that obtains it is "n8n" (platform) |
| S | caller identity of the *workflow* is self-asserted (`requested_by: n8n:workflow:<id>`) | none server-bound | (P) | the relay cannot tell which workflow called (platform; DD02/DD03) |
| T | body tampering / unknown keys | `MAX_BODY` 1024 B; exact-key intent bodies | (E) intents; **POST /run discards unknown extra keys** (audit §3) | DD14 (agent 1) |
| T | route-table bypass | fixed `ROUTES`; `GET /momentum-lifecycle` served **outside** `ROUTES` (R2) | (E) partial | DD14 (agent 1) |
| R | n8n denies a request | `relay_log.jsonl` line per call; ledger row on run/intent | (E) | log is uid-1000 writable (X2 can rewrite) |
| I | bearer/DSN/token leaks in intent text | `_REDACT_RES` redaction; `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` (measured `true` in container) | (E) | — |
| D | request flood from n8n | body cap; gateway rate bound per route; executor class caps | (E) partial | no per-workflow quota (platform) |
| E | n8n reaches a host route beyond the table, or the host firewall lets it reach `:18091`/`:7777`/`:8766` | relay is the one door; gateway/bridge/CC bind loopback (measured); container uid 1000 mounts **not verified** (inspect refused by this session's tool classifier — operator command in §7) | (E) binds; (P) firewall check FW-S4 | if any host path is bind-mounted read-write, X1 has uid-1000 file access to it (platform; verify) |

### B2 — relay → gateway (`127.0.0.1:18091`, HMAC claim)

| STRIDE | Threat | Mitigation | Status | Residual (owner role) |
|---|---|---|---|---|
| S | X2 signs claims as `n8n-relay` or any `tradeai-*` caller | relay key is separate from dispatch key; dispatch key is the **default for every unnamed `tradeai-*` caller_id** (`resolve_caller`), i.e. caller_id is self-asserted under a shared key | (E) key split; caller identity **not** principal-bound | any uid-1000 process can read both keys from the unit env file and impersonate any caller (platform; DD02) |
| S | replay of a claim | `iat/exp/nonce`; idempotency store | (E) | — |
| T | cross-lane/mode duplicate key returns another lane's outcome as success | — | **contradicted** (audit §5 probe) | DD03 (agent 1) |
| T | `p:` keys accepted on the legacy path | — | **contradicted** | DD03 (agent 1) |
| R | who requested a run | ledger `requested_by` | (E) | self-asserted (see S) |
| I | ledger read by n8n | read scope returns projections only | (E) | — |
| D | gateway refusal storm hides real failures | refusals are data (D3) | (E) partial | DD04 (agent 1) |
| E | revoked allowlist row still admitted (startup-cached policy) | contracts claim per-request re-read; **source caches at startup** (audit §4) | **contradicted** | DD08 (agent 1) |

### B3 — executor → lane process (spawn allowlisted argv)

| STRIDE | Threat | Mitigation | Status | Residual (owner role) |
|---|---|---|---|---|
| S | a lane pretends to be another lane | per-lane lock; argv only from allowlist | (E) | — |
| T | a lane edits A3/A4/A10 (allowlist, ledger, units) | **none**: lanes run as uid `johnclaw` | **gap** | X2 = full authority-plane compromise (platform; DD02, TRK-31 uid split) |
| R | lane denies a write | receipts, ledger outcome | (E) | receipts mutable by the lane (DD07, agent 1) |
| I | lane child inherits secrets it does not need | n8n secret strip in every mode (E); env allowlist: global `TRADEAI_EXECUTOR_ENV_ALLOWLIST=enforce` **measured on the unit**, but **91 of 103 lanes are pinned `env_allowlist_mode: report`** and keep the full pre-P7 env (incl. broker names rendered into the env file); `env_bootstrap` bound mode denies broker names only inside an *enforced* child | (E) 12 lanes; **(R) 91 lanes** | §6 below; even an enforced lane can read the checkout `.env` from disk (same uid) — the allowlist is least-privilege hygiene, not confinement |
| D | runaway lane | `timeout -k`, class caps, breakers | (E) | — |
| E | lane spawns a sender or broker path transitively | allowlist never-list checks argv/filename, not the closure; `trade-ai-scalp-live` reaches `continuous_runner` → Slack/Twilio raw transports | **contradicted** (audit §4) | DD01 (agent 3) |
| E | effect replayed after partial effect (FAILED reclaim) or by a fenced late worker | effect claims opt-in; owner epoch fences admission only | **contradicted** | DD05/DD06 (agent 1) |

### B4 — comms gateway → operator (only sender)

| STRIDE | Threat | Mitigation | Status | Residual (owner role) |
|---|---|---|---|---|
| S | n8n or a lane sends directly | n8n has no bot token; forbidden node types; intents only | (E) for n8n; **contradicted** for one lane (DD01) | communications (agent 3) |
| T | intent text shapes an operator decision (prompt-injected digest) | closed route table, DIGEST class, redaction | (E) | content still model/lane authored (communications) |
| R | delivery not provable | delivery ledger on `send_telegram`; **intent → consumer → fan-in → sender → delivery receipt chain not yet proven end to end** | (P) | DD11 (this tracker) |
| I | secrets in messages | relay redaction; bridge egress sanitiser **(R)** `TRADEAI_EGRESS_SANITISER=report` (measured `report` on bridge `/health`) | (E)/(R) | §5 row 4 |
| D | caps/quiet hours suppress a P1 (SPCX 10-14 class) | P0/P1 independent of n8n (§24.1); stop-health warnings were demoted to digest — fixed #1732/#1733/#1734/#1737 LIVE at `5aa61048d` | (E) fixes deployed; effective operation **needs evidence**; incident CONTAINED not RESOLVED | DD11 (communications + operator) |
| E | generic DIGEST route used for critical safety | critical classes must stay on the protected path | (E) policy; (P) proof | DD11 |

### B5 — operator → execution (money class)

| STRIDE | Threat | Mitigation | Status | Residual (owner role) |
|---|---|---|---|---|
| S | an n8n "approved" branch, callback URL or wait-node resume treated as approval | n8n can notify, never confirm; per-order operator assertion | (E) policy; route **(P)** | N8N_HITL_CONTRACT_SPEC.md (Level 1, specified) |
| T | intent altered between approval and effect | bind `H(intent)` and re-verify at effect | (P) | HITL spec §4 |
| R/I/D | — | trading lock LIVE, LOCKED (TRK-4) | (E) | operator |
| E | money authority by analogy through a non-money route | `FORBIDDEN_ROUTE_TOKENS`, generator forbidden nodes, never-list; trading lock refuses every order whatever the caller | (E) at the declared surface | transitive lazy broker reach accepted by operator 2026-10-15 (RR11, DD01) |

### Cross-boundary surfaces the audit asked to include

| Surface | Threat | Status | Residual |
|---|---|---|---|
| Command Center `:7777` service listener | any local process calls stop/write routes | `config/cc_auth.yaml` `enforce: true, report_only: true` **in the served release** (`ea14e1c3a`); decision log 57,503 would-deny lines 2026-10-14T22:10Z → 2026-10-15T13:04Z, 56,306 of them "service token not configured (file missing)"; hard routes (secret writes) and step-up refuse even in report mode (1 hard refusal logged) | **(R)**; flip blocked on operator packet `cc-tailscale-identity-20261014` (token not generated) |
| Governed bridge `:8766` | any local process calls models as any caller (self-asserted `X-TradeAI-Agent`) | `TRADEAI_BRIDGE_CALLER_AUTH` default `report`; an **invalid value falls back to report** (`caller_auth_mode`); measured `report`; since last restart 2 callers (`advisory_desk`, `n8n_model_job`), 17 calls, **17/17 `no_key_configured`** | **(R)**; enforce today would refuse 100% of measured calls |
| OAuth proxies `:8645` (grok) / `:8646` (chatgpt) | loopback callers use provider OAuth sessions directly, bypassing the bridge | loopback bind (measured LISTEN 127.0.0.1); enabled by `CIO_BRIDGE_OAUTH_TRANSPORTS`; bridge `/health` transports `chatgpt, deepseek, grok` | X2 can call the proxies directly (bridge owner) |
| Control-file rewrite (A3) | X2 or X5 widens the allowlist | git review + guard `config-write` grant for the served tree; **dev tree is what executes for cron** (memory: dev tree executes) | uid 1000 can write both trees (platform) |
| Prompt injection (X3) | model output names an action | D8: process + template, closed schema, enum branching, host re-check (E at bridge; host action re-check **(P)**) | DD17 |

## 5. Report-mode controls — what each would take to flip

Every row is measured 2026-10-15 ~13:03Z (names and modes only). "Flip" is an operator decision or a grant-gated
unit/config change; this document flips nothing.

| # | Control | Switch (exact) | Current (measured) | Evidence required before the flip | Blocker |
|---|---|---|---|---|---|
| 1 | Executor per-lane env allowlist | per lane: `config/n8n_run_allowlist.json` `env_allowlist_mode: "report"` → `"enforce"` (global `TRADEAI_EXECUTOR_ENV_ALLOWLIST=enforce` already set on `tradeai-n8n-run-executor.service`) | 12 enforce / 91 report | per lane: static closure READY (ENV_ENFORCE_READINESS_20261015.md), the lane added to `test_enforced_inventories_cover_every_literal_read_in_the_import_closure`, one enforced dry_run receipt with `env_allowlist.effective_mode=enforce`, non-empty output | 3 lanes READY_NOW, 6 READY_WITH_RESIDUAL, 82 BLOCKED (§6) |
| 2 | Bridge caller authentication | `TRADEAI_BRIDGE_CALLER_AUTH=enforce` in a `cio-governed-bridge.service.d` drop-in; plus `TRADEAI_BRIDGE_CALLER_KEY_<CALLER>` (≥32 chars) rendered per caller; plus every caller sending `Authorization: Bearer` | `report` (default; invalid → report) | `bridge_caller_auth_report.jsonl` + `/health` `caller_auth.counts` show **0 non-`verified`** verdicts across ≥1 full weekday cycle of every registered caller; fail-closed fix so an invalid mode becomes `enforce` (code change, bridge owner) | no caller has a key (17/17 `no_key_configured`); keys are an operator secret render (§17) |
| 3 | Command Center auth | drop-in `TRADEAI_CC_AUTH_REPORT_ONLY=0` on `portfolio-server.service` (packet step 6) | `enforce: true`, `report_only: true` | service token file generated (operator), `tailscale serve` re-pointed to the serve-proxy listener, decision log shows 0 would-deny for 24 h from known callers | token file missing (56,306 would-deny) |
| 4 | Egress sanitiser | `TRADEAI_EGRESS_SANITISER=enforce` on the bridge | `report` | `egress_sanitiser_report.jsonl` match counts reviewed; no false redaction of required tickers/numbers in a replay set | review of categories (bridge owner) |
| 5 | Incident flood policy | `TRADEAI_INCIDENT_FLOOD_POLICY_MODE=enforce` (fan-in) | `report_only` (default) | flood-rule summaries on receipts show no suppressed P0/P1 | communications owner |
| 6 | Broker env-name read audit | `TRADEAI_BROKER_ENV_AUDIT=1` is **log-only by design** (step 1 of 3) | audit | step 2/3 (deny) is an operator decision (§17) | operator |
| 7 | Gateway caller identity | not a mode: shared dispatch key is `default=True` for every `tradeai-*` caller_id | shared key | per-caller keys or server-bound identity (uid/socket credential) — code change, agent 1 scope (identity) | DD02/DD03 |

## 6. Executor env enforce readiness (measured)

`scripts/report_n8n_env_enforce_readiness.py` (static AST closure; names only) over all 103 allowlist lanes:

* **READY_NOW, report-pinned (flip candidates): 3** — `hermes-research-worker-pool`, `proposal-backtest-engine`,
  `trade-thesis-review-engine`. Proposed, not applied: `ENV_ENFORCE_PROPOSED_20261015.diff`.
* **READY_WITH_RESIDUAL, report-pinned: 6** — `agent-outcome-scorer`, `hermes-research-agenda-at-45-7`,
  `identity-sweep-stage0`, `record-decision-outcome`, `trade-backtest-engine`, `update-lockup-earnings-dates`: every
  env read is declared, but the module also reads a key (usually `DB_PASSWORD`) from the checkout `.env` on disk.
  Enforce would not break them and would not confine them either.
* **BLOCKED: 82 report-pinned lanes.** 13 have a small closure (2-31 modules) and are blocked by named, fixable
  reads: `agent-calibration-engine`, `agent-number-grounding-slo`, `agent-outcome-linker`, `commitment-outcome-sweep`,
  `daily-incubator-refresh`, `document-mentions-backfill`, `hermes-news-bridge`, `hermes-topic-monitor-bridge`,
  `resolve-due-checkpoints`, `sec-data-ingest`, `storage-watch`, `weekly-incubator-builder`,
  `write-state-freshness-history`. The other 69 have a static import closure over 500 modules (median 1,121):
  through lazy imports the shared `db_adapter` / `comms_editor` / `api_v2` graph reaches code that reads broker
  names (`ALPACA_*`), `TRADEAI_CC_SERVICE_TOKEN_FILE`, ~500 optional names, ~80 non-literal reads and ~10 whole-file
  env loaders. This is an **upper bound** (a static closure includes paths the lane never executes), which is why
  the inventory needs runtime evidence too: the executor's report receipts already carry `env_allowlist.dropped_names`.
* **Staged enforce plan.** Stage 0: the 3 READY_NOW lanes (diff above) — each with its closure-test entry and one
  enforced dry_run receipt. Stage 1: the 6 READY_WITH_RESIDUAL lanes after their checkout-`.env` fallback is removed
  (resolve `DB_*` through the env only). Stage 2: the 13 small-closure lanes after their named reads are declared or
  narrowed. Stage 3: the 69 large-closure lanes, gated on cutting the lazy import edge into the shared
  `comms_editor`/`api_v2` graph (or on runtime `dropped_names` evidence that the path is never taken). No stage
  flips without the operator's word under the n8n cutover standard; nothing is flipped by this change.
* **Finding EF-1 (new):** two lanes already **enforced** — `momentum-cache-reconcile`, `momentum-lifecycle-monitor` —
  are BLOCKED by this analysis. `scripts/lib/scanner_candidate_projection.py` imports `.momentum_setup_evidence`
  **relatively**, which lazily imports `.comms_editor` and from there the ~1,121-module graph. The existing closure
  test (`tests/test_n8n_executor_env_allowlist_20261009.py::_env_reads`) skips relative imports (`not node.level`),
  so its "reviewed closure" for these two lanes is incomplete. Enforce is still the safer mode for them (bound
  loader, broker names denied); the gap is that the test's completeness claim is false. Fix: resolve relative
  imports in `_env_reads`, then either narrow the lazy import or re-inventory. Owner: executor/platform (ROLE to
  confirm); not changed here.
* **Seven enforced lanes carry the `.env` residual** (`classifier-health-check`, `materialize-watchlist-strategy-cards`,
  `research-insight-extractor`, `setup-quality-prior`, `source-attribution-monitor`, and the two above): an
  env-first, then one-key checkout `.env` fallback for `DB_PASSWORD`. Same-uid disk read; not confinement.

## 7. Residual risks (ranked)

| # | Residual | Severity | Owner (ROLE to confirm) | Closure evidence |
|---|---|---|---|---|
| RR1 | **Single uid.** Relay, gateway, executor, every lane, the bridge, CC and agent sessions are uid `johnclaw`; any one compromised process can read A2/A6/A7/A8 and rewrite A3/A4/A10 | Critical | platform + operator (uid split is TRK-31) | DD02 closure: under the actual worker identity, no key read, no control/ledger write, no `systemctl` manipulation (negative tests) |
| RR2 | n8n container runs as numeric uid 1000 = host `johnclaw`; bind mounts unverified | High | platform | operator runs `docker inspect m8m-n8n --format '{{range .Mounts}}{{.Source}} {{.RW}}{{"\n"}}{{end}}'` and `docker inspect m8m-n8n --format '{{.HostConfig.UsernsMode}}'`; any rw host mount is either removed or user-namespaced |
| RR3 | Bridge and CC caller auth in report mode; bridge invalid mode → report | High | bridge owner; CC owner; operator (keys) | §5 rows 2-3 |
| RR4 | 91 lanes report-pinned keep the full pre-P7 env (broker names included where rendered) | High | executor/platform | §6; staged flips; DD02 |
| RR5 | Shared dispatch HMAC key is the default for every `tradeai-*` caller | High | identity (agent 1) | DD02/DD03 |
| RR6 | Startup-cached policy; revocation not immediate | High | agent 1 | DD08 |
| RR7 | Transitive raw senders (scalp lane); raw transports removed 2026-10-15, no allowlisted lane reaches a direct_sender (broker reach: RR11) | High | agent 3 | DD01 |
| RR8 | Approval/HITL route absent; an n8n approval must never be authority | Medium (no route exists) | operator + platform | N8N_HITL_CONTRACT_SPEC.md acceptance tests |
| RR9 | OAuth proxies on loopback are callable without the bridge | Medium | bridge owner | DD17 |
| RR10 | Logs/receipts/ledger writable by uid 1000 → repudiation | Medium | platform | append-only / separate-writer ledger (DD02) |
| RR11 | **Accepted by operator 2026-10-15 (DD01 ruling, verbatim: "n8n ignor broker code it can't trade live ccontinue").** n8n-allowlisted lanes reach `broker_module` / `order_placement` transitively through the lazy chain `db_adapter -> holdings_guard -> schwab_position_sync -> schwab_transport` (74 / 73 lanes, none at import; LANE_TRANSITIVE_CAPABILITIES_20261015.md). Mitigation relied on: the trading lock (`assert_trading_unlocked`, first statement of `schwab_transport.place_order`; LOCKED, default-locked, operator unlock file) refuses every order whatever the caller. `direct_sender` remains forbidden (no exception). Residual: a lane child could still *read* broker state / tokens through that chain (same uid, RR1/RR4), and an operator unlock would make the reach effective for any caller | Medium (accepted) | operator (lock owner) + platform | shrink-only baseline + `OPERATOR_RULING_DD01_20261015` in `tests/test_lane_transitive_capabilities_20261015.py`; cutting the lazy chain (DD02 worker isolation) retires it |

## 8. Negative tests required before more effectful migration (audit §2 last paragraph)

1. Under the executor's actual child identity: reading `A2` key files/env fails; writing `config/n8n_run_allowlist.json`,
   the ledger file and a unit drop-in fails; `systemctl --user` on a fabric unit fails. **Today all succeed (RR1).**
2. A claim signed with the dispatch key but `caller_id` of another Trade AI caller is refused (DD02/DD03).
3. Bridge in enforce: unsigned, bad-key, unknown-caller and invalid-mode cases each return 401 before reservation.
4. CC in enforce: service listener without token → 401; serve listener without identity → 403; hard routes always refuse.
5. Enforced lane: a broker name present in the parent env and the env file never reaches the child (exists:
   `test_real_child_under_enforce_sees_no_unlisted_secret`, `test_env_bootstrap_narrow_20261011.py`).
6. Container: from inside `m8m-n8n`, connecting to `127.0.0.1:18091`, `:8766`, `:7777`, `:8645`, `:8646` and the
   `trade_ai` Postgres fails; only `172.19.0.1:18092` answers.
7. Revocation: a lane removed from the allowlist while a request is queued, claimed or paused-before-effect does not act (DD08).

## 9. Change log

* 2026-10-15 — DD01 operator ruling ("n8n ignor broker code it can't trade live ccontinue") recorded as
  RR11 (accepted residual): transitive lazy broker reach for n8n-allowlisted lanes accepted on the trading lock;
  direct_sender stays forbidden.
* 2026-10-15 — first version (audit DD02). Measurements: executor unit env (mode names only), bridge `/health`
  (`caller_auth.mode`, `transports`, verdict counts), `ss -ltn` listeners, container `N8N_BLOCK_ENV_ACCESS_IN_NODE`
  and `id`, CC decision-log reason counts, served release `config/cc_auth.yaml` modes. No secret, `.env` or
  credential file was read; the container mount inspection was refused by the session tool classifier and is left
  to the operator (RR2).
