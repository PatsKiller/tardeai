# WS0 — CIO Evidence & Hermes Inventory (Phase 0 hard gate)

**As of:** 2026-08-12 (baseline inventory)  
**Branch:** `feature/advisory-desk-v1`  
**Live pin:** `desk@v5`  
**Authority:** READ_ONLY_ADVISORY  

This report answers “what exists before building” for the Closed-Loop Intelligence Architecture.  
No assumptions: file paths and live probes below.

### Update (post-WS1/WS2 slice)

| Area | Was (WS0) | **Now** |
|------|-----------|---------|
| Catalyst on plan evidence | Assembler NO | **YES** — structured `domain=catalyst` + legacy `catalysts` on enrich |
| RSI / technicals on plan | Assembler NO | **YES** — `domain=technicals` on enrich |
| Hermes structured request | Free-text only | **`hermes_request@v1`** + `fp@v1` de-dupe + TTL reuse |
| Hermes return path | Broken | **Partial** — `complete_research_result` + findings attach; worker auto-resolve still open |
| CC plan research | Partial | Catalyst calendar table + Hermes findings panel |
| Severity / warm policy | N/A | `catalyst_policy.py` + `catalyst_domain.py` |

See [CATALYST_AND_HERMES.md](./CATALYST_AND_HERMES.md) and [CLOSED_LOOP_ARCHITECTURE.md](./CLOSED_LOOP_ARCHITECTURE.md).

---

## 1. Corrected baseline (vs plan §2)

| Area | Plan said | **Actual (this host)** | Path / evidence |
|------|-----------|------------------------|-----------------|
| Situation → plan → Telegram | Live | **Live** | `cio_situation_detector`, `cio_plan_enrichment`, `cio_telegram_converse` |
| Thesis pin | desk@v4 | **`desk@v5`** | `safe_current_pin()`; `data/cio/cio_theses.jsonl` |
| LLM enrichment | Live | Live (often Flash empty → template) | `cio_plan_enrichment.call_governed_llm` |
| Notify de-dupe | Mostly | **Live** fingerprint ledger | `cio_plan_notify_ledger.json`, `should_skip_notify` |
| Multi-domain synthesis | Weak | **Partial** — holdings/cash/portfolio/risk/hermes **counts** only | `augment_multi_domain_evidence` |
| Catalyst in CIO evidence | Not demonstrated | **Upstream YES, assembler NO** | `catalyst_record.get_catalyst_record` works; **not** in snapshot; **not** pulled by enrich |
| RSI / technicals in CIO | Not demonstrated | **Upstream YES, assembler NO** | `indicator_snapshot` has RSI for SCHD/SPCX; **not** in snapshot; **not** pulled |
| Hermes enqueue | Unproven | **Enqueue YES** (62 ENQUEUED) | `data/cio/hermes_challenge_queue.jsonl` |
| Hermes resolve → plan | Incomplete | **Broken** — 0 RESOLVED events | Counter: only ENQUEUED + GENESIS |
| Plan page | Partial | **Rich brief v1** (thesis/multi-domain sections) | `CioHub.tsx` PlanDetailPanel |
| Deep links | LAN | **Tailscale** | `cc_base()` → `https://ms01-openclaw.tail163d14.ts.net` |
| Prompt versioning | Missing | **Live** `cio_alex_enrich@v2` | `prompts/cio_alex_enrich/`, plan fields |
| Eval / judge | Not built | **Built (shadow)** | `cio_prompt_eval`, `cio_prompt_judge@v1` |
| Intelligence quality | 1–3/10 | **Improved on template path** (~3.5–4.5 heuristic; judge mean ~3.6) | probe scores |

**Diagnosis (updated):** Inbound notify + thesis/prompt systems exist. **Market micro-context (catalyst/RSI) is available in Data Broker but not assembled into CIO plans.** Hermes is **one-way enqueue** with **no completed return path** into plan evidence/re-enrich.

---

## 2. Data Broker modules (code)

| Module | Path | Role |
|--------|------|------|
| CIO portfolio snapshot | `scripts/lib/data_broker/cio_portfolio.py` | Host snapshot used by enrich |
| Catalyst | `scripts/lib/data_broker/catalyst_record.py` | `get_catalyst_record(db, symbol)` |
| Indicators / RSI | `scripts/lib/data_broker/indicator_snapshot.py` | `get_indicator_snapshot(symbols)` |
| Reentry desk | `scripts/lib/data_broker/reentry_decision_desk.py` | Uses RSI + catalysts for re-entry book |
| Market quote | `scripts/lib/data_broker/market_quote.py` | Prices |
| Analyst / research card | `analyst_*`, `research_card.py` | Adjacent research |
| Catalog | `scripts/lib/data_broker/catalog.py` | Entrypoints registry |

---

## 3. Capability registry domains

**Source:** `config/cio_domain_capability_registry.json` (35 domains)

**Relevant for closed-loop plan:**

| Domain ID | Authority class | In live `cio_snapshot`? | In `augment_multi_domain`? |
|-----------|-----------------|-------------------------|----------------------------|
| `holdings_detail` | AUTHORITATIVE_ACCOUNT_STATE | **Yes** | **Yes** |
| `cash_buying_power` | AUTHORITATIVE_ACCOUNT_STATE | **Yes** | **Yes** |
| `portfolio` | AUTHORITATIVE_ACCOUNT_STATE | **Yes** | **Yes** |
| `risk` | DERIVED_VALID | **Yes** | **Yes** |
| `cost_basis` | DERIVED_VALID | **Yes** | No (only if already on plan) |
| `hermes_research` | DERIVED_VALID | **Yes** (counts only) | **Yes** (counts only) |
| `catalysts` | EXTERNAL_MARKET_DATA | **No** | **No** |
| `technicals` | EXTERNAL_MARKET_DATA | **No** | **No** |
| `rotation` / `sectors` | mixed | Yes / Yes | No |
| `watch_intelligence` | AUTHORITATIVE_INTERNAL_RECORD | Partial empty | No |
| `reentry` | DERIVED_VALID | No (separate API) | Via desk note depth only |

---

## 4. Live snapshot probe (2026-08-12)

**File:** `data/portfolios/state/data_broker/cio_snapshot.json`

Domains present:  
`cash_buying_power`, `cost_basis`, `hermes_research`, `holdings_detail`, `income`, `investment_policy`, `model_portfolio`, `portfolio`, `reconciliation`, `retirement`, `risk`, `rotation`, `sectors`, `transactions`, `watch`, `watch_intelligence`

**Absent:** `catalyst` / `catalysts`, `technicals`, `indicators`

**hermes_research shape (counts, not findings):**
```
promoted_research_count, staged_research_count, latest_topics,
challenger_active, autonomous, model_provider, fallback
```

---

## 5. Direct Data Broker probes (same host)

| Symbol | RSI (indicator_snapshot) | Catalyst (catalyst_record) |
|--------|--------------------------|----------------------------|
| SCHD | **65.35** NEUTRAL, SMA20/50 present | **Yes** — analyst_upgrade, verified, impact 5.6 |
| SPCX | **63.82** NEUTRAL | **Yes** — contract_win, verified, impact 7.6 |

**Conclusion:** Upstream data exists for the desk’s top situations. The gap is **wiring into CIO evidence assembler**, not missing market data.

---

## 6. Trace: detector → plan → enrich → surfaces

```
cio_heartbeat / cio_reactive_cycle
  → build_evidence_from_snapshot | build_evidence_from_broker
  → CIOSituationDetector.run
  → persist plan (cio_plans.jsonl)
  → enrich_plan (cio_plan_enrichment)
       · augment_multi_domain_evidence  ← snapshot only
       · build_evidence_pack + thesis + learning
       · LLM (cio_alex_enrich@vN) or template
       · maybe_request_hermes (material)
       · structural_check + optional llm_judge
       · maybe_notify_plan (fingerprint guard)
  → Telegram format_structured_reply + /v3/cio plan page
```

**Key files:**
- `scripts/lib/cio_situation_detector.py` — *can* read `catalyst_record` / `technicals` **if present on evidence**
- `scripts/lib/cio_financial_snapshot.py` — *defines* catalysts/technicals collectors for run worker path
- `scripts/lib/cio_plan_enrichment.py` — **does not pull** catalysts/technicals today
- `scripts/lib/data_broker/cio_portfolio.py` — snapshot builder (no catalyst/indicator domains currently)

---

## 7. Trace: Hermes two-way street

### Outbound (desk → Hermes)

| Piece | Status | Path |
|-------|--------|------|
| `maybe_request_hermes` | **Code live** | `cio_plan_enrichment.py` |
| Queue | **Live** | `HermesChallengeQueue` → `data/cio/hermes_challenge_queue.jsonl` |
| Events | ENQUEUED only | 62× `HERMES_CHALLENGE_ENQUEUED`, 0× RESOLVED |
| Structured ResearchRequest schema | **Missing** | Free-text `description` + metadata only |
| Plan `hermes_challenge_id` | **Not on open plans** | Enrich may enqueue without durable plan field always surviving |

### Inbound (Hermes → desk)

| Piece | Status | Path |
|-------|--------|------|
| Worker | **Code exists** | `cio_hermes_challenge_worker.py` |
| Resolve events | **Not observed live** | No RESOLVED in JSONL |
| Result → plan evidence | **Missing** | No `hermes_research` findings domain on plans |
| Re-enrich on complete | **Missing** | No hook from RESOLVED → `enrich_plan` |
| Material notify after research | **Missing** | N/A until return path exists |

**Conclusion:** Outbound firehose without consumer completion. Not a closed loop.

---

## 8. What is already built (do not rebuild)

| Capability | Location |
|------------|----------|
| desk@v5 Desk OS thesis | `cio_theses` runtime |
| Prompt versioning Alex | `prompts/cio_alex_enrich@v2` |
| Structural + heuristic eval | `cio_prompt_eval.py` |
| LLM-as-judge Flash | `prompts/cio_judge@v1`, `cio_prompt_judge.py` |
| Tailscale deep links | `cc_base()` |
| Plan page brief | `CioHub.tsx` |
| Re-entry book + sector posture | `cio_desk_depth.py` |
| Disposition → rec constraints | enrichment template + learning |

---

## 9. Gap priority (program)

| # | Gap | Blocks | Next WS |
|---|-----|--------|---------|
| G1 | Catalyst/RSI not in snapshot or enrich pack | Real multi-domain intelligence | **WS1** |
| G2 | Hermes never resolves / no result schema | Closed research loop | **WS2/WS3** |
| G3 | Hermes findings not on plan evidence | Rec cannot change from research | **WS3** |
| G4 | Free-text challenge vs ResearchRequest contract | De-dupe, intents, CC research section | **WS2 schema** |
| G5 | Gold set + human calibration for judge | Promotion gates | **WS6** |
| G6 | Plan page Research section | Operator UX for jobs/findings | **WS5** |

---

## 10. Exit criteria for WS0 — **MET**

- [x] Written inventory with file paths  
- [x] Explicit yes/no for catalyst, technicals/RSI, hermes_research  
- [x] Trace detector → enrich → Telegram/CC  
- [x] Trace Hermes enqueue vs return  
- [x] Gap report with priorities  

---

## 11. Immediate next build (Phase 1)

1. Extend `augment_multi_domain_evidence` to pull:
   - `technicals` via `indicator_snapshot` for plan symbols (RSI, SMA, MACD)
   - `catalysts` via `catalyst_record` for plan symbols  
2. Mark `DATA_UNAVAILABLE` when pull fails (explicit ref with empty fields)  
3. Prove on S6 SCHD / S1 SPCX plans that Evidence lists RSI + catalyst headline  
4. Then Phase 3: ResearchRequest/Result JSONL + resolve → re-enrich  

---

*Generated from live host probes 2026-08-12. Re-run probes after snapshot builder changes.*
