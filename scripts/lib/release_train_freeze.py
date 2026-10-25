"""release_train_freeze.py — the Release Train v2 merge freeze, computed (AGENTS.md §25.3).

The rule: from ``starts_min_before_window`` (30) minutes before a scheduled window opens until that window's train
reaches a terminal state, nothing but the train merges to ``main``. The delegation declared it
(``merge_freeze: {starts_min_before_window: 30, ends: train_terminal, applies_to: all_non_train_merges_to_main}``);
this module is the code that says, at a given instant, whether the freeze is active and why. Contract and the
enforcement points: ``docs/ops/RELEASE_TRAIN_MERGE_FREEZE.md``.

Inputs:

* the schedule: ``config/release_train_policy.json`` ``windows[]`` (``local_time``, ``enabled``, ``days``) through
  ``release_train_window_view.policy_window`` — the same reader the request lane and the controller use, so the
  freeze can never disagree with the train about which windows exist. Only an ARMED policy schedules a freeze.
* the freeze settings: ``config/release_train_merge_freeze.json`` (the host also reads the delegation's
  ``merge_freeze.starts_min_before_window`` and uses the larger);
* the train's own records, host only: the window's on-window request
  (``<state>/train_requests/journal/rtw-<YYYYMMDD>-<HHMM>-win.json``), its receipt (``receipts/<id>.json``,
  ACKNOWLEDGED = running; COMPLETED / REFUSED / EXPIRED / FAILED = terminal, NO_OP included), and every live train
  state (``<state>/trains/<id>/state.json``; no ``outcome`` = in flight, forced canary runs included);
* GitHub, CI only: an open ``train/<id>`` batch PR into ``main``.

Two modes, one rule:

``host``  everything above. Used by the merge helpers and the Releases & schedules page.
``ci``    a GitHub runner cannot read the host's receipts, so it knows the pre-window freeze (pure time math) and
          an open batch PR, nothing else. After a window opens and before its batch PR exists it does not freeze.

Unreadable receipts (decision, see the doc §4): the 30-minute pre-window freeze always holds — it needs only the
clock and the policy. After the window opens, an unknown train state does NOT freeze (a visible warning instead):
a merge that lands under a running train is caught by the train itself (``MAIN_MOVED_AT_FREEZE`` is a quiet NO_OP,
``MAIN_MOVED_AT_MERGE`` is MERGED_NOT_LIVE + P1), which costs one window, whereas an open-ended freeze on an
unreadable file blocks every merge with no end and no owner. A policy that cannot be read is the exception: no layer
can then say "not frozen", so it reads as frozen (POLICY_UNREADABLE) and only the operator's label passes.

STOP: a SET latch means the operator stopped the train (§25.3: "unless the operator first stops the train"), so the
pre-window and awaiting-train freezes lift; a train already running (settling) still freezes until it is terminal.

Pure apart from the file reads in ``host_inputs`` / ``read_*``. Stdlib only, no environment read, no network,
nothing written. AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

try:
    from lib import release_train_window_view as V
    from lib.merge_freeze_context import FREEZE_CONTEXT
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_window_view as V  # type: ignore[no-redef]
    from scripts.lib.merge_freeze_context import FREEZE_CONTEXT  # type: ignore[no-redef]

SCHEMA = "TrainMergeFreeze@v1"
CONFIG_SCHEMA = "TrainMergeFreezeConfig@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "release_train_merge_freeze.json"
ET = ZoneInfo("America/New_York")
#: The capability library's TRAIN_RE, copied (pinned equal by the tests; that library is not imported here).
TRAIN_ID_RE = re.compile(r"^(?:train-\d{8}-\d{4}(?:-[a-z0-9]{1,12})?|rt-\d{8}-\d{4}-[a-z0-9]{4,12})$")
TRAIN_HEAD_PREFIX = "train/"
FORWARD_H = 48
DESCRIPTION_MAX = 140

#: Reason codes. Every one of them freezes.
PRE_WINDOW = "PRE_WINDOW"
WINDOW_TRAIN_RUNNING = "WINDOW_TRAIN_RUNNING"
WINDOW_TRAIN_PENDING = "WINDOW_TRAIN_PENDING"
AWAITING_REQUEST = "AWAITING_REQUEST"
TRAIN_IN_FLIGHT = "TRAIN_IN_FLIGHT"
BATCH_PR_OPEN = "BATCH_PR_OPEN"
POLICY_UNREADABLE = "POLICY_UNREADABLE"
REASONS = (PRE_WINDOW, WINDOW_TRAIN_RUNNING, WINDOW_TRAIN_PENDING, AWAITING_REQUEST, TRAIN_IN_FLIGHT, BATCH_PR_OPEN,
           POLICY_UNREADABLE)

DEFAULTS: dict[str, Any] = {
    "starts_min_before_window": 30,
    "base_branch": "main",
    "exempt_label": "freeze-exempt",
    "request_grace_min": 15,
    "ci_lead_min": 15,
    "stale_after_min": 240,
    "lookback_h": 24,
    "train_pr_authors": [],
}
_INT_BOUNDS = {"starts_min_before_window": (0, 120), "request_grace_min": (1, 60), "ci_lead_min": (0, 60),
               "stale_after_min": (30, 1440), "lookback_h": (6, 72)}


class FreezeConfigError(ValueError):
    """The freeze config is missing, unreadable or invalid."""


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────────


def validate_config(cfg: Any) -> list[str]:
    if not isinstance(cfg, Mapping):
        return ["config is not an object"]
    errs: list[str] = []
    if cfg.get("schema") != CONFIG_SCHEMA:
        errs.append(f"schema must be {CONFIG_SCHEMA}")
    if cfg.get("ends") != "train_terminal":
        errs.append("ends must be 'train_terminal'")
    if cfg.get("applies_to") != "all_non_train_merges_to_main":
        errs.append("applies_to must be 'all_non_train_merges_to_main'")
    for k, (lo, hi) in _INT_BOUNDS.items():
        v = cfg.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            errs.append(f"{k} must be an int in [{lo}, {hi}]")
    for k in ("base_branch", "exempt_label"):
        if not isinstance(cfg.get(k), str) or not cfg.get(k):
            errs.append(f"{k} must be a non-empty string")
    authors = cfg.get("train_pr_authors")
    if not isinstance(authors, list) or not all(isinstance(a, str) and a for a in authors):
        errs.append("train_pr_authors must be a list of logins")
    return errs


def load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path is not None else CONFIG_PATH
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FreezeConfigError(f"freeze config unreadable: {type(exc).__name__}") from exc
    errs = validate_config(cfg)
    if errs:
        raise FreezeConfigError("freeze config invalid: " + "; ".join(errs[:4]))
    return dict(cfg)


# ── schedule (pure) ───────────────────────────────────────────────────────────────────────────────────────────


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt is not None else None


def et_text(dt: Optional[datetime]) -> str:
    """``Sun 12:00 ET`` (the operator's clock)."""
    if dt is None:
        return "?"
    loc = dt.astimezone(ET)
    return f"{loc.strftime('%a')} {loc.strftime('%H:%M')} ET"


def occurrences(policy: Mapping[str, Any], now: datetime, *, back_h: int, fwd_h: int = FORWARD_H) -> list[dict]:
    """Every scheduled window start in ``[now - back_h, now + fwd_h]``, soonest first. Built as a wall-clock time in
    the policy timezone and compared in UTC (DST-safe: the freeze start is ``start - N minutes`` of real time, never
    wall-clock arithmetic). Only windows the policy enables on that local day count (``policy_window``)."""
    tz = ZoneInfo(str(policy.get("timezone") or "America/New_York"))
    n = _utc(now)
    lo, hi = n - timedelta(hours=back_h), n + timedelta(hours=fwd_h)
    local = n.astimezone(tz)
    out: dict[tuple, dict] = {}
    for w in policy.get("windows") or ():
        lt = str((w or {}).get("local_time") or "") if isinstance(w, Mapping) else ""
        m = re.fullmatch(r"([0-2][0-9]):([0-5][0-9])", lt)
        if not m:
            continue
        slot = m.group(1) + m.group(2)
        if slot not in V.SLOTS:
            continue
        for d in range(-(back_h // 24) - 2, fwd_h // 24 + 2):
            day = (local + timedelta(days=d)).date()
            start = datetime(day.year, day.month, day.day, int(m.group(1)), int(m.group(2)), tzinfo=tz)
            su = start.astimezone(timezone.utc)
            if not lo <= su <= hi:
                continue
            if not V.policy_window(policy, slot, V.DAYS[day.weekday()])["enabled"]:
                continue
            out[(su, slot)] = {"slot": slot, "start": start, "start_utc": su, "window_id": V.window_id(start),
                               "role": w.get("role")}
    return sorted(out.values(), key=lambda o: (o["start_utc"], o["slot"]))


def request_id(occ: Mapping[str, Any]) -> str:
    """The window's one on-window request id (``release_train_window_view.request_id_for``, tick on_window)."""
    return f"rtw-{occ['start'].strftime('%Y%m%d')}-{occ['slot']}-win"


# ── host records (read-only, never raise) ─────────────────────────────────────────────────────────────────────


def _read_json(p: Path) -> tuple[Optional[dict], Optional[str]]:
    """(doc, problem). Missing file = (None, None)."""
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, f"{p.name}: {type(exc).__name__}"
    return (doc, None) if isinstance(doc, dict) else (None, f"{p.name}: not an object")


def window_train_state(state_dir: Path, occ: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """The window's train as its request + receipt say. state: TERMINAL | RUNNING | PENDING | EXPIRED_NO_RECEIPT |
    NO_REQUEST | UNREADABLE."""
    rid = request_id(occ)
    base = Path(state_dir) / V.SPOOL_DIR
    rec, rprob = _read_json(base / V.RECEIPTS / f"{rid}.json")
    if rprob:
        return {"state": "UNREADABLE", "request_id": rid, "detail": rprob}
    if rec is not None:
        st = rec.get("state")
        if st in V.TERMINAL_RECEIPT_STATES:
            return {"state": "TERMINAL", "request_id": rid, "receipt_state": st,
                    "outcome": rec.get("outcome") or (rec.get("refusal") or {}).get("code"),
                    "finished_at": rec.get("finished_at"), "train_id": rec.get("train_id")}
        if st == "ACKNOWLEDGED":
            return {"state": "RUNNING", "request_id": rid, "acknowledged_at": rec.get("acknowledged_at"),
                    "shadow": rec.get("shadow"), "train_id": rec.get("train_id")}
        return {"state": "UNREADABLE", "request_id": rid, "detail": f"receipt state {st!r}"}
    req, qprob = _read_json(base / V.JOURNAL / f"{rid}.json")
    if qprob:
        return {"state": "UNREADABLE", "request_id": rid, "detail": qprob}
    if req is None:
        return {"state": "NO_REQUEST", "request_id": rid}
    exp = _parse(req.get("expires_at"))
    if exp is not None and _utc(now) >= exp:
        return {"state": "EXPIRED_NO_RECEIPT", "request_id": rid, "expires_at": req.get("expires_at")}
    return {"state": "PENDING", "request_id": rid, "expires_at": req.get("expires_at"), "shadow": req.get("shadow")}


def in_flight_trains(state_dir: Path) -> tuple[list[dict], Optional[str]]:
    """Live trains with no outcome yet (``<state>/trains/<id>/state.json``; only a live controller writes one). An
    unreadable state file is in flight (the controller's own ``pending_trains`` reads it the same way)."""
    tdir = Path(state_dir) / "trains"
    try:
        names = sorted(os.listdir(tdir))
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return [], f"trains/: {type(exc).__name__}"
    out = []
    for name in names:
        p = tdir / name / "state.json"
        if not p.exists():
            continue
        body, prob = _read_json(p)
        if prob or body is None:
            out.append({"train_id": name, "phase": "UNREADABLE", "window_id": None, "updated_at": None})
            continue
        if not body.get("outcome"):
            out.append({"train_id": body.get("train_id") or name, "phase": body.get("phase"),
                        "window_id": body.get("window_id"), "updated_at": body.get("updated_at")})
    return out, None


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def delegation_freeze_min(path: Optional[Path] = None) -> Optional[int]:
    """The standing delegation's ``merge_freeze.starts_min_before_window``, or None when it cannot be read."""
    doc, _p = _read_json(Path(path or V.DELEGATION_PATH))
    v = ((doc or {}).get("merge_freeze") or {}).get("starts_min_before_window") if doc else None
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 120 else None


# ── the verdict ───────────────────────────────────────────────────────────────────────────────────────────────


def evaluate(
    now: datetime,
    *,
    policy: Optional[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    mode: str,
    state_dir: Optional[Path] = None,
    stop_state: Optional[str] = None,
    delegation_min: Optional[int] = None,
    batch_prs: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """TrainMergeFreeze@v1 at ``now``. ``mode`` is ``host`` (reads ``state_dir``) or ``ci`` (reads nothing;
    ``batch_prs`` is the open ``train/<id>`` PRs it saw on GitHub). Never raises on bad records."""
    if mode not in ("host", "ci"):
        raise ValueError(f"unknown mode {mode!r}")
    n = _utc(now)
    minutes = int(cfg["starts_min_before_window"])
    if delegation_min is not None and delegation_min > minutes:
        minutes = delegation_min                       # more restrictive wins
    grace = timedelta(minutes=int(cfg["request_grace_min"]))
    stale = timedelta(minutes=int(cfg["stale_after_min"]))
    reasons: list[dict[str, Any]] = []
    warnings: list[str] = []
    stop_set = stop_state == "SET"

    receipts = "NOT_READ"
    if mode == "host":
        receipts = "OK" if state_dir is not None and Path(state_dir).is_dir() else "UNREADABLE"
        if receipts == "UNREADABLE":
            warnings.append(f"release-window state dir unreadable ({state_dir}): after a window opens its train "
                            "state is unknown, so only the pre-window freeze is enforced")

    armed = isinstance(policy, Mapping) and policy.get("armed") is True
    occ: list[dict] = []
    if policy is None:
        reasons.append({"code": POLICY_UNREADABLE, "detail": "config/release_train_policy.json unreadable: the "
                        "schedule is unknown, so the freeze cannot be ruled out"})
    elif armed:
        occ = occurrences(policy, n, back_h=int(cfg["lookback_h"]))

    for o in occ:
        start = o["start_utc"]
        frm = start - timedelta(minutes=minutes)
        base = {"window_id": o["window_id"], "slot": o["slot"], "starts_at": _iso(start), "freeze_from": _iso(frm)}
        if frm <= n < start:
            if stop_set:
                warnings.append(f"pre-window freeze for {et_text(start)} lifted: the release STOP latch is set")
                continue
            reasons.append({"code": PRE_WINDOW, **base, "ends_at_earliest": _iso(start),
                            "detail": f"{minutes} min before the {et_text(start)} window, until its train is terminal"})
            continue
        if n < start or receipts != "OK":
            continue
        ws = window_train_state(Path(state_dir), o, n)  # type: ignore[arg-type]
        st = ws["state"]
        if st == "RUNNING":
            r = {"code": WINDOW_TRAIN_RUNNING, **base, "request_id": ws["request_id"], "train_id": ws.get("train_id"),
                 "detail": f"the {et_text(start)} train is running (receipt ACKNOWLEDGED)"}
            if n - start >= stale:
                r["stale"] = True
                late = int((n - start).total_seconds() // 60)
                warnings.append(f"the {et_text(start)} train is still ACKNOWLEDGED {late} min after its window: "
                                "resolve it (train-orphan-resolve / reconcile) or STOP")
            reasons.append(r)
        elif st == "PENDING" and not stop_set:
            reasons.append({"code": WINDOW_TRAIN_PENDING, **base, "request_id": ws["request_id"],
                            "expires_at": ws.get("expires_at"),
                            "detail": f"the {et_text(start)} train is requested and not yet claimed"})
        elif st == "NO_REQUEST" and n < start + grace and not stop_set:
            reasons.append({"code": AWAITING_REQUEST, **base, "ends_at_latest": _iso(start + grace),
                            "detail": f"the {et_text(start)} window is open and its train request has not appeared"})
        elif st == "EXPIRED_NO_RECEIPT":
            if n - start < stale:
                warnings.append(f"the {et_text(start)} request expired unclaimed (no receipt): freeze ended at expiry")
        elif st == "UNREADABLE":
            warnings.append(f"the {et_text(start)} train record is unreadable ({ws.get('detail')}): not freezing "
                            "after the window opened")

    if mode == "host" and receipts == "OK":
        trains, terr = in_flight_trains(Path(state_dir))  # type: ignore[arg-type]
        if terr:
            warnings.append(f"train states unreadable ({terr})")
        for t in trains:
            r = {"code": TRAIN_IN_FLIGHT, "train_id": t["train_id"], "phase": t["phase"], "window_id": t["window_id"],
                 "detail": f"live train {t['train_id']} in phase {t['phase']} has no outcome yet"}
            upd = _parse(t.get("updated_at"))
            if upd is not None and n - upd >= stale:
                r["stale"] = True
                warnings.append(f"train {t['train_id']} has not moved since {et_text(upd)}: reconcile it or STOP")
            reasons.append(r)

    for pr in batch_prs or ():
        reasons.append({"code": BATCH_PR_OPEN, "pr": pr.get("number"), "head": pr.get("head"),
                        "detail": f"train batch PR #{pr.get('number')} ({pr.get('head')}) is open"})

    nxt = next((o for o in occ if o["start_utc"] - timedelta(minutes=minutes) > n), None)
    next_freeze = None
    if nxt is not None:
        frm = nxt["start_utc"] - timedelta(minutes=minutes)
        next_freeze = {"window_id": nxt["window_id"], "slot": nxt["slot"], "starts_at": _iso(nxt["start_utc"]),
                       "freeze_from": _iso(frm), "in_seconds": int((frm - n).total_seconds())}
    lead = timedelta(minutes=int(cfg["ci_lead_min"]))
    imminent = bool(next_freeze and timedelta(seconds=next_freeze["in_seconds"]) <= lead)
    out = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": _iso(n),
        "mode": mode,
        "frozen": bool(reasons),
        "reasons": reasons,
        "armed": armed if policy is not None else None,
        "starts_min_before_window": minutes,
        "receipts": receipts,
        "stop": stop_state,
        "next_freeze": next_freeze,
        "imminent": imminent,
        "warnings": warnings,
        "status_context": FREEZE_CONTEXT,
        "exempt_label": cfg["exempt_label"],
    }
    out["summary"] = summary(out)
    return out


def summary(v: Mapping[str, Any]) -> str:
    """One line for a refusal, a status description or the page."""
    rs = v.get("reasons") or []
    if not rs:
        nf = v.get("next_freeze")
        tail = ""
        if nf:
            tail = f"; next freeze {et_text(_parse(nf['freeze_from']))} (window {et_text(_parse(nf['starts_at']))})"
        return "No merge freeze" + tail
    r = rs[0]
    code = r["code"]
    if code == PRE_WINDOW:
        return (f"Merge freeze: {et_text(_parse(r['starts_at']))} release window; ends when its train is terminal "
                f"(no earlier than {et_text(_parse(r['ends_at_earliest']))})")
    if code in (WINDOW_TRAIN_RUNNING, WINDOW_TRAIN_PENDING):
        what = "running" if code == WINDOW_TRAIN_RUNNING else "requested"
        return f"Merge freeze: {et_text(_parse(r['starts_at']))} train {what}; ends when it is terminal"
    if code == AWAITING_REQUEST:
        return (f"Merge freeze: {et_text(_parse(r['starts_at']))} window open; ends when its train is terminal "
                f"(by {et_text(_parse(r['ends_at_latest']))} if no train starts)")
    if code == TRAIN_IN_FLIGHT:
        return f"Merge freeze: train {r.get('train_id')} in flight ({r.get('phase')}); ends when it is terminal"
    if code == BATCH_PR_OPEN:
        return f"Merge freeze: train batch PR #{r.get('pr')} open; ends when the train is terminal"
    return "Merge freeze: release policy unreadable; schedule unknown"


# ── a PR against the verdict ──────────────────────────────────────────────────────────────────────────────────


def is_train_batch_pr(pr: Mapping[str, Any], cfg: Mapping[str, Any]) -> bool:
    """The train's own batch PR: head ``train/<train id>`` in this repository (never a fork), base main, and — when
    ``train_pr_authors`` is configured — opened by one of those logins (the App's bot)."""
    head = str(pr.get("head") or "")
    if not head.startswith(TRAIN_HEAD_PREFIX) or not TRAIN_ID_RE.match(head[len(TRAIN_HEAD_PREFIX):]):
        return False
    if pr.get("cross_repo") is not False:
        return False
    if pr.get("base") != cfg["base_branch"]:
        return False
    authors = list(cfg.get("train_pr_authors") or [])
    return not authors or pr.get("author") in authors


def exemption(pr: Optional[Mapping[str, Any]], cfg: Mapping[str, Any]) -> Optional[str]:
    """Why ``pr`` may merge during a freeze, or None. ``not_main``: the freeze is about merges to main."""
    if not pr:
        return None
    if pr.get("base") and pr.get("base") != cfg["base_branch"]:
        return "not_main"
    if is_train_batch_pr(pr, cfg):
        return "train_batch_pr"
    if cfg["exempt_label"] in (pr.get("labels") or []):
        return "freeze_exempt_label"
    return None


_EXEMPT_TEXT = {"not_main": "base is not main", "train_batch_pr": "the release train's own batch PR",
                "freeze_exempt_label": "operator label freeze-exempt"}


def pr_decision(verdict: Mapping[str, Any], pr: Optional[Mapping[str, Any]], cfg: Mapping[str, Any], *,
                lead_pending: bool = False) -> dict[str, Any]:
    """{allowed, exempt, state (success|pending), description, message}. ``lead_pending`` (CI only): pending when a
    freeze starts within ``ci_lead_min`` (GitHub's schedule cannot be relied on to flip the status on time)."""
    ex = exemption(pr, cfg)
    frozen = bool(verdict.get("frozen"))
    if ex:
        desc = f"Exempt ({_EXEMPT_TEXT[ex]})" + ("; freeze active" if frozen else "")
        return {"allowed": True, "exempt": ex, "state": "success", "description": desc[:DESCRIPTION_MAX],
                "message": desc}
    if frozen:
        s = str(verdict.get("summary") or "Merge freeze active")
        msg = (f"REFUSED: {s}. Only the release train merges to main during a freeze (AGENTS.md §25.3). Wait for the "
               f"train to finish, or the operator labels the PR '{cfg['exempt_label']}' or stops the train.")
        return {"allowed": False, "exempt": None, "state": "pending", "description": s[:DESCRIPTION_MAX],
                "message": msg}
    if lead_pending and verdict.get("imminent"):
        nf = verdict.get("next_freeze") or {}
        s = (f"Merge freeze starts {et_text(_parse(nf.get('freeze_from')))} "
             f"({et_text(_parse(nf.get('starts_at')))} window)")
        return {"allowed": False, "exempt": None, "state": "pending", "description": s[:DESCRIPTION_MAX], "message": s}
    return {"allowed": True, "exempt": None, "state": "success",
            "description": str(verdict.get("summary") or "No merge freeze")[:DESCRIPTION_MAX], "message": "no freeze"}


# ── host convenience ──────────────────────────────────────────────────────────────────────────────────────────


def host_verdict(now: datetime, *, state_dir: Optional[Path], policy_path: Optional[Path] = None,
                 config_path: Optional[Path] = None, delegation_path: Optional[Path] = None) -> dict[str, Any]:
    """The host verdict from files. Never raises: a broken freeze config reads as the defaults (a warning), a broken
    policy as POLICY_UNREADABLE, an unreadable latch as not SET (keeps the freeze)."""
    warn = []
    try:
        cfg = load_config(config_path)
    except FreezeConfigError as exc:
        cfg = dict(DEFAULTS)
        warn.append(f"{exc}; using defaults")
    policy = V.read_policy(policy_path)
    stop = None
    if state_dir is not None:
        try:
            stop = V.read_latch(Path(state_dir))
        except Exception:  # noqa: BLE001 - unknown latch: not SET, so nothing lifts
            stop = "UNREADABLE"
    v = evaluate(now, policy=policy, cfg=cfg, mode="host", state_dir=state_dir, stop_state=stop,
                 delegation_min=delegation_freeze_min(delegation_path))
    v["warnings"] = warn + v["warnings"]
    return v
