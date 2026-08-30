<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3D-critique — build the missing lane

**Status:** recovered verbatim
**Source:** session transcript, operator message 018

---

Claude Code — WAVE 3D-critique. Build the missing lane, then ONE live hop.

CURRENT 23d00190 or later.
PINS: notify off, INTERDICT on, telegram_sent false, MBI=0,
ROTATE advisory-only, no cap raise, no R1 widen, no 3E.
Do not enqueue a flash job. Do not --backend live on Flash.

WHY
45 candidates, 0 flash. Two VALID artifacts await critique.
research_quality.critique() is deterministic lint. OAuth proxy
8645 is up. There is no call site.

DO — design first, then one call

1) Spec the call site in docs/ops/CIO_GROK_CRITIQUE_CONTRACT_{date}.md
   Input: existing VALID artifact + plan_id + research_id + question_ids
   Output JSON: verdict VALID|PARTIAL|REJECT, reasons[],
   execution_language bool, attachable bool
   Prompt: curated GROK_CRITIQUE template already in the gate module.
   Cost: ledger hermes_external_research or a named process_id.
   Retry: truncated = retryable once; execution_language = not retryable.
   Do not attach inside the critique function.

2) Implement research_quality.critique() network path behind
   --backend live only. Default stays lint (so dry/stub unchanged).
   Reuse existing Grok OAuth proxy 8645. No new harness.
   Unit: lint path unchanged; live path mocked; exec-lang → REJECT.

3) Dry: peek SPCX + ARKX still grok_critique.
   Run critique --backend stub on ONE (prefer SPCX if still VALID).
   Expect lint-shaped verdict, no HTTP.

4) SAME research_id, --backend live, cap 1.
   Exactly one proxy call. Persist SpecialistArtifact
   provider=grok_critique, cost_usd, verdict.
   REJECT / execution_language → no attach.
   VALID + attachable → existing attach rules only.
   Receipt would_send false.

5) Do not then climb to Flash/Pro/OpenAI.
   Do not enqueue the 32 event-driven skips.
   Do not “fix” execution_language-11 by re-researching.

DOCS docs/ops/CIO_WAVE3D_CRITIQUE_{date}.md
  contract, plan_id, cost_usd, verdict, attached y/n, proxy used.
VERIFY /v3/cio 200, telegram_sent false, cio_run DETERMINISTIC,
one live call max.

STOP after that one critique. No 3E.
