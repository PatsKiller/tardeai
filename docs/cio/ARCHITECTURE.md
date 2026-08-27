# Architecture — Track A vs Track B

Two related but distinct CIO paths run on the same authority contract (`READ_ONLY_ADVISORY`). Architects should not assume thesis injection is universal.

**R11 (2026-08-25):** Portfolio-level attention is `CIOSituationState@v1`
(`scripts/lib/cio_situation_state.py`) sitting *above* S1–S8 draft plans.
Detection is deterministic (no LLM). Narrative synthesis is optional and
governed. See `docs/ops/R11_AUTONOMOUS_INVESTMENT_OFFICE_OPERATOR_VALUE_CLOSEOUT_2026-08-25.md`.

```
                    ┌─────────────────────────────┐
                    │  desk thesis store (desk@vN)  │
                    │  scripts/lib/cio_theses.py    │
                    └─────────────┬───────────────┘
                                  │ safe_context_block / safe_current_pin
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              v                   v                   v
        ┌───────────┐      ┌────────────┐      (partial / optional)
        │  Track A  │      │  Track B   │
        │ Situation │      │ Wake/Run   │
        └───────────┘      └────────────┘
```

---

## Track A — Situation → Plan → Telegram / UI

**Purpose:** Continuous advisory situations from portfolio evidence; operator dispositions; optional notify.

```
Data Broker / snapshot
    → cio_heartbeat / cio_reactive_cycle
    → cio_situation_detector (S0–S8)
    → cio_plans (create/update)
    → cio_plan_enrichment.enrich_plan
         • loads safe_context_block(full=True)
         • stamps thesis_version = safe_current_pin
         • LLM (bridge) or template
         • multi-domain summary when material
    → notify guard (fingerprint ledger) → Telegram CIO bot
    → CC deep links: /v3/cio?plan=<id>
    → operator disposition → learning JSONL + thesis learning_log
```

| Component | Path |
|---|---|
| Detector | [`scripts/lib/cio_situation_detector.py`](../../scripts/lib/cio_situation_detector.py) |
| Plans | [`scripts/lib/cio_plans.py`](../../scripts/lib/cio_plans.py) |
| Enrichment | [`scripts/lib/cio_plan_enrichment.py`](../../scripts/lib/cio_plan_enrichment.py) |
| Telegram | [`scripts/lib/cio_telegram_converse.py`](../../scripts/lib/cio_telegram_converse.py), [`scripts/cio_telegram_bot.py`](../../scripts/cio_telegram_bot.py) |
| Desk note | [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py) |
| API | [`scripts/api_v3_cio.py`](../../scripts/api_v3_cio.py) |
| Config | [`config/cio_situations.yaml`](../../config/cio_situations.yaml), [`config/cio_llm_policy.yaml`](../../config/cio_llm_policy.yaml) |

**Thesis injection: YES (primary).** Enrichment and desk note treat thesis as governing context.

---

## Track B — WakeDispatcher → RunWorker → governed bridge

**Purpose:** Gate-B durable **runs** for scheduled/reactive CIO cycles (briefs, reviews, goal-driven wakes). Sole wake claimant is the dispatcher; worker only executes a `run_id`.

```
PENDING wakes (goal-due, reactive, resume)
    → CIOWakeDispatcher.poll_and_dispatch
         • claim lease, idempotency ledger
         • NEW_RUN → create run | RESUME_RUN → validate existing
    → CIORunWorker.execute(run_id)
         • health → evidence/snapshot
         • specialist handoff (optional wait)
         • Hermes challenge if material (optional wait)
         • governed synthesis (Alex)
         • action write (ledger) + notification enqueue
    → wake COMPLETED only after run terminal
```

| Component | Path |
|---|---|
| Entry | [`scripts/cio_wake_dispatch_entrypoint.py`](../../scripts/cio_wake_dispatch_entrypoint.py) |
| Dispatcher | [`scripts/lib/cio_wake_dispatcher.py`](../../scripts/lib/cio_wake_dispatcher.py) |
| Worker | [`scripts/lib/cio_run_worker.py`](../../scripts/lib/cio_run_worker.py) |
| Goals / wake enqueue | [`scripts/lib/cio_goals.py`](../../scripts/lib/cio_goals.py), reactive cycle |
| Model bridge | [`scripts/lib/cio_governed_model_bridge.py`](../../scripts/lib/cio_governed_model_bridge.py) |

**Authority:** Worker `ADVISORY_ONLY_TOOLS` / `FORBIDDEN_TOOLS` — no broker execution.

**Thesis injection: PARTIAL.**

| Location | Injected? |
|---|---|
| Goal context assembly | May attach `safe_context_block("desk")` into context (`cio_goals`) |
| Dispatcher run context | May copy `desk_thesis` / `thesis_version` when present on wake/ctx |
| RunWorker evidence/synthesis | Goal/thesis **snippets** path (WS3); not the same full desk@vN enrichment contract as Track A plans |
| Governed model bridge | Process routing / budgets for Alex synthesis; not the situation plan pin store |

Do **not** assume every Track B run has a full multi-domain `enrich_plan` payload or a plan_id in `cio_plans.jsonl`.

---

## Where thesis **is** injected (summary)

| Path | Mechanism |
|---|---|
| Plan enrichment | `safe_context_block` + `safe_current_pin` into evidence pack; plan field `thesis_version` |
| Situation post-create enrich | Detector → enrich under live pin |
| Telegram formatters | Active pin on cards / replies |
| Desk synthesis | Pin + full thesis for note sections |
| Goal / wake context | Optional desk block on context dict |
| Learning append | Records pin at disposition time |

---

## Where thesis is **not** (or not fully) governing

| Path | Reality |
|---|---|
| Raw detector fire reasons | Threshold math from config/evidence; thesis does not rewrite fire logic mid-pass |
| Stale open plans | May still show older `desk@v1` until re-enrich |
| Template-only enrichment when LLM deferred | Still gets pin stamp + template thesis-fit, but thinner narrative |
| Forbidden tools / broker | N/A — no thesis can authorize execution |
| Notify ledger | Fingerprint is material content, not pin alone (pin changes can re-open enrich; notify still fingerprint-gated) |
| Full Track B shadow synthesis stub | May produce placeholder synthesis without Track A desk note depth |

---

## Deep links pattern (generic)

- Prefer **path-based** links: `/v3/cio`, `/v3/cio?plan=<plan_id>`.  
- Deployments may prefix a private network base (Tailscale or LAN). Document the **pattern**, not a hard-coded internal IP, as the primary story in shared docs.  
- Absolute URLs are config (`cc_deep_links` / env), not thesis content.

---

## Data plane (`data/cio/`)

| Family | Examples |
|---|---|
| Thesis | `cio_theses.jsonl`, `cio_theses_projection.json` |
| Plans | `cio_plans.jsonl`, `cio_plans_projection.json` |
| Learning | `cio_operator_learning.jsonl` |
| Notify | `cio_plan_notify_ledger.json` |
| Desk note | `cio_desk_note_latest.md` |
| Wakes/runs | `cio_wake_jobs.jsonl`, `cio_wake_dispatches.jsonl`, `cio_runs.jsonl` |
| Events | `cio_events.jsonl`, goals, outcomes |

These are host runtime state (often gitignored). Architects use this docs packet + code; operators use host files + Drive operating packet.

---

## Recent development (2026-08-20 to 2026-08-22)

Audit finding M9 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): a cluster of
CIO Desk reliability/product closeouts landed in this window — advisory-truth
hardening, closed-loop lineage, held-thesis coverage, operator desk loop P0,
outcome-learning closeout, material-notify canary, memory shadow-measure
phase 2, and the CIO Decision Payload (Phase 1) capture going live. Full
pointer index and artifact list: `docs/MASTER_SYSTEM_DOCUMENTATION.md` §24
("Session — 2026-08-20 to 2026-08-22"). This is a pointer, not a re-statement
— Track A/B above should still be read as the current structural description;
none of this window's work changed the Track A/B split itself.

---

## Related

- [THESIS.md](./THESIS.md)  
- [SITUATIONS.md](./SITUATIONS.md)  
- [AUTHORITY.md](./AUTHORITY.md)  
- [WAKE_TRACES_P5.md](./WAKE_TRACES_P5.md)  
