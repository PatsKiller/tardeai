#!/usr/bin/env python3
"""hermes_discovery_ingestors.py — adapters: existing producers → Discovery Inbox.

Converts what today's producers ALREADY emit into inbox candidates. Additive
observation only: no producer is modified, and every producer's existing write
path stays intact — the inbox just watches the same outputs.

  --source  research_sources registry rows written by hermes_source_curation.py
            (web domains in candidate state → SOURCE_CANDIDATE; key-gated /
            dormant connectors → CONNECTOR_CANDIDATE)
  --trend   hermes_directive_hits_staging rows staged by
            hermes_directive_discovery.py / think_tank_prospect_discovery.py,
            grouped per directive → TREND_CANDIDATE (keywords, seed symbols,
            momentum from narrative_strength)
  --ticker  the audit-flagged shape-accepted extraction
            (intel_auto_discovery.extract_tickers_from_text) re-applied over
            recent news + Hermes research text → TICKER_CANDIDATE; real
            validation happens in inbox.upsert_candidate via validate_ticker
  --topic   recurring hermes_research_intelligence topics not yet registered in
            topic_monitor → TOPIC_CANDIDATE

Idempotency comes free from inbox.upsert_candidate (unique candidate_type +
normalized_key → seen_count bump + evidence merge). All DB reads go through
db_adapter._execute — one statement, immediate commit, no held transactions.
Advisory-only: never imports broker modules, never writes producer tables.

Usage:
  python3 scripts/hermes_discovery_ingestors.py --run [--source|--trend|--ticker|--topic]
                                                [--limit N] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import inbox  # noqa: E402


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    from db_adapter import _execute
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _clamp01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


def _upsert_all(payloads: list[dict[str, Any]], *, actor: str,
                dry_run: bool) -> dict[str, Any]:
    """Shared upsert loop: dry-run lists the would-be candidates, live writes."""
    out = {"scanned": len(payloads), "upserted": 0, "dry_run": bool(dry_run),
           "candidates": []}
    for p in payloads:
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "source_domain": p.get("source_domain")}
        if dry_run:
            out["candidates"].append(summary)
            continue
        row = inbox.upsert_candidate(actor=actor, **p)
        summary.update({"id": row["id"], "status": row["status"],
                        "seen_count": row["seen_count"],
                        "score": float(row["discovery_score"]) if row.get("discovery_score") is not None else None})
        out["candidates"].append(summary)
        out["upserted"] += 1
    return out


# ── (a) source curation registry → SOURCE / CONNECTOR candidates ─────────────

def ingest_sources(limit: int = 50, dry_run: bool = False) -> dict[str, Any]:
    """research_sources rows (the hermes_source_curation.py output registry).

    Web domains still in candidate state (not active, not retired/rejected)
    become SOURCE_CANDIDATEs carrying credibility/specialty/active state.
    Non-web connector rows that are dormant / key-gated become
    CONNECTOR_CANDIDATEs (they need an operator decision + a key to go live).
    """
    # Candidate-state rows only, filtered in SQL (the registry is dominated by
    # active/ruled-out rows, so a python-side filter over a top-N slice sees none):
    #   web:   inactive and not already ruled out by curation (retired/rejected)
    #   other: inactive key-gated/dormant connectors awaiting a key + decision
    rows = _rows(
        """SELECT id, source_type, source_name, source_url, credibility_score,
                  specialty, active, notes
           FROM research_sources
           WHERE active = FALSE AND (
                 (source_type = 'web'
                  AND COALESCE(notes, '') NOT ILIKE '%%retired%%'
                  AND COALESCE(notes, '') NOT ILIKE '%%rejected%%')
              OR (source_type <> 'web'
                  AND (COALESCE(notes, '') ILIKE '%%key%%'
                       OR COALESCE(notes, '') ILIKE '%%dormant%%')))
           ORDER BY credibility_score DESC NULLS LAST, id DESC
           LIMIT %s""", (max(1, int(limit)) * 2,))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        if len(payloads) >= limit:
            break
        notes = (r.get("notes") or "")
        low_notes = notes.lower()
        specialty = r.get("specialty") or []
        meta = {"registry_id": r["id"], "source_type": r["source_type"],
                "credibility": float(r.get("credibility_score") or 0),
                "specialty": list(specialty),
                "active": bool(r.get("active")),
                "registry_state": "active" if r.get("active") else "dormant"}
        if r["source_type"] == "web":
            payloads.append(dict(
                candidate_type="SOURCE_CANDIDATE",
                label=r["source_name"],
                summary=notes[:400] or None,
                source_domain=r["source_name"],
                source_url=r.get("source_url"),
                evidence=[{"source_domain": r["source_name"],
                           "note": f"research_sources registry: {notes[:160]}"}],
                meta=meta,
                signals={"source_quality": _clamp01(float(r.get("credibility_score") or 0) / 100.0)},
            ))
        else:
            meta["key_gated"] = ("key" in low_notes) or ("dormant" in low_notes)
            payloads.append(dict(
                candidate_type="CONNECTOR_CANDIDATE",
                label=r["source_name"],
                summary=notes[:400] or None,
                source_domain=None,
                source_url=r.get("source_url"),
                evidence=[{"note": f"connector registry ({r['source_type']}): {notes[:160]}"}],
                meta=meta,
            ))
    return {"type": "source", **_upsert_all(payloads, actor="ingestor:source_curation",
                                            dry_run=dry_run)}


# ── (b) directive/think-tank staging → TREND candidates ──────────────────────

def ingest_trends(limit: int = 25, dry_run: bool = False,
                  days: int = 14) -> dict[str, Any]:
    """hermes_directive_hits_staging (output of hermes_directive_discovery.py +
    think_tank_prospect_discovery.py) grouped per directive → TREND_CANDIDATE.

    Momentum = avg narrative_strength of recent staged hits (signals dict →
    scoring's trend_momentum component). meta.existing_directive_id lets
    promote_watch_directive reuse the directive instead of duplicating it.
    """
    rows = _rows(
        f"""SELECT d.id AS directive_id, d.label, d.spec,
                   count(*) AS hits,
                   avg(s.narrative_strength) AS momentum,
                   array_agg(DISTINCT s.symbol) AS symbols,
                   jsonb_agg(jsonb_build_object(
                       'symbol', s.symbol,
                       'thesis', LEFT(COALESCE(s.thesis, ''), 120),
                       'producer', s.source_detail->>'producer')
                       ORDER BY s.proposed_at DESC) AS evidence
            FROM hermes_directive_hits_staging s
            JOIN watch_directives d ON d.id = s.directive_id
            WHERE s.proposed_at > now() - interval '{int(days)} days'
            GROUP BY d.id, d.label, d.spec
            ORDER BY count(*) DESC LIMIT %s""", (max(1, int(limit)),))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        spec = r.get("spec") or {}
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception:
                spec = {}
        keywords = [k for k in (spec.get("keywords") or []) if k]
        evidence = list(r.get("evidence") or [])[:10]
        producers = sorted({e.get("producer") for e in evidence if e.get("producer")})
        payloads.append(dict(
            candidate_type="TREND_CANDIDATE",
            label=r["label"],
            summary=(f"{r['hits']} staged hit(s) in {days}d from "
                     f"{', '.join(producers) or 'hermes staging'}"),
            evidence=evidence,
            seed_symbols=[s for s in (r.get("symbols") or []) if s][:12],
            meta={"existing_directive_id": r["directive_id"],
                  "keywords": keywords[:10],
                  "producers": producers,
                  "staged_hits": int(r["hits"])},
            signals={"trend_momentum": _clamp01(r.get("momentum"))},
        ))
    return {"type": "trend", **_upsert_all(payloads, actor="ingestor:directive_staging",
                                           dry_run=dry_run)}


# ── (c) shape-accepted ticker extraction → TICKER candidates ─────────────────

def ingest_tickers(limit: int = 25, dry_run: bool = False, days: int = 2,
                   min_mentions: int = 2) -> dict[str, Any]:
    """Re-applies the audit-flagged shape-accepted extractor
    (intel_auto_discovery.extract_tickers_from_text: regex + blacklist, NO
    existence check) over recent news + Hermes research text. Candidates flow
    through inbox.upsert_candidate, where validate_ticker supplies the real
    symbol_profiles verdict — fabricated tokens land in NEEDS_VALIDATION
    instead of anyone's watchlist.

    Reads via db_adapter (the producer's own psycopg2/.env connection helper is
    deliberately not used); the producer's direct-add path is left untouched.
    """
    from intel_auto_discovery import extract_tickers_from_text

    known: set[str] = set()
    for sql in ("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active = TRUE",
                "SELECT DISTINCT symbol FROM watchlist_items"):
        known.update((r.get("symbol") or "").upper() for r in _rows(sql))

    texts = _rows(
        f"""SELECT COALESCE(title, '') || ' ' || COALESCE(summary, '') AS text,
                   COALESCE(source, 'news') AS source
            FROM news_articles WHERE created_at > now() - interval '{int(days)} days'
            ORDER BY created_at DESC LIMIT 500""")
    texts += _rows(
        f"""SELECT COALESCE(topic, '') || ' ' || COALESCE(summary, '') AS text,
                   COALESCE(source, 'hermes_research') AS source
            FROM hermes_research_intelligence
            WHERE created_at > now() - interval '{int(days)} days'
            ORDER BY created_at DESC LIMIT 300""")

    mentions: dict[str, int] = defaultdict(int)
    sources: dict[str, set[str]] = defaultdict(set)
    snippets: dict[str, str] = {}
    for row in texts:
        text = row.get("text") or ""
        for sym in extract_tickers_from_text(text):
            sym = sym.upper()
            if sym in known:
                continue
            mentions[sym] += 1
            sources[sym].add(row.get("source") or "unknown")
            snippets.setdefault(sym, text.strip()[:160])

    ranked = sorted(mentions.items(), key=lambda kv: -kv[1])
    payloads: list[dict[str, Any]] = []
    for sym, n in ranked:
        if n < max(1, int(min_mentions)):
            continue
        if len(payloads) >= limit:
            break
        payloads.append(dict(
            candidate_type="TICKER_CANDIDATE",
            label=sym,
            summary=f"{n} mention(s) in {days}d intel/news: {snippets.get(sym, '')}",
            evidence=[{"source_domain": s, "note": f"mentioned via {s}"}
                      for s in sorted(sources[sym])[:6]],
            meta={"mentions": n,
                  "extraction": "intel_auto_discovery.extract_tickers_from_text (shape-accepted)"},
        ))
    return {"type": "ticker", **_upsert_all(payloads, actor="ingestor:ticker_extraction",
                                            dry_run=dry_run)}


# ── (d) recurring research topics → TOPIC candidates ─────────────────────────

def ingest_topics(limit: int = 25, dry_run: bool = False,
                  days: int = 14) -> dict[str, Any]:
    """Recurring hermes_research_intelligence topics (>= 2 rows in the window)
    that are not yet in topic_monitor → TOPIC_CANDIDATE."""
    registered = {(r.get("display_name") or "").strip().lower()
                  for r in _rows("SELECT display_name FROM topic_monitor")}
    rows = _rows(
        f"""SELECT topic, count(*) AS n, max(created_at) AS last_seen,
                   array_agg(DISTINCT COALESCE(source, 'hermes')) AS sources,
                   max(COALESCE(summary, '')) AS sample_summary
            FROM hermes_research_intelligence
            WHERE topic IS NOT NULL AND length(topic) > 6
              AND created_at > now() - interval '{int(days)} days'
            GROUP BY topic HAVING count(*) >= 2
            ORDER BY count(*) DESC LIMIT %s""", (max(1, int(limit)) * 2,))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        if len(payloads) >= limit:
            break
        topic = (r.get("topic") or "").strip()
        if not topic or topic.lower() in registered:
            continue
        payloads.append(dict(
            candidate_type="TOPIC_CANDIDATE",
            label=topic[:120],
            summary=(r.get("sample_summary") or "")[:300] or None,
            evidence=[{"source_domain": s, "note": f"{r['n']} research rows in {days}d"}
                      for s in (r.get("sources") or [])[:5]],
            meta={"research_rows": int(r["n"]),
                  "last_seen": str(r.get("last_seen")),
                  "keywords": [topic]},
        ))
    return {"type": "topic", **_upsert_all(payloads, actor="ingestor:research_topics",
                                           dry_run=dry_run)}


# ── CLI ──────────────────────────────────────────────────────────────────────

INGESTORS = {"source": ingest_sources, "trend": ingest_trends,
             "ticker": ingest_tickers, "topic": ingest_topics}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run the selected ingestors")
    for name in INGESTORS:
        ap.add_argument(f"--{name}", action="store_true",
                        help=f"run the {name} ingestor (default: all)")
    ap.add_argument("--limit", type=int, default=25, help="max candidates per ingestor")
    ap.add_argument("--dry-run", action="store_true",
                    help="list would-be candidates without writing the inbox")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    selected = [n for n in INGESTORS if getattr(args, n)] or list(INGESTORS)
    report: dict[str, Any] = {"dry_run": bool(args.dry_run), "results": {}}
    for name in selected:
        try:
            report["results"][name] = INGESTORS[name](limit=args.limit,
                                                      dry_run=args.dry_run)
        except Exception as e:  # one broken producer never blocks the others
            report["results"][name] = {"type": name, "error": str(e)[:200]}
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for name, res in report["results"].items():
            if res.get("error"):
                print(f"[{name}] ERROR: {res['error']}")
                continue
            print(f"[{name}] scanned={res['scanned']} upserted={res['upserted']} "
                  f"dry_run={res['dry_run']}")
            for c in res["candidates"][:10]:
                extra = f" #{c['id']} {c['status']}" if "id" in c else ""
                print(f"    {c['candidate_type']} {c['label']!r}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
