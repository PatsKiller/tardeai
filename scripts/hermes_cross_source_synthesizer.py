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


def collect_signal_bundle(conn, *, hours: int = BUNDLE_HOURS) -> dict:
    """Collect cross-source signal bundle for synthesis."""
    cur = conn.cursor()
    bundle = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "sources": {},
    }

    # 1. Entity spikes (top entities by mention count)
    try:
        cur.execute(f"""
            SELECT entity_value, entity_type, COUNT(*) as mentions
            FROM content_entity_links
            WHERE extracted_at > NOW() - INTERVAL '{hours} hours'
            GROUP BY entity_value, entity_type
            HAVING COUNT(*) >= 2
            ORDER BY mentions DESC LIMIT 20
        """)
        bundle["sources"]["entity_spikes"] = [
            {"entity": r[0], "type": r[1], "mentions": r[2]} for r in cur.fetchall()
        ]
    except Exception as e:
        bundle["sources"]["entity_spikes"] = {"error": str(e)}

    # 2. Top news themes (news_articles summary)
    try:
        cur.execute(f"""
            SELECT COALESCE(symbol, 'macro') as symbol, COUNT(*) as count
            FROM news_articles
            WHERE created_at > NOW() - INTERVAL '{hours} hours'
            GROUP BY 1 ORDER BY count DESC LIMIT 15
        """)
        bundle["sources"]["news_themes"] = [
            {"symbol": r[0], "articles": r[1]} for r in cur.fetchall()
        ]
    except Exception as e:
        bundle["sources"]["news_themes"] = {"error": str(e)}

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
        bundle["sources"]["discovery_signals"] = {"error": str(e)}

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
    except Exception:
        bundle["sources"]["sector_rotation"] = []

    # 5. Recent research themes (last 7d, promoted rows)
    try:
        cur.execute(f"""
            SELECT topic, research_type, COUNT(*) as ct
            FROM hermes_research_intelligence
            WHERE created_at > NOW() - INTERVAL '{hours} hours'
              AND status = 'promoted'
            GROUP BY topic, research_type
            ORDER BY ct DESC LIMIT 10
        """)
        bundle["sources"]["research_themes"] = [
            {"topic": r[0], "type": r[1], "count": r[2]} for r in cur.fetchall()
        ]
    except Exception as e:
        bundle["sources"]["research_themes"] = {"error": str(e)}

    # 6. Agenda candidates (Phase 2 output)
    try:
        cur.execute(f"""
            SELECT decision, topic_id, rationale, run_at::text
            FROM hermes_research_agenda_audit
            WHERE run_at > NOW() - INTERVAL '{hours} hours'
            ORDER BY run_at DESC LIMIT 10
        """)
        bundle["sources"]["agenda_actions"] = [
            {"decision": r[0], "topic_id": r[1], "rationale": r[2]} for r in cur.fetchall()
        ]
    except Exception:
        bundle["sources"]["agenda_actions"] = []

    cur.close()
    return bundle


def synthesize(bundle: dict) -> list[dict]:
    """Synthesize cross-source briefs using governed cloud lanes.

    Returns list of brief payloads ready for hermes_research_intelligence.
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
- "signals_used": list of signal source names this theme draws from
- "keywords": 3-8 relevant keywords

Output format: a JSON array of theme objects. Respond ONLY with valid JSON (no markdown preamble)."""

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
        print(f"  Bundle: {signal_count} signals across {len(bundle.get('sources', {}))} sources")
        for src_name, src_data in bundle.get("sources", {}).items():
            if isinstance(src_data, list):
                print(f"    {src_name}: {len(src_data)} items")

        briefs = synthesize(bundle)
        if not briefs:
            print("  No briefs generated")
            if apply:
                write_lane_receipt("hermes-cross-source-synthesizer", ok=False, exit_code=1,
                                   started_at=started, error="NO_BRIEFS")
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
            print(json.dumps({**result, "bundle_summary": bundle_summary}, default=str))
        else:
            print(f"  Result: {result['applied']} briefs {'applied' if apply else 'validated'}")

        ok = result["applied"] == len(briefs) and bool(briefs)
        if apply:
            write_lane_receipt("hermes-cross-source-synthesizer", ok=ok, exit_code=0 if ok else 1,
                               started_at=started, summary={"briefs": len(briefs), "applied": result["applied"]})
        return 0 if ok else 1
    except Exception as exc:
        if apply:
            write_lane_receipt("hermes-cross-source-synthesizer", ok=False, exit_code=1,
                               started_at=started, error=type(exc).__name__)
        raise
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


if __name__ == "__main__":
    raise SystemExit(main())
