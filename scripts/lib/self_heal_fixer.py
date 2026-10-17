"""Self-heal Claude Code fixer: the pure core (no I/O, no subprocess).

Operator 2026-10-16: "with the self-fixing in some of these procedures, I just don't want the regular LLM routing. I
want it to connect into Claude Code to fix it in iterations. This is supposed to be smart."

A self-heal diagnosis with failure class ``code_error`` (the diagnoser's ``fix_path`` / route ``fix_pr_release``)
becomes ONE fix job per (lane, failure signature). ``scripts/self_heal_fixer.py`` owns every side effect (worktrees,
the claude CLI, pytest, git, gh); this module owns every decision, so each one is testable without a model:

* the job lifecycle and its legal transitions (a fix PR is not a heal);
* intake: which escalations become jobs, dedupe, cooldown, refused lanes;
* the evidence pack and the prompt (AGENTS.md section 0 quoted verbatim from the base commit);
* the claude argv and child env (tool allowlist, dontAsk, no credentials in the env);
* the diff guard (protected paths, append-only CI registration, test deletion / skip / assert removal);
* progress (failing set) and the arming / policy gates.

AUTHORITY: the model's output never grants execution. Arming is an operator guard grant read by the host; the diff
guard is code; the push needs the AGENTS.md amendment marker at the base commit.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    _ET = timezone(timedelta(hours=-4))

JOB_SCHEMA = "SelfHealFixJob@v1"
STATE_SCHEMA = "SelfHealFixerState@v1"
EVIDENCE_SCHEMA = "SelfHealFixEvidence@v1"
RECEIPT_SCHEMA = "SelfHealFixerReceipt@v1"

# ---------------------------------------------------------------- lifecycle
FIX_REQUESTED = "fix_requested"
FIX_ATTEMPTING = "fix_attempting"
#: Fix committed on a local branch; push/PR not allowed yet (AGENTS.md 24.5 until the amendment is ACTIVE).
FIX_READY_LOCAL = "fix_ready_local"
FIX_PR_OPENED = "fix_pr_opened"
FIX_DEPLOYED = "fix_deployed"
OUTPUT_RECOVERED = "output_recovered"
INCIDENT_RESOLVED = "incident_resolved"
FIX_FAILED = "fix_failed"
FIX_REFUSED = "fix_refused"
FIX_CLOSED = "fix_closed"
#: The attempt's owner died mid-attempt (its durable lease expired or its pid is gone). Reconciled on the next start
#: with the recorded partial evidence; never restarted blindly (architect review 2026-10-16, finding 3).
FIX_INTERRUPTED = "fix_interrupted"

STATES = (FIX_REQUESTED, FIX_ATTEMPTING, FIX_READY_LOCAL, FIX_PR_OPENED, FIX_DEPLOYED, OUTPUT_RECOVERED,
          INCIDENT_RESOLVED, FIX_FAILED, FIX_REFUSED, FIX_CLOSED, FIX_INTERRUPTED)
TERMINAL = frozenset({INCIDENT_RESOLVED, FIX_FAILED, FIX_REFUSED, FIX_CLOSED, FIX_INTERRUPTED})
ACTIVE = frozenset(STATES) - TERMINAL
#: Only these may be reported as healed: a merged PR, or even deployed code, is not a heal.
HEALED = frozenset({OUTPUT_RECOVERED, INCIDENT_RESOLVED})

TRANSITIONS: dict[str, frozenset[str]] = {
    FIX_REQUESTED: frozenset({FIX_ATTEMPTING, FIX_REFUSED, FIX_INTERRUPTED}),
    FIX_ATTEMPTING: frozenset({FIX_ATTEMPTING, FIX_READY_LOCAL, FIX_PR_OPENED, FIX_FAILED, FIX_REFUSED,
                               FIX_INTERRUPTED}),
    FIX_READY_LOCAL: frozenset({FIX_PR_OPENED, FIX_CLOSED}),
    FIX_PR_OPENED: frozenset({FIX_DEPLOYED, FIX_CLOSED}),
    FIX_DEPLOYED: frozenset({OUTPUT_RECOVERED}),
    OUTPUT_RECOVERED: frozenset({INCIDENT_RESOLVED}),
}


class TransitionError(ValueError):
    pass


def transition(job: dict, new: str, now: datetime, **fields: Any) -> dict:
    """Move ``job`` to ``new`` (legal edges only), stamping the history. Returns the job."""
    old = job.get("state")
    if new not in TRANSITIONS.get(old, frozenset()):
        raise TransitionError(f"{old} -> {new} is not a legal self-heal fix transition")
    job["state"] = new
    job.setdefault("history", []).append({"state": new, "at": now.isoformat(),
                                          **{k: v for k, v in fields.items() if k != "iteration_record"}})
    job.update({k: v for k, v in fields.items() if k not in ("iteration_record", "note")})
    return job


def is_healed(job: Mapping[str, Any]) -> bool:
    return job.get("state") in HEALED


# ---------------------------------------------------------------- identity and dedupe
_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)):\s*(.*)$", re.M)
_NOISE = re.compile(r"(0x[0-9a-f]+|\b\d+\b|/[^\s\"']+)", re.I)


def final_exception(text: Any) -> Optional[tuple[str, str]]:
    """The last ``ExcType: message`` line of a traceback tail, or None."""
    found = _EXC_LINE.findall(str(text or ""))
    return (found[-1][0], found[-1][1].strip()) if found else None


def local_signature(lane: str, stderr_tail: Any) -> str:
    """Stand-in signature when the diagnoser supplied none: lane + final exception type + normalized message."""
    exc = final_exception(stderr_tail) or ("unknown", str(stderr_tail or "")[-200:])
    msg = _NOISE.sub("<n>", exc[1].lower())
    return hashlib.sha256(f"{lane}|code_error:{exc[0]}|{msg}".encode()).hexdigest()[:12]


def dedupe_key(lane: str, signature: str) -> str:
    return f"{lane}|{signature}"


def job_id(lane: str, signature: str, n: int) -> str:
    return f"shf-{hashlib.sha256(dedupe_key(lane, signature).encode()).hexdigest()[:10]}-{n}"


def _match_any(value: str, patterns: Iterable[str]) -> Optional[str]:
    v = str(value or "").lower()
    base = v.rsplit("/", 1)[-1]
    for pat in patterns:
        p = str(pat).lower()
        if fnmatch.fnmatchcase(v, p) or fnmatch.fnmatchcase(base, p):
            return pat
    return None


def lane_refusal(lane: str, script: Optional[str], cfg: Mapping[str, Any],
                 held: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Why a lane may never get an autonomous fix (broker/order/stop/execution class, or an operator hold)."""
    pats = cfg.get("intake", {}).get("refuse_lane_patterns") or []
    hit = _match_any(lane, pats) or (script and _match_any(script, pats))
    if hit:
        return f"lane_refused:pattern:{hit}"
    if script:
        guard_hit = _match_any(script, cfg.get("diff_guard", {}).get("refuse_paths") or [])
        if guard_hit:
            return f"lane_refused:protected_script:{guard_hit}"
    if held and lane in held:
        return f"lane_refused:operator_hold:{str(held[lane])[:80]}"
    return None


# ---------------------------------------------------------------- intake: the N8nCodeDefect@v1 contract
#: The producer's contract (scripts/n8n_failure_diagnosis.py code_defect_hook, PR #1828): one record per
#: (lane, signature, episode), published in each diagnosis record's ``code_defect`` field of
#: data/runtime/n8n_diagnoses/diagnoses.jsonl and in the escalation's ``fix_path``. This lane is its consumer.
CODE_DEFECT_SCHEMA = "N8nCodeDefect@v1"
CODE_DEFECT_CONSUMER = "claude_code_iterative_fix"


def _defect_ok(d: Any, cfg: Mapping[str, Any]) -> bool:
    i = cfg.get("intake", {})
    return (isinstance(d, dict) and d.get("schema") == i.get("contract_schema", CODE_DEFECT_SCHEMA)
            and d.get("consumer") == i.get("consumer", CODE_DEFECT_CONSUMER)
            and d.get("kind") == "code_defect" and bool(d.get("defect_id")) and bool(d.get("lane")))


def defect_to_incident(d: Mapping[str, Any], *, at: Any = None, escalation: Optional[Mapping[str, Any]] = None) -> dict:
    """Normalize one N8nCodeDefect@v1 record into the fixer's incident shape (pointers kept, nothing invented)."""
    ev = d.get("evidence") or {}
    sig, ep, lane = str(d.get("signature") or ""), int(d.get("episode") or 1), str(d.get("lane"))
    esc_key = (escalation or {}).get("key") or (f"{lane}|{sig}" + (f"|ep{ep}" if ep > 1 else "") if sig else None)
    return {"defect_id": d["defect_id"], "lane": lane, "signature": sig or None, "episode": ep,
            "failure_kind": d.get("failure_kind"), "failure_class": d.get("failure_class"),
            "siem_id": ev.get("siem_id"), "incident_key": ev.get("incident_key"), "event_type": ev.get("event_type"),
            "failed_run_id": ev.get("failed_run_id"), "evidence_pack": ev.get("evidence_pack"),
            "key": esc_key, "contract": {k: d.get(k) for k in ("schema", "defect_id", "consumer", "consumer_status")},
            "at": at or (escalation or {}).get("at")}


def code_defects(records: Iterable[Mapping[str, Any]], diag_state: Optional[Mapping[str, Any]],
                 cfg: Mapping[str, Any]) -> list[dict]:
    """Every distinct N8nCodeDefect@v1 addressed to this consumer, from the diagnoses store and the escalations
    book (newest record per defect_id wins), oldest first. Records that are not the contract are ignored."""
    seen: dict[str, dict] = {}
    for rec in records or []:
        d = (rec or {}).get("code_defect") if isinstance(rec, dict) else None
        if _defect_ok(d, cfg):
            seen[d["defect_id"]] = defect_to_incident(d, at=rec.get("at") or rec.get("ts"))
    for key, esc in ((diag_state or {}).get("escalations") or {}).items():
        d = (esc or {}).get("fix_path") if isinstance(esc, dict) else None
        if _defect_ok(d, cfg):
            inc = defect_to_incident(d, escalation={**esc, "key": esc.get("key") or key})
            seen.setdefault(d["defect_id"], inc)["key"] = inc["key"]
    return sorted(seen.values(), key=lambda e: str(e.get("at") or ""))


def active_job_for(state: Mapping[str, Any], dkey: str) -> Optional[dict]:
    for job in (state.get("jobs") or {}).values():
        if job.get("dedupe_key") == dkey and job.get("state") in ACTIVE:
            return job
    return None


def last_job_for(state: Mapping[str, Any], dkey: str) -> Optional[dict]:
    jobs = [j for j in (state.get("jobs") or {}).values() if j.get("dedupe_key") == dkey]
    return max(jobs, key=lambda j: str(j.get("created_at") or "")) if jobs else None


def admit(state: dict, incident: Mapping[str, Any], *, now: datetime, cfg: Mapping[str, Any],
          held: Optional[Mapping[str, Any]] = None) -> tuple[Optional[dict], str]:
    """Create a ``fix_requested`` job for ``incident`` unless deduped, cooling down or refused. Pure on ``state``."""
    lane = str(incident.get("lane") or "")
    if not lane:
        return None, "no_lane"
    did = incident.get("defect_id")
    if did:
        prior = next((j for j in (state.get("jobs") or {}).values() if j.get("defect_id") == did), None)
        if prior:
            return None, f"consumed:{prior['job_id']}:{prior['state']}"
    sig = str(incident.get("signature") or local_signature(lane, incident.get("stderr_tail")))
    dkey = dedupe_key(lane, sig)
    act = active_job_for(state, dkey)
    if act:
        return None, f"deduped:active:{act['job_id']}"
    last = last_job_for(state, dkey)
    cool = float(cfg.get("intake", {}).get("retry_cooldown_hours", 72))
    if last and last.get("state") in (FIX_FAILED, FIX_REFUSED, FIX_CLOSED, FIX_INTERRUPTED):
        at = _parse(last.get("updated_at") or last.get("created_at"))
        if at and now - at < timedelta(hours=cool):
            return None, f"cooldown:{last['job_id']}:{last['state']}"
    n = 1 + sum(1 for j in (state.get("jobs") or {}).values() if j.get("dedupe_key") == dkey)
    job = {
        "schema": JOB_SCHEMA, "job_id": job_id(lane, sig, n), "dedupe_key": dkey, "lane": lane, "signature": sig,
        "defect_id": did, "contract": incident.get("contract"), "episode": incident.get("episode"),
        "failed_run_id": incident.get("failed_run_id"),
        "incident_key": incident.get("incident_key") or incident.get("key"),
        "escalation_key": incident.get("key"), "siem_id": incident.get("siem_id"),
        "failure_kind": (incident.get("fix_path") or {}).get("failure_kind") or incident.get("failure_kind"),
        "state": FIX_REQUESTED, "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "history": [{"state": FIX_REQUESTED, "at": now.isoformat()}], "iterations": [], "cost_usd": 0.0,
        "escalated_at": None,
    }
    refusal = lane_refusal(lane, incident.get("script"), cfg, held)
    if refusal:
        job.update(state=FIX_REFUSED, refusal=[refusal])
        job["history"].append({"state": FIX_REFUSED, "at": now.isoformat(), "reason": refusal})
    state.setdefault("jobs", {})[job["job_id"]] = job
    return job, "admitted" if not refusal else refusal


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def et_day(now: datetime) -> str:
    return now.astimezone(_ET).date().isoformat()


def jobs_started_today(state: Mapping[str, Any], now: datetime) -> int:
    day = et_day(now)
    n = 0
    for job in (state.get("jobs") or {}).values():
        at = _parse(job.get("attempt_started_at"))
        if at and et_day(at) == day:
            n += 1
    return n


# ---------------------------------------------------------------- evidence
_SECRETISH = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|COOKIE|DSN|PRIVATE_KEY)[A-Z0-9_]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
_URL_CRED = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@")
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_./-])[A-Za-z0-9+_=]{40,}(?![A-Za-z0-9_./-])")


def redact(text: Any) -> str:
    """Strip credential-shaped values from log text before it leaves the host (AGENTS.md 2A data scope)."""
    s = str(text or "")
    s = _SECRETISH.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", s)
    s = _URL_CRED.sub(lambda m: f"{m.group(1)}<redacted>@", s)
    return _LONG_TOKEN.sub(lambda m: m.group(0) if re.fullmatch(r"[0-9a-f]{40}", m.group(0)) else "<redacted>", s)


def script_from_argv(argv: Iterable[Any]) -> Optional[str]:
    for a in argv or []:
        a = str(a)
        if a.endswith(".py") and ("scripts/" in a or a.startswith("scripts")):
            return a[a.index("scripts/"):] if "scripts/" in a else a
    return None


def build_evidence(job: Mapping[str, Any], *, incident: Mapping[str, Any], receipt: Optional[Mapping[str, Any]],
                   registry_row: Optional[Mapping[str, Any]], base_sha: str, cfg: Mapping[str, Any]) -> dict:
    """Everything the fixer knows about the failure, bounded and redacted. Pure."""
    rc = dict(receipt or {})
    tail_n = int(cfg.get("intake", {}).get("stderr_tail_chars", 4000))
    argv = [str(a) for a in (rc.get("argv") or [])]
    script = incident.get("script") or script_from_argv(argv) or \
        ((registry_row or {}).get("scheduler") or {}).get("match")
    stderr = redact(str(rc.get("stderr_tail") or incident.get("stderr_tail") or "")[-tail_n:])
    exc = final_exception(stderr)
    return {
        "schema": EVIDENCE_SCHEMA,
        "job_id": job.get("job_id"),
        "lane": job.get("lane"),
        "signature": job.get("signature"),
        "failure_class": "code_error",
        "failure_kind": job.get("failure_kind") or (f"code_error:{exc[0].rsplit('.', 1)[-1]}" if exc else None),
        "incident": {k: incident.get(k) for k in ("key", "incident_key", "siem_id", "event_type", "severity",
                                                   "reason", "detail", "tried", "at") if incident.get(k) is not None},
        "failing_run": {
            "run_id": rc.get("run_id"), "state": rc.get("state"), "exit_code": rc.get("exit_code"),
            "reason": rc.get("reason"), "code_sha": rc.get("code_sha"), "finished_at": rc.get("finished_at"),
            "argv": [redact(a) for a in argv], "stderr_tail": stderr,
            "stdout_tail": redact(str(rc.get("stdout_tail") or "")[-1500:]) or None,
        },
        "final_exception": {"type": exc[0], "message": exc[1][:300]} if exc else None,
        "script": script,
        "registry": {k: (registry_row or {}).get(k) for k in ("lane_id", "owner", "state", "output_signal",
                                                             "expected_cadence_hours")} if registry_row else None,
        "repro": {
            "failing_command": " ".join(argv) or None,
            "do_not_run": "never run the lane itself (it writes the production DB and state); reproduce it in a "
                          "hermetic pytest with fakes",
            "hermetic_test_required": True,
        },
        "base_sha": base_sha,
        "data_scope": "lane metadata, error text, log lines, public repo code (AGENTS.md 2A); credentials redacted",
    }


# ---------------------------------------------------------------- prompt
_SECTION0 = re.compile(r"^# 0 · If you read nothing else\s*$(.*?)^---\s*$", re.M | re.S)


def extract_rails(agents_text: str) -> str:
    """AGENTS.md section 0 verbatim. Raises if absent: a prompt without the rails is never sent."""
    m = _SECTION0.search(agents_text or "")
    if not m or "MBI_BEHAVIOR" not in m.group(1):
        raise ValueError("AGENTS.md section 0 not found at the base commit; refusing to build a prompt")
    return "# 0 · If you read nothing else" + m.group(1).rstrip() + "\n"


def build_prompt(evidence: Mapping[str, Any], *, rails: str, cfg: Mapping[str, Any], iteration: int,
                 pytest_cmd: str, prev: Optional[Mapping[str, Any]] = None) -> str:
    py = pytest_cmd
    refuse = ", ".join(cfg["diff_guard"]["refuse_paths"])
    lane = evidence.get("lane")
    test_hint = f"tests/test_self_heal_{re.sub(r'[^a-z0-9]+', '_', str(lane).lower()).strip('_')}.py"
    parts = [
        f"You are the Trade AI self-heal fixer (iteration {iteration} of at most "
        f"{cfg['iteration']['max_iterations']}). You run headless in an isolated git worktree of the public repo "
        f"PatsKiller/tardeai at base {evidence.get('base_sha')}. Fix ONE code defect: lane `{lane}` failed with a "
        f"code error (not a transient failure). The harness, not you, will commit, push and open the PR.",
        "## Rails (AGENTS.md section 0, verbatim; they bind you)\n" + rails,
        "## Hard limits enforced by code on your diff (a breach refuses the whole job)\n"
        f"- Never edit: {refuse}. `scripts/run_cio_hardening_ci.py` is append-only: you may ONLY add your new test "
        "file to the GATES list (a new `(\"name\", [\"tests/test_x.py\"]),` entry with a comment); no other edit.\n"
        "- Never delete, skip, xfail, deselect or weaken a test; never remove an assert. Tests must stay hermetic: "
        "TRADE_AI_CI=1 is set; fake connections, tmp_path state; no DB, network, broker, Telegram, n8n or .env.\n"
        "- Never run the lane, a live script, git commit/push, gh, crontab, systemctl, psql or curl. Allowed shell: "
        f"`{py} ...` (pytest, inside your sandbox) and read-only git (diff/status/log/show).\n"
        "- You run in a sandbox: only this worktree is writable and there is no network but the model API. Never "
        "write a credential, token or key into any file: a credential-shaped literal in the diff refuses the job.\n"
        "- Preserve CRLF files byte-exactly (check `file <path>` before editing; edit with care).\n"
        f"- Keep the diff minimal: at most {cfg['diff_guard']['max_files_changed']} files and "
        f"{cfg['diff_guard']['max_lines_changed']} changed lines. Fix the root cause; do not mask it in an except.",
        "## Procedure\n"
        f"1. Reproduce FIRST: write a failing regression test (suggested `{test_hint}`) that reproduces the evidence "
        "below with fakes. The harness copies your test onto the base commit and REQUIRES it to fail there.\n"
        "2. Fix the defect in the lane's code.\n"
        f"3. Run `{py} <your test> -q` until it passes; run the neighbouring tests of the file you changed.\n"
        "4. Register the new test file in scripts/run_cio_hardening_ci.py GATES (append-only).\n"
        "5. Finish with ONE line of JSON: {\"root_cause\": \"...\", \"fix\": \"...\", \"tests\": [\"tests/...\"], "
        "\"confidence\": 0.0-1.0}. If you cannot fix it safely, change nothing and say why in that JSON.",
        "## Evidence pack\n```json\n" + json.dumps(evidence, indent=1, sort_keys=True) + "\n```",
    ]
    if prev:
        tail = int(cfg["iteration"].get("previous_output_tail_chars", 6000))
        parts.append(
            f"## Previous iteration ({prev.get('iteration')}) did not pass. The worktree still holds its diff.\n"
            f"Failing set: {json.dumps(prev.get('failing') or [])}\n"
            f"Guard refusals: {json.dumps(prev.get('refusals') or [])}\n"
            f"Red-first on base: {prev.get('red_first')}\n"
            "Harness test output (tail):\n```\n" + str(prev.get("output_tail") or "")[-tail:] + "\n```\n"
            "Address exactly these failures. Do not repeat the same change.")
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------- claude invocation
def claude_argv(cfg: Mapping[str, Any], *, budget_usd: float, pytest_cmd: str) -> list[str]:
    """``--setting-sources project``: the user's settings (which pre-approve e.g. ``gh pr merge`` and the deploy
    script for interactive sessions) are NOT loaded, so only this allowlist applies; deny rules win regardless."""
    c = cfg["claude"]
    allowed = [str(t).replace("{pytest}", pytest_cmd) for t in c["allowed_tools"]]
    argv = [c["bin"], "-p", "--output-format", "json", "--permission-mode", c.get("permission_mode", "dontAsk"),
            "--tools", ",".join(c["tools"]), "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(c["disallowed_tools"]),
            "--max-budget-usd", f"{max(0.01, float(budget_usd)):.2f}",
            "--setting-sources", c.get("setting_sources", "project"), "--strict-mcp-config",
            "--no-session-persistence"]
    if c.get("model"):
        argv += ["--model", str(c["model"])]
    return argv


def sandbox_prefix(cfg: Mapping[str, Any], *, home: str, repo_root: str, writable: Iterable[str],
                   existing: Callable[[str], Optional[str]]) -> list[str]:
    """bwrap argv prefix for every test the fixer or the model runs: no network (own netns, so no localhost DB),
    /run and /tmp replaced, credential/release/state dirs hidden, the filesystem read-only except ``writable``.
    pytest executes model-written code, so this — not the prompt — is what keeps a test off production.
    ``existing(path)`` returns "dir" / "file" / None (the caller's filesystem probe). [] when disabled."""
    sb = cfg.get("sandbox") or {}
    if not sb.get("enabled"):
        return []
    argv = [sb.get("bwrap", "bwrap"), "--die-with-parent", "--unshare-net", "--unshare-ipc", "--ro-bind", "/", "/",
            "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/run", "--tmpfs", "/tmp"]
    for raw in sb.get("hide_paths") or []:
        p = str(raw).replace("{home}", home).replace("{repo_root}", repo_root)
        kind = existing(p)
        if kind == "dir":
            argv += ["--tmpfs", p]
        elif kind == "file":
            argv += ["--ro-bind", "/dev/null", p]
    for p in writable:
        argv += ["--bind", str(p), str(p)]
    return argv


def child_env(environ: Mapping[str, str], cfg: Mapping[str, Any], *, scratch_state: str) -> dict[str, str]:
    """The env for the claude CLI and every test run: named basics only, plus the CI fence. No credential names."""
    env = {k: environ[k] for k in cfg["claude"]["env_names"] if k in environ}
    env.update(TRADE_AI_CI="1", TRADEAI_STATE_ROOT=scratch_state, PYTHONDONTWRITEBYTECODE="1")
    return env


# ---------------------------------------------------------------- the agent's own boundary (review finding 2)
#: Probe results for ``agent_sandbox_prefix``: "dir", "file", "link:<target>" or None (absent).
Probe = Callable[[str], Optional[str]]


def agent_auth_binds(cfg: Mapping[str, Any], *, home: str, agent_home: str,
                     probe: Probe) -> tuple[list[tuple[str, str, bool]], str]:
    """The ONLY credential the agent sandbox sees: ``claude.auth``. Mode ``credentials_file`` binds the one OAuth
    credentials file of the Claude CLI (``{home}/.claude/.credentials.json``, never read by the harness) at
    ``{agent_home}/.claude/.credentials.json``; ``CLAUDE_CONFIG_DIR`` points there, so the rest of ``~/.claude``
    (history, transcripts, settings, other projects) is not visible. ``rw`` lets the CLI persist a token refresh in
    place. Mode ``none`` binds nothing (stub CLIs). Returns (binds, why)."""
    auth = (cfg.get("claude") or {}).get("auth") or {"mode": "none"}
    mode = auth.get("mode", "none")
    if mode == "none":
        return [], "auth:none"
    if mode != "credentials_file":
        return [], f"auth_mode_unknown:{mode}"
    src = str(auth.get("credentials_file") or "{home}/.claude/.credentials.json").replace("{home}", home)
    if probe(src) != "file":
        return [], "auth_credentials_file_missing"
    return [(src, f"{agent_home}/.claude/.credentials.json", bool(auth.get("rw", True)))], "auth:credentials_file"


def agent_env(environ: Mapping[str, str], cfg: Mapping[str, Any], *, scratch_state: str, agent_home: str,
              proxy_port: Optional[int]) -> dict[str, str]:
    """The agent's env INSIDE its sandbox (bwrap --clearenv, then exactly these). HOME is a throwaway dir; the CLI's
    config dir is the scoped one; egress goes through the in-sandbox bridge to the host allowlist proxy."""
    asb = cfg.get("agent_sandbox") or {}
    env = child_env(environ, cfg, scratch_state=scratch_state)
    env.update(HOME=agent_home, CLAUDE_CONFIG_DIR=f"{agent_home}/.claude", TMPDIR="/tmp",
               PATH=str(asb.get("path") or "/usr/local/bin:/usr/bin:/bin"),
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1",
               DISABLE_ERROR_REPORTING="1")
    for k in ("USER", "LOGNAME"):
        env.pop(k, None)
    if proxy_port:
        url = f"http://127.0.0.1:{int(proxy_port)}"
        env.update(HTTPS_PROXY=url, https_proxy=url, HTTP_PROXY=url, http_proxy=url, NO_PROXY="", no_proxy="")
    return env


DEFAULT_SYSTEM_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")


def allowlist_prefix(sb: Mapping[str, Any], *, ro: Iterable[str], rw: Iterable[str], probe: Probe,
                     binds: Iterable[tuple[str, str, bool]] = (), masks: Iterable[str] = (),
                     env: Optional[Mapping[str, str]] = None, chdir: Optional[str] = None) -> list[str]:
    """A bwrap argv prefix over an ALLOWLIST filesystem: an empty root, the system dirs and ``ro`` read-only, ``rw``
    read-write, nothing else. $HOME is never bound, so ~/.env, ~/.ssh, ~/.config/gh, ~/.cursor, ~/.claude,
    ~/trade-ai-releases, persistent state and the operator repo's untracked files (.env backups, data/, logs/) do not
    exist inside. Own network namespace (localhost is the sandbox's own loopback), pid/ipc/uts namespaces, a new
    session, and (when ``env`` is given) a cleared environment."""
    argv = [str(sb.get("bwrap", "bwrap")), "--die-with-parent", "--new-session", "--unshare-net", "--unshare-ipc",
            "--unshare-pid", "--unshare-uts"]
    if env is not None:
        argv.append("--clearenv")
        for k in sorted(env):
            argv += ["--setenv", k, str(env[k])]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    seen: set[str] = set()
    for p in sb.get("system_ro") or DEFAULT_SYSTEM_RO:
        kind = probe(str(p))
        if kind and kind.startswith("link:"):
            argv += ["--symlink", kind[5:], str(p)]
        elif kind:
            argv += ["--ro-bind", str(p), str(p)]
        seen.add(str(p))
    for p in ro:
        p = str(p)
        if p and p not in seen and probe(p):
            argv += ["--ro-bind", p, p]
            seen.add(p)
    for p in masks:
        kind = probe(str(p))
        if kind == "dir":
            argv += ["--tmpfs", str(p)]
        elif kind:
            argv += ["--ro-bind", "/dev/null", str(p)]
    for p in rw:
        argv += ["--bind", str(p), str(p)]
    for src, dst, rw_ in binds:
        argv += ["--bind" if rw_ else "--ro-bind", src, dst]
    if chdir:
        argv += ["--chdir", str(chdir)]
    return argv


def agent_sandbox_prefix(cfg: Mapping[str, Any], *, home: str, repo_root: str, python_root: str,
                         extra_ro: Iterable[str], fix_wt: str, agent_home: str, scratch: str,
                         auth_binds: Iterable[tuple[str, str, bool]], env: Mapping[str, str],
                         probe: Probe) -> list[str]:
    """bwrap argv prefix for the Claude Code process ITSELF (review finding 2), not only its tests. Read-only: the
    system dirs, the repo's git database (``{repo_root}/.git``: history for git diff/log/show; the operator's working
    tree is NOT bound), the python venv, the CLI binary and the harness bin dir. Read-write ONLY: the candidate
    worktree, a throwaway HOME and the scratch state. The one credential is ``auth_binds``. The network is the egress
    bridge only. [] when ``agent_sandbox.enabled`` is false."""
    asb = cfg.get("agent_sandbox") or {}
    if not asb.get("enabled"):
        return []
    sb = {**asb, "bwrap": asb.get("bwrap") or (cfg.get("sandbox") or {}).get("bwrap", "bwrap")}

    def sub(raw: Any) -> str:
        return str(raw).replace("{home}", home).replace("{repo_root}", repo_root)

    return allowlist_prefix(sb, ro=[f"{repo_root}/.git", python_root, *[sub(x) for x in extra_ro]],
                            rw=[fix_wt, agent_home, scratch], binds=auth_binds,
                            masks=[sub(x) for x in asb.get("mask_paths") or []], env=env, probe=probe, chdir=fix_wt)


def eval_sandbox_prefix(cfg: Mapping[str, Any], *, repo_root: str, python_root: str, checkout: str, scratch: str,
                        env: Mapping[str, str], probe: Probe, extra_ro: Iterable[str] = ()) -> list[str]:
    """bwrap argv prefix for every HARNESS test run (red-first, targeted, CI) of a candidate (review finding 1). The
    checkout and its own .git are READ-ONLY (so are the shared objects it borrows); only the scratch state is
    writable; no network. [] when ``sandbox.enabled`` is false (then the before/after digest still catches writes)."""
    sb = cfg.get("sandbox") or {}
    if not sb.get("enabled"):
        return []
    return allowlist_prefix(sb, ro=[f"{repo_root}/.git", python_root, *extra_ro, checkout], rw=[scratch], env=env,
                            probe=probe, chdir=checkout)


def model_pytest_wrapper(*, python: str, env: Mapping[str, str], sandbox: list[str]) -> str:
    """The model's ONLY test command. Inside the agent sandbox (``sandbox`` empty) it runs pytest with a cleared env
    (no proxy, no auth, no CLAUDE_CONFIG_DIR): test code inherits nothing of the agent's. Without the agent sandbox
    (test configs only) it runs pytest under the host-view test sandbox ``sandbox``."""
    import shlex

    env_args = ["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in sorted(env.items())]]
    return "#!/bin/sh\nexec " + shlex.join([*env_args, *sandbox, python, "-m", "pytest", "-p", "no:cacheprovider"]) \
        + ' "$@"\n'


# ---------------------------------------------------------------- output contract (review finding 4)
#: n8n_output_verdict verdicts that mean "the lane's declared output was produced" (same as lib/n8n_self_heal).
OUTPUT_MET = frozenset({"produced", "empty_allowed"})


def receipt_meets_output_contract(row: Mapping[str, Any], since: Optional[datetime]) -> Optional[str]:
    """None when one ledger row (state, exit_code, finished_at, receipt) proves the lane's output contract after
    ``since``, else why not. Conservative: a LIVE RUN_DONE, exit 0, whose EFFECTIVE mode is live (the stage clamp did
    not downgrade it), finished after ``since``, with output_verdict produced / empty_allowed. A newer file mtime or
    JSON timestamp alone never counts."""
    rec = row.get("receipt") if isinstance(row.get("receipt"), Mapping) else {}
    if since is None:
        return "no_since"
    fin = _parse(row.get("finished_at") or rec.get("finished_at"))
    if not fin or fin <= since:
        return "not_after_since"
    if (row.get("state") or rec.get("state")) != "RUN_DONE":
        return "not_run_done"
    ec = row.get("exit_code") if row.get("exit_code") is not None else rec.get("exit_code")
    if ec not in (0, "0"):
        return "nonzero_or_unknown_exit"
    clamp = rec.get("stage_clamp") if isinstance(rec.get("stage_clamp"), Mapping) else {}
    if rec.get("mode") != "live" or (row.get("mode") not in (None, "live")) or \
            (clamp and clamp.get("effective_mode") != "live"):
        return "effective_mode_not_live"
    ov = rec.get("output_verdict") if isinstance(rec.get("output_verdict"), Mapping) else {}
    if str(ov.get("verdict") or "") not in OUTPUT_MET:
        return f"output_verdict:{ov.get('verdict') or 'absent'}"
    return None


# ---------------------------------------------------------------- secrets in a diff (the repo is PUBLIC)
_SECRET_LITERAL = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\"(?:accessToken|refreshToken)\"\s*:)")
_OPAQUE = re.compile(r"[A-Za-z0-9+/_-]{48,}={0,2}")


def secret_like(line: str) -> Optional[str]:
    """A credential-shaped literal in an added line, else None. The agent can see its own auth inside its sandbox,
    so the diff (which goes to a PUBLIC repo) is scanned by code before anything is committed or pushed."""
    m = _SECRET_LITERAL.search(line or "")
    if m:
        return m.group(1)[:12]
    for tok in _OPAQUE.findall(line or ""):
        if re.fullmatch(r"[0-9a-fA-F]+", tok) or "_" in tok.strip("_") and tok.lower() == tok:
            continue
        if re.search(r"[A-Z]", tok) and re.search(r"[a-z]", tok) and re.search(r"[0-9]", tok):
            return tok[:8]
    return None


def parse_claude_result(stdout: str) -> dict:
    """``claude -p --output-format json`` result -> cost / error / turns / final text. Never raises."""
    doc: Any = None
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            doc = json.loads(line)
            break
        except ValueError:
            continue
    if doc is None:
        try:
            doc = json.loads(stdout or "")
        except ValueError:
            doc = None
    if not isinstance(doc, dict):
        return {"ok": False, "is_error": True, "cost_usd": 0.0, "result": (stdout or "")[-2000:], "parse": "no_json"}
    result = str(doc.get("result") or "")
    summary = None
    for line in reversed(result.strip().splitlines()):
        line = line.strip().strip("`")
        if line.startswith("{") and line.endswith("}"):
            try:
                summary = json.loads(line)
                break
            except ValueError:
                continue
    return {"ok": not doc.get("is_error"), "is_error": bool(doc.get("is_error")),
            "cost_usd": float(doc.get("total_cost_usd") or 0.0), "num_turns": doc.get("num_turns"),
            "duration_ms": doc.get("duration_ms"), "subtype": doc.get("subtype"), "result": result[-4000:],
            "summary": summary if isinstance(summary, dict) else None}


# ---------------------------------------------------------------- backends (one contract, static selector)
#: Every fix backend is driven the same way: cwd = the fix worktree, prompt on stdin, env = child_env, tests only via
#: the sandboxed pytest wrapper; its only output that matters is the files it changed. The harness and the
#: independent evaluator (lib/self_heal_fix_evaluator.py) judge the result; a backend's own claims are not read.
BACKEND_CONTRACT = "SelfHealFixBackend@v1"


def select_backend(cfg: Mapping[str, Any]) -> tuple[Optional[str], str]:
    """The STATIC selector: the configured backend, only if enabled AND qualified. Adaptive routing is shadow-only."""
    sel = cfg.get("selector") or {}
    if sel.get("mode") != "static":
        return None, "selector.mode must be static (adaptive routing runs in shadow only)"
    name = str(sel.get("backend") or "")
    b = (cfg.get("backends") or {}).get(name)
    if not isinstance(b, dict):
        return None, f"backend {name!r} not configured"
    if not b.get("enabled"):
        return None, f"backend {name} disabled"
    if not b.get("qualified"):
        return None, f"backend {name} not qualified against {BACKEND_CONTRACT}"
    return name, "static"


def backend_argv(cfg: Mapping[str, Any], name: str, *, budget_usd: float, pytest_cmd: str) -> list[str]:
    b = cfg["backends"][name]
    if b["kind"] == "claude_cli":
        return claude_argv(cfg, budget_usd=budget_usd, pytest_cmd=pytest_cmd)
    if b["kind"] == "cli_stdin":
        return [str(a).replace("{bin}", str(b["bin"])).replace("{budget}", f"{float(budget_usd):.2f}")
                .replace("{pytest}", pytest_cmd) for a in b["argv_template"]]
    raise ValueError(f"unknown backend kind {b['kind']!r}")


def parse_backend_result(cfg: Mapping[str, Any], name: str, stdout: str) -> dict:
    """Cost/turns/summary for the record only (never acceptance). Non-JSON output is kept as text."""
    r = parse_claude_result(stdout)
    if r.get("parse") == "no_json":
        r.update(ok=None, is_error=None, result=(stdout or "")[-4000:])
    r["backend"] = name
    return r


# ---------------------------------------------------------------- repair memory + shadow router
MEMORY_SCHEMA = "SelfHealRepairMemory@v1"


def memory_row(job: Mapping[str, Any], *, event: str, now: datetime, backend: Optional[str],
               iteration: Optional[Mapping[str, Any]] = None, **extra: Any) -> dict:
    """One durable, append-only repair-memory row, keyed by failure signature (groundwork for adaptive routing)."""
    row = {"schema": MEMORY_SCHEMA, "at": now.isoformat(), "event": event, "signature": job.get("signature"),
           "lane": job.get("lane"), "failure_kind": job.get("failure_kind"), "defect_id": job.get("defect_id"),
           "job_id": job.get("job_id"), "backend": backend, "selector": "static", "state": job.get("state")}
    if iteration is not None:
        row.update({k: iteration.get(k) for k in ("iteration", "diffstat", "diff_sha256", "patch", "tests_run",
                                                  "red_first", "targeted_rc", "ci_rc", "failing", "seconds")})
        row["refusals"] = [r.get("code") for r in iteration.get("refusals") or []]
        row["accepted_local"] = (iteration.get("acceptance") or {}).get("accepted")
        row["cost_usd"] = (iteration.get("backend_result") or {}).get("cost_usd")
    row.update(extra)
    return row


def shadow_route(rows: Iterable[Mapping[str, Any]], *, failure_kind: Optional[str], backends: Iterable[str],
                 chosen: Optional[str]) -> dict:
    """What an adaptive router WOULD pick from repair memory (Laplace-smoothed local acceptance rate per backend,
    same failure_kind first, else all). Recorded beside the job; never used to select (shadow mode only)."""
    rows = [r for r in rows if r.get("event") == "iteration"]
    same = [r for r in rows if failure_kind and r.get("failure_kind") == failure_kind]
    basis = same or rows
    scores = {}
    for b in backends:
        mine = [r for r in basis if r.get("backend") == b]
        ok = sum(1 for r in mine if r.get("accepted_local"))
        scores[b] = {"attempts": len(mine), "accepted": ok, "score": round((ok + 1) / (len(mine) + 2), 4)}
    rec = max(scores, key=lambda b: (scores[b]["score"], b == chosen)) if scores else None
    return {"mode": "shadow", "used": False, "chosen_static": chosen, "recommended": rec,
            "agrees": rec == chosen, "basis": "same_failure_kind" if same else "all_history", "scores": scores}


# ---------------------------------------------------------------- diff guard
def parse_name_status(text: str) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        bits = line.split("\t")
        if len(bits) >= 2:
            out.append((bits[0][:1], bits[-1]))
            if bits[0][:1] == "R" and len(bits) == 3:
                out.append(("D", bits[1]))
    return out


def parse_numstat(text: str) -> dict[str, tuple[int, int]]:
    out = {}
    for line in (text or "").splitlines():
        bits = line.split("\t")
        if len(bits) == 3:
            a, d = (int(x) if x.isdigit() else 0 for x in bits[:2])
            out[bits[2]] = (a, d)
    return out


def split_unified(diff: str) -> dict[str, dict[str, list]]:
    """{path: {"added": [...], "removed": [...], "hunks": [(old_start, old_len)]}} from ``git diff -U0``."""
    files: dict[str, dict[str, list]] = {}
    cur = None
    for line in (diff or "").splitlines():
        if line.startswith("+++ "):
            p = line[4:]
            cur = files.setdefault(p[2:] if p.startswith("b/") else p, {"added": [], "removed": [], "hunks": []})
        elif line.startswith("--- "):
            continue
        elif line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = files.setdefault(m.group(2), {"added": [], "removed": [], "hunks": []}) if m else None
        elif line.startswith("@@") and cur is not None:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+", line)
            if m:
                cur["hunks"].append((int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)))
        elif cur is not None and line.startswith("+"):
            cur["added"].append(line[1:])
        elif cur is not None and line.startswith("-"):
            cur["removed"].append(line[1:])
    return files


def gates_region(ci_text: str) -> tuple[int, int]:
    """1-based (first, last) line of the ``GATES = [`` ... ``]`` list in run_cio_hardening_ci.py."""
    lines = (ci_text or "").splitlines()
    start = next((i + 1 for i, s in enumerate(lines) if s.startswith("GATES = [")), 0)
    end = next((i + 1 for i in range(start, len(lines)) if lines[i] == "]"), 0) if start else 0
    return start, end


def guard_diff(*, name_status: str, numstat: str, unified: str, base_ci_text: str,
               cfg: Mapping[str, Any]) -> list[dict]:
    """Every reason this diff may not ship. ``hard`` refusals end the job (authority breach or test weakening);
    soft ones go back to the model as feedback."""
    g = cfg["diff_guard"]
    out: list[dict] = []
    changes = parse_name_status(name_status)
    stats = parse_numstat(numstat)
    files = split_unified(unified)
    test_re = re.compile(g["test_path_re"])
    weak_re = re.compile(g["weakening_added_re"])
    line_re = re.compile(g["append_only_line_re"])
    append_only = set(g.get("append_only_paths") or [])
    paths = sorted({p for _s, p in changes} | set(stats))
    for p in paths:
        if p in append_only:
            continue
        hit = _match_any(p, g["refuse_paths"])
        if hit:
            out.append({"hard": True, "code": "protected_path", "path": p, "pattern": hit})
    for status, p in changes:
        if status == "D" and test_re.match(p):
            out.append({"hard": True, "code": "test_deleted", "path": p})
    for p, body in files.items():
        leak = next((h for h in (secret_like(s) for s in body["added"]) if h), None)
        if leak:
            out.append({"hard": True, "code": "secret_in_diff", "path": p, "prefix": leak[:4] + "..."})
        if test_re.match(p):
            if any(weak_re.search(s) for s in body["added"]):
                out.append({"hard": True, "code": "test_weakened:skip_or_xfail", "path": p})
            removed_tests = [s.strip() for s in body["removed"] if re.match(r"\s*(async\s+)?def test_", s)]
            added_tests = {s.strip() for s in body["added"] if re.match(r"\s*(async\s+)?def test_", s)}
            gone = [t for t in removed_tests if t not in added_tests]
            if gone:
                out.append({"hard": True, "code": "test_weakened:test_removed", "path": p, "tests": gone[:5]})
            n_rm = sum(1 for s in body["removed"] if re.match(r"\s*assert\b", s))
            n_add = sum(1 for s in body["added"] if re.match(r"\s*assert\b", s))
            if n_rm > n_add:
                out.append({"hard": True, "code": "test_weakened:asserts_removed", "path": p,
                            "removed": n_rm, "added": n_add})
        if p in append_only:
            lo, hi = gates_region(base_ci_text)
            if body["removed"]:
                out.append({"hard": True, "code": "append_only:lines_removed", "path": p})
            bad = [s for s in body["added"] if not line_re.match(s)]
            if bad:
                out.append({"hard": True, "code": "append_only:non_registration_line", "path": p, "lines": bad[:3]})
            if not lo or any(not (lo <= start <= hi) for start, _n in body["hunks"]):
                out.append({"hard": True, "code": "append_only:outside_gates_list", "path": p})
    if len(paths) > int(g["max_files_changed"]):
        out.append({"hard": False, "code": "diff_too_wide", "files": len(paths)})
    n_lines = sum(a + d for a, d in stats.values())
    if n_lines > int(g["max_lines_changed"]):
        out.append({"hard": False, "code": "diff_too_large", "lines": n_lines})
    if not paths:
        out.append({"hard": False, "code": "empty_diff"})
    elif g.get("require_new_or_changed_test") and not changed_tests(name_status):
        out.append({"hard": False, "code": "no_regression_test"})
    return out


def changed_tests(name_status: str) -> list[str]:
    return sorted({p for s, p in parse_name_status(name_status)
                   if s in ("A", "M") and re.match(r"^tests/(.*/)?test_[^/]*\.py$", p)})


def diffstat(numstat: str) -> dict:
    st = parse_numstat(numstat)
    return {"files": len(st), "added": sum(a for a, _ in st.values()), "removed": sum(d for _, d in st.values()),
            "paths": sorted(st)}


# ---------------------------------------------------------------- progress
_FAIL_LINE = re.compile(r"^(FAILED|ERROR)\s+(\S+)", re.M)


def failing_set(*outputs: str) -> list[str]:
    ids = set()
    for out in outputs:
        for kind, nid in _FAIL_LINE.findall(out or ""):
            ids.add(nid if kind == "FAILED" else f"ERROR {nid}")
    return sorted(ids)


def no_progress(history: list[Mapping[str, Any]], repeat: int) -> bool:
    """True when the last ``repeat`` iterations ended with the same non-empty failing set."""
    sets = [tuple(h.get("failing") or ()) for h in history if not h.get("passed")]
    if repeat < 2 or len(sets) < repeat:
        return False
    tail = sets[-repeat:]
    return bool(tail[0]) and all(s == tail[0] for s in tail)


# ---------------------------------------------------------------- gates
def arming_verdict(grant: Optional[Mapping[str, Any]], *, cfg: Mapping[str, Any], jobs_today: int) -> dict:
    a = cfg["arming"]
    if not isinstance(grant, dict):
        return {"armed": False, "why": f"no active {a['grant_tier']} guard grant"}
    reason = str(grant.get("reason") or "")
    if a["grant_reason_token"] not in reason:
        return {"armed": False, "why": f"active {a['grant_tier']} grant does not name {a['grant_reason_token']}"}
    if jobs_today >= int(a["daily_job_cap"]):
        return {"armed": False, "why": f"daily job cap reached ({jobs_today}/{a['daily_job_cap']})"}
    return {"armed": True, "why": "grant names self-heal-fixer; under the daily cap",
            "grant_id": str(grant.get("grant_id") or "")[:16], "grant_reason": reason[:200],
            "jobs_today": jobs_today, "daily_job_cap": int(a["daily_job_cap"])}


def policy_verdict(agents_text: str, cfg: Mapping[str, Any]) -> dict:
    """Push/PR allowed only when AGENTS.md (at the job's base) carries the ACTIVE amendment heading."""
    pg = cfg["policy_gate"]
    for line in (agents_text or "").splitlines():
        if line.startswith(pg["amendment_heading_marker"]):
            ok = pg["required_status_word"] in line
            return {"push_allowed": ok, "why": "amendment ACTIVE" if ok else "amendment present but not ACTIVE",
                    "heading": line[:200]}
    return {"push_allowed": False, "why": "AGENTS.md 24.5: no push/PR from a scheduled job; amendment 24.11 absent"}


def branch_name(job: Mapping[str, Any], cfg: Mapping[str, Any], now: datetime) -> str:
    lane = re.sub(r"[^a-z0-9-]+", "-", str(job.get("lane")).lower()).strip("-")[:40]
    sig = str(job.get("signature")).removeprefix("sig-")[:8]
    return f"{cfg['repo']['branch_prefix']}{lane}-{sig}-{now.strftime('%Y%m%d%H%M')}"


def pr_body(job: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    it = job.get("iterations") or []
    last = it[-1] if it else {}
    summ = (last.get("backend_result") or {}).get("summary") or {}
    rows = "\n".join(
        f"| {r.get('iteration')} | {(r.get('diffstat') or {}).get('files')} files "
        f"+{(r.get('diffstat') or {}).get('added')}/-{(r.get('diffstat') or {}).get('removed')} | "
        f"{r.get('red_first')} | {'pass' if r.get('passed') else 'fail'} | {len(r.get('failing') or [])} | "
        f"${float((r.get('backend_result') or {}).get('cost_usd') or 0):.2f} | {r.get('seconds')}s |" for r in it)
    exc = evidence.get("final_exception") or {}
    return (
        f"## Self-heal fix: `{job.get('lane')}`\n\n"
        f"Automated fix proposed by the **self-heal-fixer** lane (headless Claude Code, isolated worktree off "
        f"`{evidence.get('base_sha')}`). This PR is **not** a heal: the incident resolves only after this is merged, "
        f"released, and the lane's output recovers (`fix_deployed` -> `output_recovered` -> `incident_resolved`).\n\n"
        f"- Job: `{job.get('job_id')}` · signature `{job.get('signature')}` · incident `{job.get('incident_key')}` "
        f"· SIEM `{job.get('siem_id')}`\n"
        f"- Failing run: `{(evidence.get('failing_run') or {}).get('run_id')}` at code "
        f"`{(evidence.get('failing_run') or {}).get('code_sha')}`\n"
        f"- Error: `{exc.get('type')}: {str(exc.get('message'))[:160]}`\n"
        f"- Backend: `{job.get('backend')}` (static selector) · defect `{job.get('defect_id')}`\n"
        f"- Root cause (backend's claim, not evidence): {str(summ.get('root_cause') or 'n/a')[:400]}\n"
        f"- Fix (backend's claim, not evidence): {str(summ.get('fix') or 'n/a')[:400]}\n\n"
        "### Iterations\n\n| k | diff | red on base | tests+CI | failing | cost | time |\n|---|---|---|---|---|---|---|\n"
        f"{rows}\n\n"
        "### Checks enforced by the harness (code, not the model)\n"
        "- every check below judged ONE immutable commit (this PR head, sha + tree) in fresh read-only checkouts "
        "whose files and .git were digested before and after each run; the PR head was verified to be that commit\n"
        "- regression test fails on the base commit and passes with the fix\n"
        "- targeted tests + `run_cio_hardening_ci.py --profile pr` green on the candidate commit\n"
        "- the agent ran in an allowlist bwrap sandbox (writes only to its worktree; egress only to the model API)\n"
        "- diff guard: no AGENTS/guard/CI-gate/allowlist/broker/credential/cron/systemd path; no test deleted, "
        "skipped or weakened; CI registration append-only\n\n"
        "Review, merge and release through the normal path. Never auto-merged.\n")
