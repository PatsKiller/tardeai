# COGX Wave 1 approval package — pkg-20260927-cogx-w1-d9e1

```
Status:      ACTIVE (APPROVED all 14 items 2026-09-27 ~18:50 ET by typed reply in Claude Code: "APPROVE pkg-20260927-cogx-w1-d9e1 all, mine, start wave 1")
as_of:       2026-09-27T18:28:50-04:00
Measured at: 8f2a178d5 / served 8f2a178d5-main-exact-phase2-20260927-171004
Authority:   READ_ONLY_ADVISORY. This file is the durable artifact for the first ApprovalPackage@v1 until the
             ledger (13 §3) exists; it is written by hand once and appended by hand on each decision.
Package:     docs/architecture/cognitive_transformation_20260927/ (11 §3, 13)
```

## Operator decisions already recorded (Claude Code session, 2026-09-27)
Decisions 1–7 approved verbatim ("approve 1 through 7, send the wave 1 package"): adopt the roadmap · rotate plaintext DSNs first · one new schema `intelligence` + two roles · memory-influence ladder (cognition only, rows per wave) · consolidated packages with per-package grants · retire the 5 no-op timers + iris timer (W4) · retire the local-llm shim (W2).

## Delivery `[VERIFIED]`
Sent through `telegram_alert.send_telegram_with_id(bypass_router=True)` from the dev tree at 8f2a178d5 after a dry run (`split_for_telegram`: 2,504 chars, 1 chunk, balanced markup). Result: `{"accepted": true, "message_id": "54472", "message_ids": ["54472", "54473"]}`. No inline buttons: the package callback handler is a Wave 1 deliverable; the operator's typed reply is the record.

## Items and state
| # | Item | Category | State |
|---|---|---|---|
| 1 | lane platform-conformance-audit (nightly 02:30, cron) | OPERATOR | APPROVED |
| 2 | lane supervisor-breach-detector (watchdog */2, service) | OPERATOR | APPROVED |
| 3 | lane gir-projector (incremental, service) | OPERATOR | APPROVED |
| 4 | lane approval-package-reminder (hourly, cron) | OPERATOR | APPROVED |
| 5 | writer: intelligence client façade → receipts + checkpoints (DSA row) | OPERATOR | APPROVED |
| 6 | writer: GIR projector → schema intelligence (DSA row) | OPERATOR | APPROVED |
| 7 | writer: supervisor heartbeat + SLA tables (DSA row) | OPERATOR | APPROVED |
| 8 | writer: approval-package ledger (DSA row) | OPERATOR | APPROVED |
| 9 | RLS tenant policy on the intelligence schema | SECURITY | APPROVED |
| 10 | verify Telegram from-id against an operator allowlist — operator answered "mine": the allowlist is the operator's own id, read from the existing chat-id source (`tg_chat_ids`), never hardcoded | SECURITY | APPROVED |
| 11 | rotation lanes: checkpoints, contradiction candidates, advisory KB (cron) | INFRA | APPROVED |
| 12 | install 2–4 user units via install script (service) | INFRA | APPROVED |
| 13 | Ollama nomic-embed-text — approved with "all" despite the DEFER recommendation; the pull is still sequenced to Wave 4 unless the operator asks for it earlier (approval ≠ schedule) | SOFTWARE | APPROVED |
| 14 | Wave 1 effort ≈ 14 agent-days, $0 new spend | BUDGET | APPROVED |

Operator-executed prerequisites (not approvals): S-1 DSN rotation (BWS edit → render → ALTER ROLE); AC-1 one superuser session for CREATE SCHEMA / CREATE ROLE with the reviewed SQL from the Wave 1 PR.

## Decision record
`[VERIFIED]` operator reply in the Claude Code session, 2026-09-27 ~18:50 ET: `APPROVE pkg-20260927-cogx-w1-d9e1 all, mine, start wave 1`. Package state: APPROVED → EXECUTING (Wave 1 tranche 1 PR follows). Per-package guard grants are minted when host actions are due (cron/service/db-write), each with reason `pkg:pkg-20260927-cogx-w1-d9e1 pr:<n> sha:<sha> campaign:cognitive-transformation-20260927`.

## Message as sent
```
🔐 *Approval package pkg-20260927-cogx-w1-d9e1 — Wave 1 · Foundations*
Campaign: cognitive-transformation-20260927 · PR #1304 · base sha 8f2a178d5
Reviews: architecture = the package itself (PROPOSED); infra + security reviews arrive with the Wave 1 PR
Does NOT touch: MBI-BEHAVIOR (stays 0), broker, live flags, 2FA, sudo/destructive scopes
Expires: 2026-09-28 18:30 ET (reminder at +12h)

ALREADY APPROVED by you today (decisions 1–7, recorded):
✅ adopt the roadmap · ✅ rotate plaintext DSNs first · ✅ one new schema intelligence + two roles · ✅ memory-influence ladder (cognition only; rows come per wave) · ✅ consolidated packages with per-package grants · ✅ retire 5 no-op timers + iris timer (executes W4) · ✅ retire the local-llm shim (executes W2)

NEEDS YOUR ANSWER — Wave 1 items (each reversible):
OPERATOR (AGENTS §17 new lanes / new writers)
 1. lane platform-conformance-audit, nightly 02:30 (cron)
 2. lane supervisor-breach-detector, inside the watchdog cycle every 2 min (service)
 3. lane gir-projector, incremental from the event bus (service)
 4. lane approval-package-reminder, hourly (cron)
 5. writer: intelligence client façade → consumption receipts + agent checkpoints (DSA row)
 6. writer: GIR projector → schema intelligence, projection only, zero authority (DSA row)
 7. writer: supervisor heartbeat + SLA tables (DSA row)
 8. writer: approval-package ledger, append-only, hash-chained (DSA row)
SECURITY
 9. RLS tenant policy on the intelligence schema, same as memory-r10-m2
 10. verify Telegram from-id against an operator allowlist (I need your operator id — reply with it or say "mine")
INFRA
 11. rotation lanes for checkpoints, contradiction candidates, advisory KB (cron; archive with tripwire, nothing deleted)
 12. install 2–4 user units via install-cio-operator-runtime.sh (service)
SOFTWARE
 13. Ollama model nomic-embed-text (local, ~300 MB) — my recommendation: DEFER to Wave 4
BUDGET
 14. Wave 1 effort ≈ 14 agent-days; no new paid lane; $0 new spend

YOU EXECUTE ON THE HOST (I cannot): rotate the DSNs (BWS edit → render → ALTER ROLE), and one superuser session for CREATE SCHEMA / CREATE ROLE — I hand you the reviewed SQL in the Wave 1 PR.

Reply here or in Claude Code:
 APPROVE pkg-20260927-cogx-w1-d9e1 all
 APPROVE pkg-20260927-cogx-w1-d9e1 1,2,3,4,5,6,7,8,9,11,12,14
 DENY pkg-20260927-cogx-w1-d9e1 13   ·   DEFER pkg-20260927-cogx-w1-d9e1 13
No buttons yet: the package callback handler is itself a Wave 1 deliverable; your typed reply is the record.
```
