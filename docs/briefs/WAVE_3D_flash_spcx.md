<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3D-flash — one hop for SPCX

**Status:** recovered verbatim
**Source:** session transcript, operator message 017

---

enqueue one job for SPCX and rerun the sequence  Claude Code — WAVE 3D-flash. One hop through EXISTING hermes_cio_worker.
Do NOT build a Grok critique HTTP site. That is 3D-critique, later.

CURRENT 9d466af3 or later.
PINS: notify off, INTERDICT on, telegram_sent false, MBI=0,
ROTATE advisory-only, no cap raise, no R1 widen, no 3E.

1) Peek ResearchNeedDecision@v2 on open material non-dust non-S5
   non-TEST plans. Print decision histogram.
   Choose ONE whose decision is flash (not grok_critique, not skip).
   If zero flash-eligible: STOP and report why. Do not invent a job
   that decides critique and then call Flash anyway.

2) Enqueue that one research request only (existing enqueue helper).
   Confirm queue depth 1. Do not enqueue the other 7.

3) PYTHONPATH=.:scripts
   python3 -m scripts.hermes_cio_worker --drain --max 1 --backend stub --json
   Persist artifact provider=stub. No vendor HTTP.

4) Same research_id:
   python3 -m scripts.hermes_cio_worker --drain --max 1 --backend live --max 1 --json
   First hop Flash only. Do not escalate to Pro/OpenAI/Grok this PR.
   cost_usd must hit the existing hermes_external_research ledger.
   execution_language or cost_cap → fail closed, no attach.

5) VALID → attach only if current attach rules pass. Receipt would_send false.

DOCS docs/ops/CIO_WAVE3D_FLASH_{date}.md
  plan_id, research_id, cost_usd, outcome, attached, queue before/after.
VERIFY /v3/cio 200, telegram_sent false, cio_run DETERMINISTIC,
exactly one live vendor call in logs.

STOP. Do not implement research_quality.critique() networking.
