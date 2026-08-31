# Research Topic Registry — 2026-06-04

Status:      HISTORICAL
as_of:       2026-06-04T20:44:22-04:00
Measured at: efcc51365 / not measured

A managed system-of-record for research topics, built **over the existing `topic_monitor`** table
(no new table / no migration — per the STEP 0 finding that `topic_monitor` already had a rich
schema). Adds an `owner` mapping (TradeAI / Hermes / Shared) and a guarded v3 management modal.
This is the deterministic foundation the future self-learning topic-proposal phase proposes *into*.

## Schema (over `topic_monitor`)
- Added column **`owner TEXT NOT NULL DEFAULT 'shared'`** with `CHECK (owner IN ('tradeai','hermes','shared'))`.
- Backfill: all 17 existing topics → `shared` (current behavior — feed the shared RAG both sides read).
- Backup taken before ALTER (`bak_topic_monitor_owner_<ts>`); table row count unchanged (17).

## Owner routing semantics (symmetric — both engines wired)
| owner | Who researches it |
|-------|-------------------|
| `tradeai` | `topic_ingestion.py` only (`WHERE owner IN ('tradeai','shared')`) |
| `hermes` | Hermes only — `hermes_topic_monitor_bridge.py` enqueues it into `hermes_research_intelligence` (`WHERE owner IN ('hermes','shared')`) |
| `shared` | **BOTH** — TradeAI's `topic_ingestion` *and* Hermes's bridge pick it up (co-owned) |

**Can the two own the same topic? Yes — that's `shared`.** The two engines filter symmetrically
(`('tradeai','shared')` vs `('hermes','shared')`), so a `shared` topic is researched by both;
`tradeai`/`hermes` are exclusive to one.

### Hermes pickup — WIRED (`hermes_topic_monitor_bridge.py`, cron `30 7 * * *`)
Mirrors the news bridge: reads `topic_monitor WHERE owner IN ('hermes','shared')` (stale/never,
deduped), inserts staged `hermes_research_intelligence` rows (`research_type='topic_research'`),
which Hermes's existing coordinator pipeline (auto-promote + embedding) researches — the same
enqueue mechanism Hermes's own librarian uses.

The bridge runs **reconcile-then-enqueue** each cron:
1. **Reconcile completions:** when Hermes has promoted/reviewed a `topic_research` row (its
   completion), stamp `topic_monitor.last_searched` with that row's **actual completion time** (only
   if newer). So `last_searched` reflects "Hermes finished researching it," not merely "enqueued."
   Implemented as read-side reconciliation — no surgery on the live `hermes_coordinator`.
2. **Enqueue:** feed new stale hermes/shared topics as staged rows (no enqueue-time stamp).

Verified end-to-end: enqueue (staged `hermes#719/720`) → dedup on re-run → promote a row
(simulating Hermes completion) → reconcile stamps `last_searched` from the completion time
(trust_estate 2026-05-01 → now, "reconciled 1 completion(s)"). Reconcile lag (≤ daily cron) is well
under the freshness monitor's 72h threshold, so hermes/shared topics don't false-flag stale.

## API (in `api_v2.py`)
- **GET `/api/v2/research-topics/registry`** (`_research_topics_registry()`) — all topics incl.
  paused, with owner + editable fields + `last_searched`/`last_found_count`. Read-only.
- **POST `/api/v2/admin/topic/upsert`** — add/edit (topic_id, display_name, owner, priority,
  enabled, search_queries[], video_queries[], max_age_days, min_articles).
- **POST `/api/v2/admin/topic/toggle`** — enable/pause.
- **POST `/api/v2/admin/topic/delete`** — delete.

All three writes route through the **existing** `admin_write_guard.admin_write()` (access → two-step
confirm → apply → append-only `admin_audit_log`). No new write path was built. Verified end-to-end:
upsert preview → confirm (`audit_id` returned) → DB row created with `owner=hermes` → delete →
audit trail shows both `topic.upsert` and `topic.delete`.

## v3 UI
- **`components/ResearchTopicsModal.tsx`** — lists all topics (owner badge, enabled dot, query
  count, last-searched/stale), add/edit form (incl. owner select + keyword textareas), pause,
  delete. Every write goes through the proven `adminWrite` (preview/confirm) + `AdminConfirmModal`
  two-step guard, so changes show an old→new diff and land in the audit log.
- Mounted in **`IntelligenceHub`** via a "Manage Topics" button in the header.
- `tsc && vite build` passes clean (996 modules).

## What this is foundation for
When the self-learning phase lands, topic *proposals* become `enabled=false` rows in
`topic_monitor` (owner-tagged), approved through this same guarded modal — proposals land in a table
you govern, not researched autonomously. The registry + freshness monitoring (oldest-topic check,
72h) make that verifiable rather than autonomous.

## Validation (2026-06-04)
- **v3 build:** `tsc && vite build` clean (996 modules). Served bundle on `:7777/v3/` confirmed to
  be the latest build (`index-jz104ksK.js`).
- **Playwright screenshots** (`/tmp/manage_topics_modal.png`, `_edit.png`): the "Manage Topics"
  modal renders all 17 topics with owner badges (Shared/both), query counts, last-searched + stale
  markers, Edit/Pause/Del; the edit form shows the Owner→engine dropdown (with the
  "researched by BOTH" / "Hermes only" notes), priority/min-articles/enabled, and keyword textareas.
- **Live-server smoke test (`:7777`) — 7/7 PASS:** GET registry (17 topics, 3 owners) · upsert
  preview→needs_confirm · upsert confirm→applied (audit_id) · registry reflects new owner=hermes ·
  toggle pause→applied · delete→applied · topic removed. Confirms the api_v2 hot-reload picked up
  the new routes, the two-step guard works over HTTP, and CRUD round-trips + cleans up.
- **Guarded UI verified end-to-end with the real token (2026-06-04, post ADMIN_WRITE_TOKEN arming):**
  Manage Topics → toggle → AdminConfirmModal shows the exact `old→new` diff → Confirm → applied +
  written to `admin_audit_log` (operator captured). Tokenless writes now 403; the browser token
  authorizes. Change restored, no net effect.

---
*Built 2026-06-04 over live `topic_monitor`; schema change backed up per IRON RULE; writes guarded
via the existing admin_write path; backend verified end-to-end; frontend builds clean; UI
screenshotted + live-server smoke test 7/7 green.*
