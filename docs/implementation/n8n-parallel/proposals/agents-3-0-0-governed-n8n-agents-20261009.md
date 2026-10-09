# Proposal — AGENTS.md 3.0.0: governed LLM and Agent capability in n8n (2026-10-09)

```
Status:        SUPERSEDED BY RATIFICATION: AGENTS.md 3.0.0 is ACTIVE (ratified in #1552, 377e9b536);
               this file is kept as the evidence record. Original status: PROPOSED. Grants nothing until the operator ratifies the AGENTS.md change with
               APPROVE_AGENTS_POLICY_3_0_0 <pr> <sha>. Merging this document changes no rule.
Version:       MAJOR (2.0.1 -> 3.0.0). Per the document version policy (AGENTS.md:126-145) a change to
               egress policy, role authority or §17 boundaries is MAJOR.
Author:        Agent A (supervisor, Claude Code session), from the operator's written direction of
               2026-10-09 and three read-only guardrail audits of origin/main a9fa8b89b.
Evidence:      docs/implementation/n8n-parallel/audits/guardrail-audit-a-config-20261009.md   (216 rows, 41 gaps)
               docs/implementation/n8n-parallel/audits/guardrail-audit-b-code-20261009.md     (59 rows, 16 gaps)
               docs/implementation/n8n-parallel/audits/guardrail-audit-c-policy-n8n-20261009.md (70 rules + 17 controls, 18 gaps)
```

## 1. Why this amendment exists (operator direction, 2026-10-09)

The operator rejected keeping n8n Agents off the roadmap. The reason given: n8n is being adopted to
automate workflows, retire fragile cron jobs and scripts, centralise orchestration and monitoring, and
enable intelligent execution and remediation across a catalogue projected past 1,100 workflows. A
scheduler without governed AI capability does not justify the investment.

The operator also set the limits. n8n gets no unrestricted AI access and no provider credentials. A
workflow requests a **capability**, never a provider or a model. Routing prefers the OAuth-backed
lanes (Grok, then ChatGPT) and falls back to DeepSeek. Spend, logging, filtering and compliance stay
central. And no capability expands until a full guardrail audit proves **governance parity or better**:
n8n becomes the orchestration layer, never the source of truth for governance.

This proposal turns that direction into policy text, a target architecture, and a gated rollout whose
gates are the gaps the audits found.

## 2. Design principles (binding once ratified)

1. **n8n orchestrates; it never governs.** Every rule that decides what may run, what may be said to a
   model, what may leave the host, what may be sent to a person, and what may touch money stays in the
   host code and config that enforce it today. n8n holds references to those rules (process ids,
   template ids, routing policy ids, lane ids), never copies of them.
2. **Governance parity is a precondition, not a goal.** No capability is enabled in n8n while any
   guardrail that applies to the same work outside n8n is weaker inside it. The audits are the measure.
3. **Capability, not provider.** A workflow or Agent names a registered capability (process id) and a
   template. The bridge picks the provider and model from the routing policy.
4. **One credential, one door.** n8n holds exactly one secret per door it may knock on, valid only at
   that door. No provider keys, no database roles, no messaging tokens.
5. **Every action is attributable and receipted.** An Agent turn, a tool call and a run request each
   leave a host-side receipt naming the workflow, the execution, the grant and the outcome.

## 3. Proposed AGENTS.md text (replaces §23.3–§23.5, adds §23.8–§23.9)

### §23.3 Governed actions (replaces the current §23.3 first bullet; the rest of §23.3 stays)

- n8n workflows **and n8n Agent nodes** may cause host work only through the relay to the gateway's
  `coordination/run` operation, for lanes in `config/n8n_run_allowlist.json`, and through the read-only
  coordination endpoints. An Agent tool is a call to one of those endpoints and nothing else.
- An Agent may not invoke unrestricted execution, create or read credentials, change policy, change a
  workflow, approve or mint a grant, or bypass an approval. The never-list (broker, order, stop,
  position, paper execution, every sender, secret render, guard, release deploy, destructive retention,
  memory and learning writers, authoritative ingest, DOF SQL) applies to Agent tools exactly as to lanes.
- Every Agent tool call is checked against a per-process tool allowlist **at the bridge** before the
  result reaches n8n, and against the gateway's forbidden-route tokens. A tool the allowlist does not
  name is refused with a typed reason, not dropped.

### §23.4 Governed LLM access (replaces the current §23.4)

- n8n workflows and Agent nodes may request AI capability **only through the governed bridge**, by
  naming a registered process (`n8n_*` in `config/llm_process_registry.json`), a versioned template
  (`config/n8n_prompt_templates.json`) and optionally a routing policy (`config/llm_routing_policy.json`).
- They may not select a provider, select a model, send raw prompt text that bypasses the egress filter,
  or bypass logging, spend caps, schema validation or deferral.
- **Routing order is a policy, not a workflow choice.** The default capability policy for n8n processes
  is: primary Grok (OAuth proxy), secondary ChatGPT (OAuth proxy), fallback DeepSeek (metered). Health
  gating, concurrency limits and the global daily cap apply to every lane. A process that needs a
  different order gets its own named routing policy, reviewed like any other config change.
- Free-text Agent input is allowed only after it passes the single egress sanitiser (`sanitise_for_external`,
  §2A) on the host, and only for processes whose registry row sets `free_text_allowed: true`.
- Every model output used by a workflow is validated against the process's output schema and scanned for
  behaviour fields (size, quantity, order, stop, limit, weight, trade) before it returns to n8n. Outputs
  are drafts: `READ_ONLY_ADVISORY`, `recommendation: NONE`, never written to an InstrumentRecord,
  belief, lesson or memory store from this path.

### §23.5 Credential governance (replaces the current §23.5 first bullet)

- n8n holds **at most two credentials**: the relay bearer (run requests and reads) and, once the Agent
  gate opens, one bridge token (AI requests). Each is valid only at its own door, rendered from Bitwarden
  SM, rotated weekly with a `_PREVIOUS` overlap. Any other credential in n8n is a defect.
- Execution data on success is not retained; error data is pruned at 168 h.
- **Operator waiver recorded 2026-10-09:** owner MFA is not required. Rationale: the n8n editor listens
  on 127.0.0.1 only and is reached through an SSH tunnel over Tailscale. This waiver does not extend to
  the database role: the non-superuser `n8n_app` role remains a precondition for the bridge token.

### §23.8 n8n Agent nodes (new)

- An Agent node is permitted only in a workflow that has a lane registry row, a host receipt per turn,
  and a grant naming the workflow id for its activation.
- Its model node points at the governed bridge's Agent endpoint, never at a provider.
- Its tools are limited to the bridge-enforced allowlist in §23.3. Code, HTTP, database, file, messaging,
  MCP and vector-store tool nodes stay excluded in `NODES_EXCLUDE` unless a later amendment admits a
  specific one with its own guardrail.
- Turn count, `max_tokens` and wall time are capped per process. Streaming is refused until the bridge
  streams the governed result instead of calling the provider again (audit B, H1).

### §23.9 Governance parity (new)

- Before any lane or capability moves into n8n, its guardrails are listed with: where each executes today,
  its source (code, JSON, policy), its kind (technical, procedural, policy), how it is enforced in n8n,
  how that is validated, and how it is monitored. A gap blocks the move until it has a remediation and an
  owner. The three 2026-10-09 audits are the baseline; each tranche PR updates them.

## 4. Target architecture

```
n8n workflow / Agent node
   │  (1) run request ── bearer ──▶ relay 172.19.0.1:18092 ──▶ gateway coordination/run ──▶ ledger ──▶ executor ──▶ lane script
   │  (2) AI request ─ bridge token ─▶ bridge Agent endpoint (new listener, docker-bridge address only)
   ▼                                        │ caller identity bound to the token (no header identity)
                                            │ process + template + routing policy → model (Grok → ChatGPT → DeepSeek)
                                            │ egress sanitiser → provider → output schema + behaviour scan
                                            │ tool-call allowlist → typed refusal or permitted call via (1)
                                            ▼
                                  caps · reservation · cost event · routing_decision receipt
```

Today only path (1) exists. Path (2) is what this amendment authorises, behind the gates in §5.

## 5. Preconditions — every one must be measured true, with a receipt, before an Agent node is activated

Status as of 2026-10-09 15:10Z.

| # | Precondition | Source | Status |
|---|---|---|---|
| P1 | Amendment ratified; §23 and ADR status lines made consistent (AGENTS.md:16 still says "2.0.0 is PROPOSED") | C G11, G12 | open (this PR) |
| P2 | Bridge streams the governed result; no second provider call | B H1 | in progress (hardening PR) |
| P3 | Bridge caller identity signed; report mode then enforce | B H2 | in progress (report mode) |
| P4 | Single egress sanitiser built and on the bridge path | B H3, A, C G4 | open |
| P5 | Per-process tool allowlist enforced at the bridge | B H4 | open |
| P6 | Output schema + behaviour-field scan at the bridge for every n8n process | B M3 | open |
| P7 | Executor and Agent paths get a per-lane secret allowlist (not the full 126-name env) | A high-1/2, B M2 | partial (hardening strips TRADEAI_N8N_*) |
| P8 | Off-peak deferral and crontab-wide flags apply on the executor and bridge paths | A, B M1 | in progress (executor parity) |
| P9 | `NODES_EXCLUDE` extended (Telegram, Slack, Discord, Postgres, Files, MCP, HTTP/Code tools, vector stores); live check that active node types ⊆ approved set | C G2, G13, A high-4/5 | open |
| P10 | Network: container reaches only 172.19.0.1:18092 on the host | C G3 | **done 2026-10-09** (ufw allow 18092 at rule 1, deny bridge at rule 2; host 22/7777/7776/9090 time out) |
| P11 | Network: container egress to the internet blocked (DOCKER-USER rule) or forced through an egress proxy | C G3 | open |
| P12 | Public API disabled; zero n8n API keys | C G7 | open (operator compose change) |
| P13 | Database role non-superuser (`n8n_app`) | C G1, G6 | open (scheduled with the PG17 recreate) |
| P14 | Owner MFA | C G1 | **waived by operator 2026-10-09** (§23.5 text above) |
| P15 | Owner password out of agent-readable `.env` | C G6 | open (operator) |
| P16 | Workflow edits attributable: activation only under a grant naming the workflow id, reconciled against `guard log` | C G5 | partial (process rule adopted by Agent A 2026-10-09; no technical check) |
| P17 | Registry-first: undeclared n8n schedule fails CI and alerts | A medium, C G10 | open |
| P18 | Scheduled git-vs-live workflow drift check | C G9 | open |
| P19 | Retention: manual executions not saved; pre-hardening data purged; backup scope decided | C G8 | open |
| P20 | n8n declared in `agent_clients.yaml` and `agent_registry.json`; gateway forbidden routes kept in step with `global_denied_tools` | A high-6/7/8 | open |
| P21 | Routing policy `cost_ceiling_usd` / `latency_budget_ms` enforced; registry `tools_allowed` / `advisory_only` checked by the bridge | A medium | open |
| P22 | Instance AI / AI builder / chat hub features confirmed off | C G13 | open |
| P23 | Legacy monitors replaced so the network deny does not blind them | C | **done 2026-10-09** (both unpublished) |

## 6. Governance parity matrix (summary; the audits hold every row)

| Layer | Rows audited | Enforced on today's n8n **run** path | Enforced for a direct n8n **Agent** today |
|---|---|---|---|
| Config / JSON (A) | 216 | 175 (YES/YES†/YES‡) · 24 partial · 17 no | not separately scored (most JSON rules execute in host scripts an Agent would not reach) |
| Code / runtime (B) | 59 | 44 yes · 11 partial · 3 no | 11 yes · 7 partial · 35 no |
| Policy / procedure (C) | 70 | ~36 with code or test behind them | 16 yes · 20 partial · 26 no |

The reading is consistent across all three: **today's run path keeps parity** (the executor runs the same
scripts with the same locks, and the relay/gateway/executor add checks), and **a direct Agent would not**
(it would skip the gateway and model_job, where the n8n-specific rails live). That is why §4 routes every
Agent call through the bridge and §5 gates the opening on P2–P9.

**The per-workflow deliverable the operator asked for** (Current system → guardrail → rule source →
migration strategy → n8n implementation → validation → monitoring, for every migrated workflow) is
generated per tranche: each tranche PR adds one table per lane to `docs/implementation/n8n-parallel/parity/`
built from the audit rows that lane's script touches. N1's four cut-over lanes are the first.

## 7. Rollout

1. **Now:** fix the open high findings that affect production regardless of Agents (P2, P3 report mode,
   P7 partial, P8) — the hardening PR.
2. **Before the bridge token exists:** P4, P5, P6, P7 full, P9, P11, P12, P13, P15, P20, P21, P22.
3. **First Agent:** one read-only Agent (e.g. "explain why lane X failed", tools = coordination reads),
   one process, Grok → ChatGPT → DeepSeek, turn cap 4, behind a grant, shadow first.
4. **Then:** each new Agent capability is a registry row, a template, a routing policy and a tool list,
   reviewed like a lane cutover, with its parity table.

## 8. Decisions for the operator

1. Ratify the §23 text in §3 as AGENTS.md 3.0.0 (MAJOR), or ask for changes.
2. Confirm the routing order for n8n processes: Grok → ChatGPT → DeepSeek (ChatGPT's OAuth proxy takes
   about 13 s per call and its session expires after days idle; the keep-alive cron mitigates this).
3. Choose the internet-egress posture for the n8n container: block entirely (DOCKER-USER rule) or allow
   only through an egress proxy with a destination allowlist.
4. Confirm the first Agent use case for step 3.
