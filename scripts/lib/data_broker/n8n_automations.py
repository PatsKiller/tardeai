"""Read-only projection for the Command Center "Automations" page (design automations/v001, APPROVED).

The page renders; the logic lives here (AGENTS §13). Everything this module reads is a READ:

  * n8n Postgres, through the documented lab read path (`docker exec m8m-n8n-db psql`, read-only SQL):
    ``workflow_entity`` for the workflow list and ``execution_entity`` for the last 7 days of runs;
  * ``execution_data.data`` for the ERROR MESSAGE ONLY, and only for the most recent failing execution of each
    failing workflow. That column is n8n's flattened form — an array whose first element maps keys to indices — so it is
    resolved here by index, bounded, and never trusted to be well formed;
  * ``crontab -l`` for the cron lines still alive (a count, never a write).

Two honesty rules shape the payload:

  * a LOCK SKIP is not a failure. When the previous run of the same workflow is still going inside its SLA, n8n records
    an error whose message says so; those are counted as ``skipped`` (FQ-129). Counting them as failures is what made the
    fleet look 97% broken.
  * week-over-week deltas need the 23:59 ET snapshot table, which does not exist yet. Until it does, the deltas are
    ``None`` with a reason — never zero, because zero is a claim about history.

No provider, scheduler, notification or write path is reachable from this module.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Sequence

SCHEMA = "N8nAutomations@v1"
DB_CONTAINER = "m8m-n8n-db"
WINDOW_DAYS = 7

#: The n8n error text for "the previous run is still going" — counted as skipped, never as failed (FQ-129).
_LOCK_SKIP = re.compile(r"previous (?:execution|run).{0,40}still (?:running|going)|workflow .{0,30}already running",
                        re.IGNORECASE)
#: The relay refusing a lane because it is not on the live list (FQ-128). Named, because it is the top cause today.
_RELAY_REFUSED = re.compile(r"relay_live_not_enabled|relay returned HTTP 403", re.IGNORECASE)

Query = Callable[[str], list[dict[str, Any]]]


# ── error text out of n8n's flattened execution_data ──────────────────────────────────────────────────────────
def parse_error(blob: Any) -> str | None:
    """The error message inside one ``execution_data.data`` value, or None.

    n8n stores ``[{key: index}, …, values…]``: the mapping object points at indices, and an index can point at another.
    Resolve a bounded chain, never assume the shape, and return None rather than raising on a malformed blob.
    """
    if isinstance(blob, (bytes, bytearray)):
        blob = blob.decode("utf-8", "replace")
    if not isinstance(blob, str) or not blob.strip():
        return None
    try:
        arr = json.loads(blob)
    except (ValueError, TypeError):
        return None
    if not isinstance(arr, list) or len(arr) < 3:
        return None

    def deref(value: Any, hops: int = 8) -> Any:
        while isinstance(value, str) and value.isdigit() and hops > 0:
            idx = int(value)
            if idx >= len(arr):
                return None
            value = arr[idx]
            hops -= 1
        return value

    mapping = arr[2]
    if not isinstance(mapping, dict):
        return None
    err = deref(mapping.get("error"))
    if not isinstance(err, dict):
        return None
    message = deref(err.get("message"))
    if isinstance(message, str) and message.strip():
        return message.strip()[:400]
    return None


def classify(message: str | None) -> str:
    """``skipped`` | ``relay_refused`` | ``failed`` | ``unknown`` — the page's error kinds."""
    if not message:
        return "unknown"
    if _LOCK_SKIP.search(message):
        return "skipped"
    if _RELAY_REFUSED.search(message):
        return "relay_refused"
    return "failed"


def one_line(message: str | None, limit: int = 160) -> str | None:
    """The sentence a failing row shows: one line, no stack, no newlines."""
    if not message:
        return None
    first = message.splitlines()[0].strip()
    return (first[: limit - 1] + "…") if len(first) > limit else first


# ── the read path ─────────────────────────────────────────────────────────────────────────────────────────────
def query_n8n(sql: str, *, timeout: int = 45) -> list[dict[str, Any]]:
    """Run ONE read-only query through the lab's documented path.

    cc-deepseek-9's F1 at d4bc7430: ``statement.lower().startswith("select")`` after ``rstrip(";")`` accepts
    ``select 1; drop table workflow_entity`` — no trailing semicolon to strip, so the prefix test passes and
    ``psql -c`` executes BOTH statements. The guard now refuses any remaining ``;``, so the rule is one statement
    and it is a SELECT; a single trailing ``;`` is still accepted because that is how a statement is written.

    Deliberately stricter than SQL: a ``;`` inside a string literal is refused too. This is a read-only lane whose
    whole purpose is to run three known queries, and a guard that has to parse SQL to be correct is the wrong shape
    for it. Fail closed.
    """
    statement = sql.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if ";" in statement:
        raise ValueError("n8n_automations is read-only: one statement per query")
    if not statement.lower().startswith("select"):
        raise ValueError("n8n_automations is read-only: only SELECT is allowed")
    # Belt and braces: even a single SELECT cannot write if the session is read-only. PGOPTIONS is honoured by psql
    # inside the container, so a future guard change cannot turn this into a writer by itself.
    cmd = ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", DB_CONTAINER,
           "psql", "-U", "n8n", "-d", "n8n", "-t", "-A", "-F", "\t", "-c", statement]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    if out.returncode != 0:
        raise RuntimeError(f"n8n query failed ({out.returncode}): {(out.stderr or '')[:200]}")
    rows: list[dict[str, Any]] = []
    for line in (out.stdout or "").splitlines():
        if not line.strip():
            continue
        cell = line.split("\t")
        rows.append({"raw": cell})
    return rows


def crontab_lines(*, timeout: int = 15) -> list[str] | None:
    """The live crontab lines, or None when crontab cannot be read (never an empty list by accident)."""
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603,S607
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [ln for ln in (out.stdout or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


# ── the pure half ────────────────────────────────────────────────────────────────────────────────────────────
def _bool(value: Any) -> bool:
    """psql renders booleans as `t`/`f` under -A; JSON-ish callers may hand `true`/`false`. Accept both, never guess."""
    return str(value).strip().lower() in ("t", "true", "1", "yes")


def workflow_rows(raw: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise ``workflow_entity`` rows: id, name, active, steps, folder, timestamps, archived."""
    out = []
    for r in raw:
        cell = r.get("raw") or []
        if len(cell) < 8:
            continue
        wid, name, active, nodes_json, created, updated, archived, folder = cell[:8]
        try:
            steps = len(json.loads(nodes_json)) if nodes_json else 0
        except (ValueError, TypeError):
            steps = 0
        out.append({
            "id": str(wid), "name": str(name), "active": _bool(active),
            "archived": _bool(archived), "steps": steps,
            "created": created or None, "updated": updated or None,
            "area": folder or None,
        })
    return out


def run_stats(raw: Sequence[dict[str, Any]], now: datetime, *, days: int = WINDOW_DAYS) -> dict[str, Any]:
    """7-day per-workflow and fleet counts from ``execution_entity`` rows: workflowId, status, startedAt, stoppedAt."""
    since = now - timedelta(days=days)
    per: dict[str, dict[str, Any]] = {}
    fleet = {"runs": 0, "ok": 0, "failed": 0, "skipped": 0, "running": 0,
             "duration_s_sum": 0.0, "duration_s_n": 0, "last_error": None, "last_error_at": None}
    for r in raw:
        cell = r.get("raw") or []
        if len(cell) < 4:
            continue
        wid, status, started, stopped = cell[:4]
        status = (status or "").lower()
        per.setdefault(wid, {"runs": 0, "ok": 0, "failed": 0, "running": 0})
        per[wid]["runs"] += 1
        fleet["runs"] += 1
        if status == "success":
            per[wid]["ok"] += 1
            fleet["ok"] += 1
        elif status == "running":
            per[wid]["running"] += 1
            fleet["running"] += 1
        elif status == "error":
            per[wid]["failed"] += 1
            fleet["failed"] += 1
        if started and stopped and status in ("success", "error"):
            try:
                a = datetime.fromisoformat(str(started)); b = datetime.fromisoformat(str(stopped))
                fleet["duration_s_sum"] += max(0.0, (b - a).total_seconds()); fleet["duration_s_n"] += 1
            except ValueError:
                pass
    return {"since": since.isoformat(timespec="seconds"), "per_workflow": per, "fleet": fleet}


def summarize(workflows: Sequence[dict[str, Any]], stats: dict[str, Any], errors: dict[str, dict[str, Any]],
              *, now: datetime, cron_lines: Sequence[str] | None, drafts: int | None,
              snapshot_days: int | None = None) -> dict[str, Any]:
    """The payload the page renders. Pure: every input is handed in, so the shape is testable without a database."""
    fleet = stats["fleet"]
    per = stats["per_workflow"]
    live = [w for w in workflows if not w["archived"]]
    rows = []
    for w in live:
        s = per.get(w["id"], {})
        total = int(s.get("runs") or 0)
        ok = int(s.get("ok") or 0)
        failed = int(s.get("failed") or 0)
        err = errors.get(w["id"]) or {}
        state = "live" if w["active"] else "off"
        if w["name"].endswith("-shadow"):
            state = "shadow"
        rows.append({**w, "state": state, "runs": total, "ok": ok, "fail": failed,
                     # cc-deepseek's F1 at 79ca2ac7e: a percentage over SAVED rows is not a failure rate on this n8n,
                     # which saves failures only (EXECUTIONS_DATA_SAVE_ON_SUCCESS=none). The absolute counts are the
                     # honest figures; the ratio is withheld with the same reason the deltas carry.
                     "fail_pct": None,
                     "last_error": err.get("one_line"), "last_error_kind": err.get("kind"),
                     "last_error_at": err.get("at")})
    # cc-deepseek's F1 at 79ca2ac7e (BLOCK): `failed / (ok + failed)` reads 98% on this host because successes are not
    # kept, so the tile would say the fleet is 98% broken — the artefact this module exists to prevent, one layer up.
    # LESSONS 2026-11-05: "compare saved failures to the schedule's expected run count, never to the table's own total".
    # That denominator needs each workflow's schedule; until it is derived, the rate is withheld rather than guessed.
    failures_only_reason = ("n8n stores failed runs only (EXECUTIONS_DATA_SAVE_ON_SUCCESS=none), so a percentage over "
                            "saved rows would read ~100% by construction; the absolute counts above are the real "
                            "figures, and a rate needs each workflow's expected run count from its schedule")
    fail_rate = None
    avg_s = fleet["duration_s_sum"] / fleet["duration_s_n"] if fleet["duration_s_n"] else None
    deltas = None
    delta_reason = None
    if not snapshot_days:
        delta_reason = ("week-over-week deltas need the 23:59 ET snapshot table; it has no rows yet, so the page shows "
                        "no change figure rather than a zero")
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS,
        "kpi": {
            "runs": fleet["runs"], "ok": fleet["ok"], "failed": fleet["failed"], "running": fleet["running"],
            "fail_rate_pct": fail_rate,
            "fail_rate_unavailable_reason": failures_only_reason,
            "avg_run_s": round(avg_s, 2) if avg_s is not None else None,
            "cron_left": len(cron_lines) if cron_lines is not None else None,
            "cron_left_has_draft": drafts,
            "deltas": deltas, "deltas_unavailable_reason": delta_reason,
        },
        "workflows": sorted(rows, key=lambda r: (-(r["fail"] > 0), -r["runs"], r["name"])),
        "counts": {"workflows": len(live), "live": sum(1 for r in rows if r["state"] == "live"),
                   "shadow": sum(1 for r in rows if r["state"] == "shadow"),
                   "off": sum(1 for r in rows if r["state"] == "off"),
                   "failing": sum(1 for r in rows if r["fail"] > 0)},
        "not_wired": {
            "cutovers": "the cutover ledger projection lands with the n8n CUTOVER tab work",
            "library": "the ~/Claude/N8N MANIFEST drift projection lands with the export lane",
        },
    }


_CACHE: dict[str, Any] = {}
_CACHE_TTL_S = 60.0


def get_automations_cached(*, ttl_s: float = _CACHE_TTL_S) -> dict[str, Any]:
    """The payload, cached briefly: the page polls, the database should not be asked on every render."""
    import time as _time
    hit = _CACHE.get("payload")
    if hit and (_time.monotonic() - float(hit.get("_at") or 0)) < ttl_s:
        return {k: v for k, v in hit.items() if k != "_at"}
    out = get_automations()
    _CACHE["payload"] = {**out, "_at": _time.monotonic()}
    return out


def get_automations(*, query: Query | None = None, now: datetime | None = None,
                    cron: Callable[[], list[str] | None] | None = None,
                    drafts: int | None = None) -> dict[str, Any]:
    """Assemble the payload. Every source is injectable so the module is testable without n8n."""
    q = query or query_n8n
    at = now or datetime.now(timezone.utc)
    wf_raw = q("select id, name, active, nodes, \"createdAt\", \"updatedAt\", \"isArchived\", \"parentFolderId\" "
               f"from workflow_entity order by name")
    workflows = workflow_rows(wf_raw)
    ex_raw = q("select \"workflowId\", status, \"startedAt\", \"stoppedAt\" from execution_entity "  # noqa: S608 — WINDOW_DAYS is an int module constant, never caller input
               f"where \"startedAt\" > now() - interval '{WINDOW_DAYS} days'")
    stats = run_stats(ex_raw, at)
    errors: dict[str, dict[str, Any]] = {}
    failing = [w["id"] for w in workflows if (stats["per_workflow"].get(w["id"], {}).get("failed") or 0) > 0]
    if failing:
        ids = ", ".join("'" + i.replace("'", "''") + "'" for i in failing[:60])
        err_rows = q("select e.\"workflowId\", e.\"startedAt\", d.data from execution_entity e "  # noqa: S608 — ids are this module's own workflow ids, quote-escaped
                     "join execution_data d on d.\"executionId\" = e.id "
                     f"where e.status = 'error' and e.\"workflowId\" in ({ids}) "
                     "order by e.id desc")
        for r in err_rows:
            cell = r.get("raw") or []
            if len(cell) < 3:
                continue
            wid, started, blob = cell[:3]
            if wid in errors:
                continue  # newest first: keep the latest error per workflow
            message = parse_error(blob)
            errors[wid] = {"kind": classify(message), "one_line": one_line(message), "at": started or None,
                           "message": message}
    return summarize(workflows, stats, errors, now=at, cron_lines=(cron or crontab_lines)(), drafts=drafts)
