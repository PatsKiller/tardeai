# Hermes Deep Research (Local) — Overnight Runner (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T13:11:03-04:00
Measured at: efcc51365 / not measured

Implements the Phase 210C internal deep-research lane. `scripts/hermes_deep_research_local.py`.

## What it does
Manual/operator-run BATCH_OVERNIGHT job. Picks recently-closed symbols not deep-researched in 7d, gathers
DB context (recent trade outcomes + prior research), prompts a local deep model, and writes an advisory
`deep_research_local` row to `hermes_research_intelligence` via the validated build_insert path.

## Model
- Production: **gemma3:27b** (default) or **gemma3-overnight:latest** (`--model`). BATCH_OVERNIGHT (22:00–06:00).
- gemma4: deferred (not installed). The 4b model is only for fast functional testing.

## Run
```
python3 scripts/hermes_deep_research_local.py                          # dry-run, gemma3:27b, 3 targets, overnight-gated
python3 scripts/hermes_deep_research_local.py --apply --max-rows 3     # overnight only (else dry-run)
python3 scripts/hermes_deep_research_local.py --apply --allow-daytime  # manual run outside the window
python3 scripts/hermes_deep_research_local.py --model gemma3-overnight:latest --apply
```

## Safety
- **Advisory + staging only** — writes hermes_research_intelligence (research_type='deep_research_local').
  NEVER touches broker/order/stop/proposal/holdings/trading.
- Singleton lockfile `/tmp/hermes_deep_research_local.lock`.
- Live kill-switch `data/runtime/HERMES_DISABLED` (NOT the retired sidecar path) → aborts.
- Ollama health gate (reachability/availability; skips cleanly when unhealthy — no flood).
- Overnight window enforced for `--apply` (use `--allow-daytime` for a manual run).
- Deterministic fields stamped from code (hermes_agent_name/research_type/topic/source_views/limitations);
  bounded summary recovery; confidence capped ≤0.8; output passes validate_payload (limitations + source_views required).
- **NOT auto-wired into cron/systemd.** Scheduling it on a nightly timer is a separate operator-approved step.

## Verified
Dry-run VALIDATED + `--apply` COMMITTED a real row (id=2003, symbol IVF) on the fast test model;
gemma3:27b is the production lane (run overnight to allow the 17GB model to warm + synthesize).

## Promotion path
deep_research_local → librarian review → embedding/promote → RAG → future advisory context (Phase 210F).

---
## Scheduled nightly (2026-06-07, operator-approved)
Enabled as a systemd **user** timer (overnight window; runner's --apply self-gates to 22:00–06:00 local).

- `hermes-deep-research-local.timer` — `OnCalendar=*-*-* 02:30:00` (local), Persistent, RandomizedDelaySec=300.
  is-enabled=enabled, is-active=active. Next run ~02:31 local.
- `hermes-deep-research-local.service` — Type=oneshot, TimeoutStartSec=3600 (27b is slow to warm),
  ExecStart=`.venv/bin/python scripts/hermes_deep_research_local.py --apply --max-rows 3 --model gemma3:27b`.

Unit files live in `~/.config/systemd/user/` (same convention as the other hermes-* timers; not repo-tracked).

### Operate
```
systemctl --user list-timers --all | grep deep-research      # next run
systemctl --user status hermes-deep-research-local.service    # last run result
journalctl --user -u hermes-deep-research-local.service       # logs
systemctl --user disable --now hermes-deep-research-local.timer   # stop scheduling (reversible)
touch data/runtime/HERMES_DISABLED                           # emergency kill-switch (runner aborts)
```
Still advisory/staging-only; the timer only runs the same guarded runner. Disable or kill-switch any time.
