"""Claim lifecycle: claimed -> building -> pr_open -> ci_green -> merged -> released (live) | abandoned.

Operator 2026-10-23: a whiteboard that shows what each agent is working on, when it is implemented and when it
is finished, so agents do not step on each other. ``scripts/lib/agent_claim_board.py`` holds the claims; this
module adds the stages, each with a timestamp.

Two sources, merged into one effective stage per claim:

* **Declared** by the owning session in its own claim file (``agent_claim.py stage <id> building`` or
  ``... pr_open --pr N``): ``stages`` {stage: iso}. Only ``building`` and ``pr_open`` can be declared; the later
  stages need evidence.
* **Observed** (read-only, cached): GitHub over ``gh api --method GET`` only -- the PR (state, base, head SHA,
  merge commit) and the check runs of its head SHA against the base branch's required status checks -- and the
  release receipts on this host (served SHA from ``CURRENT``/``BUILD_SHA``, ``release_pins/apply-*.json``). A
  claim whose PR merge commit is an ancestor of a served release SHA is ``released``. Every call has a timeout;
  gh missing, offline, unauthenticated or slow is a warning and the claim keeps its declared stage.

Observations are a cache, not owner data: ``<claims_dir>/lifecycle/<claim_id>.json`` (``AgentClaimLifecycle@v1``),
written only by a CLI run (``sync --apply``, ``claim``/``check`` refreshing a conflicting claim, ``compact
--apply``) under an flock, merged monotonically (a stage timestamp, once seen, is kept). The read-only API never
writes it; it keeps its own in-memory observations and refreshes them in a background thread
(stale-while-revalidate), so no request ever waits on GitHub.

Effect on locks: a claim at ``merged`` or ``released`` stops blocking (its files are free) but stays on the board
until ``released``; compaction then archives it like any finished claim.

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY -- GitHub GETs, local ``git merge-base --is-ancestor`` and receipt
reads; writes only the lifecycle cache files.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

STAGES = ("claimed", "building", "pr_open", "ci_green", "merged", "released")
ABANDONED = "abandoned"
ALL_STAGES = STAGES + (ABANDONED,)
DECLARABLE = ("building", "pr_open")
FREE_STAGES = ("merged", "released")  # file locks released
HOLD_STAGES = ("pr_open", "ci_green", "merged")  # kept on the board until released
LIFECYCLE_SCHEMA = "AgentClaimLifecycle@v1"
LIFECYCLE_DIRNAME = "lifecycle"
CI_STATES = ("green", "pending", "failing", "unknown")
DEFAULT_REPO = "PatsKiller/tardeai"
ENV_REPO = "TRADEAI_AGENT_CLAIMS_REPO"
GH_TIMEOUT_S = 8.0
OPEN_PR_TTL_S = 120.0
REQUIRED_TTL_S = 3600.0
MAX_PRS_PER_REFRESH = 40
MAX_RECEIPTS = 30
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_GH_PATH_RE = re.compile(r"^repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./?=&:%,-]+$")

STAGE_HELP = {
    "claimed": "Files claimed; work not started or not yet declared.",
    "building": "The agent declared it is implementing (agent_claim.py stage <id> building).",
    "pr_open": "A pull request is open for this work (declared with --pr, or found on GitHub by branch).",
    "ci_green": "Every required check on the PR's head commit passed (GitHub, read-only).",
    "merged": "The PR is merged. File locks are released; the card stays until the merge is live.",
    "released": "The merge commit is an ancestor of a release SHA this host served (release receipts).",
    "abandoned": "Released without finishing, or lost a simultaneous-claim race.",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _norm_iso(value: Any) -> str | None:
    return _iso(_parse(value))


def stage_index(stage: str | None) -> int:
    return STAGES.index(stage) if stage in STAGES else -1


def pr_number(value: Any) -> int | None:
    m = re.search(r"(\d+)\s*$", str(value or "").strip())
    return int(m.group(1)) if m else None


def default_repo(root: Path | None = None) -> str:
    env = os.environ.get(ENV_REPO)
    if env:
        return env.strip()
    try:
        out = subprocess.run(
            ["git", "-C", str(root or Path(__file__).resolve().parents[2]), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", out.stdout.strip())
        if out.returncode == 0 and m:
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return DEFAULT_REPO


# --------------------------------------------------------------------------------------------- GitHub (GET only)


class GitHubReader:
    """``gh api --method GET`` only, with a timeout per call. Never raises; returns (value, warning)."""

    def __init__(
        self,
        repo: str | None = None,
        *,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout_s: float = GH_TIMEOUT_S,
    ):
        self._repo = repo
        self.run = runner or subprocess.run
        self.timeout_s = timeout_s
        self.calls: list[str] = []
        self.down: str | None = None  # first hard failure (gh missing/offline): later calls are skipped

    @property
    def repo(self) -> str:
        if not self._repo:
            self._repo = default_repo()  # resolved on first GitHub call, never at construction
        return self._repo

    def get(self, path: str) -> tuple[Any, str | None]:
        if self.down:
            return None, self.down
        if not _GH_PATH_RE.match(path):
            return None, f"refused gh path {path[:80]!r}"
        self.calls.append(path)
        cmd = ["gh", "api", "--method", "GET", path]
        env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}
        try:
            proc = self.run(cmd, capture_output=True, text=True, timeout=self.timeout_s, env=env)
        except FileNotFoundError:
            self.down = "gh not installed: GitHub stages not observed"
            return None, self.down
        except subprocess.TimeoutExpired:
            self.down = f"gh timed out after {self.timeout_s:g}s: GitHub stages not observed"
            return None, self.down
        except OSError as exc:
            self.down = f"gh failed ({type(exc).__name__}): GitHub stages not observed"
            return None, self.down
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            msg = err[0][:160] if err else "no stderr"
            if "404" in msg or "Not Found" in msg:
                return None, f"not found: {path}"
            self.down = f"gh exited {proc.returncode} ({msg}): GitHub stages not observed"
            return None, self.down
        try:
            return json.loads(proc.stdout or "null"), None
        except ValueError:
            return None, f"gh returned unparseable JSON for {path}"

    def pr(self, number: int) -> tuple[dict | None, str | None]:
        doc, warn = self.get(f"repos/{self.repo}/pulls/{int(number)}")
        return (doc if isinstance(doc, dict) else None), warn

    def pr_for_branch(self, branch: str) -> tuple[dict | None, str | None]:
        owner = self.repo.split("/", 1)[0]
        if not re.match(r"^[A-Za-z0-9_./-]{1,200}$", branch or ""):
            return None, "branch not queryable"
        doc, warn = self.get(f"repos/{self.repo}/pulls?head={owner}:{branch}&state=all&per_page=5")
        if not isinstance(doc, list) or not doc:
            return None, warn
        doc.sort(key=lambda p: (p.get("state") == "open", p.get("created_at") or ""), reverse=True)
        return doc[0], warn

    def required_contexts(self, base: str) -> tuple[list[str] | None, str | None]:
        doc, warn = self.get(f"repos/{self.repo}/branches/{base}/protection/required_status_checks")
        if isinstance(doc, dict):
            ctx = [str(c) for c in doc.get("contexts") or []]
            ctx += [str(c.get("context")) for c in doc.get("checks") or [] if isinstance(c, dict) and c.get("context")]
            return sorted(set(ctx)), None
        return None, warn

    def check_runs(self, sha: str) -> tuple[list[dict] | None, str | None]:
        doc, warn = self.get(f"repos/{self.repo}/commits/{sha}/check-runs?per_page=100")
        if isinstance(doc, dict):
            return [r for r in doc.get("check_runs") or [] if isinstance(r, dict)], None
        return None, warn

    def compare_is_ancestor(self, a: str, b: str) -> tuple[bool | None, str | None]:
        doc, warn = self.get(f"repos/{self.repo}/compare/{a}...{b}")
        if isinstance(doc, dict) and doc.get("status"):
            return doc["status"] in ("ahead", "identical"), None
        return None, warn


def ci_from_runs(runs: list[dict] | None, required: list[str] | None) -> dict[str, Any]:
    """Required checks for one head SHA -> {state, basis, required, failing, pending, completed_at}."""
    if runs is None:
        return {"state": "unknown", "basis": "unavailable", "required": required or [], "failing": [], "pending": []}
    latest: dict[str, dict] = {}
    for r in runs:
        name = str(r.get("name") or "")
        prev = latest.get(name)
        if prev is None or (r.get("started_at") or "", r.get("id") or 0) > (
            prev.get("started_at") or "",
            prev.get("id") or 0,
        ):
            latest[name] = r
    basis = "required" if required else "all_checks"
    names = list(required) if required else sorted(latest)
    failing, pending, done_at = [], [], []
    for n in names:
        r = latest.get(n)
        if r is None or r.get("status") != "completed":
            pending.append(n)
            continue
        if r.get("conclusion") in ("success", "skipped", "neutral"):
            if r.get("completed_at"):
                done_at.append(r["completed_at"])
        else:
            failing.append(n)
    if not names:
        state = "unknown"
    elif failing:
        state = "failing"
    elif pending:
        state = "pending"
    else:
        state = "green"
    return {
        "state": state,
        "basis": basis,
        "required": names,
        "failing": failing,
        "pending": pending,
        "completed_at": _norm_iso(max(done_at)) if state == "green" and done_at else None,
    }


# --------------------------------------------------------------------------------------------- release receipts


def git_is_ancestor(canonical: Path | None = None) -> Callable[[str, str], bool | None]:
    """Local read-only ``git merge-base --is-ancestor``. None when either commit is unknown locally."""
    repo = canonical or Path(
        os.environ.get("CANONICAL_SOURCE") or Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"
    )

    def check(a: str, b: str) -> bool | None:
        if not (SHA_RE.match(a or "") and SHA_RE.match(b or "")):
            return None
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        try:
            p = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return {0: True, 1: False}.get(p.returncode)

    return check


class ReleaseReader:
    """Served SHA (CURRENT + BUILD_SHA) and ``release_pins/apply-*.json`` receipts on this host. Read-only."""

    def __init__(
        self,
        releases_base: Path | None = None,
        deploy_state_dir: Path | None = None,
        *,
        is_ancestor: Callable[[str, str], bool | None] | None = None,
        serving: Callable[[], dict] | None = None,
    ):
        home = Path.home()
        self.releases_base = Path(
            releases_base or os.environ.get("TRADEAI_RELEASES_BASE") or home / "trade-ai-releases" / "portfolio-server"
        )
        self.deploy_state_dir = Path(deploy_state_dir or home / ".local" / "state" / "cio-phase2-exact-main")
        self.is_ancestor = is_ancestor or git_is_ancestor()
        self._serving = serving
        self._anc: dict[tuple[str, str], bool | None] = {}

    def serving(self) -> dict[str, Any]:
        if self._serving:
            return self._serving()
        try:
            try:
                from scripts.lib import exact_release_receipt as ERR
            except ImportError:
                from lib import exact_release_receipt as ERR  # type: ignore[no-redef]
            ident = ERR.observed_identity(self.releases_base)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise into the board
            return {"sha": None, "reason": type(exc).__name__}
        if ident.get("availability") != "AVAILABLE":
            return {"sha": None, "reason": ident.get("reason") or "current_unavailable"}
        since = None
        try:
            rec = json.loads((self.deploy_state_dir / "deploy_receipt.json").read_text(encoding="utf-8"))
            if rec.get("deployed_sha") == ident.get("sha"):
                since = rec.get("at")
        except (OSError, ValueError):
            pass
        return {"sha": ident.get("sha"), "since": _norm_iso(since), "release_dir": ident.get("release_dir")}

    def _receipt_sha(self, target: str | None) -> str | None:
        if not target:
            return None
        try:
            pin = (Path(target) / "BUILD_SHA").read_text(encoding="utf-8").strip()
            if SHA_RE.match(pin):
                return pin
        except OSError:
            pass
        m = re.match(r"^([0-9a-f]{7,40})-", Path(target).name)
        return m.group(1) if m else None

    def apply_receipts(self) -> list[dict[str, Any]]:
        d = self.deploy_state_dir / "release_pins"
        try:
            names = sorted(n for n in os.listdir(d) if re.match(r"^apply-\d{8}T\d+Z\.json$", n))
        except OSError:
            return []
        out = []
        for n in names[-MAX_RECEIPTS:]:
            try:
                doc = json.loads((d / n).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sha = self._receipt_sha(doc.get("target_release"))
            if sha:
                out.append({"receipt": n, "at": _norm_iso(doc.get("at")), "sha": sha})
        out.sort(key=lambda r: r["at"] or "")
        return out

    def ancestor(self, a: str, b: str, gh: GitHubReader | None = None) -> bool | None:
        key = (a, b)
        if key not in self._anc:
            res = self.is_ancestor(a, b)
            if res is None and gh is not None:
                res, _w = gh.compare_is_ancestor(a, b)
            self._anc[key] = res
        return self._anc[key]

    def released(self, merge_sha: str, merged_at: str | None, gh: GitHubReader | None = None) -> dict | None:
        """Earliest release (apply receipt, then the served SHA) that contains ``merge_sha``."""
        if not merge_sha:
            return None
        m_at = _parse(merged_at)
        for r in self.apply_receipts():
            at = _parse(r["at"])
            if m_at and at and at < m_at:
                continue  # released before the merge existed
            if self.ancestor(merge_sha, r["sha"], gh):
                return {"at": r["at"], "sha": r["sha"], "basis": f"release_pins/{r['receipt']}"}
        srv = self.serving()
        if srv.get("sha") and self.ancestor(merge_sha, srv["sha"], gh):
            return {"at": srv.get("since"), "sha": srv["sha"], "basis": "served CURRENT/BUILD_SHA"}
        return None


# --------------------------------------------------------------------------------------------- observation


def observe_claim(
    doc: Mapping[str, Any],
    prev: Mapping[str, Any] | None,
    *,
    gh: GitHubReader | None,
    rel: ReleaseReader | None,
    now: datetime,
    required_cache: dict[str, tuple[float, list[str] | None]] | None = None,
) -> dict[str, Any]:
    """One claim's observation, merged over ``prev`` (monotonic stage timestamps). Never raises."""
    obs: dict[str, Any] = dict(prev or {})
    obs.update({"schema": LIFECYCLE_SCHEMA, "claim_id": doc.get("claim_id")})
    stages = dict(obs.get("stages") or {})
    warnings: list[str] = []
    num = pr_number(doc.get("pr")) or obs.get("pr_number")
    pr = None
    merged_known = bool(obs.get("merge_sha") and obs.get("pr_state") == "merged")
    if gh is not None and not merged_known:
        if num:
            pr, w = gh.pr(num)
        elif doc.get("branch") and doc.get("status") == "active":
            pr, w = gh.pr_for_branch(str(doc["branch"]))
        else:
            w = None
        if w:
            warnings.append(w)
    if pr:
        num = pr.get("number") or num
        state = "merged" if pr.get("merged_at") else ("open" if pr.get("state") == "open" else "closed")
        obs.update(
            {
                "pr_number": num,
                "pr_url": pr.get("html_url"),
                "pr_state": state,
                "pr_draft": bool(pr.get("draft")),
                "pr_title": str(pr.get("title") or "")[:200] or None,
                "pr_base": (pr.get("base") or {}).get("ref"),
                "head_sha": (pr.get("head") or {}).get("sha"),
                "merge_sha": pr.get("merge_commit_sha") if state == "merged" else None,
                "merged_at": _norm_iso(pr.get("merged_at")),
                "closed_at": _norm_iso(pr.get("closed_at")),
            }
        )
        stages.setdefault("pr_open", _norm_iso(pr.get("created_at")) or _iso(now))
        if state == "merged":
            stages.setdefault("merged", obs["merged_at"])
        if state == "open" and obs.get("head_sha"):
            base = obs.get("pr_base") or "main"
            req = None
            cached = (required_cache or {}).get(base)
            if cached and time.monotonic() - cached[0] < REQUIRED_TTL_S:
                req = cached[1]
            else:
                req, w = gh.required_contexts(base) if gh else (None, None)
                if w and not w.startswith("not found"):
                    warnings.append(w)
                if required_cache is not None:
                    required_cache[base] = (time.monotonic(), req)
            runs, w = gh.check_runs(obs["head_sha"]) if gh else (None, None)
            if w:
                warnings.append(w)
            ci = ci_from_runs(runs, req)
            ci["head_sha"] = obs["head_sha"]
            ci["checked_at"] = _iso(now)
            obs["ci"] = ci
            if ci["state"] == "green":
                stages.setdefault("ci_green", ci.get("completed_at") or _iso(now))
    elif num and not obs.get("pr_number"):
        obs["pr_number"] = num
    if rel is not None and obs.get("merge_sha") and "released" not in stages:
        hit = rel.released(str(obs["merge_sha"]), obs.get("merged_at"), gh)
        if hit:
            stages["released"] = hit.get("at") or _iso(now)
            obs["released"] = hit
    obs["stages"] = {k: v for k, v in stages.items() if v}
    obs["observed_at"] = _iso(now)
    obs["warnings"] = warnings[:5]
    return obs


def effective(doc: Mapping[str, Any], obs: Mapping[str, Any] | None) -> dict[str, Any]:
    """The board's view of one claim's lifecycle: current stage, a timestamp per reached stage, locks held."""
    obs = obs or {}
    declared = dict(doc.get("stages") or {})
    stages: dict[str, str | None] = {"claimed": doc.get("started_at")}
    for st in DECLARABLE:
        if declared.get(st):
            stages[st] = declared[st]
    for st, ts in (obs.get("stages") or {}).items():
        if st in STAGES and ts:
            prev = stages.get(st)
            stages[st] = min(prev, ts) if prev else ts
    has_pr = bool(doc.get("pr") or obs.get("pr_number"))
    if has_pr and "pr_open" not in stages:
        stages["pr_open"] = declared.get("pr_open") or doc.get("heartbeat_at")
    pr_state = obs.get("pr_state")
    ci = obs.get("ci") or {}
    if "released" in stages:
        stage = "released"
    elif "merged" in stages or pr_state == "merged":
        stage = "merged"
    elif pr_state == "open" and ci.get("state") == "green":
        stage = "ci_green"
    elif has_pr:
        stage = "pr_open"
    elif "building" in stages:
        stage = "building"
    else:
        stage = "claimed"
    if doc.get("status") == "abandoned" and stage not in FREE_STAGES:
        stage = ABANDONED
        stages[ABANDONED] = doc.get("ended_at")
    # a stage reached later than the current one (e.g. ci_green before a new push) is history, not current
    return {
        "stage": stage,
        "stages": {k: stages[k] for k in ALL_STAGES if stages.get(k)},
        "locks_held": stage not in FREE_STAGES and stage != ABANDONED,
        "pr_number": obs.get("pr_number") or pr_number(doc.get("pr")),
        "pr_url": obs.get("pr_url"),
        "pr_state": pr_state,
        "pr_draft": obs.get("pr_draft"),
        "pr_base": obs.get("pr_base"),
        "head_sha": obs.get("head_sha"),
        "merge_sha": obs.get("merge_sha"),
        "ci": ci or None,
        "released": obs.get("released"),
        "observed_at": obs.get("observed_at"),
        "observe_warnings": list(obs.get("warnings") or []),
    }


def needs_observation(doc: Mapping[str, Any], obs: Mapping[str, Any] | None) -> bool:
    """Released and abandoned-without-PR claims never need GitHub again."""
    obs = obs or {}
    if "released" in (obs.get("stages") or {}):
        return False
    if doc.get("pr") or obs.get("pr_number"):
        return doc.get("status") != "abandoned" or bool(obs.get("merge_sha"))
    return bool(doc.get("branch")) and doc.get("status") == "active"


# --------------------------------------------------------------------------------------------- sidecar store


def lifecycle_dir(claims_dir: Path) -> Path:
    return Path(claims_dir) / LIFECYCLE_DIRNAME


def read_sidecars(claims_dir: Path) -> dict[str, dict[str, Any]]:
    d = lifecycle_dir(claims_dir)
    out: dict[str, dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == LIFECYCLE_SCHEMA and doc.get("claim_id") == p.stem:
            out[p.stem] = doc
    return out


def merge_obs(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> dict[str, Any]:
    """Newer fields win; stage timestamps are monotonic (earliest kept); a known merge/release is never lost."""
    out = dict(old or {})
    out.update(new)
    st = dict((old or {}).get("stages") or {})
    for k, v in (new.get("stages") or {}).items():
        if v and (k not in st or v < st[k]):
            st[k] = v
    out["stages"] = st
    for k in ("merge_sha", "merged_at", "released"):
        if (old or {}).get(k) and not new.get(k):
            out[k] = old[k]  # type: ignore[index]
    if (old or {}).get("pr_state") == "merged":
        out["pr_state"] = "merged"
    return out


def write_sidecars(claims_dir: Path, observations: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Merge-write observation cache files under an flock. Returns the claim ids written."""
    d = lifecycle_dir(claims_dir)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    with open(d / ".lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            existing = read_sidecars(claims_dir)
            for cid, obs in observations.items():
                merged = merge_obs(existing.get(cid), obs)
                tmp = d / f".{cid}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
                fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                try:
                    os.write(fd, (json.dumps(merged, indent=2, sort_keys=True) + "\n").encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(str(tmp), str(d / f"{cid}.json"))
                written.append(cid)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return written


# --------------------------------------------------------------------------------------------- observer


class LifecycleObserver:
    """Observe many claims within a budget. ``gh=None`` means GitHub is not consulted (receipts still are)."""

    def __init__(
        self,
        gh: GitHubReader | None = None,
        rel: ReleaseReader | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        max_prs: int = MAX_PRS_PER_REFRESH,
    ):
        self.gh = gh
        self.rel = rel
        self._now = now or _utc_now
        self.max_prs = max_prs
        self.required_cache: dict[str, tuple[float, list[str] | None]] = {}

    def observe(
        self, docs: Iterable[Mapping[str, Any]], prev: Mapping[str, Mapping[str, Any]] | None = None
    ) -> tuple[dict[str, dict[str, Any]], str | None]:
        prev = prev or {}
        out: dict[str, dict[str, Any]] = {}
        n = 0
        for doc in docs:
            cid = str(doc.get("claim_id"))
            if not needs_observation(doc, prev.get(cid)):
                continue
            if n >= self.max_prs:
                break
            n += 1
            out[cid] = observe_claim(
                doc, prev.get(cid), gh=self.gh, rel=self.rel, now=self._now(), required_cache=self.required_cache
            )
        warning = self.gh.down if self.gh is not None else "GitHub not consulted (--no-gh)"
        return out, warning


class CachedObserver:
    """Process-level cache for the read-only API: returns what it has at once and refreshes in a background thread
    when older than ``ttl_s`` (stale-while-revalidate). Never writes files."""

    def __init__(self, factory: Callable[[], LifecycleObserver], ttl_s: float = OPEN_PR_TTL_S):
        self.factory = factory
        self.ttl_s = ttl_s
        self.repo: str | None = None
        self.obs: dict[str, dict[str, Any]] = {}
        self.warning: str | None = "GitHub observation pending (first refresh running)"
        self.refreshed_at: float | None = None
        self.observed_at: str | None = None
        self._lock = threading.Lock()
        self._running = False

    def _refresh(self, docs: list[dict[str, Any]], prev: dict[str, dict[str, Any]]) -> None:
        try:
            got, warning = self.factory().observe(docs, prev)
            with self._lock:
                for cid, o in got.items():
                    self.obs[cid] = merge_obs(self.obs.get(cid), o)
                self.warning = warning
                self.refreshed_at = time.monotonic()
                self.observed_at = _iso(_utc_now())
        except Exception as exc:  # noqa: BLE001 - background refresh must never crash the server
            with self._lock:
                self.warning = f"lifecycle refresh failed ({type(exc).__name__})"
                self.refreshed_at = time.monotonic()
        finally:
            with self._lock:
                self._running = False

    def snapshot(
        self, docs: list[dict[str, Any]], sidecars: Mapping[str, Mapping[str, Any]], *, background: bool = True
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        with self._lock:
            due = self.refreshed_at is None or time.monotonic() - self.refreshed_at > self.ttl_s
            start = due and not self._running
            if start:
                self._running = True
        if start:
            prev = {cid: merge_obs(sidecars.get(cid), self.obs.get(cid, {})) for cid in set(sidecars) | set(self.obs)}
            if background:
                threading.Thread(target=self._refresh, args=(docs, prev), daemon=True).start()
            else:
                self._refresh(docs, prev)
        with self._lock:
            merged = {cid: merge_obs(sidecars.get(cid), self.obs.get(cid, {})) for cid in set(sidecars) | set(self.obs)}
            meta = {
                "observed_at": self.observed_at,
                "warning": self.warning,
                "refreshing": self._running,
                "ttl_s": self.ttl_s,
            }
        return merged, meta
