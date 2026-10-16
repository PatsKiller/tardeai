"""Per-lane run receipt ``<state_root>/data/runtime/<lane_id>_last.json`` (LaneRunReceipt@v1).

n8n refactor wave 1 (cron -> n8n, 2026-10-10). One helper for all four wave-1 buckets (W1-W4 each
grew their own; consolidated here at integration -- W4's ``lane_ok_receipt`` callers were repointed,
no second module). A cron lane whose registry ``output_signal`` is its own ``>> logs/...`` redirect
proves only that cron opened a file (AGENTS.md §9.3, §0 rail 8). This receipt is the durable artifact
a dispatcher or the registry reads instead, as a ``json_key`` signal on ``ok_at``:

* written by a REAL run only -- a dry run never calls :func:`write_lane_receipt`; it calls
  :func:`dry_run_report`, which only prints (AGENTS.md §6: a dry run cannot reach the write);
* ``ok_at`` advances only on a successful run; a failed run still writes the file
  (``status: failed``) but carries the previous ``ok_at`` forward, so a failing lane goes stale
  instead of green;
* resolved against the persistent state root (explicit root -> ``TRADEAI_STATE_ROOT`` ->
  ``persistent_state_root.resolve_durable_dir("data/runtime")``), never the release dir or the
  checkout the code happens to run from (§9.4);
* atomic replace (``atomic_json_store.atomic_write_json``);
* never stores stdout, credentials or exception text: ``error`` and any ``*error`` summary value of
  the form ``"SomeError: message"`` is reduced to the exception type name;
* never raises into the caller: a receipt failure is reported on stderr and returns ``None`` -- the
  run's own result and exit code come first. (W3's original ``write_receipt`` raised; no W3 caller
  or test relied on that.)

:func:`enforce_readonly` puts a dry run's psycopg2 session in READ ONLY at the server.

2026-10-15 (third-party audit DD07, "output truth"): ``LaneRunReceipt@v2``. A writer that passes
``produced_count`` (and optionally ``attempted_count``, ``skipped_reasons``, ``output_evidence``,
``empty_reason``) writes schema v2: every v1 field plus those, plus the ATTEMPT identity the n8n executor hands
the lane in its env (``TRADEAI_RUN_ID``, ``TRADEAI_RUN_ATTEMPT``, ``TRADEAI_RUN_MODE``, ``TRADEAI_CODE_SHA``).
The mutable ``<lane>_last.json`` alone cannot prove the CURRENT attempt produced anything (a previous success or
a concurrent cron write satisfies it), so a v2 receipt with a run id is ALSO written once, immutably (``O_EXCL``),
to ``data/runtime/lane_attempts/<lane_id>/<run_id>.json`` (:func:`attempt_receipt_path`). The executor's
``output_verdict`` reads only that per-attempt file and requires its ``run_id`` / ``lane_id`` to be the run's.
The process exit field is ``exit`` (not ``exit_code``) in both versions.

Monitor bookkeeping only: MBI_BEHAVIOR = 0, no broker, no send.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "LaneRunReceipt@v1"
SCHEMA_V2 = "LaneRunReceipt@v2"
#: Attempt identity the n8n executor sets on the lane's env (scripts/n8n_run_executor.py RUN_ID_ENV ...).
RUN_ID_ENV = "TRADEAI_RUN_ID"
RUN_ATTEMPT_ENV = "TRADEAI_RUN_ATTEMPT"
RUN_MODE_ENV = "TRADEAI_RUN_MODE"
CODE_SHA_ENV = "TRADEAI_CODE_SHA"
ATTEMPTS_DIR = "lane_attempts"
_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9._-]")

_TYPE_PREFIX = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*:")
_MAX_ERROR = 300


def _resolve_durable_dir(rel: str) -> Path:
    try:
        from scripts.lib.persistent_state_root import resolve_durable_dir
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib.persistent_state_root import resolve_durable_dir  # type: ignore[no-redef]
    return Path(resolve_durable_dir(rel))


def runtime_dir(state_root: Path | str | None = None) -> Path:
    """``<state_root>/data/runtime``: explicit root, else TRADEAI_STATE_ROOT, else the durable-dir resolver."""
    if state_root:
        return Path(state_root) / "data" / "runtime"
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / "data" / "runtime"
    return _resolve_durable_dir("data/runtime")


def _state_root() -> Path:
    """The state root whose ``data/runtime`` holds the receipts (back-compat for W1/W2/W3 callers)."""
    return runtime_dir().parent.parent


def receipt_path(
    lane_id: str,
    state_root: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> Path:
    """``<state_root>/data/runtime/<lane_id>_last.json``. Rejects path-like lane ids."""
    if not lane_id or "/" in lane_id or "\\" in lane_id or lane_id.startswith("."):
        raise ValueError(f"bad lane_id {lane_id!r}")
    return runtime_dir(state_root or root) / f"{lane_id}_last.json"


def attempt_receipt_path(lane_id: str, run_id: str, state_root: Path | str | None = None) -> Path:
    """``<state_root>/data/runtime/lane_attempts/<lane_id>/<run_id with ':' -> '_'>.json`` (immutable, one per attempt)."""
    base = receipt_path(lane_id, state_root).parent
    safe = _SAFE_RUN_ID.sub("_", str(run_id))[:160]
    if not safe or safe.startswith("."):
        raise ValueError(f"bad run_id {run_id!r}")
    return base / ATTEMPTS_DIR / lane_id / f"{safe}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def previous_ok_at(path: Path | str) -> str | None:
    try:
        prev = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- no or unreadable previous receipt
        return None
    val = prev.get("ok_at") if isinstance(prev, dict) else None
    return str(val) if val else None


_previous_ok_at = previous_ok_at  # W1/W3/W4 spelling


def _scrub_error(value: Any) -> Any:
    """``"OSError: No space left on device"`` -> ``"OSError"``; other strings are length-capped."""
    if not isinstance(value, str):
        return value
    m = _TYPE_PREFIX.match(value)
    if m:
        return m.group(1)
    return value[:_MAX_ERROR]


def _scrub_summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(summary or {})
    for key, val in list(out.items()):
        if isinstance(key, str) and key.lower().endswith("error"):
            out[key] = _scrub_error(val)
    return out


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def build_receipt(
    lane_id: str,
    *,
    ok: bool,
    exit_code: int | None = None,
    started_at: str | datetime | None = None,
    script: str | None = None,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    previous_ok_at: str | None = None,
    finished_at: str | None = None,
    produced_count: int | None = None,
    attempted_count: int | None = None,
    skipped_reasons: Mapping[str, int] | None = None,
    output_evidence: list[Mapping[str, Any]] | None = None,
    empty_reason: str | None = None,
    run_id: str | None = None,
    output: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    finished = finished_at or now_iso()
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "lane_id": lane_id,
        "script": script or lane_id,
        "mode": "live",
        "status": "ok" if ok else "failed",
        "exit": int(exit_code) if exit_code is not None else None,
        "started_at": _iso(started_at),
        "finished_at": finished,
        "ok_at": finished if ok else previous_ok_at,
        "pid": os.getpid(),
        "summary": _scrub_summary(summary),
    }
    if error:
        doc["error"] = _scrub_error(str(error))
    rid = run_id if run_id is not None else os.environ.get(RUN_ID_ENV)
    if rid:
        doc["run_id"] = str(rid)[:160]
        attempt = os.environ.get(RUN_ATTEMPT_ENV)
        doc["attempt"] = int(attempt) if attempt and attempt.isdigit() else None
        doc["run_mode"] = os.environ.get(RUN_MODE_ENV) or None
        doc["code_sha"] = os.environ.get(CODE_SHA_ENV) or None
    if produced_count is not None:
        if isinstance(produced_count, bool) or not isinstance(produced_count, int) or produced_count < 0:
            raise ValueError("produced_count must be an int >= 0")
        if attempted_count is not None and (
            isinstance(attempted_count, bool) or not isinstance(attempted_count, int) or attempted_count < 0
        ):
            raise ValueError("attempted_count must be an int >= 0")
        skipped = {str(k): int(v) for k, v in (skipped_reasons or {}).items() if not isinstance(v, bool)}
        doc.update(
            {
                "schema": SCHEMA_V2,
                "produced_count": produced_count,
                "attempted_count": attempted_count,
                "skipped_reasons": skipped,
                "output_evidence": [dict(e) for e in (output_evidence or [])],
                "empty_reason": empty_reason if produced_count == 0 else None,
            }
        )
    elif output:
        # #1772 spelling: ``output={...}`` -> validated v2 output fields written ADDITIVELY on the v1 document
        # (marker ``output_fields: LaneRunReceipt@v2``); write_lane_receipt still binds an immutable per-attempt v2
        # copy when the executor handed a run id (train 2026-10-15 d: #1767 + #1772 merged).
        doc.update(output_fields(output))
    return doc


#: LaneRunReceipt@v2 output fields (docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §5), written ADDITIVELY on the
#: v1 document: ``schema`` stays ``LaneRunReceipt@v1`` because v1 readers (system_health_freshness) match it exactly
#: and ignore unknown keys. A health contract's ``expected_output`` rule (§6) reads ``produced_count``.
OUTPUT_FIELDS = ("produced_count", "attempted_count", "skipped_reasons", "empty_reason", "output_evidence")


def output_fields(output: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validated v2 output fields from ``output`` ({} when None). Counts are non-negative ints; skipped_reasons is
    {reason: count}; empty_reason a string or None; output_evidence a list of dicts. Anything else is dropped."""
    if not output:
        return {}
    out: dict[str, Any] = {}
    for key in ("produced_count", "attempted_count"):
        if key in output:
            try:
                out[key] = max(0, int(output[key]))
            except (TypeError, ValueError):
                continue
    sr = output.get("skipped_reasons")
    if isinstance(sr, Mapping):
        clean: dict[str, int] = {}
        for k, v in sr.items():
            try:
                clean[str(k)] = max(0, int(v))
            except (TypeError, ValueError):
                continue
        out["skipped_reasons"] = dict(sorted(clean.items()))
    if "empty_reason" in output:
        er = output.get("empty_reason")
        out["empty_reason"] = str(er) if er not in (None, "") else None
    ev = output.get("output_evidence")
    if isinstance(ev, list):
        out["output_evidence"] = [dict(x) for x in ev if isinstance(x, Mapping)]
    if out:
        out["output_fields"] = "LaneRunReceipt@v2"
    return out


def write_lane_receipt(
    lane_id: str,
    *,
    ok: bool,
    exit_code: int | None = None,
    started_at: str | datetime | None = None,
    script: str | None = None,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    path: Path | str | None = None,
    produced_count: int | None = None,
    attempted_count: int | None = None,
    skipped_reasons: Mapping[str, int] | None = None,
    output_evidence: list[Mapping[str, Any]] | None = None,
    empty_reason: str | None = None,
    output: Mapping[str, Any] | None = None,
) -> Path | None:
    """Atomically replace the lane receipt for one REAL run. Returns the path, or None on failure.

    Never raises: the run's own result comes first. Never call this from a dry-run branch. With ``produced_count``
    the receipt is LaneRunReceipt@v2 and, when the executor set ``TRADEAI_RUN_ID``, it is also written once,
    immutably, as this attempt's receipt (:func:`attempt_receipt_path`).
    """
    try:
        target = Path(path) if path else receipt_path(lane_id)
        doc = build_receipt(
            lane_id,
            ok=ok,
            exit_code=exit_code,
            started_at=started_at,
            script=script,
            summary=summary,
            error=error,
            previous_ok_at=previous_ok_at(target),
            produced_count=produced_count,
            attempted_count=attempted_count,
            skipped_reasons=skipped_reasons,
            output_evidence=output_evidence,
            empty_reason=empty_reason,
            output=output,
        )
        if doc.get("run_id") and (doc.get("schema") == SCHEMA_V2 or doc.get("output_fields") == SCHEMA_V2):
            # the per-attempt copy is always schema v2 (n8n_output_verdict requires it); the #1772 ``output=``
            # spelling keeps the mutable _last.json on v1 for v1 readers.
            _write_attempt_receipt(lane_id, {**doc, "schema": SCHEMA_V2}, target)
        try:
            from scripts.lib.atomic_json_store import atomic_write_json
        except ImportError:
            from lib.atomic_json_store import atomic_write_json  # type: ignore[no-redef]
        atomic_write_json(target, doc, indent=1)
        return target
    except Exception as exc:  # noqa: BLE001 -- the receipt must never mask the run's own result
        print(f"[{lane_id}] lane receipt write failed: {type(exc).__name__}", file=sys.stderr)
        return None


def _write_attempt_receipt(lane_id: str, doc: Mapping[str, Any], last_target: Path) -> Path | None:
    """Create the per-attempt receipt with O_EXCL: written once, never replaced (a second write for the same attempt
    is refused and reported). Sits next to ``last_target``'s directory so a test or explicit path stays together."""
    attempt = attempt_receipt_path(lane_id, str(doc["run_id"]), last_target.parent.parent.parent)
    attempt.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(dict(doc), indent=1, sort_keys=True, default=str) + "\n").encode("utf-8")
    try:
        fd = os.open(attempt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        print(f"[{lane_id}] attempt receipt already exists (immutable): {attempt.name}", file=sys.stderr)
        return None
    with os.fdopen(fd, "wb") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    return attempt


def write_receipt(
    name: str,
    *,
    ok: bool,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    started_at: str | datetime | None = None,
    path: Path | str | None = None,
    exit_code: int | None = None,
) -> Path | None:
    """W3 spelling of :func:`write_lane_receipt` (``name`` is the lane id and the script name)."""
    return write_lane_receipt(
        name,
        ok=ok,
        exit_code=exit_code,
        started_at=started_at,
        summary=summary,
        error=error,
        path=path,
    )


def dry_run_report(
    lane_id: str,
    summary: Mapping[str, Any],
    *,
    would_write: list[str] | None = None,
    receipt: Path | str | None = None,
) -> dict:
    """Print (and return) what a real run would have written. Writes nothing."""
    try:
        target = str(receipt or receipt_path(lane_id))
    except Exception as exc:  # noqa: BLE001 -- a dry run reports, it does not fail on path resolution
        target = f"<unresolved: {type(exc).__name__}>"
    report = {
        "dry_run": True,
        "lane_id": lane_id,
        "would_write_receipt": target,
        "would_write": list(would_write or []),
        "summary": dict(summary),
    }
    print("DRY-RUN " + json.dumps(report, default=str, sort_keys=True), flush=True)
    return report


def enforce_readonly(conn: Any) -> Any:
    """Make a dry run's DB session READ ONLY at the server (AGENTS.md §6).

    Defence in depth for scripts whose dry run still runs SELECTs: even if a write statement were
    reached, PostgreSQL refuses it (``cannot execute INSERT in a read-only transaction``) instead of
    the script trusting a flag. Ends any open transaction first (set_session must run outside one).
    """
    set_session = getattr(conn, "set_session", None)
    if set_session is None:  # not a psycopg2 connection (test double); nothing to enforce
        return conn
    conn.rollback()
    set_session(readonly=True)
    return conn
