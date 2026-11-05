# N8N Agent Node Preconditions

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 4462-4501 -->
## Moved from AGENTS.md (25.0.1 lines 4462-4501)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

**Ratifying 3.0.0 grants nothing by itself.** No Agent node is activated and no bridge token is
created until **every** item below is measured true and leaves a receipt (a command output, a test
run or a guard log entry quoted in the closing PR). An item without a receipt is open. The identifiers
are the proposal's §5 table; the cause of each is the audit finding named beside it.

- [ ] **P2** — the bridge streams the governed result; no second provider call (audit B H1).
- [ ] **P3** — bridge caller identity is signed: report mode, then enforce (audit B H2).
- [ ] **P4** — the single egress sanitiser `sanitise_for_external()` is built and on the bridge path
  (audit B H3, audit A, audit C G4).
- [ ] **P5** — the per-process tool allowlist is enforced at the bridge (audit B H4).
- [ ] **P6** — output schema plus behaviour-field scan at the bridge for every n8n process (audit B M3).
- [ ] **P7** — the executor and Agent paths get a per-lane secret allowlist, not the full rendered env
  of 126 names (audit A high, audit B M2).
- [ ] **P8** — off-peak deferral and the crontab-wide flags apply on the executor and bridge paths
  (audit A, audit B M1).
- [ ] **P9** — `NODES_EXCLUDE` extended (Telegram, Slack, Discord, Postgres, Files, MCP, HTTP/Code
  tools, vector stores) and a live check that active node types ⊆ the approved set (audit C G2, G13;
  audit A high).
- [ ] **P11** — container internet egress blocked by the `DOCKER-USER` rule (decision 3; audit C G3).
- [ ] **P12** — n8n public API disabled; zero n8n API keys (audit C G7).
- [ ] **P13** — n8n database role is the non-superuser `n8n_app` (audit C G1, G6). Not waived.
- [ ] **P15** — the owner password is out of the agent-readable `.env` (audit C G6).
- [ ] **P16** — workflow edits attributable: activation only under a grant naming the workflow id,
  reconciled against `guard log` by a check, not only by process (audit C G5).
- [ ] **P17** — registry-first: an undeclared n8n schedule fails CI and alerts (audit A medium, audit C G10).
- [ ] **P18** — a scheduled git-vs-live workflow drift check (audit C G9).
- [ ] **P19** — retention: manual executions not saved, pre-hardening execution data purged, backup
  scope decided (audit C G8).
- [ ] **P20** — n8n declared in `config/agent_clients.yaml` and `config/agent_registry.json`; the
  gateway's forbidden routes kept in step with `global_denied_tools` (audit A high).
- [ ] **P21** — routing policy `cost_ceiling_usd` / `latency_budget_ms` enforced; registry
  `tools_allowed` / `advisory_only` checked by the bridge (audit A medium).
- [ ] **P22** — n8n instance AI, AI builder and chat hub features confirmed off (audit C G13).

Closed or waived before this version and therefore not listed: **P1** (this amendment and the §23/ADR
status lines, audit C G11/G12 — closes on ratification), **P10** (container reaches only
`172.19.0.1:18092` on the host, done 2026-10-09), **P14** (owner MFA, waived 2026-10-09, §23.5),
**P23** (legacy monitors replaced so the network deny does not blind them, done 2026-10-09).
*Cause (§20): audit C "minimum controls before an Agent" — every gap the three audits rated
CRITICAL or HIGH for Agent enablement maps to one item here.*

<!-- moved from AGENTS.md 25.0.1 lines 5169-5181 -->
## Moved from AGENTS.md (25.0.1 lines 5169-5181)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **Reference documents** (informational, not normative): the n8n architecture of record —
  `docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` (reference architecture: planes, trust boundaries, run
  lifecycle, failure and recovery paths) and `docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md` (design architecture of
  every n8n contract: workflow, Run Lane request/receipt, run keys, effect keys, health, error-to-incident,
  notification intent, LLM step, approval, allowlist/registry), added 2026-10-15 on operator direction; framework
  table and n8n operational standards —
  `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` §0; workflow development —
  `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` §0; monitoring —
  `docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md` §0; alerting —
  `docs/ALERT_INCIDENT_RESOLUTION.md`; AI/LLM — `docs/architecture/GOVERNED_MODEL_BRIDGE.md` §0; incidents —
  `docs/runbooks/INCIDENT_RESPONSE.md`; DR — `docs/RESTORE_GUIDE.md` §0; readiness —
  `docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md`; gap assessment —
  `docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md`.
