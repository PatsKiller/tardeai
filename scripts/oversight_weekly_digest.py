#!/usr/bin/env python3
"""oversight_weekly_digest.py — Defense v9 WS-E: Saturday 08:00, deterministic
assembly from stored reviews (NO new LLM calls). Report file + one Telegram line."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    from db_adapter import _get_conn
    import defense_adjudication as adj
    conn = _get_conn()
    cur = conn.cursor()
    adj.ensure_tables(cur)
    conn.commit()
    cur.execute("""SELECT seat, status, verdicts, memo, cost_est, created_at FROM oversight_reviews
                   WHERE created_at > now() - interval '7 days' ORDER BY created_at""")
    rows = cur.fetchall()
    from collections import Counter
    per_seat, objects, spend = {}, [], 0.0
    for seat, status, verdicts, memo, cost, at in rows:
        spend += float(cost or 0)
        if status != "ok":
            continue
        vs = verdicts if isinstance(verdicts, list) else json.loads(verdicts or "[]")
        c = Counter(v["verdict"] for v in vs)
        agg = per_seat.setdefault(seat, Counter())
        agg.update(c)
        for v in vs:
            if v["verdict"] == "OBJECT":
                objects.append((seat, v["id"], (v.get("reason") or "")[:110]))
    league = adj.seat_league(cur)
    console = adj.evaluate_console(cur)
    gov = adj.governance(cur)
    lines = [f"# Oversight Weekly — {datetime.now(timezone.utc).date()}", ""]
    lines.append(f"**Reviews this week:** {len(rows)} · spend ${spend:.2f}")
    lines.append("")
    for seat, c in per_seat.items():
        lines.append(f"- **{seat}**: {dict(c)}")
    lines.append("")
    lines.append(f"## OBJECTs ({len(objects)})")
    seen = set()
    for seat, cid, reason in objects:
        k = (seat, cid)
        if k in seen:
            continue
        seen.add(k)
        lines.append(f"- [{seat}] {cid}: {reason}")
    lines.append("")
    lines.append("## Seat league")
    for l in league:
        lines.append(f"- {l['seat']}: reviews {l['reviews']} · object-precision {l['object_precision']} · ${l['cost_usd']} · {l['note'] or 'RANKED'}")
    lines.append("")
    lines.append("## Promote console")
    lines.append(f"- criteria locked: {console['criteria_locked']} · review {console['review_window']}")
    for card in console["cards"]:
        lines.append(f"- {card['id']}: {card['verdict_preview']}")
    lines.append("")
    lines.append("## Directives")
    for g in gov:
        lines.append(f"- {g['directive']}: {g['status']}")
    md = "\n".join(lines)
    out = ROOT / "data" / "runtime" / f"oversight_weekly_{datetime.now(timezone.utc).date()}.md"
    out.write_text(md)
    print(f"[weekly-digest] {out.name} · {len(rows)} reviews · ${spend:.2f}")
    try:
        from telegram_alert import send_telegram
        red = sum(1 for card in console["cards"] if "NOT met" in card["verdict_preview"])
        send_telegram(f"[OPERATIONAL] Oversight Weekly: {len(rows)} reviews · ${spend:.2f} · "
                      f"{len(seen)} OBJECTs · console: {red} criteria red · report on the desk",
                      bypass_router=True)
    except Exception as e:
        print(f"[weekly-digest] telegram failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
