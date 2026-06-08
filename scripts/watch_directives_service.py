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
sys.path.insert(0, str(ROOT / "scripts"))
import directive_promotion as dp  # the real evaluation engine (governor → classify Bucket 2/3 → watchpool)


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

    def recent_hit(did, sym, by):
        cur.execute("""SELECT 1 FROM watch_directive_hits WHERE directive_id=%s AND symbol=%s AND surfaced_by=%s
                       AND surfaced_at > now()-interval '12 hours' LIMIT 1""", (did, sym, by))
        return cur.fetchone() is not None

    def evaluate(sym, did, reason, source_system, auto):
        # RECONCILED: route through the REAL evaluation engine instead of a flat watchlist add.
        # promote_directive_lead = governor (tier+divergence) → register provenance → enrich-on-demand
        # → classify (Bucket 2/3 ONLY; momentum_scalp/gap_and_go/SAME_DAY excluded) → watchpool. It
        # records the watch_directive_hit itself and runs under its own app-role connection.
        try:
            return dp.promote_directive_lead(sym, did, reason, source_system, auto=auto)
        except Exception as e:
            return {"status": "ERROR", "error": str(e)[:140]}

    report = {"directives": len(directives), "ta_hits": 0, "hermes_drained": 0,
              "promoted": 0, "staged": 0, "detail": []}
    for d in directives:
        did = d["id"]
        # ── Trade AI side: resolve the directive's own symbols ──
        if d["trade_ai_enabled"]:
            # ticker = operator named the exact symbol → auto (real eval; scalp firewall still applies).
            # sector/trend surfaced symbols → governor decides (typically STAGE for one-tap).
            is_ticker = d["kind"] == "ticker"
            src = "operator" if is_ticker else "trade_ai"  # surfaced_by my engine will record
            for sym in _resolve(d):
                if recent_hit(did, sym, src):   # dedup on the same surfaced_by (was 'trade_ai' only — bug)
                    continue
                if not dry:
                    res = evaluate(sym, did, f"directive:{d['label']}", src,
                                   True if is_ticker else None)
                    st = res.get("status")
                    report["promoted"] += 1 if st == "PROMOTED" else 0
                    report["staged"] += 1 if st == "STAGED_FOR_REVIEW" else 0
                    report["detail"].append({"directive": d["label"], "symbol": sym,
                                             "surfaced_by": "trade_ai", "status": st})
                else:
                    report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "trade_ai"})
                report["ta_hits"] += 1
        # ── Hermes drain (firewall: app drains staging, then evaluates under app role) ──
        if d["hermes_enabled"]:
            cur.execute("""SELECT * FROM hermes_directive_hits_staging WHERE drained=false AND directive_id=%s LIMIT 50""", (did,))
            for h in cur.fetchall():
                sym = (h["symbol"] or "").upper()
                if not sym:
                    continue
                if not dry:
                    res = evaluate(sym, did, f"hermes:{(h.get('thesis') or '')[:60]}", "hermes", None)
                    st = res.get("status")
                    report["promoted"] += 1 if st == "PROMOTED" else 0
                    report["staged"] += 1 if st == "STAGED_FOR_REVIEW" else 0
                    cur.execute("UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s", (h["id"],))
                    report["detail"].append({"directive": d["label"], "symbol": sym,
                                             "surfaced_by": "hermes", "status": st})
                else:
                    report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "hermes"})
                report["hermes_drained"] += 1
        if not dry:
            cur.execute("UPDATE watch_directives SET last_serviced_at=now(), updated_at=now() WHERE id=%s", (did,))
    if not dry:
        c.commit()
    c.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
