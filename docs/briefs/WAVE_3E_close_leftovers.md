<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# No Wave 3F — close leftovers

**Status:** recovered verbatim
**Source:** session transcript, operator message 019

---

fix the question_id contract and re-run the critique Claude Code — NO WAVE 3F. Close leftovers. Do not invent a wave.

CURRENT as promoted. Notify stays off. INTERDICT on. telegram_sent false.
MBI=0. No ROTATE-as-action. No new Telegram producer. No digest cron.

1) Cash workaround api_v2.py:2593
   Live-check cash_gap and total_cash_source on holdings + /v2/overview + /v3/cio.
   If gap < 1 AND source=position_rows on the stored field:
     delete the read-site recompute; tests must read the stored field.
   Else: leave it, document why (50% abort / no Monday pass).

2) Vacuous tests
   Fail the suite on `or True` / assertions on empty src in cash/loader/cio tests.
   Fix or delete each hit. Comment/docstring scans stay stripped.

3) Interdict canary
   test_invariant_notification_delivery_fail_closed_no_credentials
   → expect DELIVERY_INTERDICTED (pin working). Do not enable credentials
   delivery to satisfy the old name.

4) Seasonality surface
   If /v3/cio strategy_context still grades off the synthetic file,
   finish the French consumer swap + BEFORE/AFTER table.
   If already French: record pin and skip.

5) Do not: 3D hop, Grok allowlist, enqueue, notify-on, 3F.

DOCS docs/ops/CIO_LEFTOVER_CLOSEOUT_{date}.md
VERIFY /v3/cio + health 200, cash 630784.82 class, telegram_sent false.

STOP.
