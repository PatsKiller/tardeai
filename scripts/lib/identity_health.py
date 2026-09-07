"""Identity custodian — freshness, coverage and retention for the GUID spine.

WHY THIS EXISTS
---------------
Audited 2026-09-06: **nothing watched identity at all.** The registry holds 10,279
entities that research, news and (soon) catalysts join against, and there was no
check on whether it was fresh, whether coverage had regressed, or whether its
producers were still scheduled. `build_catalyst_graph.py` had no cron and no
timer — the graph was frozen wherever it was last run by hand.

A spine with no custodian is the same shape as every other defect found that day:
a control that has never been observed firing is indistinguishable from its
absence.

NO MODEL RUNS HERE, AND NONE MAY
--------------------------------
Every question this asks is deterministic — a count, a clock, a scheduler lookup.
`uuid5` is a pure function of (namespace, name): the same input yields the same
GUID forever, which is the entire value of the spine, and a model in that path
destroys auditability without adding information.

An LLM has exactly one legitimate role in identity, and it is not here: proposing
resolutions for the UNRESOLVED tail, written as CANDIDATE only. Deterministic
evidence (a CUSIP) is the sole thing that promotes to CONFIRMED. See AGENTS.md.

WHAT IT ALARMS ON
-----------------
  registry_stale        the minter has not run within its cadence + grace
  coverage_regressed    CONFIRMED count fell — a feed dropping identifiers
  producer_unscheduled  a writer the spine depends on has no cron and no timer
  registry_unreadable   the file is missing or corrupt

Coverage is reported even when nothing fires, so a slow decline is visible before
it becomes an alarm.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "IdentityHealth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANE = "identity-spine"

#: The minter runs weekdays 05:50 ET. Grace covers a weekend plus a missed day —
#: alarming on a Sunday because Friday was the last weekday run is the false
#: positive this system produces most often.
REGISTRY_MAX_AGE_HOURS = int(os.environ.get("IDENTITY_REGISTRY_MAX_AGE_HOURS", "80"))

#: A drop larger than this in CONFIRMED entities is a regression, not churn.
#: The registry's own rule is one-way by rank, so CONFIRMED should never fall on
#: its own; a fall means a feed stopped publishing identifiers.
COVERAGE_DROP_TOLERANCE = int(os.environ.get("IDENTITY_COVERAGE_DROP_TOLERANCE", "0"))

#: Producers the spine depends on. Each must be reachable by a scheduler, or the
#: data it maintains silently ages. `strategy_rule_engine` is listed because its
#: absence emptied a table that cio_decision_engine inner-joins, which cost 30
#: days of decisions before anyone noticed.
REQUIRED_PRODUCERS = (
    "mint_identity_registry.py",
    "build_catalyst_graph.py",
)


def _state_path() -> Path:
    """Durable, not tree-relative. A per-checkout copy would reset the coverage
    baseline on every deploy and make regression undetectable."""
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(
        Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "runtime")
    return Path(root) / "identity_health_state.json"


def _registry_path() -> Optional[Path]:
    try:
        from lib import identity_registry as R  # noqa: PLC0415
        return R.registry_path()
    except Exception:
        try:
            from scripts.lib import identity_registry as R  # type: ignore  # noqa: PLC0415
            return R.registry_path()
        except Exception:
            return None


def _is_scheduled(script: str) -> bool:
    """cron OR systemd. A scheduler declaration is a claim about reality and this
    system uses both, so checking one is how an unscheduled producer hides."""
    stem = script.replace(".py", "")
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
        for line in (cron.stdout or "").splitlines():
            s = line.strip()
            if s.startswith("#"):          # a commented cron is NOT scheduled
                continue
            if script in s:
                return True
    except Exception:
        pass
    try:
        t = subprocess.run(["systemctl", "--user", "list-timers", "--all"],
                           capture_output=True, text=True, timeout=15)
        if stem in (t.stdout or ""):
            return True
    except Exception:
        pass
    return False


def collect_identity_health(*, now: Optional[datetime] = None,
                            check_schedulers: bool = True) -> dict[str, Any]:
    """One lane row for `research_lane_health`, same shape as its collectors."""
    now = now or datetime.now(timezone.utc)
    firing: list[str] = []
    counts: dict[str, int] = {}
    age_h: Optional[float] = None
    unscheduled: list[str] = []

    path = _registry_path()
    if path is None or not path.is_file():
        firing.append("registry_unreadable")
    else:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            ents = doc.get("entities") or {}
            for e in ents.values():
                st = str(e.get("identity_status") or "UNKNOWN")
                counts[st] = counts.get(st, 0) + 1
            counts["TOTAL"] = len(ents)
            counts["WITH_CUSIP"] = sum(
                1 for e in ents.values() if (e.get("identifiers") or {}).get("cusip"))
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age_h = round((now - mtime).total_seconds() / 3600.0, 1)
            if age_h > REGISTRY_MAX_AGE_HOURS:
                firing.append(f"registry_stale:{age_h}h>{REGISTRY_MAX_AGE_HOURS}h")
        except Exception:
            firing.append("registry_unreadable")

    # Coverage regression, against the last observation rather than a constant.
    prev: dict[str, Any] = {}
    sp = _state_path()
    try:
        prev = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    prev_conf = int(prev.get("confirmed") or 0)
    conf = int(counts.get("CONFIRMED") or 0)
    if prev_conf and conf < prev_conf - COVERAGE_DROP_TOLERANCE:
        firing.append(f"coverage_regressed:{prev_conf}->{conf}")

    if check_schedulers:
        unscheduled = [p for p in REQUIRED_PRODUCERS if not _is_scheduled(p)]
        for p in unscheduled:
            firing.append(f"producer_unscheduled:{p}")

    if counts.get("TOTAL"):
        try:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps({
                "confirmed": conf, "total": counts.get("TOTAL"),
                "as_of": now.replace(microsecond=0).isoformat(),
            }, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    return {
        "lane": LANE,
        "ok": not firing,
        "firing": firing,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "registry_age_hours": age_h,
        "counts": counts,
        "unscheduled_producers": unscheduled,
        "previous_confirmed": prev_conf or None,
        "financial_action": False,
    }
