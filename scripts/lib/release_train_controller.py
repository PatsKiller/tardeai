"""Release train controller (Release Train v2, Phase 3): the window runner's train mode. BUILD ONLY; nothing armed.

``scripts/release_window.py`` stays the one deployer and the one entry point (``train-plan``, ``train-run``,
``train-status``, ``train-reconcile``, ``train-quarantine-resolve``). This module is its train pipeline; every
production effect goes through ``release_window.Host`` (``cio_phase2_exact_main_deploy.sh`` prepare / promote /
rollback) and the release is verified by ``release_window.Runner._verify`` (CURRENT, BUILD_SHA, units, /api/health,
served copy, Command Center pages, platform-health, needs-action). Plan ``joyful-skipping-wilkes.md`` Phase 3;
enhanced design 2026-10-21 §4, §5, §6, §9.

Pipeline: select -> freeze -> integrate -> local test -> (wait for window) -> qualify -> merge -> promote -> verify
-> outcome.

  select     ``QueueSource`` (pluggable). Today: the PR-hygiene receipt plus ``gh pr list`` (read-only). The Phase 1
             store (branch ``feat/release-train-queue-20261021``) plugs in through the same interface. Risk comes
             from ``Classifier``; until the Phase 1 classifier exists, ``HoldAllClassifier`` holds every PR (unknown
             risk is held: fail closed). A PR that touches the train's own verifier (``PROTECTED_SURFACES``) is
             blocked whatever the classifier says.
  freeze     ``TrainCandidate@v1`` manifest: base main SHA, full PR head SHAs in dependency order, policy digest,
             classifier version, the required-check manifest (cio-hardening, agent-governance, release-readiness,
             ci-gate) and the window id (America/New_York, ISO with offset; DST-safe).
  integrate  an isolated scratch worktree: ``git merge --no-ff`` each PR in order, then the generated files are
             regenerated once. A conflict ejects that PR and its dependents, with a reason.
  local test a worker with an environment built from an allowlist (never ``.env``, ``DB_*``, tokens). A failure is
             bisected over prefixes inside an attempt and time budget; the culprit is attributed, the uncertain
             remainder is ``pending_investigation`` (stays queued, not ejected wholesale).
  qualify    build/publish capability -> push ``train/<id>`` and open/update the batch PR -> wait until all four
             checks read exactly ``success`` on the candidate SHA (trusted app, latest run). No tree-equivalence.
  merge      merge capability; STOP / epoch / revocation re-checked immediately before; expected-base compare
             (main == frozen base, PR heads unchanged); the resulting main SHA is recorded and its parents checked.
  promote    exact-SHA push/main checks on the merge commit, then ``prepare`` under a prepare capability and
             ``promote`` under a promote capability whose rollback target is the bound previous release; STOP and
             epoch re-checked at activation; failed verification -> roll back to the bound target, latch STOP,
             quarantine the artifact (and its lineage until the operator resolves it).

Windows (operator 2026-10-21): 18:00 and 00:00 general; 06:00 needs a proven drain (``DrainProbe``; none is proven,
so it is skipped); 08:00 latest activation start = 09:00 minus measured promote + verify + rollback minus a buffer,
skipped on 08:30 macro-release days or when the calendar is missing/stale. The repository has NO macro-calendar
provider (``scripts/economic_calendar.py``: FMP retired 2026-09-13, declared gap), so 08:00 is always skipped until an
operator-supplied calendar exists. A window is claimable only from ``lead_min`` before its start until ``grace_min``
after it; a missed window is never caught up. A per-day, per-slot claim file (O_EXCL) makes a repeated local hour
unable to activate twice.

Durability: every step appends a ``TrainEvent@v1`` row to ``<state>/train_events.jsonl`` (fsync, append-only); an
``intent`` row is written BEFORE each side effect; train state lives in ``<state>/trains/<id>/state.json``. On
restart, a non-terminal train is reconciled against GitHub main, CURRENT and the services before anything else
runs; an ambiguous effect latches STOP.

Dry run is the default for every command: GitHub writes, the merge and the promote are simulated and printed
step by step; nothing is claimed, issued, pushed or written. ``TRAIN_CONTROLLER_STATUS = "BUILD_ONLY"`` makes the
CLI refuse ``--live``; the live GitHub writer additionally refuses while ``GITHUB_WRITES_STATUS`` is not ACTIVE
(decision D2 + the AGENTS 17.0.0 amendment). MBI_BEHAVIOR = 0: no broker, no order path, no credential read.

Pre-build check (AGENTS §13.5): reuses release_window (Host, State, verification, latch, GUARDED_ENV,
train_ci_verdict), release_capability (phase capabilities, reservation, reconcile), release_control (STOP/pause/
epoch, the one global lock), release_delegation (standing policy). New: queue/classifier interfaces, manifest,
scratch integration, bisect, CI evidence reader, GitHub writer interface, event log, reconcile, quarantine.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

try:
    from scripts import release_window as RW
    from scripts.lib import release_capability as CAP
    from scripts.lib import release_control as RC
    from scripts.lib import release_delegation as RD
    from scripts.lib import release_train_contracts as TC
    from scripts.lib import release_train_queue as Q
except ImportError:  # pragma: no cover - scripts/ on sys.path
    import release_window as RW  # type: ignore[no-redef]
    from lib import release_capability as CAP  # type: ignore[no-redef]
    from lib import release_control as RC  # type: ignore[no-redef]
    from lib import release_delegation as RD  # type: ignore[no-redef]
    from lib import release_train_contracts as TC  # type: ignore[no-redef]
    from lib import release_train_queue as Q  # type: ignore[no-redef]

CONTROLLER_VERSION = "release_train_controller/1"
SCHEMA_MANIFEST = "TrainCandidate@v1"
SCHEMA_EVENT = "TrainEvent@v1"
SCHEMA_OUTCOME = "TrainOutcome@v1"
SCHEMA_RUN = "ReleaseTrainRun@v1"
SCHEMA_STATE = "ReleaseTrainState@v1"

#: The CLI refuses --live while this is BUILD_ONLY. Arming is an operator act (plan "Not in scope of approval").
TRAIN_CONTROLLER_STATUS = "BUILD_ONLY"
#: The real GitHub writer refuses until D2 (GitHub App) and the AGENTS 17.0.0 amendment are ACTIVE.
GITHUB_WRITES_STATUS = "PROPOSED"

TZ = RW.TZ
REQUIRED_CHECKS = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")
BATCH_QUALIFIER = "ci-gate"
TRUSTED_CHECK_APPS = frozenset({"github-actions"})
ACTOR = RC.Actor("controller", "release_window.train")

#: A train that changes any of these is refused (enhanced design §5: candidate code cannot modify the trusted
#: verifier or the checks that qualify it). Globs; a trailing "/" means the whole tree.
PROTECTED_SURFACES = (
    "scripts/release_window.py",
    "scripts/lib/release_train_controller.py",
    "scripts/lib/release_capability.py",
    "scripts/lib/release_control.py",
    "scripts/lib/release_delegation.py",
    "scripts/release_control_cli.py",
    "scripts/cio_phase2_exact_main_deploy.sh",
    "scripts/release_grant_preflight.py",
    "scripts/lib/release_grant_binding.py",
    "scripts/lib/release_train_classify.py",
    "config/release_train_policy.json",
    "config/release_train_delegation.example.json",
    "config/schemas/release_delegation_v1.schema.json",
    ".github/workflows/",
    ".github/CODEOWNERS",
    ".githooks/",
    ".cursor/hooks/",
    "bin/guard",
    "AGENTS.md",
    "AI_WORK_POLICY.md",
)

#: Default slots when no delegation is readable (plan / dry run): the four operator windows, all disabled.
DEFAULT_SLOTS = (
    {"window_id": "1800", "start_et": "18:00", "duration_min": 90, "enabled": False, "role": "canary"},
    {"window_id": "0000", "start_et": "00:00", "duration_min": 120, "enabled": False, "role": "general"},
    {"window_id": "0600", "start_et": "06:00", "duration_min": 60, "enabled": False,
     "role": "requires_drain_or_non_disruptive_path"},
    {"window_id": "0800", "start_et": "08:00", "duration_min": 30, "enabled": False, "role": "last_enabled",
     "latest_start_et": "08:10", "skip_on_macro_days": True},
)

STATE_ROOT = RW.STATE_ROOT
HYGIENE_RECEIPT = STATE_ROOT / "data" / "runtime" / "pr-hygiene-audit_last.json"
HOST_CONFIG = Path.home() / ".config" / "tradeai" / "release_train"
MACRO_CALENDAR_PATH = HOST_CONFIG / "macro_calendar.json"
SCRATCH_ROOT = Path(os.environ.get("TRADEAI_RELEASE_TRAIN_SCRATCH", str(Path.home() / ".cache" / "rtc")))

# Outcomes (TrainOutcome@v1, docs/ops/RELEASE_TRAIN_API.md §8)
NO_OP, FAILED_PRE_MERGE, MERGED_NOT_LIVE = "NO_OP", "FAILED_PRE_MERGE", "MERGED_NOT_LIVE"
RELEASED_VERIFIED, ROLLED_BACK, ROLLBACK_FAILED = "RELEASED_VERIFIED", "ROLLED_BACK", "ROLLBACK_FAILED"
STOPPED, CANCELLED = "STOPPED", "CANCELLED"
TERMINAL_OUTCOMES = frozenset({NO_OP, FAILED_PRE_MERGE, MERGED_NOT_LIVE, RELEASED_VERIFIED, "RELEASED_OBSERVING",
                               ROLLED_BACK, ROLLBACK_FAILED, STOPPED, CANCELLED})

EXIT_OK, EXIT_REFUSED, EXIT_STOPPED = 0, 2, 3
EXIT_ROLLED_BACK, EXIT_ROLLBACK_FAILED, EXIT_UNCERTAIN, EXIT_MERGED_NOT_LIVE = 4, 5, 6, 7
OUTCOME_EXIT = {NO_OP: EXIT_OK, RELEASED_VERIFIED: EXIT_OK, FAILED_PRE_MERGE: EXIT_STOPPED, CANCELLED: EXIT_STOPPED,
                STOPPED: EXIT_STOPPED, MERGED_NOT_LIVE: EXIT_MERGED_NOT_LIVE, ROLLED_BACK: EXIT_ROLLED_BACK,
                ROLLBACK_FAILED: EXIT_ROLLBACK_FAILED}
ALERT_PRIORITY = {ROLLBACK_FAILED: "P1", ROLLED_BACK: "P1", MERGED_NOT_LIVE: "P1", STOPPED: "P2",
                  FAILED_PRE_MERGE: "P2"}

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPENDS_RE = re.compile(r"(?im)^\s*(?:depends[- ]on|stacked[- ]on)\s*:?\s*((?:#\d+[\s,]*)+)")


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj: Any) -> bytes:
    return RD.canonical(obj)


def digest(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(obj)).hexdigest()


def is_protected(path: str) -> bool:
    for pat in PROTECTED_SURFACES:
        if pat.endswith("/"):
            if path.startswith(pat):
                return True
        elif path == pat or fnmatch(path, pat):
            return True
    return False


class Halt(Exception):
    """Ends the train with a TrainOutcome@v1 outcome (or a refusal before any claim)."""

    def __init__(self, outcome: str, reason: str, detail: str = "", *, code: Optional[int] = None,
                 refusal: bool = False) -> None:
        super().__init__(f"{outcome}:{reason}")
        self.outcome, self.reason, self.detail, self.refusal = outcome, reason, detail, refusal
        self.code = code if code is not None else (EXIT_REFUSED if refusal else OUTCOME_EXIT.get(outcome, 3))


# ── windows ───────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TrainWindow:
    slot: str
    role: str
    start: datetime
    duration_min: int
    enabled: bool
    latest_start_et: Optional[str] = None
    skip_on_macro_days: bool = False

    @property
    def window_id(self) -> str:
        """ISO local start with its UTC offset: unambiguous across DST (a repeated hour has two offsets)."""
        return self.start.isoformat(timespec="minutes")

    @property
    def claim_key(self) -> str:
        return f"{self.start.strftime('%Y%m%d')}-{self.slot}"

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_min)

    def train_id(self, suffix: str) -> str:
        return f"rt-{self.start.strftime('%Y%m%d')}-{self.slot}-{suffix}"


def local_start(day: date, hhmm: str) -> Optional[datetime]:
    """The first occurrence (fold=0) of HH:MM on ``day`` in America/New_York; None when the local time does not
    exist (spring-forward gap). A repeated local time (fall-back) maps to its first occurrence only."""
    hh, mm = int(hhmm[:2]), int(hhmm[2:])
    dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
    rt = dt.astimezone(timezone.utc).astimezone(TZ)
    if (rt.hour, rt.minute) != (hh, mm):
        return None
    return dt


def slots_from(delegation: Optional[dict]) -> list[dict]:
    if isinstance(delegation, dict):
        slots = ((delegation.get("windows") or {}).get("slots"))
        if isinstance(slots, list) and slots:
            return [dict(s) for s in slots]
    return [dict(s) for s in DEFAULT_SLOTS]


def window_at(now: datetime, slots: list[dict], *, lead_min: int, grace_min: int) -> tuple[Optional[TrainWindow], str]:
    """(window, "open"|"lead") when ``now`` is within [start - lead, start + grace) of a slot; (None, why) otherwise.
    No catch-up: past the grace the slot is gone until tomorrow."""
    local = now.astimezone(TZ)
    best: Optional[tuple[TrainWindow, str]] = None
    for s in slots:
        hhmm = str(s.get("window_id") or str(s.get("start_et", "")).replace(":", ""))
        for day in (local.date() - timedelta(days=1), local.date(), local.date() + timedelta(days=1)):
            start = local_start(day, hhmm)
            if start is None:
                continue
            if start - timedelta(minutes=lead_min) <= now < start + timedelta(minutes=grace_min):
                w = TrainWindow(hhmm, str(s.get("role") or ""), start, int(s.get("duration_min") or 60),
                                bool(s.get("enabled")), s.get("latest_start_et"), bool(s.get("skip_on_macro_days")))
                phase = "open" if now >= start else "lead"
                if best is None or start < best[0].start:
                    best = (w, phase)
    if best:
        return best
    return None, "off_window"


def next_windows(now: datetime, slots: list[dict], n: int = 4) -> list[dict]:
    out = []
    local = now.astimezone(TZ)
    for s in slots:
        hhmm = str(s.get("window_id"))
        for k in range(0, 3):
            start = local_start(local.date() + timedelta(days=k), hhmm)
            if start is not None and start > now:
                out.append({"slot": hhmm, "window_id": start.isoformat(timespec="minutes"),
                            "enabled": bool(s.get("enabled")), "role": s.get("role")})
                break
    return sorted(out, key=lambda r: r["window_id"])[:n]


class DrainProbe(Protocol):
    def check(self, window: TrainWindow) -> tuple[bool, str]: ...


class UnprovenDrain:
    """06:00 needs an explicit drain or a demonstrated non-disruptive release path (design §6). None is proven."""

    def check(self, window: TrainWindow) -> tuple[bool, str]:  # noqa: ARG002
        return False, "no service drain or non-disruptive release path has been proven for 06:00 (plan Phase 7)"


class MacroCalendar:
    """Operator-supplied 08:30 macro-release calendar (``MacroReleaseCalendar@v1``), read fail closed.

    The repository declares no macro-events provider (scripts/economic_calendar.py; FMP retired 2026-09-13), so
    until the operator provides ``~/.config/tradeai/release_train/macro_calendar.json`` the verdict is UNAVAILABLE
    and the 08:00 window is skipped. Body: {"schema", "as_of", "source", "covers_from", "covers_through",
    "release_days_0830": ["YYYY-MM-DD", ...]}."""

    SCHEMA = "MacroReleaseCalendar@v1"

    def __init__(self, path: Path = MACRO_CALENDAR_PATH, *, max_age_h: float = 168.0) -> None:
        self.path, self.max_age_h = Path(path), max_age_h

    def verdict(self, day: date, now: datetime) -> tuple[str, str]:
        if not os.path.lexists(self.path):
            return "UNAVAILABLE", (f"{self.path} absent; the repo has no macro-calendar provider "
                                   "(scripts/economic_calendar.py declares the gap)")
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(body, dict) or body.get("schema") != self.SCHEMA:
                return "UNAVAILABLE", "calendar schema is not MacroReleaseCalendar@v1"
            as_of = datetime.fromisoformat(str(body["as_of"]))
            if as_of.tzinfo is None:
                return "UNAVAILABLE", "calendar as_of has no offset"
            frm = date.fromisoformat(str(body["covers_from"]))
            thru = date.fromisoformat(str(body["covers_through"]))
            days = {date.fromisoformat(str(d)) for d in body["release_days_0830"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return "UNAVAILABLE", f"calendar unreadable: {type(exc).__name__}"
        age_h = (now - as_of).total_seconds() / 3600
        if age_h > self.max_age_h or age_h < -1:
            return "STALE", f"calendar as_of {as_of.isoformat()} is {age_h:.0f} h old (max {self.max_age_h:.0f})"
        if not frm <= day <= thru:
            return "STALE", f"calendar covers {frm}..{thru}, not {day}"
        if day in days:
            return "MACRO_DAY", f"{day} has an 08:30 macro release"
        return "CLEAR", f"{day} has no 08:30 macro release ({body.get('source')})"


class Measurements:
    """Durations of past trains (promote, verify, rollback seconds), append-only JSONL in the state dir."""

    def __init__(self, path: Path, *, window: int = 10) -> None:
        self.path, self.window = Path(path), window

    def rows(self) -> list[dict]:
        out = []
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        out.append(row)
        except OSError:
            return []
        return out[-200:]

    def worst(self, key: str) -> Optional[float]:
        vals = [float(r[key]) for r in self.rows() if isinstance(r.get(key), (int, float)) and r[key] >= 0]
        return max(vals[-self.window:]) if vals else None

    def append(self, row: dict) -> None:
        RC._append_jsonl(self.path, row)


def latest_activation_start(window: TrainWindow, m: Measurements, *, buffer_min: float,
                            deadline: str = "09:00") -> tuple[Optional[datetime], str]:
    """09:00 minus measured promote + verify + rollback minus the buffer; also capped by the delegation's static
    ``latest_start_et``. None (skip) when any of the three has never been measured."""
    parts = {k: m.worst(k) for k in ("promote_s", "verify_s", "rollback_s")}
    missing = [k for k, v in parts.items() if v is None]
    if missing:
        return None, f"unmeasured: {','.join(missing)} (08:00 needs measured promote, verify and rollback)"
    dl = local_start(window.start.date(), deadline.replace(":", ""))
    if dl is None:
        return None, "deadline does not exist on this day"
    latest = dl - timedelta(seconds=sum(parts.values())) - timedelta(minutes=buffer_min)
    if window.latest_start_et:
        static = local_start(window.start.date(), window.latest_start_et.replace(":", ""))
        if static is not None and static < latest:
            latest = static
    return latest, f"09:00 - {sum(parts.values()):.0f}s measured - {buffer_min:g} min buffer -> {latest.isoformat()}"


# ── queue and classification ──────────────────────────────────────────────────────────────────────

@dataclass
class QueueEntry:
    pr: int
    head_sha: str
    base_ref: str = "main"
    head_ref: str = ""
    title: str = ""
    draft: bool = False
    labels: tuple = ()
    depends_on: tuple = ()
    files: Optional[tuple] = None
    census: dict = field(default_factory=dict)


@dataclass
class QueueSnapshot:
    source: str
    as_of: Optional[str]
    complete: bool
    entries: list
    reasons: list = field(default_factory=list)


class QueueSource(Protocol):
    name: str

    def snapshot(self) -> QueueSnapshot: ...


def parse_depends(body: str) -> tuple:
    out: list[int] = []
    for m in _DEPENDS_RE.finditer(body or ""):
        out += [int(n) for n in re.findall(r"#(\d+)", m.group(1))]
    return tuple(dict.fromkeys(out))


class HygieneReceiptGhQueueSource:
    """The queue today: the PR-hygiene lane receipt (census, holds, conflicts) joined with ``gh pr list`` (read-only).

    Fail closed: a missing, unreadable or stale (> ``max_age_h``) receipt, or a ``gh`` failure, gives an
    INCOMPLETE snapshot, and the controller selects nothing from an incomplete snapshot."""

    name = "pr-hygiene-receipt+gh-pr-list"

    def __init__(self, *, receipt: Path = HYGIENE_RECEIPT, repo_dir: Path = RW.RELEASE_CHECKOUT,
                 max_age_h: float = 36.0, runner: Optional[Callable] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.receipt, self.repo_dir, self.max_age_h = Path(receipt), Path(repo_dir), max_age_h
        self.runner = runner or subprocess.run
        self.clock = clock

    def _receipt(self) -> tuple[Optional[dict], list[str]]:
        try:
            body = json.loads(self.receipt.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, [f"no_receipt:{self.receipt}"]
        except (OSError, ValueError) as exc:
            return None, [f"receipt_unreadable:{type(exc).__name__}"]
        summary = body.get("summary") if isinstance(body, dict) else None
        if not isinstance(summary, dict):
            return None, ["receipt_unreadable:no summary"]
        as_of = summary.get("as_of") or body.get("finished_at")
        try:
            ts = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None, ["receipt_unreadable:as_of"]
        if self.clock() - ts > self.max_age_h * 3600:
            return summary, [f"receipt_stale:{as_of}"]
        return summary, []

    def snapshot(self) -> QueueSnapshot:
        summary, reasons = self._receipt()
        fields = "number,headRefOid,baseRefName,headRefName,title,isDraft,labels,body,files"
        try:
            p = self.runner(["gh", "pr", "list", "--state", "open", "--limit", "500", "--json", fields],
                            capture_output=True, text=True, timeout=120, check=True, cwd=str(self.repo_dir))
            rows = json.loads(p.stdout or "[]")
            if not isinstance(rows, list):
                raise ValueError("not a list")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return QueueSnapshot(self.name, None, False, [], reasons + [f"gh_pr_list_failed:{type(exc).__name__}"])
        if len(rows) >= 500:
            reasons.append("possible_truncation")
        census = {}
        for r in (summary or {}).get("prs") or []:
            if isinstance(r, dict) and isinstance(r.get("number"), int):
                census[r["number"]] = r
        entries = []
        head_to_pr = {str(r.get("headRefName")): r.get("number") for r in rows if isinstance(r, dict)}
        for r in rows:
            if not isinstance(r, dict) or not isinstance(r.get("number"), int):
                reasons.append("row_without_number")
                continue
            deps = list(parse_depends(r.get("body") or ""))
            base = str(r.get("baseRefName") or "")
            if base and base != "main" and head_to_pr.get(base):
                deps.append(int(head_to_pr[base]))
            files = tuple(f.get("path") for f in (r.get("files") or []) if isinstance(f, dict) and f.get("path"))
            entries.append(QueueEntry(
                pr=r["number"], head_sha=str(r.get("headRefOid") or ""), base_ref=base,
                head_ref=str(r.get("headRefName") or ""), title=str(r.get("title") or "")[:200],
                draft=bool(r.get("isDraft")),
                labels=tuple(sorted(str(lab.get("name")) for lab in (r.get("labels") or []) if isinstance(lab, dict))),
                depends_on=tuple(dict.fromkeys(deps)), files=files if len(files) < 100 else None,
                census=census.get(r["number"], {})))
        as_of = (summary or {}).get("as_of")
        return QueueSnapshot(self.name, as_of, not reasons, entries, reasons)


class Phase1StoreQueueSource:
    """The Phase 1 store: ``release_queue`` projection rows (``release_train_queue.read_queue``) in a riding state
    (submitted / classified / ready). The controller re-classifies every row itself and re-reads each head from
    GitHub at freeze. NOT_MIGRATED / DB_UNAVAILABLE give an incomplete snapshot whose reason starts with
    ``store:`` so ``FallbackQueueSource`` can tell "store absent" from "store empty"."""

    name = "phase1:release_queue"
    RIDING = ("submitted", "classified", "ready")

    def __init__(self, conn_factory: Optional[Callable[[], Any]] = None) -> None:
        self.conn_factory = conn_factory or default_conn_factory

    def snapshot(self) -> QueueSnapshot:
        try:
            conn = self.conn_factory()
        except Exception as exc:  # noqa: BLE001
            return QueueSnapshot(self.name, None, False, [], [f"store:db_unavailable:{type(exc).__name__}"])

        def dbq(sql: str, params: Any = None, fetch: str = "all") -> Any:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone() if fetch == "one" else cur.fetchall()

        try:
            res = Q.read_queue(dbq, limit=500)
        except Exception as exc:  # noqa: BLE001
            return QueueSnapshot(self.name, None, False, [], [f"store:error:{type(exc).__name__}"])
        finally:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
        if res.get("store_state") != Q.OK:
            return QueueSnapshot(self.name, res.get("as_of"), False, [],
                                 [f"store:{res.get('reason') or str(res.get('store_state')).lower()}"])
        entries = []
        for r in res.get("rows") or []:
            if r.get("state") not in self.RIDING:
                continue
            entries.append(QueueEntry(pr=int(r["pr_number"]), head_sha=str(r.get("head_sha") or ""),
                                      depends_on=tuple(int(d) for d in (r.get("depends_on") or [])),
                                      census={"queue_state": r.get("state"), "risk_class": r.get("risk_class")}))
        reasons = ["possible_truncation"] if len(res.get("rows") or []) >= 500 else []
        return QueueSnapshot(self.name, res.get("as_of"), not reasons, entries, reasons)


class FallbackQueueSource:
    """Phase 1 store first; when it is NOT_MIGRATED or unreachable (reason ``store:*``), the PR-hygiene receipt +
    gh source. A readable store that is empty is a real empty and never falls back."""

    def __init__(self, primary: QueueSource, fallback: QueueSource) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}|{fallback.name}"

    def snapshot(self) -> QueueSnapshot:
        snap = self.primary.snapshot()
        if snap.complete or not any(str(r).startswith("store:") for r in snap.reasons):
            return snap
        fb = self.fallback.snapshot()
        fb.reasons = list(fb.reasons)
        fb.source = f"{fb.source} (fallback: {self.primary.name} {';'.join(snap.reasons)})"
        return fb


def default_queue_source() -> QueueSource:
    return FallbackQueueSource(Phase1StoreQueueSource(), HygieneReceiptGhQueueSource())


class Classifier(Protocol):
    version: str
    policy_version: Optional[str]

    def classify(self, entry: QueueEntry, change: Optional[dict]) -> tuple[str, list[str]]: ...


class HoldAllClassifier:
    """Fallback when the Phase 1 classifier cannot be loaded or its policy is invalid: every PR is HELD (unknown risk
    is held; enhanced design §4)."""

    version = "hold-all-stub/1"
    policy_version: Optional[str] = None

    def __init__(self, why: str = "classifier unavailable") -> None:
        self.why = why

    def classify(self, entry: QueueEntry, change: Optional[dict]) -> tuple[str, list[str]]:  # noqa: ARG002
        return "held", [f"{self.why}: unknown risk is held"]


class PolicyClassifier:
    """The Phase 1 classifier: ``scripts/lib/release_train_classify.classify_change`` with
    ``config/release_train_policy.json``. No change set (files unknown) is HELD; a classifier error is HELD."""

    def __init__(self, module: Any, policy: dict, tiers: Any, impact_map: Any) -> None:
        self.m, self.policy, self.tiers, self.impact_map = module, policy, tiers, impact_map
        self.version = str(getattr(module, "CLASSIFIER_VERSION", "release_train_classify/?"))
        self.policy_version = (str(policy.get("policy_version") or "")[:40]) or None

    def classify(self, entry: QueueEntry, change: Optional[dict]) -> tuple[str, list[str]]:  # noqa: ARG002
        if not change or not change.get("paths"):
            return "held", ["no change set (changed files unknown): held"]
        try:
            res = self.m.classify_change(change, self.policy, tiers=self.tiers, impact_map=self.impact_map)
        except Exception as exc:  # noqa: BLE001 - a classifier failure never admits a change
            return "held", [f"classifier error {type(exc).__name__}: held"]
        cls = res.get("class")
        if cls not in TC.RISK_CLASSES:
            return "held", [f"classifier returned {cls!r}: held"]
        reasons = [f"{r.get('rule')}:{r.get('path')}" for r in (res.get("reasons") or [])][:6]
        if change.get("approximate"):
            reasons.append("approximate change set (gh file list; dry run only)")
        return cls, reasons


def load_classifier(*, closure: bool = True) -> Classifier:
    try:
        from scripts.lib import release_train_classify as M
    except ImportError as exc:
        return HoldAllClassifier(f"release_train_classify not importable ({type(exc).__name__})")
    try:
        policy = M.load_policy()
        errs = M.validate_policy(policy)
        if errs:
            return HoldAllClassifier("config/release_train_policy.json invalid: " + "; ".join(errs)[:160])
        tiers = M.TI.load_tiers()
        imap = M.load_impact_map(edges=policy["import_closure"].get("edges", "imports")) if closure else None
    except Exception as exc:  # noqa: BLE001
        return HoldAllClassifier(f"classifier inputs unavailable ({type(exc).__name__})")
    return PolicyClassifier(M, policy, tiers, imap)


def change_from_files(entry: QueueEntry) -> Optional[dict]:
    """Dry-run approximation from the gh file list: every path as modified (deletions and semantic JSON keys are
    unknown). The live run always classifies from git."""
    if entry.files is None:
        return None
    return {"paths": [{"path": f, "status": "M"} for f in entry.files], "head_sha": entry.head_sha,
            "approximate": True}


def change_from_git(repo: Path, base: str, entry: QueueEntry) -> Optional[dict]:
    """Fetch the PR head into the release checkout (refs/train-scratch/pr-N) and read base...head from git."""
    rc, _ = _run(["git", "-C", str(repo), "fetch", "-q", "origin",
                  f"+refs/pull/{entry.pr}/head:refs/train-scratch/pr-{entry.pr}"], timeout=600)
    if rc != 0:
        return None
    try:
        from scripts.lib import release_train_classify as M
        ch = M.changeset_from_git(base, entry.head_sha, root=repo)
    except Exception:  # noqa: BLE001
        return None
    if ch is None or ch.get("head_sha") != entry.head_sha:
        return None
    return ch


def order_members(entries: list[QueueEntry]) -> tuple[list[QueueEntry], dict[int, str]]:
    """Dependency order (each PR after the PRs it depends on), ties by PR number. A PR whose dependency is not in
    the set, or that sits in a cycle, is excluded with a reason."""
    by = {e.pr: e for e in entries}
    excluded: dict[int, str] = {}
    changed = True
    while changed:
        changed = False
        for e in list(by.values()):
            missing = [d for d in e.depends_on if d not in by]
            if missing:
                excluded[e.pr] = f"DEPENDENCY_NOT_IN_TRAIN:{missing}"
                by.pop(e.pr)
                changed = True
    out: list[QueueEntry] = []
    placed: set[int] = set()
    remaining = dict(by)
    while remaining:
        ready = sorted(p for p, e in remaining.items() if all(d in placed for d in e.depends_on))
        if not ready:
            for p in remaining:
                excluded[p] = "DEPENDENCY_CYCLE"
            break
        p = ready[0]
        out.append(remaining.pop(p))
        placed.add(p)
    return out, excluded


def dependents_of(pr: int, members: list[dict]) -> set[int]:
    out: set[int] = set()
    frontier = {pr}
    while frontier:
        nxt = {m["pr"] for m in members if set(m.get("depends_on") or ()) & frontier and m["pr"] not in out}
        out |= nxt
        frontier = nxt
    return out


# ── scratch integration and local test ────────────────────────────────────────────────────────────

def _run(argv: list[str], *, cwd: Optional[Path] = None, env: Optional[dict] = None, timeout: float = 600,
         preexec: Optional[Callable] = None) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None,
                           env=env, preexec_fn=preexec)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout:.0f}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {str(exc)[:200]}"


class GitWorkspace:
    """An isolated scratch worktree of ``repo``. Merges, regeneration and tests happen only here; nothing in it is
    pushed except through the build/publish capability. Never removed by the controller (AGENTS §0 rule 6)."""

    IDENT = ["-c", "user.name=release-train", "-c", "user.email=release-train@localhost"]

    def __init__(self, repo: Path, path: Path, *, remote: str = "origin", env: Optional[dict] = None) -> None:
        self.repo, self.path, self.remote = Path(repo), Path(path), remote
        # Commands that run inside the candidate tree get a built environment (no credentials) and the TRUSTED
        # hooks of the release checkout, never hooks a PR under test could have changed.
        self.env = env
        rc, out = _run(["git", "-C", str(self.repo), "config", "--get", "core.hooksPath"], timeout=30)
        hp = out.strip() if rc == 0 else ""
        self.hooks = ["-c", f"core.hooksPath={(self.repo / hp) if hp and not hp.startswith('/') else hp}"] if hp else []

    def git(self, *args: str, timeout: float = 300) -> tuple[int, str]:
        return _run(["git", *self.IDENT, *self.hooks, "-C", str(self.path), *args], timeout=timeout, env=self.env)

    def repo_git(self, *args: str, timeout: float = 600) -> tuple[int, str]:
        """Fetches run in the release checkout itself (its own credentials; no candidate code executes)."""
        return _run(["git", "-C", str(self.repo), *args], timeout=timeout)

    def create(self, base: str) -> None:
        if (self.path / ".git").exists():
            rc, out = self.git("checkout", "-q", "-f", "--detach", base)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rc, out = _run(["git", "-C", str(self.repo), "worktree", "add", "-q", "--detach", str(self.path), base],
                           timeout=600)
        if rc != 0:
            raise Halt(FAILED_PRE_MERGE, "SCRATCH_WORKTREE_FAILED", out.strip()[-300:])

    def reset(self, base: str) -> None:
        self.git("merge", "--abort")
        rc, out = self.git("checkout", "-q", "-f", "--detach", base)
        if rc != 0:
            raise Halt(FAILED_PRE_MERGE, "SCRATCH_RESET_FAILED", out.strip()[-300:])

    def fetch_pr(self, pr: int) -> Optional[str]:
        rc, _ = self.repo_git("fetch", "-q", self.remote, f"+refs/pull/{pr}/head:refs/train-scratch/pr-{pr}")
        if rc != 0:
            return None
        rc, out = self.repo_git("rev-parse", f"refs/train-scratch/pr-{pr}")
        return out.strip() if rc == 0 and SHA_RE.match(out.strip()) else None

    def changed_files(self, base: str, head: str) -> Optional[list[str]]:
        rc, out = self.git("diff", "--name-only", f"{base}...{head}")
        return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else None

    def diff_files(self, a: str, b: str) -> Optional[list[str]]:
        rc, out = self.git("diff", "--name-only", a, b)
        return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else None

    def merge(self, sha: str, message: str) -> tuple[bool, str]:
        rc, out = self.git("merge", "--no-ff", "--no-edit", "-m", message, sha, timeout=600)
        if rc == 0:
            return True, out.strip()[-200:]
        self.git("merge", "--abort")
        return False, out.strip()[-400:]

    def head(self) -> str:
        rc, out = self.git("rev-parse", "HEAD")
        return out.strip() if rc == 0 else ""

    def commit_tracked(self, message: str) -> Optional[str]:
        rc, out = self.git("status", "--porcelain", "--untracked-files=no")
        if rc != 0 or not out.strip():
            return None
        self.git("add", "-u")
        rc, out = self.git("commit", "-q", "-m", message)
        if rc != 0:
            raise Halt(FAILED_PRE_MERGE, "REGENERATE_COMMIT_FAILED", out.strip()[-300:])
        return self.head()


#: Generated files are regenerated ONCE after all merges. GATES: on main the gate list is a literal tuple in
#: scripts/run_cio_hardening_ci.py and (after ci/deconflict-gates-index) one file per gate; neither is generated,
#: so the gates step is a registry check that fails closed on a malformed or dangling registration.
REGENERATORS: tuple = (
    ("docs_index", ["bash", "scripts/regenerate_generated_files.sh"]),
    ("gates_registry", ["{python}", "scripts/run_cio_hardening_ci.py", "--list-plan"]),
)

#: The local test worker's environment is BUILT from this allowlist; nothing else is inherited.
WORKER_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "TZ", "TERM")
WORKER_ENV_FIXED = {"TRADE_AI_CI": "1", "CIO_TELEGRAM_INTERDICT": "1", "ENABLE_TELEGRAM": "0",
                    "PYTHONDONTWRITEBYTECODE": "1", "TRADEAI_RELEASE_TRAIN_WORKER": "1", "PYTHONHASHSEED": "0"}
WORKER_ENV_FORBIDDEN = re.compile(
    r"^(DB_|PG|DATABASE|POSTGRES|GH_|GITHUB_|TELEGRAM|ALPACA|SCHWAB|MOOMOO|OPENAI|ANTHROPIC|AWS_|DEEPSEEK|BRAVE)"
    r"|(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|_KEY|APIKEY|DSN)", re.I)


def worker_env(base: dict, *, home: Path, tmp: Path) -> dict:
    env = {k: base[k] for k in WORKER_ENV_ALLOW if k in base}
    env.update(WORKER_ENV_FIXED)
    env["HOME"], env["TMPDIR"] = str(home), str(tmp)
    bad = [k for k in env if WORKER_ENV_FORBIDDEN.search(k)]
    if bad:
        raise Halt(FAILED_PRE_MERGE, "WORKER_ENV_FORBIDDEN", ",".join(bad))
    return env


@dataclass
class TestResult:
    ok: bool
    rc: int
    seconds: float
    tail: str = ""


class LocalTester:
    """Runs the test command in the scratch worktree, no production credentials, an rlimit on CPU time and a wall
    timeout. The command defaults to the hardening runner's PR profile against the frozen base."""

    def __init__(self, *, command: Optional[list[str]] = None, python: Optional[str] = None,
                 cpu_limit_s: int = 3600, base_env: Optional[dict] = None,
                 runner: Optional[Callable] = None) -> None:
        self.command, self.python = command, python or "python3"
        self.cpu_limit_s = cpu_limit_s
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.runner = runner or _run

    def argv(self, base_sha: str) -> list[str]:
        cmd = self.command or ["{python}", "scripts/run_cio_hardening_ci.py", "--profile", "pr", "--base", "{base}"]
        return [c.replace("{python}", self.python).replace("{base}", base_sha) for c in cmd]

    def run(self, workdir: Path, base_sha: str, *, timeout: float, scratch: Path, now: Callable[[], float]) -> TestResult:
        home, tmp = scratch / "home", scratch / "tmp"
        home.mkdir(parents=True, exist_ok=True)
        tmp.mkdir(parents=True, exist_ok=True)
        env = worker_env(self.base_env, home=home, tmp=tmp)
        cpu = self.cpu_limit_s

        def _limits() -> None:  # pragma: no cover - runs in the child
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

        t0 = now()
        rc, out = self.runner(self.argv(base_sha), cwd=workdir, env=env, timeout=max(1.0, timeout),
                              preexec=_limits)
        return TestResult(rc == 0, rc, now() - t0, out.strip()[-600:])


# ── CI evidence (read-only) ───────────────────────────────────────────────────────────────────────

def check_evidence(runs: list[dict], sha: str, required: tuple = REQUIRED_CHECKS, *, now: float) -> dict:
    """Latest run per required check name on exactly ``sha`` from a trusted app. Untrusted-app runs and runs on any
    other SHA are recorded as ignored, never counted."""
    chosen: dict[str, dict] = {}
    ignored = []
    for r in runs or []:
        if not isinstance(r, dict) or r.get("name") not in required:
            continue
        if r.get("head_sha") != sha:
            ignored.append({"name": r.get("name"), "why": "other_sha", "head_sha": str(r.get("head_sha"))[:12]})
            continue
        if r.get("app") not in TRUSTED_CHECK_APPS:
            ignored.append({"name": r.get("name"), "why": "untrusted_app", "app": r.get("app")})
            continue
        prev = chosen.get(r["name"])
        if prev is None or int(r.get("id") or 0) > int(prev.get("id") or 0):
            chosen[r["name"]] = r
    checks = [{"name": c["name"], "head_sha": c["head_sha"], "status": c.get("status"),
               "conclusion": c.get("conclusion"), "id": c.get("id"), "app": c.get("app")} for c in chosen.values()]
    return {"sha": sha, "checks": sorted(checks, key=lambda c: c["name"]), "ignored": ignored,
            "collected_at": utc_iso(now), "required": list(required)}


def evidence_verdict(ev: dict, required: tuple = REQUIRED_CHECKS) -> tuple[str, list[str]]:
    """GREEN only when every required check's latest trusted run on the SHA is completed/success. Missing or in
    flight is PENDING; neutral, skipped, cancelled, stale, timed_out or failure is RED. Never "not failure"."""
    by = {c["name"]: c for c in ev.get("checks") or []}
    pending, red = [], []
    for name in required:
        c = by.get(name)
        if c is None or c.get("status") != "completed":
            pending.append(f"{name}:{'missing' if c is None else c.get('status')}")
        elif c.get("conclusion") != "success":
            red.append(f"{name}:{c.get('conclusion')}")
    if red:
        return "RED", red + pending
    if pending:
        return "PENDING", pending
    return "GREEN", []


# ── GitHub (read-only reader; mutating writer behind a capability) ─────────────────────────────────

class GitHubReader(Protocol):
    repository: str

    def main_head(self) -> str: ...

    def pr_head(self, pr: int) -> Optional[str]: ...

    def check_runs(self, sha: str) -> list[dict]: ...

    def commit_parents(self, sha: str) -> Optional[list[str]]: ...

    def contains(self, ancestor: str, descendant: str) -> Optional[bool]: ...

    def ref_sha(self, ref: str) -> Optional[str]: ...


class GhCliReader:
    """GET-only GitHub reads through ``gh api`` (no -X, no fields)."""

    def __init__(self, host: RW.Host) -> None:
        self.host = host
        self._repo: Optional[str] = None

    @property
    def repository(self) -> str:
        if self._repo is None:
            self._repo = self.host._repository()
        return self._repo

    def _get(self, path: str, jq: str) -> Any:
        rc, out = self.host._run(["gh", "api", path, "--jq", jq], timeout=60)
        if rc != 0:
            raise RuntimeError(f"gh api {path.split('?')[0]} failed")
        return json.loads(out or "null")

    def main_head(self) -> str:
        return self.host.main_head()

    def pr_head(self, pr: int) -> Optional[str]:
        try:
            return self._get(f"repos/{self.repository}/pulls/{int(pr)}", ".head.sha | tojson")
        except (RuntimeError, ValueError):
            return None

    def check_runs(self, sha: str) -> list[dict]:
        jq = "[.check_runs[] | {id, name, head_sha, status, conclusion, app: .app.slug}] | tojson"
        return list(self._get(f"repos/{self.repository}/commits/{sha}/check-runs?filter=latest&per_page=100", jq))

    def commit_parents(self, sha: str) -> Optional[list[str]]:
        try:
            return list(self._get(f"repos/{self.repository}/commits/{sha}", "[.parents[].sha] | tojson"))
        except (RuntimeError, ValueError):
            return None

    def contains(self, ancestor: str, descendant: str) -> Optional[bool]:
        try:
            status = self._get(f"repos/{self.repository}/compare/{ancestor}...{descendant}", ".status | tojson")
        except (RuntimeError, ValueError):
            return None
        return status in ("ahead", "identical")

    def ref_sha(self, ref: str) -> Optional[str]:
        try:
            return self._get(f"repos/{self.repository}/git/ref/{ref}", ".object.sha | tojson")
        except (RuntimeError, ValueError):
            return None


class GitHubWriter(Protocol):
    simulated: bool

    def push_train_ref(self, train_id: str, sha: str) -> dict: ...

    def open_or_update_batch_pr(self, train_id: str, sha: str, title: str, body: str) -> int: ...

    def merge_batch_pr(self, pr: int, expected_head_sha: str, message: str) -> str: ...


class WriterNotArmed(RuntimeError):
    pass


class GhCliWriter:
    """The live writer. It can only publish ``refs/heads/train/<id>`` and open/update/merge that batch PR. It refuses
    to construct while GITHUB_WRITES_STATUS is not ACTIVE (D2 GitHub App + AGENTS 17.0.0 are operator acts)."""

    simulated = False

    def __init__(self, host: RW.Host, reader: GhCliReader, *, status: Optional[str] = None) -> None:
        if (status or GITHUB_WRITES_STATUS) != "ACTIVE":
            raise WriterNotArmed(f"GitHub writes are {status or GITHUB_WRITES_STATUS}: decision D2 and the AGENTS "
                                 "17.0.0 amendment are not in force")
        self.host, self.reader = host, reader

    def push_train_ref(self, train_id: str, sha: str) -> dict:
        ref = f"refs/heads/train/{train_id}"
        if not (CAP.TRAIN_RE.match(train_id) and SHA_RE.match(sha)):
            raise ValueError("train id / sha")
        rc, out = self.host._run(["git", "-C", str(self.host.checkout), "push", "origin", f"{sha}:{ref}"], timeout=600)
        if rc != 0:
            raise RuntimeError(f"push refused rc={rc}: {out.strip()[-200:]}")
        return {"ref": ref, "sha": sha}

    def open_or_update_batch_pr(self, train_id: str, sha: str, title: str, body: str) -> int:
        repo = self.reader.repository
        head = f"train/{train_id}"
        rc, out = self.host._run(["gh", "api", f"repos/{repo}/pulls?head={repo.split('/')[0]}:{head}&state=open",
                                  "--jq", "[.[].number] | tojson"], timeout=60)
        nums = json.loads(out or "[]") if rc == 0 else []
        if nums:
            return int(nums[0])
        rc, out = self.host._run(["gh", "api", "-X", "POST", f"repos/{repo}/pulls", "-f", f"title={title}",
                                  "-f", f"head={head}", "-f", "base=main", "-f", f"body={body}",
                                  "--jq", ".number"], timeout=60)
        if rc != 0:
            raise RuntimeError(f"open PR failed rc={rc}")
        return int(out.strip())

    def merge_batch_pr(self, pr: int, expected_head_sha: str, message: str) -> str:
        repo = self.reader.repository
        rc, out = self.host._run(["gh", "api", "-X", "PUT", f"repos/{repo}/pulls/{int(pr)}/merge",
                                  "-f", f"sha={expected_head_sha}", "-f", "merge_method=merge",
                                  "-f", f"commit_title={message}", "--jq", ".sha"], timeout=120)
        if rc != 0:
            raise RuntimeError(f"merge refused rc={rc}: {out.strip()[-200:]}")
        return out.strip()


class SimulatedGitHubWriter:
    """Dry run: records exactly what would be written; writes nothing."""

    simulated = True

    def __init__(self, say: Callable[[str], None]) -> None:
        self.say = say
        self.actions: list[dict] = []

    def push_train_ref(self, train_id: str, sha: str) -> dict:
        self.actions.append({"action": "push_train_ref", "ref": f"refs/heads/train/{train_id}", "sha": sha})
        self.say(f"WOULD push {sha[:12]} -> refs/heads/train/{train_id} (the only ref the build capability allows)")
        return {"ref": f"refs/heads/train/{train_id}", "sha": sha, "simulated": True}

    def open_or_update_batch_pr(self, train_id: str, sha: str, title: str, body: str) -> int:
        self.actions.append({"action": "open_batch_pr", "head": f"train/{train_id}", "title": title})
        self.say(f"WOULD open/update batch PR head=train/{train_id} base=main title={title!r}")
        return 0

    def merge_batch_pr(self, pr: int, expected_head_sha: str, message: str) -> str:
        self.actions.append({"action": "merge_batch_pr", "pr": pr, "expected_head_sha": expected_head_sha})
        self.say(f"WOULD merge batch PR (merge_method=merge, sha={expected_head_sha[:12]} so a moved head is refused)")
        return "SIMULATED-MERGE-COMMIT"


# ── durable events ────────────────────────────────────────────────────────────────────────────────

class EventSink(Protocol):
    def append(self, event: dict) -> dict: ...


class InvalidTrainEvent(ValueError):
    pass


def validate_event(event: dict) -> None:
    errs = TC.validate_as(TC.TRAIN_EVENT, event)
    if errs:
        raise InvalidTrainEvent("; ".join(errs)[:500])


class JsonlEventSink:
    """Append-only ``train_events.jsonl``: one TrainEvent@v1 per line (validated), monotonically increasing ``seq``,
    fsync per row, flock-serialized. Never rewritten, never truncated. The local fallback of the Phase 1 store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _last_seq(self) -> int:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 65536))
                lines = fh.read().splitlines()
        except OSError:
            return 0
        for line in reversed(lines):
            try:
                return int(json.loads(line)["seq"])
            except (ValueError, KeyError, TypeError):
                continue
        return 0

    def append(self, event: dict) -> dict:
        validate_event(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_name(self.path.name + ".lock"), "a+") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                row = {**event, "seq": self._last_seq() + 1, "recorded_at": event["occurred_at"]}
                RC._append_jsonl(self.path, row)
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
        return {**row, "store": "jsonl"}


class MemoryEventSink:
    """Dry run: validated rows kept in memory and printed; nothing is written."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append(self, event: dict) -> dict:
        validate_event(event)
        row = {**event, "seq": len(self.rows) + 1, "store": "memory"}
        self.rows.append(row)
        return row


def default_conn_factory() -> Any:
    from scripts.session13_db import get_conn
    return get_conn()


class StoreEventSink:
    """The Phase 1 store (``release_queue_events``) through ``release_train_queue.append_event``. The store is probed
    once; when it reads NOT_MIGRATED or DB_UNAVAILABLE (or an append fails), the row goes to the JSONL fallback so
    the safety record is never lost. ``finish`` rebuilds the ``release_queue`` projection when the store is OK."""

    def __init__(self, conn_factory: Callable[[], Any], fallback: JsonlEventSink) -> None:
        self.conn_factory, self.fallback = conn_factory, fallback
        self.store_state: Optional[str] = None
        self.conn: Any = None
        self.errors: list[str] = []

    def _dbq(self, sql: str, params: Any = None, fetch: str = "all") -> Any:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if fetch == "one" else cur.fetchall()

    def probe(self) -> str:
        if self.store_state is None:
            try:
                self.conn = self.conn_factory()
                self.store_state = Q.probe(self._dbq)["state"]
                try:
                    self.conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001 - an unreachable store is DB_UNAVAILABLE, never empty
                self.store_state = Q.DB_UNAVAILABLE
                self.errors.append(f"connect:{type(exc).__name__}")
        return self.store_state

    def append(self, event: dict) -> dict:
        validate_event(event)
        if self.probe() == Q.OK:
            try:
                seq = Q.append_event(self.conn, event)
                return {**event, "seq": seq, "store": "postgres"}
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"append:{type(exc).__name__}")
                try:
                    self.conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
        return self.fallback.append(event)

    def finish(self) -> Optional[int]:
        if self.store_state != Q.OK:
            return None
        try:
            return Q.rebuild_projection(self.conn)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"projection:{type(exc).__name__}")
            return None


# ── the controller ────────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainConfig:
    lead_min: int = 90                      # integrate + local test may start this long before the window
    grace_min: int = 15                     # a window is claimable until start + grace; never caught up
    qualify_timeout_s: float = 5400.0
    main_ci_timeout_s: float = 5400.0
    poll_s: float = 60.0
    test_attempts: int = 6
    test_budget_s: float = 2700.0
    buffer_min: float = 10.0
    max_prs: int = 12
    scratch_root: Path = SCRATCH_ROOT
    regenerators: tuple = REGENERATORS
    dry_run_integrate: bool = False
    dry_run_local_test: bool = False
    simulate_classifier: Optional[str] = None     # dry run only: "allow" previews the pipeline past the stub


class TrainController:
    def __init__(self, *, host: RW.Host, state: RW.State, github: GitHubReader, queue: QueueSource,
                 classifier: Classifier, live: bool = False, writer: Optional[GitHubWriter] = None,
                 tester: Optional[LocalTester] = None, events: Optional[EventSink] = None,
                 delegation_path: Optional[Path] = None, key_path: Path = CAP.DEFAULT_KEY_PATH,
                 config: Optional[TrainConfig] = None, env: Optional[dict] = None,
                 drain: Optional[DrainProbe] = None, calendar: Optional[MacroCalendar] = None,
                 workspace_factory: Optional[Callable[[Path], GitWorkspace]] = None,
                 allow_repo_delegation: bool = False) -> None:
        self.host, self.state, self.github, self.queue, self.classifier = host, state, github, queue, classifier
        self.live = live
        self.cfg = config or TrainConfig()
        self.env = dict(os.environ if env is None else env)
        self.steps: list[str] = []
        self.writer: GitHubWriter = writer if writer is not None else SimulatedGitHubWriter(self.say)
        if live and getattr(self.writer, "simulated", False):
            raise ValueError("a live controller needs a real writer")
        if not live and not getattr(self.writer, "simulated", False):
            raise ValueError("a dry run never holds a real writer")
        self.tester = tester or LocalTester(python=str(getattr(host, "python", "python3")))
        self.events: EventSink = events if events is not None else (
            StoreEventSink(default_conn_factory, JsonlEventSink(state.root / "train_events.jsonl")) if live
            else MemoryEventSink())
        self.changeset: Callable[[QueueEntry, str], Optional[dict]] = (
            lambda e, base: change_from_git(host.checkout, base, e) if (live or self.cfg.dry_run_integrate)
            else change_from_files(e))
        self.delegation_path = delegation_path
        self.key_path = key_path
        self.allow_repo_delegation = allow_repo_delegation
        self.drain = drain or UnprovenDrain()
        self.calendar = calendar or MacroCalendar()
        self.measure = Measurements(state.root / "train_measurements.jsonl")
        self.workspace_factory = workspace_factory or (lambda p: GitWorkspace(host.checkout, p, env=worker_env(
            self.env, home=p.parent / "home", tmp=p.parent / "tmp")))
        self.control = RC.ReleaseControl(state.root, clock=self._ts)
        self.authority = CAP.CapabilityAuthority(state.root, key_path=key_path, delegation_path=delegation_path,
                                                 clock=self._ts, allow_repo_delegation=allow_repo_delegation)
        self.train_id: Optional[str] = None
        self.window: Optional[TrainWindow] = None
        self.tstate: dict = {}
        self.would_refuse: list[str] = []
        self.epoch_at_claim: Optional[int] = None
        self._train_lock: Any = None
        self.event_errors: list[str] = []

    # -- small helpers -------------------------------------------------------------------------------
    def _ts(self) -> float:
        return self.host.now().timestamp()

    def say(self, text: str) -> None:
        self.steps.append(text)

    def _train_dir(self) -> Path:
        return self.state.root / "trains" / str(self.train_id)

    _LEGACY = {"claimed": "selected", "outcome": "outcome_recorded"}
    _JOURNAL_ONLY = frozenset({"intent", "effect", "uncertain", "reconciled"})
    _PHASE_EVENT = {"frozen": ("frozen", "selected"), "integrating": ("integrating", "integrating"),
                    "tested": ("integrating", "integrating"), "waiting_window": ("waiting_window", "waiting_window"),
                    "qualifying": ("integrating", "integrating"), "qualified": ("qualified", "qualified"),
                    "merging": ("qualified", "qualified"), "merged": ("merged", "merged"),
                    "promoting": ("promoting", "promoting"), "verifying": ("verifying", "promoting")}
    _OUTCOME_STATE = {RELEASED_VERIFIED: "released", "RELEASED_OBSERVING": "observing", ROLLED_BACK: "rolled_back",
                      ROLLBACK_FAILED: "rollback_failed", MERGED_NOT_LIVE: "merged", STOPPED: "cancelled",
                      CANCELLED: "cancelled", FAILED_PRE_MERGE: "cancelled", NO_OP: None}

    def _event(self, event_type: str, state_after: Optional[str], payload: Optional[dict] = None, *,
               subject_kind: str = "train", pr: Optional[int] = None, idem: Optional[str] = None) -> dict:
        """One TrainEvent@v1 (validated) to the store / JSONL / memory sink. A PR state event's event_type is its
        state_after (contract rule). Intents and effects go to the local intent journal, not the event store
        (TrainEvent@v1 has no intent type; see the packet README)."""
        payload = json.loads(json.dumps(payload or {}, default=str))
        if event_type in self._JOURNAL_ONLY:
            self._journal({"kind": event_type, "train_id": self.train_id, "pr": pr, "state": state_after,
                           "idempotency_key": idem, **payload})
            return {}
        if not self.train_id or not TC.TRAIN_ID_RE.match(str(self.train_id)):
            return {}
        if subject_kind == "pr" and pr is not None:
            if state_after not in TC.QUEUE_STATES:
                return {}
            et = state_after
            payload.setdefault("step", event_type)
        else:
            subject_kind, et = "train", self._LEGACY.get(event_type, event_type)
            if state_after not in TC.QUEUE_STATES:
                state_after = None
        now = datetime.fromtimestamp(self._ts(), timezone.utc).isoformat(timespec="seconds")
        ev = {"schema": SCHEMA_EVENT, "event_id": f"rte-{uuid.uuid4().hex}", "event_type": et,
              "subject_kind": subject_kind,
              "subject_id": f"pr:{pr}" if subject_kind == "pr" else f"train:{self.train_id}",
              "pr_number": pr if subject_kind == "pr" else None, "train_id": self.train_id,
              "state_after": state_after, "actor": ACTOR.identity,
              "policy_version": self.tstate.get("classifier_policy_version"), "epoch": self.epoch_at_claim,
              "idempotency_key": idem if idem and len(idem) <= 200 else
              f"{self.train_id}:{et}:{pr or 'train'}:{uuid.uuid4().hex[:12]}",
              "occurred_at": now, "payload": payload, "evidence_refs": []}
        try:
            return self.events.append(ev)
        except InvalidTrainEvent as exc:
            # A contract defect must never strand a train mid-release: journal it, count it (tests assert zero).
            self.event_errors.append(f"{et}: {exc}"[:300])
            self._journal({"kind": "invalid_event", "errors": str(exc)[:500], "event": ev})
            return {}

    def _journal(self, row: dict) -> None:
        if not self.live:
            return
        RC._append_jsonl(self.state.root / "train_intents.jsonl", {"at": utc_iso(self._ts()), **row})

    def _save_state(self, **kw: Any) -> None:
        self.tstate.update(kw)
        if not self.live or not self.train_id:
            return
        self.tstate["updated_at"] = utc_iso(self._ts())
        body = {k: v for k, v in self.tstate.items() if not k.startswith("_")}
        RC._atomic_write_json(self._train_dir() / "state.json", {"schema": SCHEMA_STATE, **body})

    def _intent(self, action: str, detail: dict) -> str:
        """Persist the intent BEFORE the side effect (fsynced intent journal + train state)."""
        key = f"{self.train_id}:{action}:{uuid.uuid4().hex[:8]}"
        intents = list(self.tstate.get("intents") or [])
        intents.append({"key": key, "action": action, "status": "INTENT", "at": utc_iso(self._ts()), **detail})
        self._save_state(intents=intents, pending_intent=key)
        self._event("intent", self.tstate.get("phase", ""), {"action": action, **detail}, idem=key)
        return key

    def _effect(self, key: str, status: str, detail: dict) -> None:
        intents = list(self.tstate.get("intents") or [])
        for i in intents:
            if i["key"] == key:
                i.update(status=status, finished_at=utc_iso(self._ts()), result=detail)
        self._save_state(intents=intents, pending_intent=None)
        self._event("effect", self.tstate.get("phase", ""), {"intent": key, "status": status, **detail},
                    idem=f"{key}:effect")

    def _phase(self, phase: str, payload: Optional[dict] = None) -> None:
        self._save_state(phase=phase)
        et, st = self._PHASE_EVENT.get(phase, ("integrating", None))
        self._event(et, st, {"step": phase, **(payload or {})})

    def _members_event(self, state_after: str, prs: list, payload: Optional[dict] = None) -> None:
        for pr in prs:
            self._event(state_after, state_after, payload, subject_kind="pr", pr=int(pr))

    def _evidence(self, sha: str, kind: str, name: str, conclusion: str, **extra: Any) -> None:
        doc = {"schema": TC.TRAIN_EVIDENCE, "evidence_id": f"rtev-{uuid.uuid4().hex[:24]}",
               "train_id": self.train_id, "candidate_sha": sha, "kind": kind, "name": name[:200],
               "conclusion": conclusion,
               "collected_at": datetime.fromtimestamp(self._ts(), timezone.utc).isoformat(timespec="seconds"),
               "check_manifest_version": "rt-checks/1", **extra}
        self._event("evidence_recorded", None, doc)

    def _boundary(self, label: str, *, in_flight: bool = False) -> None:
        """A mutation boundary: STOP latch / STOP request / revoke / pause / epoch change stop the train here."""
        v = self.control.view()
        if not self.live:
            refusal = v.mutation_refusal(self.train_id)
            if refusal:
                self._would(f"at {label}: control state {refusal}")
            return
        if v.mode == RC.STOP_REQUESTED:
            self.control.acknowledge_stop(ACTOR)
            self.control.settle(ACTOR, in_flight=in_flight)
            raise Halt(self._stop_outcome(), "STOP_REQUESTED", f"acknowledged at {label}")
        refusal = v.mutation_refusal(self.train_id)
        if refusal:
            if v.mode in (RC.STOP_ACKNOWLEDGED, RC.SETTLING):
                self.control.settle(ACTOR, in_flight=in_flight)
            raise Halt(self._stop_outcome(), refusal, f"at {label}")
        if self.epoch_at_claim is not None and v.epoch != self.epoch_at_claim:
            raise Halt(self._stop_outcome(), "EPOCH_CHANGED", f"{self.epoch_at_claim} -> {v.epoch} at {label}")

    def _stop_outcome(self) -> str:
        return MERGED_NOT_LIVE if self.tstate.get("main_sha") else STOPPED

    def _fail_outcome(self) -> str:
        return MERGED_NOT_LIVE if self.tstate.get("main_sha") else FAILED_PRE_MERGE

    def _would(self, why: str) -> None:
        self.would_refuse.append(why)
        self.say(f"LIVE WOULD REFUSE: {why}")

    # -- the run -------------------------------------------------------------------------------------
    def run(self, now: Optional[datetime] = None) -> tuple[int, dict]:
        now = now or self.host.now()
        rec: dict = {"schema": SCHEMA_RUN, "mode": "live" if self.live else "dry_run",
                     "controller": CONTROLLER_VERSION, "started_at": utc_iso(now.timestamp())}
        self.say(f"release train {'LIVE' if self.live else 'DRY RUN'} at {now.astimezone(TZ).isoformat()}")
        claimed = False
        try:
            dv = self._preconditions(rec)
            w, phase = self._window(now, dv, rec)
            self.window = w
            self.train_id = w.train_id(uuid.uuid4().hex[:6])
            rec["train_id"] = self.train_id
            self.tstate["started_at"] = rec["started_at"]
            if self.live:
                self._claim(w, dv)
                claimed = True
            else:
                self.say(f"WOULD claim window {w.window_id} (claim key {w.claim_key}, O_EXCL) and train {self.train_id}")
            self._rules(w, now, rec)
            members, excluded = self._select(rec)
            manifest = self._freeze(w, members, dv, rec)
            cand = self._integrate_and_test(manifest, rec)
            self._wait_for_window(w, rec)
            batch = self._qualify(manifest, cand, rec)
            merge_sha = self._merge(manifest, cand, batch, rec)
            self._promote(manifest, cand, batch, merge_sha, rec)
        except Halt as h:
            rec.update(outcome=h.outcome, reason=h.reason, detail=h.detail)
            code = h.code
            if h.refusal:
                rec["refused"] = True
            self.say(f"=> {h.outcome} ({h.reason}{': ' + h.detail if h.detail else ''})")
        else:
            code = EXIT_OK
        finally:
            if claimed:
                self._terminal(rec)
            if self._train_lock is not None:
                self._train_lock.release()
        rec["exit_code"] = code
        rec["would_refuse"] = self.would_refuse
        rec["event_errors"] = self.event_errors
        rec["steps"] = self.steps
        rec["finished_at"] = utc_iso(self._ts())
        if isinstance(self.events, MemoryEventSink):
            rec["events"] = self.events.rows
        if isinstance(self.events, StoreEventSink):
            rec["event_store"] = {"state": self.events.store_state, "errors": self.events.errors,
                                  "projection_rows": self.events.finish()}
        return code, rec

    # -- preconditions -------------------------------------------------------------------------------
    def _preconditions(self, rec: dict) -> RD.DelegationVerdict:
        bad = RW.guarded_env_violations(self.env)
        if bad:
            raise Halt("REFUSED", "REFUSED_BYPASS_ENV", ",".join(bad), refusal=True)
        latch_state, latch = self.state.read_latch()
        rec["latch_state"] = latch_state
        if latch_state != "ABSENT":
            reason = "REFUSED_STOP_UNREADABLE" if latch_state == "UNREADABLE" else "REFUSED_STOP_LATCHED"
            if self.live:
                raise Halt("REFUSED", reason, json.dumps(latch)[:200], refusal=True)
            self._would(f"{reason} ({latch_state})")
        view = self.control.view()
        rec["control"] = {"mode": view.mode, "epoch": view.epoch, "error": view.error}
        refusal = view.mutation_refusal(None)
        if refusal:
            if self.live:
                raise Halt("REFUSED", f"REFUSED_{refusal}", view.error or "", refusal=True)
            self._would(f"control {refusal}")
        dv = RD.load(self.delegation_path, allow_repo_path=self.allow_repo_delegation)
        rec["delegation"] = {"code": dv.code, "authorized": dv.authorized, "digest": dv.digest}
        if not dv.authorized:
            if self.live:
                raise Halt("REFUSED", f"REFUSED_DELEGATION_{dv.code}", dv.detail[:200], refusal=True)
            self._would(f"delegation {dv.code}: {dv.detail[:120]}")
        elif view.accepted_policy_digest not in (None, dv.digest):
            if self.live:
                raise Halt("REFUSED", "REFUSED_POLICY_NOT_ACCEPTED", "delegation digest differs from the armed one",
                           refusal=True)
            self._would("delegation digest differs from the armed one")
        pending = self.pending_trains()
        if pending:
            if self.live:
                raise Halt("REFUSED", "REFUSED_RECONCILE_FIRST",
                           f"non-terminal trains {pending}: run train-reconcile", refusal=True)
            self._would(f"non-terminal trains need reconciliation first: {pending}")
        self._quarantine_lineage(rec)
        self.say(f"preconditions: latch {latch_state}, control {view.mode} epoch {view.epoch}, delegation {dv.code}")
        return dv

    def pending_trains(self) -> list[str]:
        out = []
        for p in sorted((self.state.root / "trains").glob("*/state.json")):
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out.append(p.parent.name + "(unreadable)")
                continue
            if not body.get("outcome"):
                out.append(p.parent.name)
        return out

    def quarantined(self) -> list[dict]:
        """Unresolved quarantine entries (append-only file; a later ``resolved`` row for the SHA clears it)."""
        rows = Measurements(self.state.root / "quarantine.jsonl").rows()
        open_: dict[str, dict] = {}
        for r in rows:
            sha = str(r.get("sha") or "")
            if r.get("kind") == "quarantine":
                open_[sha] = r
            elif r.get("kind") == "resolved":
                open_.pop(sha, None)
        return list(open_.values())

    def _quarantine_lineage(self, rec: dict) -> None:
        q = self.quarantined()
        rec["quarantine_open"] = [r.get("sha") for r in q]
        if not q:
            return
        try:
            main = self.github.main_head()
        except (RuntimeError, ValueError) as exc:
            raise Halt("REFUSED", "REFUSED_MAIN_UNREADABLE", str(exc)[:160], refusal=True) from exc
        for r in q:
            inside = self.github.contains(str(r.get("sha")), main)
            if inside is not False:   # True or unknown: fail closed
                why = (f"quarantined failed artifact {str(r.get('sha'))[:12]} is "
                       f"{'in' if inside else 'possibly in'} main's lineage; operator resolves first")
                if self.live:
                    raise Halt("REFUSED", "REFUSED_QUARANTINED_LINEAGE", why, refusal=True)
                self._would(why)

    # -- window ----------------------------------------------------------------------------------------
    def _window(self, now: datetime, dv: RD.DelegationVerdict, rec: dict) -> tuple[TrainWindow, str]:
        slots = slots_from(dv.delegation)
        w, phase = window_at(now, slots, lead_min=self.cfg.lead_min, grace_min=self.cfg.grace_min)
        rec["next_windows"] = next_windows(now, slots)
        if w is None:
            raise Halt("REFUSED", "REFUSED_OFF_WINDOW",
                       f"no window within -{self.cfg.lead_min}/+{self.cfg.grace_min} min; no catch-up", refusal=True)
        rec["window"] = {"slot": w.slot, "window_id": w.window_id, "role": w.role, "enabled": w.enabled,
                         "phase": phase, "start": w.start.isoformat(), "end": w.end.isoformat()}
        self.say(f"window {w.window_id} slot {w.slot} ({w.role}) {phase}; enabled={w.enabled}")
        if not w.enabled:
            if self.live:
                raise Halt("REFUSED", "REFUSED_WINDOW_DISABLED", w.slot, refusal=True)
            self._would(f"window {w.slot} is disabled in the delegation")
        return w, phase

    def _rules(self, w: TrainWindow, now: datetime, rec: dict) -> None:
        if w.slot == "0600":
            ok, why = self.drain.check(w)
            rec["drain"] = {"ok": ok, "detail": why}
            if not ok:
                raise Halt(NO_OP, "WINDOW_SKIPPED_NO_DRAIN", why)
        if w.slot == "0800" or w.skip_on_macro_days:
            verdict, why = self.calendar.verdict(w.start.date(), now)
            rec["macro_calendar"] = {"verdict": verdict, "detail": why}
            if verdict != "CLEAR":
                raise Halt(NO_OP, f"WINDOW_SKIPPED_MACRO_{verdict}", why)
        if w.slot == "0800" or w.latest_start_et:
            latest, why = latest_activation_start(w, self.measure, buffer_min=self.cfg.buffer_min)
            rec["latest_activation_start"] = {"at": latest.isoformat() if latest else None, "detail": why}
            if latest is None:
                raise Halt(NO_OP, "WINDOW_SKIPPED_UNMEASURED", why)
            if max(now, w.start) > latest:
                raise Halt(NO_OP, "WINDOW_SKIPPED_PAST_LATEST_START", why)
            self.tstate["latest_activation_start"] = latest.timestamp()
        self.say("window rules: pass")

    def _check_latest(self, label: str) -> None:
        latest = self.tstate.get("latest_activation_start")
        if latest is not None and self._ts() > latest:
            raise Halt(FAILED_PRE_MERGE if label == "merge" else MERGED_NOT_LIVE, "PAST_LATEST_ACTIVATION_START",
                       f"{label} after {utc_iso(latest)}")

    def _claim(self, w: TrainWindow, dv: RD.DelegationVerdict) -> None:
        root = self.state.root
        root.mkdir(parents=True, exist_ok=True)
        self._train_lock = RC._Flock(root / "train.lock", 0.0)
        try:
            self._train_lock.acquire()
        except RC.ControlRefused as exc:
            self._train_lock = None
            raise Halt("REFUSED", "REFUSED_TRAIN_BUSY", "another train run holds train.lock", refusal=True) from exc
        claims = root / "claims"
        claims.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(claims / f"{w.claim_key}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise Halt("REFUSED", "REFUSED_WINDOW_ALREADY_CLAIMED", w.claim_key, refusal=True) from exc
        try:
            os.write(fd, json.dumps({"train_id": self.train_id, "window_id": w.window_id,
                                     "claimed_at": utc_iso(self._ts())}).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            res = self.control.claim_train(ACTOR, str(self.train_id))
        except RC.ControlRefused as exc:
            raise Halt("REFUSED", f"REFUSED_{exc.code}", exc.detail, refusal=True) from exc
        self.epoch_at_claim = res["epoch"]
        self._save_state(train_id=self.train_id, window_id=w.window_id, claim_key=w.claim_key, phase="claimed",
                         policy_digest=dv.digest, epoch=res["epoch"], intents=[], outcome=None,
                         started_at=self.tstate.get("started_at"),
                         classifier_policy_version=getattr(self.classifier, "policy_version", None))
        self._event("claimed", "claimed", {"window_id": w.window_id, "claim_key": w.claim_key})
        self.say(f"claimed {w.claim_key} as {self.train_id} (epoch {res['epoch']})")

    # -- select / freeze -------------------------------------------------------------------------------
    def _select(self, rec: dict) -> tuple[list[QueueEntry], dict]:
        snap = self.queue.snapshot()
        rec["queue"] = {"source": snap.source, "as_of": snap.as_of, "complete": snap.complete,
                        "reasons": snap.reasons, "open": len(snap.entries)}
        self.say(f"select: {snap.source}: {len(snap.entries)} open, complete={snap.complete} {snap.reasons or ''}")
        if not snap.complete:
            raise Halt(NO_OP, "QUEUE_INCOMPLETE", ";".join(snap.reasons)[:300])
        classifier = self.classifier
        if self.cfg.simulate_classifier == "allow":
            if self.live:
                raise Halt("REFUSED", "REFUSED_SIMULATED_CLASSIFIER", "dry run only", refusal=True)
            self.say("NOTE: --simulate-classifier allow (dry run only): every clean PR treated as eligible")
            classifier = _AllowForPreview()
        rec["classifier_version"] = classifier.version
        self.tstate["classifier_version"] = classifier.version
        self.tstate["classifier_policy_version"] = getattr(classifier, "policy_version", None)
        try:
            base = self.github.main_head()
        except (RuntimeError, ValueError) as exc:
            raise Halt(NO_OP, "MAIN_UNREADABLE", str(exc)[:160]) from exc
        self.tstate["select_base"] = base
        eligible, excluded = [], {}
        for e in sorted(snap.entries, key=lambda e: e.pr):
            why = self._pre_exclusion(e)
            if why:
                excluded[e.pr] = why
                continue
            change = self.changeset(e, base)
            if change and any(is_protected(str(p.get("path"))) for p in change.get("paths") or []):
                excluded[e.pr] = "BLOCKED_SELF_MODIFICATION"
                self._event("classified", "classified", {"risk_class": "blocked",
                                                         "reasons": ["touches the train's own verifier"]},
                            subject_kind="pr", pr=e.pr)
                self._event("blocked", "blocked", {"reason": "BLOCKED_SELF_MODIFICATION"}, subject_kind="pr",
                            pr=e.pr)
                continue
            risk, reasons = classifier.classify(e, change)
            self._event("classified", "classified", {"risk_class": risk, "reasons": reasons[:6],
                                                     "head_sha": e.head_sha, "classifier": classifier.version},
                        subject_kind="pr", pr=e.pr)
            self._event({"eligible": "ready"}.get(risk, risk), {"eligible": "ready"}.get(risk, risk),
                        {"risk_class": risk}, subject_kind="pr", pr=e.pr)
            if risk != "eligible":
                excluded[e.pr] = f"{risk}:{'; '.join(reasons)[:160]}"
                continue
            eligible.append(e)
        ordered, dep_excl = order_members(eligible)
        excluded.update(dep_excl)
        if len(ordered) > self.cfg.max_prs:
            for e in ordered[self.cfg.max_prs:]:
                excluded[e.pr] = f"OVER_TRAIN_LIMIT:{self.cfg.max_prs}"
            ordered = [e for e in ordered[: self.cfg.max_prs]]
            ordered, more = order_members(ordered)
            excluded.update(more)
        self.tstate["select_excluded"] = {str(k): v for k, v in excluded.items()}
        rec["selection"] = {"members": [e.pr for e in ordered], "excluded": {str(k): v for k, v in excluded.items()}}
        self.say(f"select: {len(ordered)} eligible {[e.pr for e in ordered]}; {len(excluded)} not riding")
        held = sum(1 for v in excluded.values() if v.startswith("held:"))
        if held:
            self.say(f"select: {held} held by classifier {classifier.version}")
        if not ordered:
            raise Halt(NO_OP, "NOTHING_ELIGIBLE", f"{len(excluded)} open PRs, none eligible")
        return ordered, excluded

    def _pre_exclusion(self, e: QueueEntry) -> Optional[str]:
        if e.head_ref.startswith("train/"):
            return "TRAIN_INTERNAL"
        if e.draft:
            return "DRAFT"
        if not SHA_RE.match(e.head_sha or ""):
            return "HEAD_SHA_UNKNOWN"
        if e.census.get("holds"):
            return f"HELD_BY_HYGIENE:{e.census.get('holds')}"
        if e.census.get("conflict") is True:
            return "CONFLICTING"
        if e.files is not None:
            bad = [f for f in e.files if is_protected(f)]
            if bad:
                return f"BLOCKED_SELF_MODIFICATION:{bad[:3]}"
        return None

    def _freeze(self, w: TrainWindow, members: list[QueueEntry], dv: RD.DelegationVerdict, rec: dict) -> dict:
        base = self.github.main_head()
        if base != self.tstate.get("select_base"):
            raise Halt(NO_OP, "MAIN_MOVED_AT_FREEZE", f"{str(self.tstate.get('select_base'))[:9]} -> {base[:9]}")
        heads = []
        for e in members:
            cur = self.github.pr_head(e.pr)
            if cur != e.head_sha:
                raise Halt(NO_OP, "PR_HEAD_MOVED_AT_FREEZE", f"#{e.pr} {e.head_sha[:9]} -> {str(cur)[:9]}")
            heads.append(e)
        manifest = {
            "schema": SCHEMA_MANIFEST, "train_id": self.train_id, "window_id": w.window_id, "window_slot": w.slot,
            "base_sha": base,
            "members": [{"pr": e.pr, "head_sha": e.head_sha, "order": i + 1, "depends_on": list(e.depends_on),
                         "title": e.title} for i, e in enumerate(heads)],
            "policy_version": dv.digest, "policy_status": dv.code,
            "classifier_version": rec.get("classifier_version"), "check_manifest": list(REQUIRED_CHECKS),
            "batch_qualifier": BATCH_QUALIFIER, "controller_version": CONTROLLER_VERSION,
            "queue_source": (rec.get("queue") or {}).get("source"), "queue_as_of": (rec.get("queue") or {}).get("as_of"),
            "frozen_at": utc_iso(self._ts()),
        }
        manifest["manifest_digest"] = digest({k: v for k, v in manifest.items() if k != "frozen_at"})
        tc = {"schema": TC.TRAIN_CANDIDATE, "train_id": self.train_id, "window_id": w.window_id,
              "repo": getattr(self.github, "repository", RD.REPOSITORY), "base_sha": base,
              "members": [{"pr_number": e.pr, "head_sha": e.head_sha, "risk_class": "eligible", "order": i + 1}
                          for i, e in enumerate(heads)],
              "dependency_graph": {str(e.pr): sorted(set(e.depends_on)) for e in heads if e.depends_on},
              "policy_version": self.tstate.get("classifier_policy_version") or "none",
              "classifier_version": str(rec.get("classifier_version") or "none")[:60],
              "check_manifest": list(REQUIRED_CHECKS), "frozen_at": datetime.fromtimestamp(
                  self._ts(), timezone.utc).isoformat(timespec="seconds"), "candidate_sha": None}
        errs = TC.validate_as(TC.TRAIN_CANDIDATE, tc)
        if errs:
            raise Halt(NO_OP, "CANDIDATE_CONTRACT_INVALID", "; ".join(errs)[:300])
        manifest["train_candidate"] = tc
        self.tstate["members_frozen"] = [e.pr for e in heads]
        self.tstate["base_sha"] = base
        rec["manifest"] = manifest
        if self.live:
            path = self._train_dir() / "manifest.json"
            if os.path.lexists(path):
                raise Halt(FAILED_PRE_MERGE, "MANIFEST_EXISTS", str(path))
            RC._atomic_write_json(path, manifest)
        self._phase("frozen", {"manifest_digest": manifest["manifest_digest"], "train_candidate": tc})
        self._members_event("selected", [e.pr for e in heads], {"train_id": self.train_id})
        self.say(f"freeze: base {base[:12]}, members " +
                 ", ".join(f"#{m['pr']}@{m['head_sha'][:9]}" for m in manifest["members"]) +
                 f"; checks {list(REQUIRED_CHECKS)}; manifest {manifest['manifest_digest'][:19]}")
        return manifest

    # -- integrate + local test ------------------------------------------------------------------------
    def _integrate_and_test(self, manifest: dict, rec: dict) -> dict:
        if not self.live and not self.cfg.dry_run_integrate:
            for m in manifest["members"]:
                self.say(f"WOULD merge --no-ff #{m['pr']} {m['head_sha'][:12]} in a scratch worktree (conflict ejects "
                         "it and its dependents)")
            self.say("WOULD regenerate once: " + ", ".join(n for n, _ in self.cfg.regenerators))
            self.say(f"WOULD run local tests: {' '.join(self.tester.argv(manifest['base_sha']))} (worker env from "
                     f"allowlist {list(WORKER_ENV_ALLOW)}; bisect budget {self.cfg.test_attempts} runs / "
                     f"{self.cfg.test_budget_s:.0f}s)")
            return {"sha": None, "members": manifest["members"], "simulated": True}
        self._phase("integrating")
        for d in ("home", "tmp"):
            (self.cfg.scratch_root / str(self.train_id) / d).mkdir(parents=True, exist_ok=True)
        ws = self.workspace_factory(self.cfg.scratch_root / str(self.train_id) / "wt")
        base = manifest["base_sha"]
        ws.create(base)
        members = [dict(m) for m in manifest["members"]]
        ejected: dict[int, str] = {}
        for m in members:
            if m["pr"] in ejected:
                continue
            got = ws.fetch_pr(m["pr"])
            if got != m["head_sha"]:
                self._eject(m, members, ejected, "HEAD_MOVED_OR_UNFETCHABLE", f"fetched {str(got)[:12]}")
                continue
            files = ws.changed_files(base, m["head_sha"])
            if files is None:
                self._eject(m, members, ejected, "DIFF_UNAVAILABLE", "")
                continue
            bad = [f for f in files if is_protected(f)]
            if bad:
                self._eject(m, members, ejected, "BLOCKED_SELF_MODIFICATION", ",".join(bad[:5]))
        kept = [m for m in members if m["pr"] not in ejected]
        kept = self._merge_all(ws, base, kept, members, ejected)
        if not kept:
            raise Halt(FAILED_PRE_MERGE, "ALL_EJECTED", json.dumps({str(k): v for k, v in ejected.items()})[:300])
        cand = self._regenerate(ws, base)
        self.tstate["_integrated"] = [m["pr"] for m in kept]
        rec["integration"] = {"candidate": cand, "kept": [m["pr"] for m in kept],
                              "ejected": {str(k): v for k, v in ejected.items()}}
        self.say(f"integrate: candidate {cand[:12]} from {[m['pr'] for m in kept]}; ejected {ejected or 'none'}")
        if not self.live and not self.cfg.dry_run_local_test:
            self.say(f"WOULD run local tests on {cand[:12]}: {' '.join(self.tester.argv(base))}")
            return {"sha": cand, "members": kept, "simulated_test": True}
        result = self._test_with_bisect(ws, base, kept, members, ejected, rec)
        final = self._final_protected_check(ws, base, result)
        self._phase("tested", {"candidate": final["sha"], "members": [m["pr"] for m in final["members"]]})
        return final

    def _final_protected_check(self, ws: GitWorkspace, base: str, cand: dict) -> dict:
        files = ws.diff_files(base, cand["sha"])
        if files is None:
            raise Halt(FAILED_PRE_MERGE, "CANDIDATE_DIFF_UNAVAILABLE", cand["sha"][:12])
        bad = [f for f in files if is_protected(f)]
        if bad:
            raise Halt(FAILED_PRE_MERGE, "CANDIDATE_TOUCHES_VERIFIER", ",".join(bad[:5]))
        cand["changed_files"] = len(files)
        return cand

    def _eject(self, m: dict, members: list[dict], ejected: dict, reason: str, detail: str) -> None:
        ejected[m["pr"]] = f"{reason}:{detail}"[:200]
        self._event("ejected", "blocked", {"reason": reason, "detail": detail[:200]}, subject_kind="pr", pr=m["pr"])
        self.say(f"eject #{m['pr']}: {reason} {detail[:80]}")
        for d in sorted(dependents_of(m["pr"], members)):
            if d not in ejected:
                ejected[d] = f"DEPENDENCY_EJECTED:#{m['pr']}"
                self._event("ejected", "blocked", {"reason": "DEPENDENCY_EJECTED", "dependency": m["pr"]},
                            subject_kind="pr", pr=d)
                self.say(f"eject #{d}: depends on ejected #{m['pr']}")

    def _merge_all(self, ws: GitWorkspace, base: str, kept: list[dict], members: list[dict], ejected: dict) -> list:
        out = []
        for m in kept:
            if m["pr"] in ejected:
                continue
            ok, detail = ws.merge(m["head_sha"], f"release train {self.train_id}: merge #{m['pr']} {m['head_sha']}")
            if ok:
                out.append(m)
            else:
                self._eject(m, members, ejected, "MERGE_CONFLICT", detail)
        return [m for m in out if m["pr"] not in ejected]

    def _regenerate(self, ws: GitWorkspace, base: str) -> str:  # noqa: ARG002
        python = str(getattr(self.host, "python", "python3"))
        env = worker_env(self.env, home=self.cfg.scratch_root / str(self.train_id) / "home",
                         tmp=self.cfg.scratch_root / str(self.train_id) / "tmp")
        for d in (env["HOME"], env["TMPDIR"]):
            Path(d).mkdir(parents=True, exist_ok=True)
        env["TRADEAI_PY"] = python
        for name, argv in self.cfg.regenerators:
            argv = [a.replace("{python}", python) for a in argv]
            rc, out = _run(argv, cwd=ws.path, env=env, timeout=900)
            if rc != 0:
                raise Halt(FAILED_PRE_MERGE, "REGENERATE_FAILED", f"{name} rc={rc}: {out.strip()[-200:]}")
        ws.commit_tracked(f"release train {self.train_id}: regenerate generated files")
        return ws.head()

    def _integrate_subset(self, ws: GitWorkspace, base: str, subset: list[dict]) -> Optional[str]:
        prs = [m["pr"] for m in subset]
        if prs == self.tstate.get("_integrated") and ws.head():
            return ws.head()
        self.tstate["_integrated"] = None
        ws.reset(base)
        for m in subset:
            ok, _ = ws.merge(m["head_sha"], f"release train {self.train_id}: merge #{m['pr']} {m['head_sha']}")
            if not ok:
                return None
        sha = self._regenerate(ws, base)
        self.tstate["_integrated"] = prs
        return sha

    def _test_with_bisect(self, ws: GitWorkspace, base: str, kept: list[dict], members: list[dict],
                          ejected: dict, rec: dict) -> dict:
        t_end = self._ts() + self.cfg.test_budget_s
        attempts: list[dict] = []
        scratch = self.cfg.scratch_root / str(self.train_id)

        def test(subset: list[dict], label: str) -> Optional[bool]:
            if len(attempts) >= self.cfg.test_attempts or self._ts() >= t_end:
                return None
            sha = self._integrate_subset(ws, base, subset)
            if sha is None:
                attempts.append({"label": label, "prs": [m["pr"] for m in subset], "result": "integrate_failed"})
                return False
            res = self.tester.run(ws.path, base, timeout=t_end - self._ts(), scratch=scratch, now=self._ts)
            if SHA_RE.match(sha or ""):
                self._evidence(sha, "local_test", f"local_test:{label}:{[m['pr'] for m in subset]}"[:200],
                               "success" if res.ok else "failure")
            attempts.append({"label": label, "prs": [m["pr"] for m in subset], "sha": sha, "ok": res.ok,
                             "rc": res.rc, "seconds": round(res.seconds, 1), "tail": res.tail[-200:]})
            self.say(f"local test [{label}] {[m['pr'] for m in subset]} @ {sha[:12]}: "
                     f"{'PASS' if res.ok else 'FAIL rc=' + str(res.rc)} ({res.seconds:.0f}s)")
            return res.ok

        rec["local_test"] = {"attempts": attempts}
        full = test(kept, "full")
        if full:
            return {"sha": ws.head(), "members": kept}
        if full is None:
            raise Halt(FAILED_PRE_MERGE, "LOCAL_TEST_BUDGET_EXHAUSTED", "no test run fit the budget")
        lo, hi = 0, len(kept)          # prefix kept[:lo] passes (lo=0: base, assumed green), kept[:hi] fails
        while hi - lo > 1:
            mid = (lo + hi) // 2
            r = test(kept[:mid], f"prefix{mid}")
            if r is None:
                break
            if r:
                lo = mid
            else:
                hi = mid
        pending: list[int] = []
        if hi - lo == 1:
            culprit = kept[hi - 1]
            if hi == 1:
                base_ok = test([], "base")
                if base_ok is False:
                    for m in kept:
                        self._pending(m, "BASE_RED")
                    raise Halt(FAILED_PRE_MERGE, "BASE_RED", "the frozen base fails the local tests")
                if base_ok is None:
                    for m in kept:
                        self._pending(m, "BUDGET_EXHAUSTED_BEFORE_ATTRIBUTION")
                    raise Halt(FAILED_PRE_MERGE, "LOCAL_TEST_UNATTRIBUTED", "budget exhausted")
            self._eject(culprit, members, ejected, "LOCAL_TEST_FAILED_ATTRIBUTED",
                        f"prefix {hi} fails, prefix {lo} passes")
            rest = [m for m in kept if m["pr"] not in ejected]
            r = test(rest, "without-culprit") if rest else None
            rec["failure_attribution"] = {"attributed": [culprit["pr"]]}
            if r:
                return {"sha": ws.head(), "members": rest, "attributed": culprit["pr"]}
            safe = [m for m in kept[:lo] if m["pr"] not in ejected]
            pending = [m["pr"] for m in rest if m not in safe]
        else:
            safe = kept[:lo]
            pending = [m["pr"] for m in kept[lo:hi]] + [m["pr"] for m in kept[hi:]]
        for pr in pending:
            self._pending(next(m for m in kept if m["pr"] == pr), "UNATTRIBUTED_FAILURE")
        attributed = [int(k) for k, v in ejected.items() if str(v).startswith("LOCAL_TEST_FAILED_ATTRIBUTED")]
        rec["failure_attribution"] = {"attributed": attributed, "pending_investigation": pending}
        if not safe:
            raise Halt(FAILED_PRE_MERGE, "LOCAL_TEST_UNATTRIBUTED", f"pending investigation: {pending}")
        sha = self._integrate_subset(ws, base, safe)
        if sha is None:
            raise Halt(FAILED_PRE_MERGE, "LOCAL_TEST_UNATTRIBUTED", "safe prefix no longer integrates")
        self.say(f"local test: releasing the passing prefix {[m['pr'] for m in safe]}; pending {pending}")
        return {"sha": sha, "members": safe, "pending_investigation": pending}

    def _pending(self, m: dict, reason: str) -> None:
        self._event("pending_investigation", "ready", {"reason": reason}, subject_kind="pr", pr=m["pr"])
        self.say(f"#{m['pr']}: pending investigation ({reason}); stays queued, not ejected")

    # -- wait for window -------------------------------------------------------------------------------
    def _wait_for_window(self, w: TrainWindow, rec: dict) -> None:  # noqa: ARG002
        now = self._ts()
        start = w.start.timestamp()
        if now < start:
            if not self.live:
                self.say(f"WOULD wait {start - now:.0f}s for the window to open at {w.start.isoformat()}")
            else:
                self._phase("waiting_window", {"opens": w.start.isoformat()})
                while self._ts() < start:
                    self._boundary("wait_for_window")
                    self.host.sleep(min(self.cfg.poll_s, max(1.0, start - self._ts())))
        if self._ts() >= w.end.timestamp():
            raise Halt(FAILED_PRE_MERGE, "WINDOW_CLOSED", "no catch-up")

    # -- qualify ---------------------------------------------------------------------------------------
    def _observed(self, **kw: Any) -> dict:
        d = self._delegation_body()
        return {"repository": d.get("repository", RD.REPOSITORY), "environment": d.get("environment", "production"),
                "train_id": self.train_id, **kw}

    def _delegation_body(self) -> dict:
        dv = RD.load(self.delegation_path, allow_repo_path=self.allow_repo_delegation)
        return dv.delegation or {}

    _STOP_CODES = frozenset({"STOPPED", "STOP_LATCHED", "STOP_LATCH_UNREADABLE", "REVOKED", "PAUSED",
                             "PAUSED_AFTER_CURRENT", "EPOCH_STALE", "DELEGATION_EPOCH_STALE", "POLICY_DIGEST_CHANGED",
                             "CONTROL_CORRUPT", "CONTROL_UNARMED"})

    def _refusal(self, exc: RC.ControlRefused, stage: str, label: str) -> Halt:
        outcome = self._stop_outcome() if exc.code in self._STOP_CODES else self._fail_outcome()
        return Halt(outcome, f"{stage}_{exc.code}", f"{label}: {exc.detail}"[:300])

    def _cap_effect(self, issue: Callable[[], str], action: str, observed: Callable[[], dict],
                    effect: Callable[[], Any], *, label: str, recheck_hook: Optional[Callable[[], None]] = None,
                    keep: bool = False) -> Any:
        """intent -> issue -> reserve -> recheck (STOP/epoch/revocation) -> effect -> outcome. The intent row is
        durable before the capability is reserved, so a crash anywhere after it is found by train-reconcile.
        Refusals before the effect consume nothing; an exception during the effect is UNCERTAIN."""
        key = self._intent(action, {"label": label})
        try:
            token = issue()
            res = self.authority.reserve(token, action, observed=observed())
        except RC.ControlRefused as exc:
            self._effect(key, "REFUSED_NO_EFFECT", {"code": exc.code})
            raise self._refusal(exc, "CAPABILITY", label) from exc
        self._update_intent(key, capability_intent=res.intent_id)
        try:
            if recheck_hook:
                recheck_hook()
            res.recheck(observed())
        except RC.ControlRefused as exc:
            if not res.done:
                res._end(CAP.ABORTED_NO_EFFECT, {"code": exc.code}, refund=True)
            self._effect(key, "ABORTED_NO_EFFECT", {"code": exc.code})
            raise self._refusal(exc, "RECHECK", label) from exc
        except Halt as h:
            if not res.done:
                res._end(CAP.ABORTED_NO_EFFECT, {"halt": h.reason}, refund=True)
            self._effect(key, "ABORTED_NO_EFFECT", {"halt": h.reason})
            raise
        try:
            out = effect()
        except Halt as h:
            if not res.done:
                res.failed_no_effect({"halt": h.reason})
            self._effect(key, "FAILED_NO_EFFECT", {"halt": h.reason})
            raise
        except Exception as exc:  # noqa: BLE001 - the outcome of the effect is unknown
            res.uncertain({"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            self._effect(key, "UNCERTAIN", {"error": type(exc).__name__})
            raise Halt("UNCERTAIN", "EFFECT_UNCERTAIN", f"{label}: {type(exc).__name__}: {str(exc)[:160]}",
                       code=EXIT_UNCERTAIN) from exc
        if keep:
            return out, res, key
        res.succeeded({"result": _clip(out)})
        self._effect(key, "SUCCEEDED", {"result": _clip(out)})
        return out

    def _update_intent(self, key: str, **kw: Any) -> None:
        intents = list(self.tstate.get("intents") or [])
        for i in intents:
            if i["key"] == key:
                i.update(kw)
        self._save_state(intents=intents)

    def _qualify(self, manifest: dict, cand: dict, rec: dict) -> dict:
        self._boundary("qualify")
        heads = [{"pr": m["pr"], "head_sha": m["head_sha"]} for m in cand["members"]]
        sha = cand.get("sha")
        title = f"Release train {self.train_id} ({len(heads)} PRs)"
        body = (f"Release train `{self.train_id}`, window {manifest['window_id']}.\n\nBase `{manifest['base_sha']}`.\n"
                + "\n".join(f"- #{h['pr']} `{h['head_sha']}`" for h in heads)
                + f"\n\nManifest `{manifest['manifest_digest']}`. Opened by the release train controller.")
        if not self.live:
            self.say(f"WOULD issue build_publish capabilities (push_train_ref, open_batch_pr) bound to base "
                     f"{manifest['base_sha'][:12]}, {len(heads)} PR heads, output ref refs/heads/train/{self.train_id}")
            self.writer.push_train_ref(str(self.train_id), sha or "<candidate>")
            self.writer.open_or_update_batch_pr(str(self.train_id), sha or "<candidate>", title, body)
            self.say(f"WOULD wait <= {self.cfg.qualify_timeout_s:.0f}s for {list(REQUIRED_CHECKS)} to read exactly "
                     f"'success' (latest run, app github-actions) on {str(sha or '<candidate>')[:12]}; "
                     "neutral/skipped/cancelled/missing never pass; no tree-equivalence fallback")
            return {"pr": 0, "evidence": None, "simulated": True}
        self._phase("qualifying", {"candidate": sha})
        base = manifest["base_sha"]

        def build(action: str) -> Callable[[], str]:
            return lambda: self.authority.issue_build(str(self.train_id), base_sha=base, pr_heads=heads,
                                                      actions=[action], candidate_sha=sha)

        obs = lambda: self._observed(main_sha=self.github.main_head())  # noqa: E731
        self._cap_effect(build("push_train_ref"), "push_train_ref", obs,
                         lambda: self.writer.push_train_ref(str(self.train_id), sha), label="push train ref")
        pr = self._cap_effect(build("open_batch_pr"), "open_batch_pr", obs,
                              lambda: self.writer.open_or_update_batch_pr(str(self.train_id), sha, title, body),
                              label="open batch PR")
        self._save_state(batch_pr=pr, candidate=sha, base_sha=base, members=heads)
        ev = self._wait_checks(sha, REQUIRED_CHECKS, self.cfg.qualify_timeout_s, FAILED_PRE_MERGE, "batch")
        self._phase("qualified", {"candidate": sha, "batch_pr": pr, "evidence": ev})
        rec["batch"] = {"pr": pr, "candidate": sha, "evidence": ev}
        return {"pr": pr, "evidence": ev}

    def _wait_checks(self, sha: str, required: tuple, timeout_s: float, fail_outcome: str, label: str) -> dict:
        deadline = self._ts() + timeout_s
        window_end = self.window.end.timestamp() if self.window else deadline
        while True:
            self._boundary(f"wait_checks_{label}")
            try:
                runs = self.github.check_runs(sha)
            except (RuntimeError, ValueError) as exc:
                runs, err = [], type(exc).__name__
            else:
                err = None
            ev = check_evidence(runs, sha, required, now=self._ts())
            verdict, errs = evidence_verdict(ev, required)
            if verdict == "GREEN":
                self.say(f"{label} checks GREEN on {sha[:12]}: {[c['name'] for c in ev['checks']]}")
                if label != "batch_recheck":
                    for c in ev["checks"]:
                        rid = c.get("id")
                        if isinstance(rid, int) and not isinstance(rid, bool) and rid > 0:
                            self._evidence(sha, "ci_run", f"{label}:{c['name']}", "success", workflow=c["name"],
                                           run_id=rid)
                return ev
            if verdict == "RED":
                raise Halt(fail_outcome, f"CI_RED_{label.upper()}", ";".join(errs)[:300])
            if self._ts() >= min(deadline, window_end):
                raise Halt(fail_outcome, f"CI_TIMEOUT_{label.upper()}", ";".join(errs + ([err] if err else []))[:300])
            self.host.sleep(self.cfg.poll_s)

    # -- merge -----------------------------------------------------------------------------------------
    def _merge(self, manifest: dict, cand: dict, batch: dict, rec: dict) -> str:
        base, sha = manifest["base_sha"], cand.get("sha")
        heads = [{"pr": m["pr"], "head_sha": m["head_sha"]} for m in cand["members"]]
        if not self.live:
            self.say(f"WOULD re-read the 4 checks on the candidate, then issue a merge capability (expected base "
                     f"{base[:12]}, candidate, artifact {manifest['manifest_digest'][:19]}, evidence digest, rollback "
                     f"target main_ref {base[:12]})")
            self.say("WOULD re-check STOP / control epoch / delegation epoch+digest / main == base / PR heads "
                     "immediately before the merge")
            self._check_latest_preview()
            self.writer.merge_batch_pr(int(batch.get("pr") or 0), sha or "<candidate>",
                                       f"Release train {self.train_id}")
            self.say("WOULD record the resulting main SHA and require parents == [base, candidate]")
            return "SIMULATED-MERGE-COMMIT"
        self._boundary("merge")
        self._check_latest("merge")
        ev = self._wait_checks(sha, REQUIRED_CHECKS, 0.0, FAILED_PRE_MERGE, "batch_recheck")
        self._phase("merging", {"candidate": sha})

        def observed() -> dict:
            cur = [{"pr": h["pr"], "head_sha": self.github.pr_head(h["pr"]) or ""} for h in heads]
            return self._observed(main_sha=self.github.main_head(), candidate_sha=self.github.pr_head(batch["pr"]),
                                  artifact_digest=manifest["manifest_digest"], pr_heads=cur)

        def issue() -> str:
            return self.authority.issue_merge(str(self.train_id), expected_base_sha=base, pr_heads=heads,
                                              candidate_sha=sha, artifact_digest=manifest["manifest_digest"],
                                              evidence=_cap_evidence(ev), rollback_target={"kind": "main_ref",
                                                                                           "sha": base},
                                              actions=["merge_batch_pr"])

        merged = self._cap_effect(issue, "merge_batch_pr", observed,
                                  lambda: self.writer.merge_batch_pr(int(batch["pr"]), sha,
                                                                     f"Release train {self.train_id}"),
                                  label="merge batch PR", recheck_hook=lambda: self._check_latest("merge"))
        merged = str(merged).strip()
        parents = self.github.commit_parents(merged) if SHA_RE.match(merged) else None
        self._save_state(main_sha=merged, merge_parents=parents)
        rec["merge"] = {"main_sha": merged, "parents": parents}
        if not parents or parents[0] != base or sha not in parents:
            self._latch(f"merge commit {merged[:12]} parents {parents} != [base {base[:12]}, candidate {sha[:12]}]")
            raise Halt(MERGED_NOT_LIVE, "MAIN_MOVED_AT_MERGE", f"parents {parents}")
        self._phase("merged", {"main_sha": merged})
        self._members_event("merged", [h["pr"] for h in heads], {"main_sha": merged})
        self.say(f"merged: main is {merged[:12]} (parents base {base[:12]} + candidate {sha[:12]})")
        return merged

    def _check_latest_preview(self) -> None:
        latest = self.tstate.get("latest_activation_start")
        if latest is not None:
            self.say(f"WOULD refuse merge/activation after the 08:00 latest start {utc_iso(latest)}")

    # -- promote ---------------------------------------------------------------------------------------
    def _promote(self, manifest: dict, cand: dict, batch: dict, merged: str, rec: dict) -> None:
        heads = [{"pr": m["pr"], "head_sha": m["head_sha"]} for m in cand["members"]]
        units = list(self.host_units())
        if not self.live:
            self.say(f"WOULD wait <= {self.cfg.main_ci_timeout_s:.0f}s for exact-SHA push/main checks "
                     f"{[c for c in REQUIRED_CHECKS if c != BATCH_QUALIFIER]} on the merge commit")
            self.say("WOULD refuse if the merge commit or its prepared artifact is quarantined, or CURRENT moved")
            self.say(f"WOULD git -C {self.host.checkout} fetch + checkout --detach <merge commit>; then "
                     f"bash {self.host.deploy} prepare (TRADEAI_RELEASE_CAMPAIGN=release-train-{self.train_id}, "
                     "TRADEAI_RELEASE_PR=<batch PR>) under a prepare capability")
            self.say(f"WOULD issue a promote capability: artifact digest of the prepared dir, services {units}, "
                     f"rollback target = CURRENT ({self.host.current_release()}), batch evidence bound")
            self.say("WOULD re-check STOP + epoch at activation, then bash cio_phase2_exact_main_deploy.sh promote "
                     "<prepared dir>")
            self.say("WOULD verify: promote exit, CURRENT, BUILD_SHA, units, /api/health, served copy, CC pages "
                     f"{list(RW.VERIFY_PAGES)}, platform-health, needs-action")
            self.say("WOULD on failure: rollback <bound target>, latch STOP, quarantine the artifact")
            self._check_latest_preview()
            raise Halt("DRY_RUN_COMPLETE", "DRY_RUN_COMPLETE", "nothing was claimed, issued, pushed or written",
                       code=EXIT_OK)
        self._boundary("promote")
        main_ev = self._wait_checks(merged, tuple(c for c in REQUIRED_CHECKS if c != BATCH_QUALIFIER),
                                    self.cfg.main_ci_timeout_s, MERGED_NOT_LIVE, "main")
        if merged in {str(r.get("sha")) for r in self.quarantined()}:
            raise Halt(MERGED_NOT_LIVE, "QUARANTINED_ARTIFACT", merged[:12])
        prev = self.host.current_release()
        prev_sha = self.host.build_sha(prev)
        self._save_state(rollback_target={"release": str(prev), "sha": prev_sha})
        if not SHA_RE.match(prev_sha or ""):
            raise Halt(MERGED_NOT_LIVE, "ROLLBACK_TARGET_UNKNOWN", str(prev))
        self._phase("promoting", {"main_sha": merged, "rollback_target": str(prev)})
        head = self.github.main_head()
        train_sha = merged if head != merged else None
        env = RW.deploy_env(self.env, _CampaignWindow(f"release-train-{self.train_id}"), int(batch["pr"]), train_sha)
        if not self.host.checkout_clean():
            raise Halt(MERGED_NOT_LIVE, "CHECKOUT_DIRTY", str(self.host.checkout))

        def obs_main() -> dict:
            return self._observed(main_sha=self.github.main_head(), candidate_sha=merged)

        def current_unchanged() -> None:
            if self.host.current_release() != prev:
                raise Halt(MERGED_NOT_LIVE, "CURRENT_MOVED", f"{prev} -> {self.host.current_release()}")

        # prepare (builds the artifact; CURRENT untouched)
        t0 = self._ts()

        def do_prepare() -> dict:
            rc, out = self.host.checkout_sha(merged)
            if rc != 0:
                raise Halt(MERGED_NOT_LIVE, "CHECKOUT_FAILED", out.strip()[-200:])
            rc, out = self.host.run_deploy(["prepare"], env)
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            ok_lines = [m.group(1) for m in (RW._PREPARE_OK_RE.search(ln) for ln in lines) if m]
            if rc != 0 or not ok_lines:
                raise Halt(MERGED_NOT_LIVE, "PREPARE_FAILED", "\n".join(lines[-4:])[-300:])
            return {"release_dir": os.path.realpath(ok_lines[-1])}

        def issue_prepare() -> str:
            return self.authority.issue_promote(
                str(self.train_id), expected_base_sha=manifest["base_sha"], pr_heads=heads, candidate_sha=merged,
                artifact_digest=manifest["manifest_digest"], evidence=_cap_evidence(main_ev),
                batch_candidate_sha=cand["sha"], batch_evidence=_cap_evidence(batch["evidence"]),
                rollback_target={"kind": "release", "sha": prev_sha, "release": str(prev)},
                services=units, actions=["prepare_release"])

        prep = self._cap_effect(issue_prepare, "prepare_release", lambda: self._observed(
            main_sha=self.github.main_head(), candidate_sha=merged, artifact_digest=manifest["manifest_digest"]),
            do_prepare, label="prepare", recheck_hook=current_unchanged)
        prepared = Path(prep["release_dir"])
        if self.host.build_sha(prepared) != merged:
            raise Halt(MERGED_NOT_LIVE, "PREPARE_BUILD_SHA_MISMATCH", self.host.build_sha(prepared))
        art = artifact_digest(prepared, merged)
        if art in {str(r.get("artifact_digest")) for r in self.quarantined()}:
            raise Halt(MERGED_NOT_LIVE, "QUARANTINED_ARTIFACT", art)
        self._save_state(prepared=str(prepared), artifact_digest=art)

        def issue_promote() -> str:
            return self.authority.issue_promote(
                str(self.train_id), expected_base_sha=manifest["base_sha"], pr_heads=heads, candidate_sha=merged,
                artifact_digest=art, evidence=_cap_evidence(main_ev), batch_candidate_sha=cand["sha"],
                batch_evidence=_cap_evidence(batch["evidence"]),
                rollback_target={"kind": "release", "sha": prev_sha, "release": str(prev)},
                services=units, actions=["promote_release"])

        def recheck_activation() -> None:
            current_unchanged()
            self._check_latest("activation")
            self._boundary("activation")

        before = self.host.units_active(tuple(units))
        _, res, key = self._cap_effect(issue_promote, "promote_release", lambda: self._observed(
            main_sha=self.github.main_head(), candidate_sha=merged, artifact_digest=artifact_digest(prepared, merged)),
            lambda: None, label="activate", recheck_hook=recheck_activation, keep=True)
        # The reservation is held (global lock) through activation, verification and any rollback.
        try:
            self._save_state(in_flight=True)
            t_act = self._ts()
            rc, out = self.host.run_deploy(["promote", str(prepared)], env)
            t_ver = self._ts()
            runner = RW.Runner(self.host, self.state, env=self.env, units=tuple(units))
            checks = runner._verify(prepared, merged, before, promote_rc=rc)
            t_done = self._ts()
        except Exception as exc:  # noqa: BLE001
            res.uncertain({"error": type(exc).__name__})
            self._effect(key, "UNCERTAIN", {"error": type(exc).__name__})
            raise Halt("UNCERTAIN", "ACTIVATION_UNCERTAIN", str(exc)[:200], code=EXIT_UNCERTAIN) from exc
        rec["verification"] = checks
        ok = all(c.get("ok") for c in checks.values())
        timing = {"train_id": self.train_id, "at": utc_iso(self._ts()), "prepare_s": round(t_act - t0, 1),
                  "promote_s": round(t_ver - t_act, 1), "verify_s": round(t_done - t_ver, 1)}
        if ok:
            res.succeeded({"verified": True, "main_sha": merged})
            self._effect(key, "SUCCEEDED", {"verified": True})
            self.measure.append(timing)
            self._save_state(in_flight=False, served_sha=merged)
            self._members_event("released", [h["pr"] for h in heads], {"served_sha": merged})
            self.say(f"verified: CURRENT {prepared} serves {merged[:12]}")
            self._settle_if_stopping()
            raise Halt(RELEASED_VERIFIED, "VERIFIED", merged[:12], code=EXIT_OK)
        failed = [k for k, c in checks.items() if not c.get("ok")]
        self.say(f"verification FAILED: {failed}; rolling back to the bound target {prev}")
        t_rb = self._ts()
        if self.host.current_release() == prev:
            rb_ok, rb = True, {"by": "deploy promote internal health rollback"}
        else:
            rc, out = self.host.run_deploy(["rollback", str(prev)], env)
            health = runner._health()
            rb_ok = rc == 0 and self.host.current_release() == prev and health == 200
            rb = {"rc": rc, "health": health, "tail": out.strip()[-200:]}
        timing["rollback_s"] = round(self._ts() - t_rb, 1)
        self.measure.append(timing)
        res.succeeded({"verified": False, "rolled_back": rb_ok, "failed": failed})
        self._effect(key, "ROLLED_BACK" if rb_ok else "ROLLBACK_FAILED", {"failed": failed, **rb})
        self._members_event("rolled_back" if rb_ok else "rollback_failed", [h["pr"] for h in heads],
                            {"failed": failed})
        self._quarantine(merged, art, prepared, failed)
        self._latch(f"verification failed {failed}; rollback {'ok' if rb_ok else 'FAILED'}")
        self._save_state(in_flight=False, served_sha=prev_sha if rb_ok else None)
        self._settle_if_stopping()
        rec["rollback"] = {"ok": rb_ok, **rb}
        raise Halt(ROLLED_BACK if rb_ok else ROLLBACK_FAILED, "VERIFY_FAILED", ",".join(failed))

    def host_units(self) -> tuple:
        d = self._delegation_body()
        named = (d.get("limits") or {}).get("named_services") or []
        return tuple(u for u in RW.UNITS if u in named) or tuple(RW.UNITS)

    def _settle_if_stopping(self) -> None:
        v = self.control.view()
        if v.mode == RC.STOP_REQUESTED:
            self.control.acknowledge_stop(ACTOR)
            v = self.control.view()
        if v.mode in (RC.STOP_ACKNOWLEDGED, RC.SETTLING):
            self.control.settle(ACTOR, in_flight=False)

    def _latch(self, detail: str) -> None:
        if not self.live:
            self.say(f"WOULD latch STOP: {detail}")
            return
        if self.state.read_latch()[0] == "ABSENT":
            RC._atomic_write_json(self.state.latch, {
                "latched_at": utc_iso(self._ts()), "window_id": self.window.window_id if self.window else None,
                "outcome": "TRAIN_STOP", "train_id": self.train_id, "source": "release_train_controller",
                "detail": detail[:400] + "; operator reviews, then release_control_cli.py resume / clear-stop"})

    def _quarantine(self, sha: str, art: str, prepared: Path, failed: list) -> None:
        row = {"kind": "quarantine", "sha": sha, "artifact_digest": art, "release_dir": str(prepared),
               "train_id": self.train_id, "failed": failed, "at": utc_iso(self._ts()),
               "detail": "failed artifact and its main lineage: no train releases a base containing it until "
                         "train-quarantine-resolve records how main was reconciled"}
        RC._append_jsonl(self.state.root / "quarantine.jsonl", row)
        self._event("quarantined", "quarantined", row)

    # -- terminal --------------------------------------------------------------------------------------
    def outcome_doc(self, outcome: str, reason: Any, detail: Any, attribution: Optional[dict] = None) -> dict:
        """TrainOutcome@v1 (validated). Members are the frozen membership (NO_OP has none)."""
        def sha(k: str) -> Optional[str]:
            v = self.tstate.get(k)
            return v if isinstance(v, str) and SHA_RE.match(v) else None

        rt = self.tstate.get("rollback_target") or {}
        members = [] if outcome == NO_OP else list(dict.fromkeys(self.tstate.get("members_frozen") or []))
        art = self.tstate.get("artifact_digest")
        body = {"schema": SCHEMA_OUTCOME, "train_id": self.train_id,
                "window_id": self.tstate.get("window_id") or (self.window.window_id if self.window else ""),
                "outcome": outcome, "members": members,
                "started_at": str(self.tstate.get("started_at") or utc_iso(self._ts())),
                "finished_at": utc_iso(self._ts()), "base_sha": sha("base_sha"), "candidate_sha": sha("candidate"),
                "main_sha": sha("main_sha"), "served_sha": sha("served_sha"),
                "artifact_digest": art if isinstance(art, str) and art.startswith("sha256:") else None,
                "rollback_target": (str(rt.get("release"))[:400] if rt.get("release") else None),
                "failure_attribution": attribution or None,
                "notes": f"{reason}: {detail}"[:2000] if reason else None}
        errs = TC.validate_as(TC.TRAIN_OUTCOME, body)
        if errs:
            body["notes"] = (f"{body['notes'] or ''} [contract: {'; '.join(errs)}]")[:2000]
        return body

    def _terminal(self, rec: dict) -> None:
        outcome = rec.get("outcome")
        if outcome == "UNCERTAIN":
            self._save_state(phase="uncertain")
            self._event("uncertain", "uncertain", {"reason": rec.get("reason"), "detail": rec.get("detail")})
            return            # stays non-terminal: train-reconcile resolves it before anything else runs
        if outcome not in TERMINAL_OUTCOMES:
            outcome = CANCELLED
            rec["outcome"] = outcome
        body = self.outcome_doc(outcome, rec.get("reason"), rec.get("detail"), rec.get("failure_attribution"))
        self._save_state(phase="terminal", outcome=body)
        RC._atomic_write_json(self._train_dir() / "outcome.json", body)
        self._event("outcome", self._OUTCOME_STATE.get(outcome), body)
        try:
            self.control.train_terminal(ACTOR, str(self.train_id), outcome)
        except RC.ControlRefused as exc:
            rec["control_terminal_error"] = exc.code
        prio = ALERT_PRIORITY.get(outcome)
        if prio:
            rec["notification"] = self.host.notify(
                f"Release train {self.train_id} {outcome}: {rec.get('reason')} {str(rec.get('detail') or '')[:160]}",
                prio)


class _AllowForPreview:
    version = "simulated-allow/dry-run-only"
    policy_version = "dry-run-preview"

    def classify(self, entry: QueueEntry, change: Optional[dict]) -> tuple[str, list[str]]:  # noqa: ARG002
        return "eligible", ["dry-run preview only"]


@dataclass(frozen=True)
class _CampaignWindow:
    campaign: str


def _cap_evidence(ev: dict) -> dict:
    return {"sha": ev["sha"], "checks": [{k: c.get(k) for k in ("name", "head_sha", "status", "conclusion")}
                                         for c in ev.get("checks") or []]}


def artifact_digest(release_dir: Path, sha: str) -> str:
    """Identity of a prepared release: its resolved path, BUILD_SHA and build metadata files."""
    p = Path(os.path.realpath(release_dir))
    parts: dict[str, Any] = {"path": str(p), "sha": sha}
    for name in ("BUILD_SHA", "BUILD_META.json", "BUILD_INFO.json"):
        try:
            parts[name] = hashlib.sha256((p / name).read_bytes()).hexdigest()
        except OSError:
            parts[name] = None
    return digest(parts)


def _clip(v: Any) -> Any:
    s = json.dumps(v, default=str, sort_keys=True)
    return v if len(s) <= 2000 else s[:2000]


# ── reconcile (restart) ───────────────────────────────────────────────────────────────────────────

class Reconciler:
    """Restart: for each non-terminal train, observe GitHub main, CURRENT and the services, decide each pending
    intent's disposition, record it (capability reconcile + event + train outcome). Ambiguity latches STOP and
    leaves the train non-terminal for the operator. Dry run prints the decisions and writes nothing."""

    def __init__(self, ctl: TrainController) -> None:
        self.c = ctl

    def run(self) -> tuple[int, dict]:
        c = self.c
        out: dict = {"schema": "ReleaseTrainReconcile@v1", "mode": "live" if c.live else "dry_run", "trains": []}
        try:
            main = c.github.main_head()
        except (RuntimeError, ValueError) as exc:
            out["error"] = f"main unreadable: {exc}"
            return EXIT_REFUSED, out
        cur = c.host.current_release()
        observed = {"main_sha": main, "current": str(cur), "current_build_sha": c.host.build_sha(cur),
                    "units": c.host.units_active(tuple(RW.UNITS)), "at": utc_iso(c._ts())}
        out["observed"] = observed
        code = EXIT_OK
        for tid in c.pending_trains():
            path = c.state.root / "trains" / tid / "state.json"
            try:
                st = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out["trains"].append({"train_id": tid, "disposition": "AMBIGUOUS", "why": "state unreadable"})
                code = EXIT_UNCERTAIN
                continue
            decision = self.decide(st, observed)
            decision["train_id"] = tid
            out["trains"].append(decision)
            if c.live:
                self.apply(st, decision, observed)
            if decision["disposition"] == "AMBIGUOUS":
                code = EXIT_UNCERTAIN
        c.say(json.dumps(out["trains"], default=str)[:2000])
        out["steps"] = c.steps
        return code, out

    def decide(self, st: dict, obs: dict) -> dict:
        c = self.c
        pending = [i for i in st.get("intents") or [] if i.get("status") in ("INTENT", "UNCERTAIN")]
        if not pending:
            phase = st.get("phase")
            outcome = MERGED_NOT_LIVE if st.get("main_sha") else FAILED_PRE_MERGE
            return {"disposition": "NO_PENDING_EFFECT", "phase": phase, "outcome": outcome, "intents": []}
        decisions = []
        ambiguous = False
        outcome = FAILED_PRE_MERGE
        for i in pending:
            action = i.get("action")
            d = "AMBIGUOUS"
            if action in ("push_train_ref", "open_batch_pr"):
                ref = c.github.ref_sha(f"heads/train/{st.get('train_id')}")
                d = "EFFECT_APPLIED" if ref == st.get("candidate") else ("EFFECT_ABSENT" if ref is None else "AMBIGUOUS")
                if action == "open_batch_pr":
                    d = "EFFECT_ABSENT_OR_HARMLESS" if d != "AMBIGUOUS" else d
            elif action == "merge_batch_pr":
                cand, base = st.get("candidate"), st.get("base_sha")
                if obs["main_sha"] == base:
                    d = "EFFECT_ABSENT"
                elif cand and c.github.contains(cand, obs["main_sha"]) is True:
                    d, outcome = "EFFECT_APPLIED", MERGED_NOT_LIVE
            elif action == "prepare_release":
                d = "EFFECT_ABSENT" if obs["current"] == (st.get("rollback_target") or {}).get("release") else "AMBIGUOUS"
                outcome = MERGED_NOT_LIVE
            elif action == "promote_release":
                rt = st.get("rollback_target") or {}
                if obs["current"] == rt.get("release") and obs["current_build_sha"] == rt.get("sha"):
                    d, outcome = "EFFECT_ABSENT", MERGED_NOT_LIVE
                elif st.get("prepared") and obs["current"] == st.get("prepared") \
                        and obs["current_build_sha"] == st.get("main_sha"):
                    d, outcome = "EFFECT_APPLIED_UNVERIFIED", STOPPED
            if d == "AMBIGUOUS" or d == "EFFECT_APPLIED_UNVERIFIED":
                ambiguous = ambiguous or d == "AMBIGUOUS"
            decisions.append({"intent": i.get("key"), "action": action, "disposition": d,
                              "capability_intent": i.get("capability_intent")})
        disp = "AMBIGUOUS" if ambiguous else "RESOLVED"
        return {"disposition": disp, "outcome": None if ambiguous else outcome, "intents": decisions}

    def apply(self, st: dict, decision: dict, obs: dict) -> None:
        c = self.c
        c.train_id = st.get("train_id")
        c.tstate = dict(st)
        ledger_intents = self._ledger_intents(str(c.train_id))
        for d in decision["intents"]:
            disp = d["disposition"]
            # The train intent may predate its capability reservation (crash between them): match the ledger's
            # open intents for this train and action too, so nothing stays UNCERTAIN and blocks every train.
            capids = {d.get("capability_intent")} | {i for i, r in ledger_intents.items()
                                                    if r.get("action") == d.get("action")}
            for capid in sorted(x for x in capids if x):
                if disp == "AMBIGUOUS":
                    continue
                try:
                    c.authority.reconcile(capid, disposition="EFFECT_APPLIED" if disp.startswith("EFFECT_APPLIED")
                                          else "EFFECT_ABSENT", observed_evidence=obs,
                                          reconciled_by="release_window.train-reconcile")
                except RC.ControlRefused as exc:
                    d.setdefault("capability_reconcile", []).append(exc.code)
            c._event("reconciled", "reconciled", {"intent": d.get("intent"), "disposition": disp, "observed": obs})
        if decision["disposition"] == "AMBIGUOUS":
            c._latch(f"restart with an ambiguous effect in {c.train_id}: {decision['intents']}")
            c._save_state(phase="reconciliation_required")
            return
        if any(d["disposition"] == "EFFECT_APPLIED_UNVERIFIED" for d in decision["intents"]):
            c._latch(f"{c.train_id}: promote applied before the restart but never verified; operator verifies "
                     "or rolls back")
        if decision["outcome"] == MERGED_NOT_LIVE and not c.tstate.get("main_sha"):
            c.tstate["main_sha"] = obs["main_sha"]
        c.epoch_at_claim = st.get("epoch")
        body = c.outcome_doc(decision["outcome"], "RECONCILED_AFTER_RESTART",
                             json.dumps(decision["intents"], default=str))
        intents = [dict(i, status="RECONCILED") if i.get("status") in ("INTENT", "UNCERTAIN") else i
                   for i in st.get("intents") or []]
        c._save_state(phase="terminal", outcome=body, intents=intents, pending_intent=None)
        RC._atomic_write_json(c._train_dir() / "outcome.json", body)
        c._event("outcome", c._OUTCOME_STATE.get(decision["outcome"]), body)
        try:
            c.control.train_terminal(ACTOR, str(c.train_id), str(decision["outcome"]))
        except RC.ControlRefused:
            pass

    def _ledger_intents(self, train_id: str) -> dict:
        try:
            ledger = self.c.authority._load_ledger(create=False)
        except RC.ControlRefused:
            return {}
        return {i: r for i, r in ledger["intents"].items()
                if r.get("train_id") == train_id and r.get("status") in (CAP.RESERVED, CAP.UNCERTAIN)}


def status(state: RW.State) -> dict:
    """Read-only: latch, control, trains, last outcome, quarantine, measurements."""
    ctl = RC.ReleaseControl(state.root)
    v = ctl.view()
    trains = []
    for p in sorted((state.root / "trains").glob("*/state.json"))[-20:]:
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trains.append({"train_id": p.parent.name, "phase": "UNREADABLE"})
            continue
        trains.append({"train_id": body.get("train_id"), "phase": body.get("phase"),
                       "outcome": (body.get("outcome") or {}).get("outcome"), "window_id": body.get("window_id")})
    q = Measurements(state.root / "quarantine.jsonl").rows()
    return {"schema": "ReleaseTrainStatus@v1", "controller_status": TRAIN_CONTROLLER_STATUS,
            "github_writes_status": GITHUB_WRITES_STATUS, "latch_state": state.read_latch()[0],
            "control": {"mode": v.mode, "epoch": v.epoch, "stop_phase": v.stop_phase,
                        "current_train_id": v.current_train_id, "error": v.error},
            "trains": trains, "quarantine_rows": q[-10:],
            "measurements": Measurements(state.root / "train_measurements.jsonl").rows()[-5:]}


def resolve_quarantine(state: RW.State, sha: str, reason: str, evidence: str, *, live: bool,
                       now: Callable[[], float] = time.time) -> tuple[int, dict]:
    """Operator: record how main's lineage was reconciled for a quarantined SHA (append-only; never deleted)."""
    if not SHA_RE.match(sha or "") or len(" ".join(str(reason).split())) < 8 or not str(evidence).strip():
        return EXIT_REFUSED, {"outcome": "REFUSED", "detail": "full SHA, a reason (>= 8 chars) and evidence required"}
    rows = Measurements(state.root / "quarantine.jsonl").rows()
    if not any(r.get("kind") == "quarantine" and r.get("sha") == sha for r in rows):
        return EXIT_REFUSED, {"outcome": "REFUSED", "detail": "no quarantine row for that SHA"}
    row = {"kind": "resolved", "sha": sha, "reason": " ".join(str(reason).split())[:400],
           "evidence": str(evidence)[:400], "at": utc_iso(now())}
    if not live:
        return EXIT_OK, {"outcome": "WOULD_RESOLVE", "row": row}
    RC._append_jsonl(state.root / "quarantine.jsonl", row)
    return EXIT_OK, {"outcome": "RESOLVED", "row": row}


# ── CLI (called by scripts/release_window.py train-*) ─────────────────────────────────────────────

def build_controller(*, live: bool, config: Optional[TrainConfig] = None, host: Optional[RW.Host] = None,
                     state: Optional[RW.State] = None) -> TrainController:
    host = host or RW.Host()
    state = state or RW.State()
    reader = GhCliReader(host)
    writer = GhCliWriter(host, reader) if live else None    # raises WriterNotArmed until D2 + 17.0.0
    return TrainController(host=host, state=state, github=reader, queue=default_queue_source(),
                           classifier=load_classifier(), live=live, writer=writer, config=config)


def render(code: int, body: dict) -> str:
    lines = list(body.get("steps") or [])
    lines.append(f"outcome: {body.get('outcome')} reason: {body.get('reason')} exit: {code}")
    if body.get("would_refuse"):
        lines.append("a live run would refuse: " + " | ".join(body["would_refuse"]))
    return "\n".join(lines)


def cli(args: Any) -> int:
    live = bool(getattr(args, "live", False))
    if live and TRAIN_CONTROLLER_STATUS != "ACTIVE":
        body = {"outcome": "REFUSED_BUILD_ONLY", "controller_status": TRAIN_CONTROLLER_STATUS,
                "detail": "the train controller is built, not armed; arming (delegation, capability key, control "
                          "arm, GitHub App, AGENTS 17.0.0, timer) is an operator act. Run without --live for a "
                          "dry run."}
        print(json.dumps(body, indent=2))
        return EXIT_REFUSED
    if args.cmd == "train-status":
        print(json.dumps(status(RW.State()), indent=2, sort_keys=True, default=str))
        return EXIT_OK
    if args.cmd == "train-claim":
        return cli_claim(args)
    if args.cmd == "train-quarantine-resolve":
        code, body = resolve_quarantine(RW.State(), args.sha, args.reason, args.evidence, live=live)
        print(json.dumps(body, indent=2, default=str))
        return code
    if args.cmd == "train-reconcile":
        try:
            ctl = build_controller(live=live)
        except WriterNotArmed as exc:
            print(json.dumps({"outcome": "REFUSED_WRITER_NOT_ARMED", "detail": str(exc)}, indent=2))
            return EXIT_REFUSED
        code, body = Reconciler(ctl).run()
        print(json.dumps(body, indent=2, default=str))
        return code
    cfg = TrainConfig(dry_run_integrate=bool(args.integrate), dry_run_local_test=bool(args.local_test),
                      simulate_classifier=args.simulate_classifier)
    now = RW._parse_now(args.now) if getattr(args, "now", None) else None
    if now is not None and live:
        print(json.dumps({"outcome": "REFUSED", "detail": "--now is for dry runs only"}))
        return EXIT_REFUSED
    try:
        ctl = build_controller(live=live, config=cfg)
    except WriterNotArmed as exc:
        print(json.dumps({"outcome": "REFUSED_WRITER_NOT_ARMED", "detail": str(exc)}, indent=2))
        return EXIT_REFUSED
    code, body = ctl.run(now)
    print(json.dumps(body, indent=2, sort_keys=True, default=str) if args.json else render(code, body))
    return code


# ── n8n window requests (docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md rev 1, branch feat/release-train-n8n-20261021) ──
# The controller half of TrainWindowRequest@v1 / TrainWindowReceipt@v1 (C1-C11). The request schema and validator
# (config/schemas/release_train/train_window_request.v1.schema.json, scripts/lib/release_train_window.py) are not on
# this branch yet, so validate_request() below implements the contract's §5 table strictly; swap it for the shared
# validator when that lands. A request is never authority: everything is re-derived on the host.

REQUEST_SCHEMA, RECEIPT_SCHEMA = "TrainWindowRequest@v1", "TrainWindowReceipt@v1"
REQUEST_ID_RE = re.compile(r"^rtw-[0-9]{8}-[0-9]{4}-(win|f[0-9a-f]{6})$")
REQUEST_KEYS_REQUIRED = frozenset({"schema", "request_id", "window_slot", "window_id", "window_start", "tick",
                                   "shadow", "requested_at", "expires_at", "requested_by", "authority"})
REQUEST_KEYS_OPTIONAL = frozenset({"shadow_reason", "readiness", "note"})
REFUSAL_CODES = frozenset({"INVALID_REQUEST", "EXPIRED", "DUPLICATE_WINDOW", "STOP_SET", "STOP_UNREADABLE",
                           "NOT_ARMED", "DELEGATION_NOT_ACTIVE", "WINDOW_NOT_ENABLED", "OUTSIDE_WINDOW",
                           "CONTROLLER_BUILD_ONLY", "LOCK_HELD", "SHADOW_LIVE_MISMATCH"})
TERMINAL_RECEIPT_STATES = frozenset({"COMPLETED", "REFUSED", "EXPIRED", "FAILED"})
#: The controller's precise refusal -> the contract's closed set (C9). The contract has no code for a reconcile-first,
#: quarantined-lineage, bypass-environment or corrupt-control refusal; they map to the closest fail-closed code and
#: the precise reason travels in ``refusal.detail`` (reported as a contract gap in the packet README).
REFUSAL_MAP = {
    "REFUSED_STOP_LATCHED": "STOP_SET", "REFUSED_STOP_UNREADABLE": "STOP_UNREADABLE",
    "REFUSED_CONTROL_UNARMED": "NOT_ARMED", "REFUSED_CONTROL_CORRUPT": "NOT_ARMED", "REFUSED_REVOKED": "NOT_ARMED",
    "REFUSED_PAUSED": "NOT_ARMED", "REFUSED_STOPPED": "STOP_SET", "REFUSED_POLICY_NOT_ACCEPTED": "NOT_ARMED",
    "REFUSED_WINDOW_DISABLED": "WINDOW_NOT_ENABLED", "REFUSED_OFF_WINDOW": "OUTSIDE_WINDOW",
    "REFUSED_WINDOW_ALREADY_CLAIMED": "DUPLICATE_WINDOW", "REFUSED_TRAIN_BUSY": "LOCK_HELD",
    "REFUSED_TRAIN_ALREADY_CLAIMED": "LOCK_HELD", "REFUSED_RECONCILE_FIRST": "STOP_SET",
    "REFUSED_QUARANTINED_LINEAGE": "STOP_SET", "REFUSED_BYPASS_ENV": "NOT_ARMED",
}


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def validate_request(body: Any, filename: str) -> list[str]:
    """TrainWindowRequest@v1 (contract §5), strict: unknown keys are invalid (a request that names a SHA, PR, train
    id, capability or command is invalid), and every identity field must agree with the others."""
    if not isinstance(body, dict):
        return ["request is not an object"]
    errs = []
    keys = set(body)
    if REQUEST_KEYS_REQUIRED - keys:
        errs.append(f"missing {sorted(REQUEST_KEYS_REQUIRED - keys)}")
    extra = keys - REQUEST_KEYS_REQUIRED - REQUEST_KEYS_OPTIONAL
    if extra:
        errs.append(f"unknown fields {sorted(extra)} (a request carries no SHA, PR, train id or command)")
    if errs:
        return errs
    if body["schema"] != REQUEST_SCHEMA:
        errs.append("schema")
    rid = body["request_id"]
    if not (isinstance(rid, str) and REQUEST_ID_RE.match(rid)):
        errs.append("request_id pattern")
    elif filename != f"{rid}.json":
        errs.append("request_id disagrees with the file name")
    slot = body["window_slot"]
    if slot not in ("0000", "0600", "0800", "1800"):
        errs.append("window_slot")
    start = _parse_ts(body["window_start"])
    if start is None:
        errs.append("window_start")
    else:
        local = start.astimezone(TZ)
        if local.strftime("%H%M") != slot or local.isoformat(timespec="minutes") != body["window_id"]:
            errs.append("window_id / window_start / window_slot disagree")
        if isinstance(rid, str) and REQUEST_ID_RE.match(rid) and rid[4:17] != local.strftime("%Y%m%d-%H%M"):
            errs.append("request_id date/slot disagree with the window")
    if body["tick"] not in ("on_window", "off_window"):
        errs.append("tick")
    if not isinstance(body["shadow"], bool):
        errs.append("shadow must be a boolean")
    if body["tick"] == "off_window" and body["shadow"] is not True:
        errs.append("an off-window request is always shadow")
    if isinstance(rid, str) and rid.endswith("-win") != (body["tick"] == "on_window"):
        errs.append("request_id suffix disagrees with tick")
    if _parse_ts(body["requested_at"]) is None or _parse_ts(body["expires_at"]) is None:
        errs.append("requested_at / expires_at")
    if body["authority"] != "REQUEST_ONLY":
        errs.append("authority must be REQUEST_ONLY")
    rb = body["requested_by"]
    if not (isinstance(rb, dict) and isinstance(rb.get("lane_id"), str) and isinstance(rb.get("run_id"), str)):
        errs.append("requested_by")
    elif isinstance(slot, str) and rb["lane_id"] != f"release-train-request-{slot}":
        errs.append("requested_by.lane_id is not this slot's lane")
    return errs


class RequestSpool:
    """<state_dir>/train_requests/{pending,claimed,receipts}. Claim = os.rename(pending -> claimed) (C2). Nothing
    is ever deleted; a terminal receipt is never rewritten (C8)."""

    def __init__(self, state_root: Path) -> None:
        self.root = Path(state_root) / "train_requests"
        self.pending, self.claimed, self.receipts = self.root / "pending", self.root / "claimed", self.root / "receipts"

    def pending_files(self) -> list[Path]:
        try:
            return sorted(p for p in self.pending.iterdir() if p.is_file())
        except OSError:
            return []

    def claim(self, p: Path) -> Optional[Path]:
        self.claimed.mkdir(parents=True, exist_ok=True)
        dest = self.claimed / p.name
        if os.path.lexists(dest):
            return None                                   # a file of that name was already claimed: duplicate
        try:
            os.rename(p, dest)
        except FileNotFoundError:
            return None                                   # another claimer won the rename
        return dest

    def receipt(self, request_id: str) -> Optional[dict]:
        try:
            return json.loads((self.receipts / f"{request_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_receipt(self, request_id: str, body: dict) -> bool:
        prior = self.receipt(request_id)
        if prior and prior.get("state") in TERMINAL_RECEIPT_STATES:
            return False
        RC._atomic_write_json(self.receipts / f"{request_id}.json", body)
        return True


def _receipt(req: dict, *, state: str, mode: str, now: float, acknowledged_at: Optional[str] = None,
             refusal: Optional[dict] = None, rec: Optional[dict] = None, outcome: Optional[str] = None) -> dict:
    rec = rec or {}
    sel = rec.get("selection") or {}
    needs = [{"code": "NOT_RIDING", "pr": int(k), "text": str(v)[:160]} for k, v in
             list((sel.get("excluded") or {}).items())[:16]]
    needs += [{"code": "LIVE_WOULD_REFUSE", "pr": None, "text": str(x)[:160]} for x in rec.get("would_refuse") or []]
    manifest = rec.get("manifest") or {}
    members = [{"pr": m["pr"], "head_sha": m["head_sha"]} for m in manifest.get("members") or []]
    sims = [a["action"] for a in (rec.get("simulated_writes") or [])]
    if rec.get("outcome") == "DRY_RUN_COMPLETE":
        sims += ["prepare", "promote", "verify"]
    notif = rec.get("notification") or {}
    return {"schema": RECEIPT_SCHEMA, "request_id": req.get("request_id"), "window_id": req.get("window_id"),
            "window_slot": req.get("window_slot"), "shadow": req.get("shadow"), "mode": mode, "state": state,
            "acknowledged_at": acknowledged_at, "finished_at": utc_iso(now) if state in TERMINAL_RECEIPT_STATES
            else None,
            "controller": {"version": CONTROLLER_VERSION, "code_sha": None, "host": os.uname().nodename},
            "train_id": rec.get("train_id") if T_ID_RE.match(str(rec.get("train_id") or "")) else None,
            "outcome": outcome if state == "COMPLETED" else None, "refusal": refusal, "members": members,
            "candidate_sha": (rec.get("batch") or {}).get("candidate"),
            "main_sha": (rec.get("merge") or {}).get("main_sha"), "served_sha": None,
            "needs_action": needs[:20], "simulated_effects": list(dict.fromkeys(sims)) if mode == "simulate" else [],
            "injected_failures": [],
            "p1_alert": ({"sent_by": "host_notifier", "incident_key": f"release-train:{rec.get('train_id')}",
                          "at": rec.get("finished_at")} if notif.get("priority") == "P1" else None),
            "evidence_refs": []}


T_ID_RE = re.compile(r"^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$")


def _refusal(code: str, detail: str) -> dict:
    return {"code": code if code in REFUSAL_CODES else "INVALID_REQUEST", "detail": str(detail)[:200]}


def process_requests(state: RW.State, factory: Callable[[bool], TrainController], *, apply: bool,
                     now: Optional[Callable[[], float]] = None, live_status: Optional[str] = None) -> tuple[int, dict]:
    """Claim and answer pending TrainWindowRequest@v1 files (C1-C11). Without ``apply``: list what would be claimed
    and answered, run nothing, write nothing. With ``apply``: claim by rename, acknowledge, run the train (shadow ->
    dry run only, C3; live -> refused while the controller is BUILD_ONLY), write the terminal receipt."""
    clock = now or time.time
    spool = RequestSpool(state.root)
    out: dict = {"schema": "ReleaseTrainClaimRun@v1", "mode": "apply" if apply else "dry_run", "requests": []}
    status_ = live_status or TRAIN_CONTROLLER_STATUS
    lock = None
    if apply:
        lock = RC._Flock(spool.root / ".claimer.lock", 0.0)
        try:
            lock.acquire()
        except RC.ControlRefused:
            out["outcome"] = "CLAIMER_BUSY"
            return EXIT_OK, out
    try:
        files = spool.pending_files()
        bodies = []
        for p in files:
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                body = None
            bodies.append((p, body))
        bodies.sort(key=lambda pb: (str((pb[1] or {}).get("requested_at") or ""), pb[0].name)
                    if isinstance(pb[1], dict) else ("", pb[0].name))
        for p, body in bodies:
            out["requests"].append(_answer(spool, p, body, factory, apply=apply, clock=clock, status_=status_))
    finally:
        if lock is not None:
            lock.release()
    return EXIT_OK, out


def _answer(spool: RequestSpool, p: Path, body: Any, factory: Callable[[bool], TrainController], *, apply: bool,
            clock: Callable[[], float], status_: str) -> dict:
    name = p.name
    rid = (body or {}).get("request_id") if isinstance(body, dict) else None
    rid = rid if isinstance(rid, str) and REQUEST_ID_RE.match(rid) and name == f"{rid}.json" else name[:-5]
    item: dict = {"file": name, "request_id": rid}
    errs = validate_request(body, name)
    req = body if isinstance(body, dict) else {}
    if not apply:
        item["would"] = ("REFUSE INVALID_REQUEST: " + "; ".join(errs)) if errs else (
            f"claim; {'simulate (shadow)' if req.get('shadow') else 'live -> ' + ('refused: CONTROLLER_BUILD_ONLY' if status_ != 'ACTIVE' else 'run live')}")
        return item
    claimed = spool.claim(p)
    if claimed is None:
        item["result"] = "NOT_CLAIMED (another claimer, or a duplicate name already claimed)"
        if os.path.lexists(p) and os.path.lexists(spool.claimed / name):
            spool.write_receipt(rid, _receipt(req, state="REFUSED", mode="simulate", now=clock(),
                                              refusal=_refusal("DUPLICATE_WINDOW", "request already claimed")))
            item["result"] = "REFUSED DUPLICATE_WINDOW"
        return item
    shadow = req.get("shadow") is True
    mode = "simulate" if shadow or errs else "live"
    if errs:
        spool.write_receipt(rid, _receipt(req, state="REFUSED", mode="simulate", now=clock(),
                                          refusal=_refusal("INVALID_REQUEST", "; ".join(errs))))
        item["result"] = "REFUSED INVALID_REQUEST"
        return item
    if clock() > _parse_ts(req["expires_at"]).timestamp():
        spool.write_receipt(rid, _receipt(req, state="EXPIRED", mode=mode, now=clock(),
                                          refusal=_refusal("EXPIRED", f"expired at {req['expires_at']}")))
        item["result"] = "EXPIRED"
        return item
    ack = utc_iso(clock())
    spool.write_receipt(rid, _receipt(req, state="ACKNOWLEDGED", mode=mode, now=clock(), acknowledged_at=ack))
    if not shadow and status_ != "ACTIVE":
        spool.write_receipt(rid, _receipt(req, state="REFUSED", mode="live", now=clock(), acknowledged_at=ack,
                                          refusal=_refusal("CONTROLLER_BUILD_ONLY",
                                                           f"TRAIN_CONTROLLER_STATUS={status_}")))
        item["result"] = "REFUSED CONTROLLER_BUILD_ONLY"
        return item
    try:
        ctl = factory(not shadow)
        if shadow and ctl.live:
            raise Halt("REFUSED", "SHADOW_LIVE_MISMATCH", "a shadow request produced a live controller", refusal=True)
        start = _parse_ts(req["window_start"])
        at = start + timedelta(minutes=1) if (shadow and req["tick"] == "off_window") else None
        code, rec = ctl.run(at)
    except Halt as h:
        spool.write_receipt(rid, _receipt(req, state="REFUSED", mode=mode, now=clock(), acknowledged_at=ack,
                                          refusal=_refusal(h.reason, h.detail)))
        item["result"] = f"REFUSED {h.reason}"
        return item
    except Exception as exc:  # noqa: BLE001 - the controller itself failed: FAILED, exception type only
        spool.write_receipt(rid, _receipt(req, state="FAILED", mode=mode, now=clock(), acknowledged_at=ack,
                                          # C9 has no controller-error code (contract gap, packet README):
                                          # LOCK_HELD for a busy lock, else NOT_ARMED; detail = exception type.
                                          refusal={"code": "LOCK_HELD" if isinstance(exc, RC.LockBusy)
                                                   else "NOT_ARMED", "detail": type(exc).__name__}))
        item["result"] = f"FAILED {type(exc).__name__}"
        return item
    if isinstance(ctl.writer, SimulatedGitHubWriter):
        rec["simulated_writes"] = ctl.writer.actions
    got = (rec.get("window") or {}).get("window_id")
    if rec.get("refused"):
        code9 = REFUSAL_MAP.get(str(rec.get("reason")), "NOT_ARMED")
        receipt = _receipt(req, state="REFUSED", mode=mode, now=clock(), acknowledged_at=ack, rec=rec,
                           refusal=_refusal(code9, f"{rec.get('reason')}: {rec.get('detail') or ''}"))
    elif got != req["window_id"]:
        receipt = _receipt(req, state="REFUSED", mode=mode, now=clock(), acknowledged_at=ack, rec=rec,
                           refusal=_refusal("OUTSIDE_WINDOW", f"the host derived window {got}, not {req['window_id']}"))
    else:
        oc = rec.get("outcome")
        if shadow and oc not in (NO_OP, FAILED_PRE_MERGE, STOPPED, CANCELLED):
            oc = NO_OP                                  # simulate: never a release, never a fake success (§7)
        receipt = _receipt(req, state="COMPLETED", mode=mode, now=clock(), acknowledged_at=ack, rec=rec,
                           outcome=oc if oc in TERMINAL_OUTCOMES else CANCELLED)
    spool.write_receipt(rid, receipt)
    item["result"] = f"{receipt['state']} {receipt.get('outcome') or (receipt.get('refusal') or {}).get('code')}"
    item["train_id"] = rec.get("train_id")
    return item


def cli_claim(args: Any) -> int:
    def factory(live: bool) -> TrainController:
        return build_controller(live=live)
    code, body = process_requests(RW.State(), factory, apply=bool(getattr(args, "apply", False)))
    print(json.dumps(body, indent=2, default=str))
    return code
