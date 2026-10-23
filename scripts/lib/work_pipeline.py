"""Work pipeline: one row per WORK ITEM (task, PR or design phase), staged as an incubator workflow.

Operator 2026-10-23 13:15 ET, on Ops -> Coordination -> "Who's working": "This should be telling who, what, when,
where, and how, and should be an incubator workflow that I can see at each stage, whether it's green, amber, red,
what are next steps?" and "We have a whole bunch of stuff that says stale, where are the items that are queued up?"

The old view was one row per file claim, and "stale" meant only "no heartbeat for 2 h", so finished work waiting for
a release batch looked dead. This module joins what already exists into one read model:

* the task board (``agent_task_board``: free / taken / done tasks, OPERATOR to-dos),
* the claims plus their lifecycle (``agent_claim_board.board_view``: claimed -> building -> pr_open -> ci_green ->
  merged -> released, worklog summary),
* the design registry (``design_registry``: designs and packets awaiting operator approval),
* a GitHub PR census (open PRs with their check rollup, recently merged PRs, the open release-batch PRs and their
  Included / Excluded lists), and
* the release receipts (served SHA, ``release_pins/apply-*.json``, ``deploy_receipt.json`` health).

Stages (``STAGES``)::

    proposed -> approved -> queued -> claimed -> building -> pr_open -> ci -> in_batch -> merged -> released -> verified

An item SITS in exactly one stage. Cells before it are green (done), its own cell is amber (in progress or waiting)
or red (blocked, failed or stale), cells after it are grey (not reached). A verified item is all green and counts as
finished. RAG rules that answer the operator's complaint directly:

* PR open and CI green, not in a batch: sits in ``in_batch``, AMBER "waiting for batch". Never "stale".
* "stale" (red) only when there is no heartbeat for ``stale_hours`` AND the item is pre-PR (claimed/building), or
  CI has failed AND there has been no activity for more than ``stale_hours``.

Every item carries who / what / when / where / how, a blocker and a NEXT STEP with its owner (``operator`` or
``agent``). A claim worklog's Handoff "Next step:" wins over the derived next step.

Memory and GitHub safety (the 2026-10-23 server kills came from unbounded per-request reads):

* the view is built at most once per ``REFRESH_S`` with single-flight (a concurrent caller gets the last value);
* GitHub is read only by a background thread, at most once per ``CENSUS_MIN_INTERVAL_S`` (60 s), single-flight,
  with a timeout per call and a byte cap on every output; a request never waits on GitHub and never starts more
  than one refresh;
* every list is capped (``MAX_OPEN_PRS``, ``MAX_MERGED_PRS``, ``MAX_BATCHES``, ``MAX_ITEMS``) and worklogs are read
  through a bounded tail (``WORKLOG_TAIL_BYTES``).

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY -- read-only ``gh pr list|view`` and ``gh api --method GET``, local
``git merge-base --is-ancestor``, coordination and receipt files. Writes nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from scripts.lib import agent_claim_lifecycle as LC
except ImportError:  # scripts/ on sys.path (api_v2)
    from lib import agent_claim_lifecycle as LC  # type: ignore[no-redef]

SCHEMA = "WorkPipeline@v1"
STAGES = (
    "proposed",
    "approved",
    "queued",
    "claimed",
    "building",
    "pr_open",
    "ci",
    "in_batch",
    "merged",
    "released",
    "verified",
)
STAGE_LABEL = {
    "proposed": "Proposed",
    "approved": "Approved",
    "queued": "Queued",
    "claimed": "Claimed",
    "building": "Building",
    "pr_open": "PR open",
    "ci": "CI",
    "in_batch": "In batch",
    "merged": "Merged",
    "released": "Released",
    "verified": "Verified live",
}
STAGE_HELP = {
    "proposed": "A design, packet or draft PR waiting for the operator's approval.",
    "approved": "Approved, but no task registered on the task board yet.",
    "queued": "On the task board, free: nobody has started it (OPERATOR: tasks are the operator's to-dos).",
    "claimed": "An agent claimed the files; work not started.",
    "building": "The agent declared it is implementing.",
    "pr_open": "A pull request is open; CI not observed yet (or the PR is a draft / closed).",
    "ci": "CI is running or failing on the PR's head commit.",
    "in_batch": "CI green. Waiting for a release batch, in an open batch, or waiting for an operator merge.",
    "merged": "Merged to main; waiting for a release.",
    "released": "In a release this host applied; waiting for live verification.",
    "verified": "The served release contains it and the deploy health check passed.",
}
RAGS = ("green", "amber", "red", "grey")
OWNERS = ("operator", "agent")
REFRESH_S = 30.0
CENSUS_MIN_INTERVAL_S = 60.0
GH_CALL_TIMEOUT_S = 25.0
MAX_GH_OUTPUT_BYTES = 6 * 1024 * 1024
MAX_OPEN_PRS = 100
MAX_MERGED_PRS = 40
MAX_BATCHES = 3
MAX_ITEMS = 400
MAX_FILES_SHOWN = 60
WORKLOG_TAIL_BYTES = 24 * 1024
DEFAULT_STALE_HOURS = 2.0
BATCH_BRANCH_RE = re.compile(r"^release/batch-\d+")
HOLD_RE = re.compile(r"\b(DRAFT|PROPOSED|DO[- ]NOT[- ]MERGE|HOLD)\b", re.I)
OPERATOR_PREFIX_RE = re.compile(r"^\s*OPERATOR\s*:\s*", re.I)
_TS_RE = re.compile(r"`(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)`")
_PR_REF_RE = re.compile(r"#(\d{2,6})\b")
_OK_CONCLUSIONS = ("SUCCESS", "SKIPPED", "NEUTRAL")
_OK_STATES = ("SUCCESS",)


# --------------------------------------------------------------------------------------------- time helpers


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    return LC._parse(value)


def _iso(dt: datetime | None) -> str | None:
    return LC._iso(dt)


def _max_iso(*values: Any) -> str | None:
    got = [d for d in (_parse(v) for v in values) if d is not None]
    return _iso(max(got)) if got else None


def _age_min(ts: Any, now: datetime) -> float | None:
    d = _parse(ts)
    return None if d is None else round((now - d).total_seconds() / 60, 1)


# --------------------------------------------------------------------------------------------- GitHub census


def ci_from_rollup(rollup: Iterable[Mapping[str, Any]] | None, required: Iterable[str] | None = None) -> dict[str, Any]:
    """``gh pr list --json statusCheckRollup`` -> {state, failing, pending, total, completed_at}.

    CheckRun entries carry name/status/conclusion/completedAt; StatusContext entries carry context/state. Only the
    latest entry per name counts. When ``required`` is known, only those names decide the state."""
    if rollup is None:
        return {"state": "unknown", "failing": [], "pending": [], "total": 0, "completed_at": None}
    latest: dict[str, Mapping[str, Any]] = {}
    for r in rollup:
        if not isinstance(r, Mapping):
            continue
        name = str(r.get("name") or r.get("context") or "")
        if not name:
            continue
        prev = latest.get(name)
        key = str(r.get("startedAt") or r.get("completedAt") or "")
        if prev is None or key >= str(prev.get("startedAt") or prev.get("completedAt") or ""):
            latest[name] = r
    req = sorted(set(required or ()))
    names = [n for n in req if n in latest] if req else sorted(latest)
    missing = [n for n in req if n not in latest]
    failing, pending, done_at = [], list(missing), []
    for n in names:
        r = latest[n]
        if "context" in r and "status" not in r:  # StatusContext
            st = str(r.get("state") or "").upper()
            if st in _OK_STATES:
                done_at.append(str(r.get("createdAt") or ""))
            elif st in ("PENDING", "EXPECTED", ""):
                pending.append(n)
            else:
                failing.append(n)
            continue
        if str(r.get("status") or "").upper() != "COMPLETED":
            pending.append(n)
        elif str(r.get("conclusion") or "").upper() in _OK_CONCLUSIONS:
            done_at.append(str(r.get("completedAt") or ""))
        else:
            failing.append(n)
    if not names and not missing:
        state = "unknown"
    elif failing:
        state = "failing"
    elif pending:
        state = "pending"
    else:
        state = "green"
    return {
        "state": state,
        "failing": failing[:12],
        "pending": pending[:12],
        "total": len(names) + len(missing),
        "completed_at": _max_iso(*done_at) if state == "green" else None,
    }


def parse_batch_body(body: str | None) -> dict[str, Any]:
    """A release-batch PR body -> {members: [pr numbers], excluded: {pr: reason}}.

    ``## Included`` table rows start ``| #NNNN |``; ``## Excluded`` bullets read ``- #1991, #1997: reason``."""
    members: list[int] = []
    excluded: dict[int, str] = {}
    section = None
    for raw in (body or "").splitlines()[:600]:
        line = raw.strip()
        m = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if m:
            h = m.group(1).lower()
            section = "in" if h.startswith("included") else ("ex" if h.startswith("excluded") else None)
            continue
        if section == "in":
            mm = re.match(r"^\|\s*#(\d+)\s*\|", line)
            if mm and int(mm.group(1)) not in members:
                members.append(int(mm.group(1)))
        elif section == "ex" and line.startswith("-"):
            head, _, reason = line.lstrip("- ").partition(":")
            for n in _PR_REF_RE.findall(head):
                excluded[int(n)] = (reason.strip() or "excluded from the batch")[:200]
    return {"members": members, "excluded": excluded}


def _norm_open_pr(p: Mapping[str, Any], required: list[str] | None) -> dict[str, Any]:
    return {
        "number": int(p.get("number") or 0),
        "title": str(p.get("title") or "")[:200],
        "url": p.get("url"),
        "branch": p.get("headRefName"),
        "head_sha": p.get("headRefOid"),
        "base": p.get("baseRefName"),
        "draft": bool(p.get("isDraft")),
        "author": ((p.get("author") or {}).get("login") if isinstance(p.get("author"), Mapping) else None),
        "created_at": LC._norm_iso(p.get("createdAt")),
        "updated_at": LC._norm_iso(p.get("updatedAt")),
        "state": "open",
        "ci": ci_from_rollup(p.get("statusCheckRollup"), required if p.get("baseRefName") == "main" else None),
    }


def _norm_merged_pr(p: Mapping[str, Any]) -> dict[str, Any]:
    mc = p.get("mergeCommit") if isinstance(p.get("mergeCommit"), Mapping) else {}
    return {
        "number": int(p.get("number") or 0),
        "title": str(p.get("title") or "")[:200],
        "url": p.get("url"),
        "branch": p.get("headRefName"),
        "base": p.get("baseRefName"),
        "draft": False,
        "author": ((p.get("author") or {}).get("login") if isinstance(p.get("author"), Mapping) else None),
        "created_at": LC._norm_iso(p.get("createdAt")),
        "updated_at": LC._norm_iso(p.get("mergedAt")),
        "merged_at": LC._norm_iso(p.get("mergedAt")),
        "merge_sha": (mc or {}).get("oid"),
        "state": "merged",
        "ci": None,
    }


class PrCensus:
    """Open PRs + check rollup, recently merged PRs (with release detection), and open release-batch PRs.

    Refreshed only by :meth:`kick` in a background thread, at most once per ``min_interval_s``, never two at once.
    ``runner`` runs a gh argv and returns (stdout, warning); injectable for tests."""

    def __init__(
        self,
        *,
        runner: Callable[[list[str]], tuple[str | None, str | None]] | None = None,
        release: "LC.ReleaseReader | None" = None,
        min_interval_s: float = CENSUS_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
    ):
        self.runner = runner or _gh_runner
        self.release = release
        self.min_interval_s = min_interval_s
        self.clock = clock
        self.now = now
        self.value: dict[str, Any] | None = None
        self.warning: str | None = "PR census: first refresh pending"
        self.refreshed_at: str | None = None
        self.refreshes = 0
        self._at: float | None = None
        self._running = False
        self._lock = threading.Lock()
        self._required: tuple[float, list[str] | None] | None = None

    def kick(self, *, background: bool = True) -> bool:
        """Start one refresh if due and none is running. Returns True when a refresh started."""
        with self._lock:
            due = self._at is None or self.clock() - self._at >= self.min_interval_s
            if not due or self._running:
                return False
            self._running = True
            self._at = self.clock()
        if background:
            threading.Thread(target=self._refresh, daemon=True, name="work-pipeline-census").start()
        else:
            self._refresh()
        return True

    def snapshot(self) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with self._lock:
            return self.value, {
                "refreshed_at": self.refreshed_at,
                "warning": self.warning,
                "refreshing": self._running,
                "min_interval_s": self.min_interval_s,
                "refreshes": self.refreshes,
            }

    def _json(self, argv: list[str]) -> tuple[Any, str | None]:
        out, warn = self.runner(argv)
        if out is None:
            return None, warn
        try:
            return json.loads(out or "null"), warn
        except ValueError:
            return None, f"gh returned unparseable JSON ({' '.join(argv[:3])})"

    def _required_contexts(self) -> list[str] | None:
        if self._required and self.clock() - self._required[0] < LC.REQUIRED_TTL_S:
            return self._required[1]
        repo = LC.default_repo()
        doc, _w = self._json(
            ["gh", "api", "--method", "GET", f"repos/{repo}/branches/main/protection/required_status_checks"]
        )
        req = None
        if isinstance(doc, dict):
            req = [str(c) for c in doc.get("contexts") or []]
            req += [str(c.get("context")) for c in doc.get("checks") or [] if isinstance(c, dict) and c.get("context")]
            req = sorted(set(req)) or None
        self._required = (self.clock(), req)
        return req

    def _refresh(self) -> None:
        warnings: list[str] = []
        try:
            required = self._required_contexts()
            opened, w = self._json(
                [
                    "gh", "pr", "list", "--state", "open", "--limit", str(MAX_OPEN_PRS), "--json",
                    "number,title,url,headRefName,headRefOid,baseRefName,isDraft,author,createdAt,updatedAt,statusCheckRollup",
                ]
            )  # fmt: skip
            if w:
                warnings.append(w)
            merged, w = self._json(
                [
                    "gh", "pr", "list", "--state", "merged", "--limit", str(MAX_MERGED_PRS), "--json",
                    "number,title,url,headRefName,baseRefName,author,createdAt,mergedAt,mergeCommit",
                ]
            )  # fmt: skip
            if w:
                warnings.append(w)
            if not isinstance(opened, list):
                raise RuntimeError(warnings[0] if warnings else "open PR list unavailable")
            open_prs = [_norm_open_pr(p, required) for p in opened[:MAX_OPEN_PRS] if isinstance(p, dict)]
            merged_prs = [_norm_merged_pr(p) for p in (merged or [])[:MAX_MERGED_PRS] if isinstance(p, dict)]
            batches: dict[int, dict[str, Any]] = {}
            for p in [p for p in open_prs if BATCH_BRANCH_RE.match(str(p.get("branch") or ""))][:MAX_BATCHES]:
                doc, w = self._json(["gh", "pr", "view", str(p["number"]), "--json", "body"])
                if w:
                    warnings.append(w)
                parsed = parse_batch_body((doc or {}).get("body") if isinstance(doc, dict) else None)
                batches[p["number"]] = {**parsed, "number": p["number"], "title": p["title"], "ci": p["ci"]}
            if self.release is not None:
                for p in merged_prs:
                    if p.get("merge_sha"):
                        try:
                            p["released"] = self.release.released(str(p["merge_sha"]), p.get("merged_at"))
                        except Exception as exc:  # noqa: BLE001 - release detection degrades, never raises
                            warnings.append(f"release detection failed ({type(exc).__name__})")
                            break
            value = {"open": open_prs, "merged": merged_prs, "batches": batches, "required": required}
            with self._lock:
                self.value = value
                self.warning = "; ".join(dict.fromkeys(warnings))[:300] or None
                self.refreshed_at = _iso(self.now())
                self.refreshes += 1
        except Exception as exc:  # noqa: BLE001 - background refresh must never crash the server
            with self._lock:
                self.warning = f"PR census unavailable: {str(exc)[:160] or type(exc).__name__} (last good kept)"
        finally:
            with self._lock:
                self._running = False


def _gh_runner(argv: list[str]) -> tuple[str | None, str | None]:
    """Read-only gh: ``pr list``, ``pr view`` or ``api --method GET``. Timeout and byte cap on every call."""
    if argv[:3] not in (["gh", "pr", "list"], ["gh", "pr", "view"]) and argv[:4] != ["gh", "api", "--method", "GET"]:
        return None, f"refused non-read gh call {' '.join(argv[:3])}"
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=GH_CALL_TIMEOUT_S, env=env)
    except FileNotFoundError:
        return None, "gh not installed"
    except subprocess.TimeoutExpired:
        return None, f"gh timed out after {GH_CALL_TIMEOUT_S:g}s"
    except OSError as exc:
        return None, f"gh failed ({type(exc).__name__})"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return None, f"gh exited {proc.returncode}: {(err[0] if err else 'no stderr')[:120]}"
    if len(proc.stdout or "") > MAX_GH_OUTPUT_BYTES:
        return None, f"gh output over {MAX_GH_OUTPUT_BYTES} bytes refused"
    return proc.stdout, None


# --------------------------------------------------------------------------------------------- release health


def release_health(deploy_state_dir: Path | None = None) -> dict[str, Any]:
    """The last deploy receipt: served SHA, when, and whether its health check passed. Never raises."""
    d = Path(deploy_state_dir or Path.home() / ".local" / "state" / "cio-phase2-exact-main")
    try:
        rec = json.loads((d / "deploy_receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sha": None, "ok": None, "at": None, "basis": "deploy_receipt.json unreadable"}
    ok = bool(rec.get("ok")) and str(rec.get("health") or "").lower() == "ok" and not rec.get("rolled_back")
    return {
        "sha": rec.get("deployed_sha"),
        "ok": ok,
        "health": rec.get("health"),
        "at": LC._norm_iso(rec.get("at")),
        "basis": "deploy_receipt.json",
    }


# --------------------------------------------------------------------------------------------- worklog tail


def latest_worklog_line(path: str | None) -> str | None:
    """The newest agent-written timestamped line of a worklog, from a bounded tail read (never the whole file)."""
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - WORKLOG_TAIL_BYTES))
            text = fh.read(WORKLOG_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    best: tuple[str, str] | None = None
    for ln in text.splitlines():
        if ln.rstrip().endswith("(auto)"):
            continue
        stamps = _TS_RE.findall(ln) or re.findall(r"_\((?:added|done) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\)_", ln)
        if not stamps:
            continue
        ts = max(stamps)
        clean = re.sub(r"\s*_\((?:added|done) [^)]*\)_", "", ln)
        clean = _TS_RE.sub("", clean).strip().lstrip("-").strip()
        clean = re.sub(r"^\[(x| )\]\s*", lambda m: "done: " if m.group(1) == "x" else "planned: ", clean)
        if clean and (best is None or ts >= best[0]):
            best = (ts, clean[:240])
    return best[1] if best else None


# --------------------------------------------------------------------------------------------- derivation


def _cells(stage: str, rag: str, label: str, evidence: Mapping[str, str], times: Mapping[str, str | None]) -> list:
    i = STAGES.index(stage)
    out = []
    for j, s in enumerate(STAGES):
        if j < i:
            c_rag, c_label = "green", "done"
        elif j == i:
            c_rag, c_label = rag, label
        else:
            c_rag, c_label = "grey", ""
        out.append(
            {
                "stage": s,
                "rag": c_rag,
                "label": c_label,
                "at": times.get(s),
                "evidence": evidence.get(s) or ("" if c_rag == "grey" else STAGE_HELP[s]),
            }
        )
    return out


def _who(claims: list[Mapping[str, Any]], task: Mapping[str, Any] | None, pr: Mapping[str, Any] | None) -> dict:
    if task and OPERATOR_PREFIX_RE.match(str(task.get("title") or "")) and not claims:
        return {"kind": "operator", "label": "OPERATOR", "vendor": "operator", "agent": None, "session": None}
    if claims:
        c = claims[0]
        agents = sorted({f"{x.get('vendor') or '?'}/{x.get('agent') or str(x.get('session') or '?')[:14]}" for x in claims})
        label = agents[0] + (f" · {len(claims)} claims" if len(claims) > 1 else "")
        return {
            "kind": "agent",
            "label": label,
            "vendor": c.get("vendor"),
            "agent": c.get("agent"),
            "session": c.get("session"),
        }
    owner = (task or {}).get("owner") if task else None
    if isinstance(owner, Mapping) and owner:
        return {
            "kind": "agent",
            "label": f"{owner.get('vendor') or '?'}/{owner.get('agent') or '?'}",
            "vendor": owner.get("vendor"),
            "agent": owner.get("agent"),
            "session": owner.get("session"),
        }
    if pr and pr.get("author"):
        return {"kind": "github", "label": f"github:{pr['author']}", "vendor": "github", "agent": None, "session": None}
    return {"kind": "none", "label": "nobody yet", "vendor": None, "agent": None, "session": None}


def derive(
    *,
    task: Mapping[str, Any] | None = None,
    claims: list[Mapping[str, Any]] | None = None,
    pr: Mapping[str, Any] | None = None,
    design: Mapping[str, Any] | None = None,
    batches: Mapping[int, Mapping[str, Any]] | None = None,
    health: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    held: Mapping[str, Any] | None = None,
    queue_position: int | None = None,
) -> dict[str, Any]:
    """One work item's stage, cells, RAG, blocker and next step from its facts. Pure; the tests drive it directly."""
    now = now or _utc_now()
    claims = [c for c in (claims or []) if c]
    batches = batches or {}
    stale_s = stale_hours * 3600
    lead = claims[0] if claims else None
    lc_stages: dict[str, str] = {}
    for c in claims:
        for k, v in (c.get("stages") or {}).items():
            if v and (k not in lc_stages or v < lc_stages[k]):
                lc_stages[k] = v
    pr_num = (pr or {}).get("number") or next((c.get("pr_number") for c in claims if c.get("pr_number")), None)
    pr_state = (pr or {}).get("state") or next((c.get("pr_state") for c in claims if c.get("pr_state")), None)
    ci = (pr or {}).get("ci") or next((c.get("ci") for c in claims if c.get("ci")), None) or {}
    ci_state = ci.get("state") or "unknown"
    released = (pr or {}).get("released") or next((c.get("released") for c in claims if c.get("released")), None)
    merged_at = (pr or {}).get("merged_at") or lc_stages.get("merged")
    title = str((task or {}).get("title") or (pr or {}).get("title") or (lead or {}).get("task") or "")
    title = title or str((design or {}).get("title") or "")
    is_batch = bool(pr and BATCH_BRANCH_RE.match(str(pr.get("branch") or "")))
    batch_of = None
    excluded_reason = None
    if pr_num:
        for bn, b in batches.items():
            if int(pr_num) in (b.get("members") or []) and int(pr_num) != int(bn):
                batch_of = b
            if int(pr_num) in (b.get("excluded") or {}):
                excluded_reason = b["excluded"][int(pr_num)]
    hb = _max_iso(*(c.get("heartbeat_at") for c in claims))
    wl_last = _max_iso(*(((c.get("worklog") or {}).get("last_entry_at")) for c in claims))
    last_activity = _max_iso(hb, wl_last, (pr or {}).get("updated_at"), (task or {}).get("taken_at"))
    idle_s = None if _parse(last_activity) is None else (now - _parse(last_activity)).total_seconds()  # type: ignore[operator]
    hb_age_s = None if _parse(hb) is None else (now - _parse(hb)).total_seconds()  # type: ignore[operator]
    wl_next = next(
        (
            str((c.get("worklog") or {}).get("next_step"))
            for c in claims
            if (c.get("worklog") or {}).get("next_step")
            and not str((c.get("worklog") or {}).get("next_step")).startswith("(not set")
        ),
        None,
    )
    wl_blockers = sum(int((c.get("worklog") or {}).get("blockers") or 0) for c in claims)
    times: dict[str, str | None] = {
        "proposed": (task or {}).get("created_at") or (pr or {}).get("created_at") or (lead or {}).get("started_at"),
        "approved": (task or {}).get("created_at") or (lead or {}).get("started_at") or (pr or {}).get("created_at"),
        "queued": (task or {}).get("created_at") or (lead or {}).get("started_at") or (pr or {}).get("created_at"),
        "claimed": lc_stages.get("claimed") or (lead or {}).get("started_at") or (task or {}).get("taken_at"),
        "building": lc_stages.get("building"),
        "pr_open": lc_stages.get("pr_open") or (pr or {}).get("created_at"),
        "ci": ci.get("completed_at") or lc_stages.get("ci_green"),
        "in_batch": None,
        "merged": merged_at,
        "released": (released or {}).get("at") or lc_stages.get("released"),
        "verified": None,
    }
    ev: dict[str, str] = {}
    if task:
        ev["queued"] = f"task {task.get('task_id')} on the task board since {task.get('created_at')}"
        ev["approved"] = "registered on the task board (registration is the approval to start)"
    elif pr and not claims:
        for s in ("proposed", "approved", "queued", "claimed", "building"):
            ev[s] = f"not tracked: PR #{pr_num} opened without a task or claim"
    if lead:
        ev["claimed"] = f"claim {lead.get('claim_id')} at {lead.get('started_at')}"
    if lc_stages.get("building"):
        ev["building"] = f"declared building at {lc_stages['building']}"
    if pr_num:
        ev["pr_open"] = f"PR #{pr_num} opened {times['pr_open'] or '?'}"
    if ci_state == "green":
        ev["ci"] = f"required checks green ({ci.get('total') or '?'}) at {ci.get('completed_at') or '?'}"

    blocker = None
    next_owner, next_text = "agent", ""
    stale = False
    # --- stage ---------------------------------------------------------------------------------------------------
    t_status = (task or {}).get("status")
    verified = False
    if released and health and health.get("ok") and health.get("sha"):
        r_at, h_at = _parse(released.get("at")), _parse(health.get("at"))
        verified = r_at is None or h_at is None or h_at >= r_at
    if released and verified:
        stage, rag, label = "verified", "green", "live"
        times["verified"] = (health or {}).get("at")
        ev["released"] = f"{released.get('basis') or 'release receipt'} ({str(released.get('sha') or '')[:9]})"
        ev["verified"] = f"served {str((health or {}).get('sha') or '')[:9]} contains the merge; deploy health ok"
        next_owner, next_text = "agent", "Nothing: live and verified"
    elif released:
        stage = "released"
        ev["released"] = f"{released.get('basis') or 'release receipt'} ({str(released.get('sha') or '')[:9]})"
        if health and health.get("ok") is False:
            rag, label = "red", "health failed"
            blocker = f"deploy health {health.get('health') or 'not ok'} at {health.get('at') or '?'}"
            next_owner, next_text = "agent", "Agent: investigate the failed deploy health check"
        else:
            rag, label = "amber", "verify"
            next_owner, next_text = "agent", "Agent: verify live (served SHA + deploy health)"
    elif merged_at or pr_state == "merged":
        stage, rag, label = "merged", "amber", "awaiting release"
        ev["merged"] = f"merged {merged_at or '?'}; not in a release receipt yet"
        next_owner, next_text = "agent", "Agent: ship it in the next release (promote main)"
    elif pr_num and pr_state == "closed":
        stage, rag, label = "pr_open", "red", "closed"
        blocker = f"PR #{pr_num} closed without merging"
        next_owner, next_text = "agent", "Agent: reopen the PR or release the claim with a summary"
    elif pr_num and ((pr or {}).get("draft") or (lead or {}).get("pr_draft")):
        draft_hold = bool(HOLD_RE.search(title))
        stage, rag, label = ("proposed", "amber", "draft held") if draft_hold else ("pr_open", "amber", "draft")
        ev[stage] = f"draft PR #{pr_num}" + (" held for the operator" if draft_hold else "")
        if draft_hold:
            next_owner, next_text = "operator", f"Operator: approve or reject draft #{pr_num}"
        else:
            next_owner, next_text = "agent", f"Agent: mark #{pr_num} ready for review"
    elif pr_num and ci_state == "green":
        if is_batch:
            stage, rag, label = "in_batch", "amber", "merge batch"
            ev["in_batch"] = f"release batch PR #{pr_num}; CI green"
            next_owner, next_text = "operator", f"Operator: merge batch #{pr_num}"
        elif batch_of is not None:
            stage = "in_batch"
            bci = (batch_of.get("ci") or {}).get("state")
            times["in_batch"] = None
            ev["in_batch"] = f"in release batch #{batch_of.get('number')} (its CI: {bci or 'unknown'})"
            label = f"#{batch_of.get('number')}"
            rag = "amber"
            if bci == "failing":
                blocker = f"batch #{batch_of.get('number')} CI failing: " + ", ".join(
                    (batch_of.get("ci") or {}).get("failing") or []
                )
                next_owner, next_text = "agent", f"Agent: fix batch #{batch_of.get('number')} CI"
            elif bci == "green":
                next_owner, next_text = "operator", f"Operator: merge batch #{batch_of.get('number')}"
            else:
                next_owner, next_text = "agent", f"Agent: wait for batch #{batch_of.get('number')} CI"
        elif excluded_reason is not None:
            stage, rag, label = "in_batch", "amber", "operator merge"
            ev["in_batch"] = f"excluded from the batch: {excluded_reason}"
            blocker = f"excluded from the batch: {excluded_reason}"
            next_owner, next_text = "operator", f"Operator: merge #{pr_num}"
        elif (pr or {}).get("base") and (pr or {}).get("base") != "main":
            stage, rag, label = "in_batch", "amber", "stacked"
            ev["in_batch"] = f"CI green; stacked on {(pr or {}).get('base')}: goes in with (or after) its base"
            next_owner, next_text = "agent", f"Agent: retarget #{pr_num} to main once {(pr or {}).get('base')} merges"
        else:
            stage, rag, label = "in_batch", "amber", "waiting for batch"
            ev["in_batch"] = "CI green, not in any open release batch: waiting for batch"
            next_owner, next_text = "agent", f"Coordinator: add #{pr_num} to the next release batch"
    elif pr_num and ci_state == "failing":
        stage, rag = "ci", "red"
        failing = ", ".join(ci.get("failing") or []) or "checks"
        stale = idle_s is not None and idle_s > stale_s
        label = "stale" if stale else f"{len(ci.get('failing') or []) or ''} fail".strip()
        ev["ci"] = f"failing: {failing}" + (f"; no activity for {idle_s / 3600:.1f} h" if stale and idle_s else "")
        blocker = f"CI failing: {failing}"
        next_owner, next_text = "agent", f"Agent: fix {failing} on #{pr_num}" + (" (take over: stale)" if stale else "")
    elif pr_num and ci_state == "pending":
        stage, rag, label = "ci", "amber", "running"
        if ci.get("total") and len(ci.get("pending") or []) >= int(ci.get("total") or 0):
            label = "not run"
        ev["ci"] = "pending: " + ", ".join(ci.get("pending") or [])
        next_owner, next_text = "agent", f"Agent: wait for CI on #{pr_num}"
    elif pr_num:
        stage, rag, label = "pr_open", "amber", "CI not seen"
        ev["pr_open"] = f"PR #{pr_num} open; CI state not observed yet"
        next_owner, next_text = "agent", f"Agent: check CI on #{pr_num}"
    elif claims:
        building = bool(lc_stages.get("building"))
        stage = "building" if building else "claimed"
        stale = all(c.get("state") == "stale" for c in claims) or (hb_age_s is not None and hb_age_s > stale_s)
        if stale:
            rag, label = "red", "stale"
            blocker = f"no heartbeat for {hb_age_s / 3600:.1f} h" if hb_age_s is not None else "no heartbeat"
            ev[stage] = f"stale: {blocker}, no PR yet"
            next_owner, next_text = "agent", f"Agent: take over {lead.get('claim_id')} (agent_claim.py takeover)"  # type: ignore[union-attr]
        else:
            rag, label = "amber", "building" if building else "not started"
            wl = (lead or {}).get("worklog") or {}
            plan = f" ({wl.get('plan_done')}/{wl.get('plan_total')})" if wl.get("plan_total") else ""
            next_text = f"Agent: build{plan}, then open a PR" if building else "Agent: start building (stage building)"
    elif task and t_status == "done":
        stage, rag, label = "verified", "green", "done"
        times["verified"] = task.get("done_at")
        ev["verified"] = f"task marked done {task.get('done_at') or '?'} (no PR on this task)"
        next_owner, next_text = "agent", "Nothing: done"
    elif task:
        stage, rag, label = "queued", "amber", "not started"
        deps = list(task.get("blocked_by") or [])
        is_op = bool(OPERATOR_PREFIX_RE.match(str(task.get("title") or "")))
        if deps:
            rag, label = "red", "blocked"
            blocker = "waits for " + ", ".join(deps)
            ev["queued"] = f"blocked by {', '.join(deps)}"
            next_owner, next_text = "agent", f"After {deps[0]} is done: " + (
                "operator acts" if is_op else f"agent_claim.py take {task.get('task_id')}"
            )
            if is_op:
                next_owner = "operator"
        elif is_op:
            next_owner, next_text = "operator", "Operator: " + OPERATOR_PREFIX_RE.sub("", str(task.get("title") or ""))
        else:
            next_owner, next_text = "agent", f"Agent: agent_claim.py take {task.get('task_id')}"
    elif design:
        if design.get("awaiting"):
            stage, rag, label = "proposed", "amber", "awaiting operator"
            ev["proposed"] = f"{design.get('kind') or 'design'} {design.get('id')}: {design.get('approval') or 'awaiting operator'}"
            next_owner, next_text = "operator", f"Operator: approve or reject {design.get('id')}"
        else:
            stage, rag, label = "approved", "amber", "no tasks"
            ev["approved"] = f"{design.get('id')} approved; no task registered on the task board"
            next_owner, next_text = "agent", f"Agent: register tasks (agent_claim.py task add --id {design.get('id')}-T1 ...)"
    else:
        stage, rag, label = "queued", "amber", ""
    if wl_next and stage in ("claimed", "building", "pr_open", "ci") and not held:
        wl_next = re.sub(r"\s*_\(.*?\)_\s*$", "", wl_next).strip()[:240]
        next_text = wl_next
        next_owner = "operator" if re.match(r"^\s*operator\b", wl_next, re.I) else next_owner
        if not re.match(r"^\s*(operator|agent|coordinator)\b", wl_next, re.I):
            next_text = ("Operator: " if next_owner == "operator" else "Agent: ") + wl_next
    if wl_blockers and not blocker:
        blocker = f"{wl_blockers} open blocker(s) in the worklog"
        if rag == "amber":
            rag = "red"
            label = "blocked"
    if queue_position and stage == "in_batch" and label == "waiting for batch":
        label = f"next batch #{queue_position}"
        ev["in_batch"] = f"CI green; the operator queued it for the next batch (position {queue_position})"
        next_owner, next_text = "agent", f"Coordinator: build the next batch (#{pr_num} is queued at {queue_position})"
    if held and stage not in ("merged", "released", "verified"):
        label = "held"
        blocker = f"on hold by {held.get('by') or 'operator'} since {held.get('at') or '?'}" + (
            f": {held['reason']}" if held.get("reason") else ""
        )
        next_owner, next_text = "operator", "Operator: unhold when ready (agents and the batch builder skip it)"
    stage_since = {
        "proposed": times["proposed"],
        "approved": times["approved"],
        "queued": times["queued"],
        "claimed": times["claimed"],
        "building": times["building"] or times["claimed"],
        "pr_open": times["pr_open"],
        "ci": (pr or {}).get("updated_at") or times["pr_open"],
        "in_batch": ci.get("completed_at") or (pr or {}).get("updated_at") or times["pr_open"],
        "merged": times["merged"],
        "released": times["released"],
        "verified": times["verified"],
    }[stage]
    cells = _cells(stage, rag, label, ev, times)
    return {
        "stage": stage,
        "rag": rag,
        "label": label,
        "stale": stale,
        "cells": cells,
        "blocker": blocker,
        "next": {"owner": next_owner, "text": next_text or "—"},
        "finished": stage == "verified",
        "title": title,
        "pr_number": int(pr_num) if pr_num else None,
        "batch": (batch_of or {}).get("number") if batch_of else (int(pr_num) if is_batch and pr_num else None),
        "is_batch": is_batch,
        "waiting_for_batch": stage == "in_batch" and (label == "waiting for batch" or label.startswith("next batch")),
        "held": dict(held) if held else None,
        "queue_position": queue_position,
        "when": {
            "started": times["claimed"] or times["pr_open"] or times["queued"],
            "last_activity": last_activity,
            "stage_since": stage_since,
            "stage_age_minutes": _age_min(stage_since, now),
            "idle_minutes": None if idle_s is None else round(idle_s / 60, 1),
        },
    }


# --------------------------------------------------------------------------------------------- actions


_SCRIPT_INDEX: dict[str, str] | None = None
_SH_RE = re.compile(r"\b([A-Za-z0-9_.-]+\.(?:sh|py))\b")


def _script_index(root: Path | None = None) -> dict[str, str]:
    """basename -> repo-relative path for scripts/**.sh|py (built once, bounded)."""
    global _SCRIPT_INDEX
    if _SCRIPT_INDEX is None:
        base = Path(root or Path(__file__).resolve().parents[2])
        idx: dict[str, str] = {}
        for i, pth in enumerate(sorted((base / "scripts").rglob("*"))):
            if i > 20000:
                break
            if pth.suffix in (".sh", ".py") and pth.name not in idx:
                idx[pth.name] = str(pth.relative_to(base))
        _SCRIPT_INDEX = idx
    return _SCRIPT_INDEX


def operator_command(item: Mapping[str, Any], pr: Mapping[str, Any] | None, task: Mapping[str, Any] | None,
                     design: Mapping[str, Any] | None, index: Callable[[], dict[str, str]] = _script_index) -> str | None:
    """The exact command the operator runs for an operator-owned next step (copied client-side), else None."""
    nxt = item.get("next") or {}
    if nxt.get("owner") != "operator":
        return None
    text = str(nxt.get("text") or "")
    num = item.get("pr_number")
    sha = (pr or {}).get("head_sha")
    if num and re.search(r"\bmerge\b", text, re.I):
        return f"gh pr merge {num} --merge" + (f" --match-head-commit {sha}" if sha else "")
    if task:
        tid = task.get("task_id")
        hit = _SH_RE.search(str(task.get("title") or ""))
        path = index().get(hit.group(1)) if hit else None
        run = (f"bash {path}" if path.endswith(".sh") else f"python3 {path}") if path else None
        done = f'python3 scripts/agent_claim.py task done {tid} --summary "<what you did>"'
        return f"{run} && {done}" if run else f"python3 scripts/agent_claim.py task show {tid}"
    if design and design.get("path"):
        return f"${{EDITOR:-nano}} {design['path']}  # status: APPROVED, with your words and the date"
    if num:
        return f"gh pr view {num} --web"
    return None


def item_actions(item: Mapping[str, Any], task: Mapping[str, Any] | None, claims: list[Mapping[str, Any]],
                 queued_prs: list[int], held_prs: Mapping[str, Any]) -> dict[str, Any]:
    """Which Tier 1 commands the UI offers on this card (the endpoint re-validates every one)."""
    num = item.get("pr_number")
    acts: list[str] = ["note"]
    if task:
        acts.append("set_priority")
        acts.append("unhold" if task.get("held") else "hold")
        if task.get("status") == "free":
            acts.append("task_split")
    elif num:
        acts.append("unhold" if str(num) in held_prs else "hold")
    if num and int(num) in queued_prs:
        acts.append("batch_remove")
    elif item.get("waiting_for_batch") and str(num) not in held_prs:
        acts.append("batch_add")
    stale_claims = [
        c.get("claim_id")
        for c in claims
        if c.get("state") == "stale" and c.get("status") == "active"
        and (c.get("stage") in ("claimed", "building") or (c.get("stage") == "pr_open" and (c.get("ci") or {}).get("state") == "failing"))
    ]
    if item.get("stale") and stale_claims:
        acts.append("release_stale_claim")
    return {"available": acts, "stale_claims": stale_claims}


# --------------------------------------------------------------------------------------------- grouping


def _files_of(task: Mapping | None, claims: list[Mapping], pr: Mapping | None) -> list[str]:
    out: list[str] = []
    for src in [*(c.get("paths") or [] for c in claims), (task or {}).get("areas") or []]:
        for f in src:
            if f not in out:
                out.append(str(f))
    return out


def build_items(
    *,
    tasks: list[Mapping[str, Any]],
    claims: list[Mapping[str, Any]],
    census: Mapping[str, Any] | None,
    awaiting: list[Mapping[str, Any]] | None = None,
    health: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    latest_line: Callable[[str | None], str | None] = latest_worklog_line,
    queue: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Group the sources into work items (task > PR > claim > design) and derive each one."""
    now = now or _utc_now()
    census = census or {}
    batches = {int(k): v for k, v in (census.get("batches") or {}).items()}
    open_by = {int(p["number"]): p for p in census.get("open") or [] if p.get("number")}
    merged_by = {int(p["number"]): p for p in census.get("merged") or [] if p.get("number")}
    live_claims = [c for c in claims if c.get("state") != "abandoned" and c.get("stage") != "abandoned"]
    by_id = {c["claim_id"]: c for c in live_claims if c.get("claim_id")}
    used: set[str] = set()
    used_prs: set[int] = set()
    groups: list[dict[str, Any]] = []

    def pr_for(num: Any) -> Mapping[str, Any] | None:
        if not num:
            return None
        return open_by.get(int(num)) or merged_by.get(int(num))

    for t in tasks:
        if t.get("status") == "split":
            continue
        cs = [by_id[t["claim_id"]]] if t.get("claim_id") in by_id else []
        num = next((c.get("pr_number") for c in cs if c.get("pr_number")), None)
        if num:
            cs += [c for c in live_claims if c.get("pr_number") == num and c not in cs]
            used_prs.add(int(num))
        used.update(c["claim_id"] for c in cs)
        groups.append({"key": t["task_id"], "kind": "task", "task": t, "claims": cs, "pr": pr_for(num)})
    by_pr: dict[int, list[Mapping[str, Any]]] = {}
    for c in live_claims:
        if c["claim_id"] in used:
            continue
        if c.get("pr_number"):
            by_pr.setdefault(int(c["pr_number"]), []).append(c)
        else:
            # finished claims without a PR are history, not work in flight
            if c.get("state") == "done" or c.get("status") == "done":
                continue
            groups.append({"key": c["claim_id"], "kind": "claim", "task": None, "claims": [c], "pr": None})
    for num, cs in by_pr.items():
        if num in used_prs:
            continue
        used_prs.add(num)
        groups.append({"key": f"PR-{num}", "kind": "pr", "task": None, "claims": cs, "pr": pr_for(num)})
    for num, p in open_by.items():
        if num not in used_prs:
            used_prs.add(num)
            groups.append({"key": f"PR-{num}", "kind": "pr", "task": None, "claims": [], "pr": p})
    for num, p in merged_by.items():
        if num not in used_prs:
            used_prs.add(num)
            groups.append({"key": f"PR-{num}", "kind": "pr", "task": None, "claims": [], "pr": p})
    for d in awaiting or []:
        groups.append(
            {"key": str(d.get("id")), "kind": d.get("kind") or "design", "task": None, "claims": [], "pr": None,
             "design": {**d, "awaiting": True}}
        )  # fmt: skip

    queue = queue or {}
    held_prs = {str(k): v for k, v in (queue.get("held_prs") or {}).items()}
    queued_prs = [int(e.get("pr")) for e in queue.get("next_batch") or [] if str(e.get("pr") or "").isdigit()]
    pr_notes = queue.get("pr_notes") or {}
    items = []
    for g in groups[:MAX_ITEMS]:
        task, cs, pr = g["task"], g["claims"], g["pr"]
        num0 = (pr or {}).get("number") or next((c.get("pr_number") for c in cs if c.get("pr_number")), None)
        held = (task or {}).get("held") or (held_prs.get(str(num0)) if num0 else None)
        qpos = queued_prs.index(int(num0)) + 1 if num0 and int(num0) in queued_prs else None
        d = derive(
            task=task, claims=cs, pr=pr, design=g.get("design"), batches=batches, health=health, now=now,
            stale_hours=stale_hours, held=held, queue_position=qpos,
        )  # fmt: skip
        d["next"]["command"] = operator_command(d, pr, task, g.get("design"))
        d["actions"] = item_actions(d, task, cs, queued_prs, held_prs)
        lead = cs[0] if cs else None
        wl = (lead or {}).get("worklog") or {}
        files = _files_of(task, cs, pr)
        pr_num = d["pr_number"]
        pr_url = (pr or {}).get("url") or next((c.get("pr_url") for c in cs if c.get("pr_url")), None)
        design_id = (task or {}).get("design_id") or ((g.get("design") or {}).get("id") if g.get("design") else None)
        if not design_id:
            m = re.search(r"DSN-\d{8}-[a-z0-9-]+?(?=-P\d|\b)", " ".join([str(d["title"]), *(str(c.get("task") or "") for c in cs)]))
            design_id = m.group(0) if m else None
        items.append(
            {
                "id": g["key"],
                "kind": g["kind"],
                **d,
                "who": _who(cs, task, pr),
                "what": {
                    "title": d["title"] or g["key"],
                    "design_id": design_id,
                    "task_id": (task or {}).get("task_id"),
                    "pr_number": pr_num,
                    "pr_url": pr_url,
                    "batch": d["batch"],
                    "kind": (task or {}).get("kind"),
                    "priority": (task or {}).get("priority"),
                },
                "where": {
                    "branch": (pr or {}).get("branch") or (lead or {}).get("branch"),
                    "worktree": (lead or {}).get("worktree"),
                    "file_count": len(files),
                    "files": files[:MAX_FILES_SHOWN],
                },
                "how": {
                    "plan_done": wl.get("plan_done"),
                    "plan_total": wl.get("plan_total"),
                    "latest": latest_line(wl.get("path")) if wl.get("exists") else None,
                    "worklog": bool(wl.get("exists")),
                    "claim_ids": [c.get("claim_id") for c in cs],
                    "operator_note": (list(pr_notes.get(str(pr_num)) or [None])[-1]) if pr_num else None,
                },
                "links": {
                    "pr": pr_url,
                    "ci": f"{pr_url}/checks" if pr_url else None,
                    "diff": f"{pr_url}/files" if pr_url else None,
                    "worklog_claim": next((c.get("claim_id") for c in cs if (c.get("worklog") or {}).get("exists")), None),
                },
            }
        )
    order = {"red": 0, "amber": 1, "green": 2, "grey": 3}
    items.sort(
        key=lambda it: (
            it["finished"],
            order.get(it["rag"], 9),
            it["next"]["owner"] != "operator",
            -STAGES.index(it["stage"]),
            str(it["id"]),
        )
    )
    return items


def summarize(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    live = [i for i in items if not i.get("finished")]
    return {
        "counts": {s: sum(1 for i in live if i["stage"] == s) for s in STAGES},
        "red": sum(1 for i in live if i["rag"] == "red"),
        "amber": sum(1 for i in live if i["rag"] == "amber"),
        "needs_me": sum(1 for i in live if (i.get("next") or {}).get("owner") == "operator"),
        "waiting_for_batch": sum(1 for i in live if i.get("waiting_for_batch")),
        "finished": len(items) - len(live),
        "total": len(items),
    }


# --------------------------------------------------------------------------------------------- service


class WorkPipeline:
    """The served read model. ``view()`` never blocks on GitHub and rebuilds at most once per ``ttl``."""

    def __init__(
        self,
        *,
        claims_dir: Path | None = None,
        census: PrCensus | None = None,
        sources: Callable[[], dict[str, Any]] | None = None,
        health: Callable[[], dict[str, Any]] | None = None,
        ttl: float = REFRESH_S,
        now: Callable[[], datetime] = _utc_now,
    ):
        self.claims_dir = claims_dir
        self.census = census or PrCensus(release=LC.ReleaseReader())
        self.sources = sources or self._read_sources
        self.health = health or release_health
        self.now = now
        try:
            from scripts.lib.design_registry import _Cached
        except ImportError:
            from lib.design_registry import _Cached  # type: ignore[no-redef]
        self.cached = _Cached(self._build, ttl)
        self.ttl = ttl

    def _read_sources(self) -> dict[str, Any]:
        try:
            from scripts.lib import agent_claim_board as B
            from scripts.lib import design_registry as DR
        except ImportError:
            from lib import agent_claim_board as B  # type: ignore[no-redef]
            from lib import design_registry as DR  # type: ignore[no-redef]
        view = B.board_view(self.claims_dir, include_finished=True)
        try:
            awaiting = DR.work_board().designs().get("awaiting_approval") or []
        except Exception:  # noqa: BLE001 - designs are additive
            awaiting = []
        try:
            from scripts.lib import work_pipeline_commands as WPC
        except ImportError:
            from lib import work_pipeline_commands as WPC  # type: ignore[no-redef]
        return {
            "queue": WPC.read_queue(self.claims_dir or view.get("claims_dir")),
            "claims": view.get("claims") or [],
            "tasks": (view.get("task_board") or {}).get("tasks") or [],
            "awaiting": awaiting,
            "stale_hours": view.get("stale_after_hours") or DEFAULT_STALE_HOURS,
            "lifecycle": view.get("lifecycle"),
        }

    def _build(self) -> dict[str, Any]:
        now = self.now()
        src = self.sources()
        census, meta = self.census.snapshot()
        health = self.health()
        items = build_items(
            tasks=src.get("tasks") or [],
            claims=src.get("claims") or [],
            census=census,
            awaiting=src.get("awaiting") or [],
            health=health,
            now=now,
            stale_hours=float(src.get("stale_hours") or DEFAULT_STALE_HOURS),
            queue=src.get("queue"),
        )
        q = src.get("queue") or {}
        return {
            "batch_queue": {
                "next_batch": [e.get("pr") for e in q.get("next_batch") or []],
                "held_prs": sorted(int(k) for k in (q.get("held_prs") or {})),
                "updated_at": q.get("updated_at"),
            },
            "schema": SCHEMA,
            "as_of": _iso(now),
            "stages": list(STAGES),
            "stage_label": dict(STAGE_LABEL),
            "stage_help": dict(STAGE_HELP),
            "summary": summarize(items),
            "items": items,
            "sources": {
                "census": meta,
                "census_age_s": None
                if not meta.get("refreshed_at")
                else round((now - _parse(meta["refreshed_at"])).total_seconds()),  # type: ignore[operator]
                "open_prs": None if census is None else len(census.get("open") or []),
                "merged_prs": None if census is None else len(census.get("merged") or []),
                "batches": None if census is None else sorted((census.get("batches") or {}).keys()),
                "claims": len(src.get("claims") or []),
                "tasks": len(src.get("tasks") or []),
                "served": health,
                "lifecycle": src.get("lifecycle"),
            },
            "stale_hours": float(src.get("stale_hours") or DEFAULT_STALE_HOURS),
            "refresh_s": self.ttl,
        }

    def view(self, *, background: bool = True) -> dict[str, Any]:
        self.census.kick(background=background)
        return self.cached.get()


_PIPELINE: WorkPipeline | None = None
_P_LOCK = threading.Lock()


def work_pipeline() -> WorkPipeline:
    global _PIPELINE
    with _P_LOCK:
        if _PIPELINE is None:
            _PIPELINE = WorkPipeline()
        return _PIPELINE
