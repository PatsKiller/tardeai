# Plan registry — every registered plan persisted for every agent

Operator, 2026-11-02: "build the plan registry". A plan is written once to the server, with its
provenance, and every agent — Claude Code, Codex, Cursor, any vendor — can find it, link its
claim/branch/PR, tick its steps and follow it to done or abandoned.

## Status lifecycle

    registered -> in_progress -> done
                 \-> abandoned / stalled

`registered` is the default and it is **not** an approval. It records only that the plan exists and
who registered it. A plan becomes `approved` only when the caller writes it explicitly (`add
--status approved`, or `set-status <id> approved`) — the CLI and the hook never claim approval on
someone else's behalf. Only `approved` and `in_progress` plans are eligible for the stale scan; a
`registered` plan is not "an approved plan nobody picked up".

## Where it lives

    ${TRADEAI_STATE_ROOT:-~/trade-ai-releases/persistent-state}/data/coordination/plans/
      <plan-id>.md          front-matter + the plan body (steps as - [ ] boxes)
      ledger.jsonl          append-only: one line per add / link / step_done / status / stalled
      .lock                 flock target; every write is locked and atomic (tmp + replace)

`<plan-id>` is `<slug>-<12 hex>`, derived from the title, body and author, so the SAME plan always
gets the same id and a retried registration never duplicates it (the day is deliberately not part of
the id).

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
            "command": "python3 <repo-root>/scripts/plan_registry_hook.py"
          }
        ]
      }
    ]
  }
}
```

The hook reads Claude Code's JSON on stdin, takes the plan text (`tool_response.plan` first, then
a `planFilePath` file, then `tool_input.plan`), and **registers** it with `status: registered`,
`vendor: claude` and the session id as `author_session`. It never passes `status: approved`: an
`ExitPlanMode` payload is evidence that a plan exists, not a claim that the operator approved it. A `planFilePath` is read ONLY when it is a plan-shaped document — a `*.md` / `*.markdown` / `*.txt`
name that is not a dotfile and not credential-shaped (`token`, `secret`, `credential`, `password`,
`api_key`, `.env`, `id_rsa`, `.pem`, `.key` are refused) — inside one of two directories: the plan
store (`<state root>/data/coordination/plans`) or `~/.claude/plans`. It must be a regular,
non-symlink file of at most 256 KiB, valid UTF-8 text with no NUL byte. Nothing else is plan input,
so the shared registry can never be used to copy a credential or an arbitrary file. It never fails the tool: a registry problem
is reported on stderr and the exit status is 0.

## Every other vendor: the CLI

    python3 scripts/plan_registry.py add --title "..." --file plan.md \
        --author <session> --vendor codex [--quote "operator words"] \
        [--status registered|approved|in_progress|done|abandoned|stalled]

`--status` defaults to `registered`. Only pass `--status approved` when you are recording an actual
approval; the default registration is not one.

`approved_at` is never defaulted: it is recorded only when the caller passes `--approved-at` (or the
library receives one). A registration therefore carries no approval time, and the page prints an
approval date only for a plan whose status is `approved`. The ExitPlanMode hook records none.

`author_session` is a self-declared string. Each plan also records `author_proof`: `claim:<id>` when
that session matches a live claim on the board, otherwise `self-declared` — weigh it accordingly; it
is not an authentication. Both `author_proof` and `stalled_since` are served by the read-only API
(list and detail).
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
written as ONE dated notice file per run into the live coordinator inbox directory
(`data/coordination/coordinator/inbox/codex/<ts>-plan-stalled.md`) that the lead reads. Registration itself is
not activity; only a link, a step or a status change is.

Run it hourly from a host timer (PROPOSED lane `plan-registry-stale` in `config/lane_registry.json`;
installing the timer is operator-only, AGENTS.md §17):

    python3 scripts/plan_registry.py stale --apply

## Read-only API and the Command Center page

Follow-up PR: `/api/v2/plans` (read-only list/detail from the same plan files) and a mobile-first
Command Center "Plans" page (list -> full-screen detail, steps done/left, claim and PR links).

The endpoint answers `200` with
`{"ok": true, "data": {"schema": "PlanRegistryView@v1", "as_of": <UTC ISO-8601>, "store": {...},
"plans"|"plan": ...}}`. `as_of` is the time the answer was built.

`store` says whether the store could actually be read, so a store that was never read can never
render byte-identically to a genuinely empty one:

```json
{"state": "ok" | "absent" | "unlistable", "reason": null | "<fixed string>"}
```

* `ok` — the directory exists and can be listed; `reason` is `null`.
* `absent` — `.../data/coordination/plans` does not exist or is not a directory; reason is
  `"the plan store directory does not exist"`.
* `unlistable` — listing the directory raised `OSError` (e.g. permissions); reason is
  `"the plan store directory cannot be listed"`.

The reason strings are fixed — they never carry a filesystem path or exception text. `plans` stays
`[]` on a gap: no row is ever fabricated. The same `store`/`as_of` fields are present on a detail
read.

An id that fails the id rules is `400` with the fixed `{"ok": false, "error": "invalid plan id"}`; a
valid id with no plan is `404` with `{"ok": false, "error": "plan not found"}`. Neither body echoes
the id or an exception, because the generic dispatcher's `500` would publish both.

A `*.md` file in the store whose front matter cannot be parsed (truncated, missing, or non-UTF-8) is
still listed — as `{"status": "unreadable", "id": ..., "filename": ..., "reason": ...}` — rather than
dropped, so the page never hides a plan the operator approved. A file listed but unreadable (`OSError`,
e.g. an entry that is a directory) is the same kind of row, with the fixed reason
`"the plan file cannot be read"`; one such entry never takes the listing down. The same row surfaces
from `list()`, so the stale scan skips it instead of failing. Valid plans are unchanged; a detail read
(`get()`, or `/api/v2/plans?id=`) of such a file is `404`, never a decode error and never a plan with
zero steps.

## Authority

Read/write over the coordination plan store only. It never touches a broker, order, stop, position,
credential or release path.


## Containment (review 2, 2026-11-02)

The store is not trusted to contain itself through the filesystem alone. Every read and write:

* validates the id (`^[a-z0-9][a-z0-9-]{0,80}$`) and proves the resolved path stays under the plan
  store — including `list()` and `stale()`, which skip any `*.md` whose stem fails that check, so a
  symlink dropped into the store is never served;
* writes through `mkstemp` (`O_EXCL`) inside the store and renames it into place, so a pre-planted
  temp-name symlink cannot redirect the write outside;
* opens the lock and the ledger with `O_NOFOLLOW`, so neither can be a link to another file.

The hook's plan file is read through **one descriptor**: `O_NOFOLLOW` refuses a symlinked final
component, `fstat` decides regular/size on that descriptor, containment is proven on
`/proc/self/fd/<fd>` — the file actually opened — and the bytes are read from the same descriptor, so
swapping the path between a check and the read cannot redirect it. If the kernel cannot say where the
descriptor points, nothing is read.
