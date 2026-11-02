# Plan registry — every approved plan persisted for every agent

Operator, 2026-11-02: "build the plan registry". A plan the operator approves is written once to the
server, with its approval provenance, and every agent — Claude Code, Codex, Cursor, any vendor — can
find it, link its claim/branch/PR, tick its steps and follow it to done or abandoned.

## Where it lives

    ${TRADEAI_STATE_ROOT:-~/trade-ai-releases/persistent-state}/data/coordination/plans/
      <plan-id>.md          front-matter + the plan body (steps as - [ ] boxes)
      ledger.jsonl          append-only: one line per add / link / step_done / status / stalled
      .lock                 flock target; every write is locked and atomic (tmp + replace)

`<plan-id>` is `YYYYMMDD-<slug>-<8 hex>`, derived from the title and body, so the SAME plan always
gets the same id and a retried registration never duplicates it.

## Claude Code: the ExitPlanMode hook

The repository never edits `~/.claude/settings.json`. To register every plan the operator approves in
Claude Code, add this to that file (merge into the existing `hooks` object):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "ExitPlanMode",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/plan_registry_hook.py"
          }
        ]
      }
    ]
  }
}
```

The hook reads Claude Code's JSON on stdin, takes `tool_input.plan`, and writes an approved plan with
`vendor: claude` and the session id as `author_session`. It never fails the tool: a registry problem
is reported on stderr and the exit status is 0.

## Every other vendor: the CLI

    python3 scripts/plan_registry.py add --title "..." --file plan.md \
        --author <session> --vendor codex [--quote "operator words"]
    python3 scripts/plan_registry.py status
    python3 scripts/plan_registry.py list [--status approved] [--json]
    python3 scripts/plan_registry.py show <plan-id>
    python3 scripts/plan_registry.py link <plan-id> --claim <claim-id> --branch wt/x --pr 123
    python3 scripts/plan_registry.py step done <plan-id> "third step text"
    python3 scripts/plan_registry.py set-status <plan-id> in_progress|done|abandoned|stalled
    python3 scripts/plan_registry.py stale --hours 72 [--apply]

`link` also revives a `stalled` plan to `in_progress`: activity is what the stale check watches.

## Stale plans

Every approved or in-progress plan with no `claim`, `branch` or `pr` and no activity for
`stale_hours` (default 72, `config/plan_registry.json`) is set to `stalled` and one line per plan is
appended to the coordinator inbox (`data/coordination/coordinator/inbox.md`). Registration itself is
not activity; only a link, a step or a status change is.

Run it hourly from a host timer (PROPOSED lane `plan-registry-stale` in `config/lane_registry.json`;
installing the timer is operator-only, AGENTS.md §17):

    python3 scripts/plan_registry.py stale --apply

## Read-only API and the Command Center page

Follow-up PR: `/api/v2/plans` (read-only list/detail from the same plan files) and a mobile-first
Command Center "Plans" page (list -> full-screen detail, steps done/left, claim and PR links).

## Authority

Read/write over the coordination plan store only. It never touches a broker, order, stop, position,
credential or release path.
