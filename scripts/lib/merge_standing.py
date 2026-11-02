"""merge_standing — the deterministic evaluator for a STANDING operator merge delegation.

Operator, 2026-11-02, verbatim: "Build the standing merge delegation" (after the design and the gap
were put to them; the capability is the operator's, delegated, not an agent's).

This module is the missing piece between "the branch is uploaded hands-free" and "the deploy poller
promotes main hands-free": it decides whether a PR may receive the EXISTING ``operator-merge`` label
with no operator tap, and it applies nothing else.

It is not a merge actor. It never calls Mergify, merges, pushes, promotes, or touches a broker,
secret, flag or held class. Its only possible mutation is one label request through
``pr_merge_telegram.add_operator_merge_label`` — the same helper the Telegram Approve tap uses — and
only when every gate below holds on the exact head. Mergify's queues, the ET window, the required
checks and the deploy poller's own gates are unchanged.

Design rules:

* **Default OFF, fail closed.** The capability is armed only by an AGENTS.md version that is ACTIVE on
  ``origin/main`` and whose version-history row names ``APPROVE_MERGE_STANDING``. Nothing else arms
  it: no config flag, no environment variable, no claim. Until that policy is ratified and merged this
  module returns ``enabled: False`` before it makes a single GitHub call.
* **Authentic operator origin only.** The approval is an operator-authored comment on the single issue
  titled *Standing merge approvals*, carrying ``APPROVE_MERGE_STANDING <glob> until <date>``. It is a
  DIFFERENT token and a DIFFERENT issue from #2459's standing *push* approval; a push approval never
  authorises a merge. Free text in a claim, a PR body or a handoff is not evidence.
* **Bounded.** The glob must start with a configured literal prefix (``wt/`` ``feat/`` ``fix/``
  ``chore/`` ``docs/``), may never match ``main``/``master``/``release/*``/``train/*``, expires on a
  required UTC date at most ``max_days`` after the comment, and is voided by a later
  ``REVOKE_MERGE_STANDING`` (any case or markup) or by closing the issue.
* **Evidence, not judgement.** Non-draft, base ``main``, not held, not already labelled; every check
  green on the exact head SHA (``pr_all_checks_green.all_checks_green`` reads the API, not the
  rollup); TWO independent ``Adversarial-review: MERGE`` receipts bound to that exact head, neither
  written by the author's agent, session or GitHub login; inside the configured merge window; the
  deploy STOP latch absent.
* **One per run.** ``max_labels_per_run`` defaults to 1, matching the queue's ``batch_size: 1``.

Every decision that reaches the label step appends a ``MergeStandingReceipt@v1`` row.

AUTHORITY: READ_ONLY_ADVISORY except for ``apply``, which adds one label under every gate above.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "merge_standing.json"
SCHEMA = "MergeStandingDecision@v1"
RECEIPT_SCHEMA = "MergeStandingReceipt@v1"
NO_CONSUMER_REASON = (
    "MergeStandingReceipt@v1 is the evidence record for an automatic merge-label decision: what the evaluator "
    "saw, which operator approval admitted it and which reviewers signed. No state machine reads it yet; a later "
    "audit or the digest line does, so it is retained rather than consumed."
)

TOKEN = "APPROVE_MERGE_STANDING"
REVOKE = "REVOKE_MERGE_STANDING"
#: The structured, affirmative marker the ratifying version row must carry. A bare mention of the
#: token — a rejected example, a "not adopted", a passing reference — never arms anything (review cc3
#: B3). Only this exact string, in a MAJOR row, is the capability.
GRANT_MARKER = "APPROVE_MERGE_STANDING: GRANTED"
#: The grant moves an operator/role boundary (merge delegation), so it can only be ratified as MAJOR.
REQUIRED_CLASS = "MAJOR"
#: The policy version that must be ACTIVE on main, and whose history row must carry the marker.
MIN_POLICY = (29, 6, 0)
MIN_POLICY_TEXT = "29.6.0"

TOKEN_RE = re.compile(r"^[ \t]*" + TOKEN + r"[ \t]+(?P<glob>\S+)[ \t]+until[ \t]+(?P<until>\S+)[ \t]*$", re.MULTILINE)
GLOB_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9-]{1,19}/)(?P<rest>[A-Za-z0-9._*?-]{1,121})$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,19}/$")
PROTECTED_RE = re.compile(r"^(main|master|head)$|^(release|train)(/|$)", re.IGNORECASE)
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?(^[ \t]*\1[ \t]*$|\Z)", re.MULTILINE | re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?(-->|\Z)", re.DOTALL)
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)[^\n]*$", re.MULTILINE)
#: Branches a standing merge glob must never be able to cover (probed, like the push approval).
_PROTECTED_PROBES = ("main", "master", "HEAD", "head", "release/x", "release/2026-11-01", "train/x",
                     "train/2026-11-01")
_ROW_RE = r"^\|\s*{v}\s*\|[^|]*\|\s*([^|]*)\|"

DEFAULTS: dict[str, Any] = {
    "issue_title": "Standing merge approvals",
    "issue_number": None,
    "operator_login": "PatsKiller",
    "max_days": 45,
    "prefixes": ["wt/", "feat/", "fix/", "chore/", "docs/"],
    "timezone": "America/New_York",
    "windows": [{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "17:30", "end": "18:30"}],
    "max_candidates": 8,
    "max_labels_per_run": 1,
    "max_pages": 10,
    "receipt_rel": "data/runtime/pr_merge_standing",
    "gh_timeout": 20,
}


class Refused(Exception):
    """A gate does not hold."""


# --------------------------------------------------------------------------- config


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    try:
        doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    for k, v in doc.items():
        cfg[k] = v
    cfg["windows"] = [w for w in (cfg.get("windows") or []) if isinstance(w, dict)]
    return cfg


def _semver(v: Optional[str]) -> Optional[tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _row_status(text: str, version: str) -> Optional[str]:
    m = re.search(_ROW_RE.format(v=re.escape(version)), text, re.M)
    return m.group(1).strip() if m else None


def _row_line(text: str, version: str) -> str:
    """The whole version-history row for ``version`` (the capability token lives in its summary)."""
    m = re.search(r"^\|\s*" + re.escape(version) + r"\s*\|.*$", text, re.M)
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- policy capability


def _row_fields(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def policy_capability(text: Optional[str]) -> dict[str, Any]:
    """Is a STANDING MERGE capability explicitly ratified in this AGENTS.md text?

    Three things, all required: the control block is ACTIVE at >= 29.6.0; the version-history row of
    that same version is class **MAJOR** (an operator/role boundary, never a MINOR by number); and the
    row carries the structured marker ``APPROVE_MERGE_STANDING: GRANTED``. A bare mention of the token
    — a rejected example, a "not adopted", a passing reference — never arms anything.
    """
    base: dict[str, Any] = {"schema": "MergeStandingPolicy@v1", "version": None, "capability": False}
    if not isinstance(text, str) or not text.strip():
        return {**base, "detail": "no AGENTS.md text"}
    try:
        from scripts.lib import hands_off_policy as hop
    except ImportError:  # scripts/ on sys.path
        from lib import hands_off_policy as hop  # type: ignore
    st = hop.policy_state_from_text(text, source="merge_standing")
    version = st.get("version")
    base["version"] = version
    if not st.get("active"):
        return {**base, "detail": f"AGENTS.md is not ACTIVE ({st.get('detail')})"}
    sv = _semver(version)
    if sv is None or sv < MIN_POLICY:
        return {**base, "detail": f"AGENTS.md {version} is below {MIN_POLICY_TEXT}"}
    row = _row_line(text, str(version))
    if not row:
        return {**base, "detail": f"AGENTS.md {version} has no history row"}
    fields = _row_fields(row)
    change_class = fields[3].upper() if len(fields) > 3 else ""
    base["change_class"] = change_class or None
    if change_class != REQUIRED_CLASS:
        return {**base, "detail": f"AGENTS.md {version} is class {change_class or 'unknown'}; "
                                  f"a merge delegation can only be ratified as {REQUIRED_CLASS}"}
    if GRANT_MARKER not in row:
        return {**base, "detail": f"AGENTS.md {version} row does not carry the affirmative marker {GRANT_MARKER!r} "
                                  f"(a bare mention of {TOKEN} is not a grant)"}
    return {**base, "capability": True, "detail": f"AGENTS.md {version} {REQUIRED_CLASS} ACTIVE with {GRANT_MARKER}"}


def _inside_git_work_tree(path: Path) -> bool:
    try:
        cp = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return cp.returncode == 0 and cp.stdout.strip() == "true"


def policy_text(root: Optional[Path] = None) -> Optional[str]:
    """main's ratified AGENTS.md, read from the source that is main's text — never a branch's.

    * In a git work tree: ``git show origin/main:AGENTS.md`` (the branch's own edit can never arm it).
    * In the SERVED release tree (``portfolio-server/CURRENT``), which is not a git work tree, read the
      tree's own ``AGENTS.md``: by construction that file *is* the promoted main content, and it is the
      only policy the host actually runs (review cc3 B5). The served-tree read is allowed ONLY when
      the directory is not inside a git work tree, so a checkout can never substitute its own text.
    * Anything else (git fails inside a work tree, served file missing) → None, and the path is OFF.
    """
    base = Path(root or ROOT)
    text = policy_text_from_git(cwd=base)
    if isinstance(text, str) and text.strip():
        return text
    if _inside_git_work_tree(base):
        return None  # fail closed: never fall back to a branch's own AGENTS.md
    try:
        served = (base / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return None
    return served if served.strip() else None


def policy_text_read(cwd: Optional[Path] = None) -> Optional[str]:
    """The text the evaluator judges: ``origin/main`` in a checkout, the served tree otherwise."""
    return policy_text(cwd)


def cadence_report(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Can the WIRED caller ever run inside a merge window? Report it; never pretend it can.

    The digest timer runs 08:00/12:00/16:30 ET and the window is 17:30-18:30 ET today, so the answer
    is no. That is a scheduler fact, not a bug this module may fix: a cadence change is an operator
    decision (PROPOSED, nothing installed), so the evaluator states the mismatch in its own output.
    """
    times = [str(t) for t in (cfg.get("caller_schedule_et") or [])]
    windows = [(str(w.get("start") or ""), str(w.get("end") or "")) for w in (cfg.get("windows") or [])]
    can = any(start and end and start <= t <= end for t in times for start, end in windows)
    return {"schema": "MergeStandingCadence@v1", "caller": "pr_merge_digest", "caller_schedule_et": times,
            "windows_local": [f"{a}-{b}" for a, b in windows], "timezone": cfg.get("timezone"), "can_fire": can,
            "detail": ("a wired run can fall inside a window" if can else
                       "the wired caller never runs inside the merge window; a cadence that can is an "
                       "operator scheduler decision (PROPOSED, not installed)")}


def _cached_gh(gh: Callable[[str], Any]) -> Callable[[str], Any]:
    """Memoize reads for one run: the approval issue was re-read once per candidate (cc3 N3)."""
    cache: dict[str, Any] = {}

    def call(path: str) -> Any:
        if path not in cache:
            cache[path] = gh(path)
        return cache[path]

    return call


def policy_text_from_git(ref: str = "origin/main", cwd: Path | str | None = None) -> Optional[str]:
    """main's AGENTS.md, never the branch's own edit. None on any failure (the caller stays disabled)."""
    try:
        cp = subprocess.run(["git", "show", f"{ref}:AGENTS.md"], cwd=str(cwd or ROOT), capture_output=True,
                            text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


# --------------------------------------------------------------------------- standing approval


def _unfenced(body: str) -> str:
    """The body as GitHub renders prose: fenced blocks, HTML comments and indented code lines removed.

    An example or a hidden line is never an approval. A revoke is matched on the RAW body instead, so
    a revoke counts wherever it appears.
    """
    return INDENTED_CODE_RE.sub("", FENCE_RE.sub("", HTML_COMMENT_RE.sub("", body)))


def standing_prefixes(cfg: Mapping[str, Any]) -> list[str]:
    out = []
    for p in cfg.get("prefixes") or []:
        p = str(p)
        if PREFIX_RE.match(p) and not PROTECTED_RE.search(p) and not PROTECTED_RE.search(p.rstrip("/")):
            out.append(p)
    return out


def _glob_re(glob: str) -> Optional[re.Pattern[str]]:
    m = GLOB_RE.match(glob or "")
    if m is None:
        return None
    body = "".join("[A-Za-z0-9._-]*" if c == "*" else "[A-Za-z0-9._-]" if c == "?" else re.escape(c)
                   for c in m.group("rest"))
    return re.compile("^" + re.escape(m.group("prefix")) + body + "$")


def glob_problem(glob: str, cfg: Mapping[str, Any]) -> Optional[str]:
    m = GLOB_RE.match(glob or "")
    if not m:
        return f"glob {glob!r} is not '<prefix>/<pattern>' ('*' alone or a second '/' is refused)"
    if m.group("prefix") not in standing_prefixes(cfg):
        return f"glob {glob!r}: prefix {m.group('prefix')!r} is not one of {standing_prefixes(cfg)}"
    rx = _glob_re(glob)
    hit = [p for p in _PROTECTED_PROBES if rx and rx.match(p)]
    if hit:
        return f"glob {glob!r} could match a protected branch ({', '.join(hit)})"
    return None


def _date(v: str) -> Optional[datetime]:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", v or ""):
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _login(doc: Any) -> str:
    return str(((doc or {}).get("user") or {}).get("login") or "") if isinstance(doc, dict) else ""


def _gh_json(gh_json: Callable[[str], Any], path: str) -> Any:
    try:
        return gh_json(path)
    except Exception:  # noqa: BLE001 - a reader that raises is a failed read, never an allow
        return None


def _pages(gh_json: Callable[[str], Any], path: str, cfg: Mapping[str, Any], what: str) -> list[dict]:
    max_pages = int(cfg.get("max_pages") or 10)
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = _gh_json(gh_json, f"{path}&per_page=100&page={page}")
        if not isinstance(rows, list):
            raise Refused(f"standing merge approval: could not read {what}")
        out += [r for r in rows if isinstance(r, dict)]
        if len(rows) < 100:
            return out
    raise Refused(f"standing merge approval: {what} has more than {max_pages * 100} entries; refusing")


def standing_issue(gh_json: Callable[[str], Any], repo: str, cfg: Mapping[str, Any]) -> int:
    """The operator's single open issue with the configured title, or the pinned number."""
    op = str(cfg.get("operator_login") or "")
    num = cfg.get("issue_number")
    if num is None:
        title = str(cfg.get("issue_title") or "")
        rows = _pages(gh_json, f"repos/{repo}/issues?creator={op}&state=all&sort=created&direction=asc",
                      cfg, "the operator's issues")
        nums = sorted({r["number"] for r in rows if r.get("title") == title and "pull_request" not in r
                       and isinstance(r.get("number"), int) and not isinstance(r.get("number"), bool)
                       and _login(r) == op})
        if not nums:
            raise Refused(f"standing merge approval: no operator issue titled {title!r}")
        if len(nums) > 1:
            raise Refused(f"standing merge approval: {len(nums)} operator issues are titled {title!r} "
                          f"(#{', #'.join(map(str, nums[:5]))}); pin one with issue_number")
        num = nums[0]
    if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
        raise Refused("standing merge approval: issue_number is not an issue number")
    doc = _gh_json(gh_json, f"repos/{repo}/issues/{num}")
    if not isinstance(doc, dict) or doc.get("number") != num or str(doc.get("state") or "") != "open" \
            or "pull_request" in doc:
        raise Refused(f"standing merge approval: issue #{num} is not an open issue")
    if _login(doc) != op:
        raise Refused(f"standing merge approval: issue #{num} was not opened by the operator")
    return num


def standing_approval(branch: str, *, repo: str, cfg: Mapping[str, Any], gh_json: Callable[[str], Any],
                      now: Optional[datetime] = None) -> dict[str, Any]:
    """The newest unrevoked, unexpired operator APPROVE_MERGE_STANDING line whose glob covers ``branch``."""
    if PROTECTED_RE.search(branch or ""):
        raise Refused(f"standing merge approval never covers {branch}")
    op = str(cfg.get("operator_login") or "")
    num = standing_issue(gh_json, repo, cfg)
    events = _pages(gh_json, f"repos/{repo}/issues/{num}/events?direction=asc", cfg, f"the events of #{num}")
    cutoff: Optional[datetime] = None
    for e in events:
        if str(e.get("event") or "") != "closed":
            continue
        t = _ts(e.get("created_at"))
        if t is None:
            raise Refused(f"standing merge approval: a close event on #{num} has no time; refusing")
        cutoff = t if cutoff is None or t > cutoff else cutoff
    comments = _pages(gh_json, f"repos/{repo}/issues/{num}/comments?direction=asc", cfg, f"the comments of #{num}")
    prefix = f"https://github.com/{repo}/issues/{num}#issuecomment-"
    rows: list[tuple[datetime, int, dict]] = []
    for c in comments:
        if _login(c) != op:
            continue
        made = _ts(c.get("created_at"))
        cid = c.get("id")
        if made is None or not isinstance(cid, int) or isinstance(cid, bool):
            raise Refused(f"standing merge approval: an operator comment on #{num} has no usable id or time")
        if cutoff is not None and made <= cutoff:
            continue
        if str(c.get("updated_at") or "") != str(c.get("created_at") or ""):
            raise Refused(f"standing merge approval: operator comment {cid} on #{num} was edited; post a new comment")
        rows.append((made, cid, c))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines: list[tuple[dict, str, str]] = []
    for _made, _cid, c in rows:
        body = str(c.get("body") or "")
        if REVOKE in body.upper():
            lines = []  # voids everything before it, and the revoking comment itself
            continue
        if "APPROVE_AGENTS_POLICY_" in body or str(c.get("html_url") or "") != f"{prefix}{c.get('id')}":
            continue
        lines += [(c, m.group("glob").strip("`"), m.group("until").strip("`"))
                  for m in TOKEN_RE.finditer(_unfenced(body))]
    if not lines:
        raise Refused(f"standing merge approval: no unrevoked {TOKEN} line on #{num}")
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    max_days = int(cfg.get("max_days") or 45)
    errs: list[str] = []
    for c, glob, until in reversed(lines):  # newest first
        url = str(c.get("html_url"))
        problem = glob_problem(glob, cfg)
        exp, made = _date(until), _ts(c.get("created_at"))
        if problem:
            errs.append(f"{url}: {problem}")
        elif exp is None:
            errs.append(f"{url}: expiry {until!r} is not a YYYY-MM-DD date")
        elif made is None:
            errs.append(f"{url}: comment has no created_at")
        elif exp < today:
            errs.append(f"{url}: expired {until} (UTC)")
        elif (exp - made.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).days > max_days:
            errs.append(f"{url}: expiry {until} is more than {max_days} days after the comment")
        elif not (_glob_re(glob) or re.compile(r"$^")).match(branch or ""):
            errs.append(f"{url}: {glob} does not cover {branch}")
        else:
            return {"kind": "standing_merge_comment", "ref": url, "author": op, "comment_id": str(c.get("id")),
                    "glob": glob, "until": until, "issue": num}
    raise Refused("standing merge approval: " + " | ".join(errs[:3]))


# --------------------------------------------------------------------------- window, stop, receipts


def merge_window(now: datetime, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Is ``now`` inside a configured merge window? UTC input; windows carry their own timezone."""
    tzname = str(cfg.get("timezone") or "America/New_York")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname)
    except Exception:  # noqa: BLE001 - no tz database is a refusal, never a pass
        return {"ok": False, "detail": f"timezone {tzname!r} is not available"}
    local = now.astimezone(tz)
    day = local.strftime("%a")
    hhmm = local.strftime("%H:%M")
    for w in cfg.get("windows") or []:
        days = [str(d)[:3].title() for d in (w.get("days") or [])]
        start, end = str(w.get("start") or ""), str(w.get("end") or "")
        if day in days and re.match(r"^\d{2}:\d{2}$", start) and re.match(r"^\d{2}:\d{2}$", end):
            if start <= hhmm <= end:
                return {"ok": True, "detail": f"{day} {hhmm} {tzname} inside {start}-{end}"}
    return {"ok": False, "detail": f"{day} {hhmm} {tzname} is outside every configured merge window"}


def stop_state() -> dict[str, Any]:
    """The deploy STOP latch, fail closed: only ABSENT lets a label through."""
    try:
        from scripts.lib import deploy_stop as ds
        from scripts.lib import release_control as rc
    except ImportError:  # scripts/ on sys.path
        from lib import deploy_stop as ds  # type: ignore
        from lib import release_control as rc  # type: ignore
    try:
        status, _body = rc.read_latch(Path(ds.state_dir()) / rc.LATCH_NAME)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "UNREADABLE", "detail": f"{type(exc).__name__}: {exc}"}
    return {"ok": status == rc.LATCH_ABSENT, "state": status,
            "detail": "STOP latch absent" if status == rc.LATCH_ABSENT else f"STOP latch {status}"}


def coordinator_checker() -> Callable[[str], bool]:
    """Is ``session`` a live (<= 24 h) claim on the coordinator virtual path? Fail closed on a read error."""
    try:
        from scripts.lib import agent_claim_board as board
        from scripts.lib import hands_off_policy as hop
    except ImportError:  # scripts/ on sys.path
        from lib import agent_claim_board as board  # type: ignore
        from lib import hands_off_policy as hop  # type: ignore
    try:
        views, _bad = board.ClaimBoard(None).views()
        rows = []
        for v in views:
            doc = dict(v.doc)
            doc["_state"] = v.state
            doc["_path"] = str(v.path)
            rows.append(doc)
    except Exception:  # noqa: BLE001 - an unreadable board is no coordinator, never a pass
        return lambda _session: False

    def check(session: str) -> bool:
        session = (session or "").strip()
        if not session:
            return False
        if hop.coordinator_session_ok(session, rows, live_only=True) is not None:
            return True
        # A coordinator claim may be live-but-quiet; the push handoff path allows up to 24 h.
        for r in hop.coordinator_claims(rows, live_only=False):
            if str(r.get("session") or "").strip() == session:
                hb = _ts(r.get("heartbeat_at") or r.get("started_at"))
                if hb is not None and (datetime.now(timezone.utc) - hb).total_seconds() <= 24 * 3600:
                    return True
        return False

    return check


def review_receipts(comments: Iterable[Mapping[str, Any]], *, head: str, author_agent: str,
                    author_session: str, author_login: str,
                    coordinator_ok: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
    """TWO independent review receipts bound to the exact head AND to their authenticated authors.

    A receipt is a PR comment in ``hands_off_policy.parse_receipt``'s shape. The identity that counts is
    the **GitHub login that wrote the comment**, not the ``reviewer=`` string: text is forgeable, an
    authenticated author is not. One receipt per comment; logins are compared case-insensitively; the
    PR author's own login never counts; and the named ``coordinator=`` must hold a live coordinator
    claim. When provenance is unavailable — no comment author, or no coordinator checker — the path
    refuses rather than falling back to the text (review cc3 B1/N2).

    Consequence, stated plainly: on this host ``gh`` is authenticated as the operator, so agent-written
    comments all share one login. Two distinct authenticated authors therefore need two distinct GitHub
    identities; until agents have them, this gate cannot pass. That is the fail-closed behaviour the
    lead asked for, not an oversight.
    """
    try:
        from scripts.lib import hands_off_policy as hop
    except ImportError:  # scripts/ on sys.path
        from lib import hands_off_policy as hop  # type: ignore
    if coordinator_ok is None:
        return {"ok": False, "receipts": [], "rejected": ["no coordinator-provenance check available"],
                "detail": "coordinator provenance is unavailable; refusing"}
    banned = {x.casefold() for x in (author_agent, author_session, author_login) if x}
    author = (author_login or "").casefold()
    seen: list[dict[str, str]] = []
    rejected: list[str] = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        body = str(c.get("body") or "")
        parsed = hop.parse_receipt(body)
        if not parsed:
            continue  # not a receipt line at all
        login = _login(c)
        if not login:
            rejected.append("a receipt comment has no authenticated author")
            continue
        key = login.casefold()
        if author and key == author:
            rejected.append(f"{login}: wrote the PR under review")
            continue
        for r in parsed[:1]:  # one comment is one reviewer's signature, however many lines it carries
            if not head or not head.lower().startswith(r["head"]):
                rejected.append(f"{login}: receipt head {r['head']} is not this head")
                continue
            if r["reviewer"].casefold() in banned:
                rejected.append(f"{login}: names the author's agent, session or login")
                continue
            if not coordinator_ok(r["coordinator"]):
                rejected.append(f"{login}: coordinator {r['coordinator']} holds no live coordinator claim")
                continue
            if any(x["login"] == key for x in seen):
                continue  # the same account cannot sign twice
            seen.append({**r, "login": login})
    ok = len(seen) >= 2
    return {"ok": ok, "receipts": seen, "rejected": rejected[:6],
            "detail": ("two independently authenticated receipts on this head" if ok
                       else f"{len(seen)} independently authenticated receipt(s) on this head; two are required")}


# --------------------------------------------------------------------------- the decision


def decide(evidence: Mapping[str, Any], cfg: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Pure decision over already-gathered evidence. No IO, no clock beyond ``now``."""
    refusals: list[str] = []
    pr = evidence.get("pr") or {}
    branch = str(pr.get("branch") or "")
    head = str(pr.get("head") or "")

    cap = evidence.get("capability") or {}
    if not cap.get("capability"):
        refusals.append(f"policy: {cap.get('detail') or 'standing merge capability is not ratified'}")
    stand = evidence.get("standing") or {}
    if not stand.get("ref"):
        refusals.append(f"approval: {evidence.get('standing_error') or 'no standing merge approval'}")
    else:
        rx = _glob_re(str(stand.get("glob") or ""))
        if rx is None or not rx.match(branch):
            refusals.append(f"approval: glob {stand.get('glob')} does not cover {branch}")
    if bool(pr.get("draft")):
        refusals.append("pr: still a draft")
    if str(pr.get("base") or "main") != "main":
        refusals.append(f"pr: base is {pr.get('base')}, not main")
    if bool(pr.get("already_labelled")):
        refusals.append("pr: already carries operator-merge")
    held = evidence.get("held") or {}
    if held.get("labels") or held.get("classes"):
        refusals.append(f"held: labels={held.get('labels')} classes={held.get('classes')}")
    trust = evidence.get("trust") or {}
    if trust.get("hit"):
        refusals.append(f"trust-anchor: the PR changes what this path trusts ({', '.join(trust['hit'][:3])})")
    if not evidence.get("files_verified"):
        refusals.append("files: could not verify every changed path")
    checks = evidence.get("checks") or {}
    if not checks.get("ok"):
        refusals.append(f"checks: {checks.get('reason') or '; '.join(checks.get('failing') or []) or 'not green'}")
    elif not checks.get("passing"):
        # Every run merely skipped is not evidence that anything passed.
        refusals.append("checks: no check reported success on this head")
    receipts = evidence.get("receipts") or {}
    if not receipts.get("ok"):
        refusals.append(f"review: {receipts.get('detail')}")
    win = evidence.get("window") or {}
    if not win.get("ok"):
        refusals.append(f"window: {win.get('detail')}")
    stop = evidence.get("stop") or {}
    if not stop.get("ok"):
        refusals.append(f"stop: {stop.get('detail')}")
    return {
        "schema": SCHEMA,
        "pr": pr.get("number"),
        "branch": branch,
        "head": head,
        "eligible": not refusals,
        "refusals": refusals,
        "standing": ({"ref": stand.get("ref"), "glob": stand.get("glob"), "until": stand.get("until")}
                     if stand.get("ref") else None),
        "reviewers": [r["reviewer"] for r in (receipts.get("receipts") or [])][:2],
        "checks_checked": checks.get("checked"),
        "at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- evidence + apply


def _author_claim(branch: str) -> dict[str, str]:
    """The branch's active claim row (author agent + session). Absent refuses the independence check."""
    try:
        from scripts.lib import agent_claim_board as board
    except ImportError:  # scripts/ on sys.path
        from lib import agent_claim_board as board  # type: ignore
    try:
        views, _bad = board.ClaimBoard(None).views()
    except Exception:  # noqa: BLE001
        return {}
    for v in views:
        doc = dict(v.doc)
        if str(doc.get("branch") or "") == branch and str(doc.get("status") or "") == "active":
            return {"agent": str(doc.get("agent") or ""), "session": str(doc.get("session") or "")}
    return {}


def gather(pr_number: int, *, repo: str, cfg: Mapping[str, Any], gh_json: Callable[[str], Any], now: datetime,
           capability: Mapping[str, Any], stop: Mapping[str, Any],
           claim_reader: Optional[Callable[[str], Mapping[str, str]]] = None,
           coordinator_ok: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
    """Read one PR's evidence. Every read is GET-only; a failed read refuses, never admits."""
    view = _gh_json(gh_json, f"repos/{repo}/pulls/{int(pr_number)}")
    if not isinstance(view, dict) or not view:
        return {"pr": {"number": int(pr_number)}, "error": "could not read the PR"}
    branch = str((view.get("head") or {}).get("ref") or "")
    head = str((view.get("head") or {}).get("sha") or "")
    labels = {str((lab or {}).get("name") or "") for lab in (view.get("labels") or []) if isinstance(lab, dict)}
    files_rows = _gh_json(gh_json, f"repos/{repo}/pulls/{int(pr_number)}/files?per_page=100") or []
    files = [str((f or {}).get("filename") or "") for f in files_rows if isinstance(f, dict)]
    changed = int(view.get("changed_files") or len(files))
    author = dict((claim_reader or _author_claim)(branch) or {})
    author_login = str(((view.get("user") or {}).get("login")) or "")
    try:
        from scripts.lib import merge_hold_paths as mhp
    except ImportError:  # scripts/ on sys.path
        from lib import merge_hold_paths as mhp  # type: ignore
    held_labels = sorted(labels & mhp.hold_labels())
    held_classes = sorted(mhp.held_classes(files)) if files else []
    anchors = [str(a) for a in (cfg.get("trust_anchors") or [])]
    trust_hits = sorted({f for f in files if any(f == a or f.startswith(a.rstrip("/") + "/") for a in anchors)})
    try:
        from scripts.lib import pr_all_checks_green as pacg
    except ImportError:  # scripts/ on sys.path
        from lib import pr_all_checks_green as pacg  # type: ignore
    checks = pacg.all_checks_green(gh_json, repo, head) if head else {"ok": False, "reason": "no head sha"}
    try:
        comments = _pages(gh_json, f"repos/{repo}/issues/{int(pr_number)}/comments?direction=asc", cfg,
                          f"the comments of #{pr_number}")
        receipts = review_receipts(comments, head=head, author_agent=author.get("agent", ""),
                                   author_session=author.get("session", ""), author_login=author_login,
                                   coordinator_ok=coordinator_ok)
    except Refused as exc:
        receipts = {"ok": False, "receipts": [], "rejected": [], "detail": str(exc)}
    try:
        standing: Optional[dict[str, Any]] = standing_approval(branch, repo=repo, cfg=cfg, gh_json=gh_json,
                                                               now=now) if branch else None
        standing_error = "" if standing else "no branch"
    except Refused as exc:
        standing, standing_error = None, str(exc)
    return {
        "pr": {"number": int(pr_number), "branch": branch, "head": head,
               "draft": bool(view.get("draft")), "base": str((view.get("base") or {}).get("ref") or ""),
               "already_labelled": "operator-merge" in labels},
        "held": {"labels": held_labels, "classes": held_classes},
        "trust": {"hit": trust_hits},
        "files_verified": bool(files) and len(files) >= changed,
        "checks": checks,
        "receipts": receipts,
        "window": merge_window(now, cfg),
        "stop": dict(stop),
        "capability": dict(capability),
        "standing": standing,
        "standing_error": standing_error,
        "author": {"claim": author, "login": author_login},
    }


def receipt_path(cfg: Mapping[str, Any]) -> Path:
    root = Path(os.environ.get("TRADEAI_STATE_ROOT")
                or (Path.home() / "trade-ai-releases" / "persistent-state"))
    return root / str(cfg.get("receipt_rel") or "data/runtime/pr_merge_standing") / "receipts.jsonl"


def write_receipt(row: Mapping[str, Any], cfg: Mapping[str, Any]) -> Path:
    path = receipt_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(row, schema=RECEIPT_SCHEMA, no_consumer_reason=NO_CONSUMER_REASON),
                            sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path


def review(ready: Iterable[Mapping[str, Any]], *, repo: str, cfg: Optional[Mapping[str, Any]] = None,
           apply: bool = False, now: Optional[datetime] = None,
           gh_json: Optional[Callable[[str], Any]] = None,
           policy_text: Optional[str] = None,
           label_applier: Optional[Callable[..., Any]] = None,
           stop_reader: Optional[Callable[[], Mapping[str, Any]]] = None,
           claim_reader: Optional[Callable[[str], Mapping[str, str]]] = None,
           coordinator_ok: Optional[Callable[[str], bool]] = None,
           policy_root: Optional[Path] = None) -> dict[str, Any]:
    """Annotate the digest's ready rows with a standing decision; label at most one when ``apply``.

    ``apply`` is the host timer's flag. It is NOT sufficient on its own: nothing is labelled unless
    the policy capability is ratified AND a genuine operator standing approval covers the branch AND
    every gate in ``decide`` holds on the head read at that moment, and every gate is re-asserted
    immediately before the label is written.
    """
    cfg = dict(cfg or load_config())
    now = now or datetime.now(timezone.utc)
    text = policy_text if policy_text is not None else policy_text_read(cwd=policy_root or ROOT)
    cap = policy_capability(text)
    out: dict[str, Any] = {"schema": SCHEMA, "enabled": bool(cap.get("capability")), "apply": bool(apply),
                           "policy": cap, "decisions": [], "applied": [], "considered": 0,
                           "cadence": cadence_report(cfg), "detail": ""}
    if not cap.get("capability"):
        out["detail"] = f"standing merge path OFF: {cap.get('detail')}"
        return out
    gh = _cached_gh(gh_json or _default_gh_json)
    raw_gh = gh_json or _default_gh_json
    stop = dict((stop_reader or stop_state)() or {})
    coord_ok = coordinator_ok or coordinator_checker()
    rows = [i for i in ready if isinstance(i, Mapping) and isinstance(i.get("pr"), int)]
    limit = int(cfg.get("max_candidates") or 8)
    out["considered"] = min(len(rows), limit)
    for item in rows[:limit]:
        ev = gather(int(item["pr"]), repo=repo, cfg=cfg, gh_json=gh, now=now, capability=cap, stop=stop,
                    claim_reader=claim_reader, coordinator_ok=coord_ok)
        if ev.get("error"):
            out["decisions"].append({"pr": int(item["pr"]), "eligible": False, "refusals": [ev["error"]]})
            continue
        decision = decide(ev, cfg, now)
        out["decisions"].append(decision)
        if apply and decision["eligible"] and len(out["applied"]) < int(cfg.get("max_labels_per_run") or 1):
            applied = _apply_one(decision, repo=repo, cfg=cfg, applier=label_applier, gh_json=raw_gh,
                                 stop_reader=stop_reader, coordinator_ok=coord_ok, now=now)
            out["applied"].append(applied)
            decision["labelled"] = bool(applied.get("ok"))
    if not apply:
        out["detail"] = "dry run: nothing labelled"
    return out


def _prelabel_problems(decision: Mapping[str, Any], *, repo: str, cfg: Mapping[str, Any],
                       gh_json: Optional[Callable[[str], Any]],
                       stop_reader: Optional[Callable[[], Mapping[str, Any]]],
                       coordinator_ok: Optional[Callable[[str], bool]],
                       now: Optional[datetime] = None) -> list[str]:
    """Re-assert EVERY gate immediately before the label is written (review cc3 B4).

    The decision was made after several API reads; a PR can turn draft, gain a held label, be labelled
    by someone else, the head can move, the operator can revoke, the window can close and STOP can be
    set in between. Only the head was re-read before. This re-reads the PR view (uncached), the STOP
    latch (local), the window (clock) and the standing approval (GitHub) and returns every violated
    gate; an empty list is the only state in which the label is written.
    """
    number = int(decision["pr"])
    head = str(decision.get("head") or "")
    branch = str(decision.get("branch") or "")
    problems: list[str] = []
    if gh_json is not None:
        view = _gh_json(gh_json, f"repos/{repo}/pulls/{number}")
        if not isinstance(view, dict) or not view:
            problems.append("could not re-read the PR before labelling")
        else:
            now_head = str(((view.get("head") or {}).get("sha")) or "")
            if now_head != head:
                problems.append(f"head moved {head[:9]} -> {now_head[:9]}")
            if view.get("draft"):
                problems.append("the PR became a draft")
            if str((view.get("base") or {}).get("ref") or "main") != "main":
                problems.append("the base is no longer main")
            labels = {str((lab or {}).get("name") or "") for lab in (view.get("labels") or [])}
            if "operator-merge" in labels:
                problems.append("operator-merge appeared on the PR independently")
            try:
                from scripts.lib import merge_hold_paths as mhp
            except ImportError:  # scripts/ on sys.path
                from lib import merge_hold_paths as mhp  # type: ignore
            held = sorted(labels & mhp.hold_labels())
            if held:
                problems.append(f"held label(s) appeared: {held}")
    stop = dict((stop_reader or stop_state)() or {})
    if not stop.get("ok"):
        problems.append(f"stop: {stop.get('detail')}")
    now = now or datetime.now(timezone.utc)
    win = merge_window(now, cfg)
    if not win.get("ok"):
        problems.append(f"window: {win.get('detail')}")
    if gh_json is not None and branch:
        try:
            again = standing_approval(branch, repo=repo, cfg=cfg, gh_json=gh_json, now=now)
            was = (decision.get("standing") or {}).get("ref")
            if was and again.get("ref") != was:
                problems.append(f"the standing approval changed ({was} -> {again.get('ref')})")
        except Refused as exc:
            problems.append(f"standing approval no longer resolves: {exc}")
    return problems


def _apply_one(decision: Mapping[str, Any], *, repo: str, cfg: Mapping[str, Any],
               applier: Optional[Callable[..., Any]], gh_json: Optional[Callable[[str], Any]] = None,
               stop_reader: Optional[Callable[[], Mapping[str, Any]]] = None,
               coordinator_ok: Optional[Callable[[str], bool]] = None,
               now: Optional[datetime] = None) -> dict[str, Any]:
    """Label the PR, but only after every gate is re-asserted on the state read at that moment."""
    number = int(decision["pr"])
    problems = _prelabel_problems(decision, repo=repo, cfg=cfg, gh_json=gh_json, stop_reader=stop_reader,
                                  coordinator_ok=coordinator_ok, now=now)
    if problems:
        event = ("standing-merge-head-moved"
                 if len(problems) == 1 and problems[0].startswith("head moved") else "standing-merge-prelabel-refused")
        row = {"event": event, "pr": number, "branch": decision.get("branch"), "head": decision.get("head"),
               "repo": repo, "problems": problems, "detail": "nothing was labelled"}
        try:
            row["receipt"] = str(write_receipt(row, cfg))
        except OSError as exc:
            row["receipt_error"] = f"{type(exc).__name__}: {exc}"
        return {"pr": number, "ok": False, **row}
    if applier is None:
        try:
            from scripts.lib import pr_merge_telegram as pmt
        except ImportError:  # scripts/ on sys.path
            from lib import pr_merge_telegram as pmt  # type: ignore
        applier = pmt.add_operator_merge_label
    try:
        res = applier(number, repo=repo)
    except Exception as exc:  # noqa: BLE001 - a failed label is reported, never retried in a loop
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    ok = bool(isinstance(res, Mapping) and res.get("ok"))
    row: dict[str, Any] = {
        "event": "standing-merge-label-applied" if ok else "standing-merge-label-failed",
        "pr": number, "branch": decision.get("branch"), "head": decision.get("head"),
        "standing_ref": (decision.get("standing") or {}).get("ref"),
        "reviewers": decision.get("reviewers"), "checks_checked": decision.get("checks_checked"),
        "repo": repo,
        "result": ({k: v for k, v in res.items() if k != "body"} if isinstance(res, Mapping) else str(res)),
    }
    try:
        row["receipt"] = str(write_receipt(row, cfg))
    except OSError as exc:
        row["receipt_error"] = f"{type(exc).__name__}: {exc}"
    return {"pr": number, "ok": ok, **row}


def _default_gh_json(path: str) -> Any:
    # No --paginate: every caller builds its own page=N (mixing the two concatenated pages and made
    # json.loads fail on a 100+ item issue; cc3 N1).
    cp = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=False)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        return json.loads(cp.stdout)
    except ValueError:
        return None


def open_candidates(gh_json: Callable[[str], Any], repo: str) -> list[dict[str, Any]]:
    """Open, non-draft PRs against main, read with ONE light REST call (no heavy GraphQL digest)."""
    rows = _gh_json(gh_json, f"repos/{repo}/pulls?state=open&base=main&per_page=100&sort=created&direction=desc")
    if not isinstance(rows, list):
        return []
    return [{"pr": int(r["number"])} for r in rows
            if isinstance(r, dict) and isinstance(r.get("number"), int) and not r.get("draft")]


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="standing merge delegation: evaluate, and (with every gate) label")
    ap.add_argument("--repo", default=os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai"))
    ap.add_argument("--apply", action="store_true", help="add operator-merge when every gate holds")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--pr", type=int, action="append", default=None, help="evaluate only these PRs")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    apply = bool(a.apply) and not a.dry_run
    gh = _default_gh_json
    ready = ([{"pr": n} for n in a.pr] if a.pr else open_candidates(gh, a.repo))
    out = review(ready, repo=a.repo, apply=apply, gh_json=gh)
    if a.as_json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"standing merge: enabled={out['enabled']} apply={out['apply']} considered={out['considered']}")
        if out.get("detail"):
            print(f"  {out['detail']}")
        if not out["enabled"] and ready:
            ids = ", ".join("#%d" % r["pr"] for r in ready[:20])
            print(f"  candidates (not evaluated, path OFF): {ids}")
        for dec in out["decisions"]:
            print(f"  #{dec.get('pr')} {'ELIGIBLE' if dec.get('eligible') else 'refused'} "
                  f"branch={dec.get('branch')} head={str(dec.get('head'))[:9]}")
            for r in dec.get("refusals") or []:
                print(f"    - {r}")
        for row in out["applied"]:
            print(f"  applied #{row.get('pr')} ok={row.get('ok')} event={row.get('event')} "
                  f"receipt={row.get('receipt')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
