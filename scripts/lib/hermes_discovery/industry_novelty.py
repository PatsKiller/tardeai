"""Universal Research Discovery Layer — industry / sector novelty discovery.

Surfaces sectors/themes that are *prominent in current news but absent from our
covered universe* — a structural coverage gap, distinct from entity_spikes
(which flags attention spikes in sectors we already track). Novel sectors become
GAP_CANDIDATE rows (meta_json.gap_type = MISSING_SECTOR) in the Discovery Inbox.

Observed set: content_entity_links entity_type='sector' over a config window,
news-source attributed for a cross-source gate.
Covered set: distinct symbol_profiles.sector (the taxonomy our universe spans) ∪
active watch_directive / enabled topic_monitor keys (entity_spikes.covered_keys).
A news sector whose normalized key is in neither is "novel".

HARD RULES (mirrors entity_spikes.py — tested):
  * candidates ONLY — OPERATOR_REVIEW_REQUIRED, never promotes, never auto-adds
    to a watchlist, no broker/execution/promotion imports;
  * shadow-first: industry_novelty_enabled=false → computes + reports, writes
    nothing (an operator flips the flag to go live);
  * GAP_TYPES is a closed taxonomy — these are MISSING_SECTOR gaps (news-derived,
    not the keyword-heuristic white_space path), tagged meta.lane=industry_novelty;
  * honors industry_novelty_max_per_day so it can never swamp the inbox.

All DB reads go through this module's _execute wrapper so tests can monkeypatch
it with synthetic rows.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains, entity_spikes, inbox

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEDULE_CONFIG_PATH = Path(os.getenv("HERMES_DISCOVERY_SCHEDULE_JSON")
                            or PROJECT_ROOT / "config" / "hermes_discovery_schedule.json")

PRODUCER = "industry_novelty_discovery"
ACTOR = "discovery:industry_novelty"
LANE = "industry_novelty"
GAP_TYPE = "MISSING_SECTOR"        # closed GAP_TYPES taxonomy (white_space.GAP_TYPES)

WINDOW_HOURS = 168                 # a week of news — coverage gaps are slow signals
SCAN_LIMIT = 400
GAP_TTL_DAYS = 30
_WHY_IT_MATTERS = ("A sector/theme recurring in the news that our covered "
                   "universe (symbol_profiles sectors, watch directives, topic "
                   "monitors) does not represent — a candidate blind spot.")
_PROPOSED_COVERAGE = ("Operator review: add a watch directive / topic monitor "
                      "or map representative symbols into the covered universe.")


# ── plumbing ─────────────────────────────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _table_exists(table: str) -> bool:
    try:
        return bool(_execute(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = %s",
            (table,), fetch="one"))
    except Exception:
        return False


def load_novelty_config(path: Path | str | None = None) -> dict[str, Any]:
    """Thresholds from config/hermes_discovery_schedule.json with conservative
    defaults (a broken config never widens intake)."""
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
        "industry_novelty_enabled": bool(cfg.get("industry_novelty_enabled", False)),
        "industry_novelty_window_hours": _i("industry_novelty_window_hours", WINDOW_HOURS),
        "industry_novelty_min_sources": _i("industry_novelty_min_sources", 2),
        "industry_novelty_min_mentions": _i("industry_novelty_min_mentions", 3),
        "industry_novelty_max_per_day": _i("industry_novelty_max_per_day", 5),
    }


# ── input collectors (defensive; missing table → [] + note) ─────────────────

def collect_observed_sectors(window_hours: int = WINDOW_HOURS,
                             notes: list[str] | None = None) -> list[dict[str, Any]]:
    """content_entity_links sector entities in the window, grouped with a
    distinct-source count (news_articles join) for the cross-source gate."""
    if not _table_exists("content_entity_links"):
        if notes is not None:
            notes.append("content_entity_links missing — novelty scan skipped")
        return []
    h = max(1, int(window_hours))
    return _rows(
        f"""SELECT l.entity_value, count(*) AS n,
                   count(DISTINCT COALESCE(a.source, 'unknown')) AS n_sources,
                   (array_agg(DISTINCT COALESCE(a.source, 'unknown')))[1:6] AS sources,
                   max(COALESCE(a.title, '')) AS sample
            FROM content_entity_links l
            LEFT JOIN news_articles a
              ON l.content_type = 'news_article' AND a.id = l.content_id
            WHERE l.entity_type = 'sector'
              AND l.entity_value IS NOT NULL
              AND l.created_at > now() - interval '{h} hours'
            GROUP BY 1
            ORDER BY count(*) DESC
            LIMIT %s""", (SCAN_LIMIT,))


def covered_sector_keys(notes: list[str] | None = None) -> set[str]:
    """Normalized keys of the covered universe: distinct symbol_profiles.sector
    plus active watch_directive / enabled topic_monitor keys."""
    covered: set[str] = set()
    if _table_exists("symbol_profiles"):
        try:
            for r in _rows("SELECT DISTINCT sector FROM symbol_profiles "
                           "WHERE sector IS NOT NULL AND sector <> ''"):
                key = dedupe.normalize_key(str(r.get("sector") or ""))
                if key:
                    covered.add(key)
        except Exception as e:  # pragma: no cover - defensive
            if notes is not None:
                notes.append(f"symbol_profiles coverage unavailable: {e}")
    covered |= entity_spikes.covered_keys(notes)
    return covered


# ── pure detection core (unit-testable without a DB) ─────────────────────────

def compute_novel(observed: list[dict[str, Any]], covered: set[str], *,
                  min_mentions: int = 3, min_sources: int = 2,
                  skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Filter observed sectors to those meeting the recurrence + cross-source
    bars whose normalized key is NOT in the covered set. Returns novel-sector
    dicts sorted by mentions desc."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in observed:
        value = str(r.get("entity_value") or "").strip()
        key = dedupe.normalize_key(value)
        if not value or not key:
            _skip("empty_value")
            continue
        n = int(r.get("n") or 0)
        n_sources = int(r.get("n_sources") or 0)
        if n < max(1, int(min_mentions)):
            _skip("low_recurrence")
            continue
        if n_sources < max(1, int(min_sources)):
            _skip("low_cross_source")
            continue
        if key in covered:
            _skip("already_covered")
            continue
        if key in seen:
            _skip("duplicate_in_run")
            continue
        seen.add(key)
        out.append({
            "sector": value,
            "mentions": n,
            "cross_source_count": n_sources,
            "sources": [str(s) for s in (r.get("sources") or []) if s][:6],
            "sample": str(r.get("sample") or "")[:200],
        })
    out.sort(key=lambda s: (-s["mentions"], -s["cross_source_count"]))
    return out


def build_payloads(novel: list[dict[str, Any]], *, limit: int,
                   skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Novel sectors → GAP_CANDIDATE (MISSING_SECTOR) payloads, capped at `limit`
    (industry_novelty_max_per_day)."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    payloads: list[dict[str, Any]] = []
    for g in novel:
        if len(payloads) >= max(1, int(limit)):
            _skip("run_cap")
            continue
        sector = g["sector"]
        why_missing = (f"'{sector}' recurred {g['mentions']}x across "
                       f"{g['cross_source_count']} distinct news sources in the "
                       f"window but matches nothing in the covered universe "
                       f"(symbol_profiles sectors, watch directives, topic monitors).")
        payloads.append(dict(
            candidate_type="GAP_CANDIDATE",
            label=f"Coverage gap: {sector}"[:120],
            summary=(f"{GAP_TYPE}: {why_missing}")[:400],
            evidence=[{"source_domain": s,
                       "note": f"{g['mentions']} mentions ({g['cross_source_count']} sources)"}
                      for s in g["sources"]] or
                     [{"source_domain": "news", "note": why_missing[:180]}],
            seed_symbols=[],
            meta={
                "producer": PRODUCER,
                "lane": LANE,
                "gap_type": GAP_TYPE,
                "why_missing": why_missing,
                "why_it_matters": _WHY_IT_MATTERS,
                "proposed_coverage": _PROPOSED_COVERAGE,
                "detector": "news_entities_vs_covered_taxonomy",
                "recurrence_count": g["mentions"],
                "source_count": g["cross_source_count"],
                "demand_sources": g["sources"],
                "keywords": [sector][:10],
            },
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=GAP_TTL_DAYS,
        ))
    return payloads


def _payload_domain(payload: dict[str, Any]) -> str:
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
                  config_path: Path | str | None = None) -> dict[str, Any]:
    """Full novelty pass. Shadow-first: industry_novelty_enabled=false forces
    effective dry-run (computes + reports, writes nothing)."""
    cfg = load_novelty_config(config_path)
    notes: list[str] = []
    skipped: dict[str, int] = {}

    effective_dry = bool(dry_run) or not cfg["industry_novelty_enabled"]
    if effective_dry and not dry_run:
        notes.append("industry_novelty_enabled=false — computed only, no writes "
                     "(operator flips the flag to go live)")

    observed = collect_observed_sectors(cfg["industry_novelty_window_hours"], notes)
    novel = compute_novel(
        observed, covered_sector_keys(notes),
        min_mentions=cfg["industry_novelty_min_mentions"],
        min_sources=cfg["industry_novelty_min_sources"],
        skipped=skipped)

    run_cap = int(limit) if limit else cfg["industry_novelty_max_per_day"]
    payloads = build_payloads(novel, limit=run_cap, skipped=skipped)

    by_domain: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        domain = _payload_domain(p)
        by_domain[domain] = by_domain.get(domain, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "domain": domain, "lane": LANE,
                   "gap_type": GAP_TYPE, "mentions": p["meta"]["recurrence_count"]}
        if not effective_dry:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({"id": row.get("id"), "status": row.get("status"),
                            "seen_count": row.get("seen_count")})
            upserted += 1
        candidates.append(summary)

    return {
        "mode": "industry_novelty",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "effective_dry_run": effective_dry,
        "enabled_in_schedule": cfg["industry_novelty_enabled"],
        "thresholds": {
            "window_hours": cfg["industry_novelty_window_hours"],
            "min_mentions": cfg["industry_novelty_min_mentions"],
            "min_sources": cfg["industry_novelty_min_sources"],
            "max_per_day": cfg["industry_novelty_max_per_day"],
        },
        "scanned_sectors": len(observed),
        "novel_detected": len(novel),
        "upserted": upserted,
        "would_upsert": len(candidates) if effective_dry else None,
        "by_domain": by_domain,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    }
