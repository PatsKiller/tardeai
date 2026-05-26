# Source Export: scripts/weekly_learning_digest.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/weekly_learning_digest.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `501727d109da0af44c55540f57d78cea2f6a9b4d11736d3ee2310a80f8c1ec39` |
| **File Size** | 12843 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""weekly_learning_digest.py — Generate weekly learning digest from all subsystems.

Usage:
    .venv/bin/python scripts/weekly_learning_digest.py --current-week --dry-run --json
    .venv/bin/python scripts/weekly_learning_digest.py --current-week --apply --json
    .venv/bin/python scripts/weekly_learning_digest.py --latest --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="WLD_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def get_week_range(week_start=None):
    today = date.today()
    if week_start:
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
    else:
        start = today - timedelta(days=today.weekday() + 7)  # Last Monday
    end = start + timedelta(days=6)
    return start, end


def generate_digest(conn, period_start, period_end):
    cur = conn.cursor()
    digest_id = _uid()

    # Holdings
    try:
        h = json.load(open(PROJECT_ROOT / "data/portfolios/state/holdings.json"))
        holdings_val = h["portfolio_totals"]["total_value"]
    except Exception:
        holdings_val = 0

    # Paper trades
    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'")
    open_trades = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'")
    closed_trades = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FILTER (WHERE pnl>0), COUNT(*) FILTER (WHERE pnl<=0), COALESCE(SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END),0), COALESCE(SUM(CASE WHEN pnl<0 THEN ABS(pnl) ELSE 0 END),0) FROM paper_trades WHERE status='closed'")
    row = cur.fetchone()
    wins, losses = row[0], row[1]
    gp, gl = _f(row[2]), _f(row[3])
    wr = round(wins / max(wins + losses, 1), 4)
    pf = round(gp / max(gl, 0.01), 4)

    # Proposals
    cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at >= %s AND created_at <= %s", [str(period_start), str(period_end)])
    props_created = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paper_trade_proposals WHERE status IN ('APPROVED','APPROVED_FOR_PAPER_TEST') AND created_at >= %s AND created_at <= %s", [str(period_start), str(period_end)])
    props_approved = cur.fetchone()[0]

    # Thesis reviews
    thesis_items = []
    cur.execute("SELECT review_id, symbol, thesis_validity, thesis_score, lesson_summary FROM trade_thesis_reviews ORDER BY created_at DESC LIMIT 10")
    for r in cur.fetchall():
        thesis_items.append({"review_id": r[0], "symbol": r[1], "validity": r[2], "score": _f(r[3]), "lesson": r[4]})

    # Agent calibration
    agent_summary = {}
    cur.execute("SELECT agent_name, resolved, accuracy, calibration_error, sample_size_status FROM agent_calibration_windows ORDER BY created_at DESC LIMIT 10")
    for r in cur.fetchall():
        agent_summary[r[0]] = {"resolved": r[1], "accuracy": _f(r[2]), "cal_error": _f(r[3]), "tier": r[4]}

    # Source scores
    source_summary = {}
    cur.execute("SELECT source_key, usefulness_score, reliability_score, recommendation FROM source_learning_scores ORDER BY created_at DESC LIMIT 20")
    for r in cur.fetchall():
        source_summary[r[0]] = {"usefulness": _f(r[1]), "reliability": _f(r[2]), "rec": r[3]}

    # Strategy scores
    strategy_summary = {}
    cur.execute("SELECT strategy_id, closed_trades, win_rate, profit_factor, recommendation FROM strategy_learning_scores ORDER BY created_at DESC LIMIT 10")
    for r in cur.fetchall():
        strategy_summary[r[0]] = {"closed": r[1], "wr": _f(r[2]), "pf": _f(r[3]), "rec": r[4]}

    # Learning recommendations pending
    cur.execute("SELECT recommendation_id, title, domain, status FROM learning_recommendations WHERE status='proposed' ORDER BY created_at DESC LIMIT 10")
    pending_recs = [{"id": r[0], "title": r[1], "domain": r[2]} for r in cur.fetchall()]

    # Config proposals pending
    cur.execute("SELECT proposal_id, domain, target_key, status FROM config_change_proposals WHERE status='proposed' ORDER BY created_at DESC LIMIT 10")
    pending_props = [{"id": r[0], "domain": r[1], "target": r[2]} for r in cur.fetchall()]

    # Pipeline health
    cur.execute("SELECT status, COUNT(*) FROM pipeline_runs GROUP BY status ORDER BY 2 DESC")
    pipeline = {r[0]: r[1] for r in cur.fetchall()}

    # Top lessons
    lessons = []
    if thesis_items:
        lessons.extend([f"Trade {t['symbol']}: {t['lesson'][:80]}" for t in thesis_items[:3]])
    if pending_recs:
        lessons.append(f"{len(pending_recs)} learning recommendations pending review")
    if pending_props:
        lessons.append(f"{len(pending_props)} config proposals pending approval")

    # Human review items
    review_items = []
    if pending_recs:
        review_items.extend([{"type": "learning_recommendation", "title": r["title"]} for r in pending_recs])
    if pending_props:
        review_items.extend([{"type": "config_proposal", "title": f"{p['domain']}/{p['target']}"} for p in pending_props])

    low_sample = closed_trades < 30

    # Generate markdown
    md = _generate_markdown(period_start, period_end, holdings_val, open_trades, closed_trades,
                            wr, pf, lessons, thesis_items, agent_summary, source_summary,
                            strategy_summary, pending_recs, pending_props, low_sample, pipeline)

    return {
        "digest_id": digest_id,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "holdings_value": holdings_val,
        "paper_trades_open": open_trades,
        "paper_trades_closed": closed_trades,
        "proposals_created": props_created,
        "proposals_approved": props_approved,
        "win_rate": wr,
        "profit_factor": pf,
        "low_sample_size": low_sample,
        "top_lessons": lessons,
        "risk_alerts": [],
        "agent_summary": agent_summary,
        "source_summary": source_summary,
        "strategy_summary": strategy_summary,
        "thesis_summary": {"reviews": thesis_items},
        "recommendations": [r["title"] for r in pending_recs],
        "human_review_items": review_items,
        "digest_markdown": md,
    }


def _generate_markdown(start, end, holdings, open_t, closed_t, wr, pf,
                       lessons, thesis, agents, sources, strategies,
                       recs, props, low_sample, pipeline):
    lines = [
        f"# Weekly Learning Digest: {start} — {end}",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"\n## Safety Status",
        f"- Mode: PAPER ONLY",
        f"- Holdings: ${holdings:,.0f}",
        f"- Live Trading: BLOCKED",
        f"\n## Paper Trading Summary",
        f"- Open trades: {open_t}",
        f"- Closed trades: {closed_t}",
        f"- Win rate: {wr:.0%}" if wr else "- Win rate: N/A",
        f"- Profit factor: {pf:.2f}" if pf else "- Profit factor: N/A",
    ]
    if low_sample:
        lines.append(f"- **LOW SAMPLE SIZE**: {closed_t} closed trades (need 30+ for insights)")

    if lessons:
        lines.append(f"\n## Top Lessons")
        for l in lessons[:5]:
            lines.append(f"- {l}")

    if thesis:
        lines.append(f"\n## Thesis Reviews ({len(thesis)})")
        for t in thesis[:5]:
            lines.append(f"- {t['symbol']}: {t['validity']} (score={t['score']})")

    if agents:
        lines.append(f"\n## Agent Calibration")
        for name, data in agents.items():
            acc = f"{data['accuracy']:.0%}" if data.get('accuracy') else "?"
            lines.append(f"- {name}: resolved={data.get('resolved',0)}, acc={acc}, tier={data.get('tier','?')}")

    if recs:
        lines.append(f"\n## Pending Learning Recommendations ({len(recs)})")
        for r in recs[:5]:
            lines.append(f"- [{r['domain']}] {r['title']}")

    if props:
        lines.append(f"\n## Pending Config Proposals ({len(props)})")
        for p in props[:5]:
            lines.append(f"- [{p['domain']}] {p['target']}")

    lines.append(f"\n## What Not to Act On Yet")
    lines.append("- All findings are low sample size until 30+ closed paper trades")
    lines.append("- No config changes should be made based on 3 closed trades")

    return "\n".join(lines)


def save_digest(conn, digest, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO weekly_learning_digests
            (digest_id, period_start, period_end, status, holdings_value,
             paper_trades_open, paper_trades_closed, proposals_created, proposals_approved,
             win_rate, profit_factor, low_sample_size, top_lessons, agent_summary,
             source_summary, strategy_summary, thesis_summary, recommendations,
             human_review_items, digest_markdown, digest_payload)
        VALUES (%s,%s,%s,'generated',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (digest_id) DO NOTHING
    """, [digest["digest_id"], digest["period_start"], digest["period_end"],
          digest["holdings_value"], digest["paper_trades_open"], digest["paper_trades_closed"],
          digest["proposals_created"], digest["proposals_approved"],
          digest["win_rate"], digest["profit_factor"], digest["low_sample_size"],
          json.dumps(digest["top_lessons"], default=str),
          json.dumps(digest["agent_summary"], default=str),
          json.dumps(digest["source_summary"], default=str),
          json.dumps(digest["strategy_summary"], default=str),
          json.dumps(digest["thesis_summary"], default=str),
          json.dumps(digest["recommendations"], default=str),
          json.dumps(digest["human_review_items"], default=str),
          digest["digest_markdown"],
          json.dumps({k: v for k, v in digest.items() if k != "digest_markdown"}, default=str)])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Weekly Learning Digest")
    parser.add_argument("--current-week", action="store_true")
    parser.add_argument("--week-start")
    parser.add_argument("--week-end")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--send-telegram")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        if args.latest:
            cur = conn.cursor()
            cur.execute("SELECT digest_id, period_start, period_end, status, digest_markdown FROM weekly_learning_digests ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                out = {"digest_id": row[0], "period": f"{row[1]}—{row[2]}", "status": row[3]}
                if args.json:
                    print(json.dumps(out, indent=2, default=str))
                else:
                    print(row[4] or "No markdown content")
            else:
                print(json.dumps({"message": "No digests yet"}) if args.json else "No digests generated yet.")
            return

        start, end = get_week_range(args.week_start)
        digest = generate_digest(conn, start, end)
        if not dry_run:
            save_digest(conn, digest)
            # Write markdown file
            md_path = PROJECT_ROOT / "docs" / "project" / f"WEEKLY_LEARNING_DIGEST_{start.strftime('%Y%m%d')}.md"
            md_path.write_text(digest["digest_markdown"])

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "digest_id": digest["digest_id"],
            "period": f"{start}—{end}",
            "closed_trades": digest["paper_trades_closed"],
            "win_rate": digest["win_rate"],
            "low_sample": digest["low_sample_size"],
            "lessons": len(digest["top_lessons"]),
            "review_items": len(digest["human_review_items"]),
        }
        if args.json:
            out["digest"] = {k: v for k, v in digest.items() if k != "digest_markdown"}
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Digest: {out['period']} ({out['mode']}), {out['closed_trades']} closed, "
                  f"{out['lessons']} lessons, {out['review_items']} review items")
            if digest["low_sample_size"]:
                print("  WARNING: Low sample size — do not act on findings yet")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
```
