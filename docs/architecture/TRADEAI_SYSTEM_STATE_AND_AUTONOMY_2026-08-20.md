# TradeAI System State & Autonomy Record — 2026-08-20

**Authority:** READ_ONLY_ADVISORY (no chat→broker execution)  
**CURRENT release:** `d4003a356a032810e04ae21a86d1ea264abc7fec` (`d4003a35-main-exact-phase2-20260820-210356`)  
**Purpose:** Persistent recoverable record of architecture, configuration, workflows, and autonomy gaps through PR **#420**.  
**Drive mirror:** `Trade_AI_Docs_v2` (folder id `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`)

---

## 1. Executive snapshot

| Dimension | State (2026-08-20) |
|-----------|-------------------|
| Portfolio-server tip | `d4003a35` (#420 held-book thesis coverage) |
| Alex Telegram converse | **LIVE** — meta / desk / **freeform** grounded agent |
| Reentry → S3 detector | **LIVE** (#414) — domain wired; host saw S3≈21 |
| Watch → S7 detector | **LIVE** (#415) — shape fixed; promotion_grade often 0 |
| Held symbol theses CURRENT | **~13.6%** (3 CURRENT / 22 tickers; 19 RESEARCH_REQUIRED) |
| Continuous wakes | Dense (reactive 2m, material 10m, Hermes, research_scheduler, watch jobs) |
| Proactive financial Telegram | **Gated** (canaries / fingerprint dedupe; not always-on blast) |
| Broker auto-execution | **Off by design** |

**Bottleneck for “institutional autonomous advisor”:** not missing timers — missing **held-book living thesis coverage** + **catalyst→thesis→notify closed loop** + **Telegram feedback→preference learning**.

---

## 2. As-is architecture

```text
Holdings / Watch / Market / News / Catalysts
        │
        ▼
┌───────────────────┐     ┌────────────────────┐
│ Data Broker       │────▶│ Desks              │
│ quotes, ind,      │     │ RI / Watch / Defense│
│ catalysts, risk   │     │ Reentry / GG(shadow)│
└───────────────────┘     └─────────┬──────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ S1–S8 plans   │         │ Thesis stores   │         │ Alex Telegram   │
│ material scan │         │ desk@vN LIVE    │         │ desk loop       │
│ reactive 2m   │         │ symbol_* 3/22   │         │ meta+freeform   │
└───────┬───────┘         └────────┬────────┘         └────────┬────────┘
        │                          │                           │
        └──────────────┬───────────┴───────────────────────────┘
                       ▼
              Notify / Delivery (gated)
```

---

## 3. What is LIVE (session builds)

| Capability | PR / tip | Notes |
|------------|----------|-------|
| Reentry desk → `get_cio_snapshot` → S3 | **#414** `86e68ee6` | `intel.state` → READY\|NEAR\|BLOCK; fail-soft |
| Watch intelligence → S7 shape | **#415** `599b8faf` | Promotion-grade only; often 0 READY/GO/NEAR |
| Phase A INTERDICT truth / ACT_NOW gates | **#416** `4198f7bc` | Delivery policy hardening |
| Operator desk loop + P0 meta | **#418** `66399ef0` | `what llm you using` → Flash facts, no reentry dump |
| Freeform Flash agent | **#419** `539a756f` | Soft Trade-AI gather + grounded reasoning |
| Held-book thesis coverage SLA | **#420** `d4003a35` | Report + acquire wrapper + dry revision ledger |

### Pre-existing platform (not invented this session)

- **S1–S8** `cio_situation_detector.py` + `config/cio_situations.yaml`
- **Material scan** / **reactive cycle** / **delivery** systemd timers
- **Hermes** fingerprint queue, CIO worker, autonomous loop, nightly outcome learning
- **RI / Watch / Defense** desks; Gain Guardian **shadow**
- **Catalyst** Data Broker + news→catalyst; Form 4 partial
- **Desk thesis** `cio_theses.py`; symbol thesis modules (acquisition/publish) — coverage thin in prod
- **Operator profile** `cio_operator_profile.py`; advisory KB lessons; intelligence lineage (PARTIAL)
- **Docs→Drive** hourly sync to `Trade_AI_Docs_v2`

---

## 4. Configuration & ops surfaces

### Key systemd timers (user)

| Timer | Cadence | Role |
|-------|---------|------|
| `tradeai-cio-reactive` | ~2m | Event/goal wakes |
| `tradeai-cio-material-scan` | ~10m | Material decisions |
| `tradeai-cio-delivery` | ~5m | Notification outbox |
| `tradeai-hermes-cio-worker` | ~15m | Hermes drain |
| `tradeai-watch-decision-scheduler` | market hours | Watch refresh |
| `tradeai-cio-telegram` | long-running | Converse ingress |
| Advisory / nightly reflection | evening | Lessons / reflection candidates |

### Dual-root debt

Hourly Drive sync and many crons still treat  
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` as **SRC**, while live serve is  
`~/trade-ai-releases/portfolio-server/CURRENT`.  
Docs must land on **main** *and* be present under rebuild `docs/` (or rebuild pulled to tip) before Drive sync.

### Notify gates (do not confuse with converse)

- Converse (ask Alex) can answer while material financial blast remains canaried.
- Drop-in `25-cio-only-live.conf` historically sets converse-related INTERDICT policy; exact-main promote receipts may still stamp `CIO_TELEGRAM_INTERDICT` for portfolio-server — **operator must treat material canary flags as separate from freeform replies**.
- Flags of record: `CIO_SITUATION_NOTIFY`, `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY`, fingerprint dedupe in delivery.

---

## 5. Telegram & learning

| Surface | Status |
|---------|--------|
| Freeform grounded answers | **LIVE** (e.g. JEPI fit / covered-call Q&A 2026-08-20) |
| Meta runtime/LLM | **LIVE** (#418) |
| Reentry desk cards | **LIVE** (regex + desk loop) |
| Ingest operator Telegram replies → prefs/sentiment | **MISSING / PARTIAL** (profile store exists; no auto feedback loop) |
| Disposition SLA on proactive cards | **MISSING** (Phase 3) |

---

## 6. Autonomy Directive — gap matrix

Maps the operator’s Autonomous TradeAI Directive to current truth.

| Requirement | Status | Evidence / next |
|-------------|--------|-----------------|
| Continuous event-driven monitoring (price, tech, volume, earnings, news, …) | **PARTIAL** | Sensors + timers LIVE; not all events revise theses or alert |
| SEC filings depth (beyond Form 4) | **PARTIAL** | Form 4 scalp/context; no full 8-K/10-Q/transcript stack |
| Options unusual activity | **MISSING** | Paper options ≠ institutional flow product |
| Living thesis per held security | **PARTIAL** | Code LIVE; **~14% CURRENT** — Phase 1 SLA (#420) |
| Thesis revision history + evidence | **PARTIAL** | Revision ledger stub (#420); full reassess worker = Phase 2 |
| Long-term + thesis memory compounding | **PARTIAL** | Lineage/lessons/profile exist; MBI≈0 |
| Telegram feedback learning loop | **MISSING** | Freeform answers; replies not auto-ingested |
| Auto Hermes delegation on gaps | **PARTIAL** | Freeform soft-queue + acquisition runner; not universal |
| Hermes iterate to confidence | **PARTIAL** | Queue/TTL/review_mode; human-gated grafts |
| Self-improving from outcomes | **PARTIAL** | Outcome observer thin; advisory lessons Iris-gated |
| Proactive entry/exit/monitor cards | **PARTIAL** | S1–S8/material/GG shadow; notify gated |
| Personalized IPS/risk/style in every rec | **PARTIAL** | Profile/IPS files; not injected everywhere |
| 24/7 institutional IC workflow | **PARTIAL** | Desks + wakes; no single morning IC book with ack SLA |
| Auto broker execution | **OUT** | Explicit non-goal near term |

---

## 7. Phased roadmap (approved)

| Phase | Focus | Status |
|-------|--------|--------|
| **0** | Ops truth / dual-root / notify gate clarity | Ongoing |
| **1** | Held-book thesis coverage SLA + acquire | **Shipped #420** |
| **2** | Catalyst → thesis revise → canary Telegram cards | Next Build |
| **3** | Personalization injector + disposition SLA + TG feedback ingest | Planned |
| **4** | GG publish, SEC/transcripts, scenarios; options only with vendor | Later |

**Spine:** Holdings → living theses → catalyst revisions → evidence cards → Telegram → disposition → memory.

---

## 8. Evidence index (ops closeouts)

| Doc | Topic |
|-----|--------|
| `docs/ops/CIO_REENTRY_S3_WIRE_2026-08-20.md` | #414 |
| `docs/ops/CIO_WATCH_S7_WIRE_2026-08-20.md` | #415 |
| `docs/ops/CIO_OPERATOR_DESK_LOOP_P0_2026-08-20.md` | #418 |
| `docs/ops/CIO_OPERATOR_FREEFORM_AGENT_2026-08-20.md` | #419 |
| `docs/ops/CIO_HELD_THESIS_COVERAGE_2026-08-20.md` | #420 |
| `docs/ops/AUTONOMOUS_ADVISOR_SESSION_CLOSEOUT_2026-08-20.md` | This session rollup |
| `data/cio/held_thesis_coverage_latest.json` | Live SLA artifact (host; not Drive-synced) |

---

## 9. Recovery notes

1. Serve from `~/trade-ai-releases/portfolio-server/CURRENT` after exact-main promote.  
2. Rebuild `docs/` must track `main` for Drive hourly sync.  
3. Re-run: `python3 scripts/cio_held_thesis_coverage.py --report`  
4. Never sync `.env`, holdings JSON, credentials, or Hermes payload dumps to Drive.

---

*Generated 2026-08-20/21 — documentation Build; READ_ONLY.*
