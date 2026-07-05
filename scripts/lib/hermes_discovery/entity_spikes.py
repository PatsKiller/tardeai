"""Universal Research Discovery Layer — entity/term spike discovery (spec Part E).

Detects attention spikes: an entity or research topic whose current-window
mention count materially exceeds its prior-window baseline, confirmed across
enough distinct sources. Spikes become TREND_CANDIDATE / TOPIC_CANDIDATE rows
in the Discovery Inbox via inbox.upsert_candidate.

HARD RULES (tested):
  * candidates ONLY — safe_action_level=OPERATOR_REVIEW_REQUIRED, never
    promotes, never transitions status, never touches trading thresholds or
    execution (no broker/execution/promotion imports anywhere in this module);
  * dedupe against existing candidates comes free from upsert idempotency
    (unique candidate_type + normalized_key → seen_count bump);
  * dedupe against active coverage: a spike whose normalized_key is already
    covered by an active watch_directive or enabled topic_monitor row is
    skipped — a DIFFERENT normalized_key is a distinct subtopic and passes.

Inputs (each read defensively; a missing table/file is skipped with a note):
  content_entity_links (topic/sector/ticker entities) LEFT JOINed read-only to
      news_articles for per-article source attribution (cross-source gate)
  hermes_research_intelligence topics (term spikes in Hermes research output)
  watch_directives (active) + topic_monitor (enabled) → covered-key dedupe set
  holdings.json (subjects.held_symbols) + watchlist_items → relevance boost

Gates (ALL must pass, thresholds from config/hermes_discovery_schedule.json):
  recurrence   current_count >= min_recurrence_count            (default 2)
  sources      cross_source_count >= entity_spike_min_sources   (default 2)
  lift         current / max(prior, 1) >= MIN_LIFT (2.0), capped at LIFT_CAP;
               prior == 0 → "new entity" spike (lift = current, capped)
  coverage     normalized_key not in the covered set (see above)

All DB reads go through this module's _execute wrapper (one statement per
call, db_adapter under the hood) so tests can monkeypatch it with synthetic
rows and the 120s idle-in-transaction guard can never bite.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains, inbox, subjects

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_CONFIG_PATH = Path(os.getenv("HERMES_DISCOVERY_SCHEDULE_JSON")
                            or PROJECT_ROOT / "config" / "hermes_discovery_schedule.json")

PRODUCER = "entity_spike_discovery"
ACTOR = "ingestor:entity_spikes"

WINDOW_HOURS = 48          # current window (spec Part E)
MIN_LIFT = 2.0             # current/max(prior,1) must at least double
LIFT_CAP = 10.0            # new-entity spikes can't claim infinite lift
LIFT_FULL_SCALE = 6.0      # lift at/above this → trend_momentum signal 1.0
RELEVANCE_BOOST = 0.10     # held/watchlist symbol involvement
SCAN_LIMIT = 400           # max grouped terms pulled per input stream
SPIKE_TTL_DAYS = 14        # attention spikes go stale fast

# entity_type → inbox candidate type. Ticker spikes stay TREND (a ticker
# attention spike is a trend around a symbol, not a fresh ticker submission —
# spec Part E emits TREND/TOPIC only).
_ENTITY_CANDIDATE_TYPES = {
    "ticker": "TREND_CANDIDATE",
    "sector": "TREND_CANDIDATE",
    "topic": "TOPIC_CANDIDATE",
    "research_topic": "TOPIC_CANDIDATE",
}


# ── plumbing ─────────────────────────────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute
    (one statement per call, immediate commit)."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _table_exists(table: str) -> bool:
    try:
        row = _execute(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = %s",
            (table,), fetch="one")
        return bool(row)
    except Exception:
        return False


def load_spike_config(path: Path | str | None = None) -> dict[str, Any]:
    """Thresholds from config/hermes_discovery_schedule.json with safe
    defaults — a broken config falls back to the conservative defaults
    (higher bar, never a wider intake)."""
    p = Path(path) if path else SCHEDULE_CONFIG_PATH
    cfg: dict[str, Any] = {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}

    def _i(key: str, default: int) -> int:
        try:
            return max(1, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "entity_spike_min_sources": _i("entity_spike_min_sources", 2),
        "min_recurrence_count": _i("min_recurrence_count", 2),
        "max_candidates_per_run": _i("max_candidates_per_run", 25),
        "entity_spike_enabled": bool(cfg.get("entity_spike_enabled", False)),
        "min_lift": MIN_LIFT,
    }


# ── input collectors (defensive; missing table → [] + note) ─────────────────

def collect_entity_counts(window_hours: int = WINDOW_HOURS,
                          notes: list[str] | None = None,
                          ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    """content_entity_links grouped current-window rows + prior-window baseline
    map {(entity_type, entity_lower): prior_count}."""
    if not _table_exists("content_entity_links"):
        if notes is not None:
            notes.append("content_entity_links missing — entity stream skipped")
        return [], {}
    h = max(1, int(window_hours))
    current = _rows(
        f"""SELECT l.entity_type, l.entity_value, count(*) AS n,
                   count(DISTINCT COALESCE(a.source, 'unknown')) AS n_sources,
                   (array_agg(DISTINCT COALESCE(a.source, 'unknown')))[1:6] AS sources,
                   max(COALESCE(a.title, '')) AS sample
            FROM content_entity_links l
            LEFT JOIN news_articles a
              ON l.content_type = 'news_article' AND a.id = l.content_id
            WHERE l.created_at > now() - interval '{h} hours'
            GROUP BY 1, 2
            ORDER BY count(*) DESC
            LIMIT %s""", (SCAN_LIMIT,))
    prior_rows = _rows(
        f"""SELECT l.entity_type, l.entity_value, count(*) AS n
            FROM content_entity_links l
            WHERE l.created_at <= now() - interval '{h} hours'
              AND l.created_at > now() - interval '{2 * h} hours'
            GROUP BY 1, 2""")
    prior = {(str(r["entity_type"]).lower(), str(r["entity_value"]).strip().lower()):
             int(r["n"]) for r in prior_rows}
    for r in current:
        r["stream"] = "entity_links"
    return current, prior


def collect_topic_counts(window_hours: int = WINDOW_HOURS,
                         notes: list[str] | None = None,
                         ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    """hermes_research_intelligence topics: current grouped rows + prior map."""
    if not _table_exists("hermes_research_intelligence"):
        if notes is not None:
            notes.append("hermes_research_intelligence missing — topic stream skipped")
        return [], {}
    h = max(1, int(window_hours))
    current = _rows(
        f"""SELECT 'research_topic' AS entity_type, topic AS entity_value,
                   count(*) AS n,
                   count(DISTINCT COALESCE(source, 'hermes')) AS n_sources,
                   (array_agg(DISTINCT COALESCE(source, 'hermes')))[1:6] AS sources,
                   max(COALESCE(summary, '')) AS sample
            FROM hermes_research_intelligence
            WHERE topic IS NOT NULL AND length(topic) > 4
              AND created_at > now() - interval '{h} hours'
            GROUP BY 2
            ORDER BY count(*) DESC
            LIMIT %s""", (SCAN_LIMIT,))
    prior_rows = _rows(
        f"""SELECT topic AS entity_value, count(*) AS n
            FROM hermes_research_intelligence
            WHERE topic IS NOT NULL AND length(topic) > 4
              AND created_at <= now() - interval '{h} hours'
              AND created_at > now() - interval '{2 * h} hours'
            GROUP BY 1""")
    prior = {("research_topic", str(r["entity_value"]).strip().lower()): int(r["n"])
             for r in prior_rows}
    for r in current:
        r["stream"] = "research_topics"
    return current, prior


def covered_keys(notes: list[str] | None = None) -> set[str]:
    """Normalized keys already covered by an ACTIVE watch_directive (label +
    spec keywords) or an ENABLED topic_monitor row. Spikes matching one of
    these keys are skipped; a different normalized_key = distinct subtopic."""
    covered: set[str] = set()
    try:
        for r in _rows("SELECT label, spec FROM watch_directives WHERE status = 'active'"):
            key = dedupe.normalize_key(str(r.get("label") or ""))
            if key:
                covered.add(key)
            spec = r.get("spec") or {}
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except Exception:
                    spec = {}
            for kw in (spec.get("keywords") or []) if isinstance(spec, dict) else []:
                kw_key = dedupe.normalize_key(str(kw))
                if kw_key:
                    covered.add(kw_key)
    except Exception as e:
        if notes is not None:
            notes.append(f"watch_directives coverage unavailable: {e}")
    try:
        for r in _rows("SELECT display_name FROM topic_monitor WHERE enabled = TRUE"):
            key = dedupe.normalize_key(str(r.get("display_name") or ""))
            if key:
                covered.add(key)
    except Exception as e:
        if notes is not None:
            notes.append(f"topic_monitor coverage unavailable: {e}")
    return covered


def relevant_symbols(notes: list[str] | None = None) -> set[str]:
    """Held symbols (read-only holdings.json) + watchlist symbols — used only
    to BOOST the trend_momentum signal, never to gate."""
    syms: set[str] = set()
    try:
        syms |= subjects.held_symbols()
    except Exception as e:
        if notes is not None:
            notes.append(f"holdings relevance unavailable: {e}")
    try:
        syms |= {str(r.get("symbol") or "").upper()
                 for r in _rows("SELECT DISTINCT symbol FROM watchlist_items")
                 if r.get("symbol")}
    except Exception as e:
        if notes is not None:
            notes.append(f"watchlist relevance unavailable: {e}")
    return syms


# ── pure detection core (unit-testable without a DB) ─────────────────────────

def compute_spikes(current: list[dict[str, Any]],
                   prior: dict[tuple[str, str], int], *,
                   min_recurrence: int = 2,
                   min_sources: int = 2,
                   min_lift: float = MIN_LIFT,
                   skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Apply the recurrence / cross-source / lift gates to grouped term rows.

    `current` rows: {entity_type, entity_value, n, n_sources, sources, sample}.
    `prior`: {(entity_type_lower, entity_value_lower): baseline_count}.
    Returns spike dicts sorted by lift desc. `skipped` (optional) tallies
    gate-rejection reasons for the run report.
    """
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    spikes: list[dict[str, Any]] = []
    for r in current:
        etype = str(r.get("entity_type") or "").strip().lower()
        value = str(r.get("entity_value") or "").strip()
        if not value or etype not in _ENTITY_CANDIDATE_TYPES:
            _skip("unknown_entity_type" if value else "empty_value")
            continue
        n = int(r.get("n") or 0)
        n_sources = int(r.get("n_sources") or 0)
        if n < max(1, int(min_recurrence)):
            _skip("low_recurrence")
            continue
        if n_sources < max(1, int(min_sources)):
            _skip("low_cross_source")
            continue
        prior_n = int(prior.get((etype, value.lower()), 0))
        lift = min(LIFT_CAP, n / max(prior_n, 1))
        if lift < float(min_lift):
            _skip("low_lift")
            continue
        spikes.append({
            "entity_type": etype,
            "entity_value": value,
            "stream": r.get("stream") or "entity_links",
            "current_count": n,
            "prior_count": prior_n,
            "lift": round(lift, 4),
            "new_entity": prior_n == 0,
            "cross_source_count": n_sources,
            "sources": [str(s) for s in (r.get("sources") or []) if s][:6],
            "sample": str(r.get("sample") or "")[:200],
        })
    spikes.sort(key=lambda s: (-s["lift"], -s["current_count"]))
    return spikes


def momentum_signal(lift: float, *, relevant: bool = False) -> float:
    """Lift normalized to the 0..1 trend_momentum signal, with a small
    holdings/watchlist relevance boost, hard-clamped to [0, 1]."""
    base = min(1.0, max(0.0, float(lift)) / LIFT_FULL_SCALE)
    if relevant:
        base = min(1.0, base + RELEVANCE_BOOST)
    return round(base, 4)


def _spike_label(spike: dict[str, Any]) -> str:
    value = spike["entity_value"]
    if spike["entity_type"] == "ticker":
        return f"{value.upper()} news attention spike"
    if spike["entity_type"] == "sector":
        return f"{value} sector attention spike"
    return value[:120]


def build_payloads(spikes: list[dict[str, Any]], *,
                   covered: set[str],
                   relevant_syms: set[str],
                   window_hours: int = WINDOW_HOURS,
                   limit: int = 25,
                   skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Spikes → inbox.upsert_candidate keyword payloads.

    Coverage dedupe happens HERE (normalized_key vs covered set); duplicate
    candidates are handled downstream by upsert idempotency. Every payload is
    OPERATOR_REVIEW_REQUIRED and carries evidence refs + the spike meta block.
    """
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    payloads: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for spike in spikes:
        if len(payloads) >= max(1, int(limit)):
            _skip("run_cap")
            continue
        label = _spike_label(spike)
        key = dedupe.normalize_key(label)
        value_key = dedupe.normalize_key(spike["entity_value"])
        if not key:
            _skip("empty_key")
            continue
        if key in covered or (value_key and value_key in covered):
            _skip("covered_by_directive_or_topic")
            continue
        if key in seen_keys:
            _skip("duplicate_in_run")
            continue
        seen_keys.add(key)

        seed_symbols = ([spike["entity_value"].upper()]
                        if spike["entity_type"] == "ticker" else [])
        relevant = any(s in relevant_syms for s in seed_symbols)
        summary = (f"{spike['current_count']} mentions in {window_hours}h vs "
                   f"{spike['prior_count']} prior (lift {spike['lift']}x, "
                   f"{spike['cross_source_count']} sources). "
                   f"{spike['sample']}"[:300])
        payloads.append(dict(
            candidate_type=_ENTITY_CANDIDATE_TYPES[spike["entity_type"]],
            label=label,
            summary=summary,
            evidence=[{"source_domain": s,
                       "note": (f"{spike['current_count']} mentions in {window_hours}h "
                                f"(prior {spike['prior_count']}, lift {spike['lift']}x)")}
                      for s in spike["sources"]],
            seed_symbols=seed_symbols,
            meta={
                "producer": PRODUCER,
                "keywords": [spike["entity_value"]][:10],
                "entities": [spike["entity_value"]],
                "holdings_or_watchlist_relevant": relevant,
                "spike": {
                    "stream": spike["stream"],
                    "entity_type": spike["entity_type"],
                    "window_hours": window_hours,
                    "baseline_hours": window_hours,
                    "current_count": spike["current_count"],
                    "prior_count": spike["prior_count"],
                    "lift": spike["lift"],
                    "new_entity": spike["new_entity"],
                    "cross_source_count": spike["cross_source_count"],
                },
            },
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=SPIKE_TTL_DAYS,
            signals={"trend_momentum": momentum_signal(spike["lift"], relevant=relevant)},
        ))
    return payloads


def _payload_domain(payload: dict[str, Any]) -> str:
    """Best-effort domain for the run report (live rows re-derive it inside
    inbox); classification failure never blocks the report."""
    try:
        return domains.classify_domain({
            "candidate_type": payload["candidate_type"],
            "label": payload["label"],
            "summary": payload.get("summary"),
            "meta": payload.get("meta") or {},
            "evidence": payload.get("evidence") or [],
        })
    except Exception:
        return "unclassified"


# ── run entry point ──────────────────────────────────────────────────────────

def run_discovery(*, dry_run: bool = False, limit: int | None = None,
                  window_hours: int = WINDOW_HOURS,
                  config_path: Path | str | None = None) -> dict[str, Any]:
    """Full entity-spike pass. Returns the JSON run report; live mode writes
    candidates exclusively through inbox.upsert_candidate."""
    cfg = load_spike_config(config_path)
    notes: list[str] = []
    skipped: dict[str, int] = {}

    cur_entities, prior_entities = collect_entity_counts(window_hours, notes)
    cur_topics, prior_topics = collect_topic_counts(window_hours, notes)
    current = cur_entities + cur_topics
    prior = {**prior_entities, **prior_topics}

    spikes = compute_spikes(
        current, prior,
        min_recurrence=cfg["min_recurrence_count"],
        min_sources=cfg["entity_spike_min_sources"],
        min_lift=cfg["min_lift"],
        skipped=skipped)

    payloads = build_payloads(
        spikes,
        covered=covered_keys(notes),
        relevant_syms=relevant_symbols(notes),
        window_hours=window_hours,
        limit=int(limit) if limit else cfg["max_candidates_per_run"],
        skipped=skipped)

    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        domain = _payload_domain(p)
        by_type[p["candidate_type"]] = by_type.get(p["candidate_type"], 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "domain": domain,
                   "trend_momentum": p["signals"]["trend_momentum"],
                   "spike": p["meta"]["spike"]}
        if not dry_run:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({
                "id": row.get("id"), "status": row.get("status"),
                "seen_count": row.get("seen_count"),
                "research_domain": (row.get("meta_json") or {}).get("research_domain"),
                "score": (float(row["discovery_score"])
                          if row.get("discovery_score") is not None else None),
            })
            upserted += 1
        candidates.append(summary)

    return {
        "mode": "entity_spikes",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "enabled_in_schedule": cfg["entity_spike_enabled"],
        "thresholds": {
            "window_hours": window_hours,
            "min_recurrence_count": cfg["min_recurrence_count"],
            "entity_spike_min_sources": cfg["entity_spike_min_sources"],
            "min_lift": cfg["min_lift"],
        },
        "scanned_terms": len(current),
        "spikes_detected": len(spikes),
        "upserted": upserted,
        "would_upsert": len(candidates) if dry_run else None,
        "by_type": by_type,
        "by_domain": by_domain,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    }
