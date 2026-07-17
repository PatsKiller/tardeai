#!/usr/bin/env python3
"""Nightly system rollup snapshot + Daily System Digest (Reports v3 WS-B).

1. Computes the 24h whole-system rollup (api_v2._system_rollup — same payload the
   Reports → System tab renders, so the digest can never disagree with the page).
2. Upserts ONE row/day into system_rollup_daily (trends corpus for the sparklines).
3. Renders a deterministic markdown digest → data/portfolios/reports/system_digest_<date>.md
   (indexed by the report catalog family 'system_digest') + an ai_reports row (archive).
4. Telegram gets ONE line (counts + archive pointer), never the body.

Deterministic, zero LLM, advisory-only. Cron: 20:40 daily.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _headlines(panels: dict) -> dict:
    g = lambda n: (panels.get(n) or {}).get("data") or {}
    pipes = g("pipelines").get("rows") or []
    agents = g("agents").get("rows") or []
    props = g("proposals").get("rows") or []
    alerts = g("alerts").get("rows") or []
    return {
        "pipelines_run": sum(int(r.get("runs") or 0) for r in pipes),
        "pipeline_failures": sum(int(r.get("failures") or 0) for r in pipes),
        "agent_analyses": sum(int(r.get("analyses") or 0) for r in agents),
        "proposals": sum(int(r.get("cnt") or 0) for r in props),
        "paper_closed": g("paper_trades").get("closed", 0),
        "paper_pnl": g("paper_trades").get("pnl"),
        "alerts_raw": sum(int(r.get("n") or 0) for r in alerts),
        "research_items": (g("research").get("hermes_items") or 0),
        "reports_generated": sum(int(r.get("n") or 0) for r in (g("reports_generated").get("rows") or [])),
        "directive_hits": g("directives").get("hits", 0),
        "health_score": g("health").get("health_score"),
    }


def main() -> int:
    import api_v2
    from db_adapter import _get_conn

    rollup = api_v2._system_rollup("24h")
    panels = rollup.get("panels") or {}
    hl = _headlines(panels)
    today = datetime.now(timezone.utc).date()

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO system_rollup_daily (day, payload) VALUES (%s, %s::jsonb)
           ON CONFLICT (day) DO UPDATE SET payload = EXCLUDED.payload, created_at = now()""",
        (today, json.dumps({"headlines": hl, "panels": panels}, default=str)))
    conn.commit()

    # deterministic markdown digest
    fails = [r for r in ((panels.get("pipelines") or {}).get("data") or {}).get("rows", [])
             if int(r.get("failures") or 0) > 0]
    lines = [
        f"# Daily System Digest — {today}",
        "",
        f"*Deterministic 24h rollup · generated {datetime.now(timezone.utc).isoformat()[:16]}Z · advisory only*",
        "",
        "## Headlines",
        f"- Pipelines: {hl['pipelines_run']} runs · {hl['pipeline_failures']} failures",
        f"- Agents: {hl['agent_analyses']} analyses",
        f"- Proposals: {hl['proposals']} created",
        f"- Paper trades closed: {hl['paper_closed']} · P&L ${hl['paper_pnl'] or 0}",
        f"- Alerts (raw events): {hl['alerts_raw']}",
        f"- Research items: {hl['research_items']} · Reports generated: {hl['reports_generated']}",
        f"- Directive hits: {hl['directive_hits']} · Health score: {hl['health_score']}",
        "",
    ]
    if fails:
        lines.append("## Pipeline failures (red rail)")
        for r in fails:
            lines.append(f"- {r.get('pipeline_key')}: {r.get('failures')} failed of {r.get('runs')}")
        lines.append("")
    lines.append("## Panel detail (corpus-tagged)")
    for name, p in panels.items():
        if name == "trends":
            continue
        lines.append(f"### {name} · corpus: {p.get('corpus')}")
        lines.append("```json")
        lines.append(json.dumps(p.get("data") if not p.get("error") else {"error": p["error"]},
                                indent=1, default=str)[:2000])
        lines.append("```")
    md = "\n".join(lines)

    out = ROOT / "data" / "portfolios" / "reports" / f"system_digest_{today}.md"
    out.write_text(md)

    cur.execute(
        """INSERT INTO ai_reports (report_type, title, content, provider, cost, generated_at)
           VALUES ('system_digest', %s, %s, 'deterministic', 0, now())""",
        (f"Daily System Digest — {today}", md))
    conn.commit()

    # refresh the catalog so the Library row appears without waiting for its cron
    try:
        from generate_reports_hub import build_report_catalog
        build_report_catalog(str(ROOT))
    except Exception as e:
        print(f"[system-digest] catalog refresh failed: {e}")

    one_liner = (f"System digest ready · {hl['pipelines_run']} pipelines · "
                 f"{hl['pipeline_failures']} failures · {hl['paper_closed']} trades closed · "
                 f"health {hl['health_score']} → Reports › Library")
    try:
        from telegram_alert import send_telegram
        send_telegram(one_liner, bypass_router=True)
    except Exception as e:
        print(f"[system-digest] telegram failed: {e}\n{one_liner}")
    print(f"[system-digest] wrote {out.name}, snapshot row {today}, ai_reports row; {one_liner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
