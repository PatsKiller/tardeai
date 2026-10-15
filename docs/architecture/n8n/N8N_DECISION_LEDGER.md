# n8n decision ledger — D1–D10

```
Status:      PROPOSED record (informational; AGENTS.md is normative). Closes the decision-provenance half of audit DD18.
as_of:       2026-10-15
Machine:     N8N_DECISION_LEDGER.json (N8nDecisionLedger@v1) — the source of truth; this page mirrors it
Source:      N8N_REFERENCE_ARCHITECTURE.md §11 (statements, rationale, rejected alternatives)
Audit:       independent due diligence 2026-10-15 (pinned e355be188) §14-§15
Guard:       tests/test_n8n_decision_ledger_20261015.py — every D# in §11 has a JSON row with every required
             field, and this page's status column matches the JSON
```

**Why this exists.** The audit found that all nine decisions have a rationale and a rejected alternative, but lack a
per-decision owner, status, ratification reference, implementing dependency and acceptance evidence. Policy
ratification (§23.23 10.0.0, §23.24 11.0.0) accepts the **direction**; it does not prove a decision is realized.

**Status values.** `accepted` = direction ratified **and** acceptance criteria proved with dated runtime evidence.
`partially_realized` = direction ratified, some implementation, acceptance not proved or contradicted in part.
`specified_not_enforced` = written rule, no runtime enforcement.

**Owners are roles to confirm**, not assignments (audit §14: "a role to confirm, not an invented assignment"). The
operator names the person per role.

## Summary

| Status | Count | Decisions |
|---|---|---|
| accepted | 0 | — |
| partially_realized | 9 | D1, D10, D2, D3, D4, D5, D6, D7, D8 |
| specified_not_enforced | 1 | D9 |

## Ledger

| # | Decision | Status | Accountable owner (ROLE to confirm) | Ratification | Open findings | Proof still required |
|---|---|---|---|---|---|---|
| D1 | n8n owns flow, the host owns authority | partially_realized | process owner + platform owner | §23.23 10.0.0, `APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279`, 2026-10-14T23:25:56Z | DD03 DD04 DD05 DD07 | first accepted bounded business process (zero owned today) |
| D2 | one door: relay → HMAC gateway | partially_realized | platform / relay owner | §23.23 10.0.0 + ADR_COORDINATION_SECRETS | DD02 DD08 DD14 | 8 handlers = `ROUTES` = catalogue; firewall; negative route tests |
| D3 | refusals are data | partially_realized | process + protocol owner | §23.23 10.0.0 governance (5) | DD04 DD07 | stalled-output alarm; legacy refusal errors retired |
| D4 | Run Lane is the only retry owner | partially_realized | execution / flow owner | §23.23 10.0.0 | DD04 | one scheduler per namespace; real DLQ ref (contradicted today: host RETRY_DUE + executor v2 also decide) |
| D5 | semantic effect key across schedulers | partially_realized | effect owner; operator controls owner switch | §23.23 10.0.0 + REFACTOR_PLAN addendum 1 | DD05 DD06 | ambiguous-hold + drain + stale-epoch tests counting target effects |
| D6 | workflows generated from git, drift = P1 | partially_realized | trusted deployment owner | §23.23 10.0.0 + §23.24 11.0.0 (`1747 89fb642cd`, 2026-10-15T11:51:39Z) | DD09 DD15 DD16 | scheduled drift + injected-drift P1 delivery receipt |
| D7 | send-intents, never sends | partially_realized | communications / domain owner | §23.23 10.0.0 + §24.1 | DD01 DD11 | intent → delivery receipt; transitive raw-sender closure (scalp lane) |
| D8 | LLM steps: process + template, closed schema, host re-check | partially_realized | bridge owner + action owner | §23.23 10.0.0 LLM steps + §23.4 | DD02 DD17 | one-door `/llm_step`; enforced caller; action-refusal receipt |
| D9 | empty success is a failure | specified_not_enforced | contract owner + verifier owner | §0 rule 8 + §23.24 11.0.0 FW-M6 | DD07 | immutable attempt receipt + independent verifier |
| D10 | n8n LLM: OAuth first, DeepSeek on failure or higher reasoning | partially_realized | bridge owner | operator decision 2026-10-15 (verbatim in the JSON row) | DD17 | operator 4-path proof after release; route receipts in production |

Implementing files, commits, dependencies, acceptance criteria, test ids and dated runtime evidence for each row are
in `N8N_DECISION_LEDGER.json`. A row moves to `accepted` only in a PR that adds a dated `runtime_evidence` entry
meeting its `acceptance_criteria`; a documentation change alone never moves a status (audit §18: "a source
correction can improve design completeness; it cannot by itself raise integrated operational maturity").
