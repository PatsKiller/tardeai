"""Every remediation must point at something that exists.

Phase 6 originally specced "each entry declares a verification check". That is
redundant: #565 made verification generic -- the post-batch verdict pass re-runs
`compute(policy)` and classifies CLEARED / INEFFECTIVE / FAILED / WORSENED for
every command that fired, so no per-entry declaration adds information.

The reachability variant ("is this finding type emittable?") is unsound here:
types are built dynamically -- `ft = "news_stale" if name == "news" else
f"{name}_stale"` at health_agent.py:770 -- so a static scan reports 66 of 68
entries dead when none are. That detector was written, run, and discarded.

What IS statically decidable is below.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config/health_agent_policy.json"


ENTRYPOINT = re.compile(r"((?:scripts|linux_launchers)/[A-Za-z0-9_/]+\.(?:py|sh))")


# safe_flock.sh is the locking wrapper, not the work. Counting it as an
# entrypoint made the guard demand that the wrapper take some other job's lock.
WRAPPERS = {"scripts/safe_flock.sh"}


def _entrypoints(cmd) -> list[str]:
    blob = cmd if isinstance(cmd, str) else json.dumps(cmd)
    return [e for e in ENTRYPOINT.findall(blob) if e not in WRAPPERS]


def _cron_locks_by_script() -> dict[str, str]:
    """script path -> the lock file its cron entry holds, for flocked entries."""
    import subprocess
    try:
        text = subprocess.run(["crontab", "-l"], capture_output=True,
                              text=True, timeout=20).stdout or ""
    except Exception:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "flock" not in line:
            continue
        lock = re.search(r"(/[^\s]*\.lock)", line)
        if not lock:
            continue
        for entry in ENTRYPOINT.findall(line):
            out.setdefault(entry, lock.group(1))
    return out


def _rmap() -> dict:
    doc = json.loads(POLICY.read_text(encoding="utf-8"))
    return {k: v for k, v in (doc.get("remediation_map") or {}).items()
            if not k.startswith("_")}


def test_every_referenced_script_exists():
    """A remediation naming a deleted script fails at the moment it is needed."""
    missing = []
    for finding_type, cmd in _rmap().items():
        blob = cmd if isinstance(cmd, str) else json.dumps(cmd)
        for rel in _entrypoints(cmd):
            if not (ROOT / rel).exists():
                missing.append(f"{finding_type} -> {rel}")
    assert not missing, "remediation points at a nonexistent script: " + "; ".join(missing)


def test_every_remediation_names_a_reviewable_entrypoint():
    """A bare shell string with no script is unreviewable as an allowlist.

    `linux_launchers/` is a legitimate home for entrypoints (the pg_backup
    launcher lives there); the first version of this test only looked under
    `scripts/` and flagged three sound entries.
    """
    bare = [k for k, v in _rmap().items() if not _entrypoints(v)]
    assert not bare, f"remediation with no entrypoint to review: {bare}"


def test_a_retry_of_a_cron_flocked_script_takes_the_same_lock():
    """The map's own `_comment` states the rule, and names the incident.

    "LLM-heavy processor retries are flock-guarded on the SAME lock as the cron
    so they SINGLE-FLIGHT ... (the 2026-06-25 Ollama thundering-herd: 6+
    --limit 15 processes -> 503/timeout cascade)."

    So the predicate is not "does the finding name sound LLM-ish" -- that
    version flagged `synthesis_processing_stuck`, which runs a DB row reset.
    Scope: entries that ALREADY flock. Whether an unflocked retry *should*
    flock depends on whether that processor is LLM-heavy, which this file
    cannot decide -- the broad version flagged 30 entries that have run for
    months. What is decidable, and is the silent failure mode (see the
    quote-refresh nested-flock incident), is a retry that locks the WRONG file:
    it looks guarded, single-flights against nothing, and races the cron.
    """
    locks = _cron_locks_by_script()
    if not locks:
        return  # no crontab in this environment; nothing to assert against

    violations = []
    for finding_type, cmd in _rmap().items():
        blob = cmd if isinstance(cmd, str) else json.dumps(cmd)
        if "flock" not in blob:
            continue
        for entry in _entrypoints(cmd):
            want = locks.get(entry)
            if want and want not in blob:
                violations.append(
                    f"{finding_type} flocks, but not on {entry}'s cron lock {want}")
    assert not violations, "; ".join(violations)
