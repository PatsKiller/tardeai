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
| WS1 | Unified evidence (catalyst/RSI) | **Live** — RSI + structured `domain=catalyst` (severity policy + rollups); snapshot still partial |
| WS2 | CIO → Hermes structured requests | **Live** — `fp@v1` fingerprint de-dupe + priority bump + TTL reuse |
| WS3 | Hermes → re-enrich | **Live** — worker claim→result→`on_hermes_completed` attach + re-synth + guarded notify |
| WS4 | Prompt curation/versioning | **Done** |
| WS5 | Dual surface + Tailscale | **Mostly done** |
| WS6 | Eval/gold/judge | **Shadow judge live**; gold set not frozen |
| WS7 | desk@v5 | **Done** |
| WS8 | Continuous learning | **Partial** — dispositions bias recs |

---

## Hermes research contract (MVP)

**Modules:**
- `scripts/lib/hermes_research_fingerprint.py` — `fp@v1` canonicalize → `sha256:…`
- `scripts/lib/hermes_research_policy.py` — priority/situation TTL + quality gate
- `scripts/lib/hermes_research_queue.py` — pure enqueue (in-flight → TTL reuse → create)
- `scripts/lib/cio_hermes_research.py` — JSONL store + projection indexes

**Schema:** `hermes_request@v1` / `hermes_result@v1`  
**Files:** `data/cio/hermes_research_requests.jsonl`, `…_results.jsonl`, `…_projection.json`

**Enqueue order:** fingerprint → in-flight de-dupe (optional priority bump) → TTL reuse of fresh completed → create.  
Projection keys: `by_research_id`, `by_plan_id`, `by_fingerprint_open`, `by_fingerprint_completed`.  
`maybe_request_hermes` dual-writes structured request + legacy challenge queue; no Telegram on `duplicate_in_flight` / pure reuse.

---

## Next builds (ordered)

1. **Gold set freeze** for judge calibration  
2. **Live HermesBridgeBackend** (replace stub/catalyst-first with full governed pipeline when ready)  
3. **Snapshot domain publish** of technicals/catalyst as first-class `get_cio_snapshot` domains  

### Hermes loop (worker + CIO hook)

```text
material gap / /cio research
  → enqueue_research_request (fingerprint de-dupe / TTL)
  → hermes_cio_worker claim → Stub|CatalystFirst backend → validate
  → mark_completed → on_hermes_completed (attach evidence → enrich once → notify if material change)
```

| Module | Role |
|--------|------|
| `hermes_research_schema.py` | request/result validate + evidence domain |
| `hermes_research_loop.py` | emit_research_for_plan, on_hermes_completed |
| `hermes_worker.py` | HermesWorker + backends |
| `scripts/hermes_cio_worker.py` | CLI `--once` / `--drain` / `--research-id` |
| `cio_hermes_research.py` | claim_next / mark_* / store |

Operator: `/cio research <plan_id>` forces enqueue (`operator_forced`, bypass TTL).

### Shipped this slice (fingerprint + catalyst)

- `fp@v1` de-dupe + priority bump + TTL reuse + `catalyst_invalidated`  
- `catalyst_policy` / `catalyst_domain` severity thresholds  
- Assembler always attaches `domain=catalyst`  
- Detector `calendar_catalyst_material` + snapshot catalyst enrich  
- CC plan: Catalyst calendar table + Hermes research panel

### Catalyst severity policy

**Modules:** `scripts/lib/catalyst_policy.py` (thresholds), `scripts/lib/catalyst_domain.py` (normalize + gates)

| Gate | Min severity | Horizon |
|------|--------------|---------|
| Telegram elevate | medium | ≤5d |
| Revisit tighten | medium | ≤5d |
| Hermes warm | medium | ≤5d |
| Research gap | medium | ≤10d |
| Cache invalidate | medium | ≤15d |
| Materiality bump | high | ≤5d |

Low ex-div / income distributions do **not** warm Hermes or elevate Telegram. Compound priority: weight near fire or deep DD can raise research priority without implying orders.

**Detector:** `calendar_catalyst_material` on S1; `enrich_evidence_with_catalysts` on broker snapshot path; revisit tightened at plan create.  
**TTL reuse:** blocked when medium+ catalyst added/changed after result `as_of` (`catalyst_invalidated`).  
**CC plan page:** Catalyst calendar table + Hermes research panel (`CioHub` plan detail).


---

## Acceptance (program)

See inventory §10–11 and architecture prompt acceptance list.  
**Proven today:** SCHD/SPCX plans carry `technicals.rsi` + `catalysts.headline` after enrich; research result can attach as `hermes_research_findings`.
