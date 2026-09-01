# CC_WATCH_INTELLIGENCE_WIRING_2026-09-01

**Agent:** Cursor · Wave 2 (read-only)  
**as_of:** `2026-08-31T16:56:26Z` (watch-intelligence) · `2026-08-31T16:54:41Z` (CIO home)  
**roots:** `live_api:127.0.0.1:7777` · code `/tmp/wt-cio-phase-a@efcc51365`  
**Authority:** `READ_ONLY_ADVISORY` · no writes

---

## Verdict (operator question)

**Is the watch-intelligence synopsis part of persistent `InstrumentRecord` memory, or does the page compute parallel state?**

### **Parallel composition — rich-but-parallel.**

The primary Watch Intelligence surface does **not** read the `InstrumentRecord` spine. It composes a broker projection from Trade AI / street / quotes / membership domains on each request. That is the finding.

CIO Home **does** prefer the spine (`cc_narrative` from `InstrumentRecordStore`) and falls back deterministically — sparse-but-honest there.

---

## Watch Intelligence path (follow-symbol)

| layer | symbol | role |
|---|---|---|
| UI | `WatchIntelligenceUnified.tsx` | `GET /api/v3/data-broker/watch-intelligence` · star → `POST /api/v3/watch/commands/star` |
| Detail UI | `SymbolIntelligencePage.tsx` | WI detail + separate `GET /api/v3/cio/intelligence/{sym}` |
| API | `api_v2.py` data-broker branch `watch-intelligence` | dispatches to broker |
| Broker | [CODE] `scripts/lib/data_broker/watch_intelligence.py` → `list_watch_intelligence` | **no `InstrumentRecord` / `cc_narrative` / `operator_turns` / `lessons` imports** [CODE grep: zero hits] |
| Cards | [CODE] `scripts/lib/watchlist_intelligence.py` | builds `schema: watchlist_intelligence.card.v1`; `one_line_thesis = decision.get("operator_meaning")`; also copies into `investment_thesis` |

[VERIFIED] Live list as_of `2026-08-31T16:56:26Z`: `items=24`, `cards=24`, contract `watch_intelligence.broker.v1`. Item top-level has **no** `thesis` / `cc_narrative` / `operator_turns` / `lessons`. Spine fields absent.

[VERIFIED] Card `one_line_thesis` / `investment_thesis` collapse to **two strings** across 24 cards:

| text | n |
|---|---|
| `Held position — management, not starter entry` | 19 |
| `Watching for confirmation — no executable ticket` | 5 |

That is a **decision-projection template**, not per-instrument spine cognition. Rich cards (quotes, street, reviews) + thin synopsis = **rich-but-parallel**.

[VERIFIED] `GET …/watch-intelligence/DXCM`: domains include `SymbolThesis`, `CioReviewArtifact`, etc., but payload has `instrument_record: null`, `cc_narrative: null`. Parallel domains, not the record store.

---

## Operator write-back

| action | destination | spine? |
|---|---|---|
| Star / unstar on WI page | `POST /api/v3/watch/commands/star` → membership / starred set | **No** — page-local membership, not `InstrumentRecord` |
| Directives / watchlist star (other hubs) | `/api/v2/watch/directives*`, `/api/v2/watchlist/star` | membership / directive stores (not IR) |

No WI UI path writes `thesis`, `cc_narrative`, `operator_turns`, or `lessons` on the record.

---

## Spine truth (for contrast) — CIO Home

[VERIFIED] `GET /api/v3/cio/home` → `record_narrative_coverage`:

```
store_available: true
store_records: 40
rows: 26
from_record: 10
from_deterministic_fallback: 16
note: "CC prefers InstrumentRecord.cc_narrative and falls back deterministically…"
```

Matches the brief: **40 records**; surface that reads the spine looks sparse. Sample `instrument_narratives.HELD:SCHD` has `from_record: true`, `writer: cognition:defer_honored`, `next_eligible_at: 2026-08-31T14:58:17Z` (rejection/defer path) — sparse-but-honest.

Watch section on home: `rows=8`, `from_record=3` — even CIO’s watch *slice* is only partially spine-backed; the dedicated WI page is fully off-spine.

---

## Other “view” surfaces

| surface | primary endpoints | spine? | verdict |
|---|---|---|---|
| **Watch Intelligence (unified)** | `/api/v3/data-broker/watch-intelligence` | No | **rich-but-parallel** |
| **Watchlist intelligence board** | `/api/v3/watchlist/intelligence` | No (same card family; n=6 live) | parallel |
| **Symbol intelligence page** | WI detail + `/api/v3/cio/intelligence/{sym}` | CIO intel may attach research; DXCM live had no `cc_narrative`/record | hybrid UI, WI half parallel |
| **CIO Home / desk memo** | `/api/v3/cio/home` | **Yes** (prefer IR, deterministic fallback) | **sparse-but-honest** |
| **CIO investment product** | `/api/v3/cio/investment-product` | composition with IR-aware sections | spine-aware |
| **Re-entry / redeploy book** | `/api/v2/redeploy/book` | [VERIFIED] no `cc_narrative` / `InstrumentRecord` in payload | **parallel event book** |
| **Advisory desk** | `/api/v3/advisory` | advisory product (non-JSON HARDCODED in census probe; separate from IR) | parallel / product lane |
| **Watch legacy** | `/api/v3/watch/cio/latest` | STALE ~18d | stale parallel |

---

## Disagreement risk

Because WI synopsis ≠ `InstrumentRecord.cc_narrative`:

- An agent that updated the spine will **not** change WI `one_line_thesis` until/unless `operator_meaning` / decision projection changes.
- CIO Home can show a defer narrative for SCHD while WI still shows the held-position template for SCHD.
- That is expected given the wiring — call it out; do not “fix” by inventing a second index. Wave 3 option: **label** WI synopsis provenance as decision-projection (R24-style enum), or optionally *display* spine `cc_narrative` when `from_record` exists — without replacing the broker card.

---

## Corrections

1. Early guess that `SymbolThesis` domain ⇒ spine was **wrong** — domain is part of the broker card, not `InstrumentRecordStore`.
2. “Synopsis empty” would be wrong — synopsis is **present but templated** (2 values).
3. Did not open the raw `cio_instrument_records.jsonl` (release-write / secret hooks); spine counts taken from CIO home’s own `record_narrative_coverage` [VERIFIED].

---

## Handoff

- **Wave 3 (Cursor):** provenance label on WI synopsis; optional spine `cc_narrative` callout when present; MetricStrip `as_of` for stale trade-ai — no producer/Finviz work.
- **Not Cursor:** teaching WI to *write* the spine; Finviz/scanner fill.
