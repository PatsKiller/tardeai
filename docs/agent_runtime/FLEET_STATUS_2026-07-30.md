# Agent-Runtime Fleet Status — 2026-07-30

Status:      HISTORICAL
as_of:       2026-07-30T15:33:44-04:00
Measured at: efcc51365 / not measured

Report for the "enable the SHADOW fleet as far as is safely possible" task. Scope
covered Tasks A–E. **Everything remains LAB / SHADOW / read-only / zero financial
authority.** Nothing was promoted, no authority was granted, and no hollow
evidence was written.

## What landed on `main`
| PR | What | State |
|----|------|-------|
| #263 | FE truth-label fix (restores the 8 canonical strings the #260 redesign dropped) | **MERGED** |
| #261 | Maturity live-evidence bridge (read-only, fail-closed) | **MERGED** |
| #262 | Wave-1 SHADOW activation runbook | **MERGED** |

`main` is green: maturity suite 50/50, source-only CI 17/17, `no_broker_write_bypass` 11/11.

## Open PRs (human review — NOT self-merged)
| PR | What | Why not merged |
|----|------|----------------|
| #264 | Governed dispatch backend + `run_once` wiring + tests | Safety-critical execution-adjacent code |

## Per-agent status

| Agent | Wave | Prior state | Action taken | Running in LAB/SHADOW? | Evidence under its board id | Still required | Kill-switch |
|-------|------|-------------|--------------|------------------------|-----------------------------|----------------|-------------|
| sentinel | 1 | enabled / SHADOW | dispatch backend built (#264); not run | **No** | 0 runs / 0 reviews | provider module + root timer | `rm /etc/tradeai/agent_runtime_enabled` |
| darwin | 1 | enabled / SHADOW | same | No | 0 / 0 | same | same |
| iris | 1 | enabled / SHADOW | same | No | 0 / 0 | same | same |
| reflection | 1 | enabled / SHADOW | same | No | 0 / 0 | same | same |
| maria | 2 | disabled / DESIGNED | **NOT enabled** (gap report) | No | 0 / 0 | acceptance evidence; wave-1 accepted first | n/a (disabled) |
| vega | 2 | disabled / DESIGNED | **NOT enabled** (gap report) | No | 0 / 0 | acceptance evidence; wave-1 accepted first | n/a |
| risk_agent | 2 | disabled / DESIGNED | **NOT enabled** (gap report) | No | 0 / 0 | acceptance evidence; wave-1 accepted first | n/a |
| aegis | 2 | disabled / DESIGNED | **NOT enabled** (gap report) | No | 0 / 0 | acceptance evidence; wave-1 accepted first | n/a |

**How to verify any row:** `curl -s localhost:7777/api/v3/agent-maturity | jq '.data[] | {agent_id, source_class, sample_size, promotion_eligibility}'` (all currently `REPOSITORY_EVIDENCE / null / not eligible`), and per agent `SELECT count(*) FROM agentic_runtime.agent_runs WHERE agent_id='<id>'` on the LAB DB.

## Wave-2 gap analysis (Task D — none qualify)

All four wave-2 specs are **structurally valid** — owner, valid triggers, advisory-only output kinds, independent reviewer ≠ scorer (`iris`/`sentinel` review, `darwin` scores), `retrieval_required`, bounded budget, no self-governance tools, and a deny-list covering their domain authority (`proposal.authorize`, `config.promote`, `position.close`, `risk_policy.write`, `service.restart`, `systemd.enable`, …). They pass `ShadowAgentSpec.validate()`.

They fail the **promotion contract on the decisive requirement — measurable acceptance evidence:**

| Requirement | maria | vega | risk_agent | aegis |
|---|---|---|---|---|
| Valid spec / schema | ✅ | ✅ | ✅ | ✅ |
| Independent reviewer ≠ scorer ≠ producer | ✅ | ✅ | ✅ | ✅ |
| Owner + disable control (`enabled=false`) | ✅ | ✅ | ✅ | ✅ |
| Advisory-only, domain authority denied | ✅ | ✅ | ✅ | ✅ |
| **Fixtures / known-bad set connected** | ❌ | ❌ | ❌ | ❌ |
| **Measured acceptance evidence (12 gates)** | ❌ 0 runs | ❌ 0 runs | ❌ 0 runs | ❌ 0 runs |
| Gate: prior wave accepted | ❌ (wave-1 not accepted) | ❌ | ❌ | ❌ |

**Decision: enable none.** Flipping any DESIGNED→SHADOW now would assert readiness that no evidence supports — a violation of the promotion contract and the honest-evidence guardrail. Each is correctly gated behind (a) wave-1 reaching accepted maturity, and (b) its own measured gates. Re-evaluate per agent once wave-1 has live gate-measured evidence.

## LIVE now vs STILL GATED

**LIVE now**
- Read plane (`/api/v3/agent-runtime`, `/api/v3/agent-maturity`) — 200, read-only, zero authority.
- Maturity bridge (#261) — will surface `RUNTIME_EVIDENCE` per agent the instant real runs exist under that agent's id; fail-closed to `REPOSITORY_EVIDENCE` otherwise.
- Governed dispatch backend (#264, pending review) — mechanism complete and unit-tested.

**STILL GATED (deliberately) and why**
- **Wave-1 agents not producing evidence** — needs (a) an operator-authored provider module (real LLM/retrieval + real bounded job source), (b) root to enable the systemd timers, (c) `/etc/tradeai/agent_runtime_enabled`. The backend ships no canned provider so it cannot fabricate.
- **Wave-2 agents** — no acceptance evidence (above).
- **`production_activation_authorized`** — false; untouched.
- **Automatic promotion** — `HUMAN_ONLY`; untouched.
- **All financial/broker/2FA/execution authority** — denied; untouched.

## Data note the operator must resolve (id mapping)
The LAB DB already holds evidence (630 artifacts, 140 reviews, 240 scores) but under **`_shadow`-suffixed** ids (`watch_producer_shadow` produces, `sentinel_shadow` reviews) — a different naming from the board's canonical ids (`sentinel`, …). The #261 bridge groups by `run.agent_id`, so a board agent only lights up when runs exist under **its own** id (which the #264 backend produces when run with a provider module). This is not a bug — it's a naming/mapping decision: either the provider module emits runs under the canonical ids, or the bridge is extended to map `<agent>_shadow → <agent>`. Recommend the former (canonical ids at write time).

## Exact operator/root sequence to actually run wave-1 (from the runbook)
1. Confirm LAB migrations applied (they are: `agentic_runtime` schema present, `shadow_rw` writer works).
2. Author + review a **provider module** (`AGENT_RUNTIME_PROVIDER_MODULE`) exposing `build_providers(agent_id)` (real model/retrieval + `make_processor`) and `job_source(agent_id, limit)` (real Watch inputs) — its own PR.
3. Set service env: `AGENT_RUNTIME_OPERATOR_AUTH=1`, `AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot`, `AGENT_RUNTIME_DISPATCH_DSN=<shadow_rw DSN>`, `AGENT_RUNTIME_PROVIDER_MODULE=<module>`.
4. `sudo install -m0644 /dev/null /etc/tradeai/agent_runtime_enabled` (the kill switch / opt-in).
5. Install the system units and `systemctl enable --now tradeai-agent-runtime@{sentinel,darwin,iris,reflection}.timer`.
6. Restart the read server so #261's bridge is live in-process (`systemctl --user restart portfolio-server.service`).
7. Watch: `/api/v3/agent-maturity` moves those agents to `RUNTIME_EVIDENCE` with real sample sizes; 12 gates begin measuring; nothing auto-promotes.
8. **Kill:** `sudo rm /etc/tradeai/agent_runtime_enabled` halts the fleet.
