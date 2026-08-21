# TradeAI System State & Autonomy Record — 2026-08-20 (updated 2026-08-21)

**Authority:** READ_ONLY_ADVISORY (no chat→broker execution)  
**CURRENT release:** `b04f00168397e01bb85c718ae88d9381df162970` (`b04f0016-main-exact-phase2-20260821-103022`)  
**Purpose:** Persistent recoverable record of architecture, configuration, workflows, and autonomy gaps through PR **#425**.  
**Drive mirror:** `Trade_AI_Docs_v2` (folder id `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`)

---

## 1. Executive snapshot

| Dimension | State (2026-08-21) |
|-----------|-------------------|
| Portfolio-server tip | `b04f0016` (#425 bold IIC + dump kill; includes #424 SI queue) |
| Alex Telegram converse | **LIVE** — meta / desk / **freeform** grounded agent |
| Product notify | **LIVE IIC cards** — HTML bold + severity emoji; raw BOOK dumps suppressed |
| Reentry → S3 detector | **LIVE** (#414) |
| Watch → S7 detector | **LIVE** (#415) |
| Symbol Intelligence page | **LIVE dossier** (#424) — queue open count + oldest wait; journal; timeline |
| Operator ticker feedback | **LIVE** (#423) — TG buttons + CC intents → journal |
| Held symbol theses CURRENT | Still thin (~13.6% last measured); coverage SLA tools LIVE |
| Continuous wakes | Dense (reactive 2m, material 10m, Hermes, research_scheduler, watch jobs) |
| Proactive financial Telegram | **Gated** (canaries / fingerprint dedupe; not always-on blast) |
| Broker auto-execution | **Off by design** |

**Bottleneck for “institutional autonomous advisor”:** held-book living thesis coverage + catalyst→thesis closed loop + **membership churn dwell** (UBER/ARKG flip-flops) + preference learning from feedback journal.

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
└───────────────────┘     └────────┬───────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ S1–S8 plans   │         │ Thesis + IIC    │         │ Alex Telegram   │
│ material scan │         │ SymbolIntel obj │         │ desk loop       │
│ reactive 2m   │         │ feedback journal│         │ meta+freeform   │
└───────┬───────┘         └────────┬────────┘         └────────┬────────┘
        │                          │                           │
        └──────────────┬───────────┴───────────────────────────┘
                       ▼
         Notify / Delivery (IIC HTML · gated · dump-suppressed)
                       │
                       ▼
         CC pull: CioHub / SymbolThesisCard / SI dossier
```

**Shared intelligence layer:** Telegram = push (IIC + buttons); Command Center = pull (thesis card + SI page + journal).

---

## 3. What is LIVE (session builds)

| Capability | PR / tip | Notes |
|------------|----------|-------|
| Reentry desk → `get_cio_snapshot` → S3 | **#414** | `intel.state` → READY\|NEAR\|BLOCK |
| Watch intelligence → S7 shape | **#415** | Promotion-grade only |
| Phase A INTERDICT / ACT_NOW gates | **#416** | Delivery policy hardening |
| Operator desk loop + P0 meta | **#418** | Runtime/LLM asks → Flash facts |
| Freeform Flash agent | **#419** | Soft Trade-AI gather + grounded reasoning |
| Held-book thesis coverage SLA | **#420** | Report + acquire + dry revision ledger |
| System-state docs + Drive sync | **#421** | Architecture record |
| Investment Intelligence Card Phase A | **#422** | Per-ticker narrative vs raw diffs |
| IIC feedback + CC thesis card | **#423** | Buttons + journal + continuity |
| Phase D SI dossier + research queue age | **#424** | Open count + oldest wait chip |
| Bold HTML IIC + raw BOOK dump kill | **#425** `b04f0016` | Severity emoji; `parse_mode=HTML` |

### Pre-existing platform (not invented this arc)

- **S1–S8** `cio_situation_detector.py` + `config/cio_situations.yaml`
- **Material scan** / **reactive cycle** / **delivery** systemd timers
- **Hermes** fingerprint queue, CIO worker, autonomous loop, nightly outcome learning
- **RI / Watch / Defense** desks; Gain Guardian **shadow**
- **Catalyst** Data Broker + news→catalyst; Form 4 partial
- **Desk thesis** / symbol thesis modules — coverage still thin in prod
- **Operator profile** / advisory KB / lineage (PARTIAL)
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

**Rule:** Sync Drive only from **`origin/main` `docs/`** checked out into rebuild `docs/` (or a clean main worktree). Never sync a dirty feature branch that deleted ops docs.

### Notify gates

- Converse (ask Alex) ≠ material financial blast.
- Product outbox emits **IIC HTML** (`parse_mode=HTML`); residual raw `Material CIO product change ·` bodies → `SUPPRESSED_RAW_PRODUCT_DUMP`.
- Flags: `CIO_SITUATION_NOTIFY`, `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY`, fingerprint dedupe.

---

## 5. Telegram & learning

| Surface | Status |
|---------|--------|
| Freeform grounded answers | **LIVE** |
| Meta runtime/LLM | **LIVE** (#418) |
| Reentry desk cards | **LIVE** |
| Investment Intelligence Cards | **LIVE** (#422–#425) — HTML + severity emoji + Do this |
| Inline feedback buttons | **LIVE** (#423) — Agree/Disagree/Interested/Defer/Need data/Dismiss |
| Feedback journal continuity | **LIVE** — next card / CC show prior intent |
| NEED_DATA → Hermes/coverage enqueue | **LIVE** fail-soft |
| Preference learning from journal | **PARTIAL / next** — store exists; no auto IPS rewrite |
| Membership churn dwell | **MISSING** — follow-up (UBER↔ARKG flip-flops) |

---

## 6. Command Center surfaces

| Surface | Status |
|---------|--------|
| CioHub + SymbolThesisCard | **LIVE** — journal stance, feedback intents, queue chip |
| `GET/POST /api/v3/cio/intelligence/{SYM}` | **LIVE** — SIO + journal + `research_queue` |
| `/watch/intelligence/:symbol` | **LIVE dossier** (#424) — not SHADOW; queue open+oldest wait; journal; timeline |

---

## 7. Autonomy Directive — gap matrix

| Requirement | Status | Evidence / next |
|-------------|--------|-----------------|
| Continuous event-driven monitoring | **PARTIAL** | Sensors + timers LIVE; not all events revise theses |
| SEC filings depth | **PARTIAL** | Form 4; no full 8-K/10-Q/transcript stack |
| Options unusual activity | **MISSING** | |
| Living thesis per held security | **PARTIAL** | Coverage SLA tools LIVE; % still low |
| Thesis revision history + evidence | **PARTIAL** | Ledger + SI timeline; full catalyst worker next |
| Long-term + thesis memory compounding | **PARTIAL** | Lineage/lessons/profile; MBI≈0 |
| Telegram feedback learning loop | **PARTIAL** | Journal + buttons LIVE; preference ingest next |
| Auto Hermes on gaps | **PARTIAL** | NEED_DATA + freeform soft-queue |
| Hermes iterate to confidence | **PARTIAL** | Queue/TTL; human-gated grafts |
| Self-improving from outcomes | **PARTIAL** | Outcome observer thin |
| Proactive actionable cards | **PARTIAL** | IIC LIVE; churn dwell missing |
| Personalized IPS in every rec | **PARTIAL** | Profile exists; not injected everywhere |
| 24/7 institutional IC workflow | **PARTIAL** | Desks + wakes; no morning IC ack SLA |
| Auto broker execution | **OUT** | Explicit non-goal |

---

## 8. Phased roadmap

| Phase | Focus | Status |
|-------|--------|--------|
| **0** | Ops truth / dual-root / notify gate clarity | Ongoing |
| **1** | Held-book thesis coverage SLA + acquire | **Shipped #420** |
| **A–C** | IIC narrative + feedback + CC | **Shipped #422–#423** |
| **D** | SI dossier + research queue age | **Shipped #424** |
| **D+** | Bold HTML IIC + dump kill | **Shipped #425** |
| **Next** | Churn dwell/hysteresis for membership flips | Planned |
| **2** | Catalyst → thesis revise → canary cards | Planned |
| **3** | Preference ingest from feedback journal + disposition SLA | Planned |
| **4** | GG publish, SEC/transcripts; options with vendor | Later |

**Spine:** Holdings → living theses → catalyst revisions → IIC cards → Telegram feedback → CC pull → memory.

---

## 9. Evidence index (ops closeouts)

| Doc | Topic |
|-----|--------|
| `docs/ops/CIO_REENTRY_S3_WIRE_2026-08-20.md` | #414 |
| `docs/ops/CIO_WATCH_S7_WIRE_2026-08-20.md` | #415 |
| `docs/ops/CIO_OPERATOR_DESK_LOOP_P0_2026-08-20.md` | #418 |
| `docs/ops/CIO_OPERATOR_FREEFORM_AGENT_2026-08-20.md` | #419 |
| `docs/ops/CIO_HELD_THESIS_COVERAGE_2026-08-20.md` | #420 |
| `docs/ops/AUTONOMOUS_ADVISOR_SESSION_CLOSEOUT_2026-08-20.md` | Session rollup through #420 |
| `docs/ops/CIO_INVESTMENT_INTELLIGENCE_CARD_2026-08-21.md` | #422 Phase A |
| `docs/ops/CIO_IIC_FEEDBACK_CC_2026-08-21.md` | #423 Phase B+C |
| `docs/ops/CIO_IIC_PHASE_D_SI_QUEUE_2026-08-21.md` | #424 Phase D |
| `docs/ops/CIO_IIC_TELEGRAM_ACTIONABLE_VISUAL_2026-08-21.md` | #425 visual + dump kill |
| `docs/ops/CIO_IIC_SESSION_CLOSEOUT_2026-08-21.md` | Full IIC arc rollup |
| `docs/investment-office/CANON_IMPLEMENTATION_AUDIT_2026-08-21.md` | Canon frameworks: claimed vs actually influencing decisions |
| `docs/investment-office/BOOK_KNOWLEDGE_INVENTORY.md` | Catalog registry + pointer to audit |
| `data/cio/held_thesis_coverage_latest.json` | Live SLA artifact (host; not Drive) |

---

## 10. Recovery notes

1. Serve from `~/trade-ai-releases/portfolio-server/CURRENT` after exact-main promote (`cio_phase2_exact_main_deploy.sh`).  
2. Rebuild `docs/` must track **`origin/main`** before Drive sync.  
3. Re-run: `python3 scripts/cio_held_thesis_coverage.py --report`  
4. Never sync `.env`, holdings JSON, credentials, or Hermes payload dumps to Drive.  
5. Rollback: `cio_phase2_exact_main_deploy.sh rollback` → previous release under `PREV_RELEASE`.

---

*Updated 2026-08-21 — documentation Build after #424/#425 promote; READ_ONLY.*
