<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3B — do not invent notify-on

**Status:** recovered verbatim
**Source:** session transcript, operator message 014

---

Claude Code — WAVE 3B spec. Do not invent notify-on.

CURRENT pin 0cb8e6da or later. Exact-main after.
READ_ONLY_ADVISORY. telegram_sent must stay false.

PINS — if a change would violate one, skip that file:
- CIO_SITUATION_NOTIFY stays 0 / unset. Do not flip it.
- CIO_TELEGRAM_INTERDICT stays on. Do not remove it.
- No new Telegram / WhatsApp producer. No send() call sites.
- MBI ceiling 0. Do not read MBI to size or act.
- ROTATE is option_id / advisory text only. Not an action enum
  that a worker executes. No rebalance cron change.
- Council does not call a model and does not mint/attach plans.
- Hermes --backend live forbidden. Dry remains \~8 eligible, 0 paid.
- No R1 allowlist widen. No research_governance edit unless
  a test-only import demands it — prefer not.

DO

1) SpecialistArtifact@v1-lite
   Schema: workflow_id, plan_id, research_id, artifact_id,
   provider (stub|flash|pro|openai|grok_critique), cost_usd,
   outcome (VALID|PARTIAL|FAIL|execution_language|cost_cap),
   source_refs[], created_at.
   Store next to existing CIO jsonl. Writer used only by tests
   and by the deterministic join. No HTTP to a vendor.

2) CIOCouncilSynthesis@v1
   Deterministic: join VALID artifacts + CASE_SUMMARY + desk pin
   + thesis_fields. Output a synthesis block the operator product
   can already render (T/D/A labels ok).
   If two artifacts disagree: label DISPUTED, do not pick a winner
   with an LLM.

3) NotificationPolicy@v1
   Function: given plan + materiality + synthesis →
   IMMEDIATE | DIGEST | COMMAND_CENTER_ONLY | SUPPRESSED.
   Persist notification_id + decision + reason.
   Default for S1 observational and all S5 cash dups: SUPPRESSED.
   S6 fire may be COMMAND_CENTER_ONLY (not IMMEDIATE).
   Delivery layer: stub that records would_send=false.
   Test: grep / log — zero Telegram API calls in this PR.

4) OutcomeCheckpoint
   New writes MUST include plan_id.
   complete→checkpoint rate becomes computable going forward.
   Do not rewrite 148 CASH or 50 dust historical rows.

5) Eligible-jobs surface
   Cap 10: symbol, decision, next_eligible_at, skip_reason.
   Product or ops note only. No Telegram of this block.

6) EDGAR
   Registry row only: official SEC URL, refresh=event,
   dimension_scope=entity, grade C until a later ingest.
   No crawler. No full-text download sweep.

DOCS
docs/ops/CIO_WAVE3B_{date}.md
Scoreboard WAVE3B=schema+policy+join, notify=SUPPRESSED,
telegram_sent=false, MBI=0, ROTATE=advisory-only.

VERIFY
ai_local_acceptance + new tests for the four pins.
/health /v3/cio 200.
Host dry: eligible still collapsed, 0 paid calls,
telegram_sent false, cio_run DETERMINISTIC_PRODUCT.

STOP. Do not enable notify. Do not live-Hermes. Do not Wave 3C.
