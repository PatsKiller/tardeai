<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3D — one live hop, cap 1

**Status:** recovered verbatim
**Source:** session transcript, operator message 016

---

continue to wave 3d Claude Code — WAVE 3D. ONE live hop. Cap 1. Not a drain of the 8.

CURRENT ec6f7fc6 or later. Exact-main after.
READ_ONLY_ADVISORY.
PINS:
- Notify stays off. INTERDICT on. telegram_sent false. No 3E.
- MBI=0. ROTATE advisory-only. Council DISPUTED picks no winner.
- Do not raise process caps. Do not --drain --max > 1.
- No R1 allowlist widen.

SEQUENCE (stop at first FAIL)
1) Dry peek: print the 8 eligible. Pick ONE that is material,
   not S5-cash-dup, not TEST, not dust, has a plan_id.
2) Same job --backend stub --max 1 --json.
   Expect claimed/completed without a vendor HTTP.
   Persist SpecialistArtifact provider=stub.
3) SAME research_id --backend live --max 1.
   Allowed first hop only: DeepSeek Flash if that is the decision,
   else Grok critique if decision is grok_critique.
   Do not climb Flash→Pro→OpenAI in this PR.
4) If outcome execution_language or cost_cap: fail closed, no attach,
   no next gate.
5) If VALID: attach only if existing attach rules pass; mint
   CASE_SUMMARY only if 2A hook would; council join deterministic.
   DISPUTED if a second artifact disagrees — do not LLM-break the tie.
6) Receipt: would_send false. Eligible-jobs recount.

DOCS
docs/ops/CIO_WAVE3D_{date}.md
  chosen plan_id, decision, backend, cost_usd, outcome,
  attached y/n, telegram_sent false.
Scoreboard 3D=one hop.

VERIFY
/health /v3/cio 200. cash unchanged-class. cio_run DETERMINISTIC.
telegram_sent false. At most one live vendor call in logs.

STOP. No second live job. No 3E.
