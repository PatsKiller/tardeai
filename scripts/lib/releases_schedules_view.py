"""Releases & Schedules — read-only Command Center projection (operator-approved 2026-10-22).

Backs ``GET /api/v2/ops/releases-schedules`` (the System → Releases & schedules page). Contract:
``docs/ops/RELEASES_SCHEDULES_PAGE.md``. One response, nine sections, each a Field envelope
(``value``, ``as_of``, ``freshness`` OK|STALE|UNAVAILABLE, ``source``, ``reason``, ``age_s``):

  serving        CURRENT symlink + its BUILD_SHA pins (exact_release_receipt.observed_identity), the
                 ACTIVE_RELEASE / EXPECTED_RELEASE pin files and the last deploy receipt.
  next_release   main HEAD as the canonical checkout last fetched it (local ref, no network), the
                 first-parent PRs since the served SHA, and exact-SHA CI from the main-ci-watch receipt
                 (scripts/main_ci_watch.py: SUCCESS | FAILURE | PENDING with its age), else from
                 post_merge_ci.json, each only when it names the same SHA. GitHub is never called from the
                 request path.
  windows        the release-train windows (release_train_view.upcoming_windows) with the host gate's
                 state and reason (release_train_window.readiness_view + decide).
  queue          the release-train queue store and the PR-hygiene census (release_train_view.build_queue). When
                 the census is not OK, ``census.alert`` says so loudly: why, the lane's last ledger attempt
                 (any mode) and its next scheduled fire, so "0 queued" is never read as "nothing is waiting".
  history        release pin receipts (apply / rollback) + the deploy receipt, PRs per release from git.
  release_errors refused / stopped release-window receipts, rollbacks, a failed deploy receipt, the STOP
                 latch, non-success checks in post_merge_ci.json, and FAILURE workflows in the main-ci-watch
                 receipt. CI on main beyond those: not covered (said so in the response).
  n8n_today      the n8n coordination ledger (SQLite, mode=ro): runs by mode/state today (America/New_York,
                 by requested_at), failures, lock skips, unreleased dead letters, busiest lanes.
  timeline       the next 3 hours of host cron (``crontab -l`` or its fresh snapshot, including
                 ``# PAUSED <date> <note> <line>`` lines) and n8n lanes (config/lane_registry.json schedules,
                 stage, relay live list names only), merged and sorted.
  kpis           derived from the above; a KPI over an UNAVAILABLE section is null, never 0 or green.

Pattern: scripts/lib/release_train_view.py. Every source is read off the request thread in a worker with its
own deadline; a source that misses it or fails is UNAVAILABLE with a reason. Cached 30 s.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Nothing here writes, merges, releases, arms, sends or calls a
broker. The only subprocesses are ``git`` (rev-parse / log on the local canonical checkout) and ``crontab -l``.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

try:
    from lib import release_train_view as RTV
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_view as RTV  # type: ignore[no-redef]

SCHEMA = "ReleasesSchedules@v1"
ROUTE = "/api/v2/ops/releases-schedules"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_TIMEOUT_S = 4.0
CACHE_TTL_S = 30.0
HORIZON_H = 3
MAX_TIMELINE = 150
MAX_HISTORY = 12
MAX_ERRORS = 50
COLLAPSE_AFTER = 4  # a schedule firing more often than this in the horizon becomes one "every N min" row
FETCH_STALE_AFTER_S = 6 * 3600
MAIN_CI_STALE_AFTER_S = 2 * 3600
CENSUS_LANE = "pr-hygiene-audit"
ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ERROR_RUN_STATES = ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED")
OK_WINDOW_OUTCOMES = ("RELEASED", "NO_CHANGE")
PAUSED_RE = re.compile(r"^\s*#\s*PAUSED\s+(\d{4}-\d{2}-\d{2})\s*(.*)$")
CRON5_RE = re.compile(r"(?:^|\s)((?:@\w+)|(?:[\d*/,\-a-zA-Z]+\s+){4}[\d*/,\-a-zA-Z]+)\s+(\S.*)$")
BUCKET_WHY = {
    "train_internal": "the train's own branch",
    "queued": "in the release queue",
    "draft": "draft",
    "held": "held (a hold label or marker)",
    "stacked": "stacked on another branch, not main",
    "conflicting": "merge conflict with main",
    "mergeability_unknown": "GitHub has not computed mergeability",
    "checks_failing": "required checks failing",
    "checks_pending": "required checks still running",
    "checks_unknown": "required checks unknown",
    "unqueued_clean": "clean but not queued",
}

_EXECUTOR: Optional[cf.ThreadPoolExecutor] = None
_EXECUTOR_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _executor() -> cf.ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = cf.ThreadPoolExecutor(max_workers=10, thread_name_prefix="releases-schedules")
        return _EXECUTOR


# ── envelopes and small helpers ───────────────────────────────────────────────────────────────────────────────


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def field(value: Any, as_of: Optional[str], freshness: str, source: str, reason: Optional[str] = None,
          *, now: Optional[datetime] = None) -> dict[str, Any]:
    """release_train_view.field plus ``age_s`` (seconds since ``as_of`` at ``now``; null when unknown)."""
    out = RTV.field(value, as_of, freshness, source, reason)
    ts = _parse(as_of)
    out["age_s"] = max(0, int((now - ts).total_seconds())) if (ts and now) else None
    return out


def _unavailable(source: str, reason: str, now: datetime) -> dict[str, Any]:
    return field(None, None, "UNAVAILABLE", source, reason, now=now)


def _read_json(path: Path, limit: int = 512 * 1024) -> Optional[dict]:
    try:
        with Path(path).open("rb") as fh:
            raw = fh.read(limit + 1)
        if len(raw) > limit:
            return None
        doc = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _read_text(path: Path, limit: int = 4096) -> Optional[str]:
    try:
        with Path(path).open("rb") as fh:
            return fh.read(limit).decode("utf-8", "replace").strip()
    except OSError:
        return None


def default_paths(env: Optional[Mapping[str, str]] = None) -> dict[str, Path]:
    """Every host path this view reads, resolved as its writer resolves it (same env names, same defaults)."""
    env = os.environ if env is None else env
    state_root = Path(env.get("TRADEAI_STATE_ROOT") or HOME / "trade-ai-releases" / "persistent-state")
    return {
        # scripts/cio_phase2_exact_main_deploy.sh RELEASES_BASE / STATE_DIR / CANONICAL_SOURCE
        "releases_base": Path(env.get("TRADEAI_RELEASES_BASE") or HOME / "trade-ai-releases" / "portfolio-server"),
        "deploy_state_dir": HOME / ".local" / "state" / "cio-phase2-exact-main",
        "canonical_source": Path(env.get("CANONICAL_SOURCE") or HOME / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"),
        # scripts/release_window.py STATE_DIR
        "release_window_state_dir": Path(env.get("TRADEAI_RELEASE_WINDOW_STATE_DIR")
                                         or state_root / "data" / "runtime" / "release_window"),
        # scripts/lib/n8n_coordination_projection.ledger_path
        "ledger": Path(env.get("TRADEAI_N8N_COORDINATION_LEDGER")
                       or state_root / "data" / "governance" / "n8n_coordination_ledger.sqlite"),
        # scripts/check_registry_runtime_truth.DEFAULT_LIVE_LANES_ENV (names only are read)
        "live_lanes_env": HOME / ".config" / "tradeai" / "n8n-live-lanes.env",
        "registry": ROOT / "config" / "lane_registry.json",
        # scripts/main_ci_watch.py (lib/lane_last_receipt.receipt_path("main-ci-watch"))
        "main_ci_receipt": state_root / "data" / "runtime" / "main-ci-watch_last.json",
    }


def git_runner(canonical: Path) -> Callable[[list[str]], tuple[int, str]]:
    """Local, read-only git on the canonical checkout (rev-parse / log only; no fetch, no network)."""
    def run(args: list[str]) -> tuple[int, str]:
        if not args or args[0] not in ("rev-parse", "log"):
            raise ValueError("git subcommand not allowed here")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        p = subprocess.run(["git", "-C", str(canonical), *args], capture_output=True, text=True, timeout=3,
                           check=False, env=env)
        return p.returncode, p.stdout
    return run


def prs_from_subjects(subjects: Iterable[str]) -> list[int]:
    """PR numbers from first-parent commit subjects: release_window.prs_from_messages (the deploy's own parser)."""
    try:
        try:
            from release_window import prs_from_messages  # type: ignore
        except ImportError:
            from scripts.release_window import prs_from_messages  # type: ignore[no-redef]
    except Exception:  # noqa: BLE001 - same two patterns, kept identical
        def prs_from_messages(messages: list[str]) -> list[int]:
            seen: list[int] = []
            for msg in messages:
                first = (msg or "").splitlines()[0] if msg else ""
                m = re.match(r"^Merge pull request #(\d+)\b", first) or re.search(r"\(#(\d+)\)\s*$", first)
                if m and int(m.group(1)) not in seen:
                    seen.append(int(m.group(1)))
            return seen
    return prs_from_messages(list(subjects))


def _first_parent_subjects(git: Callable[[list[str]], tuple[int, str]], base: str, head: str,
                           limit: int = 300) -> Optional[list[str]]:
    rc, out = git(["log", "--first-parent", f"--max-count={limit}", "--format=%s", f"{base}..{head}"])
    if rc != 0:
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


# ── release side ──────────────────────────────────────────────────────────────────────────────────────────────


def _observed_identity(releases_base: Path) -> dict[str, Any]:
    try:
        from lib import exact_release_receipt as ERR
    except ImportError:  # pragma: no cover
        from scripts.lib import exact_release_receipt as ERR  # type: ignore[no-redef]
    return ERR.observed_identity(releases_base)


def read_serving(releases_base: Path, deploy_state_dir: Path, now: datetime) -> dict[str, Any]:
    src = "CURRENT symlink + BUILD_SHA pins (exact_release_receipt.observed_identity)"
    ident = _observed_identity(releases_base)
    if ident.get("availability") != "AVAILABLE":
        return _unavailable(src, ident.get("reason") or "current_unavailable", now)
    current = Path(releases_base) / "CURRENT"
    release_dir = ident.get("release_dir")
    pins = {}
    for name in ("ACTIVE_RELEASE", "EXPECTED_RELEASE"):
        text = _read_text(Path(releases_base) / name, 1024)
        pins[name] = {"value": text, "matches_current": (text == release_dir) if text is not None else None}
    receipt = _read_json(Path(deploy_state_dir) / "deploy_receipt.json")
    since, since_basis, deploy = None, None, None
    if receipt:
        deploy = {k: receipt.get(k) for k in ("ok", "mode", "health", "at", "deployed_sha", "rolled_back",
                                               "readback_errors", "prev_release", "extra", "source_pr")}
        if receipt.get("deployed_sha") == ident.get("sha") and receipt.get("mode") in ("promote", "rollback"):
            since, since_basis = receipt.get("at"), "deploy_receipt.at"
    if since is None:
        try:
            since = datetime.fromtimestamp(current.lstat().st_mtime, timezone.utc).isoformat()
            since_basis = "CURRENT symlink mtime"
        except OSError:
            since_basis = None
    value = {"sha": ident["sha"], "short_sha": ident["sha"][:9], "release_dir": release_dir,
             "release_name": Path(release_dir).name if release_dir else None, "source_pr": ident.get("source_pr"),
             "since": since, "since_basis": since_basis, "pins": pins,
             "pins_agree": all(p["matches_current"] is True for p in pins.values()),
             "deploy_receipt": deploy, "deploy_receipt_path": str(Path(deploy_state_dir) / "deploy_receipt.json")}
    reason = None if value["pins_agree"] else "ACTIVE_RELEASE / EXPECTED_RELEASE do not both name CURRENT"
    return field(value, _iso(now), "OK" if value["pins_agree"] else "STALE", src, reason, now=now)


def _ci_summary(ci: Mapping[str, Any]) -> dict[str, Any]:
    checks = [c for c in (ci.get("checks") or []) if isinstance(c, Mapping)]
    concl = [str(c.get("conclusion") or c.get("status") or "unknown") for c in checks]
    bad = [{"name": c.get("name"), "status": c.get("status"), "conclusion": c.get("conclusion"),
            "url": c.get("html_url"), "updated_at": c.get("updated_at")}
           for c in checks if c.get("conclusion") != "success"]
    latest = max((str(c.get("updated_at") or "") for c in checks), default="") or None
    return {"ok": ci.get("ok"), "candidate_sha": ci.get("candidate_sha"), "checks": len(checks),
            "success": concl.count("success"), "not_success": bad, "latest_check_at": latest}


def main_ci_from_receipt(path: Optional[Path], head: str, now: datetime) -> tuple[Optional[dict[str, Any]], str]:
    """(ci, why_not): the main-ci-watch receipt's verdict for exactly ``head``, else None and a reason."""
    if path is None:
        return None, "no main-ci-watch receipt path"
    doc = _read_json(Path(path))
    if doc is None:
        return None, ("no main-ci-watch receipt (scripts/main_ci_watch.py has not run; lane proposed in "
                      "docs/ops/proposals/main-ci-watch-lane-20261022)" if not Path(path).exists()
                      else "main-ci-watch receipt unreadable")
    s = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    at = s.get("checked_at") or doc.get("finished_at")
    ts = _parse(at)
    age = max(0, int((now - ts).total_seconds())) if ts else None
    age_txt = f"{age // 60} min old" if age is not None else "age unknown"
    if str(doc.get("status")) != "ok":
        return None, (f"main-ci-watch last run failed at {doc.get('finished_at') or '?'}: "
                      f"{str(doc.get('error') or '')[:120]}")
    if s.get("head_sha") != head:
        return None, (f"main-ci-watch receipt ({age_txt}) names {str(s.get('head_sha'))[:9]}, "
                      f"not main HEAD {head[:9]}")
    state = s.get("state") if s.get("state") in ("SUCCESS", "FAILURE", "PENDING") else "UNAVAILABLE"
    stale = age is None or age > MAIN_CI_STALE_AFTER_S
    reason = None
    if stale and state == "PENDING":
        reason = f"PENDING as of {age_txt}; re-run scripts/main_ci_watch.py for the current state"
    elif stale:
        reason = f"checked {age_txt}"
    return {"state": state, "source": "receipt:main-ci-watch", "reason": reason, "checked_at": at, "age_s": age,
            "stale": stale, "counts": s.get("counts"), "workflows": s.get("workflows"),
            "candidate_sha": head}, ""


def read_next_release(canonical: Path, deploy_state_dir: Path, serving_sha: Optional[str], now: datetime,
                      git: Optional[Callable[[list[str]], tuple[int, str]]] = None,
                      main_ci_receipt: Optional[Path] = None) -> dict[str, Any]:
    src = "git:canonical refs/remotes/origin/main (local ref as last fetched; no network)"
    git = git or git_runner(canonical)
    rc, out = git(["rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"])
    head = out.strip()
    if rc != 0 or not SHA_RE.match(head):
        return _unavailable(src, "origin/main ref unreadable in the canonical checkout", now)
    rc, out = git(["log", "-1", "--format=%cI%x1f%s", head])
    committed_at, subject = (out.strip().split("\x1f", 1) + [None])[:2] if rc == 0 and out.strip() else (None, None)
    fetched_at = _mtime_iso(Path(canonical) / ".git" / "FETCH_HEAD")
    prs, ahead, pr_reason = None, None, None
    if serving_sha and SHA_RE.match(serving_sha):
        if serving_sha == head:
            prs, ahead = [], 0
        else:
            subjects = _first_parent_subjects(git, serving_sha, head)
            if subjects is None:
                pr_reason = "git log serving..main failed (serving SHA not in the canonical checkout?)"
            else:
                prs, ahead = prs_from_subjects(subjects), len(subjects)
    else:
        pr_reason = "serving SHA unavailable"
    ci_doc = _read_json(Path(deploy_state_dir) / "post_merge_ci.json")
    watched, why_not = main_ci_from_receipt(main_ci_receipt, head, now)
    if watched is not None:
        ci = watched
    elif ci_doc and ci_doc.get("candidate_sha") == head:
        ci = {"state": "OK" if ci_doc.get("ok") else "NOT_GREEN", "source": "post_merge_ci.json", "reason": None,
              **_ci_summary(ci_doc)}
    else:
        ci = {"state": "UNAVAILABLE", "source": "receipt:main-ci-watch + post_merge_ci.json",
              "reason": why_not + "; " + ("post_merge_ci.json names " + str(ci_doc.get("candidate_sha"))[:9]
                                          + ", not main HEAD" if ci_doc else "no post_merge_ci.json receipt")
              + "; GitHub is not called from this page"}
    value = {"sha": head, "short_sha": head[:9], "subject": subject, "committed_at": committed_at,
             "fetched_at": fetched_at, "is_serving": head == serving_sha, "commits_ahead": ahead,
             "prs_since_serving": prs, "prs_reason": pr_reason, "ci": ci}
    as_of = fetched_at or _iso(now)
    fetched = _parse(fetched_at)
    stale = fetched is None or (now - fetched).total_seconds() > FETCH_STALE_AFTER_S
    return field(value, as_of, "STALE" if stale else "OK", src,
                 ("canonical checkout last fetched " + (fetched_at or "never") + "; main may have moved since")
                 if stale else None, now=now)


def _release_sha(releases_base: Path, target: Optional[str]) -> tuple[Optional[str], str]:
    if not target:
        return None, "none"
    pin = _read_text(Path(target) / "BUILD_SHA", 128)
    if pin and SHA_RE.match(pin):
        return pin, "BUILD_SHA"
    m = re.match(r"^([0-9a-f]{7,40})-", Path(target).name)
    return (m.group(1), "dir_name_prefix") if m else (None, "none")


def read_history(releases_base: Path, deploy_state_dir: Path, now: datetime,
                 git: Optional[Callable[[list[str]], tuple[int, str]]] = None,
                 limit: int = MAX_HISTORY) -> dict[str, Any]:
    pins_dir = Path(deploy_state_dir) / "release_pins"
    src = "release_pins/{apply,rollback}-*.json (ReleasePinReceipt@v1) + deploy_receipt.json"
    try:
        names = sorted((n for n in os.listdir(pins_dir) if re.match(r"^(apply|rollback)-\d{8}T\d+Z\.json$", n)),
                       key=lambda n: n.split("-", 1)[1], reverse=True)
    except OSError as exc:
        return _unavailable(src, f"release_pins unreadable: {type(exc).__name__}", now)
    receipt = _read_json(Path(deploy_state_dir) / "deploy_receipt.json") or {}
    serving = _observed_identity(releases_base)
    rows = []
    for name in names[: limit + 1]:
        doc = _read_json(pins_dir / name)
        if not doc:
            rows.append({"receipt": name, "mode": name.split("-", 1)[0], "at": None, "sha": None,
                         "sha_basis": "none", "error": "receipt unreadable"})
            continue
        sha, basis = _release_sha(releases_base, doc.get("target_release"))
        row = {"receipt": name, "mode": doc.get("mode"), "at": doc.get("at"), "sha": sha, "sha_basis": basis,
               "short_sha": sha[:9] if sha else None,
               "release_name": Path(str(doc.get("target_release"))).name if doc.get("target_release") else None,
               "from_release": Path(str(doc.get("from_release"))).name if doc.get("from_release") else None,
               "serving": bool(sha and serving.get("sha") and serving["sha"].startswith(sha)),
               "prs": None, "prs_reason": None, "verify": None,
               "verify_reason": "not retained: deploy_receipt.json holds only the latest operation"}
        if sha and receipt.get("deployed_sha") and str(receipt["deployed_sha"]).startswith(sha):
            row["verify"] = {k: receipt.get(k) for k in ("ok", "mode", "health", "rolled_back", "readback_errors", "at")}
            row["verify_reason"] = None
        rows.append(row)
    for newer, older in zip(rows, rows[1:]):
        if newer.get("mode") != "apply":
            newer["prs_reason"] = "rollback: no new PRs"
            continue
        a, b = older.get("sha"), newer.get("sha")
        if not (a and b and SHA_RE.match(a) and SHA_RE.match(b)):
            newer["prs_reason"] = "full SHAs unavailable for this release pair"
            continue
        if git is None:
            newer["prs_reason"] = "git unavailable"
            continue
        subjects = _first_parent_subjects(git, a, b)
        if subjects is None:
            newer["prs_reason"] = "git log failed for this release pair"
        else:
            newer["prs"] = prs_from_subjects(subjects)
    rows = rows[:limit]
    if rows and rows[-1]["prs"] is None and rows[-1]["prs_reason"] is None:
        rows[-1]["prs_reason"] = "previous release outside the listed history"
    newest = rows[0]["at"] if rows else None
    return field({"releases": rows, "receipts_total": len(names)}, newest or _iso(now), "OK", src,
                 None if rows else "no release pin receipts", now=now)


def read_release_errors(deploy_state_dir: Path, rw_state_dir: Path, now: datetime,
                        stop: Optional[Mapping[str, Any]] = None, hours: int = 48,
                        main_ci_receipt: Optional[Path] = None) -> dict[str, Any]:
    """Each row: {at, kind, detail, source}. Sources this can see; anything else is listed as not covered."""
    src = "release_window/windows/*.json + release_pins/rollback-*.json + deploy_receipt.json + post_merge_ci.json"
    since = now - timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    read_any = False
    wdir = Path(rw_state_dir) / "windows"
    try:
        for name in sorted(os.listdir(wdir))[-200:]:
            if not name.endswith(".json"):
                continue
            read_any = True
            doc = _read_json(wdir / name) or {}
            outcome = str(doc.get("outcome") or "")
            at = _parse(doc.get("finished_at") or doc.get("started_at"))
            if outcome and outcome not in OK_WINDOW_OUTCOMES and (at is None or at >= since):
                rows.append({"at": _iso(at), "kind": "window " + outcome.lower(),
                             "detail": str(doc.get("detail") or doc.get("reason") or doc.get("window_id") or "")[:240],
                             "source": f"release_window/windows/{name}"})
    except FileNotFoundError:
        read_any = True  # no window has ever written a receipt: nothing refused there
    except OSError:
        pass
    pins_dir = Path(deploy_state_dir) / "release_pins"
    try:
        for name in sorted(os.listdir(pins_dir)):
            read_any = True
            if not name.startswith("rollback-"):
                continue
            doc = _read_json(pins_dir / name) or {}
            at = _parse(doc.get("at"))
            if at and at >= since:
                rows.append({"at": _iso(at), "kind": "rollback",
                             "detail": "rolled back to " + Path(str(doc.get("target_release") or "?")).name
                             + " from " + Path(str(doc.get("from_release") or "?")).name,
                             "source": f"release_pins/{name}"})
    except OSError:
        pass
    receipt = _read_json(Path(deploy_state_dir) / "deploy_receipt.json")
    if receipt:
        read_any = True
        at = _parse(receipt.get("at"))
        if (receipt.get("ok") is False or receipt.get("readback_errors") or receipt.get("rolled_back")) and \
                (at is None or at >= since):
            rows.append({"at": _iso(at), "kind": f"deploy {receipt.get('mode')} not ok",
                         "detail": "; ".join(map(str, receipt.get("readback_errors") or []))
                         or str(receipt.get("extra") or receipt.get("health") or "")[:240],
                         "source": "deploy_receipt.json"})
        ci = _read_json(Path(deploy_state_dir) / "post_merge_ci.json")
        if ci:
            for c in _ci_summary(ci)["not_success"]:
                rows.append({"at": c.get("updated_at"), "kind": "main CI " + str(c.get("conclusion") or c.get("status")),
                             "detail": f"{c.get('name')} on {str(ci.get('candidate_sha'))[:9]}",
                             "source": "post_merge_ci.json", "url": c.get("url")})
    watch = _read_json(Path(main_ci_receipt)) if main_ci_receipt is not None else None
    ws = (watch or {}).get("summary") if isinstance((watch or {}).get("summary"), dict) else {}
    if watch and str(watch.get("status")) == "ok" and ws.get("state") == "FAILURE":
        read_any = True
        for w in ws.get("workflows") or []:
            if isinstance(w, Mapping) and w.get("state") == "FAILURE":
                rows.append({"at": w.get("updated_at") or ws.get("checked_at"),
                             "kind": "main CI " + str(w.get("conclusion") or "failure"),
                             "detail": f"{w.get('name')} on main {str(ws.get('head_sha'))[:9]}",
                             "source": "receipt:main-ci-watch", "url": w.get("url")})
    if stop and stop.get("effective_stop"):
        rows.append({"at": stop.get("latched_at"), "kind": f"release STOP {stop.get('state')}",
                     "detail": str(stop.get("latch_reason") or "")[:240], "source": "release_window/STOP.json"})
    if not read_any:
        return _unavailable(src, "no release error source readable", now)
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    not_covered = ("main CI failures of SHAs other than the one the main-ci-watch receipt last checked "
                   "(GitHub is not called from this page)")
    return field({"rows": rows[:MAX_ERRORS], "window_hours": hours, "not_covered": not_covered},
                 _iso(now), "OK", src, None, now=now)


def _window_state(snapshot: Mapping[str, Any]) -> tuple[str, Optional[str]]:
    try:
        from lib import release_train_window as RTW
    except ImportError:  # pragma: no cover
        from scripts.lib import release_train_window as RTW  # type: ignore[no-redef]
    d = RTW.decide(snapshot, "on_window", shadow_only=False)
    if d["disposition"] == "no_op":
        if d["no_op_reason"] in ("stop_set", "stop_unreadable"):
            return "STOPPED", "release STOP latch " + ("set" if d["no_op_reason"] == "stop_set" else "unreadable")
        return "OFF", "train not armed and shadow disabled"
    if d["shadow"]:
        why = {"train_not_armed": "train not armed (simulate only)",
               "delegation_not_active": f"delegation {snapshot.get('delegation_state')} (simulate only)",
               "window_not_enabled": "window not enabled in the policy (simulate only)"}
        return "SHADOW", why.get(d["shadow_reason"], str(d["shadow_reason"]))
    return "LIVE", None


def read_windows(now: datetime, *, rw_state_dir: Path, summary: Optional[Mapping[str, Any]] = None,
                 readiness: Optional[Callable[[], Mapping[str, Any]]] = None) -> dict[str, Any]:
    src = "config/release_train_policy.json + release_train_window.readiness_view (STOP, delegation, shadow)"
    policy, perr = RTV._load_policy()
    if policy is None:
        return _unavailable(src, perr or "policy_unreadable", now)
    if readiness is None:
        try:
            from lib import release_train_window as RTW
        except ImportError:  # pragma: no cover
            from scripts.lib import release_train_window as RTW  # type: ignore[no-redef]
        rd = RTW.readiness_view(now, stop_dir=rw_state_dir)
    else:
        rd = readiness()
    if not isinstance(rd, Mapping) or rd.get("state") != "OK":
        return _unavailable(src, "readiness " + str((rd or {}).get("reason") or "unavailable"), now)
    stop = rd.get("stop") or {}
    deleg = (rd.get("delegation") or {}).get("state")
    coverage = {c.get("slot"): c for c in rd.get("shadow_coverage") or [] if isinstance(c, Mapping)}
    out = []
    for w in RTV.upcoming_windows(policy, now):
        slot = str(w["local_time"]).replace(":", "")
        snap = {"stop_state": stop.get("state"), "armed": rd.get("armed") is True,
                "shadow_enabled": rd.get("shadow_enabled") is True, "delegation_state": deleg,
                "window_enabled": bool(w.get("enabled"))}
        state, reason = _window_state(snap)
        cov = coverage.get(slot) or {}
        out.append({**w, "slot": slot, "state": state, "reason": reason,
                    "last_shadow_request_at": cov.get("last_requested_at"),
                    "last_shadow_receipt_state": cov.get("receipt_state"),
                    "last_shadow": {k: cov.get(k) for k in ("request_id", "outcome", "reason", "queue_open",
                                                            "queue_complete", "riding", "candidate_sha", "train_id",
                                                            "has_report")} if cov.get("request_id") else None})
    value = {"windows": out, "armed": rd.get("armed"), "shadow_enabled": rd.get("shadow_enabled"),
             "delegation": rd.get("delegation"), "stop": stop, "policy_version": rd.get("policy_version"),
             "manual_path": "Until the train is armed, releases are manual: scripts/release_window.py 12:00 / 17:30 "
                            "ET windows under a release-write grant naming the SHA (AGENTS.md §25.1, §24.8)."}
    return field(value, rd.get("as_of") or _iso(now), "OK", src, None, now=now)


def census_attempt(ledger: Optional[Path], registry: Optional[Path], now: datetime) -> dict[str, Any]:
    """The census lane's last ledger attempt (any mode, any day) and its next scheduled fire. Read-only; every
    failure is a reason string, never an exception."""
    out: dict[str, Any] = {"lane_id": CENSUS_LANE, "last_attempt": None, "last_attempt_reason": None,
                           "last_live_attempt": None, "dispatch_mode": None, "stage": None, "next_fire_at": None}
    if ledger is not None:
        try:
            conn = _connect_ro(Path(ledger))
            try:
                rows = conn.execute("SELECT run_id, mode, state, requested_at, finished_at, exit_code FROM runs "
                                    "WHERE lane_id = ? ORDER BY requested_at DESC LIMIT 20", (CENSUS_LANE,)).fetchall()
            finally:
                conn.close()
            def row(r):
                return {"run_id": r[0], "mode": r[1], "state": r[2], "requested_at": r[3], "finished_at": r[4],
                        "exit_code": r[5]}
            out["last_attempt"] = row(rows[0]) if rows else None
            out["last_live_attempt"] = next((row(r) for r in rows if r[1] == "live"), None)
            if not rows:
                out["last_attempt_reason"] = "no run of this lane in the coordination ledger"
        except (OSError, sqlite3.Error) as exc:
            out["last_attempt_reason"] = f"ledger unreadable: {type(exc).__name__}"
    if registry is not None:
        try:
            reg = json.loads(Path(registry).read_text(encoding="utf-8"))
            lane = next((r for r in reg.get("lanes") or [] if isinstance(r, dict) and r.get("lane_id") == CENSUS_LANE),
                        None)
        except (OSError, ValueError):
            lane = None
        if lane:
            d = lane.get("dispatch") if isinstance(lane.get("dispatch"), dict) else {}
            out["dispatch_mode"] = d.get("mode")
            out["stage"] = (lane.get("scheduler") or {}).get("stage")
            fires = []
            for expr in d.get("cron") or []:
                f = _fires(str(expr), now, now + timedelta(hours=48), tz=str(d.get("tz") or "America/New_York"))
                fires.extend(f or [])
            out["next_fire_at"] = _iso(min(fires)) if fires else None
    return out


def _et_text(ts: Any) -> str:
    d = _parse(ts)
    return d.astimezone(ET).strftime("%m/%d %H:%M ET") if d else str(ts or "?")


def census_alert(census: Mapping[str, Any], attempt: Mapping[str, Any]) -> Optional[str]:
    """One loud sentence when the census is not OK; None when it is."""
    if census.get("freshness") == "OK":
        return None
    why = {"no_receipt": "pr-hygiene-audit has never written a receipt",
           "last_run_failed": "pr-hygiene-audit's last run failed",
           "receipt_unreadable": "the pr-hygiene-audit receipt is unreadable"}.get(
        str(census.get("reason")), f"census {census.get('freshness') or 'UNAVAILABLE'}: {census.get('reason')}")
    la = attempt.get("last_attempt")
    if la:
        last = f"last attempt {_et_text(la.get('requested_at'))} {la.get('mode')} {la.get('state')}"
        if la.get("mode") == "dry_run":
            last += " (a dry run writes no receipt)"
    else:
        last = attempt.get("last_attempt_reason") or "last attempt unknown"
    nxt = (f"next fire {_et_text(attempt['next_fire_at'])} ({attempt.get('dispatch_mode')})"
           if attempt.get("next_fire_at")
           else "no scheduled fire found in the registry")
    label = "MISSING" if census.get("freshness") == "UNAVAILABLE" else "STALE"
    prs = ("Open PRs are UNKNOWN" if label == "MISSING" else "The open-PR list is from the last good census")
    return (f"PR census {label} — {why}; {last}; {nxt}. {prs}: the queue store's count is only PRs explicitly "
            f"queued for the train, not what is waiting.")


def read_queue(db_query, now: datetime, *, ledger: Optional[Path] = None,
               registry: Optional[Path] = None) -> dict[str, Any]:
    src = "postgres:release_queue + receipt:pr-hygiene-audit (release_train_view.build_queue)"
    q = RTV.build_queue(db_query, {})
    census = q.get("census") or {}
    attempt = census_attempt(ledger, registry, now) if census.get("freshness") != "OK" else None
    alert = census_alert(census, attempt) if attempt is not None else None
    titles = RTV._receipt_titles(None)
    open_prs = []
    for b in ((census.get("value") or {}).get("buckets") or []):
        for n in b.get("prs") or []:
            open_prs.append({"pr": n, "title": titles.get(n), "bucket": b.get("name"),
                             "why_not_riding": BUCKET_WHY.get(b.get("name"), b.get("name")),
                             "riding": b.get("name") == "queued"})
    value = {"store": {"freshness": q.get("freshness"), "reason": q.get("reason"), "as_of": q.get("as_of"),
                       "total": q.get("total"), "rows": q.get("rows")},
             "census": {"freshness": census.get("freshness"), "reason": census.get("reason"),
                        "as_of": census.get("as_of"),
                        "open_prs": (census.get("value") or {}).get("open_prs"),
                        "status": (census.get("value") or {}).get("status"),
                        "attempt": attempt, "alert": alert},
             "open_prs": open_prs}
    if q.get("freshness") != "OK" and census.get("freshness") == "UNAVAILABLE":
        return field(value, None, "UNAVAILABLE", src,
                     alert or f"queue store: {q.get('reason')}; census: {census.get('reason')}", now=now)
    fresh = "OK" if q.get("freshness") == "OK" and census.get("freshness") == "OK" else "STALE"
    reasons = [f"queue store {q.get('freshness')}: {q.get('reason')}" if q.get("freshness") != "OK" else None,
               f"census {census.get('freshness')}: {census.get('reason')}" if census.get("freshness") != "OK" else None]
    return field(value, census.get("as_of") or q.get("as_of"), fresh, src,
                 "; ".join(r for r in [alert, *reasons] if r) or None, now=now)


# ── n8n side ──────────────────────────────────────────────────────────────────────────────────────────────────


def _connect_ro(path: Path, deadline_s: float = 2.5) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    deadline = time.monotonic() + deadline_s
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _receipt_bits(raw: Any) -> dict[str, Any]:
    try:
        doc = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    ov = doc.get("output_verdict") if isinstance(doc.get("output_verdict"), dict) else {}
    return {"reason": doc.get("reason"), "why": ov.get("why"), "timed_out": doc.get("timed_out")}


def read_ledger_today(ledger: Path, now: datetime) -> dict[str, Any]:
    src = "sqlite:n8n_coordination_ledger runs + dead_letters (mode=ro)"
    local = now.astimezone(ET)
    midnight = datetime(local.year, local.month, local.day, tzinfo=ET).astimezone(timezone.utc)
    since = midnight.isoformat()
    try:
        conn = _connect_ro(ledger)
    except (OSError, sqlite3.Error) as exc:
        return _unavailable(src, f"ledger unreadable: {type(exc).__name__}", now)
    try:
        conn.execute("BEGIN")
        if not _has_table(conn, "runs"):
            return _unavailable(src, "runs table absent; absence does not establish zero runs", now)
        by_mode_state: dict[str, dict[str, int]] = {}
        for mode, state, n in conn.execute(
                "SELECT mode, state, COUNT(*) FROM runs WHERE requested_at >= ? GROUP BY mode, state", (since,)):
            by_mode_state.setdefault(str(mode), {})[str(state)] = int(n)
        lanes = [{"lane": str(lane), "runs": int(n), "errors": int(e or 0), "skips": int(s or 0)}
                 for lane, n, e, s in conn.execute(
                     "SELECT lane_id, COUNT(*), SUM(state IN ('RUN_FAILED','RUN_TIMEOUT','RUN_REFUSED')), "
                     "SUM(state = 'RUN_SKIPPED_LOCK') FROM runs WHERE requested_at >= ? GROUP BY lane_id "
                     "ORDER BY COUNT(*) DESC, lane_id LIMIT 10", (since,))]
        errors = []
        for rid, lane, mode, state, at, code, raw in conn.execute(
                "SELECT run_id, lane_id, mode, state, COALESCE(finished_at, started_at, requested_at), exit_code, "
                "receipt_json FROM runs WHERE requested_at >= ? AND state IN ('RUN_FAILED','RUN_TIMEOUT',"
                "'RUN_REFUSED') ORDER BY requested_at DESC LIMIT ?", (since, MAX_ERRORS)):
            errors.append({"run_id": rid, "lane": lane, "mode": mode, "state": state, "at": at, "exit_code": code,
                           **_receipt_bits(raw)})
        skips = [{"lane": str(lane), "mode": str(mode), "count": int(n), "last_at": last}
                 for lane, mode, n, last in conn.execute(
                     "SELECT lane_id, mode, COUNT(*), MAX(requested_at) FROM runs WHERE requested_at >= ? AND "
                     "state = 'RUN_SKIPPED_LOCK' GROUP BY lane_id, mode ORDER BY COUNT(*) DESC LIMIT 30", (since,))]
        last_run_by_lane = {str(lane): {"at": at, "state": st, "mode": md}
                            for lane, at, st, md in conn.execute(
                                "SELECT r.lane_id, r.requested_at, r.state, r.mode FROM runs r JOIN (SELECT lane_id, "
                                "MAX(requested_at) m FROM runs WHERE requested_at >= ? GROUP BY lane_id) x ON "
                                "x.lane_id = r.lane_id AND x.m = r.requested_at", (since,))}
        dead: dict[str, Any] = {"available": False, "unreleased": None, "recent": None}
        if _has_table(conn, "dead_letters"):
            n = conn.execute("SELECT COUNT(*) FROM dead_letters WHERE released_at IS NULL").fetchone()[0]
            recent = [{"lane": lane, "slot_key": sk, "dead_at": at, "last_state": ls, "last_reason": lr}
                      for sk, lane, at, ls, lr in conn.execute(
                          "SELECT slot_key, lane_id, dead_at, last_state, last_reason FROM dead_letters WHERE "
                          "released_at IS NULL ORDER BY dead_at DESC LIMIT 20")]
            dead = {"available": True, "unreleased": int(n), "recent": recent}
        latest = conn.execute("SELECT MAX(requested_at) FROM runs").fetchone()[0]
        conn.execute("ROLLBACK")
    except sqlite3.Error as exc:
        return _unavailable(src, f"ledger read failed: {type(exc).__name__}", now)
    finally:
        conn.close()
    totals = {m: sum(s.values()) for m, s in by_mode_state.items()}
    states: dict[str, int] = {}
    for s in by_mode_state.values():
        for k, v in s.items():
            states[k] = states.get(k, 0) + v
    value = {"day": local.date().isoformat(), "since": since, "time_basis": "runs.requested_at >= ET midnight",
             "total": sum(totals.values()), "by_mode": totals, "by_state": states, "by_mode_state": by_mode_state,
             "errors_total": sum(states.get(s, 0) for s in ERROR_RUN_STATES),
             "skips_total": states.get("RUN_SKIPPED_LOCK", 0), "errors": errors, "lock_skips": skips,
             "busiest": lanes, "dead_letters": dead, "last_run_by_lane": last_run_by_lane,
             "latest_requested_at": latest}
    return field(value, latest or _iso(now), "OK", src, None, now=now)


def parse_crontab(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(active, paused). Active: uncommented schedule lines (env assignments skipped). Paused: ``# PAUSED <date>
    <note> <schedule> <command>`` lines; the note is everything before the schedule. Pure."""
    active, paused = [], []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        pm = PAUSED_RE.match(s)
        if pm:
            rest = " " + pm.group(2)
            cut = re.search(r"\s((?:\*|\d)[\d*/,\-]*\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-a-zA-Z]+\s+[\d*/,\-a-zA-Z]+)\s+(\S.*)$",
                            rest)
            if cut:
                paused.append({"since": pm.group(1), "note": rest[:cut.start()].strip()[:160] or None,
                               "schedule": cut.group(1), "command": cut.group(2)})
            continue
        if s.startswith("#"):
            continue
        head = s.split(None, 1)[0]
        if "=" in head and not head[0].isdigit() and head[0] not in "*@":
            continue
        m = CRON5_RE.match(s)
        if m:
            active.append({"schedule": m.group(1), "command": m.group(2)})
    return active, paused


def _lane_for_command(command: str, cron_lanes: list[tuple[str, Mapping[str, Any]]]) -> Optional[Mapping[str, Any]]:
    best = None
    for match, row in cron_lanes:
        if match and match in command and (best is None or len(match) > len(best[0])):
            best = (match, row)
    return best[1] if best else None


def _short_command(command: str) -> str:
    m = re.search(r"scripts/([\w./-]+\.(?:py|sh|mjs))", command)
    return m.group(1) if m else command.split(">>")[0].strip()[:80]


def _fires(expr: str, start: datetime, end: datetime, tz: Optional[str] = None) -> Optional[list[datetime]]:
    try:
        from lib import cron_schedule as CS
    except ImportError:  # pragma: no cover
        from scripts.lib import cron_schedule as CS  # type: ignore[no-redef]
    fields = CS.cron_fields(expr)
    if not fields or fields == CS.REBOOT:
        return None
    try:
        return [f.at for f in (CS.fires_between(fields, start, end, tz) if tz else CS.fires_between(fields, start, end))]
    except ValueError:
        return None


def _rows_for(fires: list[datetime], base: dict[str, Any]) -> list[dict[str, Any]]:
    if not fires:
        return []
    if len(fires) > COLLAPSE_AFTER:
        gap = int(round((fires[1] - fires[0]).total_seconds() / 60)) if len(fires) > 1 else None
        return [{**base, "at": _iso(fires[0]), "fires_in_horizon": len(fires),
                 "cadence_label": f"every {gap} min" if gap else f"{len(fires)}x"}]
    return [{**base, "at": _iso(f), "fires_in_horizon": 1, "cadence_label": None} for f in fires]


def read_timeline(now: datetime, *, registry_path: Path, live_lanes_path: Path,
                  crontab_reader: Optional[Callable[[], tuple[str, str, Optional[str], Optional[float]]]] = None,
                  last_run_by_lane: Optional[Mapping[str, Any]] = None, hours: int = HORIZON_H) -> dict[str, Any]:
    """Next ``hours`` of host cron and n8n lanes. ``crontab_reader`` returns (text, source, error, age_s)."""
    src = "crontab -l (or its fresh snapshot) + config/lane_registry.json + n8n-live-lanes.env (names only)"
    end = now + timedelta(hours=hours)
    notes: list[str] = []
    try:
        reg = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        lanes = [r for r in reg.get("lanes") or [] if isinstance(r, dict)]
    except (OSError, ValueError) as exc:
        lanes = None
        notes.append(f"lane registry unreadable: {type(exc).__name__}")
    try:
        try:
            from check_registry_runtime_truth import read_live_lanes  # type: ignore
        except ImportError:
            from scripts.check_registry_runtime_truth import read_live_lanes  # type: ignore[no-redef]
        live_status, live_names, live_note = read_live_lanes(Path(live_lanes_path))
    except Exception as exc:  # noqa: BLE001
        live_status, live_names, live_note = "unavailable", [], type(exc).__name__
    live = set(live_names) if live_status == "ok" else None
    if live is None:
        notes.append(f"relay live list unavailable ({live_note}); n8n live membership unknown")
    if crontab_reader is None:
        try:
            from lib import crontab_snapshot as CSN
        except ImportError:  # pragma: no cover
            from scripts.lib import crontab_snapshot as CSN  # type: ignore[no-redef]
        r = CSN.read_crontab()
        cron_text, cron_source, cron_error, cron_age = r.text, r.source, r.error, r.age_s
    else:
        cron_text, cron_source, cron_error, cron_age = crontab_reader()
    last = last_run_by_lane or {}
    rows: list[dict[str, Any]] = []
    cron_ok = cron_source in ("crontab", "snapshot")
    if not cron_ok:
        notes.append(f"host crontab unavailable: {cron_error}")
    reg_by_id = {str(r.get("lane_id")): r for r in lanes or []}
    cron_lanes = [(str((r.get("scheduler") or {}).get("match") or ""), r) for r in lanes or []
                  if (r.get("scheduler") or {}).get("kind") == "cron"]
    active, paused = parse_crontab(cron_text) if cron_ok else ([], [])
    for kind, entries in (("cron", active), ("paused", paused)):
        for e in entries:
            fires = _fires(e["schedule"], now, end)
            if fires is None:
                continue
            lane = _lane_for_command(e["command"], cron_lanes)
            lane_id = str(lane.get("lane_id")) if lane else None
            stage = (lane or {}).get("scheduler", {}).get("stage") if lane else None
            base = {"lane": lane_id or _short_command(e["command"]), "lane_id": lane_id, "runner": "cron",
                    "schedule": e["schedule"], "stage": "PAUSED" if kind == "paused" else "LIVE",
                    "n8n_stage": stage, "paused_since": e.get("since"), "paused_note": e.get("note"),
                    "registry_state": (lane or {}).get("state"),
                    "last_run": last.get(lane_id) if lane_id else None}
            rows.extend(_rows_for(fires, base))
    for r in lanes or []:
        sch = r.get("scheduler") or {}
        stage = sch.get("stage")
        n8n_kind = sch.get("kind") == "n8n"
        if not (n8n_kind or stage in ("shadow", "canary", "cutover")):
            continue
        if str(r.get("state") or "").upper() in ("RETIRED", "PAUSED", "NEVER_SCHEDULED"):
            continue
        expr = sch.get("cadence") if n8n_kind else sch.get("expression")
        fires = _fires(str(expr or ""), now, end)
        if not fires:
            continue
        lane_id = str(r.get("lane_id"))
        in_live = (lane_id in live) if live is not None else None
        if stage:
            label = stage.upper()
        else:
            label = "LIVE" if in_live else ("NOT LIVE" if in_live is False else "UNKNOWN")
        rows.extend(_rows_for(fires, {"lane": lane_id, "lane_id": lane_id, "runner": "n8n", "schedule": expr,
                                      "stage": label, "n8n_stage": stage, "in_relay_live_list": in_live,
                                      "registry_state": r.get("state"), "last_run": last.get(lane_id),
                                      "paused_since": None, "paused_note": None}))
    discrete = sorted((x for x in rows if x["fires_in_horizon"] == 1), key=lambda x: (x["at"], x["lane"]))
    recurring = sorted((x for x in rows if x["fires_in_horizon"] > 1),
                       key=lambda x: (-x["fires_in_horizon"], x["lane"], x["runner"]))
    truncated = len(discrete) > MAX_TIMELINE or len(recurring) > MAX_TIMELINE
    value = {"horizon_hours": hours, "from": _iso(now), "to": _iso(end), "rows": discrete[:MAX_TIMELINE],
             "recurring": recurring[:MAX_TIMELINE], "rows_total": len(discrete), "recurring_total": len(recurring),
             "truncated": truncated, "crontab": {"source": cron_source, "error": cron_error, "age_s": cron_age,
                                                 "active_lines": len(active), "paused_lines": len(paused)},
             "live_lanes": {"status": live_status, "count": len(live) if live is not None else None},
             "registry_lanes": len(lanes) if lanes is not None else None, "notes": notes}
    if lanes is None and not cron_ok:
        return field(value, None, "UNAVAILABLE", src, "; ".join(notes), now=now)
    fresh = "OK" if (cron_ok and lanes is not None and live is not None) else "STALE"
    return field(value, _iso(now), fresh, src, "; ".join(notes) or None, now=now)


# ── KPIs and assembly ─────────────────────────────────────────────────────────────────────────────────────────


def _kpi(key: str, label: str, value: Any, detail: Optional[str], tone: str, section: Mapping[str, Any]) -> dict:
    if section.get("freshness") == "UNAVAILABLE":
        return {"key": key, "label": label, "value": None, "detail": section.get("reason"), "tone": "warning",
                "freshness": "UNAVAILABLE", "as_of": None}
    return {"key": key, "label": label, "value": value, "detail": detail, "tone": tone,
            "freshness": section.get("freshness"), "as_of": section.get("as_of")}


def kpis(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    sv = sections["serving"].get("value") or {}
    nx = sections["next_release"].get("value") or {}
    wn = sections["windows"].get("value") or {}
    td = sections["n8n_today"].get("value") or {}
    nxt = next(iter(wn.get("windows") or []), None)
    ci = (nx.get("ci") or {})
    nx_detail = None
    if nx:
        nx_detail = ("same as serving" if nx.get("is_serving") else
                     f"{nx.get('commits_ahead') if nx.get('commits_ahead') is not None else '?'} commits ahead"
                     ) + f" · main CI {ci.get('state', 'UNAVAILABLE')}"
    by_mode = td.get("by_mode") or {}
    return [
        _kpi("serving", "Serving", sv.get("short_sha"),
             (f"since {sv.get('since')}" if sv.get("since") else None), "success" if sv.get("pins_agree") else "warning",
             sections["serving"]),
        _kpi("next_release", "Releasing next", nx.get("short_sha"), nx_detail,
             "neutral" if nx.get("is_serving") else ("success" if ci.get("state") in ("OK", "SUCCESS") else
                                                     "danger" if ci.get("state") in ("FAILURE", "NOT_GREEN") else
                                                     "warning"),
             sections["next_release"]),
        _kpi("next_window", "Next train window", nxt.get("local_time") if nxt else None,
             (f"{nxt.get('role')} · {nxt.get('state')}" + (f" · {nxt.get('reason')}" if nxt.get("reason") else ""))
             if nxt else None, "info" if nxt and nxt.get("state") == "SHADOW" else "neutral", sections["windows"]),
        _kpi("n8n_runs", "n8n runs today", td.get("total"),
             ", ".join(f"{v} {k}" for k, v in sorted(by_mode.items())) or None, "neutral", sections["n8n_today"]),
        _kpi("n8n_errors", "n8n errors · skips",
             None if not td else f"{td.get('errors_total')} · {td.get('skips_total')}",
             None if not td else f"dead letters unreleased: {(td.get('dead_letters') or {}).get('unreleased')}",
             "danger" if td.get("errors_total") else "neutral", sections["n8n_today"]),
    ]


def build(db_query, *, now: Optional[datetime] = None, paths: Optional[Mapping[str, Path]] = None,
          timeout_s: float = DEFAULT_TIMEOUT_S, git: Optional[Callable[[list[str]], tuple[int, str]]] = None,
          crontab_reader=None, readiness=None, executor: Optional[cf.Executor] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    p = {**default_paths(), **(paths or {})}
    g = git or git_runner(p["canonical_source"])
    ex = executor or _executor()
    res = RTV.run_probes({
        "serving": lambda: read_serving(p["releases_base"], p["deploy_state_dir"], now),
        "history": lambda: read_history(p["releases_base"], p["deploy_state_dir"], now, git=g),
        "windows": lambda: read_windows(now, rw_state_dir=p["release_window_state_dir"], readiness=readiness),
        "queue": lambda: read_queue(db_query, now, ledger=p["ledger"], registry=p["registry"]),
        "n8n_today": lambda: read_ledger_today(p["ledger"], now),
        "stop": lambda: RTV.read_stop(p["release_window_state_dir"]),
    }, timeout_s, executor=ex)
    sources = {
        "serving": "CURRENT symlink + BUILD_SHA pins", "history": "release_pins + deploy_receipt.json",
        "windows": "config/release_train_policy.json + readiness", "queue": "postgres:release_queue + census",
        "n8n_today": "sqlite:n8n_coordination_ledger", "stop": "file:release_window/STOP.json",
    }
    sec: dict[str, Any] = {}
    for k in ("serving", "history", "windows", "queue", "n8n_today"):
        r = res[k]
        sec[k] = r["value"] if r["status"] == "OK" else _unavailable(sources[k], r["error"], now)
    stop = res["stop"]["value"] if res["stop"]["status"] == "OK" else {
        "state": "UNREADABLE", "effective_stop": True, "latch_reason": res["stop"]["error"]}
    serving_sha = (sec["serving"].get("value") or {}).get("sha")
    ledger_last = (sec["n8n_today"].get("value") or {}).get("last_run_by_lane")
    remaining = max(0.5, timeout_s - 0.5)
    res2 = RTV.run_probes({
        "next_release": lambda: read_next_release(p["canonical_source"], p["deploy_state_dir"], serving_sha, now,
                                                  git=g, main_ci_receipt=p.get("main_ci_receipt")),
        "release_errors": lambda: read_release_errors(p["deploy_state_dir"], p["release_window_state_dir"], now,
                                                      stop=stop, main_ci_receipt=p.get("main_ci_receipt")),
        "timeline": lambda: read_timeline(now, registry_path=p["registry"], live_lanes_path=p["live_lanes_env"],
                                          crontab_reader=crontab_reader, last_run_by_lane=ledger_last),
    }, remaining, executor=ex)
    src2 = {"next_release": "git:canonical origin/main", "release_errors": "release receipts",
            "timeline": "crontab + lane_registry"}
    for k, r in res2.items():
        sec[k] = r["value"] if r["status"] == "OK" else _unavailable(src2[k], r["error"], now)
    data = {"schema": SCHEMA, "authority": AUTHORITY, "generated_at": _iso(now), "timeout_s": timeout_s,
            "kpis": kpis(sec), **sec,
            "stop": {"state": stop.get("state"), "effective_stop": stop.get("effective_stop"),
                     "latched_at": stop.get("latched_at"), "reason": stop.get("latch_reason")},
            "sources": {k: {"status": v["status"], "ms": v["ms"]} for k, v in {**res, **res2}.items()}}
    fields = [v for v in sec.values() if isinstance(v, dict) and "freshness" in v]
    data["status"] = ("OK" if all(f["freshness"] == "OK" for f in fields) else
                      "UNAVAILABLE" if all(f["freshness"] == "UNAVAILABLE" for f in fields) else "DEGRADED")
    return data


def handle(path: str, method: str, query: Optional[Mapping[str, Any]], db_query) -> Optional[tuple[int, dict]]:
    """(status, body) for GET ROUTE; 405 for any other method on ROUTE; None for every other path."""
    base = path.split("?")[0].rstrip("/") or path
    if base != ROUTE:
        return None
    if (method or "GET").upper() != "GET":
        return 405, {"ok": False, "error": "read_only"}
    with _CACHE_LOCK:
        hit = _CACHE.get(base)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return 200, {"ok": True, "data": {**hit[1], "cache": "HIT"}}
    data = build(db_query)
    with _CACHE_LOCK:
        _CACHE[base] = (time.monotonic(), data)
    return 200, {"ok": True, "data": {**data, "cache": "MISS"}}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["SCHEMA", "ROUTE", "build", "handle", "clear_cache", "parse_crontab", "read_serving", "read_next_release",
           "read_history", "read_release_errors", "read_windows", "read_queue", "read_ledger_today", "read_timeline",
           "main_ci_from_receipt", "census_attempt", "census_alert",
           "kpis", "default_paths"]
