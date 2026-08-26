# TradeAI System State & Autonomy Record — 2026-08-20 (updated 2026-08-21 evening)

**Authority:** READ_ONLY_ADVISORY (no chat→broker execution)  
**CURRENT release:** `fe34482b` until exact-main promote of #434+#435  
**Purpose:** Persistent recoverable record through G.1 / I.0 / A.1 / B.1.  
**Drive mirror:** `Trade_AI_Docs_v2` (folder id `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`)  
**Ground truth (Phase 0, closed):** `docs/_findings/ALEX_AUTONOMY_GROUND_TRUTH_2026-08-21.md`  
**Live ops (this evening):** `docs/ops/MATURATION_G1_I0_A1_B1_2026-08-21.md`

---

## 1. Executive snapshot

| Dimension | State (2026-08-21 evening) |
|-----------|-------------------|
| Portfolio-server tip | Phase 1–2 measure stack on CURRENT `fe34482b`; G.1/I.0/A.1/B.1 on #434/#435 |
| DecisionPayload capture | **ON for producers** (telegram/material-scan/reactive drop-ins). Corpus still **0 v1**. 2026-08-21 5-day window was a **false start** — restart when `payload_v1_count ≥ 1` |
| Memory behavior influence | **OFF** (`MEMORY_BEHAVIOR_INFLUENCE=0`) — do not flip until gate |
| Memory adversarial scan | Flag default **0**; TSLA canary **RETRACTED**; enable `31-memory-adversarial-scan.conf` after #434 promote |
| Memory shadow measure | **LIVE** daily 06:20; honesty fix (0 v1 ≠ available) lands with #435 promote |
| DeepSeek bulk | 10 Peak A/B crons retargeted 10:00–20:00 ET + PEAK_SKIP; autonomous-loop timer **not** retuned |
| Tree-pin | Serve CURRENT; **215** TradeAI unit/cron drift (audit only) |
| Alex Telegram converse | **LIVE** — meta / desk / **freeform** |
| Product notify | **LIVE IIC cards** — HTML bold + severity emoji; raw BOOK dumps suppressed |
| Operator ticker feedback | **LIVE** — journal thin (n=1); learning not evidenced |
| Held symbol theses CURRENT | **13.64%** (3/22); SLA not met |
| LLM daily cap | **$0.50** — do not raise until A.4+A.5 |
| Broker auto-execution | **Off by design** |

**Research lifecycle:** intended methodology `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md`. **Live as of 2026-08-22 night:** `docs/ops/RESEARCH_LIFECYCLE_AS_OF_2026-08-22.md` (holdings SLA true 17/22 CURRENT; skip-gate on; T3 sweep off; agents pull, influence 0).

**Bottleneck:** first real DecisionPayload@v1 row (then restart 5-day clock) → tree-pin → spend attribution → coverage.

### R8 correction and implementation record (2026-08-22)

This section corrects the stale architecture premise used before the R8 audit. It
does not claim deployment. The implementation is on a review branch based on
exact `origin/main` `9dfe437f6e161cb2b6c9ed2c983e23b9fa9de1b7`; live CURRENT remains
`5e91225a` until a separately authorized promotion.

- Research had already minted live symbol theses through an operator-run backfill:
  T0-HOLD 22 minted (17 CURRENT, 5 THIN), reentry 24/25 CURRENT, and T1
  292/299 CURRENT. The missing capability was automatic, quality-gated
  research-to-thesis circulation, not the first existence of live theses.
- Thesis already affected decisions. `cio_investment_product.adjudicate_reentry()`
  loaded the symbol thesis and restricted weak/non-governed readiness. The missing
  controls were first-class research deltas, deterministic change precedence, and
  prevention of fresh invalidation being hidden by an older governed RE_ENTER.
- `ResearchPromptContext@v1` is the canonical redacted stateful input. It contains
  standing thesis/version, prior delta/conclusion, unresolved gaps, deterministic
  current/change data, regime/sector state, RAG support and contradiction,
  eligible operator feedback, non-authoritative memory, ratified lessons, and
  Financial Senses receipts. It retains `MEMORY_BEHAVIOR_INFLUENCE=0`.
- `ResearchThesisDelta@v1` is accepted before reconciliation. Only A-grade material
  `STRENGTHENS`, `WEAKENS`, `INVALIDATES`, or `CONFLICTED` deltas can publish.
  `CONFIRMS` and `NO_NEW_INFO` do not create a thesis version.
- Every new automatic thesis write carries writer/version, source research ids,
  delta id, trigger, run id, source SHA, previous version, and reason for change.
- `ThesisDecisionGate@v1` is deterministic and restriction-only. Fresh
  invalidation blocks effective RE_ENTER while preserving the operator verdict as
  provenance; conflict fails closed to WAIT; weakening can demote; strengthening
  cannot independently promote.
- Exact redacted NOC prompt evidence is
  `docs/_evidence/autonomous_advisory_loop/noc_research_prompt_redacted.json`.
  The read-only host run includes the current `symbol_noc@v3`, prior DeepSeek
  conclusion and dissent, deterministic changes, ratified lessons, and Financial
  Senses receipts. RAG support/contradiction are honestly empty and the packet
  records three acquisition gaps. A prior `ResearchThesisDelta@v1` is also empty
  because that ledger is not deployed. Populated prior-delta behavior is covered
  by fixture tests and must still be proven in a deployed natural replay before
  the loop is called autonomous.

**MATURITY_IMPACT:** research utilization ->
`data/cio/research_thesis_deltas.jsonl`; reasoning -> thesis projection
`write_provenance` + `data/cio/thesis_change_cards.jsonl`. Live metric remains
UNMEASURED until reviewed code is promoted and a natural NOC run completes.

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

`ops_tree_pin_audit.py` (I.0): **215** TradeAI systemd/cron rows still `rebuild` or `hybrid` vs 15 `current`. Rebuild HEAD is `feat/two-way-watchlist-curation`, not `origin/main`.

Drive sync script default SRC is **CURRENT** after #435 (`TRADEAI_DOCS_SRC` override). Until that SHA is what cron executes, hourly sync may still use rebuild. **Never sync a dirty feature branch.**

**Rule:** Sync Drive from `origin/main` `docs/` (clean worktree or CURRENT after overlay).

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
| `docs/investment-office/CANON_IMPLEMENTATION_AUDIT_2026-08-21.md` | Canon claimed vs influencing |
| `docs/_findings/ALEX_AUTONOMY_GROUND_TRUTH_2026-08-21.md` | Phase 0 ground truth |
| `docs/ops/CIO_DECISION_PAYLOAD_PHASE1_2026-08-21.md` | Phase 1 DecisionPayload |
| `docs/ops/CIO_MEMORY_SHADOW_MEASURE_PHASE2_2026-08-21.md` | Phase 2 measure + timer |
| `docs/ops/CIO_PHASE1_2_MEASURE_CLOSEOUT_2026-08-21.md` | Phase 1–2 live closeout |
| `data/cio/held_thesis_coverage_latest.json` | Live SLA artifact (host; not Drive) |
| `data/cio/memory_shadow_measure_latest.json` | Live shadow measure (host; not Drive) |

---

## 10. Recovery notes

1. Serve from `~/trade-ai-releases/portfolio-server/CURRENT` after exact-main promote (`cio_phase2_exact_main_deploy.sh`).  
2. Rebuild `docs/` must track **`origin/main`** before Drive sync.  
3. Re-run: `python3 scripts/cio_held_thesis_coverage.py --report`  
4. Re-run measure: `systemctl --user start tradeai-cio-memory-shadow-measure.service`  
5. Never sync `.env`, holdings JSON, credentials, or Hermes payload dumps to Drive.  
6. Rollback: `cio_phase2_exact_main_deploy.sh rollback` → previous release under `PREV_RELEASE`.

---

*Updated 2026-08-21 — Phase 1–2 measure window live; READ_ONLY.*
