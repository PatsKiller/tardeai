"""Release Train v2 read-only Command Center view (Phase 1, 2026-10-21).

Backs ``GET /api/v2/coordination/release-train`` (summary), ``/queue``, ``/trains/{train_id}`` and ``/events``.
The response contract is ``docs/ops/RELEASE_TRAIN_API.md``; the Command Center Release train tab and Home card are
built against it.

Pattern: ``/api/v2/needs-action`` and ``/api/v2/system/platform-health``. Every source is read off the request
thread in a worker pool with its own deadline (``timeout_s``). A source that misses it, or fails, is UNAVAILABLE with
a reason, never zero, empty or green. Responses are cached for 15 s per route and query.

Sources: the queue store (``release_train_queue``: Postgres, read-only), the PR-hygiene census receipt
(``release_train_census``), the release STOP latch (``release_window.State.read_latch`` when main has it, else the
same file read with the same fail-closed semantics), the policy (``config/release_train_policy.json``) and the clock.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Nothing here writes, merges, releases or arms.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

try:
    from lib import release_train_census as CEN
    from lib import release_train_classify as CLS
    from lib import release_train_contracts as C
    from lib import release_train_queue as Q
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_census as CEN  # type: ignore[no-redef]
    from scripts.lib import release_train_classify as CLS  # type: ignore[no-redef]
    from scripts.lib import release_train_contracts as C  # type: ignore[no-redef]
    from scripts.lib import release_train_queue as Q  # type: ignore[no-redef]

DEFAULT_TIMEOUT_S = 3.0
CACHE_TTL_S = 15.0
ROUTE = "/api/v2/coordination/release-train"
AUTHORITY = "READ_ONLY_ADVISORY"
STOP_NOTE = "Release STOP only. The trading kill switch is separate."
LATCH_STATES = ("ABSENT", "SET", "UNREADABLE")

_EXECUTOR: Optional[cf.ThreadPoolExecutor] = None
_EXECUTOR_LOCK = threading.Lock()
_CACHE: dict[tuple, tuple[float, tuple[int, dict]]] = {}
_CACHE_LOCK = threading.Lock()


class BadRequest(ValueError):
    """A query parameter failed validation; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def _executor() -> cf.ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="release-train-view")
        return _EXECUTOR


def run_probes(probes: Mapping[str, Callable[[], Any]], timeout_s: float = DEFAULT_TIMEOUT_S,
               executor: Optional[cf.Executor] = None) -> dict[str, dict[str, Any]]:
    """Run every probe concurrently off the request thread; each gets what is left of ``timeout_s``.
    Returns {name: {"status": "OK"|"TIMEOUT"|"ERROR", "value", "error", "ms"}}. Never raises."""
    ex = executor or _executor()
    started = time.monotonic()
    futs = {name: ex.submit(fn) for name, fn in probes.items()}
    out: dict[str, dict[str, Any]] = {}
    for name, fut in futs.items():
        remaining = max(0.0, timeout_s - (time.monotonic() - started))
        t0 = time.monotonic()
        try:
            out[name] = {"status": "OK", "value": fut.result(timeout=remaining), "error": None}
        except cf.TimeoutError:
            fut.cancel()
            out[name] = {"status": "TIMEOUT", "value": None, "error": "timeout"}
        except Exception as exc:  # noqa: BLE001 - the error is the evidence
            out[name] = {"status": "ERROR", "value": None, "error": f"error:{type(exc).__name__}"}
        out[name]["ms"] = int((time.monotonic() - t0) * 1000)
    return out


def field(value: Any, as_of: Optional[str], freshness: str, source: str, reason: Optional[str] = None) -> dict:
    """The Field envelope (docs/ops/RELEASE_TRAIN_API.md section 2). UNAVAILABLE always carries value None."""
    if freshness == "UNAVAILABLE":
        value = None
    return {"value": value, "as_of": as_of, "freshness": freshness, "source": source, "reason": reason}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ── windows (pure) ────────────────────────────────────────────────────────────────────────────────────────────


def window_id(local_dt: datetime) -> str:
    iso = local_dt.isoformat()  # 2026-10-21T18:00:00-04:00
    return iso[:16] + iso[19:]


def upcoming_windows(policy: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
    """The next occurrence of each policy window, soonest first. DST-safe: each candidate is built as a wall-clock
    time in the policy timezone (fold=0) and compared in UTC; there is no catch-up for a missed window."""
    tz = ZoneInfo(policy.get("timezone") or "America/New_York")
    local_now = now.astimezone(tz)
    out = []
    for w in policy.get("windows") or ():
        hh, mm = (int(x) for x in str(w["local_time"]).split(":"))
        for days in range(0, 3):
            d = (local_now + timedelta(days=days)).date()
            cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            if cand.astimezone(timezone.utc) > now.astimezone(timezone.utc):
                break
        out.append({"window_id": window_id(cand), "local_time": w["local_time"], "timezone": str(tz.key),
                    "starts_at": cand.isoformat(),
                    "starts_in_seconds": int((cand.astimezone(timezone.utc) - now).total_seconds()),
                    "role": w.get("role"), "enable_order": w.get("enable_order"),
                    "enabled": bool(w.get("enabled")), "note": w.get("note")})
    out.sort(key=lambda x: x["starts_in_seconds"])
    return out


# ── STOP latch (fail closed) ──────────────────────────────────────────────────────────────────────────────────


def resolve_state_dir(release_window_module: Any = None) -> tuple[Path, str]:
    """The release-window state dir, resolved exactly as release_window.py (and release_train_stop.state_dir) do:
    ``TRADEAI_RELEASE_WINDOW_STATE_DIR`` at call time, else ``release_window.STATE_DIR`` (which is
    ``$TRADEAI_STATE_ROOT/data/runtime/release_window``, default ``~/trade-ai-releases/persistent-state/...``).
    Returns (path, source) so the operator can compare it with the runner's."""
    env = os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR")
    if env:
        return Path(env), "env:TRADEAI_RELEASE_WINDOW_STATE_DIR"
    rw = release_window_module
    if rw is None:
        try:
            import release_window as rw  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            rw = None
    if rw is not None and getattr(rw, "STATE_DIR", None) is not None:
        return Path(rw.STATE_DIR), "release_window.STATE_DIR"
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "runtime" / "release_window", "fallback:release_window formula"


def read_latch_file(latch: Path) -> tuple[str, Optional[dict]]:
    """Same semantics as release_window.State.read_latch (branch ops/release-train-20261021): ("ABSENT", None) only
    when no path exists; ("SET", body) for a readable JSON object; ("UNREADABLE", {"error"}) otherwise. Fail closed."""
    try:
        os.stat(latch)
    except FileNotFoundError:
        return "ABSENT", None
    except OSError as exc:
        return "UNREADABLE", {"error": f"stat: {type(exc).__name__}"}
    try:
        body = json.loads(Path(latch).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "UNREADABLE", {"error": type(exc).__name__}
    if not isinstance(body, dict):
        return "UNREADABLE", {"error": "latch is not a JSON object"}
    return "SET", body


def read_stop(state_dir: Optional[Path] = None, *, release_window_module: Any = None) -> dict[str, Any]:
    """The STOP latch as a value dict (not an envelope), in release_window.State.read_latch's vocabulary
    (ABSENT / SET / UNREADABLE). Uses ``State.read_latch`` when the module has it, else the identical file reader."""
    rw = release_window_module
    if rw is None:
        try:
            import release_window as rw  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 - fall back to the file reader with identical semantics
            rw = None
    if state_dir is not None:
        sdir, source = Path(state_dir), "explicit"
    else:
        sdir, source = resolve_state_dir(rw)
    path = sdir / "STOP.json"
    state = getattr(rw, "State", None) if rw is not None else None
    if state is not None and hasattr(state, "read_latch"):
        st, body = state(sdir).read_latch()
        reader = "release_window.State.read_latch"
    else:
        st, body = read_latch_file(path)
        reader = "file"
    st = str(st) if str(st) in LATCH_STATES else "UNREADABLE"  # an unknown verdict is a STOP
    body = body if isinstance(body, dict) else {}
    is_set = st == "SET"
    return {"state": st, "effective_stop": st != "ABSENT",
            "latched_at": body.get("latched_at") if is_set else None,
            "window_id": body.get("window_id") if is_set else None,
            "latch_reason": (body.get("reason") or body.get("outcome")) if is_set else body.get("error"),
            "reader": reader, "path": str(path), "state_dir": str(sdir), "state_dir_source": source,
            "note": STOP_NOTE}


# ── payloads ──────────────────────────────────────────────────────────────────────────────────────────────────


def _store_field(res: Mapping[str, Any], key: str, as_of: str, source: str, *, ok_reason: Optional[str] = None):
    """Map a probe result + store read dict to a Field for ``key``."""
    if res["status"] != "OK":
        return field(None, None, "UNAVAILABLE", source, res["error"])
    r = res["value"]
    if r.get("store_state") != Q.OK:
        return field(None, r.get("as_of"), "UNAVAILABLE", source, r.get("reason") or "db_unavailable")
    return field(r.get(key), r.get("as_of") or as_of, "OK", source, ok_reason or r.get("reason"))


def _policy_field(policy: Optional[Mapping[str, Any]], err: Optional[str], now_iso: str) -> dict:
    if policy is None:
        return field(None, None, "UNAVAILABLE", "config/release_train_policy.json", err or "policy_unreadable")
    errs = CLS.validate_policy(policy)
    return field({"schema": policy.get("schema"), "policy_version": policy.get("policy_version"),
                  "classifier_version": CLS.CLASSIFIER_VERSION, "status": policy.get("status"),
                  "valid": not errs, "errors": errs[:5]},
                 now_iso, "OK" if not errs else "STALE", "config/release_train_policy.json",
                 None if not errs else "policy_invalid")


def _load_policy() -> tuple[Optional[dict], Optional[str]]:
    try:
        return CLS.load_policy(), None
    except FileNotFoundError:
        return None, "policy_missing"
    except (OSError, ValueError) as exc:
        return None, f"policy_unreadable:{type(exc).__name__}"


def _census_settings(policy: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    c = (policy or {}).get("census") or {}
    return {"stale_after_hours": float(c.get("stale_after_hours", CEN.STALE_AFTER_HOURS)),
            "page_cap": int(c.get("page_cap", CEN.PAGE_CAP))}


def _census_with_queue(census_path, queued, now, settings, timeout_s, started) -> dict:
    remaining = max(0.1, timeout_s - (time.monotonic() - started))
    r = run_probes({"census": lambda: CEN.load_census(census_path, queued=queued, now=now, **settings)}, remaining)
    if r["census"]["status"] != "OK":
        return field(None, None, "UNAVAILABLE", f"receipt:{CEN.LANE_ID}", r["census"]["error"])
    return r["census"]["value"]


def _queued_numbers(db_query) -> dict[str, Any]:
    p = Q.probe(db_query)
    if p["state"] != Q.OK:
        return {"store_state": p["state"], "numbers": None}
    rows = db_query("SELECT pr_number FROM release_queue", None, fetch="all")
    if rows is None:
        return {"store_state": Q.DB_UNAVAILABLE, "numbers": None}
    return {"store_state": Q.OK, "numbers": {int(r["pr_number"] if isinstance(r, Mapping) else r[0]) for r in rows}}


def build_summary(db_query, *, now: Optional[datetime] = None, census_path: Optional[Path] = None,
                  stop_dir: Optional[Path] = None, release_window_module: Any = None,
                  timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    now = now or _now()
    now_iso = _iso(now)
    started = time.monotonic()
    policy, perr = _load_policy()
    settings = _census_settings(policy)
    res = run_probes({
        "store": lambda: {"probe": Q.probe(db_query), "counts": Q.read_counts(db_query),
                          "last": Q.read_last_outcome(db_query), "queued": _queued_numbers(db_query),
                          "current": Q.read_current_train(db_query, now=now),
                          "verified": Q.read_last_verified(db_query)},
        "census": lambda: CEN.load_census(census_path, queued=None, now=now, **settings),
        "stop": lambda: read_stop(stop_dir, release_window_module=release_window_module),
    }, timeout_s)
    store = res["store"]
    if store["status"] == "OK":
        sv = store["value"]
        p = sv["probe"]
        store_f = field({"state": p["state"], "tables": p["tables"]}, p["as_of"], "OK", "postgres:to_regclass",
                        p.get("reason"))
        counts_f = _store_field({"status": "OK", "value": sv["counts"]}, "counts", now_iso, "postgres:release_queue")
        last = sv["last"]
        last_f = _store_field({"status": "OK", "value": last}, "outcome", now_iso, "postgres:release_queue_events")
        current_f = _store_field({"status": "OK", "value": sv["current"]}, "train", now_iso,
                                 "postgres:release_queue_events")
        verified_f = _store_field({"status": "OK", "value": sv["verified"]}, "verified", now_iso,
                                  "postgres:release_queue_events")
        queued = sv["queued"]["numbers"]
    else:
        store_f = field(None, None, "UNAVAILABLE", "postgres:to_regclass", store["error"])
        counts_f = field(None, None, "UNAVAILABLE", "postgres:release_queue", store["error"])
        last_f = field(None, None, "UNAVAILABLE", "postgres:release_queue_events", store["error"])
        current_f = field(None, None, "UNAVAILABLE", "postgres:release_queue_events", store["error"])
        verified_f = field(None, None, "UNAVAILABLE", "postgres:release_queue_events", store["error"])
        queued = None
    if queued is not None:
        census_f = _census_with_queue(census_path, queued, now, settings, timeout_s, started)
    elif res["census"]["status"] == "OK":
        census_f = res["census"]["value"]
    else:
        census_f = field(None, None, "UNAVAILABLE", f"receipt:{CEN.LANE_ID}", res["census"]["error"])
    if res["stop"]["status"] == "OK":
        stop_f = field(res["stop"]["value"], now_iso, "OK", "file:release_window/STOP.json")
    else:  # fail closed: the consumer renders UNAVAILABLE as STOPPED (API doc rule 3)
        stop_f = field(None, None, "UNAVAILABLE", "file:release_window/STOP.json", res["stop"]["error"])
    if policy is not None:
        wins = upcoming_windows(policy, now)
        windows_f = field(wins, now_iso, "OK", "clock")
        next_f = field(wins[0] if wins else None, now_iso, "OK" if wins else "UNAVAILABLE", "clock",
                       None if wins else "no_windows")
        armed_f = field(bool(policy.get("armed")), now_iso, "OK", "config/release_train_policy.json",
                        "phase_1_build_only" if not policy.get("armed") else None)
    else:
        windows_f = field(None, None, "UNAVAILABLE", "clock", perr)
        next_f = field(None, None, "UNAVAILABLE", "clock", perr)
        armed_f = field(None, None, "UNAVAILABLE", "config/release_train_policy.json", perr)
    sdir, ssrc = resolve_state_dir(release_window_module) if stop_dir is None else (Path(stop_dir), "explicit")
    state_dir_f = field({"path": str(sdir), "source": ssrc}, now_iso, "OK", ssrc)
    standing = field({"state": "NOT_CONFIGURED",
                      "detail": "No standing delegation record exists (Phase 2, operator-applied)."},
                     now_iso, "OK", "config/release_train_delegation.json")
    data = {
        "schema": "ReleaseTrainSummary@v1", "authority": AUTHORITY, "generated_at": now_iso,
        "timeout_s": timeout_s,
        "armed": armed_f, "standing_policy": standing, "next_window": next_f, "windows": windows_f,
        "queue_counts": counts_f, "current_train": current_f, "last_verified": verified_f,
        "last_outcome": last_f, "stop": stop_f, "state_dir": state_dir_f, "census": census_f, "store": store_f,
        "policy": _policy_field(policy, perr, now_iso),
        "sources": {k: {"status": v["status"], "ms": v["ms"]} for k, v in res.items()},
    }
    fields = [v for v in data.values() if isinstance(v, dict) and "freshness" in v]
    data["status"] = "OK" if all(f["freshness"] == "OK" for f in fields) else "DEGRADED"
    return data


def _int_param(query: Mapping[str, Any], name: str, default: int, lo: int, hi: int, code: str) -> int:
    raw = query.get(name)
    if raw in (None, ""):
        return default
    try:
        v = int(str(raw))
    except ValueError:
        raise BadRequest(code, f"{name} must be an integer {lo}..{hi}") from None
    if not lo <= v <= hi:
        raise BadRequest(code, f"{name} must be an integer {lo}..{hi}")
    return v


def build_queue(db_query, query: Mapping[str, Any], *, now: Optional[datetime] = None,
                census_path: Optional[Path] = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    state = query.get("state") or None
    if state is not None and state not in C.QUEUE_STATES:
        raise BadRequest("bad_state", "state must be one of " + ", ".join(C.QUEUE_STATES))
    limit = _int_param(query, "limit", 200, 1, 500, "bad_limit")
    now = now or _now()
    now_iso = _iso(now)
    policy, _ = _load_policy()
    settings = _census_settings(policy)
    res = run_probes({
        "queue": lambda: Q.read_queue(db_query, state=state, limit=limit, now=now),
        "queued": lambda: _queued_numbers(db_query),
        "census_titles": lambda: _receipt_titles(census_path),
    }, timeout_s)
    started = time.monotonic()
    qr = res["queue"]
    queued = (res["queued"]["value"] or {}).get("numbers") if res["queued"]["status"] == "OK" else None
    census_f = _census_with_queue(census_path, queued, now, settings, timeout_s, started)
    titles = res["census_titles"]["value"] if res["census_titles"]["status"] == "OK" else {}
    bucket_of = {}
    for b in ((census_f.get("value") or {}).get("buckets") or []):
        for n in b["prs"]:
            bucket_of[n] = b["name"]
    base = {"schema": "ReleaseTrainQueue@v1", "authority": AUTHORITY, "generated_at": now_iso}
    if qr["status"] != "OK":
        return {**base, "as_of": None, "freshness": "UNAVAILABLE", "source": "postgres:release_queue",
                "reason": qr["error"], "store_state": "TIMEOUT" if qr["status"] == "TIMEOUT" else "ERROR",
                "total": None, "rows": None, "census": census_f}
    v = qr["value"]
    if v["store_state"] != Q.OK:
        return {**base, "as_of": v.get("as_of"), "freshness": "UNAVAILABLE", "source": "postgres:release_queue",
                "reason": v.get("reason"), "store_state": v["store_state"], "total": None, "rows": None,
                "census": census_f}
    rows = []
    for r in v["rows"]:
        rows.append({**r, "title": (titles or {}).get(r["pr_number"]), "census_bucket": bucket_of.get(r["pr_number"])})
    return {**base, "as_of": v["as_of"], "freshness": "OK", "source": "postgres:release_queue", "reason": None,
            "store_state": Q.OK, "total": len(rows), "rows": rows, "census": census_f}


def _receipt_titles(census_path: Optional[Path]) -> dict[int, str]:
    p = Path(census_path) if census_path is not None else CEN.default_receipt_path()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    prs = ((doc or {}).get("summary") or {}).get("prs") or []
    return {int(x["number"]): str(x.get("title") or "")[:160] for x in prs
            if isinstance(x, Mapping) and isinstance(x.get("number"), int)}


def build_train(db_query, train_id: str, *, now: Optional[datetime] = None,
                timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[int, dict[str, Any]]:
    if not C.TRAIN_ID_RE.match(train_id or ""):
        raise BadRequest("bad_train_id", "train_id must match ^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$")
    now = now or _now()
    base = {"schema": "ReleaseTrainDetail@v1", "authority": AUTHORITY, "generated_at": _iso(now),
            "source": "postgres:release_queue_events"}
    res = run_probes({"train": lambda: Q.read_train(db_query, train_id, now=now)}, timeout_s)["train"]
    if res["status"] != "OK":
        return 200, {"ok": True, "data": {**base, "as_of": None, "freshness": "UNAVAILABLE", "reason": res["error"],
                                          "train": None}}
    v = res["value"]
    if v["store_state"] != Q.OK:
        return 200, {"ok": True, "data": {**base, "as_of": v.get("as_of"), "freshness": "UNAVAILABLE",
                                          "reason": v.get("reason"), "train": None}}
    if not v["found"]:
        return 404, {"ok": False, "error": "train_not_found", "detail": train_id}
    return 200, {"ok": True, "data": {**base, "as_of": v["as_of"], "freshness": "OK", "reason": None,
                                      "train": v["train"]}}


def build_events(db_query, query: Mapping[str, Any], *, now: Optional[datetime] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    limit = _int_param(query, "limit", 100, 1, 500, "bad_limit")
    after = _int_param(query, "after_seq", 0, 0, 2**62, "bad_after_seq")
    train_id = query.get("train_id") or None
    if train_id is not None and not C.TRAIN_ID_RE.match(str(train_id)):
        raise BadRequest("bad_train_id", "train_id must match ^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$")
    pr = _int_param(query, "pr", 0, 1, 9999999, "bad_pr") if query.get("pr") not in (None, "") else None
    now = now or _now()
    base = {"schema": "ReleaseTrainEvents@v1", "authority": AUTHORITY, "generated_at": _iso(now),
            "source": "postgres:release_queue_events"}
    res = run_probes({"events": lambda: Q.read_events(db_query, after_seq=after, limit=limit, train_id=train_id,
                                                      pr=pr)}, timeout_s)["events"]
    if res["status"] != "OK":
        return {**base, "as_of": None, "freshness": "UNAVAILABLE", "reason": res["error"], "events": None,
                "next_after_seq": None}
    v = res["value"]
    if v["store_state"] != Q.OK:
        return {**base, "as_of": v.get("as_of"), "freshness": "UNAVAILABLE", "reason": v.get("reason"),
                "events": None, "next_after_seq": None}
    return {**base, "as_of": v["as_of"], "freshness": "OK", "reason": None, "events": v["events"],
            "next_after_seq": v["next_after_seq"]}


def build_trains(db_query, query: Mapping[str, Any], *, now: Optional[datetime] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    limit = _int_param(query, "limit", 20, 1, 100, "bad_limit")
    before = (_int_param(query, "before_seq", 0, 1, 2**62, "bad_before_seq")
              if query.get("before_seq") not in (None, "") else None)
    now = now or _now()
    base = {"schema": "ReleaseTrainList@v1", "authority": AUTHORITY, "generated_at": _iso(now),
            "source": "postgres:release_queue_events"}
    res = run_probes({"trains": lambda: Q.read_trains(db_query, limit=limit, before_seq=before, now=now)},
                     timeout_s)["trains"]
    if res["status"] != "OK":
        return {**base, "as_of": None, "freshness": "UNAVAILABLE", "reason": res["error"], "trains": None,
                "next_before_seq": None}
    v = res["value"]
    if v["store_state"] != Q.OK:
        return {**base, "as_of": v.get("as_of"), "freshness": "UNAVAILABLE", "reason": v.get("reason"),
                "trains": None, "next_before_seq": None}
    return {**base, "as_of": v["as_of"], "freshness": "OK", "reason": None, "trains": v["trains"],
            "next_before_seq": v["next_before_seq"]}


# ── dispatch ──────────────────────────────────────────────────────────────────────────────────────────────────

OWNED = frozenset({ROUTE, ROUTE + "/queue", ROUTE + "/events", ROUTE + "/trains"})
_TRAIN_PATH = re.compile(r"^/api/v2/coordination/release-train/trains/([^/]+)/?$")


def handle(path: str, method: str, query: Optional[Mapping[str, Any]], db_query) -> Optional[tuple[int, dict]]:
    """(status, body) for one of this module's GET paths, else None.

    GET only, and only the five read paths: every non-GET under /release-train, and GET .../stop, belong to the STOP
    block in api_v2.handle (scripts/lib/release_train_stop.py, branch feat/release-train-cc-20261021). Returning None
    leaves them to it; this module never answers 405 for them. Cached 15 s per (path, query)."""
    base = path.split("?")[0].rstrip("/") or path
    if (method or "GET").upper() != "GET":
        return None
    if base not in OWNED and not _TRAIN_PATH.match(base):
        return None
    q = {k: (v[0] if isinstance(v, list) and v else v) for k, v in (query or {}).items()}
    key = (base, tuple(sorted((str(k), str(v)) for k, v in q.items())))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    try:
        if base == ROUTE:
            out = (200, {"ok": True, "data": build_summary(db_query)})
        elif base == ROUTE + "/queue":
            out = (200, {"ok": True, "data": build_queue(db_query, q)})
        elif base == ROUTE + "/events":
            out = (200, {"ok": True, "data": build_events(db_query, q)})
        elif base == ROUTE + "/trains":
            out = (200, {"ok": True, "data": build_trains(db_query, q)})
        elif _TRAIN_PATH.match(base):
            out = build_train(db_query, _TRAIN_PATH.match(base).group(1))
        else:  # pragma: no cover - guarded above
            return None
    except BadRequest as exc:
        return 400, {"ok": False, "error": exc.code, "detail": exc.detail}
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), out)
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
