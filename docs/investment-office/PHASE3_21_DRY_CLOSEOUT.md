# PHASES 3–21 DRY CLOSEOUT (v4 remediation)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY`  
**Mode:** dry-tested implementation. **Not production acceptance.**

Eight isolated agents implemented phases 3–16 + 8–10. Orchestrator integrated, dry-tested, and wired CI.

| Phase | Deliverable | Dry test |
| --- | --- | --- |
| 3 | Named quote contract (`cio_canonical_quote`) | `test_cio_canonical_quote.py` |
| 4 | Removed `evaluated_now`; independent evidence | `test_cio_freshness_materiality_gate.py` |
| 5 | CIO UI four KPIs + raise copy | grep + `CioHub.tsx` |
| 6 | Sizing v2 candidates + HEURISTIC label | `test_cio_institutional_sizing.py` |
| 7 | Advisory provenance on `/v3/advisory` | `test_cio_advisory_provenance.py` |
| 8–9 | Live report builder; HTML/DOCX; honest PDF miss | `test_cio_live_report_parity.py` |
| 10 | Telegram dry canary; measured `general_sends=0` | `test_cio_telegram_canary_dry.py` |
| 11–16 | Research brain + August/September fixture reproduction | `test_cio_research_brain.py` |
| 17–19 | Retrieve-before-synthesis hook; modifier ≤10%; no standalone sell | covered in research tests |
| 20 | CI suites extended (canonical quote, research, live report, telegram dry) | `run_cio_hardening_ci.py` |
| 21 | `run_cio_acceptance.py` still **FAIL** until live book/PDF/canary | expected |

## Still FAIL on live acceptance (honest)

- Material `shares×mark ≠ broker MV` until a live reprice writes one mark
- PDF renderer absent on this host
- Telegram canary is **dry** (`sent: false`) — not a live exact-release send
- Almanac stats are **fixture reproductions**, not vendor full-sample prints
- `STOCK_ALMANAC_INTEGRATION` / `BROADER_RESEARCH_BRAIN` categories stay FAIL in v4 until those bars are met

No broker. No live Telegram. No autonomous strategy execution.
