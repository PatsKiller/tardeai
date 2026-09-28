---
Status: MEASURED (Phase 0 + first Phase 1 rows; PARTIAL by design)
as_of: 2026-09-28T11:40:00-04:00
Measured at: served a328a8817 (10:14–10:59 ET) then e2dcfce1a; code e2dcfce1a
Campaign: LIVEPROOF-20260928
---
# 07 — Operator summary (redacted)

**One line each.**
- **Alive (OBSERVED on the served release, both ends of the arrow):** Hermes CIO research → write path → deltas → symbol theses; external lanes → their table (with memory provenance); watchlist agents → results; governed search → research objects → wake; AEC → M2; options lifecycle → options theses → CIO review reading M2; acquisition cron (W0-1) firing; SEC filings feed → material changes (natural fire 08:20 ET); GIR projection (186k entities / 331k edges) consumed by the fan-out lane; memory.delta and thesis.changed on the bus; wake → checkpoint → resume chain. 22 of 46 ledger rows.
- **Wired but unproven (a reader exists, no consumption receipt yet):** the Options Desk / Watchlist / Holdings / Analyst readers of the thesis and research stores; thesis.changed reaching holdings/watchlist/options; the four SHADOW write-path adapters; the options M2 projector's writes; the advisory desk (0 memory contexts in 24 h). 12 rows.
- **Dark / intentionally off:** all Wave 3–5 behaviour switches (influence, registry routing, chooser, ladder, self-heal, conformance block, embeddings) are SHADOW by operator design; `context:persistent-wake` rolled back to SHADOW 2026-09-27; four flash timers disabled; two retired one-shot timers still enabled (LP-DEF-23).
- **Design only (not built on the served DB):** the v3.3 MVL (`agentic_runtime` has no tables), Sentinel kernel / reflective critic / Darwin / nightly reflection as v3.3 describes them, the Company Intelligence Record, the external research ladder, macro feed, Moomoo WAL/replay/features, canonical `v_canonical_*` views (unchecked). 12 rows.
- **Safe for live use:** nothing new. Live trading stays on the documented per-order authorization; this campaign placed no order, sent no production alert, changed no flag.
- **Still unproven:** every M1–M5 proof except M5 on the served SHA (1/5, same as 2026-09-25); 11 of 12 autonomy gates (1 PASS / 3 FAIL / 8 NOT_MEASURED); contradiction adjudication (first natural run 19:30 ET tonight); the post-10:20 AXTI trace (LP-DEF-02); the two-natural-opportunity clock restarted at 10:59 ET when the release flipped.

**Two repairs in the PR (C1, C2 in 06):** the earnings gate now fails closed on any strategy id it has not classified and maps every producer vocabulary onto one set (the 10:20 AXTI debit-spread gap could not recur through a new id); the lane-registry gate no longer lets a bare cron schedule declare unrelated cron lines (six masked lines are now recorded debt).

**Decisions that are yours:** LP-DEF-20 (the system-level `tradeai-continuous` timer runs while its row says PAUSED), LP-DEF-21 (cron-started daemons stay on old releases across promotes), LP-DEF-13 (the MVL schema is not on production; v3.3's first required proof cannot be measured until it is applied under a §17 grant), and the flips listed in the Waves 3–5 handoff.
