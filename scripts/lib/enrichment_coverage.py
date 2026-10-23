"""enrichment_coverage.py — the pure half of the enrichment-coverage audit (lane ``audit-enrichment-coverage``).

Why this exists (2026-10-22, operator-approved: "Yes, I agree with your recommendations."): the daily
"ENRICHMENT COVERAGE GAPS — operator-directive symbols" alert audited ``watch_universe.directive_symbols()`` — every
``watchlist_items`` row with ``in_directive_watch=true`` — which had grown to 2,310 symbols (2,201 with gaps) because
automated think-tank / sector-universe directives set the flag and nothing ever cleared it. The alert listed the first
12 names alphabetically with no total, fired P2 every weekday with no dedupe, told the operator "the fetcher skipped
the canonical watch universe" (false: news ingestion caps at NEWS_INGEST_MAX and the cloud LLM lanes fund T0/T1 only),
and dumped the full list (5.1 MB) to the log.

This module holds the rules, so they are tested without a database:

* **Scope** is the curated Watch membership (AGENTS.md §26: the CIO prospect record / curated Watch membership is the
  one watch list), never the directive flag. The I/O side resolves it (``scripts/audit_enrichment_coverage.py``).
* **Expectations match the funded policy** (``config/hermes_research_budget.yaml``): every member is held to
  technicals + analyst; ``news_7d`` only for held / proposed names; ``llm_curation`` only for held / proposed /
  high-rank names (tiers T0/T1 — ``external_cloud_tiers``); ``protection_advisory`` only for held names that have
  technicals. "No articles from any source, ever" is reported, and is not a fetcher failure.
* **The message** leads with counts, then the top 10 by priority, then a cause line per surface built from lane
  receipts and the policy — never a guess.
* **Dedupe**: an alert is sent only when the gap count rises or a new (symbol, surface) gap appears.

Pure: no DB, no network, no file write, no send. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA_STATE = "EnrichmentCoverageState@v1"
SCHEMA_MANIFEST = "EnrichmentCoverageManifest@v1"

#: Membership tiers, strongest first. The order is the alert's priority order.
TIERS = ("held", "proposed", "operator_directive", "high_rank", "active")
TIER_LABEL = {"held": "held", "proposed": "proposed", "operator_directive": "operator directive",
              "high_rank": "high-rank", "active": "active"}

SURFACES = ("technicals", "analyst", "news_7d", "llm_curation", "protection_advisory",
            "synthesis_failed_needs_retry")

#: Tiers whose names the funded policy researches with a cloud LLM (T0 held/proposed, T1 high-rank).
LLM_FUNDED_TIERS = frozenset({"held", "proposed", "high_rank"})
#: Tiers whose names the news lane must cover (held first, then proposals — news_ingestion._get_actionable_pairs).
NEWS_FUNDED_TIERS = frozenset({"held", "proposed"})

TOP_N = 10
MANIFEST_CAP = 500

#: Who creates an operator directive (watch_directives.created_by). Automated producers (think_tank,
#: sector_universe, advisory, rotation_advisor, reentry, defense, claude_challenger, cio) are not the operator.
OPERATOR_DIRECTIVE_CREATORS = ("operator", "operator_audit")


def expected_surfaces(tiers: Iterable[str]) -> list[str]:
    """The surfaces a member with these tiers is funded to have."""
    t = set(tiers)
    exp = ["technicals", "analyst"]
    if t & NEWS_FUNDED_TIERS:
        exp.append("news_7d")
    if t & LLM_FUNDED_TIERS:
        exp.append("llm_curation")
    if "held" in t:
        exp.append("protection_advisory")
    return exp


def primary_tier(tiers: Iterable[str]) -> str:
    t = set(tiers)
    for name in TIERS:
        if name in t:
            return name
    return "active"


def evaluate(members: Mapping[str, Iterable[str]], ev: Mapping[str, set]) -> dict[str, Any]:
    """Gaps for every member. ``ev`` holds the evidence sets read by the I/O side:

    tech_ok, tech_exempt, analyst_ok, news_7d_ok, news_ever, llm_ok, prot_ok, synth_err.
    Returns {gaps: [...] (priority order), no_articles_any_source: [...], surface_counts: {...}}.
    """
    def s(name: str) -> set:
        return set(ev.get(name) or ())

    tech_ok, tech_exempt, analyst_ok = s("tech_ok"), s("tech_exempt"), s("analyst_ok")
    news_ok, news_ever, llm_ok = s("news_7d_ok"), s("news_ever"), s("llm_ok")
    prot_ok, synth_err = s("prot_ok"), s("synth_err")
    news_measured = bool(ev.get("news_measured", True))
    gaps: list[dict[str, Any]] = []
    no_articles: list[str] = []
    for sym in sorted(members):
        tiers = set(members[sym])
        exp = expected_surfaces(tiers)
        miss: list[str] = []
        if sym not in tech_ok and sym not in tech_exempt:
            miss.append("technicals")
        if sym not in analyst_ok:
            miss.append("analyst")
        if "news_7d" in exp and news_measured and sym not in news_ok:
            if sym in news_ever:
                miss.append("news_7d")
            else:
                no_articles.append(sym)  # nothing from any source, ever: not a fetcher failure
        if "llm_curation" in exp and sym not in llm_ok:
            miss.append("llm_curation")
        if "protection_advisory" in exp and sym in tech_ok and sym not in prot_ok:
            miss.append("protection_advisory")
        if sym in synth_err:
            miss.append("synthesis_failed_needs_retry")
        if miss:
            gaps.append({"symbol": sym, "tier": primary_tier(tiers), "tiers": sorted(tiers, key=TIERS.index),
                         "missing": miss})
    gaps.sort(key=priority_key)
    counts = {k: 0 for k in SURFACES}
    for g in gaps:
        for m in g["missing"]:
            counts[m] = counts.get(m, 0) + 1
    return {"gaps": gaps, "no_articles_any_source": sorted(no_articles),
            "surface_counts": {k: v for k, v in counts.items() if v}}


def priority_key(g: Mapping[str, Any]) -> tuple:
    """Held first, then proposed, operator directive, high-rank, active; more missing surfaces first; then symbol."""
    return (TIERS.index(g.get("tier", "active")), -len(g.get("missing") or ()), g.get("symbol", ""))


def gap_entries(gaps: Iterable[Mapping[str, Any]]) -> list[str]:
    """``SYM:surface`` strings, sorted — the identity of the gap set."""
    return sorted(f"{g['symbol']}:{m}" for g in gaps for m in g["missing"])


def fingerprint(entries: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()[:16]


def alert_decision(prev: Optional[Mapping[str, Any]], gaps: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Send only when the gap count worsens or a new (symbol, surface) gap appears.

    prev is the last state (``EnrichmentCoverageState@v1``) or None. Returns {send, reason, previous_count,
    count, new_entries}. A shrinking or unchanged set is recorded and not sent.
    """
    entries = gap_entries(gaps)
    count = len(gaps)
    out = {"count": count, "entries": len(entries), "fingerprint": fingerprint(entries),
           "previous_count": None, "new_entries": 0}
    if count == 0:
        return {**out, "send": False, "reason": "no_gaps"}
    if not prev or prev.get("schema") != SCHEMA_STATE:
        return {**out, "send": True, "reason": "first_run"}
    prev_count = int(prev.get("count") or 0)
    prev_entries = set(prev.get("entries") or ())
    new = [e for e in entries if e not in prev_entries]
    out.update(previous_count=prev_count, new_entries=len(new))
    if count > prev_count:
        return {**out, "send": True, "reason": "worsened"}
    if new:
        return {**out, "send": True, "reason": "set_changed"}
    return {**out, "send": False, "reason": "unchanged" if not prev_entries - set(entries) else "improved"}


def new_state(gaps: list[Mapping[str, Any]], decision: Mapping[str, Any], *, now: Optional[datetime] = None,
              alerted: bool = False, prev: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    entries = gap_entries(gaps)
    last_alert = (prev or {}).get("last_alert_at")
    return {"schema": SCHEMA_STATE, "as_of": now.isoformat(), "count": len(gaps), "entries": entries,
            "fingerprint": fingerprint(entries), "last_decision": decision.get("reason"),
            "last_alert_at": now.isoformat() if alerted else last_alert}


def _fmt_ts(v: Any) -> str:
    if not v:
        return "never"
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(v)[:19]


def receipt_cause(lane_id: str, receipt: Optional[Mapping[str, Any]]) -> str:
    """One truthful clause from a LaneRunReceipt: FAILED with its error, or its last ok, or 'no receipt'."""
    if not receipt:
        return f"{lane_id}: no lane receipt found"
    status = str(receipt.get("status") or "").lower()
    if status and status != "ok":
        err = receipt.get("error") or (receipt.get("summary") or {}).get("error_type") or "no error recorded"
        return (f"{lane_id} last run FAILED {_fmt_ts(receipt.get('finished_at'))} ({str(err)[:80]}); "
                f"last ok {_fmt_ts(receipt.get('ok_at'))}")
    return f"{lane_id} last ok {_fmt_ts(receipt.get('ok_at') or receipt.get('finished_at'))}"


#: Which lane receipt and which policy fact answer "why is this surface missing". Receipt ids are the
#: data/runtime/<id>_last.json files the producers write (lib/lane_last_receipt.py).
CAUSE_SOURCES: dict[str, dict[str, Any]] = {
    "llm_curation": {"receipts": ["hermes_top20_external_intel"],
                     "policy": "cloud LLM lanes fund T0/T1 only (held, proposed, high-rank); "
                               "T2 directive names are capped at 80/run, 200/day"},
    "news_7d": {"receipts": [],
                "policy": "news_ingestion --priority covers held + proposals first and caps the run at "
                          "NEWS_INGEST_MAX={news_cap} symbols"},
    "technicals": {"receipts": ["technicals-gap-backfill"],
                   "policy": "ticker_snapshot_daily rsi within 3 days"},
    "analyst": {"receipts": [], "policy": "pro_analyst_pills_latest.json as of {pills_as_of}"},
    "protection_advisory": {"receipts": [], "policy": "hermes_research_intelligence protection_advisory within 7 days"},
    "synthesis_failed_needs_retry": {"receipts": [],
                                     "policy": "latest watchlist_final_synthesis is an 'LLM error' row"},
}


def cause_lines(surface_counts: Mapping[str, int], receipts: Mapping[str, Optional[Mapping[str, Any]]],
                facts: Mapping[str, Any]) -> list[str]:
    """One line per surface that has gaps, from the lane receipts and the funded policy."""
    lines = []
    for surface in SURFACES:
        n = surface_counts.get(surface)
        if not n:
            continue
        src = CAUSE_SOURCES.get(surface, {})
        parts = [receipt_cause(r, receipts.get(r)) for r in src.get("receipts", [])]
        pol = src.get("policy")
        if pol:
            try:
                parts.append(pol.format(**{k: facts.get(k, "unknown") for k in ("news_cap", "pills_as_of")}))
            except (KeyError, IndexError):
                parts.append(pol)
        lines.append(f"{surface} ({n}): " + "; ".join(parts))
    return lines


def message(*, members: Mapping[str, Iterable[str]], result: Mapping[str, Any], decision: Mapping[str, Any],
            causes: list[str], membership_source: str, manifest_rel: str) -> str:
    """Counts first, then the top 10 by priority, then the causes. P3: it goes to the digest."""
    tier_counts = {t: 0 for t in TIERS}
    for tiers in members.values():
        for t in set(tiers):
            tier_counts[t] = tier_counts.get(t, 0) + 1
    gaps = result.get("gaps") or []
    sc = result.get("surface_counts") or {}
    head = [
        "ENRICHMENT COVERAGE — curated Watch",
        f"{len(gaps)} of {len(members)} members have gaps ("
        + " · ".join(f"{k} {v}" for k, v in sc.items()) + ")",
        "Members: " + " · ".join(f"{TIER_LABEL[t]} {tier_counts[t]}" for t in TIERS if tier_counts.get(t))
        + f" (source: {membership_source})",
    ]
    if decision.get("reason") == "worsened":
        head.append(f"Worse than last run: {decision.get('previous_count')} → {decision.get('count')}")
    elif decision.get("reason") == "set_changed":
        head.append(f"{decision.get('new_entries')} new gap(s) since last run")
    na = result.get("no_articles_any_source") or []
    if na:
        head.append(f"Not a gap: {len(na)} held/proposed name(s) have no articles from any source")
    top = [f"• {g['symbol']} [{TIER_LABEL.get(g['tier'], g['tier'])}]: {', '.join(g['missing'])}"
           for g in gaps[:TOP_N]]
    body = head + ["", f"Top {min(TOP_N, len(gaps))} by priority:"] + top
    if causes:
        body += ["", "Why (lane receipts + funded policy):"] + [f"• {c}" for c in causes]
    body += ["", f"Full list (capped {MANIFEST_CAP}): {manifest_rel}"]
    return "\n".join(body)


def manifest(*, members: Mapping[str, Iterable[str]], result: Mapping[str, Any], decision: Mapping[str, Any],
             causes: list[str], membership_source: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """The capped manifest written instead of dumping the full list into the log."""
    now = now or datetime.now(timezone.utc)
    gaps = list(result.get("gaps") or [])
    return {"schema": SCHEMA_MANIFEST, "as_of": now.isoformat(), "membership_source": membership_source,
            "members": len(members), "symbols_with_gaps": len(gaps),
            "surface_counts": dict(result.get("surface_counts") or {}),
            "no_articles_any_source": list(result.get("no_articles_any_source") or [])[:MANIFEST_CAP],
            "alert_decision": {k: decision.get(k) for k in ("send", "reason", "count", "previous_count",
                                                            "new_entries", "fingerprint")},
            "causes": causes, "cap": MANIFEST_CAP, "truncated": len(gaps) > MANIFEST_CAP,
            "gaps": gaps[:MANIFEST_CAP]}
