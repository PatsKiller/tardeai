"""White-Space Discovery Stage 2 — coverage-diff gap engine (spec Part A).

Finds subjects the outside world keeps talking about that the system is NOT
covering anywhere, and files them as GAP_CANDIDATE rows in the Discovery
Inbox (one row per gap, meta_json.gap_type carries the MISSING_* family —
the migration deliberately did NOT mint ten candidate types).

The engine is a set difference:

  COVERED  everything the platform already tracks — holdings symbols
           (read-only holdings.json), watchlist symbols, enabled
           topic_monitor topics, ACTIVE watch_directives (labels + spec
           keywords), strategy_registry ids/types, ACTIVE research_sources
           names/domains. One db_adapter._execute per statement, every
           collector defensive (a missing table/file skips that area with a
           note — the covered set only ever SHRINKS on failure, which makes
           the engine conservative the safe way: more candidate gaps, all
           operator-gated, never a silent miss).
           EXCEPTION — fail-closed guard: if EVERY coverage area fails to
           load, the run aborts instead of declaring the whole world a gap.

  DEMAND   recurring outside-world subjects — hermes_research_intelligence
           topics, news entities via content_entity_links (news_articles
           source attribution), recurring non-gap discovery candidates
           (seen_count >= 2), and outcome-bus tags (state/hermes/
           outcome_bus.json by_tag) when present.

A demand subject becomes a gap only when recurrence >= MIN_RECURRENCE (2)
AND cross-source count >= MIN_SOURCES (2) AND its normalized key is absent
from the covered set (dedupe.normalize_key on both sides — the same
normalization that makes inbox upserts idempotent).

Every gap payload carries the required meta contract:
  gap_type                 one of GAP_TYPES (MISSING_THEME, MISSING_SECTOR,
                           MISSING_STRATEGY, MISSING_SOURCE, MISSING_COMPANY,
                           MISSING_LEGAL_TOPIC, MISSING_TAX_TOPIC,
                           MISSING_RETIREMENT_TOPIC, MISSING_PRODUCT_VERTICAL)
                           — MISSING_PRIVATE_COMPANY_PROXY is deliberately
                           Stage-4 territory (private_proxy lane), never
                           emitted here
  why_missing              which covered surfaces were checked and missed
  why_it_matters           gap-type-specific rationale
  current_system_coverage  covered-set snapshot summary (per-area counts)
  proposed_coverage        gap-type-specific operator suggestion
  evidence_refs            the same source refs as the payload evidence
  source_count             distinct demand sources
  recurrence_count         total demand mentions

HARD RULES (tested):
  * GAP_CANDIDATE emissions ONLY, safe_action_level=OPERATOR_REVIEW_REQUIRED,
    never promotes, never transitions status — no broker/execution/promotion
    imports anywhere in this module;
  * registered as the worker pool's 'white_space' lane runner
    (worker_pool.register_lane_runner contract: runner(lane_cfg, *,
    dry_run) -> payload dicts; the POOL owns all writes);
  * dedupe against existing candidates comes free from upsert idempotency.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains, inbox, subjects, worker_pool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUS_PATH = Path(os.getenv("TRADE_AI_OUTCOME_BUS_JSON")
                or PROJECT_ROOT / "state" / "hermes" / "outcome_bus.json")

PRODUCER = "white_space_discovery"
ACTOR = "ingestor:white_space"
LANE_ID = "white_space"

WINDOW_DAYS = 14           # demand look-back window
MIN_RECURRENCE = 2         # a subject must recur to be demand, not noise
MIN_SOURCES = 2            # ... and be cross-source confirmed
SCAN_LIMIT = 300           # max grouped subjects pulled per demand stream
GAP_TTL_DAYS = 30
DEFAULT_RUN_LIMIT = 8      # mirrors the white_space lane max_candidates_per_run

GAP_TYPES = frozenset({
    "MISSING_THEME", "MISSING_SECTOR", "MISSING_STRATEGY", "MISSING_SOURCE",
    "MISSING_COMPANY", "MISSING_LEGAL_TOPIC", "MISSING_TAX_TOPIC",
    "MISSING_RETIREMENT_TOPIC", "MISSING_PRODUCT_VERTICAL",
})

# term heuristics for gap_type classification (word-boundary matched, first
# hit in precedence order wins; entity_type hints take precedence over terms)
_GAP_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MISSING_TAX_TOPIC",
     ("tax", "taxes", "irs", "capital gains", "wash sale", "tax-loss", "1099",
      "deduction", "tax bracket", "estimated tax", "cost basis", "amt")),
    ("MISSING_RETIREMENT_TOPIC",
     ("retirement", "ira", "401k", "403b", "rmd", "roth", "social security",
      "medicare", "irmaa", "pension", "annuity", "ssdi")),
    ("MISSING_LEGAL_TOPIC",
     ("lawsuit", "litigation", "court", "ruling", "statute", "regulation",
      "rulemaking", "sec enforcement", "finra", "doj", "antitrust", "subpoena",
      "settlement", "compliance", "legal", "legislation", "tenant", "zoning")),
    ("MISSING_STRATEGY",
     ("strategy", "backtest", "mean reversion", "momentum", "scalp",
      "breakout", "swing trade", "arbitrage", "pairs trade", "covered call",
      "iron condor", "trend following", "stat arb", "carry trade")),
    ("MISSING_SECTOR",
     ("sector", "industrials", "utilities", "financials", "healthcare",
      "energy sector", "materials", "consumer staples",
      "consumer discretionary", "real estate", "communication services",
      "information technology")),
    ("MISSING_PRODUCT_VERTICAL",
     ("battery", "batteries", "gpu", "gpus", "chips", "saas", "robotaxi",
      "drone", "drones", "wearable", "streaming", "e-commerce", "platform",
      "devices", "robotics", "data center", "datacenter", "vertical",
      "cloud infrastructure", "weight-loss drug", "glp-1")),
    ("MISSING_COMPANY",
     ("inc", "corp", "corporation", "ltd", "plc", "company", "startup",
      "acquisition of", "ipo")),
)

_DOMAIN_GAP_TYPES = {
    "taxes": "MISSING_TAX_TOPIC",
    "retirement": "MISSING_RETIREMENT_TOPIC",
    "legal": "MISSING_LEGAL_TOPIC",
    "legal_general": "MISSING_LEGAL_TOPIC",
    "sectors": "MISSING_SECTOR",
}

_WHY_IT_MATTERS = {
    "MISSING_THEME": "A recurring cross-source theme with no research surface "
                     "means the system reasons without context the outside "
                     "world already considers material.",
    "MISSING_SECTOR": "An uncovered sector cluster can hide correlated "
                      "exposure and rotation opportunities the watchlist "
                      "never sees.",
    "MISSING_STRATEGY": "A repeatedly discussed strategy family absent from "
                        "the strategy registry is unexamined edge (or an "
                        "unexamined crowd risk).",
    "MISSING_SOURCE": "A source repeatedly cited by covered material but "
                      "absent from research_sources leaves the intake "
                      "pipeline structurally blind to it.",
    "MISSING_COMPANY": "A company drawing recurring cross-source attention "
                       "with no holding/watchlist/topic coverage is an "
                       "unassessed opportunity or spillover risk.",
    "MISSING_LEGAL_TOPIC": "Recurring legal/regulatory developments outside "
                           "coverage can change the rules a portfolio "
                           "position depends on.",
    "MISSING_TAX_TOPIC": "Recurring tax developments outside coverage can "
                         "silently change after-tax outcomes of existing "
                         "plans.",
    "MISSING_RETIREMENT_TOPIC": "Recurring retirement-policy developments "
                                "outside coverage can affect account "
                                "strategy (contribution, RMD, IRMAA math).",
    "MISSING_PRODUCT_VERTICAL": "A product vertical drawing recurring "
                                "attention with no theme/sector coverage is "
                                "where new winners/losers form unwatched.",
}

_PROPOSED_COVERAGE = {
    "MISSING_THEME": "Operator review: consider a topic_monitor entry or an "
                     "approved research topic for this theme.",
    "MISSING_SECTOR": "Operator review: consider a sector research topic or "
                      "targeted screener coverage for this sector.",
    "MISSING_STRATEGY": "Operator review: consider a STRATEGY_CANDIDATE "
                        "evaluation via the incubator (never direct adoption).",
    "MISSING_SOURCE": "Operator review: consider registering the source in "
                      "research_sources via source curation.",
    "MISSING_COMPANY": "Operator review: consider staged ticker review / "
                       "watch evaluation through governed pathways.",
    "MISSING_LEGAL_TOPIC": "Operator review: consider a legal research topic "
                           "(advisory summaries only, never legal advice).",
    "MISSING_TAX_TOPIC": "Operator review: consider a tax research topic "
                         "(research summaries only — consult a qualified "
                         "professional).",
    "MISSING_RETIREMENT_TOPIC": "Operator review: consider a retirement "
                                "research topic (research summaries only — "
                                "consult a qualified professional).",
    "MISSING_PRODUCT_VERTICAL": "Operator review: consider a product-vertical "
                                "theme topic with representative public "
                                "tickers.",
}

_SOURCE_LIKE_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*\.(?:com|org|net|io|gov|edu|co|ai|substack\.com)\b")

COVERAGE_AREAS = ("holdings", "watchlist", "topic_monitor", "watch_directives",
                  "strategy_registry", "research_sources")


# ── plumbing ─────────────────────────────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute
    (one statement per call, immediate commit — the 120s idle-in-transaction
    guard can never bite)."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _term_hit(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term.lower())
                          + r"(?![a-z0-9])", text.lower()))


# ── COVERED set (one _execute per area, all defensive) ───────────────────────

def build_covered_set(notes: list[str] | None = None) -> dict[str, Any]:
    """Everything the system already covers, as normalized keys.

    Returns {"keys": set[str], "areas": {area: count|None}, "summary": str}.
    A failed area contributes None to `areas` plus a note — the caller's
    fail-closed guard (run aborts when ALL areas fail) lives in run_discovery.
    """
    keys: set[str] = set()
    areas: dict[str, int | None] = {}

    def _note(msg: str) -> None:
        if notes is not None:
            notes.append(msg)

    def _add(area: str, values: list[str]) -> None:
        n = 0
        for v in values:
            key = dedupe.normalize_key(str(v or ""))
            if key:
                keys.add(key)
                n += 1
        areas[area] = n

    # holdings symbols — read-only holdings.json via subjects
    try:
        _add("holdings", sorted(subjects.held_symbols()))
    except Exception as e:
        areas["holdings"] = None
        _note(f"holdings coverage unavailable: {e}")

    # watchlist symbols
    try:
        _add("watchlist", [r.get("symbol") for r in
                           _rows("SELECT DISTINCT symbol FROM watchlist_items")
                           if r.get("symbol")])
    except Exception as e:
        areas["watchlist"] = None
        _note(f"watchlist coverage unavailable: {e}")

    # enabled topic monitors
    try:
        _add("topic_monitor", [r.get("display_name") for r in
                               _rows("SELECT display_name FROM topic_monitor "
                                     "WHERE enabled = TRUE")])
    except Exception as e:
        areas["topic_monitor"] = None
        _note(f"topic_monitor coverage unavailable: {e}")

    # active watch directives: labels + spec keywords
    try:
        vals: list[str] = []
        for r in _rows("SELECT label, spec FROM watch_directives "
                       "WHERE status = 'active'"):
            vals.append(str(r.get("label") or ""))
            spec = r.get("spec") or {}
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except Exception:
                    spec = {}
            if isinstance(spec, dict):
                vals.extend(str(k) for k in (spec.get("keywords") or []))
        _add("watch_directives", vals)
    except Exception as e:
        areas["watch_directives"] = None
        _note(f"watch_directives coverage unavailable: {e}")

    # strategy registry ids + types
    try:
        vals = []
        for r in _rows("SELECT strategy_id, strategy_type FROM strategy_registry"):
            vals.extend([str(r.get("strategy_id") or ""),
                         str(r.get("strategy_type") or "")])
        _add("strategy_registry", vals)
    except Exception as e:
        areas["strategy_registry"] = None
        _note(f"strategy_registry coverage unavailable: {e}")

    # active research sources: names + url hostnames
    try:
        vals = []
        for r in _rows("SELECT source_name, source_url FROM research_sources "
                       "WHERE active = TRUE"):
            vals.append(str(r.get("source_name") or ""))
            url = str(r.get("source_url") or "")
            host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            if host:
                vals.append(host)
        _add("research_sources", vals)
    except Exception as e:
        areas["research_sources"] = None
        _note(f"research_sources coverage unavailable: {e}")

    loaded = {a: n for a, n in areas.items() if n is not None}
    summary = ("covered surfaces checked: "
               + ", ".join(f"{a}={n}" for a, n in loaded.items())
               + (f"; unavailable: {sorted(a for a, n in areas.items() if n is None)}"
                  if len(loaded) < len(areas) else ""))
    return {"keys": keys, "areas": areas, "summary": summary}


# ── DEMAND signals (grouped mentions; all defensive) ─────────────────────────

def collect_demand_mentions(window_days: int = WINDOW_DAYS,
                            notes: list[str] | None = None,
                            ) -> list[dict[str, Any]]:
    """Grouped demand mentions across the four streams. Each mention:
    {subject, entity_type, stream, count, sources:[...], sample}."""
    d = max(1, int(window_days))
    mentions: list[dict[str, Any]] = []

    def _note(msg: str) -> None:
        if notes is not None:
            notes.append(msg)

    # (1) hermes research topics
    try:
        for r in _rows(
                f"""SELECT topic AS subject, count(*) AS n,
                           count(DISTINCT COALESCE(source, 'hermes')) AS n_sources,
                           (array_agg(DISTINCT COALESCE(source, 'hermes')))[1:6]
                               AS sources,
                           max(COALESCE(summary, '')) AS sample
                    FROM hermes_research_intelligence
                    WHERE topic IS NOT NULL AND length(topic) > 4
                      AND created_at > now() - make_interval(days => %s)
                    GROUP BY 1 ORDER BY count(*) DESC LIMIT %s""",
                (d, SCAN_LIMIT)):
            mentions.append({"subject": str(r["subject"] or "").strip(),
                             "entity_type": "topic",
                             "stream": "research_topics",
                             "count": int(r["n"] or 0),
                             "sources": [str(s) for s in (r["sources"] or []) if s],
                             "sample": str(r.get("sample") or "")[:200]})
    except Exception as e:
        _note(f"hermes_research_intelligence demand unavailable: {e}")

    # (2) news entities via content_entity_links (news_articles attribution)
    try:
        for r in _rows(
                f"""SELECT l.entity_type, l.entity_value AS subject, count(*) AS n,
                           count(DISTINCT COALESCE(a.source, 'unknown')) AS n_sources,
                           (array_agg(DISTINCT COALESCE(a.source, 'unknown')))[1:6]
                               AS sources,
                           max(COALESCE(a.title, '')) AS sample
                    FROM content_entity_links l
                    LEFT JOIN news_articles a
                      ON l.content_type = 'news_article' AND a.id = l.content_id
                    WHERE l.created_at > now() - make_interval(days => %s)
                    GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT %s""",
                (d, SCAN_LIMIT)):
            mentions.append({"subject": str(r["subject"] or "").strip(),
                             "entity_type": str(r["entity_type"] or "topic").lower(),
                             "stream": "news_entities",
                             "count": int(r["n"] or 0),
                             "sources": [str(s) for s in (r["sources"] or []) if s],
                             "sample": str(r.get("sample") or "")[:200]})
    except Exception as e:
        _note(f"content_entity_links demand unavailable: {e}")

    # (3) recurring non-gap discovery candidates (their subjects keep coming
    #     back through other producers — that recurrence IS demand)
    try:
        for r in _rows(
                """SELECT label AS subject, candidate_type, seen_count AS n,
                          evidence_json, source_domain
                   FROM hermes_discovery_candidates
                   WHERE candidate_type <> 'GAP_CANDIDATE'
                     AND seen_count >= 2
                     AND status NOT IN ('REJECTED', 'BLOCKED', 'ARCHIVED_COLD',
                                        'MERGED_DUPLICATE')
                   ORDER BY seen_count DESC, last_seen_at DESC LIMIT 200"""):
            ev = r.get("evidence_json")
            if isinstance(ev, str):
                try:
                    ev = json.loads(ev)
                except Exception:
                    ev = []
            srcs = sorted({str(item.get("source_domain")).lower()
                           for item in (ev or []) if isinstance(item, dict)
                           and item.get("source_domain")}
                          | ({str(r["source_domain"]).lower()}
                             if r.get("source_domain") else set()))
            mentions.append({"subject": str(r["subject"] or "").strip(),
                             "entity_type": ("ticker" if str(r.get("candidate_type"))
                                             == "TICKER_CANDIDATE" else "topic"),
                             "stream": "discovery_recurrence",
                             "count": int(r["n"] or 0),
                             "sources": srcs[:6],
                             "sample": f"recurring {r.get('candidate_type')} "
                                       f"(seen {int(r['n'] or 0)}x)"})
    except Exception as e:
        _note(f"discovery-candidate demand unavailable: {e}")

    # (4) outcome-bus tags (tag-lift evidence), when the bus file exists
    bus = _read_json(BUS_PATH)
    if isinstance(bus, dict) and isinstance(bus.get("by_tag"), dict):
        for tag, stats in bus["by_tag"].items():
            if not isinstance(stats, dict):
                continue
            try:
                n = int(stats.get("n") or 0)
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                continue
            mentions.append({"subject": str(tag).strip(),
                             "entity_type": "topic",
                             "stream": "outcome_bus_tags",
                             "count": n,
                             "sources": ["outcome_bus"],
                             "sample": f"outcome-bus tag (n={n}, "
                                       f"lift={stats.get('lift')})"})
    elif notes is not None:
        notes.append("outcome_bus.json missing/shapeless — tag demand skipped")

    return [m for m in mentions if m["subject"]]


def aggregate_demand(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge mentions across streams by normalized subject key.

    Returns subject dicts: {subject, key, entity_types, streams, recurrence,
    sources (distinct, cross-stream), samples}. Sorted by recurrence desc.
    """
    agg: dict[str, dict[str, Any]] = {}
    for m in mentions:
        key = dedupe.normalize_key(m["subject"])
        if not key:
            continue
        s = agg.setdefault(key, {"subject": m["subject"], "key": key,
                                 "entity_types": set(), "streams": set(),
                                 "recurrence": 0, "sources": set(),
                                 "samples": []})
        s["entity_types"].add(m.get("entity_type") or "topic")
        s["streams"].add(m.get("stream") or "unknown")
        s["recurrence"] += max(0, int(m.get("count") or 0))
        s["sources"].update(str(x).lower() for x in (m.get("sources") or []) if x)
        if m.get("sample") and len(s["samples"]) < 6:
            s["samples"].append({"source_domain": (m.get("sources") or [None])[0],
                                 "note": str(m["sample"])[:180],
                                 "stream": m.get("stream")})
    out = list(agg.values())
    for s in out:
        s["entity_types"] = sorted(s["entity_types"])
        s["streams"] = sorted(s["streams"])
        s["sources"] = sorted(s["sources"])
    out.sort(key=lambda s: (-s["recurrence"], -len(s["sources"])))
    return out


# ── gap classification ───────────────────────────────────────────────────────

def classify_gap_type(subject: str, *, entity_types: list[str] | None = None,
                      sample_text: str = "") -> str:
    """Heuristic MISSING_* classification. entity_type hints beat term tables;
    anything unmatched is a MISSING_THEME. MISSING_PRIVATE_COMPANY_PROXY is
    intentionally NOT produced here (Stage-4 private_proxy lane)."""
    etypes = {str(t).lower() for t in (entity_types or [])}
    if "ticker" in etypes:
        return "MISSING_COMPANY"
    if "sector" in etypes:
        return "MISSING_SECTOR"
    text = f"{subject} {sample_text}".lower()
    if _SOURCE_LIKE_RE.search(subject.lower()):
        return "MISSING_SOURCE"
    # domain registry agreement (defensive — display heuristic only)
    try:
        dom = domains.classify_domain({"candidate_type": "TOPIC_CANDIDATE",
                                       "label": subject, "summary": sample_text})
        mapped = _DOMAIN_GAP_TYPES.get(dom)
        if mapped:
            return mapped
    except Exception:
        pass
    for gap_type, terms in _GAP_TERMS:
        # company markers are generic news-prose words ("inc", "company") —
        # only the subject itself may claim MISSING_COMPANY, never sample text
        hit_text = subject.lower() if gap_type == "MISSING_COMPANY" else text
        if any(_term_hit(hit_text, t) for t in terms):
            return gap_type
    return "MISSING_THEME"


# ── the diff core (pure; unit-testable without a DB) ─────────────────────────

def compute_gaps(demand_subjects: list[dict[str, Any]],
                 covered_keys: set[str], *,
                 min_recurrence: int = MIN_RECURRENCE,
                 min_sources: int = MIN_SOURCES,
                 skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Recurrence + cross-source + absence gates over aggregated demand."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    gaps: list[dict[str, Any]] = []
    for s in demand_subjects:
        if int(s.get("recurrence") or 0) < max(1, int(min_recurrence)):
            _skip("low_recurrence")
            continue
        if len(s.get("sources") or []) < max(1, int(min_sources)):
            _skip("low_cross_source")
            continue
        if s["key"] in covered_keys:
            _skip("already_covered")
            continue
        gaps.append(s)
    return gaps


def build_gap_payloads(gaps: list[dict[str, Any]],
                       coverage_summary: str, *,
                       limit: int = DEFAULT_RUN_LIMIT,
                       skipped: dict[str, int] | None = None,
                       ) -> list[dict[str, Any]]:
    """Gaps → inbox.upsert_candidate keyword payloads (GAP_CANDIDATE only).

    Labels are stable per subject ("Coverage gap: <subject>") so re-runs bump
    seen_count instead of duplicating. Every payload carries the full
    required-meta contract (module docstring) and is
    OPERATOR_REVIEW_REQUIRED."""
    payloads: list[dict[str, Any]] = []
    for g in gaps:
        if len(payloads) >= max(1, int(limit)):
            if skipped is not None:
                skipped["run_cap"] = skipped.get("run_cap", 0) + 1
            continue
        subject = str(g["subject"]).strip()
        sample_text = " ".join(str(x.get("note") or "") for x in g.get("samples") or [])
        gap_type = classify_gap_type(subject,
                                     entity_types=g.get("entity_types"),
                                     sample_text=sample_text)
        if gap_type not in GAP_TYPES:  # belt and braces — taxonomy is closed
            gap_type = "MISSING_THEME"
        sources = list(g.get("sources") or [])
        streams = list(g.get("streams") or [])
        evidence = [{"source_domain": x.get("source_domain"),
                     "note": f"[{x.get('stream')}] {x.get('note')}"}
                    for x in (g.get("samples") or [])][:8]
        if not evidence:
            evidence = [{"source_domain": (sources or [None])[0],
                         "note": f"{g['recurrence']} demand mentions across "
                                 f"{len(sources)} sources ({', '.join(streams)})"}]
        why_missing = (f"'{subject}' recurred {g['recurrence']}x across "
                       f"{len(sources)} distinct sources "
                       f"(streams: {', '.join(streams)}) but matches nothing "
                       f"in the covered set — not a holding, watchlist symbol, "
                       f"topic monitor, watch directive, registered strategy, "
                       f"or active research source.")
        payloads.append(dict(
            candidate_type="GAP_CANDIDATE",
            label=f"Coverage gap: {subject}"[:120],
            summary=(f"{gap_type}: {why_missing}")[:400],
            evidence=evidence,
            seed_symbols=([subject.upper()] if "ticker" in
                          (g.get("entity_types") or []) else []),
            meta={
                "producer": PRODUCER,
                "gap_type": gap_type,
                "why_missing": why_missing,
                "why_it_matters": _WHY_IT_MATTERS[gap_type],
                "current_system_coverage": coverage_summary,
                "proposed_coverage": _PROPOSED_COVERAGE[gap_type],
                "evidence_refs": evidence,
                "source_count": len(sources),
                "recurrence_count": int(g["recurrence"]),
                "demand_streams": streams,
                "demand_sources": sources[:10],
                "keywords": [subject][:10],
            },
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=GAP_TTL_DAYS,
        ))
    return payloads


# ── run entry point + lane runner ────────────────────────────────────────────

def run_discovery(*, dry_run: bool = False, limit: int | None = None,
                  window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """Full white-space pass. Returns the JSON run report; live mode writes
    candidates exclusively through inbox.upsert_candidate."""
    notes: list[str] = []
    skipped: dict[str, int] = {}

    covered = build_covered_set(notes)
    demand = aggregate_demand(collect_demand_mentions(window_days, notes))

    report: dict[str, Any] = {
        "mode": "white_space",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "thresholds": {"window_days": int(window_days),
                       "min_recurrence": MIN_RECURRENCE,
                       "min_sources": MIN_SOURCES},
        "covered_areas": covered["areas"],
        "covered_keys": len(covered["keys"]),
        "demand_subjects": len(demand),
    }

    # fail-closed guard: every coverage area broken → the diff is meaningless
    if all(n is None for n in covered["areas"].values()):
        report.update({"error": "all coverage areas unavailable — refusing to "
                                "declare gaps against an empty covered set",
                       "notes": notes, "gaps_detected": 0, "upserted": 0,
                       "by_gap_type": {}, "skipped_reasons": {},
                       "candidates": []})
        return report

    gaps = compute_gaps(demand, covered["keys"], skipped=skipped)
    payloads = build_gap_payloads(gaps, covered["summary"],
                                  limit=int(limit) if limit else DEFAULT_RUN_LIMIT,
                                  skipped=skipped)

    by_gap_type: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        gap_type = p["meta"]["gap_type"]
        by_gap_type[gap_type] = by_gap_type.get(gap_type, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "gap_type": gap_type,
                   "source_count": p["meta"]["source_count"],
                   "recurrence_count": p["meta"]["recurrence_count"]}
        if not dry_run:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({
                "id": row.get("id"), "status": row.get("status"),
                "seen_count": row.get("seen_count"),
                "research_domain": (row.get("meta_json") or {}).get("research_domain"),
                "workspace_id": (row.get("meta_json") or {}).get("workspace_id"),
            })
            upserted += 1
        candidates.append(summary)

    report.update({
        "gaps_detected": len(gaps),
        "upserted": upserted,
        "would_upsert": len(candidates) if dry_run else None,
        "by_gap_type": by_gap_type,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    })
    return report


def lane_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """worker_pool 'white_space' lane runner (register_lane_runner contract).

    READ-ONLY: builds and returns the gap payload dicts; the pool owns every
    write (candidates-only, behind the lane + do-no-harm gates)."""
    notes: list[str] = []
    covered = build_covered_set(notes)
    if all(n is None for n in covered["areas"].values()):
        return []  # fail closed — never diff against an empty covered set
    demand = aggregate_demand(collect_demand_mentions(WINDOW_DAYS, notes))
    gaps = compute_gaps(demand, covered["keys"])
    try:
        limit = int(lane_cfg.get("max_candidates_per_run") or DEFAULT_RUN_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_RUN_LIMIT
    return build_gap_payloads(gaps, covered["summary"], limit=limit)


# Stage-2 wiring: this module IS the white_space lane runner.
worker_pool.register_lane_runner(LANE_ID, lane_runner, replace=True)
