#!/usr/bin/env python3
"""Release-window runner: release the exact origin/main head at 12:00 and 17:30 America/New_York.

Operator decision 2026-10-16: "Adopt daily release windows at 12:00 and 17:30 America/New_York, with valid
authorization covering preparation, promotion, verification and rollback. Preserve the existing emergency
process for urgent fixes." Packet: docs/ops/packets/release-windows-20261016/README.md.

  plan     [--window 1200|1730] [--now ISO]   read-only dry run: candidate, PR list, CI evidence, grant verdict
  run      [--window 1200|1730] [--now ISO]   select -> prepare -> promote -> verify -> (auto) rollback
  status                                      STOP latch + last receipt
  clear-stop --reason TEXT                    operator: archive the STOP latch (never deleted)

One window, one candidate:
  * the candidate is the origin/main head at the window, and ONLY if every push/main workflow on that exact SHA
    (and every REQUIRED_PUSH_WORKFLOWS entry) is completed/success. No older green SHA is substituted; no CI wait.
    A merge after selection waits for the next window.
  * `prepare` runs on that SHA (cio_phase2_exact_main_deploy.sh requires release-checkout HEAD == origin/main), then
    `promote <prepared dir>` promotes THAT artifact (promote reads its BUILD_SHA and re-checks exact-SHA CI).
  * verification: promote exit 0, CURRENT -> prepared dir, BUILD_SHA == candidate, units that were active stay
    active, /api/health 200, served-copy check (scripts/check_served_copy_split.py) exit 0.
  * a failed verification rolls back with the deploy script's own `rollback <prev>` and LATCHES a STOP.

Authorization is the existing guard ledger only: an active `release-write` grant whose reason carries the window
token (see WINDOW_TOKEN_HELP) and matches scripts/lib/release_grant_binding.py by campaign id. The runner reads
the ledger, never writes a grant; it REVOKES the window grant (tightening only) when the window ends or a stop
condition fires. Stop conditions: CI not green, a failed verification, a rollback. The runner never sets an
emergency flag, a warn mode or a bypass, and refuses to start when one is set in its environment.

Exit codes: 0 released / nothing new / already ran; 2 refused before any release action (disarmed, latched,
off-window, bypass env, busy); 3 window stopped without a release (CI not green, main moved, prepare failed);
4 verification failed and the rollback succeeded (STOP latched); 5 rollback failed (STOP latched, page operator).
No broker, no credential read, no send, no crontab/systemd edit.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA = "ReleaseWindowReceipt@v1"
TZ = ZoneInfo("America/New_York")
WINDOWS = {"1200": (12, 0), "1730": (17, 30)}
GRACE_MIN = int(os.environ.get("TRADEAI_RELEASE_WINDOW_GRACE_MIN", "45"))
TIER = "release-write"
TOKEN = "RELEASE_WINDOW"
STOP_NAMES = ("verify_failed", "rolled_back", "ci_not_green")
CAMPAIGN_RE = re.compile(r"\brelease-window-(\d{8})-(\d{4})\b")
WINDOW_TOKEN_HELP = (
    "RELEASE_WINDOW release-window-<YYYYMMDD>-<HHMM> actions=prepare,promote,verify,rollback "
    "stop=verify_failed,rolled_back,ci_not_green")
MIN_GRANT_USES = 2            # prepare + promote each consume one use (release_grant_preflight.py)
MIN_GRANT_REMAINING_S = 15 * 60

# Policy switches. A grant naming more than one window (a daily or standing grant) is outside AGENTS §24.8
# ("one grant per release") until the amendment in the packet is ratified; flipping this is that PR's job.
MULTI_WINDOW_GRANT_STATUS = "PROPOSED"

# Environment that would weaken a deploy gate. Value set = values allowed (empty = must be unset).
GUARDED_ENV: dict[str, frozenset[str]] = {
    "TRADEAI_EMERGENCY_RELEASE_SHA": frozenset(),
    "TRADEAI_RELEASE_GRANT_BINDING": frozenset({"enforce"}),
    "TRADEAI_CONFORMANCE_GATE_OVERRIDE": frozenset(),
    "TRADEAI_CONFORMANCE_GATE": frozenset({"block", "warn"}),   # warn is the deploy default; block is stricter
    "TRADEAI_RELEASE_PIN_MODE": frozenset({"apply"}),
    "TRADEAI_RELEASE_VENV_MODE": frozenset({"link"}),
    "TRADEAI_TREE_ATTESTED_PROMOTE": frozenset({"0"}),
    "CIO_DEPLOY_FF_DEV_TREE": frozenset({"1"}),
    "TRADEAI_GUARD_CONSUME": frozenset({"1"}),
}

HOME = Path.home()
CANONICAL_SOURCE = Path(os.environ.get("CANONICAL_SOURCE", str(HOME / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild")))
RELEASES_BASE = Path(os.environ.get("TRADEAI_RELEASES_BASE", str(HOME / "trade-ai-releases" / "portfolio-server")))
RELEASE_CHECKOUT = Path(os.environ.get("TRADEAI_RELEASE_CHECKOUT", str(HOME / "tradeai-exact-main-20260827")))
STATE_ROOT = Path(os.environ.get("TRADEAI_STATE_ROOT", str(HOME / "trade-ai-releases" / "persistent-state")))
STATE_DIR = Path(os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(STATE_ROOT / "data" / "runtime" / "release_window")))
HEALTH_URL = os.environ.get("TRADEAI_RELEASE_WINDOW_HEALTH_URL", "http://127.0.0.1:7777/api/health")
UNITS = tuple(os.environ.get(
    "TRADEAI_RELEASE_WINDOW_UNITS",
    "portfolio-server.service cio-governed-bridge.service tradeai-n8n-coordination-gateway.service "
    "tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service").split())

EXIT_OK, EXIT_REFUSED, EXIT_STOPPED, EXIT_ROLLED_BACK, EXIT_ROLLBACK_FAILED = 0, 2, 3, 4, 5
TERMINAL = {"RELEASED", "NO_CHANGE", "STOP_CI_NOT_GREEN", "STOP_CI_PENDING", "STOP_MAIN_MOVED",
            "STOP_PREPARE_FAILED", "ROLLED_BACK", "ROLLBACK_FAILED"}


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── window arithmetic ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    day: str          # YYYYMMDD (America/New_York)
    hhmm: str         # 1200 | 1730
    opens: datetime
    closes: datetime

    @property
    def window_id(self) -> str:
        return f"{self.day}-{self.hhmm}"

    @property
    def campaign(self) -> str:
        return f"release-window-{self.day}-{self.hhmm}"


def window_for(now: datetime, hhmm: str) -> Window:
    local = now.astimezone(TZ)
    h, m = WINDOWS[hhmm]
    opens = local.replace(hour=h, minute=m, second=0, microsecond=0)
    return Window(local.strftime("%Y%m%d"), hhmm, opens, opens + timedelta(minutes=GRACE_MIN))


def open_window(now: datetime, requested: Optional[str] = None) -> Optional[Window]:
    """The window open at `now` (opens <= now < opens + grace), optionally restricted to `requested`."""
    for hhmm in WINDOWS:
        if requested and hhmm != requested:
            continue
        w = window_for(now, hhmm)
        if w.opens <= now.astimezone(TZ) < w.closes:
            return w
    return None


# ── grant verdict (reads the guard ledger; never writes it) ───────────────────────────────────────

def grant_verdict(window: Window, sha: str, grants: list[dict[str, Any]], *, now_ts: float,
                  pr_number: Optional[int] = None, requests: Optional[list[dict[str, Any]]] = None) -> dict:
    """Whether an active release-write grant authorizes THIS window's prepare, promote and rollback."""
    from scripts.lib.release_grant_binding import ReleaseAction, decide

    out: dict[str, Any] = {"ok": False, "campaign": window.campaign, "errors": []}
    verdicts = {}
    for action in ("prepare", "promote", "rollback"):
        v = decide(ReleaseAction(action=action, target_sha=sha, pr_number=pr_number, campaign=window.campaign,
                                 now=now_ts), grants=grants, requests=requests or [])
        verdicts[action] = v.to_dict()
        if not v.allowed:
            out["errors"].append(f"{action}:{v.reason}")
    out["binding"] = verdicts
    if out["errors"]:
        return out
    gid = verdicts["prepare"]["grant_id"]
    if any(verdicts[a]["grant_id"] != gid for a in ("promote", "rollback")):
        out["errors"].append("prepare/promote/rollback matched different grants")
        return out
    row = next((g for g in grants if str(g.get("grant_id") or g.get("id") or "") == gid), {})
    reason = str(row.get("reason") or "")
    out.update(grant_id=gid, expires=row.get("expires"), uses=row.get("uses"), reason=reason[:400])
    if TOKEN not in reason:
        out["errors"].append(f"grant reason lacks the {TOKEN} token ({WINDOW_TOKEN_HELP})")
    missing = [s for s in STOP_NAMES if s not in reason]
    if missing:
        out["errors"].append("grant reason does not state the stop conditions: " + ",".join(missing))
    named = sorted({f"release-window-{d}-{t}" for d, t in CAMPAIGN_RE.findall(reason)})
    out["windows_named"] = named
    if window.campaign not in named:
        out["errors"].append(f"grant reason does not name {window.campaign}")
    if len(named) > 1 and MULTI_WINDOW_GRANT_STATUS != "ACTIVE":
        out["errors"].append("grant names more than one window; a multi-window grant needs the §24.8 window "
                             "amendment (MULTI_WINDOW_GRANT_STATUS=PROPOSED) — one grant per window")
    try:
        uses = int(row.get("uses"))
    except (TypeError, ValueError):
        uses = 0
    if 0 <= uses < MIN_GRANT_USES:
        out["errors"].append(f"grant has {uses} uses; a window needs {MIN_GRANT_USES} (prepare + promote)")
    try:
        remaining = float(row.get("expires")) - now_ts
    except (TypeError, ValueError):
        remaining = -1
    if remaining < MIN_GRANT_REMAINING_S:
        out["errors"].append(f"grant expires in {int(remaining)}s; a window needs >= {MIN_GRANT_REMAINING_S}s")
    out["ok"] = not out["errors"]
    return out


def later_windows_named(window: Window, verdict: dict) -> list[str]:
    return [c for c in verdict.get("windows_named") or [] if c > window.campaign]


# ── helpers on evidence ────────────────────────────────────────────────────────────────────────────

_PREPARE_OK_RE = re.compile(r"PREPARE OK: (/\S+)")
_PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)\b")
_PR_SQUASH_RE = re.compile(r"\(#(\d+)\)\s*$")


def prs_from_messages(messages: list[str]) -> list[int]:
    seen: list[int] = []
    for msg in messages:
        first = (msg or "").splitlines()[0] if msg else ""
        m = _PR_MERGE_RE.match(first) or _PR_SQUASH_RE.search(first)
        if m and int(m.group(1)) not in seen:
            seen.append(int(m.group(1)))
    return seen


def ci_outcome(evidence: dict) -> Optional[str]:
    """None when green; STOP_CI_PENDING when only runs in flight / not yet started; else STOP_CI_NOT_GREEN."""
    if evidence.get("ok"):
        return None
    errors = evidence.get("errors") or []
    pending_states = {"queued", "in_progress", "pending", "waiting", "requested"}
    by_path = {c.get("path"): c for c in evidence.get("checks") or []}
    hard = []
    for e in errors:
        kind, _, path = str(e).partition(":")
        if kind == "missing":
            continue                      # required workflow not started yet → pending
        if kind == "not_successful" and str((by_path.get(path) or {}).get("status")) in pending_states:
            continue
        hard.append(e)
    return "STOP_CI_NOT_GREEN" if hard else "STOP_CI_PENDING"


def guarded_env_violations(env: dict[str, str]) -> list[str]:
    bad = []
    for name, allowed in GUARDED_ENV.items():
        if name in env and env[name] != "" and env[name] not in allowed:
            bad.append(name)
    return bad


def deploy_env(base: dict[str, str], window: Window, pr: Optional[int]) -> dict[str, str]:
    env = {k: v for k, v in base.items() if k not in GUARDED_ENV}
    env["TRADEAI_RELEASE_CAMPAIGN"] = window.campaign
    if pr is not None:
        env["TRADEAI_RELEASE_PR"] = str(pr)
    else:
        env.pop("TRADEAI_RELEASE_PR", None)
    return env


# ── host adapter (everything with a side effect or a network read) ─────────────────────────────────

class Host:
    """Real host. Tests substitute a fake; nothing here is called at import."""

    def __init__(self, *, checkout: Path = RELEASE_CHECKOUT, releases: Path = RELEASES_BASE,
                 canonical: Path = CANONICAL_SOURCE) -> None:
        self.checkout, self.releases, self.canonical = checkout, releases, canonical
        self.deploy = checkout / "scripts" / "cio_phase2_exact_main_deploy.sh"
        self.python = canonical / ".venv" / "bin" / "python"

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _run(self, argv: list[str], *, timeout: int = 120, env=None, cwd=None) -> tuple[int, str]:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, f"{type(exc).__name__}: {str(exc)[:200]}"

    def main_head(self) -> str:
        rc, out = self._run(["git", "-C", str(self.checkout), "ls-remote", "origin", "refs/heads/main"])
        m = re.match(r"^([0-9a-f]{40})\s+refs/heads/main$", out.strip().splitlines()[0] if out.strip() else "")
        if rc != 0 or not m:
            raise RuntimeError("could not read origin/main head")
        return m.group(1)

    def current_release(self) -> Path:
        return (self.releases / "CURRENT").resolve()

    def build_sha(self, release: Path) -> str:
        try:
            return (release / "BUILD_SHA").read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def commit_messages(self, base: str, head: str) -> list[str]:
        repo = self._repository()
        rc, out = self._run(["gh", "api", f"repos/{repo}/compare/{base}...{head}",
                             "--jq", "[.commits[].commit.message]"], timeout=60)
        if rc != 0:
            raise RuntimeError("compare unavailable")
        return list(json.loads(out))

    def _repository(self) -> str:
        rc, out = self._run(["git", "-C", str(self.checkout), "remote", "get-url", "origin"])
        m = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", out.strip())
        if rc != 0 or not m:
            raise RuntimeError("unsupported origin remote")
        return m.group(1)

    def ci_evidence(self, sha: str) -> dict:
        from scripts.release_grant_preflight import collect_push_checks
        return collect_push_checks(sha)

    def grants(self) -> list[dict]:
        from scripts.lib import release_grant_binding as B
        return B.load_grants(B.GRANTS_PATH)

    def requests(self) -> list[dict]:
        from scripts.lib import release_grant_binding as B
        return B.load_requests(B.REQUESTS_PATH)

    def checkout_clean(self) -> bool:
        rc, out = self._run(["git", "-C", str(self.checkout), "status", "--porcelain"])
        return rc == 0 and not out.strip()

    def checkout_sha(self, sha: str) -> tuple[int, str]:
        rc, out = self._run(["git", "-C", str(self.checkout), "fetch", "-q", "origin", "main"], timeout=180)
        if rc != 0:
            return rc, out
        return self._run(["git", "-C", str(self.checkout), "checkout", "-q", "--detach", sha])

    def run_deploy(self, args: list[str], env: dict[str, str]) -> tuple[int, str]:
        return self._run(["bash", str(self.deploy), *args], timeout=3600, env=env, cwd=str(self.checkout))

    def units_active(self, units: tuple[str, ...]) -> dict[str, bool]:
        state = {}
        for u in units:
            rc, _ = self._run(["systemctl", "--user", "is-active", "--quiet", u], timeout=20)
            state[u] = rc == 0
        return state

    def http_status(self, url: str) -> int:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 (loopback constant)
                return int(r.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (OSError, ValueError):
            return 0

    def served_copy(self, release: Path) -> tuple[int, str]:
        tool = release / "scripts" / "check_served_copy_split.py"
        return self._run([str(self.python), str(tool), "--no-count", "--dev-root", str(self.canonical),
                          "--served-root", str(self.releases / "CURRENT")], timeout=180)

    def revoke(self) -> tuple[int, str]:
        # Tightening only (guard-lib: revoke is unguarded; grant/plan are blocked for agents).
        return self._run([str(self.canonical / "bin" / "guard"), "revoke", TIER], timeout=30)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# ── state ─────────────────────────────────────────────────────────────────────────────────────────

class State:
    def __init__(self, root: Path = STATE_DIR) -> None:
        self.root = root
        self.latch = root / "STOP.json"
        self.last = root / "last.json"
        self.windows = root / "windows"

    def receipt_path(self, window: Window) -> Path:
        return self.windows / f"{window.window_id}.json"

    def read(self, path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, path: Path, body: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


# ── the window ────────────────────────────────────────────────────────────────────────────────────

class Runner:
    def __init__(self, host: Host, state: State, *, env: Optional[dict[str, str]] = None,
                 units: tuple[str, ...] = UNITS, health_url: str = HEALTH_URL,
                 health_attempts: int = 12, health_sleep_s: float = 5.0) -> None:
        self.host, self.state = host, state
        self.env = dict(os.environ if env is None else env)
        self.units, self.health_url = units, health_url
        self.health_attempts, self.health_sleep_s = health_attempts, health_sleep_s

    # -- shared selection (plan and run) --
    def _select(self, window: Window, now_ts: float, rec: dict) -> Optional[int]:
        """Fill candidate, PR list, CI evidence and grant verdict. Returns an exit code to stop with, or None."""
        head = self.host.main_head()
        cur = self.host.current_release()
        base = self.host.build_sha(cur)
        rec["current"] = {"release": str(cur), "build_sha": base}
        rec["candidate"] = {"sha": head, "short": head[:9]}
        if head == base:
            rec["outcome"] = "NO_CHANGE"
            return EXIT_OK
        try:
            prs = prs_from_messages(self.host.commit_messages(base, head)) if base else []
            rec["candidate"].update(prs=prs, compare_base=base)
        except (RuntimeError, ValueError) as exc:
            rec["candidate"].update(prs=None, prs_error=str(exc)[:200], compare_base=base)
        prs = rec["candidate"].get("prs") or []
        pr = max(prs) if prs else None
        rec["candidate"]["release_pr"] = pr
        grant = grant_verdict(window, head, self.host.grants(), now_ts=now_ts, pr_number=pr,
                              requests=self.host.requests())
        rec["grant"] = grant
        evidence = self.host.ci_evidence(head)      # read-only; recorded even when disarmed
        rec["ci"] = evidence
        stop = ci_outcome(evidence)
        rec["ci_verdict"] = stop or "GREEN"
        if not grant["ok"]:
            rec["outcome"] = "DISARMED"
            return EXIT_REFUSED
        if stop:
            rec["outcome"] = stop
            return EXIT_STOPPED
        return None

    def _base_receipt(self, window: Window, mode: str, now: datetime) -> dict:
        return {"schema": SCHEMA, "mode": mode, "window_id": window.window_id, "campaign": window.campaign,
                "window_opens": window.opens.isoformat(), "window_closes": window.closes.isoformat(),
                "started_at": utc_iso(now.timestamp()), "events": []}

    def _preconditions(self, now: datetime, requested: Optional[str]) -> tuple[Optional[Window], Optional[dict]]:
        bad = guarded_env_violations(self.env)
        if bad:
            return None, {"outcome": "REFUSED_BYPASS_ENV", "names": bad,
                          "detail": "emergency/warn/bypass variables are never used by a release window"}
        latch = self.state.read(self.state.latch)
        if latch:
            return None, {"outcome": "REFUSED_STOP_LATCHED", "latch": latch,
                          "detail": "operator: scripts/release_window.py clear-stop --reason ..."}
        w = open_window(now, requested)
        if w is None:
            return None, {"outcome": "REFUSED_OFF_WINDOW", "now_et": now.astimezone(TZ).isoformat(),
                          "windows_et": sorted(WINDOWS), "grace_min": GRACE_MIN,
                          "detail": "off-window releases use the existing process (grant naming the PR/SHA) "
                                    "or the CI-outage emergency process; see the packet README"}
        return w, None

    def plan(self, requested: Optional[str] = None, now: Optional[datetime] = None) -> tuple[int, dict]:
        now = now or self.host.now()
        w, refusal = self._preconditions(now, requested)
        if refusal and refusal["outcome"] == "REFUSED_OFF_WINDOW" and requested:
            w, refusal = window_for(now, requested), None      # a plan may preview a named window off-hours
        if refusal:
            return EXIT_REFUSED, {"schema": SCHEMA, "mode": "plan", **refusal}
        rec = self._base_receipt(w, "plan", now)
        code = self._select(w, now.timestamp(), rec)
        if code is None:
            rec["outcome"] = "WOULD_RELEASE"
            code = EXIT_OK
        return code, rec

    def run(self, requested: Optional[str] = None, now: Optional[datetime] = None) -> tuple[int, dict]:
        now = now or self.host.now()
        w, refusal = self._preconditions(now, requested)
        if refusal:
            return EXIT_REFUSED, {"schema": SCHEMA, "mode": "run", **refusal}
        prior = self.state.read(self.state.receipt_path(w))
        if prior and prior.get("outcome") in TERMINAL:
            return EXIT_OK, {"schema": SCHEMA, "mode": "run", "outcome": "ALREADY_RAN", "window_id": w.window_id,
                             "prior_outcome": prior.get("outcome")}
        self.state.root.mkdir(parents=True, exist_ok=True)
        lock = open(self.state.root / ".lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return EXIT_REFUSED, {"schema": SCHEMA, "mode": "run", "outcome": "REFUSED_BUSY", "window_id": w.window_id}
        try:
            rec = self._base_receipt(w, "run", now)
            code = self._window(w, now, rec)
            rec["exit_code"] = code
            rec["finished_at"] = utc_iso(self.host.now().timestamp())
            if rec.get("outcome") != "DISARMED":       # a disarmed window leaves no receipt to block a re-run
                self.state.write(self.state.receipt_path(w), rec)
            self.state.write(self.state.last, rec)
            return code, rec
        finally:
            lock.close()

    def _event(self, rec: dict, step: str, **kw: Any) -> None:
        rec["events"].append({"at": utc_iso(self.host.now().timestamp()), "step": step, **kw})

    def _stop(self, w: Window, rec: dict, code: int, *, latch: bool) -> int:
        if latch:
            body = {"latched_at": utc_iso(self.host.now().timestamp()), "window_id": w.window_id,
                    "outcome": rec.get("outcome"), "candidate": (rec.get("candidate") or {}).get("sha"),
                    "detail": "release windows halted; operator reviews the receipt then runs clear-stop"}
            self.state.write(self.state.latch, body)
            rec["stop_latched"] = body
        self._revoke(w, rec, force=True)
        return code

    def _revoke(self, w: Window, rec: dict, *, force: bool) -> None:
        g = rec.get("grant") or {}
        gid = g.get("grant_id")
        if not gid:
            return
        if not force and later_windows_named(w, g):
            rec["revocation"] = {"done": False, "why": "grant also names a later window"}
            return
        current = next((x for x in self.host.grants() if str(x.get("tier")) == TIER), {})
        if str(current.get("grant_id") or "") != gid:
            rec["revocation"] = {"done": False, "why": "ledger's release-write grant is no longer this window's"}
            return
        rc, out = self.host.revoke()
        rec["revocation"] = {"done": rc == 0, "rc": rc, "grant_id": gid, "output": out.strip()[-200:]}

    def _window(self, w: Window, now: datetime, rec: dict) -> int:
        code = self._select(w, now.timestamp(), rec)
        if code is not None:
            if rec["outcome"] == "NO_CHANGE":
                self._revoke(w, rec, force=False)
                return code
            if rec["outcome"] == "DISARMED":
                return code
            return self._stop(w, rec, code, latch=False)          # CI not green / pending: stop this window
        sha = rec["candidate"]["sha"]
        env = deploy_env(self.env, w, rec["candidate"].get("release_pr"))
        if not self.host.checkout_clean():
            rec["outcome"] = "STOP_PREPARE_FAILED"
            self._event(rec, "checkout", ok=False, detail="release checkout is dirty")
            return self._stop(w, rec, EXIT_STOPPED, latch=False)
        rc, out = self.host.checkout_sha(sha)
        self._event(rec, "checkout", ok=rc == 0, rc=rc, tail=out.strip()[-300:])
        if rc != 0:
            rec["outcome"] = "STOP_PREPARE_FAILED"
            return self._stop(w, rec, EXIT_STOPPED, latch=False)
        # ── prepare ──
        rc, out = self.host.run_deploy(["prepare"], env)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        ok_lines = [m.group(1) for m in (_PREPARE_OK_RE.search(ln) for ln in lines) if m]
        prepared = Path(os.path.realpath(ok_lines[-1])) if ok_lines else None
        rec["prepare"] = {"rc": rc, "release_dir": str(prepared) if prepared else None, "tail": "\n".join(lines[-6:])}
        if rc != 0 or prepared is None:
            rec["outcome"] = "STOP_MAIN_MOVED" if "!= origin/main" in out else "STOP_PREPARE_FAILED"
            return self._stop(w, rec, EXIT_STOPPED, latch=False)
        stamped = self.host.build_sha(prepared)
        if stamped != sha:
            rec["prepare"]["build_sha"] = stamped
            rec["outcome"] = "STOP_PREPARE_FAILED"
            return self._stop(w, rec, EXIT_STOPPED, latch=False)
        # ── promote THAT artifact ──
        prev = self.host.current_release()
        before = self.host.units_active(self.units)
        rec["rollback_target"] = str(prev)
        rc, out = self.host.run_deploy(["promote", str(prepared)], env)
        rec["promote"] = {"rc": rc, "tail": "\n".join([ln for ln in out.splitlines() if ln.strip()][-6:])}
        # ── verify ──
        checks = self._verify(prepared, sha, before, promote_rc=rc)
        rec["verification"] = checks
        if all(c["ok"] for c in checks.values()):
            rec["outcome"] = "RELEASED"
            self._revoke(w, rec, force=False)
            return EXIT_OK
        # ── roll back ──
        if self.host.current_release() == prev:
            rec["rollback"] = {"by": "deploy promote (internal health rollback)", "ok": True}
            rec["outcome"] = "ROLLED_BACK"
            return self._stop(w, rec, EXIT_ROLLED_BACK, latch=True)
        rc, out = self.host.run_deploy(["rollback", str(prev)], env)
        health = self._health()
        ok = rc == 0 and self.host.current_release() == prev and health == 200
        rec["rollback"] = {"by": "cio_phase2_exact_main_deploy.sh rollback", "rc": rc, "target": str(prev),
                           "health": health, "ok": ok, "tail": "\n".join(out.strip().splitlines()[-6:])}
        rec["outcome"] = "ROLLED_BACK" if ok else "ROLLBACK_FAILED"
        return self._stop(w, rec, EXIT_ROLLED_BACK if ok else EXIT_ROLLBACK_FAILED, latch=True)

    def _health(self) -> int:
        code = 0
        for i in range(self.health_attempts):
            code = self.host.http_status(self.health_url)
            if code == 200:
                return code
            if i + 1 < self.health_attempts:
                self.host.sleep(self.health_sleep_s)
        return code

    def _verify(self, prepared: Path, sha: str, before: dict[str, bool], *, promote_rc: int) -> dict:
        cur = self.host.current_release()
        checks: dict[str, dict] = {
            "promote_exit": {"ok": promote_rc == 0, "rc": promote_rc},
            "current_symlink": {"ok": cur == Path(os.path.realpath(prepared)), "current": str(cur), "expected": str(prepared)},
            "build_sha": {"ok": self.host.build_sha(cur) == sha, "build_sha": self.host.build_sha(cur), "expected": sha},
        }
        code = self._health()
        checks["api_health"] = {"ok": code == 200, "http": code, "url": self.health_url}
        after = self.host.units_active(self.units)
        dropped = [u for u, was in before.items() if was and not after.get(u)]
        checks["units"] = {"ok": not dropped, "inactive_after_promote": dropped, "after": after}
        rc, out = self.host.served_copy(cur)
        checks["served_copy"] = {"ok": rc == 0, "rc": rc, "tail": "\n".join(out.strip().splitlines()[-3:])}
        return checks

    def clear_stop(self, reason: str) -> tuple[int, dict]:
        latch = self.state.read(self.state.latch)
        if not latch:
            return EXIT_OK, {"outcome": "NO_LATCH"}
        stamp = self.host.now().strftime("%Y%m%dT%H%M%SZ")
        archived = self.state.windows / f"STOP-cleared-{stamp}.json"
        self.state.write(archived, {**latch, "cleared_at": stamp, "cleared_reason": reason})
        self.state.latch.rename(self.state.windows / f"STOP-{stamp}.json.archived")
        return EXIT_OK, {"outcome": "STOP_CLEARED", "archived": str(archived)}

    def status(self) -> tuple[int, dict]:
        return EXIT_OK, {"latch": self.state.read(self.state.latch), "last": self.state.read(self.state.last),
                         "multi_window_grant_status": MULTI_WINDOW_GRANT_STATUS, "windows_et": sorted(WINDOWS),
                         "grace_min": GRACE_MIN, "grant_token": WINDOW_TOKEN_HELP}


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--window", choices=sorted(WINDOWS))
        if name == "plan":
            p.add_argument("--now", help="ISO time to evaluate (plan only); naive = America/New_York")
    sub.add_parser("status")
    c = sub.add_parser("clear-stop")
    c.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    runner = Runner(Host(), State())
    if args.cmd == "plan":
        code, body = runner.plan(args.window, _parse_now(args.now))
    elif args.cmd == "run":
        code, body = runner.run(args.window)
    elif args.cmd == "status":
        code, body = runner.status()
    else:
        code, body = runner.clear_stop(args.reason)
    print(json.dumps(body, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
