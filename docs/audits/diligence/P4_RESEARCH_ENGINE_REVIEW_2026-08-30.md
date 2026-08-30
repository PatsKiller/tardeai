# P4 — Research engine review (WS6–8)

**As-of:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0`  
**Pin context:** post Phase-0 kickoff (`852ecd47` / prior live pin `be09945b`)  
**Rails:** no budget raise · no new LLM spend · no promote  

**Evidence:** `docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json`  
**Census:** `python3 scripts/cio_research_governance_census.py --json`  
**Budget dry report:** `scripts/cio_research_budget_report.py --root <overlay> --json`  

Cited modules: `scripts/lib/cio_residual_web.py`, `scripts/lib/cio_research_budget.py`, `scripts/cio_research_budget_report.py`, `scripts/lib/cio_research_gate.py`, `scripts/lib/cio_corpus_index.py`, `scripts/lib/cio_research_librarian.py`.  
Wave 3D ops notes: `docs/ops/CIO_WAVE3D_*.md` (HOP / FLASH / CRITIQUE / CRITIQUE_DEEPSEEK / base).

---

## Exit gate (master plan)

> Free-first path proven; residual web hop/day/budget enforced; one model class per research_id/day regression green.

| Gate clause | Status | Evidence |
|-------------|--------|----------|
| Free-first path exists (FRED/Fed/RAG/corpus before paid) | **PASS (code + reference data)** | Gate ladder `skip → reuse → corpus_hit → flash → …`; 7 FRED series on disk; `free_first_refresh.py`; financial-senses FRED/ALFRED provider |
| Residual ≤1 hop / subject / day | **PASS (code + tests)** | `MAX_HOPS_PER_SUBJECT_PER_DAY = 1`; legality refuses when `hops_today >= 1` |
| Residual daily subject budget | **PASS (code)** | `DAILY_SUBJECT_BUDGET = 3` (held residual selection), distinct from research-budget `DAILY_CAP = 5` |
| Research daily subject budget | **PASS (code + live dry)** | `DAILY_CAP=5` (3 HELD + 1 CASH + 1 reentry/watch); live select 2026-08-30: PFLT, NOC, RTX, SLEEVE:CASH, EXIT:CAST |
| Grade C/D ≠ `corpus_hit` | **PASS (code + tests)** | `CLOSING_GRADES = {A,B}` only |
| One paid class / subject / day | **PASS (code + tests)** | `collapse_same_day_duplicates` on `(kind,symbol,day)` and `research_id` |
| Live residual hop under INTERDICT / no spend in this package | **N/A / held** | Package is read-only; Wave 3D already recorded the authorized hop history |

---

## WS6 — Free research layer

### What exists

| Source | Accessibility | Freshness / quality notes |
|--------|---------------|---------------------------|
| **FRED** | `scripts/fred_data_ingest.py`; financial-senses FRED/ALFRED provider; `reference/library/series/fred_*.csv` (**7** series: CPI, FedFunds, NASDAQ, SP500, T10Y2Y, UNRATE, VIX) | On-disk reference usable without key. Live API requires `FRED_API_KEY`; without it provider returns **`NOT_CONFIGURED`** honestly (`docs/financial-senses/FRED_ALFRED_PROVIDER.md`). |
| **Fed / factor research** | `ff_*.csv` Fama–French factor files beside FRED series | Static library files — not a live Fed scrape in this census. |
| **Gov / EDGAR** | EDGAR lane present as specialist provider `edgar`; Wave 3B artifact vocabulary | Not re-proven in this package (no network). |
| **Internal RAG / corpus** | `cio_corpus_index` + `cio_research_librarian` shelf life; gate `corpus_hit` before flash | Only grades **A/B** close. C/D dropped from closing set (Wave 3D / Slice D law). |
| **Historical DBs / Hermes results** | `hermes_research_results.jsonl` on overlay (**471** rows) | Free reuse path via gate `reuse` / VALID-within-TTL before paid. |
| **Free-first refresh** | `scripts/free_first_refresh.py` (`--circulate` = Hermes → RAG → structured → residual SearXNG) | Exists; this diligence package did **not** run circulate (would leave free-first path into residual/search). |

### Gap (honest)

Free-first is **architecturally real** in the gate and libraries. End-to-end “every research_id proved free-first before paid” is **not** re-proven here as a live percentage — that needs request-stream reconstruction (carry to later remediation if desired). Wave 3D already showed execution-language history must be wired into the dry report or free/paid guards are cosmetic.

---

## WS7 — Residual web

| Invariant | Value | Module |
|-----------|------:|--------|
| Max hops / subject / day | **1** | `cio_residual_web.MAX_HOPS_PER_SUBJECT_PER_DAY` |
| Daily residual subject budget | **3** | `cio_residual_web.DAILY_SUBJECT_BUDGET` |
| Gate decision token | `openai` (residual rung) | `RESIDUAL_DECISION` — lane name `residual_web` |
| Official-first / URL grading | web librarian + attaching outcomes | Wave 3D hop notes |
| Grade C/D ≠ corpus_hit | enforced | `CLOSING_GRADES` |
| Stub hop cost | **0.0** | refuses non-zero stub |

**Live posture (Wave 3D ops):** hop notes record one authorized deepseek-v4-flash research hop + critique artifacts; residual live path historically had defects (wrong model lane / dead search port) fixed on main (`#677`). This package does not re-run a live hop.

---

## WS8 — Model governance (flash / pro / grok / corpus)

Ladder (exact):

```
skip | reuse | corpus_hit | flash | pro | openai | grok_critique
```

| Rung | Lane | Paid? | Role |
|------|------|-------|------|
| skip / reuse / corpus_hit | — | no | Free-first |
| flash | `llm_flash` | yes | First paid pass |
| pro | `llm_pro` | yes | Escalate PARTIAL/truncated same research_id |
| openai | `residual_web` | residual | Questions Pro left open |
| grok_critique | `grok_critique` | ledgered (often free_oauth) | Critique before attach |

**Laws held in code:**

1. **Collapse** — one paid decision per subject (and research_id) per calendar day.  
2. **Research budget** — at most **5** subjects/day get a decision at all (`cio_research_budget`).  
3. **No redundant inference class** — gate picks one decision; worker executes it.  
4. **MBI_BEHAVIOR=0** stamped on budget schema; cognition-only selection.

**Wave 3D flash note:** zero flash-eligible when surviving names already await `grok_critique` — system correctly prefers critique over inventing a flash job.

---

## Residual risks (not closed by this package)

| ID | Sev | Note |
|----|-----|------|
| (carry) free-first proof % per research_id | 3 | Needs request-stream census beyond gate unit tests |
| (carry) residual SearXNG / live path hygiene | 3 | Fixed once on main; keep regression tests green |
| G-LOOP-01 | 2 | Lineage completion still ~54% — research arcs dominate open stages |

---

## Tests added

`tests/test_cio_diligence_p4_p5_research_specialists.py` — pins daily cap=5, hop=1 refusal, C/D∉closing, free-first ladder order, same-day collapse, census JSON shape.
