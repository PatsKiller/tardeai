"""Worker-pool lane runners for tax_retirement, system_ops and custom_domain.

These three lanes were declared on 2026-07-05 (config/hermes_research_worker_lanes.yaml)
but no module ever called worker_pool.register_lane_runner for them, so every
hourly pool run reported them ``skipped: no_runner`` with exit 0 until
2026-10-15. Each runner below reuses an EXISTING producer — no new table, no new
external host, no LLM call:

  tax_retirement  coverage.taxes_findings + coverage.retirement_findings
                  (term recurrence over news_articles + hermes_research_intelligence,
                  the adapters behind hermes_discovery_coverage_adapters.py)
                  → TOPIC_CANDIDATEs pinned to domain taxes / retirement
  system_ops      coverage.system_ops_findings (latest failing/stale
                  system_health_checks components) → TOPIC_CANDIDATEs pinned to
                  domain system_ops, behind a source-freshness probe that
                  follows the system-health-agent step in
                  config/health_tick_steps.json (quiet outside that step's
                  weekdays and hours is not a stale writer)
  custom_domain   the operator's custom research domains
                  (config/hermes_custom_research_domains.yaml) that the lane's
                  allowed_domains admit: their classification_keywords drive the
                  same term-recurrence scan, their denylist_terms and
                  blocked_source_types filter rows

Contract (worker_pool.register_lane_runner): runner(lane_cfg, *, dry_run) ->
list of inbox.upsert_candidate payload dicts. Runners are READ-ONLY; the pool
owns every write (candidates only, through its lane + do-no-harm gates;
promotion is structurally impossible there).

Fail loud, never silently empty: every DB read here is strict (a failed read
raises → the pool reports runner_error → non-zero exit), and system_ops refuses
to report "nothing failing" from a health table that is not being written.

Citations: the two sensitive lanes (requires_citations) keep only evidence that
carries a real source URL; a payload left with none is dropped here rather than
reaching the inbox on a source name alone.

LLM review: none here. Candidates in llm_review_required domains go through the
existing governed review lane (scripts/hermes_discovery_llm_review.py, daily
cloud cap in config/hermes_discovery_schedule.json) — never from this pool.

Advisory-only: never imports broker/execution modules.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import coverage, domains, worker_pool

WINDOW_DAYS = 7               # term-recurrence look-back (lanes run daily)
MIN_MATCHES = 2               # a term must recur to become a candidate
# The only writer of system_health_checks is this health_tick step. Freshness
# is "last write is at or after the latest fire of that step that has had one
# grace interval to finish." Grace and the window come from the step. There is
# no wall-clock hour limit: a larger constant would hide a stall inside the
# writer's own window (Tue 14:00 ET with a last write at Tue 08:00).
_HEALTH_WRITER_STEP_ID = "system-health-agent"
# Loop bound so a step that is never due cannot spin. Not an allowed age.
_DEADLINE_SEARCH_DAYS = 8

# blocked_source_types (custom domain yaml) → news_articles.source substrings
SOURCE_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "social": ("stocktwits", "reddit", "twitter", "x.com", "truth social",
               "facebook", "tiktok"),
    "forum": ("forum", "reddit"),
}


def _cited_only(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep evidence items with an http(s) URL; drop payloads left with none."""
    kept = []
    for p in payloads:
        ev = [e for e in (p.get("evidence") or [])
              if isinstance(e, dict) and str(e.get("url") or "").startswith(("http://", "https://"))]
        if ev:
            kept.append({**p, "evidence": ev})
    return kept


def _interleave(*streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin merge so one domain cannot crowd the other out of the cap."""
    out: list[dict[str, Any]] = []
    for i in range(max((len(s) for s in streams), default=0)):
        for s in streams:
            if i < len(s):
                out.append(s[i])
    return out


def _cap(lane_cfg: dict[str, Any], default: int = 5) -> int:
    return max(1, int(lane_cfg.get("max_candidates_per_run") or default))


# ── tax_retirement ───────────────────────────────────────────────────────────

def tax_retirement_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """taxes + retirement term-recurrence adapters, cited rows only."""
    limit = _cap(lane_cfg)
    taxes = _cited_only(coverage.taxes_findings(days=WINDOW_DAYS, limit=limit,
                                                min_matches=MIN_MATCHES, strict=True))
    retirement = _cited_only(coverage.retirement_findings(
        days=WINDOW_DAYS, limit=limit, min_matches=MIN_MATCHES, strict=True))
    return _interleave(taxes, retirement)[:limit]


# ── system_ops ───────────────────────────────────────────────────────────────

def _system_health_last_write() -> datetime | None:
    rows = coverage._rows("SELECT max(updated_at) AS last FROM system_health_checks",
                          strict=True)
    last = (rows[0] or {}).get("last") if rows else None
    if last is None:
        return None
    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace("Z", "+00:00"))
    return last if last.tzinfo else last.replace(tzinfo=timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cron_zone() -> ZoneInfo:
    """Hours and weekdays in health_tick_steps.json are cron-zone clocks.

    Host local time is not that clock, and UTC hours are not either
    (Fri 20:55 ET is Sat 01:55 UTC while EST is in force).
    """
    name = os.environ.get("TRADEAI_CRON_TZ") or "America/New_York"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RuntimeError(
            f"TRADEAI_CRON_TZ {name!r} is not a usable zone — cannot judge "
            "system_health freshness on the writer clock"
        ) from exc


def _health_tick_module():
    """health_tick lives in scripts/. Cron puts that directory on sys.path[0];
    a repo-root import uses the scripts package. Either is the same module."""
    try:
        import health_tick
        return health_tick
    except ImportError:
        pass
    try:
        from scripts import health_tick
        return health_tick
    except ImportError as exc:
        raise RuntimeError(
            "health_tick is not importable — cannot judge system_health freshness "
            "from the writer schedule"
        ) from exc


def _load_health_writer_schedule() -> tuple[dict[str, Any], int]:
    """The system-health-agent step and the table tick.

    A missing step or an unreadable table raises. An unreadable schedule must
    not look like a fresh health table.
    """
    ht = _health_tick_module()
    try:
        table = ht.load_table(ht.DEFAULT_TABLE)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "health_tick_steps.json is unreadable — cannot judge system_health freshness"
        ) from exc
    tick = int(table.get("tick_minutes") or 0)
    if tick <= 0:
        raise RuntimeError(
            "health_tick_steps.json has no tick_minutes — cannot judge system_health freshness"
        )
    for step in table["steps"]:
        if str(step.get("step_id") or "") == _HEALTH_WRITER_STEP_ID:
            return step, tick
    raise RuntimeError(
        f"health_tick step {_HEALTH_WRITER_STEP_ID} is missing — cannot tell a quiet "
        "schedule from a stalled system_health writer"
    )


def _writer_grace(step: dict[str, Any]) -> timedelta:
    """How long after a due tick the write may still be in flight.

    The longer of one cadence and the step timeout, both read from the step.
    This is a completion allowance, not a freshness limit.
    """
    cadence_s = int(step["cadence_minutes"]) * 60
    timeout_s = int(step.get("timeout_s") or 0)
    grace_s = max(cadence_s, timeout_s)
    if grace_s <= 0:
        raise RuntimeError(
            f"health_tick step {_HEALTH_WRITER_STEP_ID} has no cadence — cannot judge freshness"
        )
    return timedelta(seconds=grace_s)


def _latest_due_at_or_before(
    step: dict[str, Any], tick_minutes: int, horizon: datetime,
) -> datetime | None:
    """Latest cron tick at or before ``horizon`` on which this step is due.

    ``horizon`` is in the cron zone. The walk calls health_tick.step_is_due so
    this gate cannot grow a second reading of the cron fields.
    """
    ht = _health_tick_module()
    tick = ht.snap_to_tick(horizon, tick_minutes)
    if tick > horizon:
        tick -= timedelta(minutes=tick_minutes)
    stop = horizon - timedelta(days=_DEADLINE_SEARCH_DAYS)
    while tick >= stop:
        if ht.step_is_due(step, tick, tick_minutes):
            return tick
        tick -= timedelta(minutes=tick_minutes)
    return None


def system_health_deadline(now_utc: datetime | None = None) -> tuple[datetime, dict[str, Any]]:
    """UTC instant the latest writer fire must have landed by.

    Deadline = the latest due tick at or before ``now - grace``. A write at
    that tick is still fresh. No due tick inside the search bound raises.
    """
    step, tick_minutes = _load_health_writer_schedule()
    now = now_utc if now_utc is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    horizon = now.astimezone(_cron_zone()) - _writer_grace(step)
    due = _latest_due_at_or_before(step, tick_minutes, horizon)
    if due is None:
        raise RuntimeError(
            f"no scheduled fire of {_HEALTH_WRITER_STEP_ID} within {_DEADLINE_SEARCH_DAYS} days "
            "of the grace horizon — refusing to treat system_health_checks as fresh"
        )
    return due.astimezone(timezone.utc), step


def system_ops_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Failing/stale health-check components. Zero payloads is a healthy
    result ONLY when the health table is being written — otherwise raise."""
    last = _system_health_last_write()
    if last is None:
        raise RuntimeError("system_health_checks is empty — cannot tell healthy from unread")
    deadline, step = system_health_deadline(_utc_now())
    if last < deadline:
        raise RuntimeError(
            "system_health_checks last written "
            f"{last.isoformat()} is before the latest due {_HEALTH_WRITER_STEP_ID} fire "
            f"{deadline.isoformat()} "
            f"(weekdays={step.get('weekdays')} hours={step.get('hours')} "
            f"cadence_minutes={step.get('cadence_minutes')}) — health source is stale"
        )
    return coverage.system_ops_findings(limit=_cap(lane_cfg), strict=True)


# ── custom_domain ────────────────────────────────────────────────────────────

def custom_domains_for_lane(lane_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Custom-file domains the lane's allowed_domains admit, with keywords."""
    allowed = set(lane_cfg.get("allowed_domains") or [])
    out = []
    for name, policy in sorted(domains.load_domains().items()):
        if policy.get("source") != "custom":
            continue
        if allowed and name not in allowed:
            continue
        if not policy.get("classification_keywords"):
            continue
        out.append(policy)
    return out


def custom_domain_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Operator custom domains → term recurrence on their own keywords."""
    limit = _cap(lane_cfg)
    policies = custom_domains_for_lane(lane_cfg)
    if not policies:
        raise RuntimeError("no custom research domain with classification_keywords "
                           "is admitted by the custom_domain lane")
    streams = []
    for policy in policies:
        excluded: list[str] = []
        for stype in policy.get("blocked_source_types") or []:
            excluded.extend(SOURCE_TYPE_HINTS.get(str(stype).lower(), ()))
        found = coverage.term_recurrence_findings(
            "custom", policy["classification_keywords"], domain=policy["name"],
            label_prefix=policy["name"].replace("_", " ").title(),
            denylist_terms=policy.get("denylist_terms"),
            exclude_sources=excluded, days=WINDOW_DAYS, limit=limit,
            min_matches=MIN_MATCHES, strict=True)
        for p in found:
            p["meta"]["custom_domain"] = policy["name"]
            if policy.get("llm_review_required"):
                p["meta"]["llm_review_required"] = True
        cite = lane_cfg.get("requires_citations") or policy.get("requires_citation")
        streams.append(_cited_only(found) if cite else found)
    return _interleave(*streams)[:limit]


worker_pool.register_lane_runner("tax_retirement", tax_retirement_runner, replace=True)
worker_pool.register_lane_runner("system_ops", system_ops_runner, replace=True)
worker_pool.register_lane_runner("custom_domain", custom_domain_runner, replace=True)
