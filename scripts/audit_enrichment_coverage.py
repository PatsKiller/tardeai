#!/usr/bin/env python3
"""audit_enrichment_coverage.py — the agent that checks the checkers (operator order 2026-06-12:
"fix root cause, have agents check audit on a regular!").

For every symbol in the canonical watch universe (watch_universe.py), verifies presence/freshness
across each enrichment surface and ALERTS on gaps — so a symbol can never again sit on the
watchlist with no analyst pill / no news / no technicals / no LLM coverage and nobody noticing.

Surfaces audited (per symbol; DIRECTIVE symbols held to the strictest bar):
  technicals  — ticker_snapshot_daily rsi within 3d (or marked delisted -> exempt)
  analyst     — pro-analyst read model has the symbol (or 'none' rating recorded = checked-but-thin)
  news        — news item within 7d (directive + held symbols only; full universe would be noise)
  llm_curation— hermes_external_research within 14d (DIRECTIVE symbols only — the operator promise)
  protection  — protection_advisory within 7d (HELD real-account equities only)

  python3 scripts/audit_enrichment_coverage.py [--alert] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def run(alert=False, as_json=False):
    from db_adapter import _get_conn
    import watch_universe as wu
    conn = _get_conn(); cur = conn.cursor()
    uni = wu.symbols(cur)
    directives = wu.directive_symbols(cur)

    # held real-account equities (for the protection-advisory bar)
    held = set()
    try:
        h = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
        held = {(x.get("symbol") or "").upper() for x in h.get("holdings", [])
                if str(x.get("account", "")).startswith(("schwab", "fidelity"))
                and not x.get("is_cash") and float(x.get("market_value") or 0) > 100}
    except Exception:
        pass

    def col(q, params=None):
        # params=None ⇒ no paramstyle processing (a literal % in LIKE would otherwise IndexError)
        cur.execute(q) if params is None else cur.execute(q, params)
        return {r[0] for r in cur.fetchall()}

    tech_ok = col("""SELECT DISTINCT symbol FROM ticker_snapshot_daily
                     WHERE rsi IS NOT NULL AND snapshot_date > CURRENT_DATE - 3""")
    tech_exempt = col("""SELECT DISTINCT symbol FROM ticker_snapshot_daily
                         WHERE (data->>'delisted_or_no_data')::bool IS TRUE""")
    analyst_ok = set()
    try:
        d = json.loads((PROJECT_ROOT / "data/runtime/pro_analyst_pills_latest.json").read_text())
        analyst_ok = {p["symbol"] for p in d.get("pills", [])}
    except Exception:
        pass
    news_ok = col("""SELECT DISTINCT symbol FROM news_articles
                     WHERE published_at > now() - interval '7 days' AND symbol IS NOT NULL""") \
        if _table_exists(cur, "news_articles") else set()
    llm_ok = col("""SELECT DISTINCT symbol FROM hermes_external_research
                    WHERE created_at > now() - interval '14 days' AND status='sent'""")
    # latest agent synthesis is a dead-model failure ("LLM error: All providers failed", e.g. the
    # uninstalled qwen era) — caught here so it can never again sit unretried (operator 2026-06-12)
    synth_err = col("""SELECT symbol FROM (
                         SELECT DISTINCT ON (symbol) symbol, synthesis_narrative
                         FROM watchlist_final_synthesis ORDER BY symbol, created_at DESC) s
                       WHERE synthesis_narrative LIKE 'LLM error%'""")
    prot_ok = col("""SELECT DISTINCT symbol FROM hermes_research_intelligence
                     WHERE research_type='protection_advisory' AND created_at > now() - interval '7 days'""")

    gaps = []
    for s in sorted(uni):
        miss = []
        if s not in tech_ok and s not in tech_exempt:
            miss.append("technicals")
        if s not in analyst_ok:
            miss.append("analyst")
        if (s in directives or s in held) and news_ok and s not in news_ok:
            miss.append("news_7d")
        if s in directives and s not in llm_ok:
            miss.append("llm_curation")
        if s in held and s not in prot_ok and s in tech_ok:
            miss.append("protection_advisory")
        if s in synth_err:
            miss.append("synthesis_failed_needs_retry")
        if miss:
            gaps.append({"symbol": s, "directive": s in directives, "held": s in held, "missing": miss})

    directive_gaps = [g for g in gaps if g["directive"]]
    report = {"universe": len(uni), "directives": len(directives), "held": len(held),
              "symbols_with_gaps": len(gaps), "directive_gaps": directive_gaps,
              "gaps": gaps[:60]}
    print(json.dumps(report, indent=None if as_json else 1, default=str))
    if alert and directive_gaps:
        _alert(directive_gaps)
    return report


def _table_exists(cur, name):
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (name,))
    return cur.fetchone() is not None


def _alert(directive_gaps):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    lines = [f"• {g['symbol']}: missing {', '.join(g['missing'])}" for g in directive_gaps[:12]]
    msg = (
        "⚠️ *ENRICHMENT COVERAGE GAPS — operator-directive symbols*\n"
        + "\n".join(lines)
        + "\n\nFix: the relevant fetcher skipped the canonical watch "
          "universe (scripts/watch_universe.py)."
    )
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="audit_enrichment_coverage",
                subject_key="ops:enrichment_coverage",
                retention_class="operational", severity="warning",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if ok:
            print(f"alert sent ({len(directive_gaps)} directive gaps)")
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    run(alert=a.alert, as_json=a.json)
