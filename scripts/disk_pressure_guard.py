#!/usr/bin/env python3
"""Page the moment disk crosses a threshold — and, when armed, trigger the reviewed cleaner.

2026-11-03 — IT ACTS THROUGH THE CLEANER, UNDER AN OPERATOR SWITCH THAT DEFAULTS OFF
-----------------------------------------------------------------------------------
Operator, 2026-11-03 (disk permanent fix, item 3): "Make the pressure guard ACT at 85%: it triggers the cleaner,
not just a report." So above the trigger, and only when ``pressure_act.armed`` is literally ``true`` in
``config/disk_hygiene_rules.json`` (and ``standing_apply`` is still enabled and approved), this guard:

  1. asks `scripts/disk_hygiene.py --standing --dry-run --report` for the selection — a dry run writes nothing at
     all, not even a lane receipt, and the guard quotes the candidate count and reclaimable bytes;
  2. refuses to apply when the dry run selects nothing (``refused_nothing_eligible``) — it never improvises a
     different rule set;
  3. otherwise runs `scripts/disk_hygiene.py --standing --apply --only-if-above <trigger> --until-target <target>`,
     which re-plans under the same reviewed rules S/T/W/C/R and its own per-run caps, and records the bytes
     reclaimed in this guard's receipt.

The guard still deletes nothing itself: every removal is the cleaner's, under the cleaner's protections (never-touch
paths, CURRENT/EXPECTED_RELEASE pointers, per-item revalidation). The switch is operator-owned (AGENTS.md §17) and
shipped OFF; no agent turns it on.

2026-10-27 — WHY THE ENFORCER IS CONSULTED FOR ITS PLAN WHEN DISARMED (AGENTS.md §24.12, §0 rule 6)
------------------------------------------------------------------------
§24.12 makes `scripts/disk_hygiene.py` (n8n lane `disk-hygiene`, or the operator
CLI) the only automated removal of release directories, and puts backups out of
scope. The enforcer this guard shelled predates §24.12 and its `--apply` now
refuses (status REFUSED_OUTSIDE_24_12, exit 77). So above the trigger the guard
asks the enforcer for its PLAN only (`--dry-run`, never `--apply`), records the
condition and pages with the governed route. Requesting `--apply` here would only
collect a refusal every 15 minutes, and would quietly resume deleting if the
enforcer were ever reverted -- two independent changes are now needed for that.
The history below is kept because it explains the trigger and the paging.

WHY THIS EXISTS
---------------
Operator, 2026-09-21: "create an alerted automated mechanism that if it is over
85% full it should execute and not wait for the weekly schedule".

The reaper already existed and was not broken. `disk_hygiene_enforcer.py` ran
correctly, protected CURRENT and EXPECTED_RELEASE, and reclaimed 74 GB the
moment it was invoked. What failed was **cadence**: it is driven only by
`tradeai-weekly-disk-cleanup.timer` (Sun 06:30). Between the 09-20 run and the
09-27 run, six deploys landed on 09-21 and the disk went to 100% full with 84 MB
free -- systemd could no longer allocate inotify watches for 11 services.

This guard changes the trigger, not the policy. It shells the SAME enforcer with
the SAME protections. It mints no retention rule of its own.

WHAT IT DOES
------------
  1. Reads disk usage. Above the trigger (default 85% used == 15% free, which is
     exactly `disk_hygiene_enforcer`'s existing `warn_free_pct`) it either:
       * DISARMED (the shipped default): asks `disk_hygiene_enforcer.py --dry-run`
         for its plan, records the condition and pages with the governed route; or
       * ARMED by the operator: dry-runs the reviewed cleaner, quotes the
         selection, and applies it only when the selection is non-empty.
  2. Records the condition through `alert_condition_state.observe()`, so the
     operator is told on a TRANSITION (ok -> pressure -> recovered) and then at
     most once per `min_realert_minutes` while it stays bad. A guard that pages
     every 15 minutes during a long cleanup is noise, and this codebase already
     has ~5,500 alerts/day of that.
  3. Sends one Telegram line on a notify-worthy transition, using the same
     idiom as weekly_disk_cleanup_notify.py:285.

WHAT IT DOES NOT DO
-------------------
Never deletes anything itself: every deletion is `scripts/disk_hygiene.py`'s,
under its reviewed standing rules, never-touch paths and per-run caps. If the
cleaner is absent or fails, this reports and exits non-zero -- it does not
improvise a fallback.

It also does not touch the database. The 2026-09-21 crisis was builds: releases
were 167 GB against a 26 GB database. Postgres retention is a separate ladder
(`hermes-librarian-retention.timer`, `db-retention.timer`) and is deliberately
out of scope here.

    python scripts/disk_pressure_guard.py                 # check + act if over (only when armed)
    python scripts/disk_pressure_guard.py --dry-run       # report only, never act
    python scripts/disk_pressure_guard.py --used-pct 80   # tighter trigger

AUTHORITY: OPERATOR_APPROVED 2026-09-21 (trigger + paging). Deletes nothing itself: reclaim is the disk-hygiene
lane's job (AGENTS.md §24.12); when the operator arms `pressure_act`, this guard triggers that reviewed cleaner
(dry run -> quoted selection -> apply) and nothing else. The arming switch is operator-only (AGENTS.md §17).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Callable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

#: 85% used == 15% free == disk_hygiene_enforcer's own `warn_free_pct`. Kept
#: identical on purpose: two components disagreeing about what "pressure" means
#: is how a guard ends up firing against a policy that will not act.
DEFAULT_USED_PCT = 85.0

#: OPERATIONS.md:71-75 -- while a condition stays bad, say so again every 6h
#: rather than every run.
REALERT_MINUTES = 360

CONDITION_KEY = "system_health:disk_pressure"


try:
    from lib.live_project_root import venv_python  # noqa: E402  (release dirs ship no .venv)
except ImportError:  # imported with scripts/lib, not scripts/, on sys.path
    from live_project_root import venv_python  # noqa: E402


def disk_used_pct(path: str = "/") -> tuple[float, int, int]:
    """Percent used AS `df` REPORTS IT — used/(used+available), not used/total.

    Found by dry-running against the real disk, 2026-09-21: `df -h /` said 89%
    while this returned 83.63%, so the guard printed `over_threshold: false`
    for an operator who had just been told 85% would act.

    The gap is the ~5% root reserve. `shutil.disk_usage()` reports `total` over
    ALL blocks but `free` over blocks reachable by an UNPRIVILEGED writer, so
    used/total mixes two denominators. `df` divides by what a normal process can
    actually reach, and "over 85% full" in the request means the number on the
    operator's screen — not a second, quieter number only this script can see.
    Trigger 85 now fires at df 85 instead of df ~90.5.
    """
    total, used, free = shutil.disk_usage(path)
    reachable = used + free  # df's "1K-blocks used + available"
    return (used / reachable * 100.0) if reachable else 0.0, free, total


def _fmt_gb(n: int) -> str:
    return f"{n / (1024**3):.1f}GB"


#: Status the enforcer reports for a refused --apply (scripts/disk_hygiene_enforcer.py REFUSED_STATUS).
#: The guard never sends --apply; this is read only so a refusal can never be mistaken for a reclaim.
ENFORCER_REFUSED = "REFUSED_OUTSIDE_24_12"
#: What the page says instead of "reclaimed": where reclaim actually lives.
GOVERNED_ROUTE_LINE = (
    "no automatic removal here (AGENTS.md §24.12): the disk-hygiene lane owns reclaim — "
    "review `python3 scripts/disk_hygiene.py --report`"
)


def _exec(argv: list[str], *, timeout: float = 1800.0, env: dict | None = None) -> dict:
    """The guard's ONLY subprocess call site (its ruff S603 allowance is exactly one). Never raises.

    ``env=None`` inherits the unit's environment verbatim, as the enforcer call always has; a cleaner apply passes a
    copy carrying ``TRADEAI_RUN_ID`` so the cleaner records a run identity and its own gates bind.
    """
    kwargs = {"env": env} if env is not None else {}
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, **kwargs)
    except Exception as exc:  # noqa: BLE001 - report, never improvise a fallback
        return {"_rc": None, "stdout": "", "stderr": "", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"_rc": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or "", "error": None}


def run_enforcer(*, dry_run: bool = True) -> dict:
    """Shell the enforcer for its PLAN only (``--dry-run``, always). ``dry_run`` is kept for callers; ignored.

    Since 2026-10-27 the guard requests no removal from the enforcer: §24.12 leaves release removal to the
    disk-hygiene lane and backups to the operator. The payload is the enforcer's dry-run plan.
    """
    del dry_run  # always plan-only
    script = ROOT / "scripts" / "disk_hygiene_enforcer.py"
    if not script.is_file():
        return {"ok": False, "error": "disk_hygiene_enforcer.py missing", "skipped": True}
    py = venv_python(ROOT)
    argv = [py if Path(py).exists() else sys.executable, str(script), "--dry-run"]
    res = _exec(argv)
    if res["error"]:
        return {"ok": False, "error": res["error"]}
    payload: dict = {}
    try:
        payload = json.loads(res["stdout"] or "{}")
    except Exception:  # noqa: BLE001 - non-JSON output is still a result
        payload = {"raw_tail": (res["stdout"] or "")[-400:]}
    # NOTE: the enforcer exits 1 while the disk is still "critical" even when its
    # own plan succeeded -- that is its alarm, not a failure. Judge on the plan.
    rel = payload.get("releases_result") or {}
    entries = (rel.get("deleted") or []) + (rel.get("refused_items") or [])
    payload["_rc"] = res["_rc"]
    # Counted by action, never by list length: a dry-run "deleted" list holds would_delete entries.
    payload["_deleted_count"] = sum(1 for e in entries if e.get("action") == "deleted")
    payload["_would_remove_count"] = sum(1 for e in entries if e.get("action") in ("would_delete", "refused"))
    payload["_reclaimed"] = 0
    payload["_refused"] = payload.get("status") == ENFORCER_REFUSED
    payload["_plan_ok"] = bool(rel.get("ok", False))
    return payload


# ---------------------------------------------------------------- item 3: act through the reviewed cleaner

CLEANER = ROOT / "scripts" / "disk_hygiene.py"
DEFAULT_RULES = ROOT / "config" / "disk_hygiene_rules.json"
#: The cleaner's executor identity variable. The guard sets it on the CHILD only (never on itself), so the cleaner
#: records ``authorization: reviewed_standing`` and its own ``standing_apply.enabled`` + approval gates bind.
RUN_ID_ENV = "TRADEAI_RUN_ID"


def act_config(rules_path: Path) -> dict:
    """The operator's arming switch, read fail-closed.

    Acting needs ALL of: ``pressure_act.armed`` is literally true, ``standing_apply.enabled`` is literally true and
    ``standing_apply.approval.status`` is APPROVED. Anything unreadable, missing or malformed disarms: this guard
    must never act because a file was absent or half-written.
    """
    cfg = {"armed": False, "active": False, "armed_by": None, "armed_at": None, "standing_enabled": False,
           "approval": None, "trigger_pct": None, "target_pct": None, "rules": str(rules_path)}
    try:
        doc = json.loads(Path(rules_path).read_bytes())
    except (OSError, ValueError) as exc:
        cfg["error"] = f"rules_unreadable:{type(exc).__name__}"
        return cfg
    pa = doc.get("pressure_act") if isinstance(doc, dict) else None
    sa = doc.get("standing_apply") if isinstance(doc, dict) else None
    sa = sa if isinstance(sa, dict) else {}
    approval = sa.get("approval") if isinstance(sa.get("approval"), dict) else {}
    pressure = sa.get("pressure") if isinstance(sa.get("pressure"), dict) else {}
    cfg["armed"] = isinstance(pa, dict) and pa.get("armed") is True
    cfg["armed_by"] = (pa or {}).get("armed_by") if isinstance(pa, dict) else None
    cfg["armed_at"] = (pa or {}).get("armed_at") if isinstance(pa, dict) else None
    cfg["standing_enabled"] = sa.get("enabled") is True
    cfg["approval"] = approval.get("status")
    cfg["trigger_pct"] = pressure.get("trigger_pct")
    cfg["target_pct"] = pressure.get("target_pct")
    cfg["active"] = bool(cfg["armed"] and cfg["standing_enabled"] and approval.get("status") == "APPROVED")
    if cfg["armed"] and not cfg["active"]:
        cfg["why_not_active"] = ("standing_apply disabled" if not cfg["standing_enabled"]
                                 else "standing_apply approval not APPROVED")
    return cfg


def _cleaner_argv(*, rules_path: Path, state_root: str | None, extra: list[str]) -> list[str]:
    py = venv_python(ROOT)
    argv = [py if Path(py).exists() else sys.executable, str(CLEANER), "--standing", "--rules", str(rules_path)]
    if state_root:
        argv += ["--state-root", str(state_root)]
    return argv + extra


def _dry_run_quote(stdout: str) -> dict | None:
    """Parse `disk_hygiene.py --dry-run`'s printed report: one ``DRY-RUN {json}`` line (lane_last_receipt:389)."""
    for line in (stdout or "").splitlines():
        if line.startswith("DRY-RUN "):
            try:
                doc = json.loads(line[len("DRY-RUN "):])
            except ValueError:
                continue
            return doc if isinstance(doc, dict) else None
    # --only-if-above below threshold prints a plain JSON object instead (disk_hygiene.py:_below_threshold).
    try:
        doc = json.loads((stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return doc if isinstance(doc, dict) else None


# disk_hygiene.py's LANE_ID (line 85). A preview that does not carry it is not this cleaner's preview; a test asserts
# the two constants stay equal, so renaming the lane cannot silently turn every apply into a refusal, or vice versa.
CLEANER_DRY_RUN_LANE = "disk-hygiene"
# Any of these, at any depth, is the cleaner saying no. `skipped` is deliberately absent: the native report carries a
# skipped list on a perfectly good run.
_REFUSAL_KEYS = ("refused", "refusal", "denied", "aborted", "blocked", "error", "errors")


def _refusal_signal(node: object, depth: int = 0) -> tuple[str, object] | None:
    """The first refusal signal anywhere in a preview envelope, or None.

    Recursive on purpose: the native envelope is nested (`summary.totals`), and a refusal placed inside it was invisible
    to the flat check — `{"dry_run": true, "summary": {"refused": "manifest_stale", "totals": {"candidates": 1}}}`
    still constructed an apply request (cx-openai-3, 4e4-F6 boundary observation).
    """
    if depth > 5:
        return None
    if isinstance(node, dict):
        if node.get("ok") is False:
            return ("ok", node.get("error") or "dry_run_not_ok")
        for key in _REFUSAL_KEYS:
            if key in node and node[key] not in (None, False, "", [], {}, 0):
                return (key, node[key])
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = _refusal_signal(child, depth + 1)
        if found:
            return found
    return None


def _recognised_dry_run(quote: object) -> tuple[bool, str]:
    """Is this a COMPLETE cleaner dry-run envelope we can positively recognise as a clean success?

    Anything less is not an apply. cx-openai-3 F6: `{"candidates": 1}`, a nested partial and even
    `{"candidates": 1, "refused": "manifest_stale"}` each used to reach the apply boundary, because the parser accepted any
    dict or a loose fallback. A refusal signal inside a zero-exit preview is the dangerous shape: the status looks
    successful.

    The accepted shape is the one `lane_last_receipt.dry_run_report` actually emits for this cleaner
    (`dry_run`, `lane_id`, `would_write_receipt`, `would_write`, `summary.totals`). A dict that merely contains the right
    numbers is not a recognised envelope — the cleaner cannot produce a success without those fields, so anything that
    omits them is a shape we do not understand, and the answer is no apply.
    """
    if not isinstance(quote, dict):
        return False, "dry_run_not_a_mapping"
    signal = _refusal_signal(quote)
    if signal:
        key, value = signal
        if key == "refused":                 # keep the operator-facing wording stable for the common case
            return False, f"dry_run_refused:{str(value)[:120]}"
        if key == "ok":                      # keep the cleaner's own words
            return False, str(value or "dry_run_not_ok")[:200]
        return False, f"dry_run_{key}:{str(value)[:160]}"
    if quote.get("outcome") == "below_threshold":
        return True, ""                      # a recognised non-apply outcome; handled by the caller
    if quote.get("dry_run") is not True:
        return False, "dry_run_envelope_missing"
    if quote.get("lane_id") != CLEANER_DRY_RUN_LANE:
        return False, "dry_run_lane_unrecognised"
    if not isinstance(quote.get("would_write"), list):
        return False, "dry_run_would_write_missing"
    receipt = quote.get("would_write_receipt")
    if not isinstance(receipt, str) or not receipt.strip():
        return False, "dry_run_receipt_missing"
    summary = quote.get("summary")
    totals = summary.get("totals") if isinstance(summary, dict) else None
    if not isinstance(totals, dict):
        return False, "dry_run_totals_missing"
    candidates = totals.get("candidates")
    if isinstance(candidates, bool) or not isinstance(candidates, int) or candidates < 0:
        return False, "dry_run_candidates_invalid"
    return True, ""


def run_cleaner(*, rules_path: Path, state_root: str | None, trigger_pct: float, target_pct: float | None,
                timeout: float = 3600.0, recheck_armed: Callable[[], dict] | None = None) -> dict:
    """Dry-run the reviewed cleaner, quote the selection, then apply exactly that class of item — or refuse.

    Deletion is the cleaner's, under its reviewed standing rules S/T/W/C/R and its own caps. This function only
    decides whether to invoke it and records what it reported; it never touches a path itself.
    """
    out: dict = {"cleaner": str(CLEANER)}
    # F4: the effect-owning helper is not allowed to rely on its caller. With no recheck supplied it reads the rules
    # file itself, so a direct call cannot construct a mutation request for a disarmed guard — and it does not even
    # preview, because a disarmed guard has nothing to do.
    if recheck_armed is None:
        recheck_armed = lambda: act_config(rules_path)  # noqa: E731
    try:
        armed_now = recheck_armed()
    except Exception as exc:  # noqa: BLE001
        return {**out, "decision": "refused_disarmed", "error": f"pressure_act_unreadable_before_apply:{type(exc).__name__}"}
    if not isinstance(armed_now, dict) or armed_now.get("active") is not True:
        return {**out, "decision": "refused_disarmed", "error": "pressure_act_disarmed_before_apply",
                "why_not_active": (armed_now or {}).get("why_not_active") if isinstance(armed_now, dict) else None}
    if not CLEANER.is_file():
        return {**out, "decision": "error", "error": "disk_hygiene.py missing"}
    plan_argv = _cleaner_argv(rules_path=rules_path, state_root=state_root,
                              extra=["--dry-run", "--report", "--only-if-above", f"{trigger_pct:g}"])
    plan = _exec(plan_argv, timeout=timeout)
    quote = _dry_run_quote(plan["stdout"])
    out["dry_run"] = {"rc": plan["_rc"], "error": plan["error"]}
    if plan["error"] or quote is None:
        out["decision"] = "error"
        out["error"] = plan["error"] or "dry_run_output_unparseable"
        out["stderr_tail"] = (plan["stderr"] or "")[-400:]
        return out
    recognised, why = _recognised_dry_run(quote)
    if not recognised:
        out["decision"] = "error"
        out["error"] = why
        return out
    totals = quote.get("summary", {}).get("totals") if isinstance(quote.get("summary"), dict) else None
    totals = totals if isinstance(totals, dict) else quote
    candidates = int(totals.get("candidates") or 0)
    out["selection"] = {"candidates": candidates,
                        "reclaimable_bytes": totals.get("reclaimable_bytes"),
                        "reclaimable_gb": totals.get("reclaimable_gb")}
    if plan["_rc"] != 0:
        # A failed preview must never become a mutation request (cx-openai-4 R2): the exit status is not a detail,
        # it is the cleaner telling us it did not complete the plan.
        out["decision"] = "error"
        out["error"] = f"dry_run_failed_rc_{plan['_rc']}"
        return out
    if quote.get("outcome") == "below_threshold":
        out["decision"] = "below_threshold"
        return out
    if candidates <= 0:
        # Refuse: the reviewed rules selected nothing. Never improvise a different rule set here.
        out["decision"] = "refused_nothing_eligible"
        return out
    # R1: the arming switch is re-read at the LAST moment before the exec boundary. `main()` cached the
    # activation before the preview ran; an operator who disarms during a long preview must get a refusal,
    # not an apply. Nothing below this point may construct the mutation argv for a disarmed guard.
    if recheck_armed is not None:
        try:
            now_act = recheck_armed()
        except Exception as exc:  # noqa: BLE001 - an unreadable switch is a refusal, never an apply
            out["decision"] = "refused_disarmed"
            out["error"] = f"pressure_act_unreadable_before_apply:{type(exc).__name__}"
            return out
        if not isinstance(now_act, dict) or now_act.get("active") is not True:
            out["decision"] = "refused_disarmed"
            out["error"] = "pressure_act_disarmed_before_apply"
            out["why_not_active"] = (now_act or {}).get("why_not_active") if isinstance(now_act, dict) else None
            return out
    env = dict(os.environ)
    env.setdefault(RUN_ID_ENV, "disk_pressure_guard-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    apply_argv = _cleaner_argv(rules_path=rules_path, state_root=state_root,
                               extra=["--apply", "--only-if-above", f"{trigger_pct:g}"]
                               + (["--until-target", f"{target_pct:g}"] if isinstance(target_pct, (int, float)) else []))
    res = _exec(apply_argv, timeout=timeout, env=env)
    applied: dict | None = None
    for line in reversed((res["stdout"] or "").strip().splitlines()):
        try:
            applied = json.loads(line)
            break
        except ValueError:
            continue
    out["apply"] = {"rc": res["_rc"], "error": res["error"],
                    "result": applied if isinstance(applied, dict) else None,
                    "stderr_tail": (res["stderr"] or "")[-400:] or None}
    if res["error"] or not isinstance(applied, dict):
        out["decision"] = "error"
        out["error"] = res["error"] or ("apply_output_unparseable:" + (res["stderr"] or "").strip()[-200:]
                                        if res["stderr"] else "apply_output_unparseable")
        return out
    if res["_rc"] != 0 or applied.get("ok") is False or applied.get("error"):
        # A cleaner that failed is not a cleaner that applied (cx-openai-4 R3): a non-zero exit or a structured
        # failure shape must never be reported as success.
        out["decision"] = "error"
        out["error"] = (f"apply_failed_rc_{res['_rc']}" if res["_rc"] != 0
                        else str(applied.get("error") or "cleaner_reported_not_ok")[:200])
        return out
    if applied.get("outcome") == "below_threshold":
        out["decision"] = "below_threshold"
        out["apply"] = {**(out.get("apply") or {}), "result": applied}
        return out
    if applied.get("removed") in (None, "") and applied.get("reclaimed_bytes") in (None, ""):
        out["decision"] = "error"
        out["error"] = "apply_result_without_a_removal_count"
        return out
    out["reclaimed_bytes"] = int(applied.get("reclaimed_bytes") or 0)
    out["reclaimed_gb"] = applied.get("reclaimed_gb")
    out["removed"] = applied.get("removed")
    out["refused"] = applied.get("refused")
    out["decision"] = "refused" if applied.get("refused") else "applied"
    return out



def notify(text: str) -> str:
    try:
        from telegram_alert import send_telegram  # noqa: PLC0415

        ok = send_telegram(text, message_class="operator_alert", priority="P1", producer="disk_pressure_guard")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting must never raise here
        return f"error:{type(exc).__name__}"


#: The lane's proof-of-run. config/lane_registry.json declares this path as the
#: lane's output_signal, and evaluate_lane() derives LIVE/SLOW/SILENT from THIS
#: FILE'S MTIME -- not from the unit's exit code (AGENTS §0 rule 8: exit 0 is not
#: evidence). A lane declared without a receipt evaluates SILENT forever, which
#: is the stdout-only-monitor defect: 24 scheduled monitors in this repo compute
#: a verdict, print it to a log nobody reads, and exit 0.
RECEIPT = ROOT / "logs" / "disk_pressure_guard_receipts.jsonl"


def _write_receipt(payload: dict) -> str:
    """Append one line per run. Never raises.

    A receipt-write failure must not abort the reclaim the operator actually
    needs -- same reasoning as notify(). Report it in the payload instead.
    """
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        return "written"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--used-pct",
        type=float,
        default=DEFAULT_USED_PCT,
        help=f"act at or above this %% used (default {DEFAULT_USED_PCT})",
    )
    ap.add_argument("--path", default="/")
    ap.add_argument("--rules", default=str(DEFAULT_RULES), help="rules file holding the operator's pressure_act switch")
    ap.add_argument("--state-root", default=None, help="passed through to the cleaner's receipts (default: its own resolver)")
    ap.add_argument(
        "--dry-run", action="store_true", help="report and plan only; never triggers the cleaner (kept for callers)"
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    used, free, total = disk_used_pct(a.path)
    over = used >= a.used_pct
    act = act_config(Path(a.rules))
    # `--dry-run` reports: it asks for plans and never triggers an apply, even when the operator has armed the switch.
    acting = bool(over and act["active"] and not a.dry_run)
    out: dict = {
        "schema": "DiskPressureGuard@v1",
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": a.path,
        "used_pct": round(used, 2),
        "free": _fmt_gb(free),
        "trigger_pct": a.used_pct,
        "over_threshold": over,
        "dry_run": bool(a.dry_run),
        "pressure_act": {k: act.get(k) for k in ("armed", "active", "standing_enabled", "approval", "rules",
                                                 "why_not_active", "error", "armed_by", "armed_at") if act.get(k) is not None},
    }

    if over:
        if acting:
            out["cleaner"] = run_cleaner(rules_path=Path(a.rules), state_root=a.state_root, trigger_pct=a.used_pct,
                                         recheck_armed=lambda: act_config(Path(a.rules)),
                                         target_pct=act.get("target_pct"))
        else:
            out["enforcer"] = run_enforcer(dry_run=a.dry_run)
        used_after, free_after, _ = disk_used_pct(a.path)
        out["used_pct_after"] = round(used_after, 2)
        out["free_after"] = _fmt_gb(free_after)
        # Signed change in free space observed across the plan/act call -- only the cleaner's apply reclaims, and
        # its own receipt carries the bytes it attributes to itself; anything else here is unrelated host activity.
        out["free_space_delta_observed_gb"] = round((free_after - free) / (1024**3), 2)

    # State measured AFTER the plan call: if free space recovered by any means, the
    # operator should be told the condition recovered, not that it is still bad.
    final_used = out.get("used_pct_after", out["used_pct"])
    state = "PRESSURE" if final_used >= a.used_pct else "OK"
    try:
        from lib.alert_condition_state import observe  # noqa: PLC0415

        obs = observe(
            CONDITION_KEY,
            state,
            alertable=(state == "PRESSURE"),
            min_realert_minutes=REALERT_MINUTES,
            extra={"used_pct": final_used, "free": out.get("free_after", out["free"])},
        )
        out["condition"] = {"action": obs.get("action"), "notify": bool(obs.get("notify"))}
    except Exception as exc:  # noqa: BLE001
        out["condition"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    # 2026-10-27: the guard removes nothing and requests no removal (AGENTS.md §24.12). 2026-11-03: when the
    # operator arms pressure_act it TRIGGERS the reviewed cleaner, whose own receipt attributes every removal.
    cleaner = out.get("cleaner") or {}
    decision = cleaner.get("decision")
    if acting:
        if decision == "applied":
            out["removal"] = (f"disk_hygiene.py --standing (reviewed rules S/T/W/C/R): removed "
                              f"{cleaner.get('removed')} item(s), reclaimed {cleaner.get('reclaimed_gb')} GB")
        elif decision == "refused_nothing_eligible":
            out["removal"] = "none: the reviewed cleaner selected nothing eligible (refused_nothing_eligible)"
        elif decision == "below_threshold":
            out["removal"] = "none: usage was at or below the trigger when the cleaner checked"
        else:
            out["removal"] = f"none: the cleaner did not complete ({decision})"
    else:
        out["removal"] = "none (AGENTS.md §24.12: the disk-hygiene lane owns reclaim)"
    if out.get("condition", {}).get("notify"):
        line = f"💾 Disk {final_used:.1f}% used ({out.get('free_after', out['free'])} free) — trigger {a.used_pct:.0f}%"
        if acting:
            if decision == "applied":
                line += (f"\npressure act: ARMED — cleaner removed {cleaner.get('removed')} item(s), reclaimed "
                         f"{cleaner.get('reclaimed_gb')} GB")
            elif decision == "refused_nothing_eligible":
                line += ("\npressure act: ARMED — the reviewed cleaner selected NOTHING eligible; a person must "
                         "review (`python3 scripts/disk_hygiene.py --report`)")
            else:
                line += f"\npressure act: ARMED — cleaner decision {decision}; see this guard's receipt"
        else:
            enf = out.get("enforcer") or {}
            line += f"\n{GOVERNED_ROUTE_LINE}"
            if enf and not (enf.get("skipped") or enf.get("error")):
                line += f"\nenforcer plan (report only): {enf.get('_would_remove_count', 0)} old release(s) listed"
        out["telegram"] = notify(line)

    out["receipt"] = _write_receipt(out)
    print(json.dumps(out, indent=2))
    # Exit 0 whenever the guard DID ITS JOB, even if the disk is still over the
    # threshold. Returning 1 for "still over" made systemd mark the unit failed
    # on a run that worked perfectly -- it reclaimed, it paged, it wrote its
    # receipt -- and made a genuine crash indistinguishable from normal
    # operation. That is the same three-way collapse as
    # pipeline_freshness_monitor._age_days_table returning None for "absent",
    # "errored" and "empty" alike, which cost ~1,800 false pages a day.
    #
    # The operator signal for "reclaim was not enough" is the Telegram alert and
    # the receipt, both of which already fired. The exit code's only job is to
    # say whether the PROCESS succeeded (AGENTS §0 rule 8: exit 0 is not
    # evidence of work -- so it must not be overloaded as evidence of state).
    if acting:
        # The cleaner's own convention: a refusal is a failed run, a completed run is not.
        return 1 if decision in ("error", "refused") else 0
    enf = out.get("enforcer") or {}
    if enf.get("skipped") or enf.get("error"):
        return 1  # the enforcer could not run: a real failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
