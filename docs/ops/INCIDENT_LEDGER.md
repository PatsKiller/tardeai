# Incident ledger, watchers and supervisor

```
Status:   PROPOSED (code + units in this PR; host timers not installed until the install steps below run)
as_of:    2026-10-27
Authority: operator 2026-10-27 (verbatim below); AGENTS.md §0, §28.14 (self-heal monitor + fixer, reused), §23.14
See also: docs/ops/AGENT_START_HERE.md · docs/ops/self_heal_claude_fixer.md · docs/ops/MERGIFY_DEPLOY_FOUNDATION.md
```

Operator, 2026-10-27: "Could the LLM API monitor these processes if something goes wrong in terms of deployment,
that it will fix it automatically … or tell the agents what to do? … agents … if they have an error, they can't just
drop and leave it. They need to fix it and report it somewhere in a log that you could come back in as a coordinator
and look at it."

## 1. What it is

| Piece | Path | Runs |
|---|---|---|
| Ledger (one writer) | `scripts/lib/incidents.py` | library |
| Agent CLI | `scripts/incident.py` (`open`, `update`, `fix`, `block`, `list`, `show`, `seed`, `rebuild-index`) | by agents |
| Session check | `scripts/check_open_incidents.py --session <id>` | `agent_claim.py stage … pr_open` and `release` (warning) |
| Watchers (deterministic, no model) | `scripts/incident_watchers.py` + `scripts/lib/incident_watchers.py`, `config/incident_watchers.json` | host timer, every 5 min |
| Supervisor (governed model) | `scripts/incident_supervisor.py` + `scripts/lib/incident_supervisor.py`, `config/incident_runbook_actions.json` | host timer, every 10 min |
| Daily brief | `scripts/incident_daily_brief.py` | host timer, 08:00 ET |
| Ops page | Command Center → Ops → **Incidents** (`/v3/ops/incidents`), API `scripts/lib/incidents_view.py` | portfolio server |
| Units | `config/systemd/incidents/tradeai-incident-{watchers,supervisor,daily}.{service,timer}` | user systemd |

## 2. The store

`<persistent-state>/data/coordination/incidents/` (`TRADEAI_INCIDENTS_DIR` overrides; every test sets it):

- `events.jsonl` — append-only `IncidentEvent@v1` rows: `open`, `update`, `attempt`, `fix`, `block`, `resolve`,
  `escalate`, `ack`, `close`, `reopen`. Never rewritten (§0 rule 6). A torn tail line is skipped, never repaired.
- `index.json` — `IncidentIndex@v1`, the materialised fold, rewritten atomically under the same `flock` as the
  append. Derived: `incident.py rebuild-index` recreates it from the events.
- `watchers_last.json`, `watchers_state.json`, `supervisor_last.json`, `supervisor_calls.json`,
  `fixer_requests/<id>.json` — each lane's own receipts and memory. Durable proof that a timer ran (§0 rule 8).

`IncidentRecord@v1`: `id`, `opened_at`, `source {kind: agent|job|lane|deploy|ci|watcher|operator, session, agent, job,
lane, watcher}`, `title`, `where`, `evidence[]`, `owner`, `status open|fixing|fixed|blocked|closed`, `attempts[]`,
`fix_refs[] {kind: pr|commit|receipt|doc|incident, ref}`, `blocked_reason`, `handoff`, `resolution
(fixed|auto_resolved|wont_fix)`, `closed_at`, `acknowledged`, `escalations[]`, `recurrence_of`, `fingerprint`.

- `fixed` and `closed` are terminal. The same fingerprint later opens a **new** incident with `recurrence_of`.
- `fix` needs at least one ref. `block` needs a reason **and** a handoff (the exact next step and for whom).
- Ids are `INC-YYMMDD-xxxxxx` with a non-hex suffix. The comms-editor fingerprint strips 7–40 character hex runs and
  timestamps; 386 deploy alerts were folded into one on 2026-10-26/27 because a SHA was the only difference. An
  incident id survives that normalisation, and every P1 carries one.

## 3. Watchers (every 5 min, no model, never sends)

Each reads an existing producer's output, opens one incident per fingerprint (the SHA, job, lane or symbol is in the
fingerprint) and auto-resolves its own incidents when the condition is gone. A watcher whose input cannot be read
records a gap and resolves nothing.

| Watcher | Input | Opens when |
|---|---|---|
| `deploy_failures` | `data/runtime/deploy_on_main/*.json` (DeployOnMainReceipt@v1) | ≥3 consecutive `deploy_failed`/`verify_failed` for a main SHA |
| `deploy_stuck` | same | main ≠ CURRENT for >30 min (first receipt naming that main SHA) |
| `health_tick` | `data/runtime/health_tick_last.json` | a step in `failed`/`broken`/`timed_out`; receipt >30 min old |
| `expected_services` | `data/runtime/expected_services_last_run.json` | each `off_items` entry |
| `lane_health` | `data/runtime/research_lane_health.json`; `cron_outage_watchdog_latest.json` when fresh | a lane `ok:false`; a missed lane |
| `main_ci` | `gh run list --branch main` (read-only) | a workflow's latest run on the main tip failed |
| `prospectus_queue` | `data/prospectus/queue.json` | a job `running` for >2 h |
| `llm_backlog` | `llm_deferral.queue_summary()` (Postgres; absent = gap) | ≥200 pending deferred requests |
| `cap_hits` | `data/runtime/provider_cost/anthropic_credit.jsonl` | ≥3 cap fallbacks (`CREDIT_PROCESS_CAP`, `PAUSED_TODAY`, …) in 60 min |
| `dirty_checkout` | `git status --porcelain` of the canonical checkout | dirty for >30 min |

The cron outage watchdog's own config is `enabled:false` today; its receipt is read only when fresh.

## 4. Supervisor (every 10 min)

For each `open`/`fixing` incident, oldest first, at most 5 per cycle:

1. **Refused scope, before any model.** A §0 class (orders, stops, sizing, broker, secrets, credentials, `.env`,
   tokens) or a §28.14 item 4 scope (guard, AGENTS.md, hooks, Mergify) → `blocked` + one P1. No model, no action.
2. **Attempt cap.** Three executed actions or fixer dispatches → `blocked` with a coordinator handoff + one P1.
3. **Time box.** Unresolved for 60 min with no escalation → one P1 (the supervisor keeps working it).
4. **Model triage.** Process `incident_supervisor` (`config/llm_process_registry.json`): Anthropic credit, Claude
   Sonnet 5.5 (credit tier `mid` via `ops_process_tiers`), `daily_cost_cap_usd` 1.0, ≤40 calls/day, 30-min cooldown
   per incident. When the credit is unusable the governed walk falls back to OAuth grok/chatgpt; that answer is
   **read-only triage** (recorded, never executed). DeepSeek is not in `allowed_lanes`, and a DeepSeek answer would be
   discarded. The model returns `{class, action, params, rationale}`:
   - `runbook` → runs only an action in `config/incident_runbook_actions.json` that is enabled, applies to the
     incident's watcher and whose params match their regexes. Allowlisted today: `health_tick_step_once`,
     `cron_self_heal`, `deploy_on_main_dry_run` (never promotes), `preserve_dirty_checkout` (needs #2232's
     `preserve_dirty_checkout`; refused while any dirty path changed within 60 min), `stale_lock_report`.
     `stale_lock_reconcile` is listed **disabled**: no existing tool clears a lock (cleanup_stale_locks.sh reports only).
     The child env is the `env_passthrough` list only; no credential reaches it.
   - `code_defect` → writes an `N8nCodeDefect@v1`-shaped request (`fixer_requests/<id>.json`, consumer
     `claude_code_iterative_fix`) and runs `scripts/self_heal_fixer.py --cycle --incident <file> --apply`, once per
     incident. The fixer keeps its own arming, budget, diff guard, refused paths and worktree; it opens a PR and never
     merges or deploys (§28.14 item 3). PR links land in `fix_refs`.
   - `needs_operator` → `blocked` with the model's sentence as the handoff, and one P1 through
     `scripts/telegram_alert.send_telegram` (`priority=P1`, producer `incident_supervisor:<id>`) with the incident id and
     the Command Center link.

The supervisor never merges, pushes, promotes, deletes, orders, stops, sizes, writes a broker or reads a secret.

## 5. Operator surface

Ops → Incidents: counts, a status filter (Active by default), rows with age and source; tap → full-screen sheet with
← Back on a phone (≤820 px), side panel on desktop. The sheet shows the blocked reason and next step, evidence, every
action taken (with the model's rationale and provider), notes and PR links. The only buttons are **Acknowledge** and
**Close as won't fix** (comment required). Each is recorded first in the operator decisions ledger
(`DecisionLedger.incident_decision`, event `INCIDENT_DECISION`, `effect: RECORD_ONLY`), then in the incident ledger with
the decision's hash as `decision_ref`. Until the operator approves the `operator_decisions` domain in
`config/data_source_authority.json`, both buttons answer `STORE_APPROVAL_PENDING` — the same gate as every other
decision in Approvals.

Daily 08:00 ET: one Telegram line (`P2`), e.g. `Incidents Tue Oct 27: 1 open, 0 fixing, 2 blocked; 3 fixed in 24h ·
oldest INC-261027-… 3h05m: … — <link>`.

The prospectus window email audit hook does not exist on `main` yet (#2233 adds `prospectus_window.py`). When it
lands, it calls `scripts.incident_daily_brief.brief_line(incidents.load_records())` for its "open incidents" line.

## 6. Install (host, after merge + deploy)

Dry runs first (§0 rule 7):

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
TRADEAI_STATE_ROOT=~/trade-ai-releases/persistent-state $PY scripts/incident_watchers.py          # would_open / would_resolve
TRADEAI_STATE_ROOT=~/trade-ai-releases/persistent-state $PY scripts/incident_supervisor.py        # no model, no action
$PY scripts/incident.py seed --file config/incident_seed_20261027.json                            # would_seed x3
$PY scripts/incident.py seed --file config/incident_seed_20261027.json --apply                    # history
cp config/systemd/incidents/tradeai-incident-*.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-incident-watchers.timer tradeai-incident-supervisor.timer tradeai-incident-daily.timer
systemctl --user start tradeai-incident-watchers.service && cat ~/trade-ai-releases/persistent-state/data/coordination/incidents/watchers_last.json
```

Proof: `watchers_last.json` / `supervisor_last.json` `as_of` advance every 5 / 10 min, and `events.jsonl` grows.
The units are host timers, not n8n lanes: the supervisor sends alerts, and a monitor never depends on the thing it
monitors (§28.14 item 1, §23.14). They are not yet rows in `config/lane_registry.json` (claimed by the train-removal
session on 2026-10-27); add `KEEP_ON_HOST` rows when it is free.

## 7. Agents

See `docs/ops/AGENT_START_HERE.md` "When something breaks". `check_open_incidents.py` exits 1 when a session leaves an
incident `open` or `fixing`; `agent_claim.py stage … pr_open` and `release` print it as a warning today.
`INCIDENT_CHECK_ENFORCE=1` turns the warning into exit code 3 (enforcement switch for later).
