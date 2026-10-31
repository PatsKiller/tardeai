"""Self-heal train intake: turn release-train / CI / tester / sweep failures into deduped fix decisions. Pure.

Operator 2026-10-25 (verbatim, voice-typed): "Arm the fixer and also a logger that tracks what was fixed, but this
train should be no different than submitting in [to GitHub]. Somebody needs to monitor it, if there's little errors
they need to correct it as long as they're adhering to our agents.md."

Inputs are documents the release machinery already writes (read here, never written):

  ci       the push/main workflow runs of main HEAD (``gh run list`` rows + failed-job names + ``--log-failed`` tail,
           gathered by scripts/self_heal_train_monitor.py, GET only)
  train    ``<release state>/trains/<train_id>/outcome.json`` (TrainOutcome@v1), non-terminal ``state.json`` without
           an outcome (stale train), and ``train_requests/receipts/*.json`` (TrainWindowReceipt@v1: FAILED state,
           ``needs_action`` TRAIN_STALLED, NOT_RIDING reasons of fix PRs)
  tester   ``<state>/data/runtime/post_release_tester/last_{api,light}.json`` (PostReleaseTest@v1, PR #2106) FAILED
  sweep    ``last_nightly.json`` of the same tester: the nightly full sweep's "broken" findings

Each failure becomes a ``Finding`` with a stable ``signature`` (head SHA and timestamps are NOT part of it, so the
same defect on the next merge dedupes). ``decide`` maps a finding to exactly one remediation:

  deterministic:<rule id>   a known small error with a fixed, model-free remediation (config deterministic[])
  claude_code               hand-off to the existing self-heal fixer (scripts/self_heal_fixer.py) as one
                            N8nCodeDefect@v1-shaped record in data/self_heal/fixer_defects.jsonl
  refused:<scope>           broker / Active Trader / MBI, guard/policy, train-self, self-heal-self, credentials:
                            P1 alert + coordinator task, never a fix
  coordinator               not a code defect of main (a member PR ejected, a train outcome caused by release
                            machinery): P1 alert + coordinator task

MBI_BEHAVIOR = 0. No I/O except the read helpers that take explicit paths. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

CONFIG_SCHEMA = "SelfHealTrainMonitorConfig@v1"
FIX_LOG_SCHEMA = "SelfHealFixLog@v1"
STATE_SCHEMA = "SelfHealTrainMonitorState@v1"
DEFECT_SCHEMA = "N8nCodeDefect@v1"
DEFECT_CONSUMER = "claude_code_iterative_fix"
LANE_PREFIX = "train-monitor-"
ET = ZoneInfo("America/New_York")

SOURCES = ("ci", "train", "tester", "sweep", "lane")
#: Fix-log outcomes. The operator's four (fixed-released, fix-PR-open, escalated, gave-up) plus the states a fix
#: passes through or ends in without a release (documented in docs/ops/SELF_HEAL_TRAIN_FIXER.md section 5).
OUTCOMES = (
    "detected",
    "shadow-proposed",
    "remediating",
    "fix-PR-open",
    "fix-ready-local",
    "fixer-queued",
    "fixed-released-pending",
    "fixed-released",
    "fixed-no-release",
    "escalated",
    "gave-up",
    "cleared",
)
OPEN_OUTCOMES = frozenset(
    {"remediating", "fix-PR-open", "fix-ready-local", "fixer-queued", "fixed-released-pending"}
)  # fix-ready-local: a local branch awaiting a person's push (AGENTS.md §24.5)
TERMINAL_OUTCOMES = frozenset({"fixed-released", "fixed-no-release", "gave-up", "cleared"})

_PATH_RE = re.compile(
    r"(?<![\w./-])((?:scripts|tests|config|apps|docs|bin|migrations|sql|\.github|\.githooks)/"
    r"[\w./@+-]+|AGENTS\.md|AI_WORK_POLICY\.md|CLAUDE\.md|GEMINI\.md)"
)
_FAILED_TEST_RE = re.compile(r"(?:FAILED|ERROR)\s+(tests/[\w./-]+\.py(?:::[\w\[\]./:-]+)?)")
_NOISE = re.compile(r"(0x[0-9a-f]+|\b[0-9a-f]{7,40}\b|\b\d+(?:\.\d+)?s?\b|\d{4}-\d\d-\d\dT[\d:.]+Z?)", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ---------------------------------------------------------------- config + policy gate


def load_config(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"{path}: schema must be {CONFIG_SCHEMA}")
    return doc


def _vtuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


def _control_block(text: str) -> dict[str, str]:
    m = re.search(r"```\n(Policy-Version:.*?)```", text or "", re.DOTALL)
    out: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def policy_gate(agents_text: str, cfg: Mapping[str, Any]) -> dict:
    """LIVE only when AGENTS.md is >= min_policy_version, Status ACTIVE, and carries the 28.14 heading marked
    ACTIVE. Anything else is SHADOW (detect, log, propose; execute nothing). Same parse as
    scripts/check_agents_policy_state.py control_block."""
    a = cfg["arming"]
    cb = _control_block(agents_text)
    version, status = cb.get("Policy-Version"), cb.get("Status")
    base = {"policy_version": version, "policy_status": status, "required": a["min_policy_version"]}
    if not version or not status:
        return {**base, "live": False, "why": "AGENTS.md control block unreadable"}
    if _vtuple(version) < _vtuple(a["min_policy_version"]):
        return {
            **base,
            "live": False,
            "why": f"AGENTS.md {version} < {a['min_policy_version']}: shadow (dry-run phase)",
        }
    if status != a["required_status"]:
        return {**base, "live": False, "why": f"AGENTS.md {version} is {status}, not {a['required_status']}"}
    heading = next((ln for ln in agents_text.splitlines() if ln.startswith(a["section_heading_marker"])), None)
    if not heading:
        return {**base, "live": False, "why": f"AGENTS.md {version} ACTIVE but has no '{a['section_heading_marker']}'"}
    if a["required_status"] not in heading:
        return {**base, "live": False, "why": "section 28.14 present but its heading is not ACTIVE", "heading": heading}
    return {**base, "live": True, "why": f"AGENTS.md {version} ACTIVE with section 28.14", "heading": heading[:200]}


# ---------------------------------------------------------------- findings


@dataclass
class Finding:
    source: str  # ci | train | tester | sweep | lane
    kind: str  # e.g. ci_red, train_outcome, train_stale, train_stalled, train_receipt_failed, tester_failed
    key: str  # stable identity inside the source (workflow/job, outcome+reason, mode+route)
    title: str
    detail: str = ""
    evidence_refs: list = field(default_factory=list)
    evidence_text: str = ""
    paths: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    seen_at: Optional[str] = None

    @property
    def signature(self) -> str:
        return signature(self.source, self.kind, self.key)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signature"] = self.signature
        return d


def signature(source: str, kind: str, key: str) -> str:
    norm = _NOISE.sub("<n>", str(key).lower()).strip()
    return f"{source}-" + hashlib.sha256(f"{source}|{kind}|{norm}".encode()).hexdigest()[:12]


def strip_ansi(text: Any) -> str:
    return _ANSI.sub("", str(text or ""))


def paths_in(text: Any) -> list[str]:
    seen: dict[str, None] = {}
    for m in _PATH_RE.finditer(strip_ansi(text)):
        p = m.group(1).rstrip(".,:;)'\"")
        seen.setdefault(p.split("::", 1)[0], None)
    return list(seen)[:40]


def failed_tests(text: Any) -> list[str]:
    seen: dict[str, None] = {}
    for m in _FAILED_TEST_RE.finditer(strip_ansi(text)):
        seen.setdefault(m.group(1), None)
    return list(seen)[:20]


_BAD_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure", "action_required"})


def head_runs(runs: Iterable[Mapping[str, Any]]) -> tuple[Optional[str], list[dict]]:
    """``gh run list`` rows (newest first) -> (main HEAD sha, latest run per workflow for that sha)."""
    rows = [dict(r) for r in runs or [] if isinstance(r, Mapping)]
    if not rows:
        return None, []
    rows.sort(key=lambda r: str(r.get("createdAt") or ""), reverse=True)
    head = rows[0].get("headSha")
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("headSha") != head:
            continue
        latest.setdefault(str(r.get("workflowName") or r.get("name") or "?"), r)
    return head, list(latest.values())


def red_runs(runs: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [dict(r) for r in runs if r.get("status") == "completed" and r.get("conclusion") in _BAD_CONCLUSIONS]


def detect_ci(
    head: Optional[str],
    red: Iterable[Mapping[str, Any]],
    details: Mapping[Any, Mapping[str, Any]],
    *,
    tail_chars: int = 6000,
) -> list[Finding]:
    """One finding per red workflow run of main HEAD. ``details[run_id]`` = {"failed_jobs": [...], "log_tail": str,
    "attempt": int}. Signature = workflow + failed job names + the first failing tests (never the SHA)."""
    out: list[Finding] = []
    for r in red:
        rid = r.get("databaseId")
        d = details.get(rid) or details.get(str(rid)) or {}
        jobs = sorted(str(j) for j in d.get("failed_jobs") or [])
        log = strip_ansi(d.get("log_tail") or "")[-tail_chars:]
        tests = failed_tests(log)
        wf = str(r.get("workflowName") or r.get("name") or "?")
        key = f"{wf}|{','.join(jobs)}|{','.join(tests[:3])}"
        out.append(
            Finding(
                source="ci",
                kind="ci_red",
                key=key,
                title=f"main CI red: {wf}" + (f" ({', '.join(jobs[:3])})" if jobs else ""),
                detail=f"{r.get('conclusion')} on main {str(head or '')[:12]}; failing tests: "
                + (", ".join(tests[:5]) or "none parsed"),
                evidence_refs=[str(r.get("url") or f"gh-run:{rid}")],
                evidence_text=log,
                paths=paths_in(log) + [t.split("::", 1)[0] for t in tests],
                meta={
                    "run_id": rid,
                    "workflow": wf,
                    "failed_jobs": jobs,
                    "failed_tests": tests,
                    "head_sha": head,
                    "attempt": int(d.get("attempt") or r.get("attempt") or 1),
                },
            )
        )
    return out


def _read_json(p: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _reason_code(text: Any) -> str:
    m = re.match(r"\s*(?:\[[^\]]*\]\s*)?([A-Z][A-Z0-9_]{3,})", str(text or ""))
    return m.group(1) if m else "UNSPECIFIED"


def detect_train(release_state_dir: Path, *, now: datetime, cfg: Mapping[str, Any]) -> list[Finding]:
    """Live train outcomes, stale non-terminal trains and FAILED / TRAIN_STALLED receipts within lookback."""
    src = cfg["sources"]
    since = now - timedelta(hours=float(src.get("lookback_hours", 36)))
    want = set(src.get("train_outcomes") or [])
    out: list[Finding] = []
    trains = Path(release_state_dir) / "trains"
    try:
        tdirs = sorted(p for p in trains.iterdir() if p.is_dir())
    except OSError:
        tdirs = []
    for td in tdirs:
        oc = _read_json(td / "outcome.json")
        if oc:
            at = _parse_ts(oc.get("finished_at"))
            if oc.get("outcome") in want and (at is None or at >= since):
                code = _reason_code(oc.get("notes"))
                attribution = oc.get("failure_attribution")
                out.append(
                    Finding(
                        source="train",
                        kind="train_outcome",
                        key=f"{oc.get('outcome')}|{code}",
                        title=f"train {td.name} ended {oc.get('outcome')} ({code})",
                        detail=str(oc.get("notes") or "")[:400],
                        evidence_refs=[f"release_state:trains/{td.name}/outcome.json"],
                        evidence_text=json.dumps(oc, sort_keys=True)[:4000],
                        paths=paths_in(oc.get("notes")),
                        meta={
                            "train_id": td.name,
                            "outcome": oc.get("outcome"),
                            "reason": code,
                            "members": oc.get("members") or [],
                            "main_sha": oc.get("main_sha"),
                            "failure_attribution": attribution,
                            "finished_at": oc.get("finished_at"),
                        },
                        seen_at=oc.get("finished_at"),
                    )
                )
            continue
        st_path = td / "state.json"
        try:
            age_min = (now.timestamp() - st_path.stat().st_mtime) / 60.0
        except OSError:
            continue
        if age_min >= float(src.get("stale_train_after_minutes", 240)):
            st = _read_json(st_path) or {}
            out.append(
                Finding(
                    source="train",
                    kind="train_stale",
                    key=f"stale|{td.name}",
                    title=f"train {td.name} non-terminal for {int(age_min)} min",
                    detail=f"phase {st.get('phase') or st.get('state') or '?'}; no outcome.json",
                    evidence_refs=[f"release_state:trains/{td.name}/state.json"],
                    evidence_text=json.dumps(st, sort_keys=True, default=str)[:3000],
                    meta={"train_id": td.name, "age_min": round(age_min, 1)},
                )
            )
    rdir = Path(release_state_dir) / "train_requests" / "receipts"
    try:
        receipts = sorted(rdir.glob("*.json"))
    except OSError:
        receipts = []
    states = set(src.get("train_receipt_states") or [])
    stall = set(src.get("stall_codes") or [])
    for rp in receipts:
        rc = _read_json(rp)
        if not rc or rc.get("shadow") or rc.get("mode") == "simulate":
            continue  # a shadow / simulated window is a rehearsal, not a failure of the live train
        at = _parse_ts(rc.get("finished_at") or rc.get("acknowledged_at"))
        if at is not None and at < since:
            continue
        if rc.get("state") in states:
            ref = rc.get("refusal") or {}
            out.append(
                Finding(
                    source="train",
                    kind="train_receipt_failed",
                    key=f"receipt|{ref.get('code') or 'UNSPECIFIED'}",
                    title=f"train window {rc.get('window_slot')} {rc.get('state')}: {ref.get('code')}",
                    detail=str(ref.get("detail") or "")[:300],
                    evidence_refs=[f"release_state:train_requests/receipts/{rp.name}"],
                    evidence_text=json.dumps(rc, sort_keys=True)[:3000],
                    meta={"request_id": rc.get("request_id"), "code": ref.get("code")},
                    seen_at=rc.get("finished_at"),
                )
            )
        for n in rc.get("needs_action") or []:
            if n.get("code") in stall:
                code = _reason_code(n.get("text"))
                out.append(
                    Finding(
                        source="train",
                        kind="train_stalled",
                        key=f"stalled|{code}",
                        title=f"train stalled: {code}",
                        detail=str(n.get("text") or "")[:300],
                        evidence_refs=[f"release_state:train_requests/receipts/{rp.name}"],
                        evidence_text=str(n.get("text") or ""),
                        paths=paths_in(n.get("text")),
                        meta={"request_id": rc.get("request_id"), "reason": code},
                        seen_at=rc.get("finished_at"),
                    )
                )
    return _dedupe(out)


def not_riding(release_state_dir: Path) -> dict[int, str]:
    """PR number -> the newest NOT_RIDING reason across window receipts (shadow included: the selection is the
    same). Used to hand non-eligible fix PRs to the coordinator queue."""
    rdir = Path(release_state_dir) / "train_requests" / "receipts"
    rows: list[tuple[str, dict]] = []
    try:
        for rp in rdir.glob("*.json"):
            rc = _read_json(rp)
            if rc:
                rows.append((str(rc.get("finished_at") or rc.get("acknowledged_at") or ""), rc))
    except OSError:
        return {}
    out: dict[int, str] = {}
    for _, rc in sorted(rows, key=lambda x: x[0]):
        for n in rc.get("needs_action") or []:
            if n.get("code") == "NOT_RIDING" and n.get("pr") is not None:
                try:
                    out[int(n["pr"])] = str(n.get("text") or "")
                except (TypeError, ValueError):
                    continue
    return out


def detect_tester(tester_dir: Path, *, now: datetime, cfg: Mapping[str, Any]) -> list[Finding]:
    """PostReleaseTest@v1 FAILED receipts. api/light -> source tester; nightly -> source sweep. One finding per
    (mode, kind, route) so each broken page is its own deduped defect."""
    src = cfg["sources"]
    since = now - timedelta(hours=float(src.get("lookback_hours", 36)))
    out: list[Finding] = []
    for mode in src.get("tester_modes") or []:
        p = Path(tester_dir) / f"last_{mode}.json"
        rc = _read_json(p)
        if not rc or rc.get("status") != "FAILED":
            continue
        at = _parse_ts(rc.get("finished_at"))
        if at is not None and at < since:
            continue
        source = "sweep" if mode == "nightly" else "tester"
        ref = f"state:{p.name}"
        broken = [b for b in rc.get("broken") or [] if isinstance(b, Mapping)]
        checks = [c for c in rc.get("checks") or [] if isinstance(c, Mapping) and not c.get("ok", True)]
        if broken:
            for b in broken[:20]:
                key = f"{mode}|{b.get('kind')}|{b.get('route')}"
                out.append(
                    Finding(
                        source=source,
                        kind="tester_broken",
                        key=key,
                        title=f"{mode} sweep broken: {b.get('kind')} on {b.get('route')}",
                        detail=str(b.get("detail") or "")[:300],
                        evidence_refs=[ref] + ([str(rc["summary_path"])] if rc.get("summary_path") else []),
                        evidence_text=json.dumps(b, sort_keys=True, default=str)[:2000],
                        paths=paths_in(b.get("sample")) + paths_in(b.get("detail")),
                        meta={
                            "mode": mode,
                            "route": b.get("route"),
                            "viewport": b.get("viewport"),
                            "release_sha": rc.get("release_sha"),
                        },
                        seen_at=rc.get("finished_at"),
                    )
                )
        else:
            names = ",".join(sorted(str(c.get("name")) for c in checks)) or _reason_code(rc.get("reason"))
            out.append(
                Finding(
                    source=source,
                    kind="tester_failed",
                    key=f"{mode}|{names}",
                    title=f"post-release {mode} check FAILED: {names}",
                    detail=str(rc.get("reason") or "")[:300],
                    evidence_refs=[ref],
                    evidence_text=json.dumps(rc, sort_keys=True, default=str)[:3000],
                    paths=paths_in(rc.get("reason")),
                    meta={"mode": mode, "release_sha": rc.get("release_sha")},
                    seen_at=rc.get("finished_at"),
                )
            )
    return _dedupe(out)


def _dedupe(found: list[Finding]) -> list[Finding]:
    seen: dict[str, Finding] = {}
    for f in found:
        seen.setdefault(f.signature, f)
    return list(seen.values())


# ---------------------------------------------------------------- decisions


def _match(path: str, patterns: Iterable[str]) -> Optional[str]:
    p = str(path)
    base = p.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatchcase(p, pat) or fnmatch.fnmatchcase(base, pat):
            return pat
    return None


def refused_scope(f: Finding, cfg: Mapping[str, Any]) -> Optional[str]:
    """``<scope>:<path>`` when any path in the evidence falls in a refused scope (broker/AT/MBI, guard/policy,
    train-self, self-heal-self, credentials), else None."""
    scopes = {k: v for k, v in (cfg.get("refused_scopes") or {}).items() if not k.startswith("_")}
    for path in f.paths:
        for scope, pats in scopes.items():
            if _match(path, pats):
                return f"{scope}:{path}"
    return None


def _log_hit(text: str, patterns: Iterable[str]) -> Optional[str]:
    low = text.lower()
    return next((p for p in patterns if p.lower() in low), None)


def match_deterministic(f: Finding, cfg: Mapping[str, Any]) -> Optional[dict]:
    """The first deterministic rule that applies, or None. A CI rerun applies only to a first attempt."""
    for rule in cfg.get("deterministic") or []:
        if rule.get("source") != f.source:
            continue
        kind = rule.get("kind")
        if kind == "rerun_failed_jobs_once":
            if int(f.meta.get("attempt") or 1) > 1:
                continue
            jobs = f.meta.get("failed_jobs") or []
            if not jobs or not all(_match(j, rule.get("job_name_patterns") or []) for j in jobs):
                continue
            if _log_hit(f.evidence_text, rule.get("log_patterns") or []):
                return rule
        elif kind == "regenerate_pr":
            if _log_hit(f.evidence_text, rule.get("log_patterns") or []):
                return rule
        elif kind == "train_reconcile":
            if f.kind == "train_stale":
                return rule
    return None


def decide(f: Finding, cfg: Mapping[str, Any]) -> dict:
    """One remediation for a finding: deterministic first (no model), then refusal, then the fixer."""
    rule = match_deterministic(f, cfg)
    if rule:
        return {"remediation": f"deterministic:{rule['id']}", "rule": rule["id"]}
    scope = refused_scope(f, cfg)
    if scope:
        return {"remediation": "refused", "scope": scope, "priority": "P1"}
    if f.source == "train":
        # Train outcomes are produced by release machinery (train-self) or by a member PR; the fixer never edits
        # either. A member PR ejected pre-merge belongs to its author; everything else is the coordinator's.
        if f.kind == "train_outcome" and f.meta.get("outcome") == "FAILED_PRE_MERGE":
            return {
                "remediation": "coordinator",
                "why": "member PR failed pre-merge; its author fixes it",
                "priority": "P2",
            }
        pri = "P1" if f.meta.get("outcome") in ("ROLLBACK_FAILED", "ROLLED_BACK", "MERGED_NOT_LIVE") else "P2"
        return {"remediation": "coordinator", "why": "release machinery outcome (train-self scope)", "priority": pri}
    return {"remediation": "claude_code"}


# ---------------------------------------------------------------- dedupe, cooldown, attempts (pure on state)


def et_day(now: datetime) -> str:
    return now.astimezone(ET).strftime("%Y-%m-%d")


def new_state() -> dict:
    return {"schema": STATE_SCHEMA, "fixes": {}, "days": {}}


def fix_id(sig: str) -> str:
    return f"fx-{sig}"


def day_count(state: Mapping[str, Any], now: datetime, counter: str) -> int:
    return int(((state.get("days") or {}).get(et_day(now)) or {}).get(counter, 0))


def bump(state: dict, now: datetime, counter: str) -> None:
    d = state.setdefault("days", {}).setdefault(et_day(now), {})
    d[counter] = int(d.get(counter, 0)) + 1
    for old in sorted(state["days"])[:-14]:
        state["days"].pop(old, None)


def gate(state: Mapping[str, Any], f: Finding, *, now: datetime, cfg: Mapping[str, Any]) -> tuple[bool, str]:
    """May this finding start a NEW remediation now? (dedupe on an open fix, cooldown, attempts)."""
    rec = (state.get("fixes") or {}).get(fix_id(f.signature))
    if not rec:
        return True, "new"
    dd = cfg["dedupe"]
    if rec.get("outcome") in OPEN_OUTCOMES:
        return False, f"open:{rec.get('outcome')}"
    if rec.get("outcome") in ("escalated", "gave-up"):
        return False, f"closed:{rec.get('outcome')}"
    if int(rec.get("attempts") or 0) >= int(dd["max_attempts_per_signature"]):
        return False, "attempts_exhausted"
    last = _parse_ts(rec.get("last_action_at"))
    if not rec.get("last_action_at") and not int(rec.get("attempts") or 0):
        return True, "new"
    if str(rec.get("last_remediation") or "").startswith("deterministic:"):
        return True, "after_deterministic"  # a deterministic step that did not fix it hands over at once
    if last and now - last < timedelta(hours=float(dd["cooldown_hours"])):
        return False, "cooldown"
    return True, "retry"


# ---------------------------------------------------------------- fix log rows + fixer hand-off record


def log_row(rec: Mapping[str, Any], *, event: str, now: datetime, mode: str, detail: str = "") -> dict:
    """One append-only SelfHealFixLog@v1 row: the fix's full current projection plus the event that moved it."""
    row = {
        "schema": FIX_LOG_SCHEMA,
        "at": now.astimezone(timezone.utc).isoformat(),
        "event": event,
        "mode": mode,
        "fix_id": rec.get("fix_id"),
        "detected_at": rec.get("detected_at"),
        "source": rec.get("source"),
        "kind": rec.get("kind"),
        "signature": rec.get("signature"),
        "title": rec.get("title"),
        "evidence_refs": list(rec.get("evidence_refs") or [])[:10],
        "remediation_kind": rec.get("remediation_kind"),
        "attempts": int(rec.get("attempts") or 0),
        "model_cost_usd": rec.get("model_cost_usd"),
        "pr_number": rec.get("pr_number"),
        "pr_head": rec.get("pr_head"),
        "outcome": rec.get("outcome"),
        "released_sha": rec.get("released_sha"),
        "verified_at": rec.get("verified_at"),
        "detail": str(detail or rec.get("detail") or "")[:400],
    }
    row["event_id"] = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return row


def fixer_record(f: Finding, *, now: datetime, episode: int) -> dict:
    """The fixer hand-off: an N8nCodeDefect@v1 record (the contract scripts/self_heal_fixer.py already consumes)
    plus a ``receipt`` carrying the failing log tail as the evidence the fixer's prompt quotes."""
    lane = f"{LANE_PREFIX}{f.source}"
    did = f"{lane}|{f.signature}|ep{episode}"
    return {
        "schema": "SelfHealTrainDefect@v1",
        "at": now.astimezone(timezone.utc).isoformat(),
        "fix_id": fix_id(f.signature),
        "code_defect": {
            "schema": DEFECT_SCHEMA,
            "consumer": DEFECT_CONSUMER,
            "kind": "code_defect",
            "defect_id": did,
            "lane": lane,
            "signature": f.signature,
            "episode": episode,
            "failure_class": "code_error",
            "failure_kind": f"{f.source}:{f.kind}",
            "evidence": {
                "incident_key": f"{lane}|{f.signature}",
                "event_type": f.kind,
                "evidence_pack": f.evidence_refs[:5],
            },
        },
        "receipt": {
            "state": "FAILED",
            "reason": f.title[:200],
            "argv": [],
            "stderr_tail": (f"{f.title}\n{f.detail}\n\n" + f.evidence_text)[-6000:],
        },
        "finding": {k: v for k, v in f.to_dict().items() if k != "evidence_text"},
    }


def read_fixer_defects(path: Path, *, tail: int = 2000) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("code_defect"), dict):
            out.append(doc)
    return out


def read_fix_log(path: Path, *, tail: int = 20000) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("schema") == FIX_LOG_SCHEMA:
            out.append(doc)
    return out


def project(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Latest row per fix_id, newest first (what the Command Center and the digest show)."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("fix_id"):
            latest[str(r["fix_id"])] = dict(r)
    return sorted(latest.values(), key=lambda r: str(r.get("at") or ""), reverse=True)


def verified_for_defect(fix_log: Path, defect_id: str) -> Optional[dict]:
    """For scripts/self_heal_fixer.py advance(): a train-monitor defect counts as recovered when the monitor has
    written a fixed-released row with verified_at for its fix (the defect_id carries the signature)."""
    parts = str(defect_id or "").split("|")
    if len(parts) < 2 or not parts[0].startswith(LANE_PREFIX):
        return None
    fid = fix_id(parts[1])
    for r in reversed(read_fix_log(fix_log)):
        if r.get("fix_id") == fid and r.get("outcome") == "fixed-released" and r.get("verified_at"):
            return r
    return None
