# CIO Desk — Architect Packet

**CURRENT OPERATOR TRUTH (living sheet, R6.4 — not R7):**  
[`docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md`](../investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md)  
This sheet overrides older architecture/planning docs when they disagree. Drive: same filename, replaced in place.

Code-adjacent documentation for the Trade AI **CIO / Financial Advisor desk** on `feature/advisory-desk-v1` (repo: [PatsKiller/tardeai](https://github.com/PatsKiller/tardeai)).

**Audience:** architects and operators who need the thesis, authority model, situation catalog, learning loop, and known gaps **without host access**.  
**Authority everywhere:** `READ_ONLY_ADVISORY` — no orders, stops, or 2FA from chat or situations.

---

## Maturity statement (operator reality, not marketing)

This desk is a **working advisory skeleton with a living thesis pin**, not a wealth-management CIO product.

What is **live today**:

- Versioned desk thesis (`desk@vN`) with principles, structured risk posture, escalation rules, and a thin learning log
- Situation detector S0–S8 → durable plans → optional Telegram notify (dedicated CIO bot) and Command Center `/v3/cio` deep links
- Plan enrichment (LLM when allowed, template otherwise) that loads `safe_context_block` and pins the live `desk@vN`
- Multi-domain evidence packs from Data Broker (fail-soft; numbers or `DATA_UNAVAILABLE`)
- Structured **catalyst calendar** domain (`domain=catalyst`) with severity thresholds → revisit / Hermes warm / Telegram elevate (never orders)
- Hermes research requests with **fingerprint de-dupe**, priority bump, and TTL result reuse (invalidated on medium+ catalyst change)
- Operator dispositions (ack / rate / defer / done / reject) into an append-only learning store
- Portfolio-grade **desk note** synthesis for material focus (thesis + cash/concentration/DD + learning bias)
- Parallel Gate-B path: WakeDispatcher → RunWorker → governed bridge (advisory tools only)
- CC plan detail: Catalyst calendar table + Hermes research panel

What it is **not**:

- Not Morgan Stanley / Schwab-grade IPS, tax, estate, or multi-scenario wealth reports
- Not continuous re-entry or sector-defensive “standing posture” productization
- Not a closed-loop learning system with high disposition volume or auto-quality scoring
- Not unattended trading — recommendations never execute

Expect mixed pin hygiene on older open plans, intermittent LLM deferral to templates, and depth that is **thesis-aware advisory** rather than full FA platform.

For operator-facing host packet (pin + as_of snapshots): see [CIO_DESK_OPERATING_PACKET.md](./CIO_DESK_OPERATING_PACKET.md) (also mirrored to Google Drive when synced).

---

## Packet index

| Doc | Contents |
|---|---|
| [THESIS.md](./THESIS.md) | How `desk@vN` works: event store, pin, `safe_context_block`, principles, risk posture, escalation |
| [AUTHORITY.md](./AUTHORITY.md) | READ_ONLY_ADVISORY contract; forbidden actions; Telegram vs UI |
| [SITUATIONS.md](./SITUATIONS.md) | S-class catalog, fire rules, plan lifecycle, notify guard |
| [DESK_NOTE.md](./DESK_NOTE.md) | Desk synthesis product, section schema, regenerate commands, quality bar |
| [CLOSED_LOOP_ARCHITECTURE.md](./CLOSED_LOOP_ARCHITECTURE.md) | Closed-loop CIO plan + phase status |
| [CATALYST_AND_HERMES.md](./CATALYST_AND_HERMES.md) | Catalyst severity policy + Hermes fingerprint/TTL reuse |
| [EVIDENCE_INVENTORY_WS0.md](./EVIDENCE_INVENTORY_WS0.md) | Phase 0 inventory: catalyst/RSI/Hermes truth (historical + updates) |
| [PROMPT_CURATION.md](./PROMPT_CURATION.md) | Prompt curation, versioning, structural eval + rubric |
| [REENTRY_RR.md](./REENTRY_RR.md) | R:R formula `(target−price)/(price−stop)`; engine ≥2:1 vs desk core ≥1.5 |
| [LEARNING_LOOP.md](./LEARNING_LOOP.md) | Dispositions → learning_log → enrichment bias; limits |
| [ROADMAP_GAPS.md](./ROADMAP_GAPS.md) | Explicit missing product (aspirational only here) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Track A vs Track B; where thesis is injected (and where not) |

### Historical / phase notes (still useful)

| Doc | Role |
|---|---|
| [DESK_THESIS_V2.md](./DESK_THESIS_V2.md) | desk@v2 intelligence OS write-up |
| [THESIS_STORE_P3.md](./THESIS_STORE_P3.md) | P3 store delivery notes |
| [SITUATION_CATALOG_V1.md](./SITUATION_CATALOG_V1.md) | Phase 2a freeze + live wiring |
| [P2B_PLAN_ENRICHMENT.md](./P2B_PLAN_ENRICHMENT.md) | LLM/template enrichment policy |
| [CIO_TELEGRAM_CONVERSE_RUNBOOK.md](./CIO_TELEGRAM_CONVERSE_RUNBOOK.md) | Host Telegram bot ops |
| [WAKE_TRACES_P5.md](./WAKE_TRACES_P5.md) | Wake trace notes |

---

## Primary code map

| Concern | Path |
|---|---|
| Thesis store / pin | [`scripts/lib/cio_theses.py`](../../scripts/lib/cio_theses.py) |
| Situation detector | [`scripts/lib/cio_situation_detector.py`](../../scripts/lib/cio_situation_detector.py) |
| Plans | [`scripts/lib/cio_plans.py`](../../scripts/lib/cio_plans.py) |
| Plan enrichment + notify ledger | [`scripts/lib/cio_plan_enrichment.py`](../../scripts/lib/cio_plan_enrichment.py) |
| Catalyst severity policy | [`scripts/lib/catalyst_policy.py`](../../scripts/lib/catalyst_policy.py) |
| Catalyst domain normalize/gates | [`scripts/lib/catalyst_domain.py`](../../scripts/lib/catalyst_domain.py) |
| Hermes fingerprint `fp@v1` | [`scripts/lib/hermes_research_fingerprint.py`](../../scripts/lib/hermes_research_fingerprint.py) |
| Hermes TTL / quality reuse | [`scripts/lib/hermes_research_policy.py`](../../scripts/lib/hermes_research_policy.py) |
| Hermes enqueue core | [`scripts/lib/hermes_research_queue.py`](../../scripts/lib/hermes_research_queue.py) |
| Hermes request/result store | [`scripts/lib/cio_hermes_research.py`](../../scripts/lib/cio_hermes_research.py) |
| Desk note synthesis | [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py) |
| CC CIO hub (plan calendar/research) | [`apps/command-center-v3/src/pages/CioHub.tsx`](../../apps/command-center-v3/src/pages/CioHub.tsx) |
| Telegram converse | [`scripts/lib/cio_telegram_converse.py`](../../scripts/lib/cio_telegram_converse.py) |
| Wake dispatcher | [`scripts/lib/cio_wake_dispatcher.py`](../../scripts/lib/cio_wake_dispatcher.py) |
| Run worker | [`scripts/lib/cio_run_worker.py`](../../scripts/lib/cio_run_worker.py) |
| Situations config | [`config/cio_situations.yaml`](../../config/cio_situations.yaml) |
| LLM/notify policy | [`config/cio_llm_policy.yaml`](../../config/cio_llm_policy.yaml) |
| API hub | [`scripts/api_v3_cio.py`](../../scripts/api_v3_cio.py) |

Runtime data (host-local, typically gitignored): `data/cio/*`.

---

## Quick verification (dev host)

```bash
PYTHONPATH=scripts python3 -c "
from scripts.lib.cio_theses import safe_current_pin, safe_context_block
print(safe_current_pin())
b = safe_context_block(full=True) or {}
print(b.get('stance'), b.get('thesis_version'))
"
PYTHONPATH=scripts python3 scripts/lib/cio_desk_synthesis.py | head -40
```

---

*Document live behavior only. Label aspirations under [ROADMAP_GAPS.md](./ROADMAP_GAPS.md).*
