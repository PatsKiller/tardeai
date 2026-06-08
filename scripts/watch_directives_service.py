#!/usr/bin/env python3
"""watch_directives_service.py — wire operator Watch Directives into Trade AI + Hermes.

ADVISORY. For each ACTIVE directive: resolve to symbols (ticker→symbol; sector/trend→spec universe/seed),
record watch_directive_hits (surfaced_by='trade_ai') with current analyst divergence + GO/WAIT qualification,
and PROMOTE qualifying symbols into the watched universe (watchlist_items, origin_system='operator_directive',
directive_id, in_directive_watch) so Trade AI's news/analysis/scans cover them. Also DRAIN Hermes proposals
from hermes_directive_hits_staging → watch_directive_hits (surfaced_by='hermes') — the firewall: Hermes only
writes staging; this app-role service drains it. NEVER trades / changes GO-WAIT / scoring / stops.

  python3 scripts/watch_directives_service.py            # dry-run
  python3 scripts/watch_directives_service.py --apply
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILLS = ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2
import psycopg2.extras


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"), cursor_factory=psycopg2.extras.RealDictCursor)


def _pills():
    try:
        return {p["symbol"]: p for p in json.loads(PILLS.read_text()).get("pills", [])}
    except Exception:
        return {}


def _resolve(d):
    """Directive → candidate symbols. ticker: explicit. sector/trend: spec universe/seed_symbols (operator-listed)."""
    spec = d["spec"] if isinstance(d["spec"], dict) else json.loads(d["spec"])
    if d["kind"] == "ticker":
        s = spec.get("symbol")
        return [s.upper()] if s else []
    out = []
    for key in ("universe", "seed_symbols"):
        out += [str(x).upper() for x in (spec.get(key) or [])]
    return sorted(set(out))


def main():
    dry = "--apply" not in sys.argv
    pills = _pills()
    c = _db(); cur = c.cursor()
    cur.execute("SELECT * FROM watch_directives WHERE status='active'")
    directives = cur.fetchall()
    # today's GO/WAIT set (qualification)
    cur.execute("SELECT DISTINCT symbol FROM trade_ai_scans WHERE run_date>=current_date AND decision IN('GO','WAIT')")
    go_wait = {r["symbol"] for r in cur.fetchall()}

    def recent_hit(did, sym, by):
        cur.execute("""SELECT 1 FROM watch_directive_hits WHERE directive_id=%s AND symbol=%s AND surfaced_by=%s
                       AND surfaced_at > now()-interval '12 hours' LIMIT 1""", (did, sym, by))
        return cur.fetchone() is not None

    def promote(sym, did, reason):
        cur.execute("SELECT 1 FROM watchlist_items WHERE symbol=%s AND source='operator_directive' LIMIT 1", (sym,))
        if cur.fetchone():
            cur.execute("""UPDATE watchlist_items SET in_directive_watch=true, directive_id=%s, last_validated_at=now()
                           WHERE symbol=%s AND source='operator_directive'""", (did, sym))
            return "already_watched"
        cur.execute("""INSERT INTO watchlist_items (symbol, source, status, origin_system, directive_id,
                       in_directive_watch, source_tier, first_seen_at, provenance_reason, updated_at)
                       VALUES (%s,'operator_directive','active','operator_directive',%s,true,%s,now(),%s,now())""",
                    (sym, did, (pills.get(sym) or {}).get("recommendation_key"), reason))
        return "promoted_to_watchlist"

    def record_hit(did, sym, by, reason):
        p = pills.get(sym) or {}
        qualified = sym in go_wait
        pstatus = "PROMOTED" if qualified else "MONITORED_NO_QUALIFY"
        cur.execute("""INSERT INTO watch_directive_hits (directive_id, symbol, surfaced_by, source_tier,
                       hit_reason, divergence, promoted, promotion_status, surfaced_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                    (did, sym, by, p.get("recommendation_key"), reason, p.get("divergence"),
                     qualified, pstatus))
        return pstatus

    report = {"directives": len(directives), "ta_hits": 0, "hermes_drained": 0, "promoted": 0, "detail": []}
    for d in directives:
        did = d["id"]
        # ── Trade AI side ──
        if d["trade_ai_enabled"]:
            for sym in _resolve(d):
                if recent_hit(did, sym, "trade_ai"):
                    continue
                if not dry:
                    ps = record_hit(did, sym, "trade_ai", f"directive:{d['label']}")
                    pr = promote(sym, did, f"operator directive {d['label']}")
                    if pr == "promoted_to_watchlist":
                        report["promoted"] += 1
                report["ta_hits"] += 1
                report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "trade_ai"})
        # ── Hermes drain (firewall: app drains staging) ──
        if d["hermes_enabled"]:
            cur.execute("""SELECT * FROM hermes_directive_hits_staging WHERE drained=false AND directive_id=%s LIMIT 50""", (did,))
            for h in cur.fetchall():
                sym = (h["symbol"] or "").upper()
                if not sym:
                    continue
                if not dry:
                    record_hit(did, sym, "hermes", f"hermes:{(h.get('thesis') or '')[:60]}")
                    promote(sym, did, f"hermes lead for directive {d['label']}")
                    cur.execute("UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s", (h["id"],))
                report["hermes_drained"] += 1
                report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "hermes"})
        if not dry:
            cur.execute("UPDATE watch_directives SET last_serviced_at=now(), updated_at=now() WHERE id=%s", (did,))
    if not dry:
        c.commit()
    c.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
