#!/usr/bin/env python3
"""Warm the heavy read-only endpoints after a release restart (LQ-20261107-266).

A restart throws away every in-process cache the API held. The next operator page load pays for them all
at once: measured on ``logs/portfolio_server.log`` at the 2026-11-07T20:47:57Z restart (the server writes
one ``[slow-request]`` line per request over 10 s) —

    20:48:40Z  13.6s  /api/v2/risk
    20:48:41Z  28.7s  /api/v2/cio/pages
    20:48:41Z  29.3s  /api/v2/jobs-catalog
    20:48:43Z  31.0s  /api/v2/jobs-history
    20:49:29Z  16.3s  /api/v2/system/control-plane-surface-authority

This lane pays those costs itself, right after the restart, so the first human load does not.

Restart-scoped, not a poll. ``portfolio_server.py`` writes ``PortfolioServerBoot@v1``
(``~/.local/state/tradeai/portfolio_server_boot.json``) at startup carrying ``process_started_at``, ``pid``
and the loaded pin sha. The lane reads that file, and warms only when the identity it names differs from the
one it last warmed — then keeps the short-lived caches hot for ``WARM_WINDOW_SEC`` (most of the routes below
cache for 60 s, so one warm at restart+0 would help only the next 60 s). Outside that window a fire is a
no-op: it reads one file, writes its receipt and exits.

GET only, loopback only, and only the paths in ``ENDPOINTS`` — a reviewed constant, never an argument. No
approve/run/execute route can enter this lane; :func:`_check_endpoint_rail` refuses the shapes that could.

It writes two artifacts, because a warm run whose only output is "it went faster" cannot be audited:
  * ``<state_root>/data/runtime/warm_read_endpoints_state.json`` — the boot identity last warmed and the
    cycle count, so a fire can decide without touching the API;
  * ``<state_root>/data/runtime/warm-read-endpoints_last.json`` — the LaneRunReceipt@v2
    (:mod:`lib.lane_last_receipt`) with per-endpoint status and milliseconds.

Dry run by default (AGENTS §6): ``--dry-run`` prints the plan and writes nothing, no receipt and no state.
``--apply`` is the argv the n8n lane runs.

Read-only: it never writes to the API, never reads a credential (``lib.cc_client`` attaches the loopback
service token from the existing config, as every other loopback caller does), and never stores a response
body — the receipt carries the HTTP status and the byte count only. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:  # run as a script (scripts/ on sys.path)
    from lib.cc_client import cc_urlopen as _cc_urlopen
    from lib.lane_last_receipt import runtime_dir, write_lane_receipt
except ImportError:  # pragma: no cover - imported as scripts.warm_read_endpoints
    from scripts.lib.cc_client import cc_urlopen as _cc_urlopen  # type: ignore[no-redef]  -- the fallback rebinds the name on purpose
    from scripts.lib.lane_last_receipt import runtime_dir, write_lane_receipt  # type: ignore[no-redef]  -- same, for the receipt helper

LANE_ID = "warm-read-endpoints"
DEFAULT_BASE = "http://127.0.0.1:7777"
BOOT_STAMP_ENV = "PORTFOLIO_SERVER_BOOT_STAMP_PATH"  # the name portfolio_server.py itself reads
BOOT_STAMP_DEFAULT = Path.home() / ".local" / "state" / "tradeai" / "portfolio_server_boot.json"
STATE_NAME = "warm_read_endpoints_state.json"

#: One endpoint may take this long before it is recorded as failed. The heavy children have a 25 s deadline;
#: this leaves room for the request to queue behind another one (the measured worst is 31 s).
ENDPOINT_TIMEOUT_SEC = 60.0
#: Keep the short-lived caches hot this long after a restart. Long enough to cover "the operator opens the
#: app as soon as the release lands" (a merge deploys in ~12 min), short enough to bound the CPU the lane spends.
WARM_WINDOW_SEC = 600.0
#: A second warm inside this interval would hit a 60 s cache that is still fresh, so it would warm nothing.
WARM_MIN_INTERVAL_SEC = 95.0
#: Hard cap on warm cycles per restart, so a long window can never turn into an unlimited loop.
WARM_MAX_CYCLES = 6


@dataclass(frozen=True)
class Endpoint:
    path: str
    why: str


#: The reviewed target list. Every entry earned its place with a measured cold cost and a cache the warm can
#: actually fill; keep it SHORT — this runs inside a shared machine and each call is real work.
ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        "/api/v2/system/control-plane-surface-authority",
        "15.0 s cold (LQ-20261107-259), 16.3 s on the first call after the 20:47:57Z restart; an isolated child "
        "re-parses the lineage JSONL, held in-process for 1800 s once computed (STALE_OK_SEC)",
    ),
    Endpoint(
        "/api/v2/cio/pages",
        "28.7 s on the first post-restart load; _shared_get_cached 60 s, single-flight",
    ),
    Endpoint(
        "/api/v2/jobs-catalog",
        "29-30 s on the first post-restart load; built from the cached jobs-history projection",
    ),
    Endpoint(
        "/api/v2/jobs-history",
        "31.0 s on the first post-restart load; the projection every Ops job view reads",
    ),
    Endpoint(
        "/api/v2/risk",
        "13.6 s on the first post-restart load; _shared_get_cached 60 s, single-flight",
    ),
)

#: A target path must never be a mutation route. The list above is a constant, so this is a belt-and-braces
#: rail: a future edit that adds an action endpoint fails here (and in the test that pins this set).
FORBIDDEN_PATH_TOKENS: tuple[str, ...] = (
    "/run", "/approve", "/apply", "/execute", "/order", "/place", "/send", "/kill", "/restart",
    "/retry", "/delete", "/remediate", "/fix-now", "/decision", "/write", "/ingest",
)


def _check_endpoint_rail(endpoints: tuple[Endpoint, ...] = ENDPOINTS) -> None:
    """Refuse a target that is not a read-only GET path. Raises ValueError naming the offender."""
    if not endpoints:
        raise ValueError("no endpoints configured")
    for ep in endpoints:
        path = ep.path
        if not path.startswith("/api/"):
            raise ValueError(f"{path!r}: a target must be an /api/ path")
        if "?" in path or "#" in path:
            raise ValueError(f"{path!r}: query strings belong in the endpoint constant, not here")
        low = path.lower()
        for token in FORBIDDEN_PATH_TOKENS:
            if token in low:
                raise ValueError(f"{path!r} contains {token!r}: a warm lane never calls a mutation route")


def _is_loopback(base: str) -> bool:
    try:
        u = urlparse(base)
    except ValueError:
        return False
    return u.scheme == "http" and (u.hostname or "") in ("127.0.0.1", "localhost", "::1")


def _boot_stamp_path() -> Path:
    override = os.getenv(BOOT_STAMP_ENV)
    return Path(override).expanduser() if override else BOOT_STAMP_DEFAULT


def _read_boot_stamp(path: Path) -> dict[str, Any]:
    """The server's boot stamp, or ``{}`` when it is missing/unreadable (never raises)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _identity(boot: dict[str, Any]) -> str:
    pid = boot.get("pid")
    started = boot.get("process_started_at")
    if pid in (None, "") or not started:
        return "unknown"
    return f"{pid}:{started}"


def _started_at(boot: dict[str, Any]) -> datetime | None:
    raw = boot.get("process_started_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _runtime_base(state_root: Path | str | None) -> Path:
    return Path(state_root) / "data" / "runtime" if state_root else runtime_dir()


def _state_path(state_root: Path | str | None) -> Path:
    return _runtime_base(state_root) / STATE_NAME


def _load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    try:
        from lib.atomic_json_store import atomic_write_json
    except ImportError:  # pragma: no cover - imported as scripts.*
        from scripts.lib.atomic_json_store import atomic_write_json  # type: ignore[no-redef]  -- the package-path fallback

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, doc, indent=1)


def decide(boot_identity: str, started_at: datetime | None, state: dict[str, Any], now: datetime) -> str:
    """Why this fire should (or should not) warm.

    ``restart`` and ``still_in_window`` warm; every other value is a no-op whose reason lands on the receipt.
    A frozen clock or an unparseable stamp must never produce an unbounded loop: the cycle count is a hard cap.
    """
    last_identity = str(state.get("boot_identity") or "")
    # A state file that carries no cycle count is a state file from which nothing was warmed, so 0 is the
    # truth here, not a default standing in for an unknown.
    raw_cycles = state.get("cycles")
    cycles = raw_cycles if isinstance(raw_cycles, int) else 0
    last_warm = state.get("last_warm_at") or ""
    try:
        last_warm_dt = datetime.fromisoformat(str(last_warm)) if last_warm else None
    except ValueError:
        last_warm_dt = None
    if last_warm_dt is not None and last_warm_dt.tzinfo is None:
        last_warm_dt = last_warm_dt.replace(tzinfo=timezone.utc)

    if boot_identity == "unknown":
        # We cannot prove which process is serving, so we cannot prove it is warm. Warm once, then stop:
        # repeating this every fire would be an unconditional poll, which is the pattern this lane replaces.
        return "restart" if cycles == 0 else "boot_stamp_unreadable"
    if boot_identity != last_identity:
        return "restart"
    if started_at is not None and (now - started_at).total_seconds() > WARM_WINDOW_SEC:
        return "window_closed"
    if cycles >= WARM_MAX_CYCLES:
        return "cycle_cap"
    if last_warm_dt is not None and (now - last_warm_dt).total_seconds() < WARM_MIN_INTERVAL_SEC:
        return "too_soon"
    return "still_in_window"


def _fetch(base: str, ep: Endpoint, timeout: float = ENDPOINT_TIMEOUT_SEC) -> dict[str, Any]:
    """One GET. Never raises: a failure is a row, because one dead endpoint must not stop the others."""
    url = base.rstrip("/") + ep.path
    started = time.monotonic()
    row: dict[str, Any] = {"path": ep.path, "ok": False, "ms": None, "status": None, "bytes": 0}
    try:
        with _cc_urlopen(url, timeout=timeout) as resp:  # GET: no data argument, ever
            body = resp.read()
            status = getattr(resp, "status", None)  # absent stays absent: a response with no status is not a 0
            row["status"] = int(status) if status is not None else None
            row["bytes"] = len(body)
            row["ok"] = row["status"] == 200 and bool(body)
    except Exception as exc:  # noqa: BLE001 -- transport failure is data, not a crash
        row["status"] = getattr(exc, "code", None)
        row["error"] = type(exc).__name__  # the type only: the URL carries no secret, the message can
    row["ms"] = round((time.monotonic() - started) * 1000.0, 1)
    return row


def run(
    *,
    apply: bool,
    base: str = DEFAULT_BASE,
    boot_stamp: Path | None = None,
    state_root: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plan (``apply=False``) or warm (``apply=True``). Returns the receipt-shaped result doc."""
    _check_endpoint_rail()
    if not _is_loopback(base):
        raise ValueError(f"refusing non-loopback base {base!r}")
    now = now or datetime.now(timezone.utc)
    boot_path = boot_stamp or _boot_stamp_path()
    boot = _read_boot_stamp(boot_path)
    identity = _identity(boot)
    started_at = _started_at(boot)
    state_path = _state_path(state_root)
    receipt_path = _runtime_base(state_root) / f"{LANE_ID}_last.json" if state_root else None
    state = _load_state(state_path)
    decision = decide(identity, started_at, state, now)

    plan = {
        "lane_id": LANE_ID,
        "boot_stamp": str(boot_path),
        "boot_stamp_readable": bool(boot),
        "boot_identity": identity,
        "process_started_at": boot.get("process_started_at"),
        "loaded_pin_sha": boot.get("loaded_pin_sha"),
        "decision": decision,
        "warm": decision in ("restart", "still_in_window"),
        "state_path": str(state_path),
        "endpoints": [{"path": ep.path, "why": ep.why} for ep in ENDPOINTS],
    }
    if not apply:
        return {**plan, "mode": "dry_run"}

    if not plan["warm"]:
        summary = {
            "decision": decision,
            "warmed": False,
            "boot_identity": identity,
            "process_started_at": boot.get("process_started_at"),
            "endpoints": [],
        }
        write_lane_receipt(
            LANE_ID, ok=True, exit_code=0, script="warm_read_endpoints.py", summary=summary,
            produced_count=0, attempted_count=len(ENDPOINTS), empty_reason="already_warm",
            path=receipt_path,
        )
        return {**plan, "mode": "apply", "summary": summary, "exit_code": 0}

    rows = [_fetch(base, ep) for ep in ENDPOINTS]
    ok_rows = [r for r in rows if r["ok"]]
    all_ok = len(ok_rows) == len(rows)
    raw_cycles = state.get("cycles")
    prior_cycles = raw_cycles if isinstance(raw_cycles, int) else 0
    cycles = (0 if identity != state.get("boot_identity") else prior_cycles) + 1
    summary = {
        "decision": decision,
        "warmed": True,
        "boot_identity": identity,
        "process_started_at": boot.get("process_started_at"),
        "loaded_pin_sha": boot.get("loaded_pin_sha"),
        "warmed_at": now.isoformat(),
        "cycles": cycles,
        "endpoints": rows,
        "failed": [r["path"] for r in rows if not r["ok"]],
        "total_ms": round(sum(r["ms"] for r in rows), 1),  # _fetch always stamps ms, even on a failure
    }
    exit_code = 0 if all_ok else 1
    if all_ok:
        # Only a complete warm is remembered. A partial one leaves the old identity in place, so the next
        # fire retries instead of declaring a restart warm that it never finished.
        try:
            _write_json(
                state_path,
                {"schema": "WarmReadEndpointsState@v1", "boot_identity": identity, "cycles": cycles,
                 "last_warm_at": now.isoformat(), "endpoints": [r["path"] for r in ok_rows]},
            )
        except Exception as exc:  # noqa: BLE001 -- the write failing must not hide the warm that happened
            summary["state_write_error"] = type(exc).__name__
    write_lane_receipt(
        LANE_ID, ok=all_ok, exit_code=exit_code, script="warm_read_endpoints.py", summary=summary,
        produced_count=len(ok_rows), attempted_count=len(rows),
        skipped_reasons={r["path"]: 1 for r in rows if not r["ok"]},
        empty_reason=None if ok_rows else "all_endpoints_failed",
        output_evidence=[{"kind": "state", "path": str(state_path)}],
        path=receipt_path,
    )
    return {**plan, "mode": "apply", "summary": summary, "exit_code": exit_code}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warm the heavy read-only API endpoints after a release restart.")
    ap.add_argument("--apply", action="store_true", help="perform the GETs (the n8n lane's argv); default is a dry run")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write nothing (the default)")
    ap.add_argument("--base", default=os.getenv("TRADEAI_API_BASE", DEFAULT_BASE))
    ap.add_argument("--boot-stamp", default=None, help=f"default: ${BOOT_STAMP_ENV} or {BOOT_STAMP_DEFAULT}")
    ap.add_argument("--state-root", default=None, help="default: the durable data/runtime root")
    ap.add_argument("--json", action="store_true", help="print the whole result document")
    a = ap.parse_args(argv)
    if a.apply and a.dry_run:
        ap.error("--apply and --dry-run are exclusive")
    apply_ = bool(a.apply) and not a.dry_run
    try:
        result = run(
            apply=apply_,
            base=a.base,
            boot_stamp=Path(a.boot_stamp).expanduser() if a.boot_stamp else None,
            state_root=a.state_root,
        )
    except ValueError as exc:
        print(f"[{LANE_ID}] refused: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(result, indent=2, default=str))
    elif not apply_:
        print(f"[{LANE_ID}] DRY RUN — would {result['decision']}: "
              f"{'warm' if result['warm'] else 'do nothing'}; boot {result['boot_identity']}; "
              f"{len(result['endpoints'])} endpoint(s)")
        for ep in result["endpoints"]:
            print(f"    GET {ep['path']}   # {ep['why']}")
        print("    (a dry run writes no receipt and no state)")
    else:
        s = result.get("summary") or {}
        print(f"[{LANE_ID}] apply — decision={s.get('decision')} warmed={s.get('warmed')} "
              f"produced={sum(1 for r in s.get('endpoints', []) if r.get('ok'))}/{len(ENDPOINTS)} "
              f"total_ms={s.get('total_ms')}")
        for r in s.get("endpoints", []):
            print(f"    {r['status']} {r['ms']:>8.1f} ms {r['bytes']:>9} B {r['path']}"
                  + (f"  ({r['error']})" if r.get("error") else ""))
    code = result.get("exit_code")
    return int(code) if isinstance(code, int) else 0  # a dry run carries no exit code: it is a success


if __name__ == "__main__":
    raise SystemExit(main())
