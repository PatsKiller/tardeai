<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3C — silent closed loop

**Status:** recovered verbatim
**Source:** session transcript, operator message 015

---

continue to wave 3c  Claude Code — WAVE 3C. Silent closed loop. No Telegram. No live Hermes.

CURRENT latest promoted pin. Exact-main after.
READ_ONLY_ADVISORY.
PINS:
- CIO_SITUATION_NOTIFY stays 0. INTERDICT stays on. telegram_sent false.
- MBI = 0. ROTATE advisory-only. Council stays deterministic; DISPUTED
  still picks no winner. plan_id field required, null + plan_binding ok.
- No --backend live. Dry ~8 eligible / 0 paid.
- No R1 allowlist widen. No research_governance edit.
- Do not rewrite 148 CASH / 50 dust checkpoint history.

DO

1) DeliveryReceipt@v1 (schema + persist, no send)
   notification_id, decision (from NotificationPolicy@v1),
   would_channel (telegram|digest|cc|none), would_send=false,
   dedupe_key, created_at.
   Writer records the decision already computed in 3B.
   Test: zero Telegram/HTTP send call sites in this PR.

2) Lesson / hypothesis bind
   After OutcomeCheckpoint with a bound plan_id, write
   lesson_id + hypothesis (support-only, no AGENT_COMMITMENT).
   REVIEW_READY flag on that row. MBI stays 0.
   Unbound checkpoints do not mint lessons.

3) CanonicalStoreRegistry@v1 spine
   One index file/module that lists ids already in use:
   workflow_id event_id research_id artifact_id generation_id
   notification_id checkpoint_id outcome_id lesson_id
   Do not mint a second store of payloads. Point at existing jsonl.
   Test: each new 3B/3C write appears in the registry.

4) Graph impact 1-hop
   For HELD non-dust names only: subject_guid → 1-hop neighbors
   (sector, held peers, catalyst tag). Persist graph_impact skipped
   for CASH/dust/TEST. No identity mint of the watch book.

5) EDGAR — one filing proof, not a crawler
   Register SEC official URL if missing.
   Fetch at most ONE 10-K/10-Q index page or filing header for ONE
   held non-dust symbol (e.g. SCHD's issuer if resolvable, else skip
   with UNAVAILABLE). Store as artifact provider=edgar grade C
   dimension_scope=entity. No corpus_hit from it this PR.
   If issuer cannot be resolved: document UNAVAILABLE, do not guess.

6) Eligible-jobs already on product from 3B — leave unless broken.

DOCS
docs/ops/CIO_WAVE3C_{date}.md
Scoreboard 3C=receipt+lesson+registry+1hop, notify=SUPPRESSED,
telegram_sent=false.

VERIFY
New tests for pins + registry + unbound checkpoint does not mint lesson.
/health /v3/cio 200. cash surfaces agree. cio_run DETERMINISTIC.
Dry 8 / 0 paid. telegram_sent false.

STOP. Do not start 3D (live LLM) or 3E (notify).
