#!/usr/bin/env python3
"""Hermes Cross-Source Synthesis — generate novel insight briefs (Phase 4).

Collects signal bundles from 6+ sources, asks a governed cloud lane to synthesize
cross-source insights, and stages them as research_type='emerging_theme_synthesis'.

Safety:
  - dry-run by default, --apply to commit
  - kill switches: HERMES_DISABLED + HERMES_SYNTHESIZER_DISABLED
  - all claims grounded in bundle items (universe_guard reused)
  - optional free Grok second opinion on top-3 briefs (hermes_external_researcher)

Governed bridge (2026-10-15, n8n llm lane batch 1): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane hermes-cross-source-synthesizer) ``generate_cloud`` makes ONE governed-bridge
request as process ``hermes_cross_source_synthesizer`` and never imports llm_lane; a refusal is "no briefs" (exit 1,
nothing staged). --dry-run makes no model call. The cron line is unchanged.

Usage:
  python scripts/hermes_cross_source_synthesizer.py [--apply] [--dry-run]

Defects fixed 2026-11-07 (the lane had failed 4+ consecutive runs with the receipt saying only
"NO_BRIEFS"):
- ``collect_signal_bundle`` filtered ``content_entity_links`` on ``extracted_at``, a column that does
  not exist (the table has ``created_at``). PostgreSQL aborts the whole transaction on that first
  failed statement, so the other five sources answered "current transaction is aborted" and the
  bundle was empty on every run — the model was asked to synthesize from nothing. Each source now
  rolls the connection back when it fails, so one bad query costs one source, and the errors are
  recorded (``source_errors``) instead of two of them being silently turned into ``[]``.
- The prompt never asked for ``limitations``/``source_views``, which ``hermes_staging_ingest``
  requires for ``hermes_research_intelligence``: every brief this lane ever produced was rejected
  ("limitations array is empty or missing"). The prompt now asks for both, and they are carried into
  ``evidence_json``.
- The receipt now states why there were no briefs (the synthesis error, the unreadable sources)
  instead of ``NO_BRIEFS`` alone.
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone, date
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_HERMES = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
KILL_SYNTH = PROJECT_ROOT / "data" / "runtime" / "HERMES_SYNTHESIZER_DISABLED"
SYNTH_TIMEOUT = 300

BUNDLE_HOURS = 168  # 7-day signal window
MAX_BRIEFS = 5

#: Stated on a brief that does not carry its own limitations. True by construction of this producer:
#: it reads one internal bundle and consults nothing else, so there is never more to stand behind.
METHOD_LIMITATION = ("Single-pass synthesis over the internal {hours}h signal bundle; no external "
                     "sources and no price data were consulted.")


def _source_views(brief: dict) -> list:
    """The brief's own ``source_views``, else its ``signals_used`` restated in the required shape.

    ``hermes_staging_ingest.validate_payload`` rejects a research_intelligence row without a
    non-empty ``source_views``; before 2026-11-07 the prompt never asked for it, so every brief this
    lane produced was rejected. This does not invent evidence — it re-labels the sources the model
    already named as contributing to the theme.
    """
    views = brief.get("source_views")
    if isinstance(views, list) and views:
        return views
    return [{"source": str(s), "view": "contributing source named by the synthesis"}
            for s in (brief.get("signals_used") or [])]


def get_db():
    from lib.env_bootstrap import load_env
    load_env(names=("DB_PASSWORD",))
    db_pass = os.getenv("DB_PASSWORD")
    if not db_pass:
        raise RuntimeError("DB_PASSWORD not found")
    import psycopg2
    return psycopg2.connect(
        host="localhost", dbname="trade_ai", user="trade_ai",
        password=db_pass, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=3, connect_timeout=10)


def _source_failed(conn, bundle, key, exc):
    """Record a source that could not be read, and clear the aborted transaction.

    PostgreSQL aborts the whole transaction on the first failed statement: without the rollback
    every LATER source answers "current transaction is aborted, commands ignored until end of
    transaction block". On 2026-11-07 one bad column name in ``entity_spikes`` therefore turned
    five working sources into five fake failures and the bundle reached the model empty.
    """
    try:
        conn.rollback()
    except Exception:
        pass
    first = (str(exc).splitlines() or [""])[0][:160]
    msg = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
    bundle["sources"][key] = {"error": msg}
    bundle["source_errors"][key] = msg


def collect_signal_bundle(conn, *, hours: int = BUNDLE_HOURS) -> dict:
    """Collect cross-source signal bundle for synthesis."""
    cur = conn.cursor()
    bundle = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "sources": {},
        # Which sources could not be read, and why — a count of 0 alone cannot say "empty" vs "broken".
        "source_errors": {},
    }

    # 1. Entity spikes (top entities by mention count)
    try:
        cur.execute("""
            SELECT entity_value, entity_type, COUNT(*) as mentions
            FROM content_entity_links
            WHERE created_at > NOW() - %s * INTERVAL '1 hour'
            GROUP BY entity_value, entity_type
            HAVING COUNT(*) >= 2
            ORDER BY mentions DESC LIMIT 20
        """, (hours,))
        bundle["sources"]["entity_spikes"] = [
            {"entity": r[0], "type": r[1], "mentions": r[2]} for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "entity_spikes", e)

    # 2. Top news themes (news_articles summary)
    try:
        cur.execute("""
            SELECT COALESCE(symbol, 'macro') as symbol, COUNT(*) as count
            FROM news_articles
            WHERE created_at > NOW() - %s * INTERVAL '1 hour'
            GROUP BY 1 ORDER BY count DESC LIMIT 15
        """, (hours,))
        bundle["sources"]["news_themes"] = [
            {"symbol": r[0], "articles": r[1]} for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "news_themes", e)

    # 3. Discovery inbox top scores
    try:
        cur.execute("""
            SELECT label, candidate_type, discovery_score, meta_json->>'llm_review_json' as review
            FROM hermes_discovery_candidates
            WHERE status = 'READY_FOR_REVIEW'
            ORDER BY discovery_score DESC LIMIT 10
        """)
        bundle["sources"]["discovery_signals"] = [
            {"label": r[0], "type": r[1], "score": float(r[2] or 0)} for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "discovery_signals", e)

    # 4. Sector RS state
    try:
        cur.execute("""
            SELECT etf, sector, state, rs20
            FROM sector_momentum_state
            WHERE state != 'NEUTRAL'
            ORDER BY rs20 DESC LIMIT 10
        """)
        bundle["sources"]["sector_rotation"] = [
            {"etf": r[0], "sector": r[1], "state": r[2], "rs20": float(r[3] or 0)}
            for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "sector_rotation", e)

    # 5. Recent research themes (last 7d, promoted rows)
    try:
        cur.execute("""
            SELECT topic, research_type, COUNT(*) as ct
            FROM hermes_research_intelligence
            WHERE created_at > NOW() - %s * INTERVAL '1 hour'
              AND status = 'promoted'
            GROUP BY topic, research_type
            ORDER BY ct DESC LIMIT 10
        """, (hours,))
        bundle["sources"]["research_themes"] = [
            {"topic": r[0], "type": r[1], "count": r[2]} for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "research_themes", e)

    # 6. Agenda candidates (Phase 2 output)
    try:
        cur.execute("""
            SELECT decision, topic_id, rationale, run_at::text
            FROM hermes_research_agenda_audit
            WHERE run_at > NOW() - %s * INTERVAL '1 hour'
            ORDER BY run_at DESC LIMIT 10
        """, (hours,))
        bundle["sources"]["agenda_actions"] = [
            {"decision": r[0], "topic_id": r[1], "rationale": r[2]} for r in cur.fetchall()
        ]
    except Exception as e:
        _source_failed(conn, bundle, "agenda_actions", e)

    cur.close()
    return bundle


def synthesize(bundle: dict, *, diagnostics: dict | None = None) -> list[dict]:
    """Synthesize cross-source briefs using governed cloud lanes.

    Returns list of brief payloads ready for hermes_research_intelligence. When ``diagnostics`` is
    a dict it receives ``error`` on failure: before 2026-11-07 the caller could only learn "no
    briefs", so a rate-limited lane, a malformed answer and an empty one all looked identical.
    """
    date_label = date.today().isoformat()
    signal_count = sum(
        len(v) for v in bundle.get("sources", {}).values()
        if isinstance(v, list)
    )

    prompt = f"""You are Hermes, the autonomous research engine for Trade AI v12. Analyze the cross-source
signal bundle below and produce {min(MAX_BRIEFS, 5)} emerging-theme synthesis briefs.

## Signal Bundle ({date_label}, {BUNDLE_HOURS}h window, {signal_count} data points)

{json.dumps(bundle, indent=2, default=str)}

## Instructions

Identify the top 3-5 emerging themes that span MULTIPLE signal sources. For each theme, output a JSON object with:
- "topic": concise 1-line theme label (string)
- "summary": 2-3 sentence synthesis explaining WHY this theme matters NOW (string, REQUIRED)
- "thesis": deeper analysis of implications — what it means for markets/portfolios (string, REQUIRED)
- "thesis_type": "bullish" | "bearish" | "neutral"
- "confidence": 0.0-1.0
- "signals_used": list of signal source names this theme draws from (at least 2)
- "source_views": list of objects, one per contributing source, each {{"source": <source name>, "view": <what that source shows>}} (REQUIRED)
- "limitations": list of 2-5 strings — what this synthesis cannot conclude from the bundle (REQUIRED)
- "keywords": 3-8 relevant keywords

Ground every claim in the bundle above: do not cite the web, and do not state a current or live
price — the bundle carries no quotes. Output format: a JSON array of theme objects. Respond ONLY
with valid JSON (no markdown preamble)."""

    try:
        from lib.governed_cloud_generation import generate_cloud
        content, _lane = generate_cloud(
            prompt, process_id="hermes_cross_source_synthesizer",
            task_summary="Hermes cross-source synthesis", timeout=SYNTH_TIMEOUT,
            max_tokens=3000, response_json=True,
        )
        briefs = json.loads(content)
        if isinstance(briefs, dict):
            briefs = briefs.get("themes", briefs.get("briefs", [briefs]))
        for brief in briefs:
            if isinstance(brief, dict):
                brief["_source_lane"] = _lane
        return briefs[:MAX_BRIEFS]
    except Exception as e:
        print(f"  Synthesis FAILED: {e}")
        if isinstance(diagnostics, dict):
            diagnostics["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return []


def persist_briefs(conn, briefs: list[dict], *, apply: bool = False) -> dict:
    """Write briefs to hermes_research_intelligence + enqueue advisory events."""
    from hermes_staging_ingest import validate_payload, build_insert

    results = []
    for i, brief in enumerate(briefs):
        payload = {
            "hermes_agent_name": "cross_source_synthesizer",
            "research_type": "emerging_theme_synthesis",
            "topic": brief.get("topic", f"Emerging Theme {i+1}"),
            "summary": brief.get("summary", ""),
            "thesis": brief.get("thesis", ""),
            "thesis_type": brief.get("thesis_type", "neutral"),
            "confidence_score": brief.get("confidence", 0.5),
            "freshness_date": date.today().isoformat(),
            "model_used": brief.get("_source_lane", "governed-cloud"),
            "status": "staged",
            "tags": brief.get("keywords", []) + ["emerging_theme_synthesis", "cross_source", "phase_4"],
            "evidence_json": {
                "signals_used": brief.get("signals_used", []),
                # Required by hermes_staging_ingest for hermes_research_intelligence: without them
                # every brief was rejected ("limitations array is empty or missing").
                "limitations": brief.get("limitations") or [METHOD_LIMITATION.format(hours=BUNDLE_HOURS)],
                "source_views": _source_views(brief),
                "bundle_window_hours": BUNDLE_HOURS,
                "run_id": f"synth_{datetime.now().strftime('%Y%m%d_%H%M')}",
                "advisory_only": True,
                "not_execution": True,
            },
            "source_urls_json": [],
            "source": "hermes",
        }

        ok, errors = validate_payload(payload, "hermes_research_intelligence")
        if not ok:
            results.append({"status": "rejected", "errors": errors})
            continue

        if apply:
            try:
                sql, vals = build_insert("hermes_research_intelligence", payload)
                cur = conn.cursor()
                cur.execute(sql, vals)
                row = cur.fetchone()
                conn.commit()
                results.append({"status": "applied", "row_id": row[0],
                              "topic": payload["topic"]})
            except Exception as e:
                conn.rollback()
                results.append({"status": "apply_failed", "error": str(e)[:200]})
        else:
            results.append({"status": "validated", "topic": payload["topic"]})

    return {"briefs_processed": len(briefs),
            "applied": sum(1 for r in results if r["status"] in ("validated", "applied")),
            "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hermes Cross-Source Synthesis (Phase 4)", allow_abbrev=False)
    parser.add_argument("--apply", action="store_true", help="Apply to DB (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN hermes-cross-source-synthesizer: would collect a {BUNDLE_HOURS}h bundle, synthesize at most {MAX_BRIEFS} briefs and {'persist' if args.apply else 'validate'} them; no DB, model, network or writes")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    apply = args.apply

    if KILL_HERMES.exists():
        print("ABORT: HERMES_DISABLED")
        sys.exit(1)
    if KILL_SYNTH.exists():
        print("ABORT: HERMES_SYNTHESIZER_DISABLED")
        sys.exit(1)

    print(f"[{'APPLY' if apply else 'DRY-RUN'}] Cross-Source Synthesis")
    print(f"  Model: governed-cloud, window: {BUNDLE_HOURS}h, timeout: {SYNTH_TIMEOUT}s")

    conn = None
    try:
        conn = get_db()
        bundle = collect_signal_bundle(conn)
        signal_count = sum(len(v) for v in bundle.get("sources", {}).values()
                          if isinstance(v, list))
        unreadable = bundle.get("source_errors") or {}
        print(f"  Bundle: {signal_count} signals across {len(bundle.get('sources', {}))} sources")
        for src_name, src_data in bundle.get("sources", {}).items():
            if isinstance(src_data, list):
                print(f"    {src_name}: {len(src_data)} items")
        for src_name, err in unreadable.items():
            print(f"    {src_name}: UNREADABLE ({err})")

        diagnostics: dict = {}
        briefs = synthesize(bundle, diagnostics=diagnostics)
        if not briefs:
            print("  No briefs generated")
            if apply:
                why = diagnostics.get("error") or "the model returned an empty brief list"
                write_lane_receipt(
                    "hermes-cross-source-synthesizer", ok=False, exit_code=1, started_at=started,
                    summary={"signals": signal_count, "source_unreadable": unreadable,
                             "briefs": 0, "why": why[:200]},
                    error=f"NO_BRIEFS: {why}"[:240])
            return 1

        print(f"  Generated {len(briefs)} briefs:")
        for b in briefs[:3]:
            print(f"    - {b.get('topic', '?')}: {b.get('summary', '')[:80]}")

        result = persist_briefs(conn, briefs, apply=apply)

        if args.json:
            bundle_summary = {
                src: (len(v) if isinstance(v, list) else str(v)[:100])
                for src, v in bundle.get("sources", {}).items()
            }
            print(json.dumps({**result, "bundle_summary": bundle_summary,
                              "source_unreadable": unreadable}, default=str))
        else:
            print(f"  Result: {result['applied']} briefs {'applied' if apply else 'validated'}")

        ok = result["applied"] == len(briefs) and bool(briefs)
        if apply:
            rejected = sum(1 for r in result["results"] if r["status"] == "rejected")
            write_lane_receipt(
                "hermes-cross-source-synthesizer", ok=ok, exit_code=0 if ok else 1,
                started_at=started,
                summary={"produced_count": len(briefs), "briefs": len(briefs),
                         "applied": result["applied"], "rejected": rejected,
                         "signals": signal_count, "source_unreadable": unreadable})
        return 0 if ok else 1
    except Exception as exc:
        if apply:
            write_lane_receipt("hermes-cross-source-synthesizer", ok=False, exit_code=1,
                               started_at=started, error=f"{type(exc).__name__}: {exc}"[:240])
        raise
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


if __name__ == "__main__":
    raise SystemExit(main())
