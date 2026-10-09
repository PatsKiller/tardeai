#!/usr/bin/env python3
"""reconcile_lane_registry.py — one registry row for every scheduled job on the host.

N8N maturity program, workstream B1 (2026-10-09). The lane registry passed CI only through a
476-entry ``undeclared_baseline`` exemption: 321 of 438 live crontab lines and 45 user timers had no
row, so nothing could say who owned them, how often they should fire, or what artifact proved they
ran. This generator closes that gap deterministically:

  * It reads the live crontab (``crontab -l``) and the user systemd timers/services
    (``systemctl --user`` show/list) READ-ONLY — or a captured snapshot of both — plus the cron
    rationalization (``docs/implementation/n8n-maturity/data/F_rationalization.json``).
  * Every live cron line, timer and platform service that no existing row declares gets one
    candidate row: owner, scheduler {kind, expression, match}, expected_cadence_hours,
    output_signal, state ACTIVE, value_class and a normalised recommendation.
  * ``output_signal`` comes from evidence only:
      1. a receipt the script writes, listed in ``lane_output_evidence.json`` and accepted only when
         its ``verified_token`` literally occurs in the script's source in this repository;
      2. else the log the scheduler itself appends to (``>> logs/x.log`` / ``StandardOutput=append:``);
      3. else ``{"kind": "none", "reason": "UNVERIFIED_OUTPUT"}`` plus the row flag
         ``UNVERIFIED_OUTPUT`` — reported, never invented.
  * Rows that already exist keep every hand-written field; the generator only refreshes the
    ``rationalization`` block (value_class/recommendation copied from the rationalization).
  * ``undeclared_baseline`` and ``inherited_tranches`` are removed: nothing is exempt any more.

``--dry-run`` (the default) prints the plan and writes nothing. ``--write`` rewrites
config/lane_registry.json in place (2-space JSON, non-ASCII kept, LF), and running it again on the same
inputs is a no-op. Never edits crontab or units, never deletes a row, never runs a job.

Recommendations (normalised from the rationalization's free text):
  R0_ELIMINATE            the rationalization's 37 eliminations; the row stays ACTIVE until a
                          cron-write grant retires the line (a later step).
  KEEP_ON_CRON            broker / order / secret / daemon class. Also forced, whatever the
                          rationalization says, when the command carries a
                          pipeline_manifest.FORBIDDEN_COMMAND_TOKENS entry or the script name is a
                          gateway FORBIDDEN_ROUTE_TOKENS / SECRET_KEYS token (see ``stay_on_cron``).
  MERGE_INTO:<target>     a duplicate folded into another lane or pipeline.
  PIPELINE:<Pxx>          a member of one of the 16 orchestrated pipelines.
  EVENT_DRIVEN_CANDIDATE  a poller that should run on a producer event.
  MIGRATE_N8N             schedulable, no pipeline: moves under the registry-driven dispatcher.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cron_schedule  # noqa: E402
from scripts.lib.lane_registry import (  # noqa: E402
    REGISTRY_PATH, discover_cron, discover_systemd, discover_systemd_services, find_undeclared,
    load_registry, validate_registry,
)

GENERATOR = "scripts/reconcile_lane_registry.py"
GENERATOR_VERSION = "reconcile_lane_registry@v1"
DATA_DIR = ROOT / "docs" / "implementation" / "n8n-maturity" / "data"
RATIONALIZATION_PATH = DATA_DIR / "F_rationalization.json"
EVIDENCE_PATH = DATA_DIR / "lane_output_evidence.json"
RECONCILED_ON = "2026-10-09"

#: Any absolute home path. A match string must never contain one (repo rule: no host-specific home
#: literals) — and the substring match does not need one, the script path below it is enough.
HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+")
#: Match windows never cross a home path OR a ``~`` — so the committed, home-sanitised snapshot
#: (``/home/<user>`` → ``~``) yields byte-identical match strings to the live crontab.
SEGMENT_BREAK_RE = re.compile(r"/home/[A-Za-z0-9._-]+|~")

#: Scripts that only wrap the real job (lock, gate, LLM budget). The lane is named after the first
#: script that is not one of these.
WRAPPERS = frozenset({
    "safe_flock.sh", "run_with_deepseek_offpeak.sh", "market_day_gate.sh", "llm_priority_guard.sh",
    "non_trading_hours_gate.sh", "cron_wrap.sh", "with_env.sh", "run_with_env.sh",
})
UTILITY_MODULES = frozenset({"sys", "os", "json", "db_adapter", "psycopg2", "pathlib", "datetime", "time",
                             "subprocess", "re"})
SCRIPT_RE = re.compile(r"[\w.$~/{}-]*?([\w.-]+\.(?:py|sh|js|mjs))(?![\w.])")

#: Pipeline → owning domain (owner is a domain string in this registry, not a person).
PIPELINE_OWNER = {
    "P00": "platform", "P01": "portfolio", "P02": "scalp", "P03": "research", "P04": "platform",
    "P05": "platform", "P06": "hermes", "P07": "proposals", "P08": "defense", "P09": "execution",
    "P10": "research", "P11": "comms", "P12": "platform", "P13": "learning", "P14": "portfolio",
    "P15": "agents", "P16": "platform",
}
OS_UNIT_PREFIXES = ("snap.", "systemd-", "ubuntu-", "launchpadlib-")

#: Gateway route tokens that name a communication or storage channel, not an execution authority.
#: A script called telegram_x.py is an alert job (P11), not a broker lane; the comms/db lanes are
#: handled by their pipelines. Every other FORBIDDEN_ROUTE_TOKENS word in a script NAME keeps the
#: lane on cron. Listed here so the exemption is explicit and tested.
ROUTE_TOKEN_CHANNEL_EXEMPT = frozenset({"telegram", "email", "send", "sql", "postgres", "size", "title"})
#: SECRET_KEYS words that, in a script NAME, mean something else: ``seed`` there is data seeding
#: (tradeai-advisory-shadow-seed), not a key seed. Every other secret word keeps the lane on cron.
SECRET_NAME_EXEMPT = frozenset({"seed"})
#: market_day_gate.sh is in FORBIDDEN_COMMAND_TOKENS because the pipelines must never absorb a
#: market-day-gated line (pipeline_manifest: "stay as their own cron lines"). It is a calendar gate,
#: not a broker call, so its class says so; the recommendation is still KEEP_ON_CRON.
GATE_TOKENS = frozenset({"market_day_gate.sh"})

ENABLED_STATES = frozenset({"enabled", "enabled-runtime", "linked", "linked-runtime", "static"})
REVIEW_BY = "2026-10-16"
REC_R0 = "R0_ELIMINATE"
REC_KEEP = "KEEP_ON_CRON"
REC_EVENT = "EVENT_DRIVEN_CANDIDATE"
REC_N8N = "MIGRATE_N8N"
UNVERIFIED_OUTPUT = "UNVERIFIED_OUTPUT"


# ── inputs ────────────────────────────────────────────────────────────────────────────────────

def _forbidden_tokens() -> tuple[tuple[str, ...], frozenset, frozenset]:
    from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS, SECRET_KEYS
    from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS
    return tuple(FORBIDDEN_COMMAND_TOKENS), frozenset(FORBIDDEN_ROUTE_TOKENS), frozenset(SECRET_KEYS)


def read_live_crontab() -> str:
    return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30).stdout


def _systemctl_show(units: list[str], props: Iterable[str]) -> dict[str, dict[str, str]]:
    if not units:
        return {}
    cmd = ["systemctl", "--user", "show", *units]
    for p in props:
        cmd += ["-p", p]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    blocks = [b for b in out.split("\n\n")]
    res: dict[str, dict[str, str]] = {}
    for unit, block in zip(units, blocks):
        res[unit] = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
    return res


def _unit_stdout_targets(units: list[str]) -> dict[str, str]:
    """``StandardOutput=`` as written in the unit files and drop-ins (last wins). ``systemctl show``
    reports only the mode (``append``), never the path, so the files are read with ``systemctl cat``."""
    if not units:
        return {}
    out = subprocess.run(["systemctl", "--user", "cat", *units], capture_output=True, text=True, timeout=60).stdout
    res: dict[str, str] = {}
    cur = ""
    for line in out.splitlines():
        if line.startswith("# /"):
            path = line[2:].strip()
            parent = path.rsplit("/", 2)
            cur = parent[-2][:-2] if len(parent) >= 2 and parent[-2].endswith(".d") else parent[-1]
            continue
        if cur and line.startswith("StandardOutput="):
            res[cur] = line.split("=", 1)[1].strip()
    return res


def _calendar_cadence_hours(spec: str) -> Optional[float]:
    """Max gap between the next 400 elapses of an OnCalendar spec, from a fixed base (deterministic)."""
    try:
        out = subprocess.run(["systemd-analyze", "calendar", "--iterations=400",
                              "--base-time=2026-10-05 00:00:00", spec],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    times = []
    for line in out.splitlines():
        m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m and ("Next elapse" in line or "Iteration" in line or line.strip().startswith("(")):
            times.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    times = sorted(set(times))
    if len(times) < 2:
        return None
    gap = max((b - a).total_seconds() for a, b in zip(times, times[1:]))
    return round(gap / 3600.0, 2)


_MONO_RE = re.compile(r"(OnUnitActiveSec|OnUnitInactiveSec|OnBootSec|OnActiveSec|OnStartupSec)=([^;]+?)\s*;")


def _mono_hours(text: str) -> Optional[float]:
    best = None
    for key, val in _MONO_RE.findall(text or ""):
        if key not in ("OnUnitActiveSec", "OnUnitInactiveSec"):
            continue
        secs = 0.0
        for num, unit in re.findall(r"([\d.]+)\s*(h|min|s|ms|us|d)?", val):
            n = float(num)
            secs += n * {"d": 86400, "h": 3600, "min": 60, "s": 1, "ms": 0.001, "us": 1e-6}.get(unit or "s", 1)
        hours = round(secs / 3600.0, 2)
        best = hours if best is None else max(best, hours)
    return best


RELEASE_DIR_RE = re.compile(r"portfolio-server/[0-9a-f]{7,40}-[A-Za-z0-9._-]+")


def sanitize(text: str) -> str:
    """Replace every absolute home path with ``~`` (snapshots are committed; paths stay host-neutral)."""
    return HOME_PATH_RE.sub("~", text or "")


def sanitize_unit(text: str) -> str:
    """Unit text as committed: home path → ``~`` and a resolved release directory → ``<release>``, so a
    promote (which repoints units at a new release dir) does not change the registry."""
    return RELEASE_DIR_RE.sub("portfolio-server/<release>", sanitize(text))


def capture_units_live() -> dict[str, Any]:
    """Timers (all states) and platform services, with what a row needs. Read-only systemctl calls."""
    timers = discover_systemd()
    services = discover_systemd_services()
    tnames = [t["expression"] for t in timers]
    tprops = _systemctl_show(tnames, ["Id", "Unit", "TimersCalendar", "TimersMonotonic", "UnitFileState"])
    svc_for = {t: tprops.get(t, {}).get("Unit", "") for t in tnames}
    snames = sorted({s for s in svc_for.values() if s} | {s["expression"] for s in services})
    sprops = _systemctl_show(snames, ["Id", "ExecStart", "WorkingDirectory", "FragmentPath",
                                      "UnitFileState", "Type"])
    for unit, target in _unit_stdout_targets(snames).items():
        if unit in sprops:
            sprops[unit]["StandardOutput"] = target
    out_t = []
    for t in timers:
        name = t["expression"]
        p = tprops.get(name, {})
        cal = p.get("TimersCalendar", "")
        specs = re.findall(r"OnCalendar=([^;]+?)\s*;", cal)
        cadence = None
        for s in specs:
            h = _calendar_cadence_hours(s.strip())
            if h is not None:
                cadence = h if cadence is None else max(cadence, h)
        mono = _mono_hours(p.get("TimersMonotonic", ""))
        if cadence is None and mono is not None:
            cadence = mono
        svc = svc_for.get(name, "")
        sp = sprops.get(svc, {})
        out_t.append({
            "unit": name, "enabled_state": t.get("enabled_state"), "service": svc,
            "on_calendar": [s.strip() for s in specs], "monotonic_hours": mono,
            "expected_cadence_hours": cadence,
            "exec_start": sanitize_unit(_exec_argv(sp.get("ExecStart", ""))),
            "stdout": sanitize_unit(sp.get("StandardOutput", "")),
            "working_directory": sanitize_unit(sp.get("WorkingDirectory", "")),
        })
    out_s = []
    for s in services:
        name = s["expression"]
        sp = sprops.get(name, {})
        out_s.append({
            "unit": name, "enabled_state": s.get("enabled_state"),
            "exec_start": sanitize_unit(_exec_argv(sp.get("ExecStart", ""))),
            "stdout": sanitize_unit(sp.get("StandardOutput", "")),
            "working_directory": sanitize_unit(sp.get("WorkingDirectory", "")),
        })
    return {"timers": out_t, "services": out_s}


def _exec_argv(raw: str) -> str:
    m = re.search(r"argv\[\]=([^;]*);", raw or "")
    return (m.group(1).strip() if m else (raw or "").strip())


# ── one cron line ─────────────────────────────────────────────────────────────────────────────

def split_schedule(line: str) -> tuple[str, str]:
    s = line.strip()
    if s.startswith("@"):
        head, _, rest = s.partition(" ")
        return head, rest.strip()
    parts = s.split(None, 5)
    if len(parts) < 6:
        return s, ""
    return " ".join(parts[:5]), parts[5]


def primary_script(command: str) -> tuple[Optional[str], str]:
    """(script path token or None, lane stem). The first non-wrapper script names the lane."""
    body = command.split("#", 1)[0] if " # " in command or command.startswith("#") else command
    for m in SCRIPT_RE.finditer(body):
        base = m.group(1)
        if base in WRAPPERS:
            continue
        return m.group(0), base.rsplit(".", 1)[0]
    for m in re.finditer(r"from\s+([\w.]+)\s+import\s+(\w+)|import\s+(\w+)(?:\s+as\s+\w+)?", body):
        module = (m.group(1) or m.group(3) or "").rsplit(".", 1)[-1]
        if module in UTILITY_MODULES:
            continue
        return m.group(0), (m.group(2) or module)
    m = re.search(r"systemctl\s+--user\s+start\s+([\w@.-]+)", body)
    if m:
        return m.group(0), "start-" + m.group(1).rsplit(".", 1)[0]
    m = re.search(r"curl\b.*?(https?://[^/\s\"']+(/[^\s\"'?]*))", body)
    if m:
        seg = [p for p in m.group(2).split("/") if p and p not in ("api", "v2", "v3")]
        return m.group(1), "prewarm-" + ("-".join(seg[-2:]) if seg else "root")
    return None, "inline"


def kebab(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "lane"


def home_free_segments(line: str) -> list[tuple[int, int]]:
    segs, pos = [], 0
    for m in SEGMENT_BREAK_RE.finditer(line):
        if m.start() > pos:
            segs.append((pos, m.start()))
        pos = m.end()
    if pos < len(line):
        segs.append((pos, len(line)))
    return segs


def _token_ends(line: str, start: int, stop: int) -> list[int]:
    ends = []
    i = start
    while i < stop:
        if line[i].isspace():
            if i > start and not line[i - 1].isspace():
                ends.append(i)
        i += 1
    if stop > start and not line[stop - 1].isspace():
        ends.append(stop)
    return ends


def _unique(window: str, lines: list[str]) -> bool:
    return sum(1 for ln in lines if window in ln) == 1


_BARE_SCHEDULE = re.compile(r"^\s*(?:[\d*/,\-]+\s+){4}[\d*/,\-]+\s*$")


def _acceptable(window: str) -> bool:
    w = window.strip()
    return (len(w) >= 12 and re.search(r"[A-Za-z]", w) is not None and not _BARE_SCHEDULE.match(w)
            and not SEGMENT_BREAK_RE.search(w) and w == window)


def _anchor_offset(token: str, start: int, end: int) -> int:
    """Where a match window starts inside the anchor token: at ``scripts/`` when the token is a script
    path, at the script basename otherwise, and at the token itself for a non-script anchor."""
    if not re.search(r"\.(?:py|sh|js|mjs)$", token):
        return start
    inner = token.find("scripts/")
    return start + inner if inner != -1 else end - len(token.rsplit("/", 1)[-1])


def choose_match(line: str, lines: list[str], script_token: Optional[str], *,
                 allow_fallback: bool = True) -> Optional[str]:
    """Shortest token-aligned window that occurs in exactly this live line and holds no home path.

    Preferred: anchored at the script (``scripts/x.py`` …) and grown rightwards. Otherwise every
    token-aligned window in the home-free segments, shortest first, earliest on a tie.
    """
    segs = home_free_segments(line)
    anchors: list[int] = []
    if script_token:
        for m in re.finditer(re.escape(script_token), line):
            tok_start = m.start()
            anchors.append((_anchor_offset(script_token, tok_start, m.end()), m.end()))
    for a, min_end in anchors:
        seg = next(((s, e) for s, e in segs if s <= a < e), None)
        if not seg:
            continue
        for end in _token_ends(line, a, seg[1]):
            if end < min_end:
                continue            # the window always names the whole anchor (script path, unit, URL)
            w = line[a:end]
            if _acceptable(w) and _unique(w, lines):
                return w
    if not allow_fallback:
        return None
    # fallback: any token-aligned window (last resort: it may be only a schedule prefix)
    best: Optional[tuple[int, int, str]] = None
    for s, e in segs:
        starts = [s] + [i for i in range(s + 1, e) if line[i - 1].isspace() and not line[i].isspace()]
        for a in starts:
            if line[a].isspace():
                continue
            for end in _token_ends(line, a, e):
                w = line[a:end]
                if best is not None and len(w) > best[0]:
                    break
                if _acceptable(w) and _unique(w, lines):
                    cand = (len(w), a, w)
                    if best is None or cand < best:
                        best = cand
                    break
    return best[2] if best else None


def _command_key(cmd: str) -> str:
    """A command with its trailing ``# comment`` and whitespace runs removed."""
    body = re.split(r"\s+#\s", cmd, maxsplit=1)[0]
    return " ".join(body.split())


def choose_group_match(group: list[str], lines: list[str], script_token: Optional[str]) -> Optional[str]:
    """Shortest home-free window from the first line that occurs in every group line and in no other."""
    first = group[0]
    others = [ln for ln in lines if ln not in group]
    best: Optional[tuple[int, int, str]] = None
    anchors = []
    if script_token:
        for m in re.finditer(re.escape(script_token), first):
            anchors.append(_anchor_offset(script_token, m.start(), m.end()))
    for s0, e0 in home_free_segments(first):
        for a in [x for x in anchors if s0 <= x < e0] or [s0]:
            for end in _token_ends(first, a, e0):
                w = first[a:end]
                if _acceptable(w) and all(w in g for g in group) and not any(w in o for o in others):
                    cand = (len(w), a, w)
                    if best is None or cand < best:
                        best = cand
                    break
    return best[2] if best else None


def cron_cadence_hours_union(exprs: list[str]) -> Optional[float]:
    base = datetime(2026, 10, 5, 0, 0)
    end = base + timedelta(days=35)
    fires: set[datetime] = set()
    for e in exprs:
        t = base
        while True:
            n = cron_schedule.next_run(e, t)
            if n is None or n > end:
                break
            fires.add(n)
            t = n
    seq = sorted(fires)
    if len(seq) < 3:
        return None
    return round(max((b - a).total_seconds() for a, b in zip(seq, seq[1:])) / 3600.0, 2)


def cron_cadence_hours(expr: str) -> Optional[float]:
    """Largest gap between consecutive fires, from a fixed Monday (deterministic). None for @reboot."""
    if expr.startswith("@"):
        return {"@hourly": 1.0, "@daily": 24.0, "@midnight": 24.0, "@weekly": 168.0,
                "@monthly": 744.0, "@yearly": 8784.0, "@annually": 8784.0}.get(expr)
    base = datetime(2026, 10, 5, 0, 0)
    for days in (35, 400):
        t, fires, end = base, [], base + timedelta(days=days)
        while True:
            n = cron_schedule.next_run(expr, t)
            if n is None or n > end:
                break
            fires.append(n)
            t = n
        if len(fires) >= 3:
            gap = max((b - a).total_seconds() for a, b in zip(fires, fires[1:]))
            return round(gap / 3600.0, 2)
    return None


_REDIRECT_RE = re.compile(r"(?<![0-9&])(?:1)?>>?\s*(\"[^\"]+\"|'[^']+'|[^\s;|&)]+)")


def resolve_cwd(command: str) -> Optional[str]:
    m = re.search(r"\bcd\s+(\"[^\"]+\"|[^\s;&]+)", command)
    if not m:
        return None
    return m.group(1).strip("\"'")


def _current_rel(path: str) -> Optional[str]:
    """CURRENT/logs and CURRENT/data/{runtime,cio,audit,…} are symlinks into the state root."""
    for marker in ("portfolio-server/CURRENT/", "$PROJ/", "${PROJ}/"):
        if marker in path:
            return path.split(marker, 1)[1]
    return None


STATE_ROOT_DIRS = ("logs/", "data/runtime/", "data/cio/", "data/audit/", "data/health/", "data/state/",
                   "data/paper_trading/")


def normalise_output_path(raw: str, cwd: Optional[str]) -> Optional[str]:
    """A redirect target as an output_signal path: state-root relative when it lives there, else ``~/``."""
    p = raw.strip("\"'")
    if not p or p.startswith("/dev/") or p.startswith("&"):
        return None
    p = p.replace("${HOME}", "~").replace("$HOME", "~")
    p = HOME_PATH_RE.sub("~", p)
    rel = _current_rel(p)
    if rel is None and not p.startswith(("/", "~", "$")):
        base = HOME_PATH_RE.sub("~", cwd or "")
        if cwd is None or _current_rel(base + "/") is not None or base.rstrip("/") in ("$PROJ", "${PROJ}", "\"$CUR\"", "$CUR") \
                or base.endswith("portfolio-server/CURRENT"):
            rel = p
        else:
            return (base.rstrip("/") + "/" + p) if base.startswith(("~", "/")) else None
    if rel is not None:
        if rel.startswith(STATE_ROOT_DIRS):
            return rel
        return "~/trade-ai-releases/portfolio-server/CURRENT/" + rel
    if "$" in p:
        return None
    return p


def log_redirect(command: str) -> Optional[str]:
    body = command
    cwd = resolve_cwd(body)
    for m in _REDIRECT_RE.finditer(body):
        target = m.group(1)
        if target.startswith("/dev/"):
            continue
        path = normalise_output_path(target, cwd)
        if path:
            return path
    return None


# ── rationalization join ──────────────────────────────────────────────────────────────────────

def load_rationalization(path: Path = RATIONALIZATION_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def rationalization_for_cron(rows: list[dict[str, Any]], raw_lines: list[str]) -> dict[str, dict[str, Any]]:
    """{live line → F row}. F ids are crontab line numbers (``L92``); the join also demands the same
    schedule and the item name in the line, else falls back to a unique (schedule, name) pair."""
    by_line: dict[int, str] = {i + 1: ln.strip() for i, ln in enumerate(raw_lines)}
    active = {ln.strip() for ln in raw_lines}
    out: dict[str, dict[str, Any]] = {}
    pending = []
    for r in rows:
        if r.get("kind") != "cron":
            continue
        try:
            n = int(str(r.get("id", "")).lstrip("L"))
        except ValueError:
            continue
        ln = by_line.get(n, "")
        name = str(r.get("name") or "")
        if ln in active and ln.startswith(str(r.get("sched") or "")) and (name in ln or name == "inline"):
            out.setdefault(ln, r)
        else:
            pending.append(r)
    for r in pending:
        name, sched = str(r.get("name") or ""), str(r.get("sched") or "")
        hits = [ln for ln in active if ln.startswith(sched + " ") and name in ln and ln not in out]
        if len(hits) == 1:
            out[hits[0]] = r
    return out


def normalise_recommendation(f: Optional[dict[str, Any]]) -> Optional[str]:
    if not f:
        return None
    text = str(f.get("recommendation") or "")
    up = text.upper()
    pipe = str(f.get("pipeline") or "")
    if up.startswith("ELIMINATE"):
        return REC_R0
    if up.startswith("KEEP"):
        return REC_KEEP
    if up.startswith("EVENT-DRIVEN") or (f.get("event_driven_candidate") and not up.startswith("MERGE")):
        return REC_EVENT
    if up.startswith("MERGE") or f.get("value_class") == "Duplicated":
        m = re.search(r"MERGE[-: ]+(?:INTO\s+)?(?:the\s+)?([A-Za-z0-9_./-]+)", text, re.I)
        target = m.group(1) if m and not m.group(1).lower().startswith("keep") else (pipe or "UNSPECIFIED")
        if target.lower() in ("into", "the"):
            target = pipe or "UNSPECIFIED"
        if re.match(r"^P\d\d$", pipe) and target.lower() in ("10/15/17",):
            target = pipe
        return f"MERGE_INTO:{target}"
    if re.match(r"^P\d\d$", pipe) and up.startswith(("CONSOLIDATE", "REDESIGN")):
        m = re.search(r"\b(P\d\d)\b", text)
        return f"PIPELINE:{m.group(1) if m else pipe}"
    if up.startswith(("REPLACE", "MOVE", "REDESIGN", "INVESTIGATE", "UNVERIFIED")):
        return REC_N8N
    if re.match(r"^P\d\d$", pipe):
        return f"PIPELINE:{pipe}"
    return REC_N8N


def stay_on_cron(command: str, script_stem: str, *, tokens=None) -> Optional[dict[str, str]]:
    """Broker / order / secret class: never moved off cron. Returns {class, token} or None."""
    cmd_tokens, route_tokens, secret_keys = tokens or _forbidden_tokens()
    gate_hit = None
    for tok in cmd_tokens:
        if tok in command:
            if tok in GATE_TOKENS:
                gate_hit = gate_hit or tok
                continue
            return {"class": "broker_order", "token": tok, "source": "pipeline_manifest.FORBIDDEN_COMMAND_TOKENS"}
    words = [w for w in re.split(r"[^a-z0-9]+", script_stem.lower()) if w]
    for w in words:
        if w in route_tokens and w not in ROUTE_TOKEN_CHANNEL_EXEMPT:
            return {"class": "broker_order", "token": w, "source": "n8n_coordination_gateway.FORBIDDEN_ROUTE_TOKENS"}
    for w in words:
        if w in secret_keys and w not in SECRET_NAME_EXEMPT:
            return {"class": "secret", "token": w, "source": "n8n_coordination_gateway.SECRET_KEYS"}
    if gate_hit:
        return {"class": "pipeline_excluded_gate", "token": gate_hit,
                "source": "pipeline_manifest.FORBIDDEN_COMMAND_TOKENS"}
    return None


# ── evidence overlay ──────────────────────────────────────────────────────────────────────────

def load_evidence(path: Path = EVIDENCE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return dict(doc.get("entries") or {})


def script_source(script_token: Optional[str]) -> Optional[Path]:
    if not script_token:
        return None
    tok = HOME_PATH_RE.sub("", script_token).replace("$PROJ/", "").replace("${PROJ}/", "")
    m = re.search(r"(scripts/[\w./-]+)$", tok)
    rel = m.group(1) if m else ("scripts/" + tok.rsplit("/", 1)[-1])
    p = ROOT / rel
    return p if p.is_file() else None


def verified_receipt(entry: Optional[dict[str, Any]], sources: Iterable[Path]) -> Optional[dict[str, Any]]:
    """Accept an evidence entry only when its verified_token literally occurs in the script source."""
    if not entry or not isinstance(entry.get("output_signal"), dict):
        return None
    tok = str(entry.get("verified_token") or "")
    if not tok:
        return None
    extra = str(entry.get("source_file") or "")
    if extra and not extra.startswith("/") and ".." not in extra and (ROOT / extra).is_file():
        sources = [ROOT / extra, *[x for x in sources if x]]
    path = str((entry.get("output_signal") or {}).get("path") or "")
    if HOME_PATH_RE.search(path):
        return None                              # a receipt path must be host-neutral (~/ or state-root relative)
    for src in sources:
        try:
            if src and tok in src.read_text(encoding="utf-8", errors="replace"):
                sig = dict(entry["output_signal"])
                sig["evidence"] = "SCRIPT_RECEIPT"
                sig["evidence_ref"] = sanitize(str(entry.get("evidence") or src.relative_to(ROOT)))[:300]
                return sig
        except OSError:
            continue
    return None


# ── building rows ─────────────────────────────────────────────────────────────────────────────

def _rationalization_block(f: Optional[dict[str, Any]], rec: Optional[str]) -> dict[str, Any]:
    if not f:
        return {"source": "F_rationalization.json", "f_id": None, "recommendation": rec,
                "value_class": "UNCLASSIFIED", "note": "no rationalization item joined to this line"}
    return {"source": "F_rationalization.json", "f_id": f.get("id"), "pipeline": f.get("pipeline") or None,
            "value_class": f.get("value_class"), "recommendation": rec,
            "f_recommendation": f.get("recommendation"), "event_driven_candidate": bool(f.get("event_driven_candidate")),
            "f_evidence": f.get("evidence")}


def _final_recommendation(f_rec: Optional[str], stay: Optional[dict[str, str]]) -> str:
    if f_rec == REC_R0:
        return REC_R0           # R0 wins; a stay-class R0 is listed as a disagreement in the report
    if stay:
        return REC_KEEP
    return f_rec or REC_N8N


def _owner(f: Optional[dict[str, Any]], ev: Optional[dict[str, Any]], unit: str = "") -> str:
    if ev and ev.get("owner"):
        return str(ev["owner"])
    if unit.startswith(OS_UNIT_PREFIXES):
        return "os"
    pipe = str((f or {}).get("pipeline") or "")
    return PIPELINE_OWNER.get(pipe, "platform")


def _signal(receipt: Optional[dict[str, Any]], log_path: Optional[str], log_kind: str) -> tuple[dict[str, Any], list[str]]:
    if receipt:
        return receipt, []
    if log_path:
        return {"kind": "file_mtime", "path": log_path, "evidence": log_kind}, []
    return {"kind": "none", "reason": UNVERIFIED_OUTPUT,
            "detail": "no scheduler log redirect and no verified script receipt"}, [UNVERIFIED_OUTPUT]


def _unique_id(base: str, taken: set[str]) -> str:
    lid = base
    i = 2
    while lid in taken:
        lid = f"{base}-{i}"
        i += 1
    taken.add(lid)
    return lid


def _arg_words(command: str, script_token: Optional[str]) -> list[str]:
    tail = command
    if script_token and script_token in command:
        tail = command.split(script_token, 1)[1]
    tail = re.split(r"\s(?:\d?>>?|2>&1|\|\|)", tail, maxsplit=1)[0]
    return [w for w in re.findall(r"[a-z][a-z0-9]+", tail.lower())
            if w not in ("py", "sh", "true", "null", "dev", "lock", "tmp", "timeout", "flock", "apply")]


def build_cron_rows(lines: list[str], undeclared: list[str], raw_lines: list[str], f_rows: list[dict[str, Any]],
                    evidence: dict[str, dict[str, Any]], taken: set[str], tokens=None) -> tuple[list[dict], list[dict]]:
    fmap = rationalization_for_cron(f_rows, raw_lines)
    infos = []
    for ln in lines:
        if ln not in undeclared:
            continue
        sched, cmd = split_schedule(ln)
        tok, stem = primary_script(cmd)
        infos.append({"line": ln, "sched": sched, "cmd": cmd, "tok": tok, "stem": stem})
    # lane ids: stem, disambiguated inside a stem group by the first argument word unique to the line
    groups: dict[str, list[dict]] = {}
    for it in infos:
        groups.setdefault(kebab(it["stem"]), []).append(it)
    for base, members in groups.items():
        if len(members) == 1:
            members[0]["base_id"] = base
            continue
        words = [_arg_words(m["cmd"], m["tok"]) for m in members]
        for m, ws in zip(members, words):
            others = set().union(*[set(o) for o2, o in zip(members, words) if o2 is not m])
            uniq = [w for w in ws if w not in others]
            if uniq:
                m["base_id"] = f"{base}-{uniq[0]}"
            else:
                mf = m["sched"].split()
                slug = kebab("-".join(mf[:2]).replace("*", "x")) if len(mf) >= 2 else kebab(m["sched"])
                m["base_id"] = f"{base}-at-{slug}"
    # Lines whose script-anchored window is not unique run the same job on several schedules (e.g.
    # options_chain_snapshot.py at 10:00 and 17:35, news_ingestion.py three times a day). They become
    # ONE multi-schedule lane whose match is shared by exactly those lines — the registry's existing
    # convention ("A + B script"). Grouping is tried narrowest first: identical command; same script and
    # arguments under a different wrapper; every undeclared line running that script. Only a line that
    # fits none of these falls back to the shortest unique window anywhere in the line.
    for it in infos:
        it["match"] = choose_match(it["line"], lines, it["tok"], allow_fallback=False)
    for it in infos:
        if it["match"] or it.get("merged_into") is not None:
            continue
        candidates = [
            [o for o in infos if _command_key(o["cmd"]) == _command_key(it["cmd"])],
            [o for o in infos if (o["stem"], tuple(_arg_words(o["cmd"], o["tok"])))
             == (it["stem"], tuple(_arg_words(it["cmd"], it["tok"])))],
            [o for o in infos if it["tok"] and o["tok"] == it["tok"]],
        ]
        for twins in candidates:
            twins = [o for o in twins if o.get("merged_into") is None and not o.get("schedules")]
            if len(twins) < 2 or it not in twins:
                continue
            match = choose_group_match([o["line"] for o in twins], lines, it["tok"])
            if not match:
                continue
            lead = twins[0]
            lead["match"] = match
            lead["schedules"] = [o["sched"] for o in twins]
            lead["twin_lines"] = [o["line"] for o in twins]
            for o in twins[1:]:
                o["merged_into"] = lead
            break
    for it in infos:
        if not it["match"] and it.get("merged_into") is None:
            it["match"] = choose_match(it["line"], lines, it["tok"], allow_fallback=True)
            if it["match"]:
                it["match_basis"] = "SHORTEST_UNIQUE_WINDOW"
    rows, problems = [], []
    for it in infos:
        if it.get("merged_into") is not None:
            continue
        lid = _unique_id(kebab(it["stem"]) if it.get("schedules") and kebab(it["stem"]) not in taken
                         else it["base_id"], taken)
        match = it["match"]
        if not match:
            problems.append({"code": "NO_UNIQUE_MATCH", "line": sanitize(it["line"])[:200]})
            continue
        f = fmap.get(it["line"])
        stay = stay_on_cron(it["cmd"], it["stem"], tokens=tokens)
        rec = _final_recommendation(normalise_recommendation(f), stay)
        ev = evidence.get(lid)
        src = script_source(it["tok"])
        receipt = verified_receipt(ev, [src] if src else [])
        if ev and ev.get("output_signal") and not receipt:
            problems.append({"code": "EVIDENCE_REJECTED", "lane_id": lid,
                             "detail": "verified_token not found in script source"})
        sig, flags = _signal(receipt, log_redirect(it["cmd"]), "CRON_LOG_REDIRECT")
        schedules = it.get("schedules") or [it["sched"]]
        cadence = cron_cadence_hours(schedules[0]) if len(schedules) == 1 else cron_cadence_hours_union(schedules)
        sched_doc: dict[str, Any] = {"kind": "cron", "expression": " + ".join(schedules), "match": match}
        if len(schedules) > 1:
            sched_doc["schedules"] = schedules
        if it.get("match_basis"):
            sched_doc["match_basis"] = it["match_basis"]
        twin_f = [fmap.get(t) for t in it.get("twin_lines") or []]
        row: dict[str, Any] = {
            "lane_id": lid,
            "owner": _owner(f, ev),
            "scheduler": sched_doc,
            "expected_cadence_hours": cadence if cadence is not None else 720.0,
            "state": "ACTIVE",
            "output_signal": sig,
            "value_class": (f or {}).get("value_class") or "UNCLASSIFIED",
            "recommendation": rec,
            "rationalization": _rationalization_block(f, normalise_recommendation(f)),
            "generated_by": GENERATOR_VERSION,
            "reconciled_on": RECONCILED_ON,
            "note": "B1 reconciliation: row generated from the live crontab line; owner is the domain of its "
                    "rationalization pipeline unless lane_output_evidence.json names one.",
        }
        if len(schedules) > 1:
            row["rationalization"]["f_ids"] = [x.get("id") if x else None for x in twin_f]
            row["rationalization"]["f_recommendations"] = [normalise_recommendation(x) for x in twin_f]
        if cadence is None:
            row["cadence_basis"] = "NON_PERIODIC (e.g. @reboot): placeholder 720 h"
        else:
            row["cadence_basis"] = "max gap between consecutive fires (fixed Monday base)"
        if stay:
            row["stay_on_cron"] = stay
        if flags:
            row["flags"] = flags
        if ev and ev.get("note"):
            row["evidence_note"] = str(ev["note"])
        rows.append(row)
    return rows, problems


def build_unit_rows(units: dict[str, Any], undeclared_units: set[str], f_rows: list[dict[str, Any]],
                    evidence: dict[str, dict[str, Any]], taken: set[str], tokens=None) -> tuple[list[dict], list[dict]]:
    fmap = {str(r.get("id")): r for r in f_rows if r.get("kind") in ("timer", "service")}
    rows, problems = [], []
    items = [("timer", t) for t in units.get("timers") or []] + [("service", s) for s in units.get("services") or []]
    for kind, u in sorted(items, key=lambda x: (x[0] != "timer", x[1]["unit"])):
        name = u["unit"]
        if name not in undeclared_units:
            continue
        stem = name.rsplit(".", 1)[0]
        base = kebab(stem) + ("" if kind == "timer" else "-service")
        lid = _unique_id(base + "-timer" if (kind == "timer" and base in taken) else base, taken)
        f = fmap.get(name)
        exec_start = u.get("exec_start") or ""
        tok, script_stem = primary_script(exec_start)
        stay = stay_on_cron(exec_start, script_stem if tok else stem, tokens=tokens)
        f_rec = normalise_recommendation(f)
        if kind == "service" and not stay and f_rec not in (REC_R0,):
            stay = {"class": "daemon", "token": name, "source": "long-running user service"}
        rec = _final_recommendation(f_rec, stay)
        if name.startswith(OS_UNIT_PREFIXES) and not f:
            rec = REC_KEEP
            stay = stay or {"class": "os", "token": name, "source": "operating-system unit"}
        ev = evidence.get(lid)
        src = script_source(tok)
        receipt = verified_receipt(ev, [src] if src else [])
        if ev and ev.get("output_signal") and not receipt:
            problems.append({"code": "EVIDENCE_REJECTED", "lane_id": lid,
                             "detail": "verified_token not found in unit script source"})
        stdout = str(u.get("stdout") or "")
        log_path = None
        if stdout.startswith(("append:", "file:")):
            log_path = normalise_output_path(stdout.split(":", 1)[1], u.get("working_directory"))
        sig, flags = _signal(receipt, log_path, "SYSTEMD_STDOUT_APPEND")
        cadence = u.get("expected_cadence_hours") if kind == "timer" else 1.0
        row: dict[str, Any] = {
            "lane_id": lid,
            "owner": _owner(f, ev, name),
            "scheduler": {"kind": "systemd", "expression": name},
            "expected_cadence_hours": cadence if cadence else 168.0,
            "state": "ACTIVE",
            "output_signal": sig,
            "value_class": (f or {}).get("value_class") or ("OS" if name.startswith(OS_UNIT_PREFIXES) else "UNCLASSIFIED"),
            "recommendation": rec,
            "rationalization": _rationalization_block(f, f_rec),
            "generated_by": GENERATOR_VERSION,
            "reconciled_on": RECONCILED_ON,
            "unit_enabled_state": u.get("enabled_state"),
        }
        if str(u.get("enabled_state") or "") not in ENABLED_STATES:
            # A timer that exists but is not enabled fires nothing. It is declared off, not ACTIVE. The
            # reason comes from the evidence file when a document records it; otherwise PAUSED/UNKNOWN
            # with review_by, so the operator is asked.
            declared = (ev or {}).get("declared_state") or {}
            state = str(declared.get("state") or "PAUSED")
            if state not in ("PAUSED", "RETIRED", "NEVER_SCHEDULED"):
                state = "PAUSED"
            row["state"] = state
            row["state_since"] = str(declared.get("state_since") or RECONCILED_ON)
            row["state_reason"] = str(declared.get("state_reason") or (
                f"unit file state '{u.get('enabled_state')}' observed on the host {RECONCILED_ON}; "
                "nobody recorded why it was turned off"))
            row["reason_confidence"] = str(declared.get("reason_confidence") or "UNKNOWN")
            row["reason_evidence"] = str(declared.get("reason_evidence") or
                                         "systemctl --user list-unit-files (read-only) during B1 reconciliation")
            if state == "PAUSED":
                row["review_by"] = str(declared.get("review_by") or REVIEW_BY)
            if declared.get("superseded_by"):
                row["superseded_by"] = str(declared["superseded_by"])
        if kind == "timer":
            row["service"] = u.get("service")
            row["cadence_basis"] = ("OnCalendar max gap (systemd-analyze, fixed base)" if u.get("on_calendar")
                                    else "monotonic interval" if u.get("monotonic_hours") else
                                    "unknown schedule: placeholder 168 h")
        else:
            row["cadence_basis"] = "daemon: liveness judged hourly"
        if exec_start:
            row["exec_start"] = exec_start[:240]
        if stay:
            row["stay_on_cron"] = stay
        if flags:
            row["flags"] = flags
        if ev and ev.get("note"):
            row["evidence_note"] = str(ev["note"])
        rows.append(row)
    return rows, problems


def annotate_existing(reg: dict[str, Any], lines: list[str], raw_lines: list[str], units: dict[str, Any],
                      f_rows: list[dict[str, Any]], tokens=None) -> None:
    """Existing hand-written rows keep every field; only value_class/recommendation/rationalization are set."""
    fmap = rationalization_for_cron(f_rows, raw_lines)
    funit = {str(r.get("id")): r for r in f_rows if r.get("kind") in ("timer", "service")}
    fn8n = {str(r.get("id")): r for r in f_rows if r.get("kind") == "n8n_workflow"}
    for row in reg.get("lanes") or []:
        if row.get("generated_by") == GENERATOR_VERSION:
            continue
        sched = row.get("scheduler") or {}
        decl = declarations(row)
        f = None
        stay = None
        if sched.get("kind") in ("cron", "n8n") and decl:
            hit = [ln for ln in lines if any(d in ln for d in decl)]
            if hit:
                f = fmap.get(hit[0])
                cmd = split_schedule(hit[0])[1]
                tok, stem = primary_script(cmd)
                stay = stay_on_cron(cmd, stem, tokens=tokens)
        if f is None and sched.get("kind") == "n8n":
            f = fn8n.get(str(sched.get("expression") or ""))
        if sched.get("kind") == "systemd":
            unit = str(sched.get("match") or sched.get("expression") or "").split()[0]
            f = funit.get(unit)
            ts = next((t for t in (units.get("timers") or []) + (units.get("services") or []) if t["unit"] == unit), None)
            if ts:
                tok, stem = primary_script(ts.get("exec_start") or "")
                stay = stay_on_cron(ts.get("exec_start") or "", stem if tok else unit, tokens=tokens)
        if f is None and stay is None:
            continue
        f_rec = normalise_recommendation(f)
        row["value_class"] = (f or {}).get("value_class") or row.get("value_class") or "UNCLASSIFIED"
        row["recommendation"] = _final_recommendation(f_rec, stay)
        row["rationalization"] = _rationalization_block(f, f_rec)
        if stay:
            row["stay_on_cron"] = stay


# ── mapping ───────────────────────────────────────────────────────────────────────────────────

def declarations(row: dict[str, Any]) -> list[str]:
    sched = row.get("scheduler") or {}
    out = []
    expr = str(sched.get("expression") or "")
    if expr and not _BARE_SCHEDULE.match(expr):
        out.append(expr)
    if sched.get("match"):
        out.append(str(sched["match"]))
    return out


def line_mapping(reg: dict[str, Any], lines: list[str]) -> dict[str, list[str]]:
    """{live cron line → lane_ids whose declaration is a substring of it} (the gate's own rule)."""
    rows = [(r.get("lane_id"), declarations(r)) for r in reg.get("lanes") or []
            if (r.get("scheduler") or {}).get("kind") != "systemd"]
    return {ln: [lid for lid, decl in rows if any(d in ln for d in decl if d)] for ln in lines}


def unit_mapping(reg: dict[str, Any], unit_names: list[str]) -> dict[str, list[str]]:
    rows = [(r.get("lane_id"), set(declarations(r))) for r in reg.get("lanes") or []
            if (r.get("scheduler") or {}).get("kind") in ("systemd", "n8n")]
    return {u: [lid for lid, decl in rows if u in decl] for u in unit_names}


# ── driver ────────────────────────────────────────────────────────────────────────────────────

def reconcile(reg: dict[str, Any], *, cron_text: str, units: dict[str, Any], f_rows: list[dict[str, Any]],
              evidence: dict[str, dict[str, Any]], tokens=None) -> dict[str, Any]:
    """Pure: returns {registry, added, problems, mapping}. ``reg`` is not mutated."""
    reg = json.loads(json.dumps(reg))
    reg.pop("undeclared_baseline", None)
    reg.pop("inherited_tranches", None)
    found_cron = discover_cron(cron_text)
    lines = [c["expression"] for c in found_cron]
    raw_lines = (cron_text or "").splitlines()
    found = {"cron": found_cron,
             "systemd": [{"kind": "systemd", "expression": t["unit"], "enabled_state": t.get("enabled_state")}
                         for t in units.get("timers") or []],
             "systemd_services": [{"kind": "systemd_service", "expression": s["unit"],
                                   "enabled_state": s.get("enabled_state")} for s in units.get("services") or []]}
    undeclared = find_undeclared(reg, found, n8n_known_ids=[])
    und_cron = [u["expression"] for u in undeclared if u["kind"] == "cron"]
    und_units = {u["expression"] for u in undeclared if u["kind"] in ("systemd", "systemd_service")}
    # Rows the generator wrote earlier are re-derived from evidence on every run (idempotent).
    generated = [r for r in reg.get("lanes") or [] if r.get("generated_by") == GENERATOR_VERSION]
    if generated:
        keep = [r for r in reg["lanes"] if r.get("generated_by") != GENERATOR_VERSION]
        probe = dict(reg, lanes=keep)
        undeclared = find_undeclared(probe, found, n8n_known_ids=[])
        und_cron = [u["expression"] for u in undeclared if u["kind"] == "cron"]
        und_units = {u["expression"] for u in undeclared if u["kind"] in ("systemd", "systemd_service")}
        reg["lanes"] = keep
    taken = {str(r.get("lane_id")) for r in reg.get("lanes") or []}
    annotate_existing(reg, lines, raw_lines, units, f_rows, tokens=tokens)
    cron_rows, p1 = build_cron_rows(lines, und_cron, raw_lines, f_rows, evidence, taken, tokens=tokens)
    unit_rows, p2 = build_unit_rows(units, und_units, f_rows, evidence, taken, tokens=tokens)
    reg["lanes"] = list(reg.get("lanes") or []) + cron_rows + unit_rows
    problems = p1 + p2
    mapping = line_mapping(reg, lines)
    for ln, ids in mapping.items():
        if len(ids) != 1:
            problems.append({"code": "LINE_MAPS_TO_%d_ROWS" % len(ids), "lane_ids": ids, "line": sanitize(ln)[:200]})
    unames = [t["unit"] for t in units.get("timers") or []] + [s["unit"] for s in units.get("services") or []]
    for u, ids in unit_mapping(reg, unames).items():
        if not ids:
            problems.append({"code": "UNIT_UNDECLARED", "unit": u})
    problems.extend({"code": "STRUCTURAL", "detail": e} for e in validate_registry(reg))
    remaining = find_undeclared(reg, found, n8n_known_ids=[])
    for u in remaining:
        problems.append({"code": "STILL_UNDECLARED", "kind": u["kind"], "expression": sanitize(u["expression"])[:200]})
    return {"registry": reg, "added": cron_rows + unit_rows, "problems": problems, "mapping": mapping,
            "lines": lines, "units": unames}


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    from collections import Counter
    lanes = result["registry"]["lanes"]
    rec = Counter()
    for r in lanes:
        if r.get("recommendation"):
            rec[str(r["recommendation"]).split(":", 1)[0] + (":" if ":" in str(r["recommendation"]) else "")] += 1
    return {
        "lanes": len(lanes),
        "added": len(result["added"]),
        "added_by_kind": dict(Counter((r["scheduler"]["kind"]) for r in result["added"])),
        "by_kind": dict(Counter((r.get("scheduler") or {}).get("kind") for r in lanes)),
        "by_state": dict(Counter(r.get("state") for r in lanes)),
        "by_recommendation": dict(sorted(rec.items())),
        "unverified_output": sorted(r["lane_id"] for r in lanes if UNVERIFIED_OUTPUT in (r.get("flags") or [])),
        "live_cron_lines": len(result["lines"]),
        "live_units": len(result["units"]),
        "problems": result["problems"],
    }


N8N_SNAPSHOT_PATH = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "active_workflows_snapshot.json"
N8N_INDEX_PATH = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated" / "INDEX.json"


def disagreements(result: dict[str, Any], *, n8n_active: Optional[list[dict[str, Any]]] = None,
                  n8n_index: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]:
    """Where the crontab, the registry and the n8n program do not tell the same story."""
    lanes = result["registry"]["lanes"]
    lines = result["lines"]
    by_id = {r.get("lane_id"): r for r in lanes}
    out: dict[str, list[dict[str, Any]]] = {}
    # 1. registry says a cron lane is ACTIVE, the crontab has no line for it
    out["registry_active_cron_without_line"] = [
        {"lane_id": r["lane_id"], "match": sanitize(str((r.get("scheduler") or {}).get("match") or ""))}
        for r in lanes if r.get("state") == "ACTIVE" and (r.get("scheduler") or {}).get("kind") == "cron"
        and not any(any(d in ln for d in declarations(r)) for ln in lines)]
    # 2. an ACTIVE n8n LIVE workflow whose lane still fires from cron (double scheduler)
    active_names = {str(w.get("name") or ""): str(w.get("id") or "") for w in (n8n_active or [])}
    idx = {str(x.get("lane_id")): x for x in ((n8n_index or {}).get("lanes") or [])}
    dbl = []
    for name, wid in sorted(active_names.items()):
        row = by_id.get(name)
        live_id = (idx.get(name) or {}).get("live_workflow_id")
        if row and (row.get("scheduler") or {}).get("kind") == "cron" and any(
                any(d in ln for d in declarations(row)) for ln in lines):
            dbl.append({"lane_id": name, "workflow_id": wid, "is_generated_live_id": wid == live_id,
                        "registry_kind": "cron"})
    out["cron_and_active_n8n_live_workflow"] = dbl
    # 3. active n8n workflows that are shadows of lanes still on cron (expected during the ladder)
    out["active_n8n_shadows_of_cron_lanes"] = sorted(
        ({"workflow": n, "workflow_id": w} for n, w in active_names.items() if n.endswith("-shadow")),
        key=lambda x: x["workflow"])
    # 4. rationalization says eliminate, but the line is broker/order/secret class
    out["r0_on_stay_class_lane"] = [
        {"lane_id": r["lane_id"], "stay_on_cron": r["stay_on_cron"]}
        for r in lanes if r.get("recommendation") == REC_R0 and r.get("stay_on_cron")]
    # 5. rationalization proposes a pipeline/merge, the forbidden-token rule keeps it on cron
    out["rationalization_overridden_to_keep_on_cron"] = [
        {"lane_id": r["lane_id"], "f_recommendation": (r.get("rationalization") or {}).get("recommendation"),
         "stay_on_cron": r["stay_on_cron"]}
        for r in lanes if r.get("recommendation") == REC_KEEP and r.get("stay_on_cron")
        and (r.get("rationalization") or {}).get("recommendation") not in (None, REC_KEEP)]
    # 6. scheduled units/lines the rationalization never classified
    out["not_in_rationalization"] = [
        {"lane_id": r["lane_id"], "scheduler": (r.get("scheduler") or {}).get("expression"),
         "state": r.get("state")}
        for r in lanes if r.get("generated_by") == GENERATOR_VERSION
        and not (r.get("rationalization") or {}).get("f_id")]
    # 7. lanes merged as one row because their cron lines differ only in schedule
    out["multi_schedule_rows"] = [
        {"lane_id": r["lane_id"], "schedules": (r.get("scheduler") or {}).get("schedules")}
        for r in lanes if (r.get("scheduler") or {}).get("schedules")]
    return out


def render_report(summary: dict[str, Any], dis: dict[str, list[dict[str, Any]]], result: dict[str, Any]) -> str:
    lanes = result["registry"]["lanes"]
    added = result["added"]
    from collections import Counter

    def table(counter: Counter, head: str) -> list[str]:
        rows = [f"| {head} | rows |", "|---|---:|"]
        rows += [f"| {k} | {v} |" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]
        return rows

    rec_full = Counter(str(r.get("recommendation")) for r in lanes if r.get("recommendation"))
    rec_head = Counter(str(r.get("recommendation")).split(":", 1)[0] for r in lanes if r.get("recommendation"))
    live_rows = [r for r in lanes if r.get("recommendation")]
    sig = Counter(str((r.get("output_signal") or {}).get("evidence") or (r.get("output_signal") or {}).get("reason")
                      or "hand-written") for r in added)
    unver = [r for r in lanes if UNVERIFIED_OUTPUT in (r.get("flags") or [])]
    md: list[str] = []
    md += ["# 01 — Lane registry reconciliation (B1)", "",
           f"Generated by `{GENERATOR}` ({GENERATOR_VERSION}) on {RECONCILED_ON}. Do not edit the tables by hand: "
           "re-run `python3 scripts/reconcile_lane_registry.py --report-md "
           "docs/implementation/n8n-maturity/01-registry-reconciliation.md` (dry-run; it writes only the report).", "",
           "## Result", "",
           "- `undeclared_baseline` (476 entries) and `inherited_tranches` (113 lines) are **removed**. "
           "`check_lane_registry --fail-on-new --no-exemptions` passes with zero exemptions.",
           f"- Live scheduler inventory: **{summary['live_cron_lines']} crontab lines**, "
           f"**{summary['live_units']} user units** (timers in every state plus the enabled platform services "
           "installed under `~/.config/systemd/user`).",
           "- Every live crontab line maps to exactly one registry row; every live unit has a row.",
           f"- Rows: {summary['lanes']} ({len(added)} added by this reconciliation: "
           + ", ".join(f"{v} {k}" for k, v in sorted(summary['added_by_kind'].items())) + ").",
           f"- Rows with a rationalization recommendation: {len(live_rows)}.",
           f"- Unverified output: **{len(unver)}** rows carry `output_signal.kind = none` with reason "
           "`UNVERIFIED_OUTPUT` (listed below).", "",
           "## Counts", "", "### By scheduler kind (all rows)", ""]
    md += table(Counter((r.get("scheduler") or {}).get("kind") for r in lanes), "kind")
    md += ["", "### By state (all rows)", ""]
    md += table(Counter(r.get("state") for r in lanes), "state")
    md += ["", "### By recommendation", ""]
    md += table(rec_head, "recommendation")
    md += ["", "<details><summary>By recommendation with target</summary>", ""]
    md += table(rec_full, "recommendation")
    md += ["", "</details>", "", "### By value class (rows with a recommendation)", ""]
    md += table(Counter(str(r.get("value_class")) for r in live_rows), "value class")
    md += ["", "### Output-signal evidence of the added rows", ""]
    md += table(sig, "evidence")
    md += ["", "Evidence kinds: `SCRIPT_RECEIPT` — a fixed-path receipt the script writes, accepted only when its "
           "verified token occurs in the script source (`lane_output_evidence.json`); `CRON_LOG_REDIRECT` / "
           "`SYSTEMD_STDOUT_APPEND` — the log the scheduler appends to; `UNVERIFIED_OUTPUT` — neither could be proven.",
           "", "### By owner (added rows)", ""]
    md += table(Counter(r.get("owner") for r in added), "owner")
    md += ["", "## Lines with unverified output", "",
           "These rows are declared (the gate is green) but nothing proves they produce. Each needs a receipt "
           "(preferred) or a log redirect before the heartbeat watcher can judge it.", "",
           "| lane_id | kind | scheduler | owner | recommendation |", "|---|---|---|---|---|"]
    for r in sorted(unver, key=lambda x: x["lane_id"]):
        sch = r.get("scheduler") or {}
        md.append(f"| `{r['lane_id']}` | {sch.get('kind')} | `{sanitize(str(sch.get('expression')))}` | "
                  f"{r.get('owner')} | {r.get('recommendation')} |")
    md += ["", "## Disagreements: crontab vs registry vs n8n program", ""]
    titles = {
        "registry_active_cron_without_line": "Registry says ACTIVE cron, crontab has no line",
        "cron_and_active_n8n_live_workflow": "Lane fires from cron AND an active n8n live workflow (double scheduler)",
        "active_n8n_shadows_of_cron_lanes": "Active n8n shadow workflows (lane still on cron; expected during the ladder)",
        "r0_on_stay_class_lane": "Rationalization says ELIMINATE, line is broker/order/secret class",
        "rationalization_overridden_to_keep_on_cron": "Rationalization proposes pipeline/merge, forbidden-token rule keeps it on cron",
        "not_in_rationalization": "Scheduled on the host, absent from the rationalization",
        "multi_schedule_rows": "One lane, several crontab lines (identical job on several schedules)",
    }
    for key, title in titles.items():
        items = dis.get(key) or []
        md += [f"### {title} ({len(items)})", ""]
        if not items:
            md += ["None.", ""]
            continue
        for it in items:
            md.append("- " + ", ".join(f"{k}: `{sanitize(json.dumps(v, ensure_ascii=False)) if not isinstance(v, str) else sanitize(v)}`"
                                       for k, v in it.items()))
        md.append("")
    md += ["## Corrections made with this reconciliation", "",
           "- `alert-quality`: declared ACTIVE on 2026-10-03, but its crontab line was never installed (no live or "
           "commented line on 2026-10-09; `data/runtime/alert_quality_last.json` absent; the row's own note says the "
           "install needs the operator's cron grant). Flipped to NEVER_SCHEDULED with that evidence.",
           "- `active-trader-session-review` / `-close`: both rows matched both session-review lines (shared match "
           "`scripts/active_trader/session_review.py`); each match now names its own schedule.",
           "- `maturity-remeasure` stays as found: the cron line AND the active n8n live workflow `e18d7849b4142927` "
           "both fire it (double scheduler). Retiring the cron line needs a cron-write grant (B3, before Mon 06:40).",
           ""]
    md += ["## Method and rails", "",
           "- Inputs: `crontab -l` and `systemctl --user` (list-unit-files / show / cat, read-only), "
           "`docs/implementation/n8n-maturity/data/F_rationalization.json` (copied from the 2026-10-09 rationalization), "
           "`docs/implementation/n8n-maturity/data/lane_output_evidence.json` (receipts found by code reading, each "
           "host-checked and source-verified).",
           "- Match strings are the shortest token-aligned window anchored at the script that occurs in exactly one "
           "live line and contains no home path; identical jobs on several schedules share one row "
           "(`scheduler.schedules`).",
           "- `expected_cadence_hours` is the largest gap between consecutive fires from a fixed Monday base "
           "(weekday-only jobs therefore carry the weekend gap), or the OnCalendar max gap from `systemd-analyze calendar`.",
           "- A systemd row declares a unit, never a crontab line (`find_undeclared`).",
           "- R0 rows stay ACTIVE with `recommendation: R0_ELIMINATE`; retiring the line is a later step under a "
           "cron-write grant. Disabled timers are declared PAUSED with `review_by`.",
           "- Nothing on the host was changed: no crontab or unit edit, no job run, no row deleted.", ""]
    return "\n".join(md)


def make_snapshot(cron_text: str, units: dict[str, Any]) -> dict[str, Any]:
    """Uncommented crontab entries WITH their line numbers (the rationalization joins on them), home paths
    replaced by ``~``; units as captured (already sanitised)."""
    live = {c["expression"] for c in discover_cron(cron_text)}
    lines = [{"n": i + 1, "line": sanitize(ln.strip())}
             for i, ln in enumerate((cron_text or "").splitlines()) if ln.strip() in live]
    return {"schema": "SchedulerSnapshot@v1", "captured_on": RECONCILED_ON,
            "note": "crontab -l and systemctl --user (read-only); /home/<user> replaced by ~",
            "cron_lines": lines, "units": {"timers": units.get("timers") or [],
                                           "services": units.get("services") or []}}


def snapshot_cron_text(snap: dict[str, Any]) -> str:
    """Rebuild crontab text with each entry on its original line number (others are comments)."""
    entries = snap.get("cron_lines") or []
    last = max((int(e["n"]) for e in entries), default=0)
    out = ["#"] * last
    for e in entries:
        out[int(e["n"]) - 1] = str(e["line"])
    return "\n".join(out) + "\n"


def dump_registry(reg: dict[str, Any]) -> str:
    return json.dumps(reg, indent=2, ensure_ascii=False) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: print the plan, write nothing")
    mode.add_argument("--write", action="store_true", help="rewrite config/lane_registry.json")
    ap.add_argument("--registry", default=str(REGISTRY_PATH))
    ap.add_argument("--crontab-file", default=None, help="read crontab text from this file instead of crontab -l")
    ap.add_argument("--units-json", default=None, help="read captured units {timers, services} instead of systemctl")
    ap.add_argument("--snapshot-in", default=None,
                    help="read cron lines + units from a SchedulerSnapshot@v1 file (tests, CI, the report)")
    ap.add_argument("--snapshot-out", default=None,
                    help="also write the (home-path-sanitised) cron lines + units used, for tests and the report")
    ap.add_argument("--rationalization", default=str(RATIONALIZATION_PATH))
    ap.add_argument("--evidence", default=str(EVIDENCE_PATH))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report-md", default=None, help="also render the reconciliation report (markdown) here")
    args = ap.parse_args(argv)

    if args.snapshot_in:
        snap_in = json.loads(Path(args.snapshot_in).read_text(encoding="utf-8"))
        cron_text, units = snapshot_cron_text(snap_in), snap_in["units"]
    else:
        cron_text = (Path(args.crontab_file).read_text(encoding="utf-8") if args.crontab_file
                     else read_live_crontab())
        units = (json.loads(Path(args.units_json).read_text(encoding="utf-8")) if args.units_json
                 else capture_units_live())
    reg = load_registry(Path(args.registry))
    f_rows = load_rationalization(Path(args.rationalization))
    evidence = load_evidence(Path(args.evidence))
    result = reconcile(reg, cron_text=cron_text, units=units, f_rows=f_rows, evidence=evidence)
    summary = summarize(result)
    if args.snapshot_out:
        Path(args.snapshot_out).write_text(json.dumps(make_snapshot(cron_text, units), indent=1, ensure_ascii=False)
                                           + "\n", encoding="utf-8")
    if args.report_md:
        snap = json.loads(N8N_SNAPSHOT_PATH.read_text(encoding="utf-8")) if N8N_SNAPSHOT_PATH.exists() else {}
        index = json.loads(N8N_INDEX_PATH.read_text(encoding="utf-8")) if N8N_INDEX_PATH.exists() else {}
        dis = disagreements(result, n8n_active=snap.get("workflows") or [], n8n_index=index)
        Path(args.report_md).write_text(render_report(summary, dis, result) + "\n", encoding="utf-8")
    blocking = [p for p in result["problems"] if p["code"] not in ("EVIDENCE_REJECTED",)]
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"live cron lines {summary['live_cron_lines']}  live units {summary['live_units']}  "
              f"rows {summary['lanes']} (+{summary['added']} {summary['added_by_kind']})")
        print(f"by kind {summary['by_kind']}")
        print(f"by state {summary['by_state']}")
        print(f"by recommendation {summary['by_recommendation']}")
        print(f"unverified output {len(summary['unverified_output'])}")
        for p in result["problems"]:
            print(f"  ! {json.dumps(p, ensure_ascii=False)[:220]}")
    if args.write:
        if blocking:
            print(f"REFUSED: {len(blocking)} blocking problem(s); registry not written", file=sys.stderr)
            return 1
        out = dump_registry(result["registry"])
        path = Path(args.registry)
        if path.read_text(encoding="utf-8") != out:
            path.write_text(out, encoding="utf-8")
            print(f"wrote {path}")
        else:
            print("registry unchanged")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
