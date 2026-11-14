"""One probe of the user systemd failed set, shared by every surface that names failed units.

Before this module four readers each ran their own ``systemctl`` query over three different scopes:

* ``platform_health.probe_failed_units`` — ``list-units --failed tradeai*`` (the /ops Platform row);
* ``needs_action.probe_failed_units`` — ``list-units tradeai* --state=failed`` (the ops queue items);
* ``queue_runtime_status.get_timer_status`` — one ``systemctl --user show`` per timer, ``service_state =
  ActiveState`` (the /ops queue's ``needs_attention``);
* ``n8n_maturity.dims_signal`` — ``list-units --failed`` with no pattern (the maturity score).

All four now read this module: the two /ops cards and the maturity dimension through :func:`snapshot` (the maturity
dimension through ``probe.run`` with :data:`ARGV`, so its tests stay hermetic), and the queue's ``needs_attention``
through :func:`attention`.

The Platform and the queue therefore disagreed about which unit had failed — the Platform listed the three
failed ``tradeai*`` units while the queue named ``hermes-deep-research-local`` instead of
``tradeai-deploy-on-main`` — and neither stated its scope or when it had looked. OPS-C1 (operator OP-020,
2026-11-14): one adapter, one snapshot, source scope and observation time on every surface, so a surface that
shows fewer units says *why* instead of silently showing a different list.

Design rules, deliberately:

* **One call, unscoped.** The probe asks systemd for the whole failed set in a single bounded call. Scoping is a
  *presentation* decision made by :func:`select`, not a second query — two queries cannot share an observation time.
* **Unanswered is not zero.** When systemd cannot answer, ``answered`` is False and ``reason`` says why; ``units`` is
  empty. A reader must render UNKNOWN with that reason, never "0 failed".
* **No invented clock.** ``as_of`` is when this module read systemd, never when a page was assembled. The queue's
  per-timer ``show`` loop had no such clock at all.
* **``outside`` is named.** A surface with a narrower scope gets the units it does not own back in ``outside`` so it
  can say "N user unit(s) outside this card's scope failed: …" — the disagreement becomes an explained difference.

Pure parsing and selection are separated from the subprocess so tests drive them without a live systemd.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

SCHEMA = "FailedUnits@v1"

#: ``--all`` so a unit that is loaded but not currently in a failed job still answers; ``--state=failed`` rather than
#: ``--failed`` for symmetry with the needs-action reader; **no pattern** — see the module docstring.
ARGV: tuple[str, ...] = (
    "systemctl",
    "--user",
    "list-units",
    "--all",
    "--state=failed",
    "--no-legend",
    "--plain",
    "--no-pager",
)

SCOPE = "systemctl --user list-units --state=failed --all — every user unit, no pattern"
SOURCE = " ".join(ARGV)

#: Bounded like every other /ops probe (platform_health.PROBE_TIMEOUT_S). A systemctl that cannot answer in this
#: window is reported UNKNOWN with a reason, never retried inline.
DEFAULT_TIMEOUT_S = 2.0


def _iso(now: Optional[Callable[[], datetime]] = None) -> str:
    return (now() if now else datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def parse_failed_units(text: str) -> list[dict]:
    """Parse ``systemctl --user list-units --state=failed`` lines. Pure, and never filters by name.

    systemd prints a leading bullet (``●``) on interactive terminals; ``--no-legend --plain`` usually omits it, but
    both forms are accepted. Columns are ``UNIT LOAD ACTIVE SUB DESCRIPTION`` with the description free text.
    """
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.replace("●", " ").strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[0].endswith((".service", ".timer", ".socket", ".path", ".mount", ".target")):
            continue
        out.append(
            {
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4].strip() if len(parts) > 4 else "",
            }
        )
    out.sort(key=lambda u: u["unit"])
    return out


def probe_failed_units(
    run: Optional[Callable[..., Any]] = None,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    now: Optional[Callable[[], datetime]] = None,
) -> dict:
    """Read the user failed set once. Never raises: an unanswerable probe is ``answered: False`` with a reason."""
    started = time.monotonic()
    env_run = run or subprocess.run
    snapshot: dict = {
        "schema": SCHEMA,
        "scope": SCOPE,
        "source": SOURCE,
        "argv": list(ARGV),
        "timeout_s": timeout_s,
        "answered": False,
        "reason": None,
        "units": [],
        "as_of": None,
        "ms": 0,
    }
    try:
        proc = env_run(list(ARGV), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        snapshot["reason"] = f"systemctl timed out after {timeout_s:g} s"
        snapshot["ms"] = int((time.monotonic() - started) * 1000)
        snapshot["as_of"] = _iso(now)
        return snapshot
    except OSError as exc:
        snapshot["reason"] = f"systemctl not runnable: {type(exc).__name__}"
        snapshot["ms"] = int((time.monotonic() - started) * 1000)
        snapshot["as_of"] = _iso(now)
        return snapshot
    snapshot["ms"] = int((time.monotonic() - started) * 1000)
    rc = getattr(proc, "returncode", 1)
    if rc != 0:
        detail = str(getattr(proc, "stderr", "") or "").strip()[:160]
        snapshot["reason"] = f"systemctl exit {rc}" + (f": {detail}" if detail else "")
        snapshot["as_of"] = _iso(now)
        return snapshot
    snapshot["answered"] = True
    snapshot["units"] = parse_failed_units(str(getattr(proc, "stdout", "") or ""))
    snapshot["as_of"] = _iso(now)
    return snapshot


#: Two /ops readers in one server process (platform-health and needs-action) must not run two ``systemctl`` calls
#: seconds apart and then disagree about the observation time. A short in-process cache lets them share one snapshot.
#:
#: The cache is OPT-IN, and joining it is a per-reader decision (review F2, 2026-11-14T20:44Z): a reader that
#: injects its own ``run`` (a test, or a wrapper around another runner) probes unless it passes ``use_cache=True``.
#: In production the queue (``run=None``) and the Platform (``use_cache=deps.runner is subprocess.run``) join; a
#: reader whose payload is itself cached (the Platform's 30 s ``CACHE_TTL_S``, which can serve last-good with
#: ``age_s``) may still state a different, older ``as_of``. What the operator can rely on is each surface's own
#: ``as_of`` plus its freshness — and, within one 5 s window of one process, one ``systemctl`` reading.
CACHE_TTL_S = 5.0
_CACHE: dict = {"at": None, "snapshot": None}
_CACHE_LOCK = threading.Lock()


def _default_run(argv, **kw):
    """systemctl --user needs the user runtime bus when there is no login session (cron, systemd units)."""
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    kw.setdefault("env", env)
    return subprocess.run(argv, **kw)


def snapshot(*, run: Optional[Callable[..., Any]] = None, timeout_s: float = DEFAULT_TIMEOUT_S,
             now: Optional[Callable[[], datetime]] = None,
             use_cache: Optional[bool] = None) -> dict:
    """One snapshot per ``CACHE_TTL_S`` for the default runner; a custom runner (tests) always probes.

    ``use_cache`` overrides the default (``run is None or run is subprocess.run``), so hermetic tests that inject a
    fake never see a cached live reading and production never sees two readings where one would do.
    """
    cache_on = (run is None or run is subprocess.run) if use_cache is None else use_cache
    if cache_on:
        with _CACHE_LOCK:
            at, cached = _CACHE["at"], _CACHE["snapshot"]
            if at is not None and cached is not None and (time.monotonic() - at) < CACHE_TTL_S:
                return dict(cached, cached=True)
    snap = probe_failed_units(run or _default_run, timeout_s=timeout_s, now=now)
    if cache_on:
        with _CACHE_LOCK:
            _CACHE["at"] = time.monotonic()
            _CACHE["snapshot"] = dict(snap)
    return snap


def _matches(unit: str, prefixes: Iterable[str]) -> bool:
    return any(unit.startswith(p) for p in prefixes)


def select(
    snapshot: Optional[dict],
    prefixes: Optional[Iterable[str]] = None,
    *,
    scope_label: Optional[str] = None,
) -> dict:
    """A surface's view of one snapshot: the units it owns, the ones it does not, and the snapshot's clock.

    ``prefixes=None`` means "every failed user unit" (the queue and the maturity score). A narrower surface passes
    its prefixes and gets its units back in ``units`` and everything else in ``outside``, so it can name both.
    """
    snap = snapshot or {}
    units = list(snap.get("units") or [])
    prefixes = tuple(prefixes) if prefixes else ()
    if prefixes:
        mine = [u for u in units if _matches(u.get("unit", ""), prefixes)]
        outside = [u for u in units if not _matches(u.get("unit", ""), prefixes)]
        scope = scope_label or f"failed user units named {', '.join(prefixes)}*"
    else:
        mine, outside = units, []
        scope = scope_label or SCOPE
    return {
        "units": mine,
        "outside": outside,
        "count": len(mine),
        "outside_count": len(outside),
        "scope": scope,
        "source": snap.get("source") or SOURCE,
        "as_of": snap.get("as_of"),
        "answered": bool(snap.get("answered")),
        "reason": snap.get("reason"),
    }


def attention(selection: dict, skip: Iterable[str] = ()) -> list[dict]:
    """``needs_attention`` entries for a surface that lists failed units (the /ops queue, OPS-C1).

    ``skip`` is the set of job ids the caller already reported as "last run failed", so one timer is not listed
    twice. An unanswered selection yields no entries — the caller must publish ``answered: false`` with the reason,
    and the page must render UNKNOWN rather than an empty list that reads as an all-clear.
    """
    if not selection or not selection.get("answered"):
        return []
    skipped = set(skip or ())
    out: list[dict] = []
    for unit in selection.get("units") or []:
        job_id = (unit.get("unit") or "").rsplit(".", 1)[0]
        if job_id in skipped:
            continue
        out.append(
            {
                "job_id": job_id,
                "unit": unit.get("unit"),
                "reason": "service failed",
                "service_state": unit.get("active") or "failed",
                "source": selection.get("source"),
                "as_of": selection.get("as_of"),
            }
        )
    return out


def summary(selection: dict) -> str:
    """One sentence for a card: what this scope sees, what it does not, from which source, read when.

    An unanswered probe is named with its reason — the sentence never degrades into "0 failed".
    """
    if not selection.get("answered"):
        return (
            f"Failed units unknown: {(selection.get('reason') or 'no answer from systemctl')}. "
            f"Nothing here is known to be OK. Source: {selection.get('source')}"
        )
    n = selection.get("count", 0)
    parts = [f"{n} failed unit{'' if n == 1 else 's'} in scope ({selection.get('scope')})"]
    if n:
        parts.append(", ".join(u.get("unit", "") for u in selection.get("units") or []))
    outside = selection.get("outside") or []
    if outside:
        parts.append(
            f"{len(outside)} outside this scope: " + ", ".join(u.get("unit", "") for u in outside)
        )
    parts.append(f"source: {selection.get('source')}; as of {selection.get('as_of')}")
    return " · ".join(parts)
