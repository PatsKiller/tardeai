# Command Center v3 — Maturity Critique & Polish (2026-08-12)

**Scope:** `/v3/advisory` (Advisory Desk) and `/v3/cio` (CIO Command Center).
**Method:** live-page review of both routes, then targeted polish + data-accuracy
fixes. Every surface item below is scored 1–10 on *operator maturity* — i.e.
"can an operator act on this without needing me in the room to translate it."

---

## What changed this sprint

| Fix | File(s) | Effect |
|---|---|---|
| CIO snapshot returned empty in production (`Data Broker unavailable`) | `scripts/lib/data_broker/cio_portfolio.py` | Root cause: `from scripts.lib.cio_domain_evidence import …` — production runs `portfolio_server.py` by absolute path, so `scripts` is not on `sys.path` (only `lib` is). Changed to `lib.cio_domain_evidence` with a dev-tree fallback. Snapshot now returns 12/15 domains. |
| `ADVISORY_DESK_V1` enabled | `config/advisory_desk.yaml` → `true` | Flash/Pro opinion layer on. Routing unchanged (Flash = `advisory_desk_opinion`, Pro = `advisory_desk_synthesis`). |
| Live timer path | `config/systemd/user/tradeai-advisory-shadow-session.service.d/override.conf` | `Environment=ADVISORY_DESK_V1=true` so the daily 09:15 shadow session runs live (was deterministic-only). |
| Row rationale is pipe-joined telemetry | `scripts/api_v3_advisory.py` | Added `rationale_signals` (deterministic split + dedupe). Frontend shows the top signal; the rest live in a tooltip. |
| Expand cards were raw JSON | `apps/.../pages/AdvisoryDeskHub.tsx` | Typed renderers for Lots / Price action / Analyst / Memory / Opinion / Instrument / Evidence. |
| Remnants cluttered the verdict table | `AdvisoryDeskHub.tsx` | Sub-$500 close-out remnants hidden by default (toggle to show). |
| Banners had no call-to-action | `AdvisoryDeskHub.tsx` | One-line "what to do" per banner (`LLM_OFF` → enable flag, `LLM_DRY` → run enrichment, etc.). |
| Column headers unexplained | `AdvisoryDeskHub.tsx` | Tooltips on every column (verdict meanings, confidence scale, data-quality gap detail). |
| CIO plans leaked internal codes | `scripts/api_v3_cio.py` + `CioHub.tsx` | `situation_type` (`S1_…`, `S6_…`) → `situation_label`; `fire_reasons` telemetry → `fire_reasons_human`; `summary`/`recommendation` → `*_clean` (strips `Fire=…` and `Under desk@vN (stance):` prefixes). |
| KPI / domain chips unexplained | `CioHub.tsx` | Tooltips on the 4 KPI cards and every domain-health chip. |
| Stance shown raw (`defensive_observe`) | `CioHub.tsx` | `humanStance()` → "Defensive · observe". |

---

## Item-by-item maturity (1–10)

### Advisory Desk (`/v3/advisory`)

| # | Item | Score | Notes |
|---|---|---|---|
| 1 | **Verdict table** (symbol, class, verdict, conf, MV, wt%, P&L%, data-quality) | **8** | Clear and dollars-first. The one deduction: `Conf` mixes two scales — deterministic conviction is 0–1, LLM conviction is 0–100. The column does not say which. *Gap: unify to one scale or label the source.* |
| 2 | **Banner strip** (OK / plausibility / lots / LLM / invariants) | **8** | Was a wall of internal ids. Now each carries a "what to do" line. Deduction: banner ids are still shown verbatim (`UNTRUSTED_LOTS`) — acceptable for now, but a human title-first layout is the next step. |
| 3 | **Expand cards** | **8** | Raw JSON dump → typed cards (lots table, price-action, analyst, memory, opinion, instrument, evidence). Deduction: opinion card is empty until enrichment runs; the empty state says so (good) but there's no inline "why empty" link. |
| 4 | **Rationale** | **7** | Now a top signal + tooltip for the rest. Deduction: the deterministic rationale is still terse engineering phrasing ("Sub-threshold remnant at 0.01%"). *Gap: a curated analyst-tone rationale (like the SPCX sample) is the Flash opinion's job, not the deterministic layer's.* |
| 5 | **Data-quality column** | **7** | `ev N · gaps M · lot_data_status` with gap tooltip. Deduction: `lot_data_status` values (`RECONCILED_FROM_HOLDINGS`) are internal. *Gap: map to "reconciled vs broker" plain English.* |
| 6 | **Class filter + remnant toggle** | **8** | Class filter was present; remnant toggle is new. Clean. |
| 7 | **Synthesis block** | **6** | Renders when present. Was empty (LLM off). After live enrichment this fills with Pro dollars-first synthesis. Deduction: no provenance line (which model/process). *Gap: add "Pro · advisory_desk_synthesis" caption.* |
| 8 | **Feedback actions** (ack/snooze/useful/not-useful) | **7** | Present and wired to memory. Deduction: no confirmation styling beyond a one-line msg. |

### CIO Command Center (`/v3/cio`)

| # | Item | Score | Notes |
|---|---|---|---|
| 9 | **KPI cards** (portfolio, heat, holdings, open plans) | **7→9** | Was showing `UNKNOWN` because the snapshot was empty. Fixed. Portfolio now $1.28M, heat %, holdings count. Deduction: no "cash" card even though cash deployment is the #1 live situation. *Gap: add a cash/cash-% KPI.* |
| 10 | **Domain health strip** | **7** | Now 12/15 available with per-domain tooltips. Deduction: the 3 missing (`watch`, `watch_intelligence`, `reconciliation`) read as raw key names. *Gap: label them "Watchlist" / "Broker reconciliation" and explain why missing (no source file).* |
| 11 | **Thesis card** | **8** | Summary + humanized stance. Deduction: `summary` is a long preamble ("Mature desk OS (Desk Version 2)…") rather than a crisp one-line stance. *Gap: expose `risk_posture_structured` as chips.* |
| 12 | **Plans list** | **7→9** | Was `S5 CASH_DEPLOYMENT — cash above policy band` + `Fire=…`. Now clean labels + human fire reasons. Strong improvement. |
| 13 | **Plan detail** | **8** | Already the most complete panel (options, recommendation, risks, catalyst calendar, Hermes findings, evidence). Now uses clean summary/recommendation + human fire reasons. Deduction: `thesis_alignment` still shows raw "CONSTRAINT: Operator defer…" text. |
| 14 | **Actions ledger** | **6** | Shows open actions with priority/domain/status. Deduction: `why_now` is often raw telemetry; no filter by domain/priority. |
| 15 | **Delegation tab** | **6** | Handoff + challenge counts. Deduction: only counts, no drill-down to which handoffs are blocked. |
| 16 | **Hermes tab** | **6** | Promoted/staged counts + topics. Deduction: `model_provider` hardcoded; no link to open research jobs. |

---

## Gaps to close next (priority order)

1. **Confidence scale unification** — deterministic 0–1 vs LLM 0–100 must be one scale with a source label, or two clearly-labeled columns. Today an operator cannot tell which number they're reading.
2. **Cash posture KPI** — cash deployment is the live #1 situation, yet there's no cash card on the CIO overview. Add cash $ + cash % + vs policy band.
3. **Missing-domain labels** — `watch`, `reconciliation` should render as "Watchlist", "Broker reconciliation" with a *why* (missing source file / needs a run), not a raw snake-case key.
4. **Synthesis provenance** — the desk synthesis block needs a caption ("Pro · advisory_desk_synthesis · <n> rows") so the operator knows the model that produced it.
5. **`lot_data_status` / `thesis_alignment` plain-English** — two remaining internal-code surfaces worth a mapping pass.
6. **Actions ledger filters** — domain/priority filter + a `why_now` humanizer (same technique as fire reasons).
7. **Flash-opinion validation strictness** — the 12 Aug live shadow session called DeepSeek Flash on all 10 rows (`$0.0038`, pass) but `rejection_count: 10` — every opinion was flagged `llm_rejected` and, by design, rejected opinions are never cached (`advisory_opinion_engine.py` L520 "Only cache clean opinions"), so none surface. The rejection reasons are verbatim-evidence checks (a rationale number not byte-for-byte in the bundle; a cited ref id not in `valid_ref_ids`). The model is working; the validator's exact-match bar is too strict and needs tuning before Flash opinions can reach an operator. *Not changed here — see Authority.*

## Data-accuracy findings from the review

- **CIO snapshot was silently empty in production** while fine in dev — a `sys.path` difference, not a data gap. The fail-soft wrapper hid it as "Data Broker unavailable" with no detail; now it includes `detail`.
- **Plans summary telemetry** (`Fire=…`, `Under desk@vN (stance):`) was LLM output that repeated internal codes into the operator's face. Cleaned deterministically; no narrative was invented.
- **No `S3_` situation type exists** in the frozen catalog (S0, S1, S2, S4, S5, S6) — the "S3" that previously leaked into labels was a sprint-phase label, not a situation code. Confirmed and removed from any operator-facing path.
- **Flash opinions run but do not surface** — the 12 Aug live session proved the governed bridge works end-to-end (Flash on rows, Pro on synthesis, `$0.003783`, `pass=True`), but `validate_opinion_output` rejected all 10 row opinions (`rejection_count: 10`) on exact-match evidence checks, and rejected opinions are not cached by design. The desk therefore stays deterministic until the validator is tuned and the 30-session promotion gate clears. This is the single biggest remaining item between "LLM on" and "LLM visible".

## Authority

READ_ONLY_ADVISORY throughout. No broker action, no orders, no stops. All
changes here are presentation/labeling + the CIO snapshot import fix; no LLM
behavior, lane, or prompt was modified.
