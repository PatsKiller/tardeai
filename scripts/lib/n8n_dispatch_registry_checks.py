"""n8n_dispatch_registry_checks.py — CI rails for registry `dispatch` blocks (n8n maturity B5 follow-up).

Two pure checks over config/lane_registry.json rows, wired into scripts/check_lane_registry.py:

  * `class_policy_findings` — every row with a `dispatch` block names a `retry_policy` that exists in
    config/n8n_retry_policies.json and whose `permitted_classes` include the row's `dispatch.class`. These are
    the class rails `n8n_retry_policy.class_verdict` enforces at run time (a non-permitted class is terminal on
    the first failure); CI makes the mismatch visible before a lane is dispatched instead of after a dead letter.
  * `cron_mismatch_findings` — for a row with `dispatch.cron` whose scheduler is still the host crontab and whose
    line is live, the dispatch expressions equal the live line's schedule (design 02 §2: "must equal the live
    crontab schedule while scheduler.kind=cron"). No crontab (CI runners) or no live line: skipped, never failed.

Findings are dicts {code, lane_id, detail}. Authority: READ_ONLY_ADVISORY (pure functions).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

CODE_MALFORMED = "DISPATCH_BLOCK_MALFORMED"
CODE_UNKNOWN_POLICY = "DISPATCH_UNKNOWN_RETRY_POLICY"
CODE_UNKNOWN_CLASS = "DISPATCH_UNKNOWN_CLASS"
CODE_CLASS_NOT_PERMITTED = "DISPATCH_CLASS_NOT_PERMITTED"
CODE_CRON_MISMATCH = "DISPATCH_CRON_MISMATCH"


def _finding(code: str, lane_id: Any, detail: str) -> dict[str, str]:
    return {"code": code, "lane_id": str(lane_id or "?"), "detail": detail[:200]}


def dispatch_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Rows that carry a `dispatch` key at all (any value: a malformed block is still a block)."""
    return [r for r in rows if isinstance(r, Mapping) and "dispatch" in r]


def class_policy_findings(rows: Iterable[Mapping[str, Any]], policies: Any,
                          classes: Optional[Iterable[str]] = None) -> list[dict[str, str]]:
    """`policies` is a loaded `n8n_retry_policy.RetryPolicies` (its `.policies` map is read; no fallback to the
    default policy: an unknown name is a finding, exactly as `RetryPolicies.get` treats it as never-retry)."""
    if classes is None:
        from scripts.lib.n8n_retry_policy import CLASSES as classes  # noqa: N811
    known_classes = frozenset(classes)
    named = getattr(policies, "policies", None) or {}
    out: list[dict[str, str]] = []
    for row in dispatch_rows(rows):
        lane = row.get("lane_id")
        block = row.get("dispatch")
        if not isinstance(block, Mapping):
            out.append(_finding(CODE_MALFORMED, lane, "dispatch is not an object"))
            continue
        klass, pol_name = block.get("class"), block.get("retry_policy")
        if not isinstance(klass, str) or not isinstance(pol_name, str) or not pol_name:
            out.append(_finding(CODE_MALFORMED, lane, f"dispatch.class={klass!r} dispatch.retry_policy={pol_name!r}"))
            continue
        if klass not in known_classes:
            out.append(_finding(CODE_UNKNOWN_CLASS, lane, f"class {klass!r} not in {sorted(known_classes)}"))
            continue
        policy = named.get(pol_name)
        if policy is None:
            out.append(_finding(CODE_UNKNOWN_POLICY, lane, f"retry_policy {pol_name!r} not in {sorted(named)}"))
            continue
        permitted = frozenset(getattr(policy, "permitted_classes", ()) or ())
        if klass not in permitted:
            out.append(_finding(CODE_CLASS_NOT_PERMITTED, lane,
                                f"class {klass!r} not permitted by retry_policy {pol_name!r} {sorted(permitted)}"))
    return out


def _schedule_of(line: str) -> Optional[str]:
    """The schedule part of one crontab line: 5 fields, or a single @macro. None when it is not a job line."""
    parts = str(line or "").split()
    if not parts:
        return None
    if parts[0].startswith("@"):
        return parts[0]
    if len(parts) < 6:
        return None
    return " ".join(parts[:5])


def cron_mismatch_findings(rows: Iterable[Mapping[str, Any]],
                           cron_lines: Optional[Iterable[str]]) -> list[dict[str, str]]:
    """`cron_lines` are the active crontab lines (lane_registry.discover_cron expressions). None or empty means
    no crontab is readable (CI): nothing is compared. A row whose marker matches no live line is skipped."""
    lines = [str(x) for x in (cron_lines or []) if str(x).strip()]
    if not lines:
        return []
    out: list[dict[str, str]] = []
    for row in dispatch_rows(rows):
        block = row.get("dispatch")
        sched = row.get("scheduler") or {}
        if not isinstance(block, Mapping) or not isinstance(sched, Mapping) or sched.get("kind") != "cron":
            continue
        want = block.get("cron")
        if not isinstance(want, list) or not want:
            continue
        marker = str(sched.get("match") or sched.get("expression") or "")
        if not marker:
            continue
        live = sorted({s for s in (_schedule_of(ln) for ln in lines if marker in ln) if s})
        if not live:
            continue
        declared = sorted({" ".join(str(e).split()) for e in want})
        if declared != live:
            out.append(_finding(CODE_CRON_MISMATCH, row.get("lane_id"),
                                f"dispatch.cron {declared} != live crontab {live}"))
    return out
