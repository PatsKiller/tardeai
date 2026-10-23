"""Design registry + Work board read model: ALL queued work, broken into tasks (operator 2026-10-23).

Design ids (AGENTS.md 20.0.0 §28): a design is ``DSN-<YYYYMMDD>-<slug>``, a phase ``DSN-…-P<n>``, a task
``DSN-…-P<n>-T<m>``. Tasks are what agents claim (``agent_claim.py take DSN-…-P2-T3``). The id flows into the claim,
the worklog, the branch name, the PR title and the commit trailer ``Design-Task: <id>``.

Store (one): ``docs/designs/<design-id>.md``, YAML front matter between ``---`` lines, then free text::

    ---
    id: DSN-20261021-release-train
    title: Release train
    status: IN_PROGRESS            # PROPOSED | APPROVED | IN_PROGRESS | DONE | LIVE | HELD
    approval: awaiting operator    # optional: awaiting operator | approved | not needed
    source: docs/ops/packets/release-train-20261021/README.md
    phases:
      - id: DSN-20261021-release-train-P0
        title: ...
        status: DONE
        tasks:
          - id: DSN-20261021-release-train-P0-T1
            title: ...
            status: DONE          # optional; a task registered on the task board overrides it (owner, stage)
            areas: [scripts/x.py]
    ---

The registry is reviewed text in git (a PR changes it). The task board (``<claims_dir>/tasks``) is where agents take
work; ``agent_claim.py task add --id DSN-…-P<n>-T<m>`` registers a design task there. This module joins the two
with the claims and open PRs into the Work board.

Reads are bounded: one in-process cache per view, rebuilt at most once per ``REFRESH_S`` (30 s) with single-flight (a
concurrent caller gets the cached value, never a second rebuild); design files are re-parsed only when their
mtime/size changes. GitHub (open PRs) is read in a background thread through ``agent_claim_lifecycle.GitHubReader``
(``gh api --method GET`` only). Stdlib + PyYAML (safe_load). AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.lib import agent_claim_board as B
    from scripts.lib import agent_claim_lifecycle as LC
    from scripts.lib import agent_task_board as TB
except ImportError:  # scripts/ on sys.path (api_v2)
    from lib import agent_claim_board as B  # type: ignore[no-redef]
    from lib import agent_claim_lifecycle as LC  # type: ignore[no-redef]
    from lib import agent_task_board as TB  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
DESIGNS_REL = "docs/designs"
STATUSES = ("PROPOSED", "APPROVED", "IN_PROGRESS", "DONE", "LIVE", "HELD")
WORK_STAGES = ("open", "claimed", "in_progress", "in_review", "merged", "live")
DESIGN_ID_RE = re.compile(r"^DSN-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*$")
PHASE_ID_RE = re.compile(r"^(DSN-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*)-P[0-9]{1,3}$")
REFRESH_S = 30.0
MAX_DESIGN_BYTES = 256 * 1024
MAX_DESIGNS = 300
MAX_PACKETS = 400
_STATUS_LINE_RE = re.compile(r"^\s*Status:\s*(.+?)\s*$", re.I)

STAGE_FROM_CLAIM = {
    "claimed": "claimed",
    "building": "in_progress",
    "pr_open": "in_review",
    "ci_green": "in_review",
    "merged": "merged",
    "released": "live",
    "abandoned": "open",
}


class DesignError(ValueError):
    """A design file that does not parse or validate. Reported per file, never fatal to the board."""


# --------------------------------------------------------------------------------------------- parse


def split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        raise DesignError("no YAML front matter (file must start with ---)")
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        raise DesignError("front matter not closed with ---")
    head = parts[0][3:]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    return head, body


def parse_design(text: str, *, stem: str | None = None) -> dict[str, Any]:
    import yaml  # PyYAML is in the release venv (config/*.yaml readers)

    head, _body = split_front_matter(text)
    try:
        doc = yaml.safe_load(head) or {}
    except yaml.YAMLError as exc:
        raise DesignError(f"front matter is not YAML: {str(exc).splitlines()[0]}") from exc
    if not isinstance(doc, dict):
        raise DesignError("front matter must be a mapping")
    did = str(doc.get("id") or "")
    if not DESIGN_ID_RE.match(did):
        raise DesignError(f"id {did!r} is not DSN-<YYYYMMDD>-<slug>")
    if stem is not None and stem != did:
        raise DesignError(f"file name {stem!r} must equal the id {did!r}")
    st = str(doc.get("status") or "PROPOSED").upper()
    if st not in STATUSES:
        raise DesignError(f"status {st!r} not one of {', '.join(STATUSES)}")
    phases_out = []
    for i, ph in enumerate(doc.get("phases") or []):
        if not isinstance(ph, dict):
            raise DesignError(f"phase {i} is not a mapping")
        pid = str(ph.get("id") or "")
        m = PHASE_ID_RE.match(pid)
        if not m or m.group(1) != did:
            raise DesignError(f"phase id {pid!r} must be {did}-P<n>")
        pst = str(ph.get("status") or "PROPOSED").upper()
        if pst not in STATUSES:
            raise DesignError(f"phase {pid} status {pst!r} invalid")
        tasks_out = []
        for j, tk in enumerate(ph.get("tasks") or []):
            if not isinstance(tk, dict):
                raise DesignError(f"{pid} task {j} is not a mapping")
            tid = str(tk.get("id") or "")
            if not (tid.startswith(pid + "-T") and TB.DESIGN_TASK_RE.match(tid)):
                raise DesignError(f"task id {tid!r} must be {pid}-T<m>")
            tst = str(tk.get("status") or "PROPOSED").upper()
            if tst not in STATUSES:
                raise DesignError(f"task {tid} status {tst!r} invalid")
            tasks_out.append(
                {
                    "id": tid,
                    "title": str(tk.get("title") or ""),
                    "status": tst,
                    "areas": [str(a) for a in tk.get("areas") or []],
                    "kind": tk.get("kind"),
                }
            )
        phases_out.append({"id": pid, "title": str(ph.get("title") or ""), "status": pst, "tasks": tasks_out})
    return {
        "id": did,
        "title": str(doc.get("title") or did),
        "status": st,
        "approval": doc.get("approval"),
        "owner": doc.get("owner"),
        "source": doc.get("source"),
        "summary": str(doc.get("summary") or "")[:600],
        "phases": phases_out,
    }


# --------------------------------------------------------------------------------------------- cache


class _Cached:
    """Single-flight value cache: at most one rebuild per ``ttl`` and never two at once."""

    def __init__(self, build: Callable[[], Any], ttl: float = REFRESH_S):
        self.build = build
        self.ttl = ttl
        self.value: Any = None
        self.at: float | None = None
        self.lock = threading.Lock()

    def get(self) -> Any:
        now = time.monotonic()
        if self.at is not None and now - self.at < self.ttl:
            return self.value
        if not self.lock.acquire(blocking=self.value is None):
            return self.value  # someone else is rebuilding: serve the last value
        try:
            if self.at is not None and time.monotonic() - self.at < self.ttl:
                return self.value
            self.value = self.build()
            self.at = time.monotonic()
            return self.value
        finally:
            self.lock.release()


class DesignStore:
    """docs/designs/*.md, re-parsed per file only when its (mtime, size) changes."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or ROOT)
        self.dir = self.root / DESIGNS_REL
        self._files: dict[str, tuple[tuple[int, int], dict[str, Any] | None, str | None]] = {}

    def load(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        designs, errors = [], []
        if not self.dir.is_dir():
            return designs, errors
        seen = set()
        for p in sorted(self.dir.glob("DSN-*.md"))[:MAX_DESIGNS]:
            seen.add(p.name)
            try:
                stt = p.stat()
            except OSError:
                continue
            key = (int(stt.st_mtime_ns), int(stt.st_size))
            cached = self._files.get(p.name)
            if cached is None or cached[0] != key:
                try:
                    if stt.st_size > MAX_DESIGN_BYTES:
                        raise DesignError(f"file larger than {MAX_DESIGN_BYTES} bytes")
                    doc = parse_design(p.read_text(encoding="utf-8"), stem=p.stem)
                    doc["path"] = str(p.relative_to(self.root))
                    cached = (key, doc, None)
                except (DesignError, OSError, UnicodeDecodeError) as exc:
                    cached = (key, None, str(exc)[:300])
                self._files[p.name] = cached
            if cached[1] is not None:
                designs.append(cached[1])
            else:
                errors.append({"path": str(p.relative_to(self.root)), "error": cached[2] or "unreadable"})
        for gone in set(self._files) - seen:
            self._files.pop(gone, None)
        return designs, errors


# --------------------------------------------------------------------------------------------- approvals


def packet_status(readme: Path, lines: int = 40) -> str | None:
    try:
        with readme.open("r", encoding="utf-8", errors="replace") as fh:
            for i, ln in enumerate(fh):
                if i >= lines:
                    break
                m = _STATUS_LINE_RE.match(ln.strip("`* "))
                if m:
                    return m.group(1)[:200]
    except OSError:
        return None
    return None


def approval_state(raw: str | None) -> str:
    s = (raw or "").upper()
    if "APPROVED" in s and "AWAIT" not in s and "NOT APPROVED" not in s:
        return "approved"
    if "PROPOSED" in s or "AWAIT" in s or "PENDING" in s or "DRAFT" in s:
        return "awaiting operator"
    return "unknown"


def apply_ledger_approvals(designs: list[dict[str, Any]], claims_dir: Path | None) -> list[dict[str, Any]]:
    """Overlay the operator's passkey approvals (Work pipeline Tier 2, <claims_dir>/designs/approvals.jsonl): a design
    approved there reads APPROVED at once, with ``file_pending`` until its file says so in a reviewed commit."""
    try:
        try:
            from scripts.lib import work_pipeline_tier2 as T2
        except ImportError:
            from lib import work_pipeline_tier2 as T2  # type: ignore[no-redef]
        recs = T2.design_approvals(Path(claims_dir) if claims_dir else B.default_claims_dir())
    except Exception:  # noqa: BLE001 - the overlay is additive; the registry still renders
        return designs
    out = []
    for d in designs:
        r = recs.get(d["id"])
        if r and d.get("status") in ("PROPOSED", "HELD") or (r and "await" in str(d.get("approval") or "").lower()):
            d = {
                **d,
                "status": "APPROVED" if d.get("status") in ("PROPOSED", "HELD") else d["status"],
                "approval": f"approved by {r.get('actor')} {r.get('at')}: {r.get('words')}",
                "file_pending": True,
                "approval_record": {k: r.get(k) for k in ("at", "actor", "words", "request_id")},
            }
        out.append(d)
    return out


def ledger_approved_ids(claims_dir: Path | None) -> set[str]:
    try:
        try:
            from scripts.lib import work_pipeline_tier2 as T2
        except ImportError:
            from lib import work_pipeline_tier2 as T2  # type: ignore[no-redef]
        return set(T2.design_approvals(Path(claims_dir) if claims_dir else B.default_claims_dir()))
    except Exception:  # noqa: BLE001
        return set()


def designs_awaiting(
    root: Path, designs: list[dict[str, Any]], approved_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Operator-pending items: PROPOSED designs, packets whose README Status says PROPOSED/awaiting, and design
    entries whose approval says awaiting operator."""
    out = []
    for d in designs:
        appr = str(d.get("approval") or "")
        if d["status"] == "PROPOSED" or "await" in appr.lower():
            out.append(
                {
                    "kind": "design",
                    "id": d["id"],
                    "title": d["title"],
                    "status": d["status"],
                    "approval": appr or "awaiting operator",
                    "path": d.get("path"),
                }
            )
    pk = Path(root) / "docs" / "ops" / "packets"
    if pk.is_dir():
        for readme in sorted(pk.glob("*/README.md"))[:MAX_PACKETS]:
            raw = packet_status(readme)
            if raw and approval_state(raw) == "awaiting operator" and readme.parent.name not in (approved_ids or set()):
                out.append(
                    {
                        "kind": "packet",
                        "id": readme.parent.name,
                        "title": readme.parent.name,
                        "status": raw,
                        "approval": "awaiting operator",
                        "path": str(readme.relative_to(root)),
                    }
                )
    return out


# --------------------------------------------------------------------------------------------- work board


def _holder(owner: dict | None) -> str | None:
    if not owner:
        return None
    sess = str(owner.get("session") or "")
    return f"{owner.get('vendor') or '?'}:{sess[:8] if sess else '?'}"


def work_items(
    tasks: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    open_prs: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """One row per piece of queued work: task-board entries (agent and operator to-dos), claims with no task, and
    open PRs that no claim/task already covers. Stage: open -> claimed -> in_progress -> in_review -> merged -> live."""
    by_claim = {r["claim_id"]: r for r in claim_rows}
    rows: list[dict[str, Any]] = []
    covered_prs: set[int] = set()
    covered_claims: set[str] = set()
    for t in tasks:
        c = by_claim.get(t.get("claim_id") or "")
        if t.get("status") == "done":
            stage = STAGE_FROM_CLAIM.get(c["stage"], "merged") if c else "merged"
            stage = stage if stage in ("merged", "live") else "merged"
        elif c:
            stage = STAGE_FROM_CLAIM.get(c["stage"], "claimed")
        else:
            stage = "open"
        if c:
            covered_claims.add(c["claim_id"])
            if c.get("pr_number"):
                covered_prs.add(int(c["pr_number"]))
        rows.append(
            {
                "id": t["task_id"],
                "title": t.get("title"),
                "source": t.get("source") or ("design" if t.get("design_id") else "task board"),
                "design_id": t.get("design_id"),
                "areas": t.get("areas") or [],
                "stage": stage,
                "holder": _holder(t.get("owner")),
                "claimed_at": t.get("taken_at"),
                "claim_id": t.get("claim_id"),
                "worklog": bool(c and (c.get("worklog") or {}).get("exists")),
                "pr_number": c.get("pr_number") if c else None,
                "pr_url": c.get("pr_url") if c else None,
                "blocked_by": t.get("blocked_by") or [],
            }
        )
    for c in claim_rows:
        if c["claim_id"] in covered_claims or c.get("stage") == "abandoned" or c.get("state") == "abandoned":
            continue
        if c.get("pr_number"):
            covered_prs.add(int(c["pr_number"]))
        rows.append(
            {
                "id": c["claim_id"],
                "title": c.get("task"),
                "source": "claim",
                "design_id": None,
                "areas": c.get("paths") or [],
                "stage": STAGE_FROM_CLAIM.get(c.get("stage") or "claimed", "claimed"),
                "holder": _holder({"vendor": c.get("vendor"), "session": c.get("session")}),
                "claimed_at": c.get("started_at"),
                "claim_id": c["claim_id"],
                "worklog": bool((c.get("worklog") or {}).get("exists")),
                "pr_number": c.get("pr_number"),
                "pr_url": c.get("pr_url"),
                "blocked_by": [],
            }
        )
    for pr in open_prs or []:
        n = pr.get("number")
        if not n or int(n) in covered_prs:
            continue
        rows.append(
            {
                "id": f"PR-{n}",
                "title": pr.get("title"),
                "source": "open PR",
                "design_id": None,
                "areas": [],
                "stage": "in_review",
                "holder": f"github:{(pr.get('user') or {}).get('login') or '?'}",
                "claimed_at": pr.get("created_at"),
                "claim_id": None,
                "worklog": False,
                "pr_number": n,
                "pr_url": pr.get("html_url"),
                "blocked_by": [],
                "draft": bool(pr.get("draft")),
                "branch": (pr.get("head") or {}).get("ref"),
            }
        )
    rows.sort(
        key=lambda r: (WORK_STAGES.index(r["stage"]) if r["stage"] in WORK_STAGES else 9, str(r["claimed_at"] or ""))
    )
    return rows


def design_tree(designs: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Design -> phase -> task with the holder of each task from the task board (a registered task overrides the
    file's status: taken -> IN_PROGRESS, done -> DONE)."""
    by_id = {t["task_id"]: t for t in tasks}
    out = []
    for d in designs:
        phases = []
        for ph in d["phases"]:
            ts = []
            for tk in ph["tasks"]:
                reg = by_id.get(tk["id"])
                st = tk["status"]
                if reg is not None:
                    st = {"done": "DONE", "taken": "IN_PROGRESS"}.get(reg.get("status") or "", st)
                ts.append(
                    {
                        **tk,
                        "status": st,
                        "registered": reg is not None,
                        "holder": _holder(reg.get("owner")) if reg else None,
                        "claim_id": reg.get("claim_id") if reg else None,
                        "column": reg.get("column") if reg else None,
                    }
                )
            done = sum(1 for t in ts if t["status"] in ("DONE", "LIVE"))
            phases.append({**ph, "tasks": ts, "tasks_done": done, "tasks_total": len(ts)})
        out.append({**d, "phases": phases})
    return out


# --------------------------------------------------------------------------------------------- views


class WorkBoard:
    def __init__(
        self,
        root: Path | None = None,
        claims_dir: Path | None = None,
        *,
        gh_factory: Callable[[], LC.GitHubReader | None] | None = None,
        ttl: float = REFRESH_S,
    ):
        self.root = Path(root or ROOT)
        self.claims_dir = claims_dir
        self.store = DesignStore(self.root)
        self.gh_factory = gh_factory if gh_factory is not None else (lambda: LC.GitHubReader())
        self.prs: list[dict[str, Any]] | None = None
        self.prs_warning: str | None = "open PRs: first read pending"
        self._prs_running = False
        self._prs_at: float | None = None
        self._lock = threading.Lock()
        self.ttl = ttl
        self.tasks_view = _Cached(self._build_tasks, ttl)
        self.designs_view = _Cached(self._build_designs, ttl)

    def _refresh_prs(self) -> None:
        try:
            gh = self.gh_factory()
            if gh is None:
                prs, warn = None, "GitHub not consulted"
            else:
                doc, warn = gh.get(f"repos/{gh.repo}/pulls?state=open&per_page=100")
                prs = [p for p in doc if isinstance(p, dict)] if isinstance(doc, list) else None
            with self._lock:
                if prs is not None:
                    self.prs = prs
                self.prs_warning = warn
        except Exception as exc:  # noqa: BLE001 - background read never crashes the server
            with self._lock:
                self.prs_warning = f"open PRs unavailable ({type(exc).__name__})"
        finally:
            with self._lock:
                self._prs_running = False
                self._prs_at = time.monotonic()

    def _kick_prs(self, background: bool = True) -> None:
        with self._lock:
            due = self._prs_at is None or time.monotonic() - self._prs_at > max(self.ttl, 120.0)
            if not due or self._prs_running:
                return
            self._prs_running = True
        if background:
            threading.Thread(target=self._refresh_prs, daemon=True).start()
        else:
            self._refresh_prs()

    def _boards(self) -> tuple[B.ClaimBoard, dict[str, Any], dict[str, Any]]:
        claims = B.ClaimBoard(self.claims_dir)
        view = claims.board(include_finished=True)
        tasks = TB.TaskBoard(claims).board()
        return claims, view, tasks

    def _build_tasks(self) -> dict[str, Any]:
        _c, view, tb = self._boards()
        with self._lock:
            prs, warn = self.prs, self.prs_warning
        items = work_items(tb["tasks"], view["claims"], prs)
        counts = {s: sum(1 for r in items if r["stage"] == s) for s in WORK_STAGES}
        return {
            "schema": "WorkBoardTasks@v1",
            "as_of": view["as_of"],
            "stages": list(WORK_STAGES),
            "counts": counts,
            "items": items,
            "sources": {
                "task_board": len(tb["tasks"]),
                "claims": len(view["claims"]),
                "open_prs": None if prs is None else len(prs),
            },
            "open_prs_warning": warn,
            "refresh_s": self.ttl,
        }

    def _build_designs(self) -> dict[str, Any]:
        designs, errors = self.store.load()
        designs = apply_ledger_approvals(designs, self.claims_dir)
        _c, _view, tb = self._boards()
        return {
            "schema": "WorkBoardDesigns@v1",
            "as_of": B.iso(B.utc_now()),
            "statuses": list(STATUSES),
            "designs": design_tree(designs, tb["tasks"]),
            "awaiting_approval": designs_awaiting(self.root, designs, ledger_approved_ids(self.claims_dir)),
            "errors": errors,
            "store": DESIGNS_REL,
            "refresh_s": self.ttl,
        }

    def tasks(self, *, background: bool = True) -> dict[str, Any]:
        self._kick_prs(background)
        return self.tasks_view.get()

    def designs(self) -> dict[str, Any]:
        return self.designs_view.get()


_WORK_BOARD: WorkBoard | None = None
_WB_LOCK = threading.Lock()


def work_board() -> WorkBoard:
    global _WORK_BOARD
    with _WB_LOCK:
        if _WORK_BOARD is None:
            root = Path(os.environ.get("TRADEAI_WORK_BOARD_ROOT") or ROOT)
            _WORK_BOARD = WorkBoard(root)
        return _WORK_BOARD
