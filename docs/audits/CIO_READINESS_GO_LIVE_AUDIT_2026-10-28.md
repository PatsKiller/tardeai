Status: ACTIVE
as_of: 2026-10-28T21:25:00Z
Measured at: origin/main `33e7bd8b0` (code read; no live broker/DB access)
Canonical repo path: docs/audits/CIO_READINESS_GO_LIVE_AUDIT_2026-10-28.md
Authority: pre-merge readiness audit — evidence from code, not runtime
Supersedes: none
See also: AGENTS.md §26 (data foundation), §28.10 (conflict engine), §23.21 (cutover standard)

# CIO review / decision-authority readiness — go-live audit

## Verdict

**RED — do not treat the CIO review / decision-authority chain as production-ready.**

One sentence: the system has a single authoritative record (`InstrumentRecordStore` → `cio_instrument_records.jsonl`),
a single conflict engine (`scripts/lib/conflicts` under `config/conflict_rulebook.json`), and a single resolver
(`cio_truth.stance_for`) — but none of the three is live: the record's Postgres store is shadow/inert, the conflict
rulebook is `PROPOSED` / `live_enabled: false` / `approval: null`, and the Watch page reads three independent
producers side-by-side and renders their disagreements as conflicts it never resolves.

---

## The four root causes (all `[CODE]`, cited)

### RC-1 — The authoritative record's write is switched OFF by default

`scripts/lib/cio_prospect_writer.py:326-330` returns before any write unless `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1`.
That flag is unset by default (`cio_instrument_record.py:968`, `cio_prospect_writer.py:90-92`). The PG dual-write is
triple-gated (`prospect_store_status`, `cio_instrument_record.py:1350-1386`): registry row `PROPOSED`/grant pending,
flag off, migration `migrations/2026_10_22_cio_prospect.sql` NOT applied. Result: the scheduled prospect lanes write
the **shadow artifact** (`cio_prospect_shadow.json`), never the store. The canonical jsonl is not written at runtime.

### RC-2 — The read projection serves shadow, not the canonical record

`scripts/lib/data_broker/cio_prospect.py:137-158` reads the PG table (live-only) or the shadow JSON — never
`cio_instrument_records.jsonl` directly. Three representations, one truth, projection serves two, and the served one
is labelled "SHADOW — not the store".

### RC-3 — No live final-state ranking; the one rulebook is off

`config/conflict_rulebook.json:3,5,6` is `"status": "PROPOSED"`, `"live_enabled": false`, `"approval": null`. Its
precedence block (`:189-198`: `safety > fact > policy > deterministic_gate > operator_decision > cio_decision >
curator > opinion`) is therefore not enforced. `cio_truth.conflict_payload` returns
`"conflict engine accepted source not yet integrated"` (`cio_truth.py:443-446`, `:1337`). The only live "precedence"
is a negative gate (non-held `DETERMINISTIC_FAIL/BLOCKED/AVOID` → non-actionable; `watch_decision.py:356-359`), which
suppresses action but does not select one state.

### RC-4 — Watch reads the interim adapter, not the canonical resolver, and the lifecycle has no writer

`watch_prospects._gather_build` (`:1185-1228`) composes opportunity projection + rockville `trade_ai_state` +
`reentry_rows`; it never imports `cio_truth.stance_for` (the page's own copy admits this, `WatchProspects.tsx:505-507`).
The review-lifecycle statuses read by `cio_truth._review_view` (`:318-333`) are written by **no production module**;
`research.review_lifecycle` only ever returns `{"status": "MISSING"}`. The outcome-transport module
`data_broker/watch_review_status.py` imported at `site_payload_reads.py:382` **does not exist**.

---

## State-by-state producers (why WATCH / ENTRY_NEAR / DETERMINISTIC_FAIL / NEAR ENTRY coexist)

| displayed state | producer (file:line) | authoritative? |
|---|---|---|
| `WATCH` (prospect stance) | `cio_instrument_record.py:972,1084` — shadow-only | intended §26 truth, not live |
| `WATCH` (opportunity stance) | `opportunity.py:356-373` → `cio_opportunity_projection.json` | **what Watch actually reads** |
| `ENTRY_NEAR` / `BUY_READY` | `cio_entry_state.py:120-133` (3% above zone, ≤1 ATR) | separate entry check |
| `DETERMINISTIC_FAIL` | `strategy_ticket_reconciler.py:50-53` → `decision_projection.py:166-170` | Trade AI deterministic gate |
| `NEAR ENTRY` | `reentry_rules.py:168-179` (3% above re-entry zone, RSI<70) | separate re-entry desk |

`ENTRY_NEAR` and `NEAR ENTRY` are two *different* nearness thresholds with different producers — a name can be
"near" in one and not the other. No code maps prospect `PROSPECT_STANCES` onto opportunity `stance` vocabulary.

---

## Executive answers (evidence-only; UNKNOWN = not proven this pass)

| question | verdict |
|---|---|
| Are CIO reviews fully implemented? | **NO** — lifecycle reader exists, writer does not |
| Are automatic reviews fully implemented? | **PARTIAL** — curator/entry-state/shadow lanes run, but write shadow only |
| Are manual reviews fully implemented? | **YES (enqueue)** / **NO (deliver)** — button enqueues to a real queue; outcome never reaches the row (missing module) |
| Do reviews persist / survive restart/deploy? | **YES for `data/cio`** (`persistent_state_root.py:38-47`); shadow artifact is rebuildable |
| Are stale reviews auto-replaced / hidden? | **NO** — `stale` is computed (`cio_prospect.py:107`) but only rendered as a text suffix; nothing re-runs or hides |
| Is freshness/expiry/trigger/next-review visible in UI? | **PARTIAL** — `stale` text only on detail panel; `age_hours` computed but never rendered |
| Single authoritative CIO memory? | **YES (designed)** — `cio_instrument_records.jsonl`, single writer, versioned, auditable |
| Memory used by every desk? | **NO** — Watch reads `cio_theses.thesis_stance`; Re-Entry is a deterministic desk; four non-canonical stance writers exist |
| Authority hierarchy / conflict resolution / lineage / LLM oversight? | **NO (not live)** — rulebook PROPOSED, engine not integrated, `conflict_payload` returns "not yet integrated" |
| Second-pass validation / contradiction detection? | **NO (not live)** — engine exists but unscheduled/unintegrated |

---

## The exact minimal fix sequence (in order)

1. **Grant the `cio_prospect` registry row** (§17) and apply `migrations/2026_10_22_cio_prospect.sql`.
2. **Set `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1`** so `write_prospects` no longer early-returns.
3. **Create the missing `scripts/lib/data_broker/watch_review_status.py`** (the `presentation_state` the import expects).
4. **Activate `config/conflict_rulebook.json`** (flip `live_enabled: true`, record approval) and wire the conflict
   engine into the Watch read path — the §28.10 "one engine under one rulebook".
5. **Point Watch at `cio_truth.stance_for`** (canonical) instead of the interim adapter.
6. **Add a staleness action** — re-run or hide `expires_at < now` records; currently expiry only flags.

Each is a separate reviewed PR; items 1–2 and 4 are operator-gated (§17 / rulebook approval).

---

## Honesty

- This is a **code** audit at `33e7bd8b0`. Nothing here is claimed from live runtime; runtime freshness of the actual
  `cio_prospect_shadow.json` artifact and the PG migration state are `UNKNOWN` (not read this pass).
- The 40-tab page-by-page validation, button-by-button queue trace, ANET live-data trace, and the full persistence
  matrix are **not yet complete** — only the core decision-authority chain, trigger matrix, memory map, and lifecycle
  are proven above.
