"""incident_flood_policy.py — the incident-flood reduction rules (WS1-09, WS3-10, WS3-35; 2026-10-15).

On 2026-10-14 the fan-in held 904 open incidents. 756 came from the failure diagnoser, which reported on itself:
759 escalations for 24 SIEM rows, 714 of them its own policy refusals (deferred_offpeak, lane_daily_call_cap, ...).
The notifier's 24-message daily cap was spent by P1 sends (47 used) before a P2 batch could leave.

Five rules, all pure, applied in this order, each recorded with its reason:

  0. protect      P0 always; a P1 from any source outside ``p1_rule_sources``; any finding whose source, item or
                  detail names a stop, broker, order, position, fill or safety control. Protected findings pass
                  through untouched by every rule below. This is the guarantee the SPCX tests pin.
  1. drop         diagnoser policy refusals and RUN_REFUSED / RUN_SKIPPED_LOCK runs are not incidents.
  2. auto-resolve a run-failure incident on a lane closes when the lane's next run (same mode, when known) ends
                  RUN_DONE exit 0 after the incident was detected.
  3. collapse     diagnoser self-reports collapse to one incident per (lane, failure class).
  3b. demote      a low-confidence diagnoser P1 becomes P2 (only inside a collapse group, so a new item and key).
  4. budget       (notifier) each source may trigger at most N P2 batch messages per day; P1 sends do not count
                  toward the P2 cap. See ``budget_p2``.

``mode`` is ``report_only`` (default) or ``enforce``. Report-only computes everything and the callers publish and
send exactly what they did before; the result is written to their receipts as ``flood_policy``.
Config: config/incident_flood_policy.json; env TRADEAI_INCIDENT_FLOOD_POLICY (path) and
TRADEAI_INCIDENT_FLOOD_POLICY_MODE (mode) override it. A missing or unreadable config is report_only.

AUTHORITY: READ_ONLY_ADVISORY. No send, no write, no ledger mutation.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "incident_flood_policy.json"
SCHEMA = "IncidentFloodPolicyResult@v1"
MODES = ("report_only", "enforce")
DEFAULT_MODE = "report_only"
ENV_PATH = "TRADEAI_INCIDENT_FLOOD_POLICY"
ENV_MODE = "TRADEAI_INCIDENT_FLOOD_POLICY_MODE"
DIAGNOSER = "n8n_failure_diagnosis"
SEV_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def load_policy(env: Optional[dict] = None, path: Optional[Path] = None) -> dict[str, Any]:
    """The policy document with a resolved ``mode``. Never raises: an unreadable file is report_only, no rules."""
    env = os.environ if env is None else env
    p = Path(path or env.get(ENV_PATH) or CONFIG_PATH)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("not an object")
        note = "ok"
    except (OSError, ValueError) as exc:
        doc, note = {}, f"unavailable:{type(exc).__name__}"
    mode = str(env.get(ENV_MODE) or doc.get("mode") or DEFAULT_MODE).strip()
    if mode not in MODES:
        note, mode = f"{note}:bad_mode:{mode}", DEFAULT_MODE
    return {**doc, "mode": mode, "config_path": str(p), "config_note": note}


def enforcing(policy: dict[str, Any]) -> bool:
    return policy.get("mode") == "enforce"


def _rule(policy: dict[str, Any], name: str) -> dict[str, Any]:
    r = policy.get(name)
    return r if isinstance(r, dict) and r.get("enabled") else {}


def _pattern(policy: dict[str, Any]) -> re.Pattern[str]:
    pat = (policy.get("protected") or {}).get(
        "pattern"
    ) or r"(?<![a-z0-9])(stops?|broker|orders?|positions?|safety)(?![a-z0-9])"
    return re.compile(pat, re.I)


def is_protected(f: dict[str, Any], policy: dict[str, Any]) -> Optional[str]:
    """The reason a finding may never be suppressed, or None. Pure.

    Fail-safe: an empty policy (no config) protects every P0/P1 and every stop/broker/safety mention."""
    prot = policy.get("protected") or {}
    sev = str(f.get("severity") or "")
    if sev in (prot.get("always_severities") or ["P0"]) or sev == "P0":
        return f"severity:{sev}"
    src = str(f.get("source") or "")
    if sev == "P1" and src not in (prot.get("p1_rule_sources") or []):
        return f"p1_source:{src}"
    text = " ".join(str(f.get(k) or "") for k in ("source", "item", "detail", "lane", "event_type"))
    m = _pattern(policy).search(text)
    if m:
        return f"pattern:{m.group(0).lower()}"
    return None


def _diag_parts(f: dict[str, Any]) -> tuple[str, str, str]:
    """(lane, event_type, reason) for a diagnoser finding; the fan-in carries them, an older row is parsed."""
    lane = str(f.get("lane") or "")
    if not lane:
        item = str(f.get("item") or "")
        body = item.split(":", 1)[1] if ":" in item else item
        lane = body.rsplit("/", 1)[0] if "/" in body else body
    reason = str(f.get("reason") or "")
    if not reason:
        reason = str(f.get("detail") or "").split(";", 1)[0].strip()
    return lane, str(f.get("event_type") or "UNKNOWN"), reason


def _reason_class(reason: str) -> str:
    """Failure class for a collapse key: the reason without its free-text tail (model_refused:provider_outage)."""
    return reason.split(";", 1)[0].strip() or "unknown"


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _lane_mode(f: dict[str, Any]) -> tuple[str, Optional[str]]:
    """(lane, mode or None) for a run-tied finding."""
    src = str(f.get("source") or "")
    item = str(f.get("item") or "")
    if f.get("lane"):
        return str(f["lane"]), (str(f["mode"]) if f.get("mode") else None)
    if src == "dlq" and item.startswith("dlq:d:"):
        parts = item.split(":")  # dlq:d:<lane>:<mode>:<slot>
        if len(parts) >= 5:
            return parts[2], parts[3]
    if src == "runs" and ":" in item:
        return item.rsplit(":", 1)[0], None
    if src == DIAGNOSER:
        return _diag_parts(f)[0], None
    return "", None


def _is_refusal(f: dict[str, Any], rule: dict[str, Any]) -> Optional[str]:
    src = str(f.get("source") or "")
    if src in (rule.get("sources") or []):
        reason = _diag_parts(f)[2] if src == DIAGNOSER else str(f.get("reason") or "")
        if reason in (rule.get("reasons") or []):
            return f"policy_refusal:{reason}"
    item = str(f.get("item") or "")
    for st in rule.get("run_states") or []:
        if item.endswith(f":{st}") or str(f.get("run_state") or "") == st:
            return f"run_state:{st}"
    return None


def _auto_resolve_eligible(f: dict[str, Any], rule: dict[str, Any]) -> bool:
    src = str(f.get("source") or "")
    if src not in (rule.get("sources") or []):
        return False
    if src == DIAGNOSER:
        _, et, reason = _diag_parts(f)
        return et in (rule.get("diagnoser_event_types") or []) or any(
            reason.startswith(p) for p in rule.get("diagnoser_reason_prefixes") or []
        )
    if src == "dlq":
        return str(f.get("item") or "").startswith("dlq:d:")  # a dead slot, never an open breaker
    return src == "runs" and not str(f.get("item") or "").startswith("executor:")


def latest_successes(ledger: Optional[Path], *, until: Optional[datetime] = None) -> dict[tuple[str, str], str]:
    """{(lane, mode): newest finished_at of a RUN_DONE exit-0 run}, plus (lane, "*") for any mode.

    Read-only (sqlite mode=ro). A missing ledger or table is an empty map, never an error."""
    out: dict[tuple[str, str], str] = {}
    if ledger is None or not Path(ledger).exists():
        return out
    conn = sqlite3.connect(f"{Path(ledger).resolve().as_uri()}?mode=ro", uri=True, timeout=3)
    try:
        rows = conn.execute(
            "SELECT lane_id, mode, MAX(finished_at) FROM runs WHERE state='RUN_DONE' AND COALESCE(exit_code,0)=0"
            " AND finished_at IS NOT NULL" + (" AND finished_at <= ?" if until else "") + " GROUP BY lane_id, mode",
            ((until.isoformat(),) if until else ()),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return successes_from_rows({"lane_id": r[0], "mode": r[1], "finished_at": r[2]} for r in rows)


def successes_from_rows(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for r in rows:
        lane, mode, fin = str(r.get("lane_id") or ""), str(r.get("mode") or ""), str(r.get("finished_at") or "")
        if not lane or not fin:
            continue
        for k in ((lane, mode), (lane, "*")):
            if fin > out.get(k, ""):
                out[k] = fin
    return out


def apply_fanin_policy(
    findings: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    successes: Optional[dict[tuple[str, str], str]] = None,
) -> dict[str, Any]:
    """Rules 0-3b over the fan-in's findings. Pure; never mutates the input.

    Returns {findings (the reduced list), dropped, auto_resolved, collapsed, demoted, protected, before, after}.
    The caller publishes ``findings`` only when ``enforcing(policy)``."""
    successes = successes or {}
    drop_rule = _rule(policy, "drop_policy_refusals")
    ar_rule = _rule(policy, "auto_resolve")
    col_rule = _rule(policy, "collapse")
    dem_rule = _rule(policy, "demote_low_confidence_p1")
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in findings:
        why = is_protected(f, policy)
        if why:
            protected.append(
                {"source": f.get("source"), "item": f.get("item"), "severity": f.get("severity"), "why": why}
            )
            kept.append(f)
            continue
        if drop_rule:
            r = _is_refusal(f, drop_rule)
            if r:
                dropped.append(
                    {"source": f.get("source"), "item": f.get("item"), "severity": f.get("severity"), "rule": r}
                )
                continue
        if ar_rule and _auto_resolve_eligible(f, ar_rule):
            lane, mode = _lane_mode(f)
            fin = successes.get((lane, mode or "*")) if lane else None
            det = _ts(f.get("detected_at"))
            if fin and det is not None and (_ts(fin) or det) > det:
                resolved.append(
                    {
                        "source": f.get("source"),
                        "item": f.get("item"),
                        "severity": f.get("severity"),
                        "rule": f"lane_succeeded:{lane}:{mode or '*'}@{fin}",
                    }
                )
                continue
        if col_rule and str(f.get("source")) in (col_rule.get("sources") or []):
            lane, et, reason = _diag_parts(f)
            groups.setdefault((str(f.get("source")), lane, et), []).append({**f, "_reason": _reason_class(reason)})
            continue
        kept.append(f)
    collapsed: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    for (src, lane, et), members in sorted(groups.items()):
        members.sort(key=lambda m: (SEV_RANK.get(str(m.get("severity")), 9), str(m.get("detected_at") or "")))
        worst = members[0]
        sev = str(worst.get("severity") or "P2")
        reasons = sorted({m["_reason"] for m in members})
        if (
            dem_rule
            and sev == "P1"
            and src in (dem_rule.get("sources") or [])
            and all(
                r in (dem_rule.get("reasons") or [])
                for r in {m["_reason"] for m in members if m.get("severity") == "P1"}
            )
        ):
            demoted.append(
                {"source": src, "item": f"collapse:{lane}/{et}", "from": "P1", "to": dem_rule.get("to", "P2")}
            )
            sev = str(dem_rule.get("to") or "P2")
        first = min(str(m.get("detected_at") or "") for m in members) or worst.get("detected_at")
        row = {
            "source": src,
            "item": f"collapse:{lane}/{et}",
            "severity": sev,
            "detail": f"{len(members)} report(s) {et} on {lane}; reasons {','.join(reasons)}"[:160],
            "detected_at": first,
            "artifact_rel": worst.get("artifact_rel"),
            "store": worst.get("store"),
            "lane": lane,
            "event_type": et,
            "count": len(members),
            "event_keys": [str(m.get("item")) for m in members][:50],
        }
        kept.append(row)
        collapsed.append({"item": row["item"], "severity": sev, "members": len(members), "reasons": reasons})
    return {
        "schema": SCHEMA,
        "mode": policy.get("mode", DEFAULT_MODE),
        "config_note": policy.get("config_note"),
        "findings": kept,
        "before": _counts(findings),
        "after": _counts(kept),
        "dropped": dropped,
        "auto_resolved": resolved,
        "collapsed": collapsed,
        "demoted": demoted,
        "protected": protected,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sev: dict[str, int] = {}
    by_src: dict[str, int] = {}
    for r in rows:
        by_sev[str(r.get("severity"))] = by_sev.get(str(r.get("severity")), 0) + 1
        by_src[str(r.get("source"))] = by_src.get(str(r.get("source")), 0) + 1
    return {"open": len(rows), "by_severity": by_sev, "by_source": dict(sorted(by_src.items(), key=lambda x: -x[1]))}


def summary(result: dict[str, Any], *, sample: int = 20) -> dict[str, Any]:
    """The receipt form of a policy result: counts plus a bounded sample of each list (receipts stay small)."""
    return {
        "schema": result["schema"],
        "mode": result["mode"],
        "config_note": result.get("config_note"),
        "applied": result["mode"] == "enforce",
        "before": result["before"],
        "after": result["after"],
        **{
            k: {"n": len(result[k]), "sample": result[k][:sample]}
            for k in ("dropped", "auto_resolved", "collapsed", "demoted", "protected")
        },
    }


# ---------------------------------------------------------------------------------------------------- notifier side


def source_budget(policy: dict[str, Any], source: str) -> Optional[int]:
    """Batches a source may trigger per day, or None when the budget rule is off."""
    rule = _rule(policy, "source_budget")
    if not rule:
        return None
    per = rule.get("per_source") or {}
    return int(per.get(source, rule.get("default_batches_per_day", 4)))


def p1_counts_toward_cap(policy: dict[str, Any]) -> bool:
    """Whether a P1-bearing message spends the P2 daily cap. True (today's behaviour) unless enforcing."""
    rule = _rule(policy, "source_budget")
    if not enforcing(policy) or not rule:
        return True
    return bool(rule.get("p1_counts_toward_p2_cap", False))


def recoveries_count_toward_cap(policy: dict[str, Any]) -> bool:
    """Whether a recovery message spends the P2 daily cap (WS3-11). True today; False when enforcing."""
    rule = _rule(policy, "source_budget")
    if not enforcing(policy) or not rule:
        return True
    return bool(rule.get("recoveries_count_toward_p2_cap", False))


def budget_p2(due: list[dict[str, Any]], triggers_today: dict[str, int], policy: dict[str, Any]) -> dict[str, Any]:
    """Split the due P2 incidents by source budget. Pure.

    Returns {triggering: [incidents whose source still has budget, or protected], riding: [over-budget incidents],
    charge: {source: 1 for each source that triggers this batch}, exhausted: [sources over budget], send: bool}.
    A batch sends only if something triggers it; riding incidents are included in a batch that sends."""
    trig: list[dict[str, Any]] = []
    ride: list[dict[str, Any]] = []
    exhausted: set[str] = set()
    for inc in due:
        src = str(inc.get("source"))
        cap = source_budget(policy, src)
        if cap is None or is_protected(inc, policy) or int(triggers_today.get(src, 0)) < cap:
            trig.append(inc)
        else:
            ride.append(inc)
            exhausted.add(src)
    charge = {str(i.get("source")): 1 for i in trig if not is_protected(i, policy)}
    return {"triggering": trig, "riding": ride, "charge": charge, "exhausted": sorted(exhausted), "send": bool(trig)}


def order_lines(incs: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Protected first, then round-robin by source so one source cannot fill the shown lines. Pure, stable."""
    rule = _rule(policy, "source_budget")
    per = int(rule.get("lines_per_source", 4)) if rule else None
    prot = [i for i in incs if is_protected(i, policy)]
    rest = [i for i in incs if not is_protected(i, policy)]
    by: dict[str, list[dict[str, Any]]] = {}
    for i in rest:
        by.setdefault(str(i.get("source")), []).append(i)
    shown: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    for src in sorted(by):
        lim = per if per is not None else len(by[src])
        shown.extend(by[src][:lim])
        tail.extend(by[src][lim:])
    return prot + shown + tail
