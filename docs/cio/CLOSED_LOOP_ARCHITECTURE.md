# CIO Desk Closed-Loop Intelligence Architecture

**Status:** Phase 0 complete · Phase 1 started · Partial Phase 2–5 already shipped  
**Authority:** READ_ONLY_ADVISORY  
**Living pin:** `desk@v5`  

Companion inventory: [EVIDENCE_INVENTORY_WS0.md](./EVIDENCE_INVENTORY_WS0.md)

---

## End state

Inbound (Data Broker + catalysts + RSI/technicals + Hermes findings + dispositions)  
→ thesis-governed Alex enrichment (`cio_alex_enrich@vN`)  
→ Telegram + `/v3/cio` briefs  
→ optional structured Hermes research jobs  
→ results re-attach to `plan_id` → re-enrich if material  
→ eval (structural + judge shadow) + operator learning  

Never orders/stops/auto-routing. No second agent harness.

---

## What is live now (2026-08-12)

| Layer | Live? | Notes |
|-------|-------|-------|
| desk@v5 | Yes | Desk OS v2 thesis |
| Prompt versioning | Yes | `cio_alex_enrich@v2` |
| Structural eval + Flash judge | Yes | Judge **shadow** until gold-set calibration |
| Tailscale deep links | Yes | `cc_base()` |
| Plan page brief | Yes | CioHub multi-section |
| **Technicals/RSI on plans** | **Yes (WS1)** | via `indicator_snapshot` in `augment_multi_domain_evidence` |
| **Catalysts on plans** | **Yes (WS1)** | via `catalyst_record` |
| Hermes structured request/result | **MVP** | `cio_hermes_research.py` + JSONL |
| Hermes worker RESOLVED → auto re-enrich | **Not yet** | Manual/complete API exists; worker still legacy queue |
| Gold set freeze | Not yet | WS6 |

---

## Architecture diagram

```
Data Broker (holdings, cash, risk, catalyst, RSI, hermes counts/findings)
        │
        ▼
Situation detector ──► Plan store (plan_id + desk@vN + prompt_version)
        │
        ▼
Evidence assembler (augment_multi_domain_evidence)
  · holdings, cash, portfolio, risk
  · technicals (RSI/SMA/MACD)
  · catalysts
  · hermes_research_findings (if completed)
        │
        ▼
Alex enrichment (versioned prompt) ──► structural_check ──► optional llm_judge
        │
        ├── Telegram / CC render
        └── Research emitter (enqueue_research_request + legacy challenge queue)
                    │
                    ▼
            Hermes jobs / worker
                    │ findings
                    ▼
            complete_research_result → re-enrich plan
```

---

## Workstream status

| WS | Name | Status |
|----|------|--------|
| WS0 | Inventory | **Done** — this inventory |
| WS1 | Unified evidence (catalyst/RSI) | **Done (MVP)** — assembler pulls both; snapshot still lacks them |
| WS2 | CIO → Hermes structured requests | **MVP** — `enqueue_research_request` + fingerprint de-dupe |
| WS3 | Hermes → re-enrich | **Partial** — `complete_research_result` + evidence attach; worker auto-complete not wired |
| WS4 | Prompt curation/versioning | **Done** |
| WS5 | Dual surface + Tailscale | **Mostly done** |
| WS6 | Eval/gold/judge | **Shadow judge live**; gold set not frozen |
| WS7 | desk@v5 | **Done** |
| WS8 | Continuous learning | **Partial** — dispositions bias recs |

---

## Hermes research contract (MVP)

**Module:** `scripts/lib/cio_hermes_research.py`  
**Schema:** `hermes_request@v1` / `hermes_result@v1`  
**Files:** `data/cio/hermes_research_requests.jsonl`, `…_results.jsonl`, `…_projection.json`

Minimal fields per plan §14 of the architecture prompt.  
`maybe_request_hermes` now dual-writes structured request + legacy challenge queue.

---

## Next builds (ordered)

1. **Snapshot builder** include technicals/catalysts so detectors see them without enrich-only path  
2. **Hermes worker** on RESOLVED call `complete_research_result` + `enrich_plan` + material notify  
3. **CC Research section** on plan page from projection  
4. **Gold set freeze** for judge calibration  
5. **`/cio research`** operator force path  

---

## Acceptance (program)

See inventory §10–11 and architecture prompt acceptance list.  
**Proven today:** SCHD/SPCX plans carry `technicals.rsi` + `catalysts.headline` after enrich; research result can attach as `hermes_research_findings`.
