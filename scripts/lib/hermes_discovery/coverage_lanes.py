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
                  domain system_ops, behind a source-freshness probe
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

from datetime import datetime, timedelta, timezone
from typing import Any

from . import coverage, domains, worker_pool

WINDOW_DAYS = 7               # term-recurrence look-back (lanes run daily)
MIN_MATCHES = 2               # a term must recur to become a candidate
SYSTEM_HEALTH_FRESH_HOURS = 48  # system_health_checks must have been written within this

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


def system_ops_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Failing/stale health-check components. Zero payloads is a healthy
    result ONLY when the health table is being written — otherwise raise."""
    last = _system_health_last_write()
    if last is None:
        raise RuntimeError("system_health_checks is empty — cannot tell healthy from unread")
    age = datetime.now(timezone.utc) - last
    if age > timedelta(hours=SYSTEM_HEALTH_FRESH_HOURS):
        raise RuntimeError(f"system_health_checks last written {age.total_seconds() / 3600:.1f} h "
                           f"ago (> {SYSTEM_HEALTH_FRESH_HOURS} h) — health source is stale")
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
